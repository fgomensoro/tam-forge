import XCTest

final class AudioQualityObservationsTests: XCTestCase {
    private func chunk(track: RecordingTrackKind, samples: [Int16], sampleStart: Int64 = 0) -> RecordingPCMChunk {
        let channels = track == .microphone ? 1 : 2
        var payload = Data(capacity: samples.count * 2)
        for sample in samples { withUnsafeBytes(of: sample.littleEndian) { payload.append(contentsOf: $0) } }
        return RecordingPCMChunk(
            track: track,
            presentationNanoseconds: 0,
            sampleStart: sampleStart,
            sampleCount: samples.count / channels,
            format: try! RecordingPCMFormat(track: track, channelCount: channels),
            source: .init(sampleRate: 48_000, channelCount: channels, deviceID: "test", initialRoute: "test", conversionVersion: 1, presentationNanoseconds: 0),
            payload: payload
        )
    }

    func testSilentShortTrackIsUnavailableForDurationAndSilence() {
        var accumulator = AudioQualityAccumulator(sampleRate: 48_000, channelCount: 1)
        accumulator.observe(chunk: chunk(track: .microphone, samples: [Int16](repeating: 0, count: 4_800)))
        let observations = accumulator.finish()
        XCTAssertEqual(observations.version, "audio-quality-v1")
        XCTAssertEqual(observations.durationSeconds, 0.1, accuracy: 1e-9)
        XCTAssertTrue(observations.allSilence)
        XCTAssertEqual(observations.unavailableDimensions, ["duration", "silence"])
    }

    func testClippingAndDCOffsetFlipAvailability() {
        var accumulator = AudioQualityAccumulator(sampleRate: 48_000, channelCount: 1)
        let clipped = [Int16](repeating: Int16.max, count: 48_000)   // 1 s, every sample clipped, DC ≈ 1.0
        accumulator.observe(chunk: chunk(track: .microphone, samples: clipped))
        let observations = accumulator.finish()
        XCTAssertEqual(observations.clippedRatio, 1.0, accuracy: 1e-9)
        XCTAssertGreaterThan(observations.dcOffset, 0.9)
        XCTAssertFalse(observations.allSilence)
        XCTAssertEqual(observations.unavailableDimensions, ["clipping", "dc-offset"])
    }

    func testStereoImbalanceIsMeasuredBeforeDownmix() {
        var accumulator = AudioQualityAccumulator(sampleRate: 48_000, channelCount: 2)
        var samples = [Int16]()
        for index in 0..<48_000 { samples.append(index % 2 == 0 ? 8_000 : -8_000); samples.append(0) } // left square wave, right silent
        accumulator.observe(chunk: chunk(track: .systemAudio, samples: samples))
        let observations = accumulator.finish()
        XCTAssertNotNil(observations.channelImbalanceDecibels)
        XCTAssertGreaterThan(observations.channelImbalanceDecibels ?? 0, 20)
        XCTAssertEqual(observations.unavailableDimensions, ["channel-imbalance"])
    }

    func testDiscontinuitiesAreCountedAndCleanAudioIsFullyAvailable() {
        var accumulator = AudioQualityAccumulator(sampleRate: 48_000, channelCount: 1)
        let tone = (0..<48_000).map { Int16(8_000 * sin(2 * Double.pi * 440 * Double($0) / 48_000)) }
        accumulator.observe(chunk: chunk(track: .microphone, samples: tone))
        accumulator.noteDiscontinuity()
        let observations = accumulator.finish()
        XCTAssertEqual(observations.discontinuityCount, 1)
        XCTAssertEqual(observations.unavailableDimensions, [])
        XCTAssertEqual(observations.sourceSampleCount, 48_000)
    }
}
