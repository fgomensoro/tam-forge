import CryptoKit
import XCTest

final class ASRAudioDerivationTests: XCTestCase {
    private let recordingID = UUID(uuidString: "11111111-1111-4111-8111-111111111111")!

    private func chunk(track: RecordingTrackKind, samples: [Int16], sampleStart: Int64) -> RecordingPCMChunk {
        let channels = track == .microphone ? 1 : 2
        var payload = Data(capacity: samples.count * 2)
        for sample in samples { withUnsafeBytes(of: sample.littleEndian) { payload.append(contentsOf: $0) } }
        return RecordingPCMChunk(
            track: track, presentationNanoseconds: 0, sampleStart: sampleStart,
            sampleCount: samples.count / channels,
            format: try! RecordingPCMFormat(track: track, channelCount: channels),
            source: .init(sampleRate: 48_000, channelCount: channels, deviceID: "test", initialRoute: "test", conversionVersion: 1, presentationNanoseconds: 0),
            payload: payload)
    }

    private func sine(frequency: Double, seconds: Double, amplitude: Double = 8_000) -> [Int16] {
        (0..<Int(48_000 * seconds)).map { Int16(amplitude * sin(2 * Double.pi * frequency * Double($0) / 48_000)) }
    }

    private func derive(_ chunks: [RecordingPCMChunk], track: RecordingTrackKind) throws -> ([Int16], ASRDerivationLineage) {
        let deriver = ASRAudioDeriver(recordingID: recordingID, track: track)
        var output: [Int16] = []
        for chunk in chunks { if let block = try deriver.append(chunk) { output += block.samples } }
        let (last, lineage) = deriver.finish()
        if let last { output += last.samples }
        return (output, lineage)
    }

    private func zeroCrossings(_ samples: ArraySlice<Int16>) -> Int {
        var count = 0
        var previous = samples.first ?? 0
        for sample in samples.dropFirst() { if (previous < 0) != (sample < 0) { count += 1 }; previous = sample }
        return count
    }

    func testOneKilohertzSineKeepsFrequencyDurationAndVersion() throws {
        let (output, lineage) = try derive([chunk(track: .microphone, samples: sine(frequency: 1_000, seconds: 1), sampleStart: 0)], track: .microphone)
        XCTAssertEqual(output.count, 16_000)
        XCTAssertEqual(lineage.derivationVersion, "tamforge-asr16k-v1")
        XCTAssertEqual(lineage.outputSampleCount, 16_000)
        XCTAssertEqual(lineage.sourceSampleCount, 48_000)
        // 1 kHz has 2 000 zero crossings per second; ignore the FIR warm-up edges.
        XCTAssertEqual(zeroCrossings(output[1_000..<15_000]), 1_750, accuracy: 4)
        XCTAssertGreaterThan(output[1_000..<15_000].map { abs(Int($0)) }.max() ?? 0, 7_000)
    }

    func testStereoDownmixUsesFixedMatrixBeforeRateReduction() throws {
        var stereo: [Int16] = []
        for value in sine(frequency: 440, seconds: 1) { stereo.append(value); stereo.append(0) }
        let (output, lineage) = try derive([chunk(track: .systemAudio, samples: stereo, sampleStart: 0)], track: .systemAudio)
        let peak = output[2_000..<14_000].map { abs(Int($0)) }.max() ?? 0
        XCTAssertEqual(peak, 4_000, accuracy: 120)  // (L + R) / 2 halves a one-sided signal
        XCTAssertEqual(lineage.sourceChannelCount, 2)
        XCTAssertGreaterThan(lineage.quality.channelImbalanceDecibels ?? 0, 20)
    }

    func testGapsAreZeroFilledAndMappedToSourcePositions() throws {
        let tone = sine(frequency: 440, seconds: 0.5)
        let chunks = [
            chunk(track: .microphone, samples: tone, sampleStart: 0),
            chunk(track: .microphone, samples: tone, sampleStart: 48_000),   // 24 000-sample hole
        ]
        let (output, lineage) = try derive(chunks, track: .microphone)
        XCTAssertEqual(output.count, 24_000)
        XCTAssertEqual(lineage.zeroFilledGaps, [RecordingGap(track: .microphone, sampleStart: 24_000, sampleCount: 24_000, reason: .missingAudio)])
        XCTAssertEqual(lineage.quality.discontinuityCount, 1)
        XCTAssertTrue(output[9_000..<15_000].allSatisfy { abs(Int($0)) < 8 })   // hole is silent (after FIR tail)
        XCTAssertGreaterThan(output[17_000..<23_000].map { abs(Int($0)) }.max() ?? 0, 7_000)
    }

    func testChunkBoundariesDoNotChangeOutput() throws {
        let tone = sine(frequency: 700, seconds: 1)
        let whole = try derive([chunk(track: .microphone, samples: tone, sampleStart: 0)], track: .microphone)
        var split: [RecordingPCMChunk] = []
        var start = 0
        for size in [7, 4_800, 1, 12_345, 30_847] {
            split.append(chunk(track: .microphone, samples: Array(tone[start..<start + size]), sampleStart: Int64(start)))
            start += size
        }
        let pieces = try derive(split, track: .microphone)
        XCTAssertEqual(whole.0, pieces.0)
        XCTAssertEqual(whole.1.derivedPCMSHA256, pieces.1.derivedPCMSHA256)
    }

    func testFixedInputProducesFixedHashAndLeavesSourceUntouched() throws {
        let source = chunk(track: .microphone, samples: sine(frequency: 300, seconds: 0.25, amplitude: 12_000), sampleStart: 0)
        let before = source.payload
        let (output, lineage) = try derive([source], track: .microphone)
        var bytes = Data()
        for sample in output { withUnsafeBytes(of: sample.littleEndian) { bytes.append(contentsOf: $0) } }
        XCTAssertEqual(lineage.derivedPCMSHA256, SHA256.hash(data: bytes).map { String(format: "%02x", $0) }.joined())
        XCTAssertEqual(lineage.sourcePCMSHA256, SHA256.hash(data: before).map { String(format: "%02x", $0) }.joined())
        XCTAssertEqual(source.payload, before)
        XCTAssertEqual(lineage.recordingID, recordingID)
        XCTAssertEqual(lineage.outputSampleRate, 16_000)
        // Pin the bytes: any change to the filter or rounding must bump the version.
        XCTAssertEqual(lineage.derivedPCMSHA256, ASRAudioDerivationTests.pinnedHash300Hz, "update pinnedHash300Hz only together with ASRDerivationVersion")
    }

    static let pinnedHash300Hz = "dfb1fe21c0d5db2720937a3196171d73a5d7f3f81c648ed074d8e575c08b53ac"

    func testOutOfOrderOrMismatchedChunksFailClosed() {
        let deriver = ASRAudioDeriver(recordingID: recordingID, track: .microphone)
        _ = try? deriver.append(chunk(track: .microphone, samples: sine(frequency: 440, seconds: 0.1), sampleStart: 4_800))
        XCTAssertThrowsError(try deriver.append(chunk(track: .microphone, samples: sine(frequency: 440, seconds: 0.1), sampleStart: 0))) { error in
            XCTAssertEqual(error as? ASRDerivationError, .chunkOutOfOrder(expected: 9_600, actual: 0))
        }
        XCTAssertThrowsError(try ASRAudioDeriver(recordingID: recordingID, track: .microphone)
            .append(chunk(track: .systemAudio, samples: [0, 0], sampleStart: 0))) { error in
            XCTAssertEqual(error as? ASRDerivationError, .trackMismatch)
        }
    }

    func testEmptyInputYieldsEmptySilentLineage() {
        let deriver = ASRAudioDeriver(recordingID: recordingID, track: .microphone)
        let (block, lineage) = deriver.finish()
        XCTAssertNil(block)
        XCTAssertEqual(lineage.outputSampleCount, 0)
        XCTAssertTrue(lineage.quality.allSilence)
        XCTAssertEqual(lineage.zeroFilledGaps, [])
    }
}
