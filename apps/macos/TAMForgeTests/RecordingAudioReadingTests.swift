import CryptoKit
import Foundation
import XCTest

// No `@testable import TAMForge` — this target compiles the Speech and
// Recording sources directly, so RecordingAudioReading,
// EncryptedRecordingSpool, and EncryptedRecordingSpoolFactory are visible
// here exactly as they are to RecordingFeatureTests.swift.
final class RecordingAudioReadingTests: XCTestCase {
    func testSealedChunksReturnsOnlyMicrophoneTrackInAscendingSampleStartOrder() async throws {
        let root = try temporaryDirectory()
        let keyStore = InMemoryRecordingKeyStore()
        let factory = EncryptedRecordingSpoolFactory(
            rootURL: root, keyStore: keyStore, reservationBytes: 0
        )
        let reader: any RecordingAudioReading = factory
        let recordingID = UUID()
        let spool = try await factory.create(recordingID: recordingID)

        let firstMicChunk = RecordingPCMChunk.fixture(
            track: .microphone, presentationNanoseconds: 1_000_000_000,
            sampleStart: 0, sampleCount: 48_000, byte: 0x11
        )
        let secondMicChunk = RecordingPCMChunk.fixture(
            track: .microphone, presentationNanoseconds: 2_000_000_000,
            sampleStart: 48_000, sampleCount: 48_000, byte: 0x7f
        )
        let systemChunk = RecordingPCMChunk.fixture(
            track: .systemAudio, presentationNanoseconds: 1_000_000_000,
            sampleStart: 0, sampleCount: 48_000, byte: 0x22
        )

        // Appended out of chronological order so a passing assertion below
        // proves sealedChunks sorts by sampleStart rather than merely
        // preserving recovery order.
        try await spool.append(secondMicChunk)
        try await spool.append(firstMicChunk)
        try await spool.append(systemChunk)
        try await spool.seal(gaps: [], startedAt: Date(), endedAt: Date())

        let chunks = try await reader.sealedChunks(recordingID: recordingID, track: .microphone)

        XCTAssertEqual(chunks.map(\.sampleStart), [0, 48_000])
        XCTAssertEqual(chunks.map(\.payload), [firstMicChunk.payload, secondMicChunk.payload])
        XCTAssertTrue(chunks.allSatisfy { $0.track == .microphone })
    }

    func testSealedChunksForSystemAudioReturnsOnlyThatTrack() async throws {
        let root = try temporaryDirectory()
        let keyStore = InMemoryRecordingKeyStore()
        let factory = EncryptedRecordingSpoolFactory(
            rootURL: root, keyStore: keyStore, reservationBytes: 0
        )
        let reader: any RecordingAudioReading = factory
        let recordingID = UUID()
        let spool = try await factory.create(recordingID: recordingID)

        let micChunk = RecordingPCMChunk.fixture(
            track: .microphone, presentationNanoseconds: 1_000_000_000,
            sampleStart: 0, sampleCount: 48_000, byte: 0x11
        )
        let systemChunk = RecordingPCMChunk.fixture(
            track: .systemAudio, presentationNanoseconds: 1_000_000_000,
            sampleStart: 0, sampleCount: 48_000, byte: 0x22
        )
        try await spool.append(micChunk)
        try await spool.append(systemChunk)
        try await spool.seal(gaps: [], startedAt: Date(), endedAt: Date())

        let chunks = try await reader.sealedChunks(recordingID: recordingID, track: .systemAudio)

        XCTAssertEqual(chunks.map(\.payload), [systemChunk.payload])
        XCTAssertTrue(chunks.allSatisfy { $0.track == .systemAudio })
    }

    func testSealedChunksThrowsForARecordingThatWasNeverCreated() async throws {
        let root = try temporaryDirectory()
        let keyStore = InMemoryRecordingKeyStore()
        let factory = EncryptedRecordingSpoolFactory(
            rootURL: root, keyStore: keyStore, reservationBytes: 0
        )
        let reader: any RecordingAudioReading = factory

        do {
            _ = try await reader.sealedChunks(recordingID: UUID(), track: .microphone)
            XCTFail("sealedChunks must throw rather than return an empty array")
        } catch RecordingSpoolError.missingKey {
            // Expected: recovery loads the key before it can read anything,
            // and no key was ever created for this recording.
        }
    }

    // MARK: - Helpers
    //
    // Mirrors RecordingFeatureTests.swift's private helpers. `private` is
    // file-scoped in Swift, so they cannot be shared across test files and
    // are re-declared here rather than duplicated through indirection.

    private func temporaryDirectory() throws -> URL {
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent(
                "tamforge-recording-audio-reading-tests-\(UUID().uuidString)", isDirectory: true
            )
        try FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: url) }
        return url
    }
}

private actor InMemoryRecordingKeyStore: RecordingKeyStoring {
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

private extension RecordingPCMChunk {
    static func fixture(
        track: RecordingTrackKind,
        presentationNanoseconds: Int64,
        sampleStart: Int64,
        sampleCount: Int,
        byte: UInt8 = 0
    ) -> Self {
        let channels = track == .microphone ? 1 : 2
        return .init(
            track: track,
            presentationNanoseconds: presentationNanoseconds,
            sampleStart: sampleStart,
            sampleCount: sampleCount,
            format: try! RecordingPCMFormat(track: track, channelCount: channels),
            source: .init(
                sampleRate: 48_000, channelCount: channels,
                deviceID: track == .microphone ? "test-microphone" : "system-audio",
                initialRoute: "Test Route",
                conversionVersion: 1,
                presentationNanoseconds: presentationNanoseconds
            ),
            payload: Data(repeating: byte, count: sampleCount * channels * 2)
        )
    }
}
