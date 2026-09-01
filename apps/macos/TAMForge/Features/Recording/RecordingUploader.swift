import CryptoKit
import Foundation

typealias RecordingBearerTokenProvider = @Sendable () async throws -> String
typealias RecordingBearerRefresh = @Sendable () async throws -> String

struct RecordingServerStatus: Equatable, Sendable {
    let recordingID: UUID
    let audioCreatedOnServer: Bool
    let transcriptLineageAccepted: Bool
}

protocol RecordingServerServicing: Sendable {
    func create(_ command: RecordingCreatePayload, idempotencyKey: String) async throws
    func upload(_ part: RecordingPreparedPart) async throws
    func seal(_ command: RecordingSealPayload, idempotencyKey: String) async throws
        -> RecordingServerStatus
    func status(recordingID: UUID) async throws -> RecordingServerStatus
}

struct LiveRecordingServerClient: RecordingServerServicing, @unchecked Sendable {
    private static let maximumResponseBytes = 2 * 1024 * 1024

    let baseURL: URL
    let bearerToken: RecordingBearerTokenProvider
    let refreshBearer: RecordingBearerRefresh
    let session: URLSession

    init(
        baseURL: URL,
        bearerToken: @escaping RecordingBearerTokenProvider,
        refreshBearer: @escaping RecordingBearerRefresh,
        session: URLSession? = nil
    ) {
        self.baseURL = baseURL
        self.bearerToken = bearerToken
        self.refreshBearer = refreshBearer
        if let session {
            self.session = session
        } else {
            let configuration = URLSessionConfiguration.ephemeral
            configuration.urlCache = nil
            configuration.requestCachePolicy = .reloadIgnoringLocalAndRemoteCacheData
            configuration.httpCookieStorage = nil
            configuration.httpShouldSetCookies = false
            configuration.timeoutIntervalForRequest = 30
            configuration.timeoutIntervalForResource = 180
            self.session = URLSession(configuration: configuration)
        }
    }

    func create(_ command: RecordingCreatePayload, idempotencyKey: String) async throws {
        let data = try await sendJSON(
            method: "POST",
            path: "/api/v1/recordings",
            body: RecordingCanonicalJSON.encode(command),
            idempotencyKey: idempotencyKey,
            expectedStatus: 201
        )
        _ = try decodeGenerated(Components.Schemas.RecordingCreateResponse.self, data: data)
        let response = try decode(RecordingCreateResponsePayload.self, data: data)
        guard response.recordingID == command.recordingID else {
            throw RecordingUploadError.invalidResponse
        }
    }

    func upload(_ part: RecordingPreparedPart) async throws {
        try part.verifyFileIdentity()
        let path =
            "/api/v1/recordings/\(part.recordingID.uuidString.lowercased())"
            + "/tracks/\(part.trackID.uuidString.lowercased())/parts/\(part.sequence)"
        let data = try await sendUpload(path: path, part: part, expectedStatus: 201)
        _ = try decodeGenerated(Components.Schemas.RecordingPartReceipt.self, data: data)
        let response = try decode(RecordingPartReceiptPayload.self, data: data)
        guard response.recordingID == part.recordingID.uuidString.lowercased(),
            response.trackID == part.trackID.uuidString.lowercased(),
            response.sequence == part.sequence,
            response.plaintextSHA256 == part.plaintextSHA256
        else { throw RecordingUploadError.invalidResponse }
        try part.verifyFileIdentity()
    }

    func seal(
        _ command: RecordingSealPayload,
        idempotencyKey: String
    ) async throws -> RecordingServerStatus {
        let data = try await sendJSON(
            method: "POST",
            path: "/api/v1/recordings/\(command.recordingID)/seal",
            body: RecordingCanonicalJSON.encode(command),
            idempotencyKey: idempotencyKey,
            expectedStatus: 201
        )
        _ = try decodeGenerated(Components.Schemas.RecordingSealResponse.self, data: data)
        let status = try decode(RecordingServerStatusPayload.self, data: data).status
        guard status.recordingID.uuidString.lowercased() == command.recordingID else {
            throw RecordingUploadError.invalidResponse
        }
        return status
    }

    func status(recordingID: UUID) async throws -> RecordingServerStatus {
        let data = try await sendJSON(
            method: "GET",
            path: "/api/v1/recordings/\(recordingID.uuidString.lowercased())",
            body: nil,
            idempotencyKey: nil,
            expectedStatus: 200
        )
        _ = try decodeGenerated(Components.Schemas.RecordingStatusResponse.self, data: data)
        let status = try decode(RecordingServerStatusPayload.self, data: data).status
        guard status.recordingID == recordingID else {
            throw RecordingUploadError.invalidResponse
        }
        return status
    }

    private func sendJSON(
        method: String,
        path: String,
        body: Data?,
        idempotencyKey: String?,
        expectedStatus: Int
    ) async throws -> Data {
        try await authorizedRequest(expectedStatus: expectedStatus) { token in
            var request = try request(path: path, method: method, token: token)
            request.httpBody = body
            if body != nil {
                request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            }
            if let idempotencyKey {
                request.setValue(idempotencyKey, forHTTPHeaderField: "Idempotency-Key")
            }
            return try await session.data(for: request)
        }
    }

    private func sendUpload(
        path: String,
        part: RecordingPreparedPart,
        expectedStatus: Int
    ) async throws -> Data {
        try await authorizedRequest(expectedStatus: expectedStatus) { token in
            try part.verifyFileIdentity()
            var request = try request(path: path, method: "PUT", token: token)
            request.setValue("application/octet-stream", forHTTPHeaderField: "Content-Type")
            for (name, value) in part.headers {
                request.setValue(value, forHTTPHeaderField: name)
            }
            return try await session.upload(for: request, fromFile: part.fileURL)
        }
    }

    private func authorizedRequest(
        expectedStatus: Int,
        perform: @escaping @Sendable (String) async throws -> (Data, URLResponse)
    ) async throws -> Data {
        do {
            let token = try await bearerToken()
            var result = try await perform(token)
            if (result.1 as? HTTPURLResponse)?.statusCode == 401 {
                let replacement = try await refreshBearer()
                result = try await perform(replacement)
            }
            guard let response = result.1 as? HTTPURLResponse else {
                throw RecordingUploadError.invalidResponse
            }
            guard result.0.count <= Self.maximumResponseBytes else {
                throw RecordingUploadError.invalidResponse
            }
            guard response.statusCode == expectedStatus else {
                throw mapFailure(statusCode: response.statusCode, body: result.0)
            }
            return result.0
        } catch is CancellationError {
            throw CancellationError()
        } catch let error as URLError {
            if error.code == .cancelled { throw CancellationError() }
            switch error.code {
            case .notConnectedToInternet, .networkConnectionLost, .cannotConnectToHost,
                .cannotFindHost, .timedOut:
                throw RecordingUploadError.offline
            default:
                throw error
            }
        }
    }

    private func request(path: String, method: String, token: String) throws -> URLRequest {
        guard path.hasPrefix("/"), !path.hasPrefix("//"), !token.isEmpty,
            let url = URL(string: path, relativeTo: baseURL)?.absoluteURL,
            url.scheme == baseURL.scheme,
            url.host == baseURL.host
        else { throw RecordingUploadError.invalidResponse }
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        request.setValue("no-store", forHTTPHeaderField: "Cache-Control")
        return request
    }

    private func mapFailure(statusCode: Int, body: Data) -> RecordingUploadError {
        if statusCode == 401 { return .unauthorized }
        if statusCode == 409 { return .conflict }
        if let problem = try? JSONDecoder().decode(APIProblem.self, from: body),
            problem.status == 401
        {
            return .unauthorized
        }
        return .server(statusCode: statusCode)
    }

    private func decodeGenerated<Value: Decodable>(
        _ type: Value.Type,
        data: Data
    ) throws -> Value {
        do { return try NativeJSONCodec.decode(type, from: data) } catch {
            throw RecordingUploadError.invalidResponse
        }
    }

    private func decode<Value: Decodable>(_ type: Value.Type, data: Data) throws -> Value {
        do { return try JSONDecoder().decode(type, from: data) } catch {
            throw RecordingUploadError.invalidResponse
        }
    }
}

actor RecordingUploadPipeline: RecordingUploading {
    private let spoolFactory: EncryptedRecordingSpoolFactory
    private let server: any RecordingServerServicing
    private let partBuilder: RecordingUploadPartBuilder

    init(
        spoolFactory: EncryptedRecordingSpoolFactory,
        server: any RecordingServerServicing,
        partBuilder: RecordingUploadPartBuilder = .init()
    ) {
        self.spoolFactory = spoolFactory
        self.server = server
        self.partBuilder = partBuilder
    }

    func upload(
        recordingID: UUID,
        progress: @escaping @Sendable (Int) -> Void
    ) async throws -> RecordingReleaseGates {
        let directory = spoolFactory.rootURL.appendingPathComponent(
            recordingID.uuidString, isDirectory: true
        )
        let metadata = try await EncryptedRecordingSpool.recoverMetadata(
            recordingID: recordingID,
            rootURL: spoolFactory.rootURL,
            keyStore: spoolFactory.keyStore
        )
        guard metadata.sealed,
            let startedAt = metadata.startedAt,
            let endedAt = metadata.endedAt
        else { throw RecordingUploadError.unsealedSpool }

        if metadata.releaseGates.audioCreatedOnServer {
            let status = try await server.status(recordingID: recordingID)
            let gates = RecordingReleaseGates(
                audioCreatedOnServer: status.audioCreatedOnServer,
                transcriptLineageAccepted: status.transcriptLineageAccepted
            )
            try await spoolFactory.markReleaseGates(recordingID: recordingID, gates: gates)
            _ = try await spoolFactory.releaseIfEligible(recordingID: recordingID)
            return gates
        }

        let journal = try RecordingUploadJournal(directoryURL: directory)
        let journalState = await journal.snapshot()
        if !journalState.createAccepted {
            let tracks = RecordingTrackKind.allCases.map { track in
                RecordingTrackDeclarationPayload(
                    trackID: RecordingTrackIdentity.id(
                        recordingID: recordingID, track: track
                    ).uuidString.lowercased(),
                    kind: track.rawValue,
                    format: .init(channelCount: track == .microphone ? 1 : 2)
                )
            }
            try await server.create(
                .init(
                    recordingID: recordingID.uuidString.lowercased(),
                    startedAt: NativeJSONCodec.timestamp(startedAt),
                    tracks: tracks
                ),
                idempotencyKey: "recording.create.\(recordingID.uuidString.lowercased())"
            )
            try await journal.markCreateAccepted()
        }

        let rootKey = try await spoolFactory.keyStore.load(recordingID: recordingID)
        let reader = try await EncryptedRecordingSpool.openRecordReader(
            recordingID: recordingID,
            rootURL: spoolFactory.rootURL,
            keyStore: spoolFactory.keyStore
        )
        var sequences: [RecordingTrackKind: Int] = [:]
        var descriptors: [RecordingTrackKind: [RecordingPartDescriptorPayload]] = [:]
        var hashers: [RecordingTrackKind: SHA256] = [
            .microphone: SHA256(),
            .systemAudio: SHA256(),
        ]
        var completedCount = 0
        let completed = Set((await journal.snapshot()).completedParts)

        while let record = try await reader.next() {
            try Task.checkCancellation()
            let track = record.chunk.track
            let sequence = sequences[track, default: 0]
            sequences[track] = sequence + 1
            let plaintextHash = SHA256.hash(data: record.payload).hex
            descriptors[track, default: []].append(
                .init(
                    sequence: sequence,
                    sampleStart: record.chunk.sampleStart,
                    sampleCount: record.chunk.sampleCount,
                    byteLength: record.payload.count,
                    plaintextSHA256: plaintextHash
                ))
            var hasher = hashers[track] ?? SHA256()
            hasher.update(data: record.payload)
            hashers[track] = hasher

            let identity = "\(track.rawValue):\(sequence):\(plaintextHash)"
            if completed.contains(identity) {
                completedCount += 1
                progress(completedCount)
                continue
            }
            let part = try partBuilder.prepare(
                record: record,
                uploadSequence: sequence,
                rootKey: rootKey,
                directoryURL: directory
            )
            do {
                try await journal.begin(part: part)
                try await server.upload(part)
                try await journal.complete(part: part)
                try? FileManager.default.removeItem(at: part.fileURL)
                completedCount += 1
                progress(completedCount)
            } catch {
                try? await journal.markFailure()
                try? FileManager.default.removeItem(at: part.fileURL)
                throw error
            }
        }
        let scan = await reader.summary()
        guard !scan.ignoredIncompleteTail else {
            throw RecordingUploadError.invalidCoverage
        }
        let allGaps = metadata.gaps + scan.corruptRanges
        let manifests = try RecordingTrackKind.allCases.map { track in
            try RecordingTrackManifestPayload.make(
                recordingID: recordingID,
                track: track,
                parts: descriptors[track, default: []],
                gaps: allGaps.filter { $0.track == track }.map {
                    .init(
                        sampleStart: $0.sampleStart,
                        sampleCount: $0.sampleCount,
                        reason: $0.reason.rawValue
                    )
                },
                pcmSHA256: {
                    var hasher = hashers[track] ?? SHA256()
                    return hasher.finalize().hex
                }()
            )
        }
        let coverage = allGaps.isEmpty ? "complete" : "stored_with_gaps"
        let status = try await server.seal(
            .init(
                recordingID: recordingID.uuidString.lowercased(),
                startedAt: NativeJSONCodec.timestamp(startedAt),
                endedAt: NativeJSONCodec.timestamp(endedAt),
                coverageStatus: coverage,
                tracks: manifests
            ),
            idempotencyKey: "recording.seal.\(recordingID.uuidString.lowercased())"
        )
        try await journal.markSealAccepted()
        let gates = RecordingReleaseGates(
            audioCreatedOnServer: status.audioCreatedOnServer,
            transcriptLineageAccepted: status.transcriptLineageAccepted
        )
        guard gates.audioCreatedOnServer else { throw RecordingUploadError.invalidResponse }
        try await spoolFactory.markReleaseGates(recordingID: recordingID, gates: gates)
        _ = try await spoolFactory.releaseIfEligible(recordingID: recordingID)
        return gates
    }
}

private struct RecordingCreateResponsePayload: Decodable {
    let recordingID: String

    enum CodingKeys: String, CodingKey { case recordingID = "recording_id" }
}

private struct RecordingPartReceiptPayload: Decodable {
    let recordingID: String
    let trackID: String
    let sequence: Int
    let plaintextSHA256: String

    enum CodingKeys: String, CodingKey {
        case recordingID = "recording_id"
        case trackID = "track_id"
        case sequence
        case plaintextSHA256 = "plaintext_sha256"
    }
}

private struct RecordingServerStatusPayload: Decodable {
    let recordingID: String
    let audioCreatedOnServer: Bool
    let transcriptLineageAccepted: Bool

    enum CodingKeys: String, CodingKey {
        case recordingID = "recording_id"
        case audioCreatedOnServer = "audio_created_on_server"
        case transcriptLineageAccepted = "transcript_lineage_accepted"
    }

    var status: RecordingServerStatus {
        get throws {
            guard let id = UUID(uuidString: recordingID) else {
                throw RecordingUploadError.invalidResponse
            }
            return .init(
                recordingID: id,
                audioCreatedOnServer: audioCreatedOnServer,
                transcriptLineageAccepted: transcriptLineageAccepted
            )
        }
    }
}

extension SHA256.Digest {
    fileprivate var hex: String { map { String(format: "%02x", $0) }.joined() }
}
