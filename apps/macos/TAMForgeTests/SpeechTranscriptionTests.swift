import Foundation
import XCTest

final class SpeechTranscriptionTests: XCTestCase {
    // MARK: - SpeechTranscriptionResult.text

    func testResultTextJoinsSegmentTextsWithSingleSpaceAndTrims() {
        let segments = [
            SpeechTranscribedSegment(text: " Hello", startMilliseconds: 0, endMilliseconds: 500, words: []),
            SpeechTranscribedSegment(text: "world ", startMilliseconds: 500, endMilliseconds: 1_000, words: []),
        ]
        let result = SpeechTranscriptionResult(segments: segments, identity: fakeIdentity(), lineage: fakeLineage())
        XCTAssertEqual(result.text, "Hello world")
    }

    func testResultTextIsEmptyForNoSegments() {
        let result = SpeechTranscriptionResult(segments: [], identity: fakeIdentity(), lineage: fakeLineage())
        XCTAssertEqual(result.text, "")
    }

    // MARK: - SpeechTranscriptionRequest.validate()

    func testValidateRejectsSampleRateOtherThanSixteenKilohertz() {
        let subject = SpeechTranscriptionRequest(samples: [1, 2, 3], lineage: fakeLineage(outputSampleRate: 8_000))
        XCTAssertThrowsError(try subject.validate()) { error in
            XCTAssertEqual(error as? SpeechTranscriptionError, .unsupportedSampleRate(8_000))
        }
    }

    func testValidateRejectsEmptySamples() {
        let subject = SpeechTranscriptionRequest(samples: [], lineage: fakeLineage(outputSampleRate: 16_000))
        XCTAssertThrowsError(try subject.validate()) { error in
            XCTAssertEqual(error as? SpeechTranscriptionError, .emptyAudio)
        }
    }

    // MARK: - SpeechModelCatalog

    func testCatalogReportsNilForBothModelsWhenDirectoryIsEmpty() throws {
        let directory = try makeTemporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let catalog = SpeechModelCatalog(directory: directory)
        XCTAssertNil(catalog.transcriptionModelURL)
        XCTAssertNil(catalog.vadModelURL)
    }

    func testCatalogReportsURLsOnceModelFilesExist() throws {
        let directory = try makeTemporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        try Data().write(to: directory.appendingPathComponent(SpeechModelCatalog.transcriptionModelFilename))
        try Data().write(to: directory.appendingPathComponent(SpeechModelCatalog.vadModelFilename))

        let catalog = SpeechModelCatalog(directory: directory)

        XCTAssertEqual(catalog.transcriptionModelURL?.lastPathComponent, SpeechModelCatalog.transcriptionModelFilename)
        XCTAssertEqual(catalog.vadModelURL?.lastPathComponent, SpeechModelCatalog.vadModelFilename)
    }

    func testRequireTranscriptionModelThrowsModelUnavailableNamingTheFileNotThePath() throws {
        let directory = try makeTemporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let catalog = SpeechModelCatalog(directory: directory)

        XCTAssertThrowsError(try catalog.requireTranscriptionModel()) { error in
            guard case let .modelUnavailable(message) = error as? SpeechTranscriptionError else {
                XCTFail("expected .modelUnavailable, got \(error)")
                return
            }
            XCTAssertTrue(message.contains(SpeechModelCatalog.transcriptionModelFilename))
            XCTAssertFalse(message.contains(directory.path))
        }
    }

    // MARK: - SpeechRuntimeIdentity

    func testRuntimeIdentityAlwaysCarriesEnglish() async throws {
        let engine = FakeSpeechEngine(segments: [], identity: fakeIdentity())
        let result = try await engine.transcribe(fakeRequest())
        XCTAssertEqual(result.identity.language, "en")
    }

    // MARK: - FakeSpeechEngine lineage propagation

    func testFakeEnginePropagatesRequestLineageUnchanged() async throws {
        let engine = FakeSpeechEngine(segments: [], identity: fakeIdentity())
        let sourceRequest = fakeRequest()
        let result = try await engine.transcribe(sourceRequest)
        XCTAssertEqual(result.lineage, sourceRequest.lineage)
    }

    // MARK: - TranscriptSubmitPayload.make word normalization (Important 3)

    // whisper.cpp's per-token timestamps come from a separate heuristic than
    // its segment timestamps and are not guaranteed to satisfy the server's
    // contract (transcript-lineage final review, Important 3): this builds a
    // segment whose raw words land outside its span on both ends and overlap
    // each other in the middle -- exactly the shape the review calls out --
    // plus one token that decoded to empty text, and asserts `.make()`
    // produces a body every one of the server's rules
    // (`TranscriptSegment.validate_words`, schemas.py:96-105) would accept:
    // every word contained within [segmentStart, segmentEnd], every word's
    // own span non-negative, and no word starting before the previous one in
    // the same segment ends.
    func testMakeClampsWordsIntoTheirSegmentAndOrdersThemChronologically() {
        let segment = SpeechTranscribedSegment(
            text: "hello there world",
            startMilliseconds: 100,
            endMilliseconds: 500,
            words: [
                // Starts 20ms before the segment: whisper's token heuristic
                // ran slightly ahead of its own segment boundary.
                .init(text: "hello", startMilliseconds: 80, endMilliseconds: 250, probability: 0.9),
                // Starts inside "hello"'s already-clamped span: two tokens
                // whose heuristics disagree about where one word ends and
                // the next begins.
                .init(text: "there", startMilliseconds: 200, endMilliseconds: 320, probability: 0.85),
                // A token that decoded to empty text -- BoundedText requires
                // at least one character, so this must be dropped, not sent.
                .init(text: "", startMilliseconds: 320, endMilliseconds: 330, probability: 0.5),
                // Ends 20ms past the segment: the symmetric case of the
                // first word.
                .init(text: "world", startMilliseconds: 328, endMilliseconds: 520, probability: 0.8),
            ]
        )
        let result = SpeechTranscriptionResult(
            segments: [segment], identity: fakeIdentity(), lineage: fakeLineage()
        )

        let payload = TranscriptSubmitPayload.make(recordingID: UUID(), result: result)

        XCTAssertEqual(payload.segments.count, 1)
        let words = payload.segments[0].words
        // The empty-text token is gone; the other three survive with their
        // text untouched and in the original order.
        XCTAssertEqual(words.map(\.text), ["hello", "there", "world"])

        for word in words {
            XCTAssertGreaterThanOrEqual(word.startMilliseconds, segment.startMilliseconds)
            XCTAssertLessThanOrEqual(word.endMilliseconds, segment.endMilliseconds)
            XCTAssertLessThanOrEqual(word.startMilliseconds, word.endMilliseconds)
        }
        for (previous, current) in zip(words, words.dropFirst()) {
            XCTAssertGreaterThanOrEqual(current.startMilliseconds, previous.endMilliseconds)
        }

        // The exact values the hand-worked clamp produces, not just the
        // invariants: "hello" is pulled up to the segment start; "there"'s
        // start is pushed to "hello"'s clamped end (250), the overlap the
        // fake segment was built to provoke; "world"'s end is pulled down
        // to the segment end.
        XCTAssertEqual(words[0].startMilliseconds, 100)
        XCTAssertEqual(words[0].endMilliseconds, 250)
        XCTAssertEqual(words[1].startMilliseconds, 250)
        XCTAssertEqual(words[1].endMilliseconds, 320)
        XCTAssertEqual(words[2].startMilliseconds, 328)
        XCTAssertEqual(words[2].endMilliseconds, 500)
    }

    func testMakePassesThroughAWordTimelineThatAlreadySatisfiesTheContract() {
        // The common case -- whisper's tokens already land inside their
        // segment and in order -- must come through byte-for-byte
        // unchanged, so normalization never rewrites a timeline that was
        // already valid.
        let segment = SpeechTranscribedSegment(
            text: "hello there",
            startMilliseconds: 0,
            endMilliseconds: 900,
            words: [
                .init(text: "hello", startMilliseconds: 0, endMilliseconds: 400, probability: 0.98),
                .init(text: "there", startMilliseconds: 400, endMilliseconds: 900, probability: 0.91),
            ]
        )
        let result = SpeechTranscriptionResult(
            segments: [segment], identity: fakeIdentity(), lineage: fakeLineage()
        )

        let payload = TranscriptSubmitPayload.make(recordingID: UUID(), result: result)

        let words = payload.segments[0].words
        XCTAssertEqual(words.map(\.startMilliseconds), [0, 400])
        XCTAssertEqual(words.map(\.endMilliseconds), [400, 900])
    }

    // MARK: - Fixtures

    private func fakeQuality() -> AudioQualityObservations {
        AudioQualityObservations(
            version: "audio-quality-v1",
            sampleRate: 48_000,
            channelCount: 1,
            sourceSampleCount: 48_000,
            durationSeconds: 1.0,
            peakAbsolute: 8_000,
            allSilence: false,
            clippedRatio: 0,
            dcOffset: 0,
            channelImbalanceDecibels: nil,
            discontinuityCount: 0,
            unavailableDimensions: []
        )
    }

    private func fakeLineage(outputSampleRate: Int = 16_000) -> ASRDerivationLineage {
        ASRDerivationLineage(
            recordingID: UUID(uuidString: "22222222-2222-4222-8222-222222222222")!,
            track: .microphone,
            derivationVersion: ASRDerivationVersion.current,
            sourceSampleRate: 48_000,
            sourceChannelCount: 1,
            sourceSampleCount: 48_000,
            outputSampleRate: outputSampleRate,
            outputSampleCount: 16_000,
            zeroFilledGaps: [],
            sourcePCMSHA256: String(repeating: "a", count: 64),
            derivedPCMSHA256: String(repeating: "b", count: 64),
            quality: fakeQuality()
        )
    }

    private func fakeRequest() -> SpeechTranscriptionRequest {
        SpeechTranscriptionRequest(samples: [1, 2, 3], lineage: fakeLineage())
    }

    private func fakeIdentity() -> SpeechRuntimeIdentity {
        SpeechRuntimeIdentity(
            runtimeVersion: "fake",
            modelFilename: "fake-model.bin",
            modelSHA256: String(repeating: "0", count: 64),
            metalRequested: false,
            usedBuiltInVAD: false,
            language: "en"
        )
    }

    private func makeTemporaryDirectory() throws -> URL {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        return directory
    }
}

private struct FakeSpeechEngine: SpeechTranscribing {
    let segments: [SpeechTranscribedSegment]
    let identity: SpeechRuntimeIdentity

    func transcribe(_ request: SpeechTranscriptionRequest) async throws -> SpeechTranscriptionResult {
        try request.validate()
        return SpeechTranscriptionResult(segments: segments, identity: identity, lineage: request.lineage)
    }
}
