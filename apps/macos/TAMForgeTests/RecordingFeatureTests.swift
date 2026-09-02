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

    func testCapturePipelineCoalescesSubsecondBuffersIntoOneSecondRecord() throws {
        var pipeline = RecordingCapturePipeline()
        var events: [RecordingCaptureEvent] = []
        _ = try pipeline.bufferSystemStartupAnchor(at: 1_000_000_000)

        for index in 0..<4 {
            events += try pipeline.accept(.fixture(
                track: .microphone,
                presentationNanoseconds: 1_000_000_000 + Int64(index * 250_000_000),
                sampleCount: 12_000,
                byte: UInt8(index + 1)
            ), normalizedLevel: 0.5)
        }

        let chunks = events.recordingChunks
        XCTAssertEqual(chunks.count, 1)
        XCTAssertEqual(chunks.first?.sampleStart, 0)
        XCTAssertEqual(chunks.first?.sampleCount, 48_000)
        XCTAssertEqual(chunks.first?.payload.count, 96_000)
        XCTAssertTrue(pipeline.finish().recordingChunks.isEmpty)
    }

    func testCapturePipelineFinishFlushesAcceptedFinalPartialWithoutLoss() throws {
        var pipeline = RecordingCapturePipeline()
        _ = try pipeline.bufferSystemStartupAnchor(at: 1_000_000_000)
        let first = try pipeline.accept(.fixture(
            track: .microphone,
            presentationNanoseconds: 1_000_000_000,
            sampleCount: 30_000,
            byte: 0x11
        ), normalizedLevel: 0.5)
        let second = try pipeline.accept(.fixture(
            track: .microphone,
            presentationNanoseconds: 1_625_000_000,
            sampleCount: 30_000,
            byte: 0x22
        ), normalizedLevel: 0.5)

        XCTAssertTrue(first.recordingChunks.isEmpty)
        XCTAssertEqual(second.recordingChunks.map(\.sampleCount), [48_000])
        let final = pipeline.finish().recordingChunks
        XCTAssertEqual(final.map(\.sampleStart), [48_000])
        XCTAssertEqual(final.map(\.sampleCount), [12_000])
        XCTAssertEqual(
            second.recordingChunks.reduce(0) { $0 + $1.sampleCount }
                + final.reduce(0) { $0 + $1.sampleCount },
            60_000
        )
    }

    func testCapturePipelineSplitsPartialOnSourceLineageChange() throws {
        var pipeline = RecordingCapturePipeline()
        _ = try pipeline.bufferSystemStartupAnchor(at: 1_000_000_000)
        let first = try pipeline.accept(.fixture(
            track: .microphone,
            presentationNanoseconds: 1_000_000_000,
            sampleCount: 12_000,
            initialRoute: "Route A"
        ), normalizedLevel: 0.5)
        let second = try pipeline.accept(.fixture(
            track: .microphone,
            presentationNanoseconds: 1_250_000_000,
            sampleCount: 12_000,
            initialRoute: "Route B"
        ), normalizedLevel: 0.5)

        XCTAssertTrue(first.recordingChunks.isEmpty)
        XCTAssertEqual(second.recordingChunks.map(\.source.initialRoute), ["Route A"])
        XCTAssertEqual(pipeline.finish().recordingChunks.map(\.source.initialRoute), ["Route B"])
    }

    func testFailedRetainedSampleFlushesAudioAndEmitsExactSeparatedGaps() throws {
        var pipeline = RecordingCapturePipeline()
        _ = try pipeline.bufferSystemStartupAnchor(at: 1_000_000_000)
        _ = try pipeline.accept(.fixture(
            track: .microphone,
            presentationNanoseconds: 1_000_000_000,
            sampleCount: 24_000
        ), normalizedLevel: 0.5)

        let events = try pipeline.acceptFailure(
            droppedSourceRange: .init(
                track: .microphone,
                presentationNanoseconds: 2_000_000_000,
                sourceSampleCount: 4_410,
                sourceSampleRate: 44_100
            ),
            reason: .formatChange,
            failure: .formatUnsupported
        )

        XCTAssertEqual(events.recordingChunks.map(\.sampleCount), [24_000])
        XCTAssertEqual(events.recordingGaps, [
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
                reason: .formatChange
            ),
        ])
        XCTAssertEqual(events.recordingFailures, [.formatUnsupported])
    }

    func testCapturePipelineThrottlesLevelsToCanonicalTenHertz() throws {
        var pipeline = RecordingCapturePipeline()
        var events: [RecordingCaptureEvent] = []
        _ = try pipeline.bufferSystemStartupAnchor(at: 1_000_000_000)

        for index in 0...10 {
            events += try pipeline.accept(.fixture(
                track: .microphone,
                presentationNanoseconds: 1_000_000_000 + Int64(index * 20_000_000),
                sampleCount: 960
            ), normalizedLevel: Double(index) / 10)
        }

        XCTAssertEqual(events.recordingLevels.map { $0.normalized }, [0.0, 0.5, 1.0])
    }

    func testCapturePipelineUsesEarlierMicrophoneAnchorAfterSystemArrivesFirst() throws {
        var pipeline = RecordingCapturePipeline()
        let systemFirst = try pipeline.accept(.fixture(
            track: .systemAudio,
            presentationNanoseconds: 2_000_000_000,
            sampleCount: 4_800
        ), normalizedLevel: 0.25)

        let replay = try pipeline.accept(.fixture(
            track: .microphone,
            presentationNanoseconds: 1_000_000_000,
            sampleCount: 4_800
        ), normalizedLevel: 0.5)
        let final = pipeline.finish().recordingChunks

        XCTAssertTrue(systemFirst.isEmpty)
        XCTAssertEqual(replay.recordingGaps, [.init(
            track: .systemAudio,
            sampleStart: 0,
            sampleCount: 48_000,
            reason: .sourceDiscontinuity
        )])
        XCTAssertEqual(final.first { $0.track == .microphone }?.sampleStart, 0)
        XCTAssertEqual(final.first { $0.track == .systemAudio }?.sampleStart, 48_000)
    }

    func testCapturePipelineFailsClosedWhenSecondTrackMissingAtStartupBound() throws {
        var pipeline = RecordingCapturePipeline()
        let first = try pipeline.accept(.fixture(
            track: .microphone,
            presentationNanoseconds: 1_000_000_000,
            sampleCount: 48_000
        ), normalizedLevel: 0.5)
        let beyondBound = try pipeline.accept(.fixture(
            track: .microphone,
            presentationNanoseconds: 2_000_000_000,
            sampleCount: 1
        ), normalizedLevel: 0.5)

        XCTAssertTrue(first.isEmpty)
        XCTAssertTrue(beyondBound.recordingChunks.isEmpty)
        XCTAssertEqual(beyondBound.recordingFailures, [.requiredTracksMissing])
    }

    func testCapturePipelineFinishFailsClosedWhenSecondTrackNeverAnchors() throws {
        var pipeline = RecordingCapturePipeline()
        let buffered = try pipeline.accept(.fixture(
            track: .microphone,
            presentationNanoseconds: 1_000_000_000,
            sampleCount: 12_000
        ), normalizedLevel: 0.5)

        let final = pipeline.finish()

        XCTAssertTrue(buffered.isEmpty)
        XCTAssertTrue(final.recordingChunks.isEmpty)
        XCTAssertEqual(final.recordingFailures, [.requiredTracksMissing])
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

    func testCaptureHandoffCloseRejectsLaterOverflowBookkeeping() {
        let handoff = BoundedCaptureHandoffQueue(capacity: 1)
        XCTAssertTrue(handoff.record(dropped: .init(
            track: .microphone,
            presentationNanoseconds: 1_000_000_000,
            sourceSampleCount: 4_800,
            sourceSampleRate: 48_000
        )))

        handoff.close()

        XCTAssertTrue(handoff.isClosed)
        XCTAssertFalse(handoff.record(dropped: .init(
            track: .microphone,
            presentationNanoseconds: 2_000_000_000,
            sourceSampleCount: 4_800,
            sourceSampleRate: 48_000
        )))
        XCTAssertFalse(handoff.scheduleDrainIfNeeded())
        let drained = handoff.takeDrainBatch()
        XCTAssertEqual(drained?.count, 1)
        XCTAssertNil(handoff.takeDrainBatch())
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
        try await spool.seal(gaps: [], startedAt: Date(), endedAt: Date())

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
        XCTAssertEqual(
            crashTail.unrecoverableCorruptions.last?.reason,
            .sealedIncompleteTail
        )
    }

    func testSealedSpoolDetectsAlignedLastRecordTruncation() async throws {
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
        try await spool.append(.fixture(
            track: .microphone,
            presentationNanoseconds: 2_000_000_000,
            sampleCount: 48_000
        ))
        try await spool.append(.fixture(
            track: .systemAudio,
            presentationNanoseconds: 1_000_000_000,
            sampleCount: 48_000
        ))
        try await spool.seal(gaps: [], startedAt: Date(), endedAt: Date())

        let trackURL = root.appendingPathComponent(recordingID.uuidString, isDirectory: true)
            .appendingPathComponent("microphone.tfr")
        let bytes = try Data(contentsOf: trackURL)
        let firstLength = Int(bytes.prefix(4).reduce(0) { ($0 << 8) | Int($1) })
        try Data(bytes.prefix(4 + firstLength)).write(to: trackURL, options: .atomic)

        let recovered = try await EncryptedRecordingSpool.recover(
            recordingID: recordingID, rootURL: root, keyStore: keyStore
        )
        XCTAssertFalse(recovered.ignoredIncompleteTail)
        XCTAssertTrue(recovered.unrecoverableCorruptions.contains(.init(
            track: .microphone,
            byteOffset: nil,
            reason: .sealedCheckpointMismatch
        )))
    }

    func testSealedSpoolDetectsMissingExpectedTrackFile() async throws {
        let root = try temporaryDirectory()
        let keyStore = InMemoryRecordingKeyStore()
        let recordingID = UUID()
        let spool = try await EncryptedRecordingSpool.create(
            recordingID: recordingID, rootURL: root, keyStore: keyStore
        )
        for track in RecordingTrackKind.allCases {
            try await spool.append(.fixture(
                track: track,
                presentationNanoseconds: 1_000_000_000,
                sampleCount: 48_000
            ))
        }
        try await spool.seal(gaps: [], startedAt: Date(), endedAt: Date())

        let missingURL = root.appendingPathComponent(recordingID.uuidString, isDirectory: true)
            .appendingPathComponent("system-audio.tfr")
        try FileManager.default.removeItem(at: missingURL)

        let recovered = try await EncryptedRecordingSpool.recover(
            recordingID: recordingID, rootURL: root, keyStore: keyStore
        )
        XCTAssertTrue(recovered.unrecoverableCorruptions.contains(.init(
            track: .systemAudio,
            byteOffset: nil,
            reason: .sealedCheckpointMismatch
        )))
    }

    func testSpoolChargesExactAudioAndGapJournalRecordBytesToReservation() async throws {
        let root = try temporaryDirectory()
        let keyStore = InMemoryRecordingKeyStore()
        let recordingID = UUID()
        let reservationBytes: Int64 = 1_000_000
        let spool = try await EncryptedRecordingSpool.create(
            recordingID: recordingID,
            rootURL: root,
            keyStore: keyStore,
            reservationBytes: reservationBytes
        )
        try await spool.append(.fixture(
            track: .microphone,
            presentationNanoseconds: 1_000_000_000,
            sampleCount: 12_000
        ))
        try await spool.record(gap: .init(
            track: .microphone,
            sampleStart: 12_000,
            sampleCount: 4_800,
            reason: .callbackOverflow
        ))

        let directory = root.appendingPathComponent(recordingID.uuidString, isDirectory: true)
        let audioBytes = try fileSize(directory.appendingPathComponent("microphone.tfr"))
        let journalBytes = try fileSize(directory.appendingPathComponent("gaps.tfj"))
        let remainingReservation = try fileSize(directory.appendingPathComponent(".reserve"))
        XCTAssertEqual(
            remainingReservation,
            reservationBytes - audioBytes - journalBytes
        )
    }

    func testGapManifestPolicyBoundsRangeDurationAndEntryCount() {
        let finalValidGap = RecordingGap(
            track: .systemAudio,
            sampleStart: RecordingDiskPolicy.maximumCanonicalSamples - 1,
            sampleCount: 1,
            reason: .missingAudio
        )
        XCTAssertTrue(RecordingDiskPolicy.permitsGap(
            finalValidGap,
            trackEntryCount: RecordingDiskPolicy.maximumGapEntriesPerTrack - 1,
            totalEntryCount: RecordingDiskPolicy.maximumGapEntries - 1
        ))
        XCTAssertFalse(RecordingDiskPolicy.permitsGap(
            .init(
                track: .systemAudio,
                sampleStart: RecordingDiskPolicy.maximumCanonicalSamples,
                sampleCount: 1,
                reason: .missingAudio
            ),
            trackEntryCount: 0,
            totalEntryCount: 0
        ))
        XCTAssertFalse(RecordingDiskPolicy.permitsGap(
            finalValidGap,
            trackEntryCount: RecordingDiskPolicy.maximumGapEntriesPerTrack,
            totalEntryCount: RecordingDiskPolicy.maximumGapEntries - 1
        ))
        XCTAssertFalse(RecordingDiskPolicy.permitsGap(
            finalValidGap,
            trackEntryCount: 0,
            totalEntryCount: RecordingDiskPolicy.maximumGapEntries
        ))
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
        try await spool.seal(gaps: [], startedAt: Date(), endedAt: Date())

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
        XCTAssertTrue(recovered.unrecoverableCorruptions.isEmpty)
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
        try await spool.seal(gaps: [], startedAt: Date(), endedAt: Date())

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
        try await spool.seal(gaps: [], startedAt: Date(), endedAt: Date())

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
        try await spool.seal(gaps: [], startedAt: Date(), endedAt: Date())

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

    func testPendingSpoolBytesCountsHiddenReservationAndUploadFiles() throws {
        let root = try temporaryDirectory()
        let recording = root.appendingPathComponent(UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: recording, withIntermediateDirectories: true)
        try Data(repeating: 0, count: 3).write(
            to: recording.appendingPathComponent(".reserve")
        )
        try Data(repeating: 0, count: 5).write(
            to: recording.appendingPathComponent(".upload")
        )
        try Data(repeating: 0, count: 7).write(
            to: recording.appendingPathComponent("microphone.tfr")
        )

        XCTAssertEqual(LiveRecordingPreflight.pendingSpoolBytes(at: root), 15)
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
        let spool = GatedFakeRecordingSpool()
        let pendingWrites = PendingGapWrites()

        pendingWrites.register(gap: .init(
            track: .systemAudio, sampleStart: 0, sampleCount: 4_800, reason: .callbackOverflow
        ), spool: spool)
        await spool.waitUntilFirstWrite()
        for index in 1..<100 {
            pendingWrites.register(gap: .init(
                track: .systemAudio,
                sampleStart: Int64(index * 4_800),
                sampleCount: 4_800,
                reason: .callbackOverflow
            ), spool: spool)
        }
        // The worker is parked inside the first write, so every saturated
        // drop coalesces into exactly one pending interval.
        XCTAssertEqual(pendingWrites.bufferedIntervalCount, 1)
        await spool.releaseWrites()
        try await pendingWrites.flush()
        try await spool.seal(gaps: [], startedAt: Date(), endedAt: Date())

        let operations = await spool.operations()
        XCTAssertEqual(operations, [
            .gap(.init(
                track: .systemAudio,
                sampleStart: 0,
                sampleCount: 4_800,
                reason: .callbackOverflow
            )),
            .gap(.init(
                track: .systemAudio,
                sampleStart: 4_800,
                sampleCount: 475_200,
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

    func testCoordinatorStopPersistsSourceFinalChunkBeforeSeal() async {
        let finalChunk = RecordingPCMChunk.fixture(
            track: .microphone,
            presentationNanoseconds: 1_000_000_000,
            sampleCount: 12_000
        )
        let source = FakeRecordingCaptureSource(finalEventOnStop: .chunk(finalChunk))
        let preflight = FakeRecordingPreflight()
        let spool = OrderedFakeRecordingSpool()
        let spoolFactory = SingleRecordingSpoolFactory(spool: spool)
        let coordinator = await MainActor.run {
            RecordingCoordinator(
                preflight: preflight, source: source, spoolFactory: spoolFactory
            )
        }

        await coordinator.start()
        await coordinator.stop()

        let operations = await spool.operations()
        XCTAssertEqual(operations, [.chunk(finalChunk), .seal])
    }

    func testCoordinatorAppendFailureDuringStopNeverSeals() async {
        let finalChunk = RecordingPCMChunk.fixture(
            track: .microphone,
            presentationNanoseconds: 1_000_000_000,
            sampleCount: 12_000
        )
        let source = FakeRecordingCaptureSource(finalEventOnStop: .chunk(finalChunk))
        let spool = WriteFailingRecordingSpool(failure: .append)
        let spoolFactory = RecoveryTrackingSpoolFactory(spool: spool)
        let coordinator = await MainActor.run {
            RecordingCoordinator(
                preflight: FakeRecordingPreflight(),
                source: source,
                spoolFactory: spoolFactory
            )
        }
        await coordinator.start()

        await coordinator.stop()

        let sealAttempts = await spool.sealAttempts
        XCTAssertEqual(sealAttempts, 0)
        let phase = await MainActor.run { coordinator.phase }
        guard case .needsAttention = phase else {
            return XCTFail("append failure must leave an unsealed spool needing attention")
        }
        let createdIDs = await spoolFactory.createdRecordingIDs
        let pendingIDs = await MainActor.run { coordinator.pendingRecordingIDs }
        XCTAssertEqual(pendingIDs, createdIDs)
    }

    func testCoordinatorGapPersistenceFailureDuringStopNeverSeals() async {
        let finalGap = RecordingGap(
            track: .microphone,
            sampleStart: 0,
            sampleCount: 4_800,
            reason: .missingAudio
        )
        let source = FakeRecordingCaptureSource(finalEventOnStop: .gap(finalGap))
        let spool = WriteFailingRecordingSpool(failure: .gap)
        let spoolFactory = RecoveryTrackingSpoolFactory(spool: spool)
        let coordinator = await MainActor.run {
            RecordingCoordinator(
                preflight: FakeRecordingPreflight(),
                source: source,
                spoolFactory: spoolFactory
            )
        }
        await coordinator.start()

        await coordinator.stop()

        let sealAttempts = await spool.sealAttempts
        XCTAssertEqual(sealAttempts, 0)
        let phase = await MainActor.run { coordinator.phase }
        guard case .needsAttention = phase else {
            return XCTFail("gap failure must leave an unsealed spool needing attention")
        }
        let createdIDs = await spoolFactory.createdRecordingIDs
        let pendingIDs = await MainActor.run { coordinator.pendingRecordingIDs }
        XCTAssertEqual(pendingIDs, createdIDs)
    }

    func testCoordinatorSourceStopFailureAbandonsUnsealedSpoolAndRefreshesRecovery() async {
        let source = FakeRecordingCaptureSource(stopFailure: .streamStopped)
        let spool = OrderedFakeRecordingSpool()
        let spoolFactory = RecoveryTrackingSpoolFactory(spool: spool)
        let coordinator = await MainActor.run {
            RecordingCoordinator(
                preflight: FakeRecordingPreflight(),
                source: source,
                spoolFactory: spoolFactory
            )
        }
        await coordinator.start()

        await coordinator.stop()

        let operations = await spool.operations()
        XCTAssertFalse(operations.contains(.seal))
        let createdIDs = await spoolFactory.createdRecordingIDs
        let pendingIDs = await MainActor.run { coordinator.pendingRecordingIDs }
        XCTAssertEqual(pendingIDs, createdIDs)
        let phase = await MainActor.run { coordinator.phase }
        guard case .needsAttention = phase else {
            return XCTFail("source stop failure must preserve the spool for recovery")
        }
    }

    func testCoordinatorMissingRequiredTrackNeverSeals() async {
        let source = FakeRecordingCaptureSource(
            finalEventOnStop: .failure(.requiredTracksMissing)
        )
        let spool = OrderedFakeRecordingSpool()
        let spoolFactory = RecoveryTrackingSpoolFactory(spool: spool)
        let coordinator = await MainActor.run {
            RecordingCoordinator(
                preflight: FakeRecordingPreflight(),
                source: source,
                spoolFactory: spoolFactory
            )
        }
        await coordinator.start()

        await coordinator.stop()

        let operations = await spool.operations()
        XCTAssertFalse(operations.contains(.seal))
        let createdIDs = await spoolFactory.createdRecordingIDs
        let pendingIDs = await MainActor.run { coordinator.pendingRecordingIDs }
        XCTAssertEqual(pendingIDs, createdIDs)
        let phase = await MainActor.run { coordinator.phase }
        guard case .needsAttention = phase else {
            return XCTFail("missing startup track must preserve the unsealed spool")
        }
    }

    private func temporaryDirectory() throws -> URL {
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent(
                "tamforge-recording-tests-\(UUID().uuidString)", isDirectory: true
            )
        try FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: url) }
        return url
    }

    private func fileSize(_ url: URL) throws -> Int64 {
        let attributes = try FileManager.default.attributesOfItem(atPath: url.path)
        return try XCTUnwrap(attributes[.size] as? NSNumber).int64Value
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
        byte: UInt8 = 0,
        initialRoute: String = "Test Route",
        conversionVersion: Int = 1
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
                initialRoute: initialRoute,
                conversionVersion: conversionVersion,
                presentationNanoseconds: presentationNanoseconds
            ),
            payload: Data(repeating: byte, count: sampleCount * channels * 2)
        )
    }
}

private extension RecordingCapturePipeline {
    mutating func bufferSystemStartupAnchor(
        at presentationNanoseconds: Int64
    ) throws -> [RecordingCaptureEvent] {
        try acceptDroppedSourceInterval(.init(
            track: .systemAudio,
            startPresentationNanoseconds: presentationNanoseconds,
            endPresentationNanoseconds: presentationNanoseconds + 1
        ), reason: .callbackOverflow)
    }
}

private extension Array where Element == RecordingCaptureEvent {
    var recordingChunks: [RecordingPCMChunk] {
        compactMap { event in
            guard case let .chunk(chunk) = event else { return nil }
            return chunk
        }
    }

    var recordingGaps: [RecordingGap] {
        compactMap { event in
            guard case let .gap(gap) = event else { return nil }
            return gap
        }
    }

    var recordingFailures: [RecordingCaptureFailure] {
        compactMap { event in
            guard case let .failure(failure) = event else { return nil }
            return failure
        }
    }

    var recordingLevels: [(track: RecordingTrackKind, normalized: Double)] {
        compactMap { event in
            guard case let .level(track, normalized) = event else { return nil }
            return (track, normalized)
        }
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
    private let stopFailure: RecordingCaptureFailure?
    private let finalEventOnStop: RecordingCaptureEvent?
    private var receive: (@Sendable (RecordingCaptureEvent) -> Void)?

    init(
        startFailure: RecordingCaptureFailure? = nil,
        stopFailure: RecordingCaptureFailure? = nil,
        finalEventOnStop: RecordingCaptureEvent? = nil
    ) {
        self.startFailure = startFailure
        self.stopFailure = stopFailure
        self.finalEventOnStop = finalEventOnStop
    }

    func start(
        microphoneID: String?,
        initialRoute: String,
        receive: @escaping @Sendable (RecordingCaptureEvent) -> Void
    ) async throws {
        startCount += 1
        if let startFailure { throw startFailure }
        self.receive = receive
    }

    func stop() async throws {
        stopCount += 1
        if let finalEventOnStop { receive?(finalEventOnStop) }
        receive = nil
        if let stopFailure { throw stopFailure }
    }

}

private struct FakeRecordingPreflight: RecordingPreflighting {
    func run() async -> RecordingPreflightResult { .ready(.fixture) }
}

private actor FakeRecordingSpoolFactory: RecordingSpoolCreating {
    private(set) var createdRecordingIDs: [UUID] = []
    private(set) var discardedRecordingIDs: [UUID] = []

    func create(recordingID: UUID) async throws -> any RecordingSpoolWriting {
        createdRecordingIDs.append(recordingID)
        return FakeRecordingSpool()
    }

    func pendingRecordingIDs() async -> [UUID] { [] }
    func discard(recordingID: UUID) async throws { discardedRecordingIDs.append(recordingID) }
}

private struct SingleRecordingSpoolFactory: RecordingSpoolCreating {
    let spool: OrderedFakeRecordingSpool

    func create(recordingID: UUID) async throws -> any RecordingSpoolWriting { spool }
    func pendingRecordingIDs() async -> [UUID] { [] }
    func discard(recordingID: UUID) async throws {}
}

private actor RecoveryTrackingSpoolFactory: RecordingSpoolCreating {
    let spool: any RecordingSpoolWriting
    private(set) var createdRecordingIDs: [UUID] = []

    init(spool: any RecordingSpoolWriting) { self.spool = spool }

    func create(recordingID: UUID) async throws -> any RecordingSpoolWriting {
        createdRecordingIDs.append(recordingID)
        return spool
    }

    func pendingRecordingIDs() async -> [UUID] { createdRecordingIDs }
    func discard(recordingID: UUID) async throws {}
}

private actor FakeRecordingSpool: RecordingSpoolWriting {
    func append(_ chunk: RecordingPCMChunk) async throws {}
    func record(gap: RecordingGap) async throws {}
    func seal(gaps: [RecordingGap], startedAt: Date, endedAt: Date) async throws {}
}

private actor OrderedFakeRecordingSpool: RecordingSpoolWriting {
    enum Operation: Equatable {
        case chunk(RecordingPCMChunk)
        case gap(RecordingGap)
        case seal
    }

    private var recordedOperations: [Operation] = []

    func append(_ chunk: RecordingPCMChunk) async throws { recordedOperations.append(.chunk(chunk)) }
    func record(gap: RecordingGap) async throws { recordedOperations.append(.gap(gap)) }
    func seal(gaps: [RecordingGap], startedAt: Date, endedAt: Date) async throws { recordedOperations.append(.seal) }
    func operations() -> [Operation] { recordedOperations }
}

private actor GatedFakeRecordingSpool: RecordingSpoolWriting {
    private var recordedOperations: [OrderedFakeRecordingSpool.Operation] = []
    private var firstWriteStarted = false
    private var writesReleased = false
    private var firstWriteWaiter: CheckedContinuation<Void, Never>?
    private var gate: CheckedContinuation<Void, Never>?

    func append(_ chunk: RecordingPCMChunk) async throws {}

    func record(gap: RecordingGap) async throws {
        if !firstWriteStarted {
            firstWriteStarted = true
            firstWriteWaiter?.resume()
            firstWriteWaiter = nil
        }
        if !writesReleased {
            await withCheckedContinuation { continuation in gate = continuation }
        }
        recordedOperations.append(.gap(gap))
    }

    func seal(gaps: [RecordingGap], startedAt: Date, endedAt: Date) async throws {
        recordedOperations.append(.seal)
    }

    func waitUntilFirstWrite() async {
        if firstWriteStarted { return }
        await withCheckedContinuation { continuation in firstWriteWaiter = continuation }
    }

    func releaseWrites() {
        writesReleased = true
        gate?.resume()
        gate = nil
    }

    func operations() -> [OrderedFakeRecordingSpool.Operation] { recordedOperations }
}

private actor FailingFakeRecordingSpool: RecordingSpoolWriting {
    private(set) var recordAttempts = 0

    func append(_ chunk: RecordingPCMChunk) async throws {}
    func record(gap: RecordingGap) async throws {
        recordAttempts += 1
        throw RecordingSpoolError.invalidRecord
    }
    func seal(gaps: [RecordingGap], startedAt: Date, endedAt: Date) async throws {}
}

private actor WriteFailingRecordingSpool: RecordingSpoolWriting {
    enum Failure: Equatable {
        case append
        case gap
    }

    private let failure: Failure
    private(set) var sealAttempts = 0

    init(failure: Failure) { self.failure = failure }

    func append(_ chunk: RecordingPCMChunk) async throws {
        if failure == .append { throw RecordingSpoolError.invalidRecord }
    }

    func record(gap: RecordingGap) async throws {
        if failure == .gap { throw RecordingSpoolError.invalidRecord }
    }

    func seal(gaps: [RecordingGap], startedAt: Date, endedAt: Date) async throws { sealAttempts += 1 }
}
