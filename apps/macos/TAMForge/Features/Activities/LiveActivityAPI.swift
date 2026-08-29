import Foundation
import HTTPTypes

@MainActor
final class LiveActivityAPI: ActivityAPI {
    private let transport: NativeAPITransport
    private let encoder = JSONEncoder()
    private let decoder: JSONDecoder

    init(transport: NativeAPITransport) {
        self.transport = transport
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .custom { container in
            let value = try container.singleValueContainer().decode(String.self)
            let fractional = ISO8601DateFormatter()
            fractional.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
            let plain = ISO8601DateFormatter()
            plain.formatOptions = [.withInternetDateTime]
            guard let date = fractional.date(from: value) ?? plain.date(from: value) else {
                throw DecodingError.dataCorrupted(.init(codingPath: container.codingPath, debugDescription: "Expected RFC 3339 timestamp"))
            }
            return date
        }
        self.decoder = decoder
    }

    func fetch(activityID: Int) async throws -> ActivityDetail {
        try await send(method: .get, path: path(activityID), as: ActivityDetail.self)
    }

    func start(activityID: Int, expectedVersion: Int, idempotencyKey: String) async throws -> ActivitySummary {
        try await self.command(
            activityID: activityID,
            action: "start",
            body: VersionPayload(expectedVersion: expectedVersion),
            idempotencyKey: idempotencyKey,
            as: ActivitySummary.self
        )
    }

    func pause(_ command: ActivityHeartbeatCommand) async throws -> ActivitySummary {
        try await self.command(
            activityID: command.activityID,
            action: "pause",
            body: HeartbeatPayload(expectedVersion: command.expectedVersion, clientSequence: command.clientSequence),
            idempotencyKey: command.idempotencyKey,
            as: ActivitySummary.self
        )
    }

    func resume(activityID: Int, expectedVersion: Int, idempotencyKey: String) async throws -> ActivitySummary {
        try await self.command(
            activityID: activityID,
            action: "resume",
            body: VersionPayload(expectedVersion: expectedVersion),
            idempotencyKey: idempotencyKey,
            as: ActivitySummary.self
        )
    }

    func heartbeat(_ command: ActivityHeartbeatCommand) async throws -> ActivitySummary {
        try await self.command(
            activityID: command.activityID,
            action: "heartbeat",
            body: HeartbeatPayload(expectedVersion: command.expectedVersion, clientSequence: command.clientSequence),
            idempotencyKey: command.idempotencyKey,
            as: ActivitySummary.self
        )
    }

    func setSourceHidden(activityID: Int, expectedVersion: Int, hidden: Bool, idempotencyKey: String) async throws -> ActivityDetail {
        try await self.command(
            activityID: activityID,
            action: "source-visibility",
            body: SourceVisibilityPayload(expectedVersion: expectedVersion, hidden: hidden),
            idempotencyKey: idempotencyKey,
            as: ActivityDetail.self
        )
    }

    func commit(_ command: ActivityCommitCommand) async throws -> ActivityCommitReceipt {
        try await self.command(
            activityID: command.activityID,
            action: "commit-output",
            body: CommitPayload(
                expectedVersion: command.expectedVersion,
                clientSequence: command.clientSequence,
                output: command.output,
                artifactReferences: command.artifactReferences
            ),
            idempotencyKey: command.idempotencyKey,
            as: ActivityCommitReceipt.self
        )
    }

    func submitSelfReview(_ command: ActivitySelfReviewCommand) async throws -> ActivitySelfReviewReceipt {
        try await self.command(
            activityID: command.activityID,
            action: "self-review",
            body: SelfReviewPayload(expectedVersion: command.expectedVersion, input: command.input),
            idempotencyKey: command.idempotencyKey,
            as: ActivitySelfReviewReceipt.self
        )
    }

    func classifyIncomplete(_ command: ActivityIncompleteCommand) async throws -> ActivitySummary {
        try await self.command(
            activityID: command.activityID,
            action: "classify-incomplete",
            body: IncompletePayload(
                expectedVersion: command.expectedVersion,
                classification: command.classification,
                strongerEvidenceID: command.strongerEvidenceID
            ),
            idempotencyKey: command.idempotencyKey,
            as: ActivitySummary.self
        )
    }

    func presign(_ command: ActivityArtifactPresignCommand) async throws -> ActivityArtifactPresignResponse {
        try await self.command(
            activityID: command.activityID,
            action: "artifacts/presign",
            body: PresignPayload(command),
            idempotencyKey: command.idempotencyKey,
            as: ActivityArtifactPresignResponse.self
        )
    }

    func confirm(_ command: ActivityArtifactConfirmCommand) async throws -> ActivityArtifact {
        try await self.command(
            activityID: command.activityID,
            action: "artifacts/confirm",
            body: ConfirmPayload(command),
            idempotencyKey: command.idempotencyKey,
            as: ActivityArtifact.self
        )
    }

    private func command<Body: Encodable, Response: Decodable>(
        activityID: Int,
        action: String,
        body: Body,
        idempotencyKey: String,
        as type: Response.Type
    ) async throws -> Response {
        let data = try encoder.encode(body)
        return try await send(
            method: .post,
            path: "\(path(activityID))/\(action)",
            body: data,
            idempotencyKey: idempotencyKey,
            as: type
        )
    }

    private func send<Response: Decodable>(
        method: HTTPRequest.Method,
        path: String,
        body: Data? = nil,
        idempotencyKey: String? = nil,
        as type: Response.Type
    ) async throws -> Response {
        do {
            let response = try await transport.send(.init(method: method, path: path, body: body, idempotencyKey: idempotencyKey))
            guard let body = response.body else { throw ActivityAPIError.invalidResponse }
            do {
                return try decoder.decode(Response.self, from: body)
            } catch {
                throw ActivityAPIError.invalidResponse
            }
        } catch is CancellationError {
            throw ActivityAPIError.cancelled
        } catch let error as NativeAPIError {
            switch error {
            case let .problem(problem):
                switch problem.status {
                case 401: throw ActivityAPIError.unauthorized
                case 409: throw ActivityAPIError.conflict
                default: throw ActivityAPIError.network
                }
            default:
                throw ActivityAPIError.network
            }
        } catch let error as URLError where error.code == .cancelled {
            throw ActivityAPIError.cancelled
        } catch {
            throw ActivityAPIError.network
        }
    }

    private func path(_ activityID: Int) -> String {
        "/api/v1/activities/\(activityID)"
    }
}

private struct VersionPayload: Encodable {
    var expectedVersion: Int
    enum CodingKeys: String, CodingKey { case expectedVersion = "expected_version" }
}

private struct HeartbeatPayload: Encodable {
    var expectedVersion: Int
    var clientSequence: Int
    enum CodingKeys: String, CodingKey {
        case expectedVersion = "expected_version"
        case clientSequence = "client_sequence"
    }
}

private struct SourceVisibilityPayload: Encodable {
    var expectedVersion: Int
    var hidden: Bool
    enum CodingKeys: String, CodingKey { case expectedVersion = "expected_version"; case hidden }
}

private struct CommitPayload: Encodable {
    var expectedVersion: Int
    var clientSequence: Int
    var output: [String: ActivityJSONValue]
    var artifactReferences: [ActivityArtifactReference]
    enum CodingKeys: String, CodingKey {
        case expectedVersion = "expected_version"
        case clientSequence = "client_sequence"
        case output
        case artifactReferences = "artifact_refs"
    }
}

private struct SelfReviewPayload: Encodable {
    var expectedVersion: Int
    var input: ActivitySelfReviewInput
    enum CodingKeys: String, CodingKey {
        case expectedVersion = "expected_version"
        case mainAnswer = "main_answer"
        case didWell = "did_well"
        case structureWeakness = "structure_weakness"
        case vaguePoints = "vague_points"
        case hesitationPoints = "hesitation_points"
        case changeNext = "change_next"
        case selfScore = "self_score"
    }
    func encode(to encoder: any Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(expectedVersion, forKey: .expectedVersion)
        try container.encode(input.mainAnswer, forKey: .mainAnswer)
        try container.encode(input.didWell, forKey: .didWell)
        try container.encode(input.structureWeakness, forKey: .structureWeakness)
        try container.encode(input.vaguePoints, forKey: .vaguePoints)
        try container.encode(input.hesitationPoints, forKey: .hesitationPoints)
        try container.encode(input.changeNext, forKey: .changeNext)
        try container.encode(input.selfScore, forKey: .selfScore)
    }
}

private struct IncompletePayload: Encodable {
    var expectedVersion: Int
    var classification: ActivityIncompleteClassification
    var strongerEvidenceID: Int?
    enum CodingKeys: String, CodingKey {
        case expectedVersion = "expected_version"
        case classification
        case strongerEvidenceID = "stronger_evidence_id"
    }
}

private struct PresignPayload: Encodable {
    var expectedVersion: Int
    var artifactClass: ActivityArtifactClass
    var sha256: String
    var byteLength: Int
    var contentType: String
    var originalFilename: String
    enum CodingKeys: String, CodingKey {
        case expectedVersion = "expected_version"
        case artifactClass = "artifact_class"
        case sha256
        case byteLength = "byte_length"
        case contentType = "content_type"
        case originalFilename = "original_filename"
    }
    init(_ command: ActivityArtifactPresignCommand) {
        expectedVersion = command.expectedVersion
        artifactClass = command.artifactClass
        sha256 = command.sha256
        byteLength = command.byteLength
        contentType = command.contentType
        originalFilename = command.originalFilename
    }
}

private struct ConfirmPayload: Encodable {
    var expectedVersion: Int
    var uploadIdempotencyKey: String
    var objectKey: String
    enum CodingKeys: String, CodingKey {
        case expectedVersion = "expected_version"
        case uploadIdempotencyKey = "upload_idempotency_key"
        case objectKey = "object_key"
    }
    init(_ command: ActivityArtifactConfirmCommand) {
        expectedVersion = command.expectedVersion
        uploadIdempotencyKey = command.uploadIdempotencyKey
        objectKey = command.objectKey
    }
}

extension ActivityArtifactPresignResponse {
    init(from decoder: any Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        artifactID = try container.decodeIfPresent(Int.self, forKey: .artifactID)
        objectKey = try container.decode(String.self, forKey: .objectKey)
        reused = try container.decode(Bool.self, forKey: .reused)
        upload = try container.decodeIfPresent(ActivityPresignedUpload.self, forKey: .upload)
    }

    enum CodingKeys: String, CodingKey {
        case artifactID = "artifact_id"
        case objectKey = "object_key"
        case reused, upload
    }
}

extension ActivityPresignedUpload {
    init(from decoder: any Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        url = try container.decode(URL.self, forKey: .url)
        headers = try container.decode([String: String].self, forKey: .headers)
        expiresSeconds = try container.decode(Int.self, forKey: .expiresSeconds)
    }

    enum CodingKeys: String, CodingKey {
        case url, headers
        case expiresSeconds = "expires_seconds"
    }
}
