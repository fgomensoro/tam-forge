import CryptoKit
import Foundation
import XCTest

// No `@testable import TAMForge` — this target compiles the Speech and
// Recording sources directly, so RecordingAudioReading,
// EncryptedRecordingSpool, and EncryptedRecordingSpoolFactory are visible
// here exactly as they are to RecordingFeatureTests.swift.
final class RecordingAudioReadingTests: XCTestCase {
    func testSealedChunksReturnsOnlyMicrophoneTrackInSpoolOrder() async throws {
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

        // The system chunk sits between the microphone chunks on disk, so a
        // passing assertion below proves the other track is filtered out
        // without disturbing spool order.
        try await spool.append(firstMicChunk)
        try await spool.append(systemChunk)
        try await spool.append(secondMicChunk)
        try await spool.seal(gaps: [], startedAt: Date(), endedAt: Date())

        let chunks = try await reader.sealedChunks(recordingID: recordingID, track: .microphone).collect()

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

        let chunks = try await reader.sealedChunks(recordingID: recordingID, track: .systemAudio).collect()

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

// Reading a sealed spool must not keep the decrypted audio resident once the
// caller has dropped the chunks. The bound is deliberately far below the
// decrypted size of the spool this test builds, so the assertion fails only
// when the read path retains audio, not on ordinary allocator jitter.
final class RecordingAudioReadingFootprintTests: XCTestCase {
    func testReadingASealedMultiChunkSpoolLeavesNoAudioResident() async throws {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("tamforge-audio-footprint-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: root) }
        let keyStore = FootprintKeyStore()
        let factory = EncryptedRecordingSpoolFactory(
            rootURL: root, keyStore: keyStore, reservationBytes: 0
        )
        let recordingID = UUID()
        let spool = try await factory.create(recordingID: recordingID)
        // Two minutes of both tracks: 2 * 120 one-second chunks, about 34 MiB
        // decrypted, so retention of either track exceeds the bound below.
        let seconds = 120
        for second in 0..<seconds {
            for (track, channels) in [(RecordingTrackKind.microphone, 1), (.systemAudio, 2)] {
                try await spool.append(.init(
                    track: track,
                    presentationNanoseconds: Int64(second) * 1_000_000_000,
                    sampleStart: Int64(second) * 48_000,
                    sampleCount: 48_000,
                    format: try RecordingPCMFormat(track: track, channelCount: channels),
                    source: .init(
                        sampleRate: 48_000, channelCount: channels, deviceID: "footprint",
                        initialRoute: "Test Route", conversionVersion: 1,
                        presentationNanoseconds: Int64(second) * 1_000_000_000
                    ),
                    payload: Data(repeating: UInt8(second & 0xff), count: 48_000 * channels * 2)
                ))
            }
        }
        try await spool.seal(gaps: [], startedAt: Date(), endedAt: Date())

        ProcessMemory.returnFreedPages()
        let baseline = ProcessMemory.physicalFootprintBytes()
        let derived = try await deriveSampleCount(reader: factory, recordingID: recordingID)
        XCTAssertEqual(derived, seconds * 16_000)
        ProcessMemory.returnFreedPages()
        let after = ProcessMemory.physicalFootprintBytes()

        let delta = Int64(after) - Int64(baseline)
        XCTAssertLessThan(delta, 8 * 1024 * 1024, "read path kept \(delta / (1024 * 1024)) MiB resident")
    }

    // Scoped so every chunk and sample buffer the read produced is out of
    // scope before the footprint is measured.
    private func deriveSampleCount(
        reader: any RecordingAudioReading, recordingID: UUID
    ) async throws -> Int {
        let chunks = try await reader.sealedChunks(recordingID: recordingID, track: .microphone)
        let deriver = ASRAudioDeriver(recordingID: recordingID, track: .microphone)
        var count = 0
        for try await chunk in chunks {
            if let block = try deriver.append(chunk) { count += block.samples.count }
        }
        if let last = deriver.finish().block { count += last.samples.count }
        return count
    }
}

private actor FootprintKeyStore: RecordingKeyStoring {
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

private extension AsyncThrowingStream where Element == RecordingPCMChunk, Failure == any Error {
    func collect() async throws -> [RecordingPCMChunk] {
        var chunks: [RecordingPCMChunk] = []
        for try await chunk in self { chunks.append(chunk) }
        return chunks
    }
}
