import CryptoKit
import Foundation
import XCTest

final class RecordingFeatureTests: XCTestCase {
    func testTimelineUsesOneOriginAndMakesMissingSamplesExplicit() throws {
        var timeline = RecordingTimelineAssembler()
        let first = RecordingPCMChunk.fixture(
            track: .microphone, presentationNanoseconds: 1_000_000_000,
            sampleCount: 48_000
        )
        let second = RecordingPCMChunk.fixture(
            track: .microphone, presentationNanoseconds: 2_100_000_000,
            sampleCount: 48_000
        )

        let acceptedFirst = try timeline.accept(first)
        let acceptedSecond = try timeline.accept(second)

        XCTAssertEqual(acceptedFirst.chunk.sampleStart, 0)
        XCTAssertEqual(acceptedSecond.gap?.sampleStart, 48_000)
        XCTAssertEqual(acceptedSecond.gap?.sampleCount, 4_800)
        XCTAssertEqual(acceptedSecond.chunk.sampleStart, 52_800)
    }

    func testTimelineRejectsOverlappingOrChangingCanonicalFormat() throws {
        var timeline = RecordingTimelineAssembler()
        _ = try timeline.accept(.fixture(
            track: .systemAudio, presentationNanoseconds: 1_000_000_000,
            sampleCount: 48_000
        ))

        XCTAssertThrowsError(try timeline.accept(.fixture(
            track: .systemAudio, presentationNanoseconds: 1_500_000_000,
            sampleCount: 48_000
        )))
        XCTAssertThrowsError(try RecordingPCMFormat(track: .microphone, channelCount: 2))
    }

    func testBoundedQueueRejectsOverflowWithoutEvictingAcceptedAudio() {
        let queue = BoundedCaptureQueue<Int>(capacity: 2)

        XCTAssertTrue(queue.offer(1))
        XCTAssertTrue(queue.offer(2))
        XCTAssertFalse(queue.offer(3))
        XCTAssertEqual(queue.drain(), [1, 2])
    }

    func testSpoolAuthenticatesEachRecordAndIgnoresOnlyCrashTail() async throws {
        let root = try temporaryDirectory()
        let keyStore = InMemoryRecordingKeyStore()
        let recordingID = UUID()
        let spool = try await EncryptedRecordingSpool.create(
            recordingID: recordingID, rootURL: root, keyStore: keyStore
        )
        let first = RecordingPCMChunk.fixture(
            track: .microphone, presentationNanoseconds: 1_000_000_000,
            sampleCount: 48_000
        )
        let second = RecordingPCMChunk.fixture(
            track: .microphone, presentationNanoseconds: 2_000_000_000,
            sampleCount: 48_000,
            byte: 0x7f
        )
        try await spool.append(first)
        try await spool.append(second)
        try await spool.seal(gaps: [])

        let clean = try await EncryptedRecordingSpool.recover(
            recordingID: recordingID, rootURL: root, keyStore: keyStore
        )
        XCTAssertEqual(clean.records.map(\.payload), [first.payload, second.payload])
        XCTAssertTrue(clean.corruptRanges.isEmpty)

        let trackURL = root.appendingPathComponent(recordingID.uuidString, isDirectory: true)
            .appendingPathComponent("microphone.tfr")
        let handle = try FileHandle(forWritingTo: trackURL)
        try handle.seekToEnd()
        try handle.write(contentsOf: Data([0, 0, 1]))
        try handle.close()

        let crashTail = try await EncryptedRecordingSpool.recover(
            recordingID: recordingID, rootURL: root, keyStore: keyStore
        )
        XCTAssertEqual(crashTail.records.count, 2)
        XCTAssertTrue(crashTail.ignoredIncompleteTail)
    }

    func testSpoolTamperBecomesExplicitCorruptRange() async throws {
        let root = try temporaryDirectory()
        let keyStore = InMemoryRecordingKeyStore()
        let recordingID = UUID()
        let spool = try await EncryptedRecordingSpool.create(
            recordingID: recordingID, rootURL: root, keyStore: keyStore
        )
        let chunk = RecordingPCMChunk.fixture(
            track: .systemAudio, presentationNanoseconds: 1_000_000_000,
            sampleCount: 48_000
        )
        try await spool.append(chunk)
        try await spool.seal(gaps: [])

        let trackURL = root.appendingPathComponent(recordingID.uuidString, isDirectory: true)
            .appendingPathComponent("system-audio.tfr")
        var bytes = try Data(contentsOf: trackURL)
        bytes[bytes.index(before: bytes.endIndex)] ^= 0xff
        try bytes.write(to: trackURL, options: .atomic)

        let recovered = try await EncryptedRecordingSpool.recover(
            recordingID: recordingID, rootURL: root, keyStore: keyStore
        )
        XCTAssertEqual(recovered.corruptRanges.first?.sampleStart, 0)
        XCTAssertEqual(recovered.corruptRanges.first?.sampleCount, 48_000)
    }

    func testSpoolAADTamperFailsAuthenticationWithoutReturningAudio() async throws {
        let root = try temporaryDirectory()
        let keyStore = InMemoryRecordingKeyStore()
        let recordingID = UUID()
        let spool = try await EncryptedRecordingSpool.create(
            recordingID: recordingID, rootURL: root, keyStore: keyStore
        )
        try await spool.append(.fixture(
            track: .microphone,
            presentationNanoseconds: 1_000_000_000,
            sampleCount: 48_000
        ))
        try await spool.seal(gaps: [])

        let trackURL = root.appendingPathComponent(recordingID.uuidString, isDirectory: true)
            .appendingPathComponent("microphone.tfr")
        var bytes = try Data(contentsOf: trackURL)
        bytes[64] ^= 0xff // Length prefix + authenticated device-identity hash field.
        try bytes.write(to: trackURL, options: .atomic)

        let recovered = try await EncryptedRecordingSpool.recover(
            recordingID: recordingID, rootURL: root, keyStore: keyStore
        )
        XCTAssertTrue(recovered.records.isEmpty)
        XCTAssertEqual(recovered.corruptRanges.count, 1)
    }

    func testExplicitDiscardRemovesEncryptedSpoolAndKey() async throws {
        let root = try temporaryDirectory()
        let keyStore = InMemoryRecordingKeyStore()
        let factory = EncryptedRecordingSpoolFactory(
            rootURL: root, keyStore: keyStore, reservationBytes: 0
        )
        let recordingID = UUID()
        _ = try await factory.create(recordingID: recordingID)

        try await factory.discard(recordingID: recordingID)

        XCTAssertFalse(FileManager.default.fileExists(
            atPath: root.appendingPathComponent(recordingID.uuidString).path
        ))
        do {
            _ = try await keyStore.load(recordingID: recordingID)
            XCTFail("discard must crypto-shred the recording key")
        } catch RecordingSpoolError.missingKey {
            // Expected.
        }
    }

    func testDiskPolicyKeepsReserveAndBothCaps() {
        XCTAssertNil(RecordingDiskPolicy.failure(
            availableBytes: 11 * RecordingDiskPolicy.gibibyte,
            pendingGlobalBytes: 0,
            proposedRecordingBytes: RecordingDiskPolicy.maximumRecordingBytes
        ))
        XCTAssertEqual(RecordingDiskPolicy.failure(
            availableBytes: 8 * RecordingDiskPolicy.gibibyte,
            pendingGlobalBytes: 0,
            proposedRecordingBytes: 1
        ), .insufficientDiskReserve)
        XCTAssertEqual(RecordingDiskPolicy.failure(
            availableBytes: 20 * RecordingDiskPolicy.gibibyte,
            pendingGlobalBytes: RecordingDiskPolicy.maximumGlobalBytes,
            proposedRecordingBytes: 1
        ), .globalSpoolLimitReached)
    }

    func testReleaseGateNeverDeletesAfterAudio201Alone() {
        XCTAssertFalse(RecordingReleaseGates(
            audioCreatedOnServer: true, transcriptLineageAccepted: false
        ).mayDeleteLocalSpool)
        XCTAssertTrue(RecordingReleaseGates(
            audioCreatedOnServer: true, transcriptLineageAccepted: true
        ).mayDeleteLocalSpool)
    }

    func testCoordinatorDisablesDuplicateStartAndStopIsIdempotent() async {
        let source = FakeRecordingCaptureSource()
        let preflight = FakeRecordingPreflight()
        let spoolFactory = FakeRecordingSpoolFactory()
        let coordinator = await MainActor.run {
            RecordingCoordinator(
                preflight: preflight, source: source, spoolFactory: spoolFactory
            )
        }

        await coordinator.start()
        await coordinator.start()
        let startCount = await source.startCount
        XCTAssertEqual(startCount, 1)
        await coordinator.stop()
        await coordinator.stop()
        let stopCount = await source.stopCount
        XCTAssertEqual(stopCount, 1)
    }

    private func temporaryDirectory() throws -> URL {
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("tamforge-recording-tests-(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: url) }
        return url
    }
}

private extension RecordingPCMChunk {
    static func fixture(
        track: RecordingTrackKind,
        presentationNanoseconds: Int64,
        sampleCount: Int,
        byte: UInt8 = 0
    ) -> Self {
        let channels = track == .microphone ? 1 : 2
        return .init(
            track: track,
            presentationNanoseconds: presentationNanoseconds,
            sampleStart: 0,
            sampleCount: sampleCount,
            format: try! RecordingPCMFormat(track: track, channelCount: channels),
            source: .init(
                sampleRate: 48_000, channelCount: channels,
                deviceID: track == .microphone ? "test-microphone" : "system-audio",
                presentationNanoseconds: presentationNanoseconds
            ),
            payload: Data(repeating: byte, count: sampleCount * channels * 2)
        )
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

private actor FakeRecordingCaptureSource: RecordingCaptureSource {
    private(set) var startCount = 0
    private(set) var stopCount = 0

    func start(
        microphoneID: String?,
        receive: @escaping @Sendable (RecordingCaptureEvent) -> Void
    ) async throws {
        startCount += 1
    }

    func stop() async throws { stopCount += 1 }
}

private struct FakeRecordingPreflight: RecordingPreflighting {
    func run() async -> RecordingPreflightResult { .ready(.fixture) }
}

private actor FakeRecordingSpoolFactory: RecordingSpoolCreating {
    func create(recordingID: UUID) async throws -> any RecordingSpoolWriting {
        FakeRecordingSpool()
    }

    func pendingRecordingIDs() async -> [UUID] { [] }
    func discard(recordingID: UUID) async throws {}
}

private actor FakeRecordingSpool: RecordingSpoolWriting {
    func append(_ chunk: RecordingPCMChunk) async throws {}
    func record(gap: RecordingGap) async {}
    func seal(gaps: [RecordingGap]) async throws {}
}
