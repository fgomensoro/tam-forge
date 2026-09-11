import XCTest

// Issue #37: PCM16 is the recording format, and the spool limits follow from it.
final class RecordingFormatPolicyTests: XCTestCase {
    func testTheCanonicalFormatIsFortyEightKilohertzSignedPCM16() throws {
        let microphone = try RecordingPCMFormat(track: .microphone, channelCount: 1)
        let system = try RecordingPCMFormat(track: .systemAudio, channelCount: 2)
        for format in [microphone, system] {
            XCTAssertEqual(format.sampleEncoding, "pcm_s16le")
            XCTAssertEqual(format.sampleRate, 48_000)
            XCTAssertTrue(format.interleaved)
        }
        XCTAssertEqual(RecordingPCMFormat.bytesPerSample, 2)
    }

    func testAnyOtherSampleRateOrDepthIsNotConstructible() {
        XCTAssertThrowsError(try RecordingPCMFormat(track: .microphone, channelCount: 1, sampleRate: 44_100))
        XCTAssertThrowsError(try RecordingPCMFormat(track: .microphone, channelCount: 2))
    }

    func testTwoHoursOfPCM16FitTheSpoolCapAndPCM24WouldNot() {
        let seconds = Double(RecordingDiskPolicy.maximumDurationSeconds)
        XCTAssertEqual(seconds, 120 * 60)
        let pcm16 = 48_000.0 * 2 * 3 * seconds * 1.05
        let pcm24 = 48_000.0 * 3 * 3 * seconds * 1.05
        XCTAssertLessThanOrEqual(pcm16, Double(RecordingDiskPolicy.maximumRecordingBytes))
        XCTAssertGreaterThan(pcm24, Double(RecordingDiskPolicy.maximumRecordingBytes))
        XCTAssertEqual(RecordingDiskPolicy.maximumRecordingBytes, Int64(2.5 * Double(RecordingDiskPolicy.gibibyte)))
    }
}
