import AVFoundation
import CryptoKit
import Foundation
import XCTest

// Two halves. The verdict arithmetic (percentile, slope, gates, JSON shape)
// runs in every CI job. The measured run is opt-in: it needs the pinned
// whisper model (`make whisper-models`) and TAMFORGE_PERF_MINUTES, records
// a two-track recording of that many minutes of synthetic audio through
// the real encrypted spool, transcribes it with the real engine, proves one
// job at a time, releases, and writes the evidence artifact to
// TAMFORGE_PERF_OUTPUT. No `@testable import TAMForge`: this target
// compiles the Speech and Recording sources directly.
final class SpeechPerformanceHarnessTests: XCTestCase {
    private let mib = SpeechPerformanceGates.mebibyte

    // MARK: - Verdict arithmetic (always runs)

    func testFlatFootprintHasNoSlopeAndP95IsTheSeriesItself() {
        let samples = (0..<20).map { MemorySample(audioSeconds: Double($0 * 30), footprintBytes: 200 * mib) }
        let analysis = MemoryGrowthAnalysis(baselineBytes: 150 * mib, samples: samples)

        XCTAssertEqual(analysis.slopeBytesPerAudioMinute, 0)
        XCTAssertEqual(analysis.p95Bytes, 200 * mib)
        XCTAssertEqual(analysis.peakBytes, 200 * mib)
        XCTAssertFalse(analysis.exceedsGrowth(.initial))
    }

    func testDurationLinkedGrowthIsFlaggedEvenWhenEverySampleIsUnderTheP95Gate() {
        // One mebibyte per audio minute: far below the 300 MiB gate for an hour,
        // and exactly the kind of leak the slope exists to catch.
        let samples = (0...60).map { minute in
            MemorySample(audioSeconds: Double(minute * 60), footprintBytes: 150 * mib + UInt64(minute) * mib)
        }
        let analysis = MemoryGrowthAnalysis(baselineBytes: 150 * mib, samples: samples)

        XCTAssertEqual(analysis.slopeBytesPerAudioMinute, Double(mib), accuracy: 1)
        XCTAssertLessThanOrEqual(analysis.p95Bytes, SpeechPerformanceGates.initial.recordingP95Bytes)
        XCTAssertTrue(analysis.exceedsGrowth(.initial))
    }

    func testJitterAroundAFlatLineStaysUnderTheGrowthGate() {
        let samples = (0...120).map { index in
            let jitter = UInt64((index % 5) * 3) * mib
            return MemorySample(audioSeconds: Double(index * 30), footprintBytes: 180 * mib + jitter)
        }
        let analysis = MemoryGrowthAnalysis(baselineBytes: 150 * mib, samples: samples)

        XCTAssertFalse(analysis.exceedsGrowth(.initial))
    }

    func testP95IsNearestRankNotTheMaximum() {
        let ascending: [UInt64] = (1...100).map { UInt64($0) }
        XCTAssertEqual(MemoryGrowthAnalysis.percentile95(ascending), 95)
        XCTAssertNil(MemoryGrowthAnalysis.percentile95([]))
        XCTAssertEqual(MemoryGrowthAnalysis.percentile95([7]), 7)
    }

    func testOneJobIsOnlyProvenByASerializedPair() {
        XCTAssertTrue(OneJobObservation(soloSeconds: 10, concurrentPairSeconds: 19).serialized)
        XCTAssertFalse(OneJobObservation(soloSeconds: 10, concurrentPairSeconds: 11).serialized)
        XCTAssertFalse(OneJobObservation(soloSeconds: 0, concurrentPairSeconds: 5).serialized)
    }

    func testCleanupMustReturnWithinBothTheByteAndTheTimeBudget() {
        let gates = SpeechPerformanceGates.initial
        XCTAssertTrue(
            CleanupObservation(baselineBytes: 150 * mib, settledBytes: 240 * mib, settledAfterSeconds: 12, afterReturningFreedPagesBytes: 240 * mib, runtimeResidualBytes: 0)
                .returned(within: gates)
        )
        XCTAssertFalse(
            CleanupObservation(baselineBytes: 150 * mib, settledBytes: 260 * mib, settledAfterSeconds: 12, afterReturningFreedPagesBytes: 260 * mib, runtimeResidualBytes: 0)
                .returned(within: gates)
        )
        XCTAssertFalse(
            CleanupObservation(baselineBytes: 150 * mib, settledBytes: 160 * mib, settledAfterSeconds: 31, afterReturningFreedPagesBytes: 160 * mib, runtimeResidualBytes: 0)
                .returned(within: gates)
        )
        // Settling below the baseline is a pass, never an arithmetic surprise.
        XCTAssertTrue(
            CleanupObservation(baselineBytes: 150 * mib, settledBytes: 140 * mib, settledAfterSeconds: 1, afterReturningFreedPagesBytes: 140 * mib, runtimeResidualBytes: 0)
                .returned(within: gates)
        )
    }

    func testMemoryMallocKeptWarmDoesNotCountAgainstCleanup() {
        // 400 MiB still charged, but 30 MiB once freed pages are returned: the
        // job owned 30, malloc was keeping the rest warm.
        let warm = CleanupObservation(
            baselineBytes: 150 * mib, settledBytes: 550 * mib, settledAfterSeconds: 5,
            afterReturningFreedPagesBytes: 180 * mib, runtimeResidualBytes: 0
        )
        XCTAssertTrue(warm.returned(within: .initial))
        let owned = CleanupObservation(
            baselineBytes: 150 * mib, settledBytes: 550 * mib, settledAfterSeconds: 5,
            afterReturningFreedPagesBytes: 540 * mib, runtimeResidualBytes: 0
        )
        XCTAssertFalse(owned.returned(within: .initial))
    }

    func testReportVerdictsFollowTheGatesAndRenderWithSortedKeys() throws {
        let report = SpeechPerformanceReport(
            recordedAt: Date(timeIntervalSince1970: 0),
            audioMinutes: 10,
            audioSource: "synthetic",
            machine: .init(profile: "test", chip: "test", memoryBytes: 8 * 1_073_741_824, osVersion: "0.0.0"),
            gates: .initial,
            recording: .init(baselineBytes: 150 * mib, samples: [
                .init(audioSeconds: 0, footprintBytes: 200 * mib),
                .init(audioSeconds: 600, footprintBytes: 200 * mib),
            ]),
            recordingSamples: [],
            transcriptionPeakBytes: 1_600 * mib,
            transcriptionSeconds: 3,
            oneJob: .init(soloSeconds: 1, concurrentPairSeconds: 2),
            cleanup: .init(baselineBytes: 150 * mib, settledBytes: 160 * mib, settledAfterSeconds: 2, afterReturningFreedPagesBytes: 160 * mib, runtimeResidualBytes: Int64(90 * mib))
        )

        XCTAssertTrue(report.verdicts.recordingP95WithinGate)
        XCTAssertTrue(report.verdicts.noDurationLinkedGrowth)
        XCTAssertFalse(report.verdicts.transcriptionPeakWithinGate)
        XCTAssertTrue(report.verdicts.oneJobAtATime)
        XCTAssertTrue(report.verdicts.cleanupReturnedToBaseline)
        XCTAssertFalse(report.verdicts.allPassed)

        let json = try JSONSerialization.jsonObject(with: report.render()) as? [String: Any]
        XCTAssertEqual(json?["schemaVersion"] as? Int, 1)
        XCTAssertEqual(json?["recordedAt"] as? String, "1970-01-01T00:00:00Z")
        let text = String(decoding: try report.render(), as: UTF8.self)
        XCTAssertLessThan(text.range(of: "\"audioMinutes\"")!.lowerBound, text.range(of: "\"verdicts\"")!.lowerBound)
    }

    func testPhysicalFootprintIsMeasurableInThisProcess() {
        XCTAssertGreaterThan(ProcessMemory.physicalFootprintBytes(), 0)
    }

    // MARK: - Measured run (opt-in)

    func testMeasuredRunWritesEvidenceArtifact() async throws {
        let environment = ProcessInfo.processInfo.environment
        guard let minutesText = environment["TAMFORGE_PERF_MINUTES"], let minutes = Int(minutesText), minutes > 0 else {
            throw XCTSkip("Set TAMFORGE_PERF_MINUTES (and TAMFORGE_PERF_OUTPUT) to run the measured harness.")
        }
        guard SpeechModelCatalog().transcriptionModelURL != nil else {
            throw XCTSkip("Transcription model is not installed; run `make whisper-models` to enable this test.")
        }
        guard SpokenAudio.shared.isAvailable else {
            throw XCTSkip("The system speech synthesizer produced no audio; the harness needs spoken input.")
        }
        let outputPath = environment["TAMFORGE_PERF_OUTPUT"]
            ?? FileManager.default.temporaryDirectory.appendingPathComponent("speech-performance-\(minutes)m.json").path
        let gates = SpeechPerformanceGates.initial
        let recordingID = UUID()

        // Baseline after settling, before any spool or model exists.
        try await Task.sleep(nanoseconds: 2_000_000_000)
        let baseline = ProcessMemory.physicalFootprintBytes()

        // Phase 1: two-track recording of `minutes` of audio through the real
        // encrypted spool, one second per append, footprint sampled every 30
        // audio seconds. Chunks are built and dropped per second, exactly as
        // the capture pipeline hands them over, so nothing accumulates unless
        // the spool itself does.
        let root = try temporaryDirectory()
        let factory = EncryptedRecordingSpoolFactory(rootURL: root, keyStore: HarnessKeyStore(), reservationBytes: 0)
        let spool = try await factory.create(recordingID: recordingID)
        let startedAt = Date()
        var samples: [MemorySample] = []
        let totalSeconds = minutes * 60
        for second in 0..<totalSeconds {
            try await spool.append(SpokenAudio.shared.chunk(track: .microphone, second: second))
            try await spool.append(SpokenAudio.shared.chunk(track: .systemAudio, second: second))
            if second % 30 == 0 {
                samples.append(.init(audioSeconds: Double(second), footprintBytes: ProcessMemory.physicalFootprintBytes()))
            }
        }
        samples.append(.init(audioSeconds: Double(totalSeconds), footprintBytes: ProcessMemory.physicalFootprintBytes()))
        try await spool.seal(gaps: [], startedAt: startedAt, endedAt: Date())
        let recording = MemoryGrowthAnalysis(baselineBytes: baseline, samples: samples)
        // Phase 2: one warm-up job, released. The first transcription in a
        // process pays a one-time runtime cost (Metal library and pipelines,
        // ggml's device context) that whisper_free does not return and that
        // is not the job's to free. The cleanup gate is measured against the
        // footprint after that warm-up, and the warm-up's residual is
        // recorded so the reader can see the fixed cost separately.
        let transcriber = try WhisperTranscriber()
        let coldBaseline = ProcessMemory.physicalFootprintBytes()
        let warmUp = try await deriveRequest(reader: factory, recordingID: recordingID, seconds: 30)
        _ = try await transcriber.transcribe(warmUp)
        await transcriber.release()
        try await Task.sleep(nanoseconds: 2_000_000_000)
        ProcessMemory.returnFreedPages()
        let preJobBaseline = ProcessMemory.physicalFootprintBytes()
        let runtimeResidual = Int64(preJobBaseline) - Int64(coldBaseline)

        // Phase 3: the coordinator's path, read sealed chunks, derive to
        // 16 kHz, one request for the whole stream, peak footprint sampled
        // from a side task while whisper runs. Then one job at a time: thirty
        // seconds solo, then two copies submitted together. Scoped in a
        // helper so every buffer the job owned is gone before cleanup is
        // measured.
        let job = try await runJob(transcriber: transcriber, reader: factory, recordingID: recordingID)
        let transcriptionPeak = job.peakBytes
        let transcriptionSeconds = job.seconds
        let oneJob = job.oneJob

        // Phase 4: cleanup. Release the model context and watch the footprint
        // fall back toward the pre-job baseline.
        await transcriber.release()
        try await factory.discard(recordingID: recordingID)
        let cleanupStart = Date()
        var settled = ProcessMemory.physicalFootprintBytes()
        var settledAfter = 0.0
        while Date().timeIntervalSince(cleanupStart) < gates.cleanupReturnWithinSeconds {
            settled = ProcessMemory.physicalFootprintBytes()
            settledAfter = Date().timeIntervalSince(cleanupStart)
            if Int64(settled) - Int64(preJobBaseline) <= Int64(gates.cleanupReturnWithinBytes) { break }
            try await Task.sleep(nanoseconds: 1_000_000_000)
        }
        ProcessMemory.returnFreedPages()
        let afterRelief = ProcessMemory.physicalFootprintBytes()
        let cleanup = CleanupObservation(
            baselineBytes: preJobBaseline,
            settledBytes: settled,
            settledAfterSeconds: settledAfter,
            afterReturningFreedPagesBytes: afterRelief,
            runtimeResidualBytes: runtimeResidual
        )

        let report = SpeechPerformanceReport(
            recordedAt: startedAt,
            audioMinutes: minutes,
            audioSource: "system speech synthesizer passage tiled to length, 48 kHz PCM16, two tracks",
            machine: SpeechPerformanceReport.currentMachine(),
            gates: gates,
            recording: recording,
            recordingSamples: samples,
            transcriptionPeakBytes: transcriptionPeak,
            transcriptionSeconds: transcriptionSeconds,
            oneJob: oneJob,
            cleanup: cleanup
        )
        try report.render().write(to: URL(fileURLWithPath: outputPath))

        // The artifact is the evidence either way; the assertions make a
        // failed gate visible in the test log too.
        XCTAssertTrue(report.verdicts.recordingP95WithinGate, "recording p95 \(recording.p95Bytes / mib) MiB")
        XCTAssertTrue(report.verdicts.noDurationLinkedGrowth, "slope \(recording.slopeBytesPerAudioMinute) B/min")
        XCTAssertTrue(report.verdicts.transcriptionPeakWithinGate, "peak \(transcriptionPeak / mib) MiB")
        XCTAssertTrue(report.verdicts.oneJobAtATime, "pair/solo ratio \(oneJob.ratio)")
        XCTAssertTrue(
            report.verdicts.cleanupReturnedToBaseline,
            "delta \(cleanup.deltaFromBaselineBytes / Int64(mib)) MiB after \(cleanup.settledAfterSeconds)s,"
                + " \(cleanup.deltaAfterReturningFreedPagesBytes / Int64(mib)) MiB once freed pages returned"
        )
    }

    // MARK: - Helpers

    private struct JobObservation {
        let peakBytes: UInt64
        let seconds: Double
        let oneJob: OneJobObservation
    }

    private func runJob(
        transcriber: WhisperTranscriber, reader: any RecordingAudioReading, recordingID: UUID
    ) async throws -> JobObservation {
        let peak = FootprintPeak()
        let sampler = Task {
            while !Task.isCancelled {
                await peak.observe(ProcessMemory.physicalFootprintBytes())
                try? await Task.sleep(nanoseconds: 250_000_000)
            }
        }
        let start = Date()
        let request = try await deriveRequest(reader: reader, recordingID: recordingID, seconds: nil)
        let result = try await transcriber.transcribe(request)
        let seconds = Date().timeIntervalSince(start)
        XCTAssertEqual(result.lineage.outputSampleRate, 16_000)
        sampler.cancel()

        let probe = SpeechTranscriptionRequest(
            samples: Array(request.samples.prefix(30 * 16_000)), lineage: request.lineage
        )
        let soloStart = Date()
        _ = try await transcriber.transcribe(probe)
        let solo = Date().timeIntervalSince(soloStart)
        let pairStart = Date()
        async let first = transcriber.transcribe(probe)
        async let second = transcriber.transcribe(probe)
        _ = try await (first, second)
        let pair = Date().timeIntervalSince(pairStart)

        return JobObservation(
            peakBytes: await peak.value,
            seconds: seconds,
            oneJob: OneJobObservation(soloSeconds: solo, concurrentPairSeconds: pair)
        )
    }

    /// The coordinator's derivation path over the sealed microphone track,
    /// optionally only its first `seconds` one-second chunks.
    private func deriveRequest(
        reader: any RecordingAudioReading, recordingID: UUID, seconds: Int?
    ) async throws -> SpeechTranscriptionRequest {
        var chunks = try await reader.sealedChunks(recordingID: recordingID, track: .microphone)
        if let seconds { chunks = Array(chunks.prefix(seconds)) }
        let deriver = ASRAudioDeriver(recordingID: recordingID, track: .microphone)
        var samples: [Int16] = []
        for chunk in chunks {
            if let block = try deriver.append(chunk) { samples += block.samples }
        }
        let (last, lineage) = deriver.finish()
        if let last { samples += last.samples }
        return SpeechTranscriptionRequest(samples: samples, lineage: lineage)
    }

    private func temporaryDirectory() throws -> URL {
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("tamforge-perf-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: url) }
        return url
    }
}

private actor FootprintPeak {
    private(set) var value: UInt64 = 0
    func observe(_ bytes: UInt64) { value = max(value, bytes) }
}

private actor HarnessKeyStore: RecordingKeyStoring {
    private var values: [UUID: SymmetricKey] = [:]

    func create(recordingID: UUID) throws -> SymmetricKey {
        let key = SymmetricKey(size: .bits256)
        values[recordingID] = key
        return key
    }

    func load(recordingID: UUID) throws -> SymmetricKey {
        guard let key = values[recordingID] else { throw RecordingSpoolError.missingKey }
        return key
    }

    func delete(recordingID: UUID) throws { values[recordingID] = nil }
}

/// Real spoken English from the system synthesizer, so the engine does the
/// work a real recording makes it do. Whisper on pure tones either skips
/// everything as silence or loops the decoder for minutes per window, and
/// neither says anything about memory under load. One passage is rendered
/// once at 48 kHz PCM16 and tiled, so every run feeds identical bytes.
private final class SpokenAudio: @unchecked Sendable {
    static let sampleRate = 48_000
    static let shared = SpokenAudio()

    private let samples: [Int16]

    private init() {
        samples = (try? Self.render()) ?? []
    }

    var isAvailable: Bool { !samples.isEmpty }

    func chunk(track: RecordingTrackKind, second: Int) -> RecordingPCMChunk {
        let channels = track == .microphone ? 1 : 2
        var payload = Data(capacity: Self.sampleRate * channels * 2)
        // The system track is the same voice offset by half the passage: a
        // remote participant talking over the learner, not a copy.
        let offset = track == .microphone ? 0 : samples.count / 2
        let start = second * Self.sampleRate
        for index in 0..<Self.sampleRate {
            let sample = samples[(start + index + offset) % samples.count]
            for _ in 0..<channels {
                withUnsafeBytes(of: sample.littleEndian) { payload.append(contentsOf: $0) }
            }
        }
        return RecordingPCMChunk(
            track: track,
            presentationNanoseconds: Int64(second) * 1_000_000_000,
            sampleStart: Int64(second) * Int64(Self.sampleRate),
            sampleCount: Self.sampleRate,
            format: try! RecordingPCMFormat(track: track, channelCount: channels),
            source: .init(
                sampleRate: Double(Self.sampleRate), channelCount: channels, deviceID: "perf-harness",
                initialRoute: "perf-harness", conversionVersion: 1,
                presentationNanoseconds: Int64(second) * 1_000_000_000
            ),
            payload: payload
        )
    }

    private static let passage = """
    Thanks for walking me through the pipeline. Before we look at the dashboard, \
    I want to understand how the events reach the warehouse. You said the ingestion \
    job runs every fifteen minutes and writes to a staging table, and then a second \
    job deduplicates by order id and loads the fact table. When a customer updates \
    an order after it has been loaded, which of those two jobs is responsible for \
    the correction, and how do you make sure the revenue report does not count the \
    order twice? I would also like to know how you monitor the freshness of the \
    data, because the sales team told me the numbers looked stale last Tuesday.
    """

    private static func render() throws -> [Int16] {
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("tamforge-perf-passage-\(UUID().uuidString).caf")
        defer { try? FileManager.default.removeItem(at: url) }
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/say")
        process.arguments = ["-v", "Samantha", "-o", url.path, "--data-format=LEI16@48000", passage]
        try process.run()
        process.waitUntilExit()
        guard process.terminationStatus == 0 else { return [] }
        let file = try AVAudioFile(forReading: url, commonFormat: .pcmFormatInt16, interleaved: true)
        guard let buffer = AVAudioPCMBuffer(pcmFormat: file.processingFormat, frameCapacity: AVAudioFrameCount(file.length)) else {
            return []
        }
        try file.read(into: buffer)
        guard let channel = buffer.int16ChannelData?.pointee, file.processingFormat.sampleRate == 48_000 else {
            return []
        }
        return Array(UnsafeBufferPointer(start: channel, count: Int(buffer.frameLength)))
    }
}
