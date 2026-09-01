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

    func testTimelineSeparatesDroppedOverflowFromPreexistingHoleWithoutDoubleCounting() throws {
        var timeline = RecordingTimelineAssembler()
        _ = try timeline.accept(.fixture(
            track: .microphone, presentationNanoseconds: 1_000_000_000,
            sampleCount: 24_000
        ))

        let gaps = try timeline.accept(droppedSourceRange: .init(
            track: .microphone,
            presentationNanoseconds: 2_000_000_000,
            sourceSampleCount: 4_410,
            sourceSampleRate: 44_100
        ))
        let resumed = try timeline.accept(.fixture(
            track: .microphone, presentationNanoseconds: 2_100_000_000,
            sampleCount: 4_800
        ))

        XCTAssertEqual(gaps, [
            .init(
                track: .microphone,
                sampleStart: 24_000,
                sampleCount: 24_000,
                reason: .sourceDiscontinuity
            ),
            .init(
                track: .microphone,
                sampleStart: 48_000,
                sampleCount: 4_800,
                reason: .callbackOverflow
            ),
        ])
        XCTAssertNil(resumed.gap)
        XCTAssertEqual(resumed.chunk.sampleStart, 52_800)
    }

    func testBoundedQueueRejectsOverflowWithoutEvictingAcceptedAudio() {
        let queue = BoundedCaptureQueue<Int>(capacity: 2)

        XCTAssertTrue(queue.offer(1))
        XCTAssertTrue(queue.offer(2))
        XCTAssertFalse(queue.offer(3))
        XCTAssertEqual(queue.drain(), [1, 2])
    }

    func testCaptureHandoffQueuesOnlyOneDrainUntilWorkerFindsItEmpty() {
        let handoff = BoundedCaptureHandoffQueue(capacity: 1)
        handoff.record(dropped: .init(
            track: .microphone,
            presentationNanoseconds: 1_000_000_000,
            sourceSampleCount: 4_800,
            sourceSampleRate: 48_000
        ))

        XCTAssertTrue(handoff.scheduleDrainIfNeeded())
        XCTAssertFalse(handoff.scheduleDrainIfNeeded())
        XCTAssertEqual(handoff.takeDrainBatch()?.count, 1)
        XCTAssertTrue(handoff.isDrainScheduled)

        handoff.record(dropped: .init(
            track: .microphone,
            presentationNanoseconds: 1_100_000_000,
            sourceSampleCount: 4_800,
            sourceSampleRate: 48_000
        ))
        XCTAssertFalse(handoff.scheduleDrainIfNeeded())
        XCTAssertEqual(handoff.takeDrainBatch()?.count, 1)
        XCTAssertNil(handoff.takeDrainBatch())
        XCTAssertFalse(handoff.isDrainScheduled)
        XCTAssertTrue(handoff.scheduleDrainIfNeeded())
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

    func testSpoolHeaderTamperFailsMetadataAuthenticationWithoutReturningAudio() async throws {
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
        bytes[4 + 64] ^= 0xff // Length prefix + independently authenticated metadata field.
        try bytes.write(to: trackURL, options: .atomic)

        let recovered = try await EncryptedRecordingSpool.recover(
            recordingID: recordingID, rootURL: root, keyStore: keyStore
        )
        XCTAssertTrue(recovered.records.isEmpty)
        XCTAssertTrue(recovered.corruptRanges.isEmpty)
        XCTAssertEqual(recovered.unrecoverableCorruptions.first?.reason, .malformedHeader)
    }

    func testUnsealedSpoolRecoversGapPersistedBeforeImmediateStop() async throws {
        let root = try temporaryDirectory()
        let keyStore = InMemoryRecordingKeyStore()
        let recordingID = UUID()
        let spool = try await EncryptedRecordingSpool.create(
            recordingID: recordingID, rootURL: root, keyStore: keyStore
        )
        let firstGap = RecordingGap(
            track: .microphone,
            sampleStart: 48_000,
            sampleCount: 4_800,
            reason: .callbackOverflow
        )
        let secondGap = RecordingGap(
            track: .microphone,
            sampleStart: 52_800,
            sampleCount: 4_800,
            reason: .callbackOverflow
        )

        try await spool.record(gap: firstGap)
        try await spool.record(gap: secondGap)

        let recovered = try await EncryptedRecordingSpool.recover(
            recordingID: recordingID, rootURL: root, keyStore: keyStore
        )
        // The initial authenticated state still has count zero; unsealed recovery
        // accepts later authenticated journal entries rather than discarding them.
        XCTAssertEqual(recovered.gaps, [firstGap, secondGap])
        XCTAssertFalse(recovered.sealed)
    }

    func testSealedSpoolRequiresExactAuthenticatedGapJournalCount() async throws {
        let root = try temporaryDirectory()
        let keyStore = InMemoryRecordingKeyStore()
        let recordingID = UUID()
        let spool = try await EncryptedRecordingSpool.create(
            recordingID: recordingID, rootURL: root, keyStore: keyStore
        )
        let firstGap = RecordingGap(
            track: .microphone, sampleStart: 0, sampleCount: 4_800, reason: .callbackOverflow
        )
        let secondGap = RecordingGap(
            track: .microphone, sampleStart: 4_800, sampleCount: 4_800, reason: .callbackOverflow
        )
        try await spool.record(gap: firstGap)
        try await spool.record(gap: secondGap)
        try await spool.seal(gaps: [])

        let journalURL = root.appendingPathComponent(recordingID.uuidString, isDirectory: true)
            .appendingPathComponent("gaps.tfj")
        let journal = try Data(contentsOf: journalURL)
        let firstLength = Int(journal.prefix(4).reduce(0) { ($0 << 8) | Int($1) })
        try Data(journal.prefix(4 + firstLength)).write(to: journalURL, options: .atomic)

        let recovered = try await EncryptedRecordingSpool.recover(
            recordingID: recordingID, rootURL: root, keyStore: keyStore
        )
        XCTAssertEqual(recovered.gaps, [firstGap])
        XCTAssertTrue(recovered.sealed)
        XCTAssertEqual(recovered.unrecoverableCorruptions.last?.reason, .malformedGapJournal)
    }

    func testStructuralRecordCorruptionNeedsAttentionWithoutGuessingRange() async throws {
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

        let trackURL = root.appendingPathComponent(recordingID.uuidString, isDirectory: true)
            .appendingPathComponent("microphone.tfr")
        var bytes = try Data(contentsOf: trackURL)
        bytes.replaceSubrange(0..<4, with: [0, 0, 0, 1])
        try bytes.write(to: trackURL, options: .atomic)

        let recovered = try await EncryptedRecordingSpool.recover(
            recordingID: recordingID, rootURL: root, keyStore: keyStore
        )
        XCTAssertTrue(recovered.records.isEmpty)
        XCTAssertTrue(recovered.corruptRanges.isEmpty)
        XCTAssertEqual(recovered.unrecoverableCorruptions.first?.reason, .malformedLength)
    }

    func testMalformedCompleteHeaderWithAuthenticatedMetadataRecoversExactCorruptRange() async throws {
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

        let trackURL = root.appendingPathComponent(recordingID.uuidString, isDirectory: true)
            .appendingPathComponent("microphone.tfr")
        var bytes = try Data(contentsOf: trackURL)
        bytes[4 + 49] = 0 // Invalid source-channel field; fixed identity/range remain intact.
        bytes = try await reauthenticatedRecordMetadata(
            bytes, recordingID: recordingID, keyStore: keyStore
        )
        try bytes.write(to: trackURL, options: .atomic)

        let recovered = try await EncryptedRecordingSpool.recover(
            recordingID: recordingID, rootURL: root, keyStore: keyStore
        )
        XCTAssertEqual(recovered.corruptRanges, [.init(
            track: .microphone,
            sampleStart: 0,
            sampleCount: 48_000,
            reason: .corruptSpoolRecord
        )])
        XCTAssertTrue(recovered.unrecoverableCorruptions.isEmpty)
    }

    func testTamperedSourceChannelNeverBecomesAnAcceptedCorruptGap() async throws {
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

        let trackURL = root.appendingPathComponent(recordingID.uuidString, isDirectory: true)
            .appendingPathComponent("microphone.tfr")
        var bytes = try Data(contentsOf: trackURL)
        bytes[4 + 49] = 0 // sourceChannels low byte; metadata HMAC is intentionally stale.
        try bytes.write(to: trackURL, options: .atomic)

        let recovered = try await EncryptedRecordingSpool.recover(
            recordingID: recordingID, rootURL: root, keyStore: keyStore
        )
        XCTAssertTrue(recovered.records.isEmpty)
        XCTAssertTrue(recovered.corruptRanges.isEmpty)
        XCTAssertEqual(recovered.unrecoverableCorruptions.first?.reason, .malformedHeader)
    }

    func testTamperedSampleRangeNeverBecomesAnAcceptedCorruptGap() async throws {
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

        let trackURL = root.appendingPathComponent(recordingID.uuidString, isDirectory: true)
            .appendingPathComponent("microphone.tfr")
        var bytes = try Data(contentsOf: trackURL)
        bytes[4 + 35] ^= 0x01 // sampleStart's final byte; metadata HMAC is intentionally stale.
        try bytes.write(to: trackURL, options: .atomic)

        let recovered = try await EncryptedRecordingSpool.recover(
            recordingID: recordingID, rootURL: root, keyStore: keyStore
        )
        XCTAssertTrue(recovered.records.isEmpty)
        XCTAssertTrue(recovered.corruptRanges.isEmpty)
        XCTAssertEqual(recovered.unrecoverableCorruptions.first?.reason, .malformedHeader)
    }

    func testTamperedSampleCountNeverBecomesAnAcceptedCorruptGap() async throws {
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

        let trackURL = root.appendingPathComponent(recordingID.uuidString, isDirectory: true)
            .appendingPathComponent("microphone.tfr")
        var bytes = try Data(contentsOf: trackURL)
        bytes[4 + 39] ^= 0x01 // sampleCount's final byte; metadata HMAC is intentionally stale.
        try bytes.write(to: trackURL, options: .atomic)

        let recovered = try await EncryptedRecordingSpool.recover(
            recordingID: recordingID, rootURL: root, keyStore: keyStore
        )
        XCTAssertTrue(recovered.records.isEmpty)
        XCTAssertTrue(recovered.corruptRanges.isEmpty)
        XCTAssertEqual(recovered.unrecoverableCorruptions.first?.reason, .malformedHeader)
    }

    func testSpoolRecoversInitialRouteAndConversionVersionLineage() async throws {
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

        let recovered = try await EncryptedRecordingSpool.recover(
            recordingID: recordingID, rootURL: root, keyStore: keyStore
        )
        XCTAssertEqual(recovered.records.first?.chunk.source.initialRoute, "Test Route")
        XCTAssertEqual(recovered.records.first?.chunk.source.conversionVersion, 1)
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

    func testPendingGapWritesCoalescesSaturatedDropsBeforeImmediateSeal() async throws {
        let spool = OrderedFakeRecordingSpool()
        let pendingWrites = PendingGapWrites()

        for index in 0..<100 {
            pendingWrites.register(gap: .init(
                track: .systemAudio,
                sampleStart: Int64(index * 4_800),
                sampleCount: 4_800,
                reason: .callbackOverflow
            ), spool: spool)
        }
        XCTAssertEqual(pendingWrites.bufferedIntervalCount, 1)
        try await pendingWrites.flush()
        try await spool.seal(gaps: [])

        let operations = await spool.operations()
        XCTAssertEqual(operations, [
            .gap(.init(
                track: .systemAudio,
                sampleStart: 0,
                sampleCount: 480_000,
                reason: .callbackOverflow
            )),
            .seal,
        ])
    }

    func testPendingGapWritesNeverCoalescesNonContiguousCoverage() {
        let first = RecordingGap(
            track: .microphone,
            sampleStart: 0,
            sampleCount: 4_800,
            reason: .callbackOverflow
        )
        let nonContiguous = RecordingGap(
            track: .microphone,
            sampleStart: 9_600,
            sampleCount: 4_800,
            reason: .callbackOverflow
        )

        XCTAssertNil(PendingGapWrites.merge(first, nonContiguous))
    }

    func testPendingGapWriteFailureBlocksFutureFlushAndSeal() async {
        let spool = FailingFakeRecordingSpool()
        let pendingWrites = PendingGapWrites()
        let gap = RecordingGap(
            track: .microphone,
            sampleStart: 0,
            sampleCount: 4_800,
            reason: .callbackOverflow
        )

        pendingWrites.register(gap: gap, spool: spool)
        do {
            try await pendingWrites.flush()
            XCTFail("pending write failure must be observable")
        } catch {}
        pendingWrites.register(gap: gap, spool: spool)
        do {
            try await pendingWrites.flush()
            XCTFail("later flush must retain first worker failure")
        } catch {}
        let recordAttempts = await spool.recordAttempts
        XCTAssertEqual(recordAttempts, 1)
    }

    func testPendingGapWritesStartsNewWorkerAfterPriorWorkerDrains() async throws {
        let spool = OrderedFakeRecordingSpool()
        let pendingWrites = PendingGapWrites()
        let first = RecordingGap(
            track: .microphone,
            sampleStart: 0,
            sampleCount: 4_800,
            reason: .callbackOverflow
        )
        let second = RecordingGap(
            track: .microphone,
            sampleStart: 4_800,
            sampleCount: 4_800,
            reason: .callbackOverflow
        )

        pendingWrites.register(gap: first, spool: spool)
        try await pendingWrites.flush()
        pendingWrites.register(gap: second, spool: spool)
        try await pendingWrites.flush()

        let operations = await spool.operations()
        XCTAssertEqual(operations, [.gap(first), .gap(second)])
    }

    func testCoordinatorDiscardsNewSpoolWhenSourceStartFails() async {
        let source = FakeRecordingCaptureSource(startFailure: .sourceUnavailable)
        let preflight = FakeRecordingPreflight()
        let spoolFactory = FakeRecordingSpoolFactory()
        let coordinator = await MainActor.run {
            RecordingCoordinator(
                preflight: preflight, source: source, spoolFactory: spoolFactory
            )
        }

        await coordinator.start()

        let createdIDs = await spoolFactory.createdRecordingIDs
        let discardedIDs = await spoolFactory.discardedRecordingIDs
        let stopCount = await source.stopCount
        XCTAssertEqual(discardedIDs, createdIDs)
        XCTAssertEqual(stopCount, 1)
        let phase = await MainActor.run { coordinator.phase }
        guard case let .needsAttention(recordingID, _) = phase else {
            return XCTFail("failed start must become visible")
        }
        XCTAssertEqual(recordingID, createdIDs.first)
    }

    private func temporaryDirectory() throws -> URL {
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("tamforge-recording-tests-(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: url) }
        return url
    }

    private func reauthenticatedRecordMetadata(
        _ originalRecord: Data,
        recordingID: UUID,
        keyStore: InMemoryRecordingKeyStore
    ) async throws -> Data {
        var record = originalRecord
        let rootKey = try await keyStore.load(recordingID: recordingID)
        let authenticationKey = HKDF<SHA256>.deriveKey(
            inputKeyMaterial: rootKey,
            salt: Data("tamforge.recording.spool-record-metadata.v1".utf8),
            info: Data(recordingID.uuidString.utf8),
            outputByteCount: 32
        )
        let metadataStart = 4 // Record length prefix.
        let metadataEnd = metadataStart + 160
        let authentication = Data(HMAC<SHA256>.authenticationCode(
            for: Data(record[metadataStart..<metadataEnd]),
            using: authenticationKey
        ))
        record.replaceSubrange(metadataEnd..<(metadataEnd + 32), with: authentication)
        return record
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
                initialRoute: "Test Route",
                conversionVersion: 1,
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
    private let startFailure: RecordingCaptureFailure?

    init(startFailure: RecordingCaptureFailure? = nil) {
        self.startFailure = startFailure
    }

    func start(
        microphoneID: String?,
        initialRoute: String,
        receive: @escaping @Sendable (RecordingCaptureEvent) -> Void
    ) async throws {
        startCount += 1
        if let startFailure { throw startFailure }
    }

    func stop() async throws { stopCount += 1 }
}

private struct FakeRecordingPreflight: RecordingPreflighting {
    func run() async -> RecordingPreflightResult { .ready(.fixture) }
}

private actor FakeRecordingSpoolFactory: RecordingSpoolCreating {
    private(set) var createdRecordingIDs: [UUID] = []
    private(set) var discardedRecordingIDs: [UUID] = []

    func create(recordingID: UUID) async throws -> any RecordingSpoolWriting {
        createdRecordingIDs.append(recordingID)
        FakeRecordingSpool()
    }

    func pendingRecordingIDs() async -> [UUID] { [] }
    func discard(recordingID: UUID) async throws { discardedRecordingIDs.append(recordingID) }
}

private actor FakeRecordingSpool: RecordingSpoolWriting {
    func append(_ chunk: RecordingPCMChunk) async throws {}
    func record(gap: RecordingGap) async throws {}
    func seal(gaps: [RecordingGap]) async throws {}
}

private actor OrderedFakeRecordingSpool: RecordingSpoolWriting {
    enum Operation: Equatable {
        case gap(RecordingGap)
        case seal
    }

    private var recordedOperations: [Operation] = []

    func append(_ chunk: RecordingPCMChunk) async throws {}
    func record(gap: RecordingGap) async throws { recordedOperations.append(.gap(gap)) }
    func seal(gaps: [RecordingGap]) async throws { recordedOperations.append(.seal) }
    func operations() -> [Operation] { recordedOperations }
}

private actor FailingFakeRecordingSpool: RecordingSpoolWriting {
    private(set) var recordAttempts = 0

    func append(_ chunk: RecordingPCMChunk) async throws {}
    func record(gap: RecordingGap) async throws {
        recordAttempts += 1
        throw RecordingSpoolError.invalidRecord
    }
    func seal(gaps: [RecordingGap]) async throws {}
}
