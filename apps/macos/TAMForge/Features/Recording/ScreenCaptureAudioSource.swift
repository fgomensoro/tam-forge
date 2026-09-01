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
        do {
            try await stream.stopCapture()
        } catch {
            self.stream = nil
            output = nil
            delegate = nil
            throw error
        }
        self.stream = nil
        output = nil
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
    private var timeline = RecordingTimelineAssembler()

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
        guard handoff.offer(retained) else {
            guard let dropped = RecordingDroppedSourceRange(
                sampleBuffer: sampleBuffer, track: track
            ) else {
                receive(.failure(.conversionFailed))
                return
            }
            handoff.record(dropped: dropped)
            scheduleHandoffDrain()
            receive(.failure(.callbackOverflow))
            return
        }
        scheduleHandoffDrain()
    }

    private func scheduleHandoffDrain() {
        guard handoff.scheduleDrainIfNeeded() else { return }
        processingQueue.async { [weak self] in self?.drainHandoff() }
    }

    private func drainHandoff() {
        while let batch = handoff.takeDrainBatch() {
            for item in batch {
                do {
                    switch item {
                    case let .retained(sample):
                        let converted = try convert(sample)
                        let accepted = try timeline.accept(converted)
                        if let gap = accepted.gap { receive(.gap(gap)) }
                        for chunk in accepted.chunk.oneSecondChunks() {
                            receive(.chunk(chunk))
                        }
                        receive(.level(
                            track: sample.track,
                            normalized: accepted.chunk.payload.normalizedPCM16Level
                        ))
                    case let .dropped(range):
                        for gap in try timeline.accept(droppedSourceInterval: range) { receive(.gap(gap)) }
                    }
                } catch let failure as RecordingCaptureFailure {
                    receive(.failure(failure))
                } catch {
                    receive(.failure(.conversionFailed))
                }
            }
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
        guard frameCount > 0,
              let sourceBuffer = AVAudioPCMBuffer(
                  pcmFormat: sourceFormat, frameCapacity: frameCount
              )
        else { throw RecordingCaptureFailure.formatUnsupported }
        let copyStatus = CMSampleBufferCopyPCMDataIntoAudioBufferList(
            sample.sampleBuffer,
            at: 0,
            frameCount: Int32(frameCount),
            into: sourceBuffer.mutableAudioBufferList
        )
        guard copyStatus == noErr else { throw RecordingCaptureFailure.conversionFailed }
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
        guard let output = AVAudioPCMBuffer(pcmFormat: targetFormat, frameCapacity: capacity) else {
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
        return .init(
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

final class BoundedCaptureHandoffQueue: @unchecked Sendable {
    private let lock = NSLock()
    private let capacity: Int
    private var retained: [RetainedAudioSample] = []
    private var droppedByTrack: [RecordingTrackKind: RecordingDroppedSourceInterval] = [:]
    private var drainScheduled = false

    init(capacity: Int) {
        precondition(capacity > 0)
        self.capacity = capacity
        retained.reserveCapacity(capacity)
    }

    func offer(_ sample: RetainedAudioSample) -> Bool {
        lock.lock()
        defer { lock.unlock() }
        guard retained.count < capacity else { return false }
        retained.append(sample)
        return true
    }

    // At most one metadata-only interval survives per track, independent of source rate.
    func record(dropped range: RecordingDroppedSourceRange) {
        guard let interval = RecordingDroppedSourceInterval(range: range) else { return }
        lock.lock()
        defer { lock.unlock() }
        droppedByTrack[interval.track] = droppedByTrack[interval.track]
            .map { $0.merged(with: interval) } ?? interval
    }

    // At most one processing block is queued while capture callbacks keep arriving.
    func scheduleDrainIfNeeded() -> Bool {
        lock.lock()
        defer { lock.unlock() }
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

private extension CMTime {
    var convertedNanoseconds: Int64 {
        CMTimeConvertScale(self, timescale: 1_000_000_000, method: .roundTowardZero).value
    }
}

private extension RecordingPCMChunk {
    func oneSecondChunks() -> [RecordingPCMChunk] {
        guard sampleCount > RecordingPCMFormat.canonicalSampleRate else { return [self] }
        let bytesPerFrame = format.channelCount * RecordingPCMFormat.bytesPerSample
        var result: [RecordingPCMChunk] = []
        var consumed = 0
        while consumed < sampleCount {
            let count = min(RecordingPCMFormat.canonicalSampleRate, sampleCount - consumed)
            let byteStart = consumed * bytesPerFrame
            let byteEnd = byteStart + count * bytesPerFrame
            result.append(.init(
                track: track,
                presentationNanoseconds: presentationNanoseconds
                    + Int64(consumed) * 1_000_000_000
                    / Int64(RecordingPCMFormat.canonicalSampleRate),
                sampleStart: sampleStart + Int64(consumed),
                sampleCount: count,
                format: format,
                source: source,
                payload: payload.subdata(in: byteStart..<byteEnd)
            ))
            consumed += count
        }
        return result
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
