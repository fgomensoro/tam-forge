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
