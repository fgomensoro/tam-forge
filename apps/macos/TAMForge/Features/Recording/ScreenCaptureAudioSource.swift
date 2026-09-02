import AVFoundation
import CoreMedia
import Foundation
import ScreenCaptureKit

actor ScreenCaptureAudioSource: RecordingCaptureSource {
    private var stream: SCStream?
    private var output: ScreenCaptureAudioOutput?
    private var delegate: ScreenCaptureStreamDelegate?

    func start(
        microphoneID: String?,
        initialRoute: String,
        receive: @escaping @Sendable (RecordingCaptureEvent) -> Void
    ) async throws {
        guard stream == nil else { return }
        let content = try await SCShareableContent.excludingDesktopWindows(
            false, onScreenWindowsOnly: false
        )
        guard let display = content.displays.first else {
            throw RecordingCaptureFailure.sourceUnavailable
        }
        let filter = SCContentFilter(display: display, excludingWindows: [])
        let configuration = SCStreamConfiguration()
        configuration.capturesAudio = true
        configuration.excludesCurrentProcessAudio = false
        configuration.sampleRate = RecordingPCMFormat.canonicalSampleRate
        configuration.channelCount = 2
        configuration.captureMicrophone = true
        configuration.microphoneCaptureDeviceID = microphoneID
        configuration.queueDepth = 1
        configuration.width = 2
        configuration.height = 2
        configuration.minimumFrameInterval = CMTime(value: 1, timescale: 1)
        configuration.showsCursor = false

        let delegate = ScreenCaptureStreamDelegate(receive: receive)
        let output = ScreenCaptureAudioOutput(
            microphoneID: microphoneID ?? "system-default-microphone",
            initialRoute: initialRoute,
            receive: receive
        )
        let stream = SCStream(filter: filter, configuration: configuration, delegate: delegate)
        do {
            try stream.addStreamOutput(
                output, type: .audio, sampleHandlerQueue: output.callbackQueue
            )
            try stream.addStreamOutput(
                output, type: .microphone, sampleHandlerQueue: output.callbackQueue
            )
            try await stream.startCapture()
        } catch {
            receive(.failure(.sourceUnavailable))
            throw error
        }
        self.delegate = delegate
        self.output = output
        self.stream = stream
    }

    func stop() async throws {
        guard let stream else { return }
        let output = self.output
        do {
            try await stream.stopCapture()
        } catch {
            await output?.finish()
            self.stream = nil
            self.output = nil
            delegate = nil
            throw error
        }
        await output?.finish()
        self.stream = nil
        self.output = nil
        delegate = nil
    }
}

private final class ScreenCaptureStreamDelegate: NSObject, SCStreamDelegate, @unchecked Sendable {
    private let receive: @Sendable (RecordingCaptureEvent) -> Void

    init(receive: @escaping @Sendable (RecordingCaptureEvent) -> Void) {
        self.receive = receive
    }

    func stream(_ stream: SCStream, didStopWithError error: any Error) {
        receive(.failure(.streamStopped))
    }
}

private final class ScreenCaptureAudioOutput: NSObject, SCStreamOutput, @unchecked Sendable {
    let callbackQueue = DispatchQueue(
        label: "com.fgomensoro.tamforge.recording.callback",
        qos: .userInteractive
    )
    private let processingQueue = DispatchQueue(
        label: "com.fgomensoro.tamforge.recording.processing",
        qos: .userInitiated
    )
    private let handoff = BoundedCaptureHandoffQueue(capacity: 16)
    private let microphoneID: String
    private let initialRoute: String
    private let receive: @Sendable (RecordingCaptureEvent) -> Void
    private var pipeline = RecordingCapturePipeline()

    init(
        microphoneID: String,
        initialRoute: String,
        receive: @escaping @Sendable (RecordingCaptureEvent) -> Void
    ) {
        self.microphoneID = microphoneID
        self.initialRoute = initialRoute
        self.receive = receive
    }

    func stream(
        _ stream: SCStream,
        didOutputSampleBuffer sampleBuffer: CMSampleBuffer,
        of type: SCStreamOutputType
    ) {
        let track: RecordingTrackKind
        switch type {
        case .audio:
            track = .systemAudio
        case .microphone:
            track = .microphone
        default:
            return
        }
        guard sampleBuffer.isValid, sampleBuffer.dataReadiness == .ready else { return }
        let retained = RetainedAudioSample(track: track, sampleBuffer: sampleBuffer)
        switch handoff.offer(retained) {
        case .accepted:
            scheduleHandoffDrain()
        case .full:
            guard let dropped = RecordingDroppedSourceRange(
                sampleBuffer: sampleBuffer, track: track
            ) else {
                receive(.failure(.conversionFailed))
                return
            }
            guard handoff.record(dropped: dropped) else { return }
            scheduleHandoffDrain()
            receive(.failure(.callbackOverflow))
        case .closed:
            return
        }
    }

    private func scheduleHandoffDrain() {
        guard handoff.scheduleDrainIfNeeded() else { return }
        processingQueue.async { [weak self] in self?.drainHandoff() }
    }

    // The callback-queue close is the acceptance boundary. Holding self strongly
    // keeps that fixed accepted prefix alive through conversion and final flush.
    func finish() async {
        await withCheckedContinuation { continuation in
            callbackQueue.async { [handoff] in
                handoff.close()
                continuation.resume()
            }
        }
        await withCheckedContinuation { continuation in
            processingQueue.async { [self] in
                drainHandoff()
                for event in pipeline.finish() { receive(event) }
                continuation.resume()
            }
        }
    }

    private func drainHandoff() {
        while let batch = handoff.takeDrainBatch() {
            for item in batch {
                do {
                    switch item {
                    case let .retained(sample):
                        let converted = try convert(sample)
                        for event in try pipeline.accept(
                            converted,
                            normalizedLevel: converted.payload.normalizedPCM16Level
                        ) { receive(event) }
                    case let .dropped(range):
                        for event in try pipeline.acceptDroppedSourceInterval(
                            range, reason: .callbackOverflow
                        ) { receive(event) }
                    }
                } catch let failure as RecordingCaptureFailure {
                    emitFailure(for: item, failure: failure)
                } catch {
                    emitFailure(for: item, failure: .conversionFailed)
                }
            }
        }
    }

    private func emitFailure(for item: CaptureHandoff, failure: RecordingCaptureFailure) {
        guard case let .retained(sample) = item,
              let interval = RecordingDroppedSourceInterval(
                sampleBuffer: sample.sampleBuffer, track: sample.track
              )
        else {
            receive(.failure(failure))
            return
        }
        let reason: RecordingGapReason = failure == .formatUnsupported
            ? .formatChange
            : .missingAudio
        do {
            for event in try pipeline.acceptFailure(
                droppedSourceInterval: interval,
                reason: reason,
                failure: failure
            ) { receive(event) }
        } catch {
            receive(.failure(failure))
        }
    }

    private func convert(_ sample: RetainedAudioSample) throws -> RecordingPCMChunk {
        guard let description = sample.sampleBuffer.formatDescription,
              let streamDescription = CMAudioFormatDescriptionGetStreamBasicDescription(description)
        else { throw RecordingCaptureFailure.formatUnsupported }
        guard let sourceFormat = AVAudioFormat(streamDescription: streamDescription) else {
            throw RecordingCaptureFailure.formatUnsupported
        }
        let frameCount = AVAudioFrameCount(sample.sampleBuffer.numSamples)
        guard frameCount > 0 else { throw RecordingCaptureFailure.formatUnsupported }
        // ScreenCaptureKit vends audio as an AudioBufferList-backed block
        // buffer; CMSampleBufferCopyPCMDataIntoAudioBufferList rejects those
        // buffers (kCMSampleBufferError_ArrayTooSmall), so wrap the list in
        // place and convert before the block buffer goes away.
        return try sample.sampleBuffer.withAudioBufferList { audioBufferList, _ in
            guard let sourceBuffer = AVAudioPCMBuffer(
                pcmFormat: sourceFormat,
                bufferListNoCopy: UnsafePointer(audioBufferList.unsafeMutablePointer)
            ), sourceBuffer.frameLength >= frameCount
            else { throw RecordingCaptureFailure.conversionFailed }
            sourceBuffer.frameLength = frameCount

            let channelCount: AVAudioChannelCount = sample.track == .microphone ? 1 : 2
            guard let targetFormat = AVAudioFormat(
                commonFormat: .pcmFormatInt16,
                sampleRate: Double(RecordingPCMFormat.canonicalSampleRate),
                channels: channelCount,
                interleaved: true
            ), let converter = AVAudioConverter(from: sourceFormat, to: targetFormat)
            else { throw RecordingCaptureFailure.formatUnsupported }
            let ratio = Double(RecordingPCMFormat.canonicalSampleRate) / sourceFormat.sampleRate
            let capacity = AVAudioFrameCount((Double(frameCount) * ratio).rounded(.up)) + 32
            guard let output = AVAudioPCMBuffer(
                pcmFormat: targetFormat, frameCapacity: capacity
            ) else {
                throw RecordingCaptureFailure.conversionFailed
            }
            var supplied = false
            var conversionError: NSError?
            let status = converter.convert(to: output, error: &conversionError) { _, inputStatus in
                guard !supplied else {
                    inputStatus.pointee = AVAudioConverterInputStatus.noDataNow
                    return nil
                }
                supplied = true
                inputStatus.pointee = AVAudioConverterInputStatus.haveData
                return sourceBuffer
            }
            guard status != AVAudioConverterOutputStatus.error,
                  conversionError == nil,
                  output.frameLength > 0
            else {
                throw RecordingCaptureFailure.conversionFailed
            }
            let buffer = output.audioBufferList.pointee.mBuffers
            guard let pointer = buffer.mData else { throw RecordingCaptureFailure.conversionFailed }
            let payload = Data(bytes: pointer, count: Int(buffer.mDataByteSize))
            let presentation = sample.sampleBuffer.presentationTimeStamp.convertedNanoseconds
            let sourceChannels = Int(streamDescription.pointee.mChannelsPerFrame)
            let format = try RecordingPCMFormat(
                track: sample.track, channelCount: Int(channelCount)
            )
            return RecordingPCMChunk(
                track: sample.track,
                presentationNanoseconds: presentation,
                sampleStart: 0,
                sampleCount: Int(output.frameLength),
                format: format,
                source: .init(
                    sampleRate: sourceFormat.sampleRate,
                    channelCount: sourceChannels,
                    deviceID: sample.track == .microphone ? microphoneID : "system-audio",
                    initialRoute: sample.track == .microphone
                        ? initialRoute
                        : "ScreenCaptureKit authorized system mix",
                    conversionVersion: 1,
                    presentationNanoseconds: presentation
                ),
                payload: payload
            )
        }
    }
}

final class RetainedAudioSample: @unchecked Sendable {
    let track: RecordingTrackKind
    let sampleBuffer: CMSampleBuffer

    init(track: RecordingTrackKind, sampleBuffer: CMSampleBuffer) {
        self.track = track
        self.sampleBuffer = sampleBuffer
    }
}

enum CaptureHandoff: Sendable {
    case retained(RetainedAudioSample)
    case dropped(RecordingDroppedSourceInterval)
}

enum CaptureHandoffOfferResult: Equatable, Sendable {
    case accepted
    case full
    case closed
}

final class BoundedCaptureHandoffQueue: @unchecked Sendable {
    private let lock = NSLock()
    private let capacity: Int
    private var retained: [RetainedAudioSample] = []
    private var droppedByTrack: [RecordingTrackKind: RecordingDroppedSourceInterval] = [:]
    private var drainScheduled = false
    private var closed = false

    init(capacity: Int) {
        precondition(capacity > 0)
        self.capacity = capacity
        retained.reserveCapacity(capacity)
    }

    func offer(_ sample: RetainedAudioSample) -> CaptureHandoffOfferResult {
        lock.lock()
        defer { lock.unlock() }
        guard !closed else { return .closed }
        guard retained.count < capacity else { return .full }
        retained.append(sample)
        return .accepted
    }

    func close() {
        lock.lock()
        closed = true
        lock.unlock()
    }

    var isClosed: Bool {
        lock.lock()
        defer { lock.unlock() }
        return closed
    }

    // At most one metadata-only interval survives per track, independent of source rate.
    @discardableResult
    func record(dropped range: RecordingDroppedSourceRange) -> Bool {
        guard let interval = RecordingDroppedSourceInterval(range: range) else { return false }
        lock.lock()
        defer { lock.unlock() }
        guard !closed else { return false }
        droppedByTrack[interval.track] = droppedByTrack[interval.track]
            .map { $0.merged(with: interval) } ?? interval
        return true
    }

    // At most one processing block is queued while capture callbacks keep arriving.
    func scheduleDrainIfNeeded() -> Bool {
        lock.lock()
        defer { lock.unlock() }
        guard !closed else { return false }
        guard !drainScheduled else { return false }
        drainScheduled = true
        return true
    }

    var isDrainScheduled: Bool {
        lock.lock()
        defer { lock.unlock() }
        return drainScheduled
    }

    // Keeps the worker registered while it processes batches. It clears the
    // schedule atomically only after observing the queue empty.
    func takeDrainBatch() -> [CaptureHandoff]? {
        lock.lock()
        defer { lock.unlock() }
        guard !retained.isEmpty || !droppedByTrack.isEmpty else {
            drainScheduled = false
            return nil
        }
        let samples = retained.map(CaptureHandoff.retained)
        let dropped = droppedByTrack.values
            .sorted { $0.startPresentationNanoseconds < $1.startPresentationNanoseconds }
            .map(CaptureHandoff.dropped)
        retained.removeAll(keepingCapacity: true)
        droppedByTrack.removeAll(keepingCapacity: true)
        return samples + dropped
    }
}

private extension RecordingDroppedSourceRange {
    init?(sampleBuffer: CMSampleBuffer, track: RecordingTrackKind) {
        guard let description = sampleBuffer.formatDescription,
              let streamDescription = CMAudioFormatDescriptionGetStreamBasicDescription(description),
              sampleBuffer.numSamples > 0
        else { return nil }
        let sampleRate = Int(streamDescription.pointee.mSampleRate.rounded())
        guard sampleRate > 0 else { return nil }
        self.init(
            track: track,
            presentationNanoseconds: sampleBuffer.presentationTimeStamp.convertedNanoseconds,
            sourceSampleCount: sampleBuffer.numSamples,
            sourceSampleRate: sampleRate
        )
    }
}

private extension RecordingDroppedSourceInterval {
    init?(sampleBuffer: CMSampleBuffer, track: RecordingTrackKind) {
        if let range = RecordingDroppedSourceRange(sampleBuffer: sampleBuffer, track: track),
           let interval = RecordingDroppedSourceInterval(range: range) {
            self = interval
            return
        }
        let duration = sampleBuffer.duration
        guard sampleBuffer.numSamples > 0,
              duration.isValid,
              duration.isNumeric,
              duration.value > 0
        else { return nil }
        let start = sampleBuffer.presentationTimeStamp.convertedNanoseconds
        let (end, overflow) = start.addingReportingOverflow(duration.convertedNanoseconds)
        guard !overflow, end > start else { return nil }
        self.init(
            track: track,
            startPresentationNanoseconds: start,
            endPresentationNanoseconds: end
        )
    }
}

private extension CMTime {
    var convertedNanoseconds: Int64 {
        CMTimeConvertScale(self, timescale: 1_000_000_000, method: .roundTowardZero).value
    }
}

private extension Data {
    var normalizedPCM16Level: Double {
        withUnsafeBytes { (raw: UnsafeRawBufferPointer) -> Double in
            let samples = raw.bindMemory(to: Int16.self)
            guard !samples.isEmpty else { return 0 }
            var peak: Int32 = 0
            let stride = Swift.max(1, samples.count / 2_048)
            var index = 0
            while index < samples.count {
                peak = Swift.max(peak, abs(Int32(samples[index])))
                index += stride
            }
            return Swift.min(1, Double(peak) / Double(Int16.max))
        }
    }
}
