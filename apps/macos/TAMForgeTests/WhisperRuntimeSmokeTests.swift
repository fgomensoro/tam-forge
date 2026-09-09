import Foundation
import XCTest

// Opt-in: only runs once the pinned model is installed (`make whisper-models`),
// so CI (which never fetches models) always skips it and stays green. No
// `@testable import TAMForge` — this target compiles the Speech and Recording
// sources directly, so WhisperTranscriber, SpeechModelCatalog, and
// ASRAudioDeriver are visible here exactly as they are to
// SpeechTranscriptionTests.swift and ASRAudioDerivationTests.swift.
final class WhisperRuntimeSmokeTests: XCTestCase {
    private let recordingID = UUID(uuidString: "44444444-4444-4444-8444-444444444444")!

    override func setUpWithError() throws {
        guard SpeechModelCatalog().transcriptionModelURL != nil else {
            throw XCTSkip("Transcription model is not installed; run `make whisper-models` to enable this test.")
        }
    }

    // MARK: - Fixtures
    //
    // Mirrors ASRAudioDerivationTests.swift's private helpers. `private` is
    // file-scoped in Swift, so they cannot be shared across test files and
    // are re-declared here rather than duplicated through indirection.

    private func chunk(samples: [Int16], sampleStart: Int64 = 0) -> RecordingPCMChunk {
        var payload = Data(capacity: samples.count * 2)
        for sample in samples { withUnsafeBytes(of: sample.littleEndian) { payload.append(contentsOf: $0) } }
        return RecordingPCMChunk(
            track: .microphone,
            presentationNanoseconds: 0,
            sampleStart: sampleStart,
            sampleCount: samples.count,
            format: try! RecordingPCMFormat(track: .microphone, channelCount: 1),
            source: .init(
                sampleRate: 48_000, channelCount: 1, deviceID: "smoke-test",
                initialRoute: "smoke-test", conversionVersion: 1, presentationNanoseconds: 0
            ),
            payload: payload
        )
    }

    private func sine(frequency: Double, seconds: Double, amplitude: Double = 8_000) -> [Int16] {
        (0..<Int(48_000 * seconds)).map { Int16(amplitude * sin(2 * Double.pi * frequency * Double($0) / 48_000)) }
    }

    // Derives a single chunk of synthetic 48 kHz mono audio down to the
    // 16 kHz stream WhisperTranscriber requires, the same path real
    // recordings take (RecordingPCMChunk -> ASRAudioDeriver).
    private func derive(_ samples: [Int16]) throws -> (samples: [Int16], lineage: ASRDerivationLineage) {
        let deriver = ASRAudioDeriver(recordingID: recordingID, track: .microphone)
        var output: [Int16] = []
        if let block = try deriver.append(chunk(samples: samples)) { output += block.samples }
        let (last, lineage) = deriver.finish()
        if let last { output += last.samples }
        return (output, lineage)
    }

    private func assertMonotonicallyOrdered(_ segments: [SpeechTranscribedSegment]) {
        var previousEnd: Int64 = 0
        for segment in segments {
            XCTAssertLessThanOrEqual(segment.startMilliseconds, segment.endMilliseconds)
            XCTAssertGreaterThanOrEqual(segment.startMilliseconds, previousEnd)
            previousEnd = segment.endMilliseconds
        }
    }

    // MARK: - Tests

    func testRealRuntimeIdentityAndLineageOnSyntheticAudio() async throws {
        let tone = sine(frequency: 440, seconds: 2)
        let (samples, lineage) = try derive(tone)
        let request = SpeechTranscriptionRequest(samples: samples, lineage: lineage)

        let transcriber = try WhisperTranscriber()
        let result = try await transcriber.transcribe(request)
        await transcriber.release()

        XCTAssertEqual(result.identity.language, "en")
        XCTAssertTrue(result.identity.metalRequested)
        XCTAssertGreaterThanOrEqual(result.segments.count, 0)
        assertMonotonicallyOrdered(result.segments)
        XCTAssertEqual(result.lineage, lineage)
    }

    func testSilenceProducesZeroSegmentsRatherThanError() async throws {
        let silence = [Int16](repeating: 0, count: 48_000 * 2)
        let (samples, lineage) = try derive(silence)
        let request = SpeechTranscriptionRequest(samples: samples, lineage: lineage)

        let transcriber = try WhisperTranscriber()
        let result = try await transcriber.transcribe(request)
        await transcriber.release()

        XCTAssertTrue(result.segments.isEmpty)
    }
}
