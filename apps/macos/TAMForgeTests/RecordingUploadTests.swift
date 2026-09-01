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
        sampleStart: Int64 = 0
    ) throws -> RecoveredSpoolRecord {
        var chunk = try chunk(track: track)
        chunk.sampleStart = sampleStart
        return .init(recordingID: recordingID, sequence: 0, payload: chunk.payload, chunk: chunk)
    }

    private func chunk(track: RecordingTrackKind) throws -> RecordingPCMChunk {
        let channels = track == .microphone ? 1 : 2
        let samples = 48
        return .init(
            track: track,
            presentationNanoseconds: 1_000_000_000,
            sampleStart: 0,
            sampleCount: samples,
            format: try RecordingPCMFormat(track: track, channelCount: channels),
            source: .init(
                sampleRate: 48_000,
                channelCount: channels,
                deviceID: "fixture-\(track.rawValue)",
                presentationNanoseconds: 1_000_000_000
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

private actor FakeRecordingServer: RecordingServerServicing {
    private(set) var uploadedParts: [RecordingPreparedPart] = []
    private(set) var uploadAttempts = 0
    private let failureOnUploadAttempt: Int?
    private let uploadFailure: RecordingUploadError
    private let blockUploads: Bool
    private var statusByRecording: [UUID: RecordingServerStatus] = [:]

    init(
        failureOnUploadAttempt: Int? = nil,
        uploadFailure: RecordingUploadError = .offline,
        blockUploads: Bool = false
    ) {
        self.failureOnUploadAttempt = failureOnUploadAttempt
        self.uploadFailure = uploadFailure
        self.blockUploads = blockUploads
    }

    func create(_ command: RecordingCreatePayload, idempotencyKey: String) async throws {
        guard let id = UUID(uuidString: command.recordingID) else {
            throw RecordingUploadError.invalidResponse
        }
        statusByRecording[id] = .init(
            recordingID: id,
            audioCreatedOnServer: false,
            transcriptLineageAccepted: false
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
        let status = RecordingServerStatus(
            recordingID: id,
            audioCreatedOnServer: true,
            transcriptLineageAccepted: false
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
