import CryptoKit
import Foundation
import XCTest

final class RecordingUploadTests: XCTestCase {
    func testPreparedPartIsDeterministicFileBackedAndDetectsMutation() async throws {
        let root = try temporaryDirectory()
        let recordingID = UUID()
        let record = try recoveredRecord(recordingID: recordingID, track: .microphone)
        let key = SymmetricKey(data: Data(repeating: 7, count: 32))
        let builder = RecordingUploadPartBuilder()

        let first = try builder.prepare(
            record: record,
            uploadSequence: 0,
            rootKey: key,
            directoryURL: root
        )
        let firstBytes = try Data(contentsOf: first.fileURL)
        let second = try builder.prepare(
            record: record,
            uploadSequence: 0,
            rootKey: key,
            directoryURL: root
        )

        XCTAssertEqual(firstBytes, try Data(contentsOf: second.fileURL))
        XCTAssertNotEqual(firstBytes, record.payload)
        XCTAssertEqual(first.headers["X-TAM-Part-Key"]?.count, 43)
        XCTAssertFalse(first.headers.values.contains(key.data.base64EncodedString()))
        try second.verifyFileIdentity()

        try FileManager.default.setAttributes(
            [.posixPermissions: 0o600],
            ofItemAtPath: second.fileURL.path
        )
        let handle = try FileHandle(forUpdating: second.fileURL)
        try handle.seek(toOffset: 0)
        try handle.write(contentsOf: Data([firstBytes[0] ^ 0xff]))
        try handle.synchronize()
        try handle.close()
        try FileManager.default.setAttributes(
            [.posixPermissions: 0o400],
            ofItemAtPath: second.fileURL.path
        )
        XCTAssertThrowsError(try second.verifyFileIdentity())
    }

    func testPartKeyEncodingRejectsNoncanonicalTrailingCharacter() {
        let canonical = String(repeating: "A", count: 43)
        XCTAssertTrue(RecordingPartKeyEncoding.isCanonical(canonical))
        XCTAssertFalse(RecordingPartKeyEncoding.isCanonical(
            String(repeating: "A", count: 42) + "B"
        ))
        XCTAssertFalse(RecordingPartKeyEncoding.isCanonical(canonical + "="))
        XCTAssertFalse(RecordingPartKeyEncoding.isCanonical(String(repeating: "A", count: 42)))
    }

    func testGrouperEmitsSixtySecondAndPartialPartsWithoutCrossingTrackBoundaries() throws {
        let recordingID = UUID()
        var grouper = RecordingUploadPartGrouper(maximumSampleCount: 48 * 60)
        var groups: [RecoveredSpoolRecord] = []

        for index in 0..<61 {
            let record = try recoveredRecord(
                recordingID: recordingID,
                track: .microphone,
                sampleStart: Int64(index * 48)
            )
            if let completed = grouper.append(record) { groups.append(completed) }
        }
        if let completed = grouper.finish() { groups.append(completed) }

        XCTAssertEqual(groups.map(\.chunk.sampleCount), [48 * 60, 48])
        XCTAssertEqual(groups.map(\.chunk.sampleStart), [0, Int64(48 * 60)])
        XCTAssertEqual(groups.map(\.payload.count), [48 * 60 * 2, 48 * 2])
    }

    func testLineageCoalescesContiguousEqualSourceAndSplitsOnRouteChange() throws {
        let recordingID = UUID()
        var coalescer = RecordingSourceLineageCoalescer()

        try coalescer.append(record: recoveredRecord(
            recordingID: recordingID, track: .microphone, sampleStart: 0
        ))
        try coalescer.append(record: recoveredRecord(
            recordingID: recordingID, track: .microphone, sampleStart: 48,
            presentationNanoseconds: 1_001_000_000
        ))
        try coalescer.append(record: recoveredRecord(
            recordingID: recordingID, track: .microphone, sampleStart: 96,
            presentationNanoseconds: 1_002_000_000, route: "Different Route"
        ))
        // A gap always splits lineage because coverage is no longer contiguous.
        try coalescer.append(record: recoveredRecord(
            recordingID: recordingID, track: .microphone, sampleStart: 240,
            presentationNanoseconds: 1_005_000_000, route: "Different Route"
        ))
        let segments = coalescer.finish()

        XCTAssertEqual(segments.map(\.sampleStart), [0, 96, 240])
        XCTAssertEqual(segments.map(\.sampleCount), [96, 48, 48])
        XCTAssertEqual(
            segments.map(\.route),
            ["Fixture Route", "Different Route", "Different Route"]
        )
        XCTAssertEqual(segments.map(\.presentationTimeStart), [
            1_000_000_000, 1_002_000_000, 1_005_000_000,
        ])
        XCTAssertEqual(
            segments.map(\.presentationTimeTimescale),
            [1_000_000_000, 1_000_000_000, 1_000_000_000]
        )
    }

    func testLineagePresentationEndUsesExactCanonicalDuration() throws {
        var coalescer = RecordingSourceLineageCoalescer()
        try coalescer.append(record: recoveredRecord(
            recordingID: UUID(), track: .microphone, sampleStart: 0
        ))
        let segments = coalescer.finish()

        XCTAssertEqual(
            segments.map { $0.presentationTimeEnd - $0.presentationTimeStart },
            [Int64(48) * 1_000_000_000 / 48_000]
        )
        XCTAssertEqual(segments.map(\.conversionVersion), ["tamforge-pcm16-v1"])
    }

    func testLineageTruncatesIdentityStringsToServerLimit() throws {
        var coalescer = RecordingSourceLineageCoalescer()
        try coalescer.append(record: recoveredRecord(
            recordingID: UUID(), track: .microphone, sampleStart: 0,
            route: String(repeating: "r", count: 300)
        ))
        let segments = coalescer.finish()

        XCTAssertEqual(segments.map(\.route), [String(repeating: "r", count: 256)])
    }

    func testLineageFailsClosedOnUnknownConversionVersion() throws {
        var coalescer = RecordingSourceLineageCoalescer()
        XCTAssertThrowsError(try coalescer.append(record: recoveredRecord(
            recordingID: UUID(), track: .microphone, sampleStart: 0, conversionVersion: 2
        )))
    }

    func testCanonicalJSONEscapesNonASCIIExactlyLikeThePythonContract() throws {
        let encoded = try RecordingCanonicalJSON.encode([
            "route": "Kopfhörer",
            "clef": "𝄞",
        ])
        let text = try XCTUnwrap(String(data: encoded, encoding: .utf8))

        XCTAssertEqual(text, #"{"clef":"\ud834\udd1e","route":"Kopfh\u00f6rer"}"#)
        XCTAssertTrue(encoded.allSatisfy { $0 < 0x80 })
    }

    func testTimelineHashMatchesBackendGoldenFixture() throws {
        let fixtureURL = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .appendingPathComponent("backend/tests/fixtures/recordings/recording-manifest-v1.json")
        let manifest = try JSONDecoder().decode(
            GoldenManifestFixture.self,
            from: Data(contentsOf: fixtureURL)
        )

        XCTAssertEqual(manifest.tracks.count, 2)
        for track in manifest.tracks {
            XCTAssertEqual(
                try RecordingTrackManifestPayload.timelineSHA256(of: track),
                track.timelineSHA256
            )
        }
    }

    func testJournalReconstructsInflightAsPendingWithoutPersistingHeaders() async throws {
        let root = try temporaryDirectory()
        let part = try RecordingUploadPartBuilder().prepare(
            record: recoveredRecord(recordingID: UUID(), track: .systemAudio),
            uploadSequence: 0,
            rootKey: SymmetricKey(data: Data(repeating: 4, count: 32)),
            directoryURL: root
        )
        let journal = try RecordingUploadJournal(directoryURL: root)
        try await journal.begin(part: part)

        let relaunched = try RecordingUploadJournal(directoryURL: root)
        let state = await relaunched.snapshot()
        let persisted = try String(contentsOf: root.appendingPathComponent("upload-journal.json"))

        XCTAssertNil(state.inFlightPart)
        XCTAssertNil(state.inFlightFileIdentity)
        XCTAssertFalse(persisted.contains(part.partKeyBase64URL))
        XCTAssertFalse(persisted.contains("Authorization"))
    }

    func testLiveUploadRecreatesTaskWithRefreshedBearerAfter401() async throws {
        let root = try temporaryDirectory()
        let recordingID = UUID()
        let part = try RecordingUploadPartBuilder().prepare(
            record: recoveredRecord(recordingID: recordingID, track: .microphone),
            uploadSequence: 0,
            rootKey: SymmetricKey(data: Data(repeating: 3, count: 32)),
            directoryURL: root
        )
        let fixture = URLProtocolFixture()
        fixture.enqueue(.response(
            statusCode: 401,
            body: Data(#"{"title":"Authentication required","status":401}"#.utf8)
        ))
        fixture.enqueue(.response(
            statusCode: 201,
            body: Data("""
            {"schema_version":1,"recording_id":"\(recordingID.uuidString.lowercased())",\
            "track_id":"\(part.trackID.uuidString.lowercased())","sequence":0,\
            "sample_start":0,"sample_count":48,"plaintext_sha256":"\(part.plaintextSHA256)",\
            "high_water_sample":48,"replayed":false}
            """.utf8)
        ))
        let refreshes = TokenRefreshRecorder()
        let client = LiveRecordingServerClient(
            baseURL: URL(string: "https://api.example.test")!,
            bearerToken: {
                .init(token: "expired-token", sessionGeneration: 7)
            },
            refreshBearer: { lease in
                XCTAssertEqual(lease.sessionGeneration, 7)
                await refreshes.didRefresh()
                return .init(token: "fresh-token", sessionGeneration: 7)
            },
            session: fixture.session()
        )

        try await client.upload(part)

        XCTAssertEqual(fixture.requests.count, 2)
        XCTAssertEqual(
            fixture.requests.map { $0.value(forHTTPHeaderField: "Authorization") },
            ["Bearer expired-token", "Bearer fresh-token"]
        )
        let refreshCount = await refreshes.count
        XCTAssertEqual(refreshCount, 1)
        XCTAssertEqual(
            fixture.requests[1].value(forHTTPHeaderField: "X-TAM-Part-Key"),
            part.partKeyBase64URL
        )
    }

    func testSealedSpoolTraversesLiveHTTPRecoveryAndBothReleaseGates() async throws {
        let spool = try await sealedSpool()
        let fixture = URLProtocolFixture()
        let recordingID = spool.recordingID.uuidString.lowercased()
        let microphoneID = RecordingTrackIdentity.id(
            recordingID: spool.recordingID,
            track: .microphone
        ).uuidString.lowercased()
        let systemID = RecordingTrackIdentity.id(
            recordingID: spool.recordingID,
            track: .systemAudio
        ).uuidString.lowercased()
        let microphoneHash = sha256(Data(repeating: 1, count: 48 * 2))
        let systemHash = sha256(Data(repeating: 2, count: 48 * 2 * 2))
        let manifestHash = String(repeating: "a", count: 64)
        let makeClient = {
            LiveRecordingServerClient(
                baseURL: URL(string: "https://api.example.test")!,
                bearerToken: { .init(token: "live-token", sessionGeneration: 3) },
                refreshBearer: { _ in
                    throw NativeAuthenticationError.reauthenticationRequired
                },
                session: fixture.session()
            )
        }

        fixture.enqueue(.response(
            statusCode: 201,
            body: Data(
                #"{"schema_version":1,"recording_id":"\#(recordingID)","state":"reserved","replayed":false}"#.utf8
            )
        ))
        // The server accepted this PUT, but the process lost its receipt and exits.
        fixture.enqueue(.error(URLError(.networkConnectionLost)))
        let interrupted = RecordingUploadPipeline(
            spoolFactory: spool.factory,
            server: makeClient()
        )
        await XCTAssertAsyncThrowsError {
            _ = try await interrupted.upload(
                recordingID: spool.recordingID,
                progress: { _ in }
            )
        }
        XCTAssertEqual(fixture.requests.map(\.httpMethod), ["POST", "PUT"])
        XCTAssertTrue(FileManager.default.fileExists(atPath: spool.directory.path))

        for (trackID, hash, replayed) in [
            (microphoneID, microphoneHash, true),
            (systemID, systemHash, false),
        ] {
            fixture.enqueue(.response(
                statusCode: 201,
                body: Data(
                    #"{"schema_version":1,"recording_id":"\#(recordingID)","track_id":"\#(trackID)","sequence":0,"sample_start":0,"sample_count":48,"plaintext_sha256":"\#(hash)","high_water_sample":48,"replayed":\#(replayed)}"#.utf8
                )
            ))
        }
        fixture.enqueue(.response(
            statusCode: 201,
            body: Data(
                #"{"schema_version":1,"recording_id":"\#(recordingID)","state":"stored","coverage_status":"complete","track_manifest_sha256":["\#(manifestHash)","\#(manifestHash)"],"audio_created_on_server":true,"transcript_lineage_accepted":false,"replayed":false}"#.utf8
            )
        ))
        let relaunched = RecordingUploadPipeline(
            spoolFactory: spool.factory,
            server: makeClient()
        )
        let firstGates = try await relaunched.upload(
            recordingID: spool.recordingID,
            progress: { _ in }
        )
        XCTAssertEqual(
            fixture.requests.map(\.httpMethod),
            ["POST", "PUT", "PUT", "PUT", "POST"]
        )
        for header in [
            "Idempotency-Key", "X-TAM-Plaintext-SHA256", "X-TAM-Ciphertext-SHA256",
            "X-TAM-Part-Nonce", "X-TAM-Part-Key",
        ] {
            XCTAssertEqual(
                fixture.requests[1].value(forHTTPHeaderField: header),
                fixture.requests[2].value(forHTTPHeaderField: header)
            )
        }
        XCTAssertTrue(firstGates.audioCreatedOnServer)
        XCTAssertFalse(firstGates.transcriptLineageAccepted)
        XCTAssertTrue(FileManager.default.fileExists(atPath: spool.directory.path))

        fixture.enqueue(.response(
            statusCode: 200,
            body: Data(
                #"{"schema_version":1,"recording_id":"\#(recordingID)","state":"stored","coverage_status":"complete","tracks":[{"track_id":"\#(microphoneID)","kind":"microphone","high_water_sample":48,"stored_part_count":1,"gap_count":0,"manifest_sha256":"\#(manifestHash)"},{"track_id":"\#(systemID)","kind":"system_audio","high_water_sample":48,"stored_part_count":1,"gap_count":0,"manifest_sha256":"\#(manifestHash)"}],"audio_created_on_server":true,"transcript_lineage_accepted":true}"#.utf8
            )
        ))
        let statusRelaunch = RecordingUploadPipeline(
            spoolFactory: spool.factory,
            server: makeClient()
        )
        let finalGates = try await statusRelaunch.upload(
            recordingID: spool.recordingID,
            progress: { _ in }
        )

        XCTAssertTrue(finalGates.mayDeleteLocalSpool)
        XCTAssertFalse(FileManager.default.fileExists(atPath: spool.directory.path))
    }

    func testPipelineUploadsOnePartAtATimeAndKeepsSpoolAfterAudio201() async throws {
        let fixture = try await sealedSpool()
        let server = FakeRecordingServer()
        let pipeline = RecordingUploadPipeline(
            spoolFactory: fixture.factory,
            server: server
        )
        let progress = ProgressRecorder()

        let gates = try await pipeline.upload(
            recordingID: fixture.recordingID,
            progress: { count in Task { await progress.append(count) } }
        )
        let uploaded = await server.uploadedParts
        let metadata = try await EncryptedRecordingSpool.recoverMetadata(
            recordingID: fixture.recordingID,
            rootURL: fixture.factory.rootURL,
            keyStore: fixture.keyStore
        )

        XCTAssertEqual(uploaded.count, 2)
        XCTAssertEqual(Set(uploaded.map(\.track)), Set(RecordingTrackKind.allCases))
        XCTAssertTrue(gates.audioCreatedOnServer)
        XCTAssertFalse(gates.transcriptLineageAccepted)
        XCTAssertEqual(metadata.releaseGates, gates)
        XCTAssertTrue(FileManager.default.fileExists(atPath: fixture.directory.path))
    }

    func testSealCommandCarriesSourceLineageForUploadedAudioOnly() async throws {
        let fixture = try await sealedSpool()
        let server = FakeRecordingServer()
        let pipeline = RecordingUploadPipeline(spoolFactory: fixture.factory, server: server)

        _ = try await pipeline.upload(recordingID: fixture.recordingID, progress: { _ in })

        let sealCommands = await server.sealCommands
        let command = try XCTUnwrap(sealCommands.first)
        XCTAssertEqual(command.coverageStatus, "complete")
        XCTAssertEqual(command.tracks.map(\.kind), ["microphone", "system_audio"])
        for track in command.tracks {
            XCTAssertEqual(track.sourceLineage.map(\.sampleStart), [0])
            XCTAssertEqual(track.sourceLineage.map(\.sampleCount), [48])
            XCTAssertEqual(track.sourceLineage.map(\.conversionVersion), ["tamforge-pcm16-v1"])
            XCTAssertEqual(track.sourceLineage.map(\.presentationTimeTimescale), [1_000_000_000])
        }
    }

    func testReaderBlocksUploadBeforeAnyServerCallOnSealedAlignedTruncation() async throws {
        let fixture = try await sealedSpool()
        let trackURL = fixture.directory.appendingPathComponent("microphone.tfr")
        let bytes = try Data(contentsOf: trackURL)
        let firstLength = Int(bytes.prefix(4).reduce(0) { ($0 << 8) | Int($1) })
        // Keep zero complete records: drop the whole aligned record suffix.
        XCTAssertEqual(bytes.count, 4 + firstLength)
        try Data().write(to: trackURL, options: .atomic)
        let server = FakeRecordingServer()
        let pipeline = RecordingUploadPipeline(spoolFactory: fixture.factory, server: server)

        await XCTAssertAsyncThrowsError {
            _ = try await pipeline.upload(recordingID: fixture.recordingID, progress: { _ in })
        }

        let createCalls = await server.createCalls
        let uploadAttempts = await server.uploadAttempts
        XCTAssertEqual(createCalls, 0)
        XCTAssertEqual(uploadAttempts, 0)
        XCTAssertTrue(FileManager.default.fileExists(atPath: fixture.directory.path))
    }

    func testReaderBlocksUploadOnMissingSealedTrackFile() async throws {
        let fixture = try await sealedSpool()
        try FileManager.default.removeItem(
            at: fixture.directory.appendingPathComponent("system-audio.tfr")
        )
        let server = FakeRecordingServer()
        let pipeline = RecordingUploadPipeline(spoolFactory: fixture.factory, server: server)

        await XCTAssertAsyncThrowsError {
            _ = try await pipeline.upload(recordingID: fixture.recordingID, progress: { _ in })
        }

        let createCalls = await server.createCalls
        XCTAssertEqual(createCalls, 0)
        XCTAssertTrue(FileManager.default.fileExists(atPath: fixture.directory.path))
    }

    func testCorruptCiphertextWithMatchingCheckpointBecomesExplicitManifestGap() async throws {
        let fixture = try await sealedSpool()
        let trackURL = fixture.directory.appendingPathComponent("system-audio.tfr")
        var bytes = try Data(contentsOf: trackURL)
        bytes[bytes.index(before: bytes.endIndex)] ^= 0xff
        try bytes.write(to: trackURL, options: .atomic)
        let server = FakeRecordingServer()
        let pipeline = RecordingUploadPipeline(spoolFactory: fixture.factory, server: server)

        let gates = try await pipeline.upload(
            recordingID: fixture.recordingID, progress: { _ in }
        )

        XCTAssertTrue(gates.audioCreatedOnServer)
        let uploaded = await server.uploadedParts
        XCTAssertEqual(uploaded.map(\.track), [.microphone])
        let sealCommands = await server.sealCommands
        let command = try XCTUnwrap(sealCommands.first)
        XCTAssertEqual(command.coverageStatus, "stored_with_gaps")
        let system = try XCTUnwrap(command.tracks.first { $0.kind == "system_audio" })
        XCTAssertTrue(system.parts.isEmpty)
        XCTAssertEqual(system.gaps.map(\.sampleStart), [0])
        XCTAssertEqual(system.gaps.map(\.sampleCount), [48])
        XCTAssertEqual(system.gaps.map(\.reason), ["corrupt_spool_record"])
        XCTAssertTrue(system.sourceLineage.isEmpty)
        let microphone = try XCTUnwrap(command.tracks.first { $0.kind == "microphone" })
        XCTAssertEqual(microphone.sourceLineage.map(\.sampleCount), [48])
    }

    func testUploadFailsClosedOnUnknownConversionVersionBeforeAnyServerCall() async throws {
        let root = try temporaryDirectory()
        let keyStore = UploadTestKeyStore()
        let factory = EncryptedRecordingSpoolFactory(
            rootURL: root,
            keyStore: keyStore,
            reservationBytes: 0
        )
        let recordingID = UUID()
        let spool = try await factory.create(recordingID: recordingID)
        try await spool.append(try chunk(track: .microphone, conversionVersion: 2))
        try await spool.append(try chunk(track: .systemAudio))
        try await spool.seal(gaps: [], startedAt: Date(), endedAt: Date())
        let server = FakeRecordingServer()
        let pipeline = RecordingUploadPipeline(spoolFactory: factory, server: server)

        await XCTAssertAsyncThrowsError {
            _ = try await pipeline.upload(recordingID: recordingID, progress: { _ in })
        }

        let createCalls = await server.createCalls
        XCTAssertEqual(createCalls, 0)
    }

    func testRelaunchUsesServerStatusAndReleasesOnlyAfterTranscriptLineage() async throws {
        let fixture = try await sealedSpool()
        let server = FakeRecordingServer()
        let pipeline = RecordingUploadPipeline(spoolFactory: fixture.factory, server: server)
        _ = try await pipeline.upload(recordingID: fixture.recordingID, progress: { _ in })
        await server.acceptTranscript(recordingID: fixture.recordingID)

        let gates = try await RecordingUploadPipeline(
            spoolFactory: fixture.factory,
            server: server
        ).upload(recordingID: fixture.recordingID, progress: { _ in })

        XCTAssertTrue(gates.mayDeleteLocalSpool)
        XCTAssertFalse(FileManager.default.fileExists(atPath: fixture.directory.path))
        await XCTAssertAsyncThrowsError {
            _ = try await fixture.keyStore.load(recordingID: fixture.recordingID)
        }
    }

    func testSubmissionRejectedBeforeAudioReadyIsRetriedAndEventuallySucceeds() async throws {
        let fixture = try await sealedSpool()
        let server = FakeRecordingServer(requireAudioBeforeTranscript: true)
        let cache = RecordingTranscriptCache()
        let payload = TranscriptSubmitPayload.fixture(recordingID: fixture.recordingID)
        await cache.store(payload, recordingID: fixture.recordingID)

        // Represents the coordinator's opportunistic attempt firing the
        // instant local transcription finishes, which can easily race
        // ahead of the audio pipeline's create/seal for a recording of any
        // meaningful length. The backend's transcript_lineage_requires_audio
        // constraint (modeled here by requireAudioBeforeTranscript) rejects
        // it, exactly like the 409 described in issue #44's own trace.
        await XCTAssertAsyncThrowsError {
            _ = try await server.submitTranscript(payload, idempotencyKey: payload.idempotencyKey)
        }
        let submittedBeforeAudio = await server.submittedTranscripts
        XCTAssertTrue(submittedBeforeAudio.isEmpty)

        let pipeline = RecordingUploadPipeline(
            spoolFactory: fixture.factory, server: server, transcriptCache: cache
        )

        // First worker pass: creates + seals the audio (this recording's
        // gates start with audioCreatedOnServer false, so this is the
        // create/upload/seal branch, not the retry branch). A submission
        // attempt only ever happens after create/seal complete, never
        // during them, so nothing is (re)submitted on this same pass.
        let firstPass = try await pipeline.upload(recordingID: fixture.recordingID, progress: { _ in })
        XCTAssertTrue(firstPass.audioCreatedOnServer)
        XCTAssertFalse(firstPass.transcriptLineageAccepted)

        // Next worker pass: audio now exists, so the status-recheck branch
        // retries the same cached, still-unaccepted submission using the
        // same idempotency key. This time the server accepts it, and the
        // spool releases.
        let secondPass = try await pipeline.upload(recordingID: fixture.recordingID, progress: { _ in })
        XCTAssertTrue(secondPass.mayDeleteLocalSpool)
        let attemptsAfterSecondPass = await server.submissionAttempts
        XCTAssertEqual(attemptsAfterSecondPass, 2)
        let acceptedSubmissions = await server.submittedTranscripts
        XCTAssertEqual(acceptedSubmissions.count, 1)
        XCTAssertFalse(FileManager.default.fileExists(atPath: fixture.directory.path))
    }

    func testTransientSubmissionFailureIsRetriedRatherThanAbandoned() async throws {
        let fixture = try await sealedSpool()
        let server = FakeRecordingServer(failSubmission: true)
        let cache = RecordingTranscriptCache()
        let payload = TranscriptSubmitPayload.fixture(recordingID: fixture.recordingID)
        await cache.store(payload, recordingID: fixture.recordingID)
        let pipeline = RecordingUploadPipeline(
            spoolFactory: fixture.factory, server: server, transcriptCache: cache
        )

        // First pass creates + seals; audio now exists. Nothing is
        // submitted yet (the retry branch has not run).
        let firstPass = try await pipeline.upload(recordingID: fixture.recordingID, progress: { _ in })
        XCTAssertTrue(firstPass.audioCreatedOnServer)
        let attemptsAfterFirstPass = await server.submissionAttempts
        XCTAssertEqual(attemptsAfterFirstPass, 0)

        // Second pass: the retry branch resubmits the cached payload, but
        // the configured transient failure rejects it. The pass must still
        // complete with accurate, unaccepted gates rather than abandon the
        // recording, and the spool must survive.
        let secondPass = try await pipeline.upload(recordingID: fixture.recordingID, progress: { _ in })
        XCTAssertFalse(secondPass.transcriptLineageAccepted)
        XCTAssertFalse(secondPass.mayDeleteLocalSpool)
        let attemptsAfterFailedRetry = await server.submissionAttempts
        XCTAssertEqual(attemptsAfterFailedRetry, 1)
        XCTAssertTrue(FileManager.default.fileExists(atPath: fixture.directory.path))

        // The transient condition clears. A later pass retries the exact
        // same cached payload -- never abandoned -- and this time succeeds.
        await server.setFailSubmission(false)
        let thirdPass = try await pipeline.upload(recordingID: fixture.recordingID, progress: { _ in })
        XCTAssertTrue(thirdPass.mayDeleteLocalSpool)
        let attemptsAfterSuccessfulRetry = await server.submissionAttempts
        XCTAssertEqual(attemptsAfterSuccessfulRetry, 2)
        let acceptedSubmissions = await server.submittedTranscripts
        XCTAssertEqual(acceptedSubmissions.count, 1)
        XCTAssertFalse(FileManager.default.fileExists(atPath: fixture.directory.path))
    }

    func testPermanentTranscriptRejectionDropsTheCacheAndStopsRetryingInsteadOfLoopingForever() async throws {
        let fixture = try await sealedSpool()
        let server = FakeRecordingServer(failSubmissionPermanently: true)
        let cache = RecordingTranscriptCache()
        let payload = TranscriptSubmitPayload.fixture(recordingID: fixture.recordingID)
        await cache.store(payload, recordingID: fixture.recordingID)
        let pipeline = RecordingUploadPipeline(
            spoolFactory: fixture.factory, server: server, transcriptCache: cache
        )

        // First pass creates + seals; audio now exists. Nothing is
        // submitted yet (the retry branch has not run).
        let firstPass = try await pipeline.upload(recordingID: fixture.recordingID, progress: { _ in })
        XCTAssertTrue(firstPass.audioCreatedOnServer)
        XCTAssertEqual(await server.submissionAttempts, 0)

        // Second pass: the retry branch submits the cached payload, the
        // server permanently rejects it (422) -- unlike a transient
        // failure, this must propagate rather than being swallowed, so the
        // caller sees a real failure instead of a silently-incomplete
        // "waiting for transcript" pass (Important 3).
        await XCTAssertAsyncThrowsError {
            _ = try await pipeline.upload(recordingID: fixture.recordingID, progress: { _ in })
        }
        XCTAssertEqual(await server.submissionAttempts, 1)
        let cachedAfterRejection = await cache.payload(for: fixture.recordingID)
        XCTAssertNil(cachedAfterRejection)

        // Third pass: the cache entry is gone, so the retry branch has
        // nothing left to resubmit -- submissionAttempts must not climb
        // again. This is the "instead of an infinite retry" half of
        // Important 3: a permanently rejected body stops being resent,
        // rather than every later pass repeating the same doomed POST.
        let thirdPass = try await pipeline.upload(recordingID: fixture.recordingID, progress: { _ in })
        XCTAssertFalse(thirdPass.transcriptLineageAccepted)
        XCTAssertEqual(await server.submissionAttempts, 1)
    }

    // Regression coverage for the fix that narrowed isPermanentTranscriptRejection:
    // it used to treat every `.server(400...499)` as permanent, which put 404 in
    // range alongside 422. A 404 here means the recording row does not exist yet
    // from the submission's point of view -- exactly the race
    // RecordingCoordinator.submitTranscript's own doc comment names, since it fires
    // as soon as transcription finishes, in parallel with the create/upload/seal
    // pass the same stop() call started. Misclassifying it as permanent drops the
    // only copy of the cached payload (memory-only, and beginTranscription is
    // reachable only from stop()) with no way to recompute it, so the encrypted
    // spool would never release -- the exact defect this whole feature exists to
    // fix, reintroduced on a path that used to self-heal.
    func testRecordingNotFoundTranscriptRejectionKeepsRetryingInsteadOfDroppingTheCache() async throws {
        let fixture = try await sealedSpool()
        let server = FakeRecordingServer(failSubmissionWithRecordingNotFound: true)
        let cache = RecordingTranscriptCache()
        let payload = TranscriptSubmitPayload.fixture(recordingID: fixture.recordingID)
        await cache.store(payload, recordingID: fixture.recordingID)
        let pipeline = RecordingUploadPipeline(
            spoolFactory: fixture.factory, server: server, transcriptCache: cache
        )

        // First pass creates + seals; audio now exists. Nothing is
        // submitted yet (the retry branch has not run).
        let firstPass = try await pipeline.upload(recordingID: fixture.recordingID, progress: { _ in })
        XCTAssertTrue(firstPass.audioCreatedOnServer)
        XCTAssertEqual(await server.submissionAttempts, 0)

        // Second pass: the retry branch submits the cached payload and the
        // server returns 404. Unlike the real permanent-rejection test
        // above, this must be swallowed exactly like a transient failure
        // (no throw here, unlike that test's XCTAssertAsyncThrowsError),
        // and -- the crux of this regression test -- the cached payload
        // must survive so a later pass still has something to resubmit.
        let secondPass = try await pipeline.upload(recordingID: fixture.recordingID, progress: { _ in })
        XCTAssertFalse(secondPass.transcriptLineageAccepted)
        XCTAssertFalse(secondPass.mayDeleteLocalSpool)
        XCTAssertEqual(await server.submissionAttempts, 1)
        let cachedAfterRejection = await cache.payload(for: fixture.recordingID)
        XCTAssertNotNil(cachedAfterRejection)

        // Third pass: the payload is still cached, so the retry branch
        // resubmits it again on the worker's ordinary cadence --
        // submissionAttempts climbs to 2, proving this keeps retrying
        // rather than being dropped after one failure.
        let thirdPass = try await pipeline.upload(recordingID: fixture.recordingID, progress: { _ in })
        XCTAssertFalse(thirdPass.transcriptLineageAccepted)
        XCTAssertEqual(await server.submissionAttempts, 2)
        let cachedAfterThirdPass = await cache.payload(for: fixture.recordingID)
        XCTAssertNotNil(cachedAfterThirdPass)
    }

    func testRelaunchAfterAudio201WithoutTranscriptKeepsSpoolAndNeverResubmitsParts() async throws {
        let fixture = try await sealedSpool()
        let server = FakeRecordingServer()
        _ = try await RecordingUploadPipeline(spoolFactory: fixture.factory, server: server)
            .upload(recordingID: fixture.recordingID, progress: { _ in })
        let attemptsAfterFirstRun = await server.uploadAttempts

        let gates = try await RecordingUploadPipeline(
            spoolFactory: fixture.factory,
            server: server
        ).upload(recordingID: fixture.recordingID, progress: { _ in })

        XCTAssertTrue(gates.audioCreatedOnServer)
        XCTAssertFalse(gates.transcriptLineageAccepted)
        XCTAssertFalse(gates.mayDeleteLocalSpool)
        let uploadAttempts = await server.uploadAttempts
        XCTAssertEqual(uploadAttempts, attemptsAfterFirstRun)
        let createCalls = await server.createCalls
        XCTAssertEqual(createCalls, 1)
        let sealCommands = await server.sealCommands
        XCTAssertEqual(sealCommands.count, 1)
        XCTAssertTrue(FileManager.default.fileExists(atPath: fixture.directory.path))
        _ = try await fixture.keyStore.load(recordingID: fixture.recordingID)
    }

    func testOfflineFailureLeavesSpoolAndDeterministicRetryConverges() async throws {
        let fixture = try await sealedSpool()
        let server = FakeRecordingServer(failureOnUploadAttempt: 2)
        let pipeline = RecordingUploadPipeline(spoolFactory: fixture.factory, server: server)

        await XCTAssertAsyncThrowsError {
            _ = try await pipeline.upload(recordingID: fixture.recordingID, progress: { _ in })
        }
        XCTAssertTrue(FileManager.default.fileExists(atPath: fixture.directory.path))

        let gates = try await pipeline.upload(
            recordingID: fixture.recordingID,
            progress: { _ in }
        )
        XCTAssertTrue(gates.audioCreatedOnServer)
        let uploadedParts = await server.uploadedParts
        XCTAssertEqual(uploadedParts.count, 2)
        XCTAssertEqual(Set(uploadedParts.map(\.track)), Set(RecordingTrackKind.allCases))
        let uploadAttempts = await server.uploadAttempts
        XCTAssertEqual(uploadAttempts, 3)
    }

    func testServerConflictPreservesEncryptedSpoolForRecovery() async throws {
        let fixture = try await sealedSpool()
        let server = FakeRecordingServer(
            failureOnUploadAttempt: 1,
            uploadFailure: .conflict
        )
        let pipeline = RecordingUploadPipeline(spoolFactory: fixture.factory, server: server)

        do {
            _ = try await pipeline.upload(recordingID: fixture.recordingID, progress: { _ in })
            XCTFail("Expected immutable server conflict")
        } catch let error as RecordingUploadError {
            XCTAssertEqual(error, .conflict)
        }

        XCTAssertTrue(FileManager.default.fileExists(atPath: fixture.directory.path))
        _ = try await fixture.keyStore.load(recordingID: fixture.recordingID)
    }

    func testCancellationPreservesSpoolAndReturnsUploadToPendingRecovery() async throws {
        let fixture = try await sealedSpool()
        let server = FakeRecordingServer(blockUploads: true)
        let pipeline = RecordingUploadPipeline(spoolFactory: fixture.factory, server: server)
        let task = Task {
            try await pipeline.upload(recordingID: fixture.recordingID, progress: { _ in })
        }
        for _ in 0..<100 {
            if await server.uploadAttempts > 0 { break }
            await Task.yield()
        }

        task.cancel()
        do {
            _ = try await task.value
            XCTFail("Expected cancellation")
        } catch is CancellationError {}

        XCTAssertTrue(FileManager.default.fileExists(atPath: fixture.directory.path))
        _ = try await fixture.keyStore.load(recordingID: fixture.recordingID)
    }

    func testManifestRejectsHiddenTimelineHole() throws {
        let recordingID = UUID()
        let descriptor = RecordingPartDescriptorPayload(
            sequence: 0,
            sampleStart: 48_000,
            sampleCount: 48_000,
            byteLength: 96_000,
            plaintextSHA256: String(repeating: "a", count: 64)
        )

        XCTAssertThrowsError(
            try RecordingTrackManifestPayload.make(
                recordingID: recordingID,
                track: .microphone,
                parts: [descriptor],
                gaps: [],
                sourceLineage: [],
                pcmSHA256: String(repeating: "b", count: 64)
            ))
    }

    func testManifestRejectsLineageThatDoesNotCoverUploadedAudioExactly() throws {
        let recordingID = UUID()
        let descriptor = RecordingPartDescriptorPayload(
            sequence: 0,
            sampleStart: 0,
            sampleCount: 48_000,
            byteLength: 96_000,
            plaintextSHA256: String(repeating: "a", count: 64)
        )

        XCTAssertThrowsError(
            try RecordingTrackManifestPayload.make(
                recordingID: recordingID,
                track: .microphone,
                parts: [descriptor],
                gaps: [],
                sourceLineage: [],
                pcmSHA256: String(repeating: "b", count: 64)
            ))
        XCTAssertThrowsError(
            try RecordingTrackManifestPayload.make(
                recordingID: recordingID,
                track: .microphone,
                parts: [descriptor],
                gaps: [],
                sourceLineage: [
                    .init(
                        sampleStart: 0,
                        sampleCount: 24_000,
                        sourceSampleRateHz: 48_000,
                        sourceChannelCount: 1,
                        deviceID: "fixture-microphone",
                        route: "Fixture Route",
                        presentationTimeStart: 0,
                        presentationTimeEnd: 500_000_000,
                        presentationTimeTimescale: 1_000_000_000,
                        conversionVersion: "tamforge-pcm16-v1"
                    )
                ],
                pcmSHA256: String(repeating: "b", count: 64)
            ))
    }

    private func sealedSpool() async throws -> UploadFixture {
        let root = try temporaryDirectory()
        let keyStore = UploadTestKeyStore()
        let factory = EncryptedRecordingSpoolFactory(
            rootURL: root,
            keyStore: keyStore,
            reservationBytes: 0
        )
        let recordingID = UUID()
        let spool = try await factory.create(recordingID: recordingID)
        try await spool.append(try chunk(track: .microphone))
        try await spool.append(try chunk(track: .systemAudio))
        let start = Date(timeIntervalSince1970: 1_788_278_400)
        try await spool.seal(
            gaps: [],
            startedAt: start,
            endedAt: start.addingTimeInterval(1)
        )
        return .init(
            recordingID: recordingID,
            directory: root.appendingPathComponent(recordingID.uuidString, isDirectory: true),
            factory: factory,
            keyStore: keyStore
        )
    }

    private func recoveredRecord(
        recordingID: UUID,
        track: RecordingTrackKind,
        sampleStart: Int64 = 0,
        presentationNanoseconds: Int64 = 1_000_000_000,
        route: String = "Fixture Route",
        conversionVersion: Int = 1
    ) throws -> RecoveredSpoolRecord {
        var chunk = try chunk(
            track: track,
            presentationNanoseconds: presentationNanoseconds,
            route: route,
            conversionVersion: conversionVersion
        )
        chunk.sampleStart = sampleStart
        return .init(recordingID: recordingID, sequence: 0, payload: chunk.payload, chunk: chunk)
    }

    private func chunk(
        track: RecordingTrackKind,
        presentationNanoseconds: Int64 = 1_000_000_000,
        route: String = "Fixture Route",
        conversionVersion: Int = 1
    ) throws -> RecordingPCMChunk {
        let channels = track == .microphone ? 1 : 2
        let samples = 48
        return .init(
            track: track,
            presentationNanoseconds: presentationNanoseconds,
            sampleStart: 0,
            sampleCount: samples,
            format: try RecordingPCMFormat(track: track, channelCount: channels),
            source: .init(
                sampleRate: 48_000,
                channelCount: channels,
                deviceID: "fixture-\(track.rawValue)",
                initialRoute: route,
                conversionVersion: conversionVersion,
                presentationNanoseconds: presentationNanoseconds
            ),
            payload: Data(repeating: track == .microphone ? 1 : 2, count: samples * channels * 2)
        )
    }

    private func temporaryDirectory() throws -> URL {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent(
            "tamforge-upload-tests-\(UUID().uuidString)",
            isDirectory: true
        )
        try FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: url) }
        return url
    }

    private func sha256(_ data: Data) -> String {
        SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }
}

private struct GoldenManifestFixture: Decodable {
    let tracks: [RecordingTrackManifestPayload]
}

private extension TranscriptSubmitPayload {
    // A minimal, valid wire-shape payload for tests that only care about
    // the retry mechanism, not about any specific transcript content.
    static func fixture(
        recordingID: UUID,
        track: RecordingTrackKind = .microphone
    ) -> TranscriptSubmitPayload {
        .init(
            recordingID: recordingID.uuidString.lowercased(),
            track: track.rawValue,
            segments: [
                .init(
                    text: "fixture transcript",
                    startMilliseconds: 0,
                    endMilliseconds: 500,
                    words: [
                        .init(
                            text: "fixture", startMilliseconds: 0, endMilliseconds: 250,
                            probability: 0.9
                        ),
                        .init(
                            text: "transcript", startMilliseconds: 250, endMilliseconds: 500,
                            probability: 0.9
                        ),
                    ]
                )
            ],
            modelIdentity: .init(
                runtimeVersion: "fixture",
                modelFilename: "fixture-model.bin",
                modelSHA256: String(repeating: "0", count: 64),
                metalRequested: false,
                usedBuiltInVAD: false,
                language: "en"
            ),
            derivation: .init(
                derivationVersion: "tamforge-asr-derivation-v1",
                sourceSampleRate: 48_000,
                sourceChannelCount: 1,
                sourceSampleCount: 48,
                outputSampleRate: 16_000,
                outputSampleCount: 16,
                zeroFilledGaps: [],
                sourcePCMSHA256: String(repeating: "a", count: 64),
                derivedPCMSHA256: String(repeating: "b", count: 64),
                quality: .init(
                    version: "1",
                    sampleRate: 16_000,
                    channelCount: 1,
                    sourceSampleCount: 48,
                    durationSeconds: 0.001,
                    peakAbsolute: 100,
                    allSilence: false,
                    clippedRatio: 0,
                    dcOffset: 0,
                    channelImbalanceDecibels: nil,
                    discontinuityCount: 0,
                    unavailableDimensions: []
                )
            )
        )
    }
}

private struct UploadFixture {
    let recordingID: UUID
    let directory: URL
    let factory: EncryptedRecordingSpoolFactory
    let keyStore: UploadTestKeyStore
}

private actor UploadTestKeyStore: RecordingKeyStoring {
    private var keys: [UUID: SymmetricKey] = [:]

    func create(recordingID: UUID) async throws -> SymmetricKey {
        let key = SymmetricKey(size: .bits256)
        keys[recordingID] = key
        return key
    }

    func load(recordingID: UUID) async throws -> SymmetricKey {
        guard let key = keys[recordingID] else { throw RecordingSpoolError.missingKey }
        return key
    }

    func delete(recordingID: UUID) async throws { keys.removeValue(forKey: recordingID) }
}

// Not private: RecordingFeatureTests.swift's coordinator-level transcript
// tests reuse this same double instead of duplicating create/upload/seal
// bookkeeping.
actor FakeRecordingServer: RecordingServerServicing {
    private(set) var uploadedParts: [RecordingPreparedPart] = []
    private(set) var uploadAttempts = 0
    private(set) var createCalls = 0
    private(set) var sealCommands: [RecordingSealPayload] = []
    private(set) var submittedTranscripts: [TranscriptSubmitPayload] = []
    private(set) var submissionAttempts = 0
    private let failureOnUploadAttempt: Int?
    private let uploadFailure: RecordingUploadError
    private let blockUploads: Bool
    private var failSubmission: Bool
    private let failSubmissionPermanently: Bool
    private let failSubmissionWithRecordingNotFound: Bool
    private let requireAudioBeforeTranscript: Bool
    private var statusByRecording: [UUID: RecordingServerStatus] = [:]

    init(
        failureOnUploadAttempt: Int? = nil,
        uploadFailure: RecordingUploadError = .offline,
        blockUploads: Bool = false,
        failSubmission: Bool = false,
        failSubmissionPermanently: Bool = false,
        failSubmissionWithRecordingNotFound: Bool = false,
        requireAudioBeforeTranscript: Bool = false
    ) {
        self.failureOnUploadAttempt = failureOnUploadAttempt
        self.uploadFailure = uploadFailure
        self.blockUploads = blockUploads
        self.failSubmission = failSubmission
        self.failSubmissionPermanently = failSubmissionPermanently
        self.failSubmissionWithRecordingNotFound = failSubmissionWithRecordingNotFound
        self.requireAudioBeforeTranscript = requireAudioBeforeTranscript
    }

    // Lets a test simulate a transient failure clearing between one pass
    // and the next, unlike the permanent failure a `let` would model.
    func setFailSubmission(_ value: Bool) {
        failSubmission = value
    }

    func create(_ command: RecordingCreatePayload, idempotencyKey: String) async throws {
        createCalls += 1
        guard let id = UUID(uuidString: command.recordingID) else {
            throw RecordingUploadError.invalidResponse
        }
        // Preserve an already-accepted transcript: submission and the audio
        // pipeline race independently, and create/seal must not clobber a
        // lineage flag a concurrent submitTranscript already set true.
        let alreadyAccepted = statusByRecording[id]?.transcriptLineageAccepted ?? false
        statusByRecording[id] = .init(
            recordingID: id,
            audioCreatedOnServer: false,
            transcriptLineageAccepted: alreadyAccepted
        )
    }

    func upload(_ part: RecordingPreparedPart) async throws {
        uploadAttempts += 1
        if failureOnUploadAttempt == uploadAttempts { throw uploadFailure }
        if blockUploads { try await Task.sleep(for: .seconds(60)) }
        uploadedParts.append(part)
    }

    func seal(
        _ command: RecordingSealPayload,
        idempotencyKey: String
    ) async throws -> RecordingServerStatus {
        guard let id = UUID(uuidString: command.recordingID) else {
            throw RecordingUploadError.invalidResponse
        }
        sealCommands.append(command)
        let alreadyAccepted = statusByRecording[id]?.transcriptLineageAccepted ?? false
        let status = RecordingServerStatus(
            recordingID: id,
            audioCreatedOnServer: true,
            transcriptLineageAccepted: alreadyAccepted
        )
        statusByRecording[id] = status
        return status
    }

    func submitTranscript(
        _ command: TranscriptSubmitPayload,
        idempotencyKey: String
    ) async throws -> RecordingServerStatus {
        submissionAttempts += 1
        guard let id = UUID(uuidString: command.recordingID) else {
            throw RecordingUploadError.invalidResponse
        }
        // Mirrors the backend's transcript_lineage_requires_audio
        // constraint (opt-in so every other test, which does not care
        // about this ordering, is unaffected): a transcript for a
        // recording whose audio is not yet on the server is a 409
        // conflict, not an accepted submission.
        if requireAudioBeforeTranscript, statusByRecording[id]?.audioCreatedOnServer != true {
            throw RecordingUploadError.conflict
        }
        // 422: the shape isPermanentTranscriptRejection matches (a 4xx that
        // is not the 409-before-audio case above). 500 (failSubmission)
        // stays a distinct, transient case a later pass can still resolve.
        // 404 mirrors the backend rejecting a submission that raced ahead
        // of this same recording's create (service.py's `_resolve_recording`
        // finding no row yet): isPermanentTranscriptRejection excludes it,
        // so it must stay retryable exactly like failSubmission's 500.
        if failSubmissionPermanently { throw RecordingUploadError.server(statusCode: 422) }
        if failSubmissionWithRecordingNotFound { throw RecordingUploadError.server(statusCode: 404) }
        if failSubmission { throw RecordingUploadError.server(statusCode: 500) }
        submittedTranscripts.append(command)
        // Mirrors LiveRecordingServerClient.submitTranscript: a successful
        // submission only ever happens once the backend's
        // transcript_lineage_requires_audio constraint already passed, so
        // audio is unconditionally true here too, regardless of whether
        // create/seal have run yet on this fake.
        let status = RecordingServerStatus(
            recordingID: id,
            audioCreatedOnServer: true,
            transcriptLineageAccepted: true
        )
        statusByRecording[id] = status
        return status
    }

    func status(recordingID: UUID) async throws -> RecordingServerStatus {
        guard let status = statusByRecording[recordingID] else {
            throw RecordingUploadError.server(statusCode: 404)
        }
        return status
    }

    func acceptTranscript(recordingID: UUID) {
        statusByRecording[recordingID] = .init(
            recordingID: recordingID,
            audioCreatedOnServer: true,
            transcriptLineageAccepted: true
        )
    }
}

private actor ProgressRecorder {
    private(set) var values: [Int] = []
    func append(_ value: Int) { values.append(value) }
}

private actor TokenRefreshRecorder {
    private(set) var count = 0
    func didRefresh() { count += 1 }
}

extension SymmetricKey {
    fileprivate var data: Data { withUnsafeBytes { Data($0) } }
}

private func XCTAssertAsyncThrowsError(
    _ expression: () async throws -> Void,
    file: StaticString = #filePath,
    line: UInt = #line
) async {
    do {
        try await expression()
        XCTFail("Expected async expression to throw", file: file, line: line)
    } catch {}
}
