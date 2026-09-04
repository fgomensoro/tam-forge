import Foundation
import HTTPTypes
import OpenAPIRuntime

@MainActor
final class LiveActivityAPI: ActivityAPI {
    private let transport: NativeAPITransport

    init(transport: NativeAPITransport) {
        self.transport = transport
    }

    func fetch(activityID: Int) async throws -> ActivityDetail {
        try await send(
            method: .get,
            path: path(activityID),
            responseLimit: .activityOutput,
            as: Components.Schemas.ActivityDetailResponse.self,
            map: { try .init(api: $0) }
        )
    }

    func start(activityID: Int, expectedVersion: Int, idempotencyKey: String) async throws -> ActivitySummary {
        try await command(
            activityID: activityID,
            action: "start",
            body: Components.Schemas.VersionedCommand(expectedVersion: expectedVersion),
            idempotencyKey: idempotencyKey,
            as: Components.Schemas.ActivityResponse.self,
            map: { try .init(api: $0) }
        )
    }

    func pause(_ command: ActivityHeartbeatCommand) async throws -> ActivitySummary {
        try await self.command(
            activityID: command.activityID,
            action: "pause",
            body: Components.Schemas.HeartbeatCommand(
                clientSequence: command.clientSequence,
                expectedVersion: command.expectedVersion
            ),
            idempotencyKey: command.idempotencyKey,
            as: Components.Schemas.ActivityResponse.self,
            map: { try .init(api: $0) }
        )
    }

    func resume(activityID: Int, expectedVersion: Int, idempotencyKey: String) async throws -> ActivitySummary {
        try await command(
            activityID: activityID,
            action: "resume",
            body: Components.Schemas.VersionedCommand(expectedVersion: expectedVersion),
            idempotencyKey: idempotencyKey,
            as: Components.Schemas.ActivityResponse.self,
            map: { try .init(api: $0) }
        )
    }

    func heartbeat(_ command: ActivityHeartbeatCommand) async throws -> ActivitySummary {
        try await self.command(
            activityID: command.activityID,
            action: "heartbeat",
            body: Components.Schemas.HeartbeatCommand(
                clientSequence: command.clientSequence,
                expectedVersion: command.expectedVersion
            ),
            idempotencyKey: command.idempotencyKey,
            as: Components.Schemas.ActivityResponse.self,
            map: { try .init(api: $0) }
        )
    }

    func setSourceHidden(
        activityID: Int, expectedVersion: Int, hidden: Bool, idempotencyKey: String
    ) async throws -> ActivityDetail {
        try await command(
            activityID: activityID,
            action: "source-visibility",
            body: Components.Schemas.SourceVisibilityCommand(
                expectedVersion: expectedVersion,
                hidden: hidden
            ),
            idempotencyKey: idempotencyKey,
            as: Components.Schemas.ActivityDetailResponse.self,
            map: { try .init(api: $0) }
        )
    }

    func commit(_ command: ActivityCommitCommand) async throws -> ActivityCommitReceipt {
        let artifactReferences = try command.artifactReferences.map {
            Components.Schemas.ArtifactReference(
                artifactId: $0.artifactID,
                linkRole: try generated(
                    Components.Schemas.ArtifactReference.LinkRolePayload.self,
                    rawValue: $0.linkRole.rawValue
                )
            )
        }
        let body = try Components.Schemas.CommitOutputCommand(
            artifactRefs: artifactReferences,
            clientSequence: command.clientSequence,
            expectedVersion: command.expectedVersion,
            output: .init(additionalProperties: .init(activityJSONValues: command.output))
        )
        return try await self.command(
            activityID: command.activityID,
            action: "commit-output",
            body: body,
            idempotencyKey: command.idempotencyKey,
            as: Components.Schemas.OutputCommitResponse.self,
            map: { try .init(api: $0) }
        )
    }

    func submitSelfReview(_ command: ActivitySelfReviewCommand) async throws -> ActivitySelfReviewReceipt {
        try await self.command(
            activityID: command.activityID,
            action: "self-review",
            body: Components.Schemas.SelfReviewCommand(
                changeNext: command.input.changeNext,
                didWell: command.input.didWell,
                expectedVersion: command.expectedVersion,
                hesitationPoints: command.input.hesitationPoints,
                mainAnswer: command.input.mainAnswer,
                selfScore: command.input.selfScore,
                structureWeakness: command.input.structureWeakness,
                vaguePoints: command.input.vaguePoints
            ),
            idempotencyKey: command.idempotencyKey,
            as: Components.Schemas.SelfReviewResponse.self,
            map: { try .init(api: $0) }
        )
    }

    func classifyIncomplete(_ command: ActivityIncompleteCommand) async throws -> ActivitySummary {
        try await self.command(
            activityID: command.activityID,
            action: "classify-incomplete",
            body: Components.Schemas.IncompleteCommand(
                classification: try generated(
                    Components.Schemas.IncompleteClassification.self,
                    rawValue: command.classification.rawValue
                ),
                expectedVersion: command.expectedVersion,
                strongerEvidenceId: command.strongerEvidenceID
            ),
            idempotencyKey: command.idempotencyKey,
            as: Components.Schemas.ActivityResponse.self,
            map: { try .init(api: $0) }
        )
    }

    func presign(_ command: ActivityArtifactPresignCommand) async throws -> ActivityArtifactPresignResponse {
        try await self.command(
            activityID: command.activityID,
            action: "artifacts/presign",
            body: Components.Schemas.ArtifactPresignCommand(
                artifactClass: try generated(
                    Components.Schemas.ArtifactPresignCommand.ArtifactClassPayload.self,
                    rawValue: command.artifactClass.rawValue
                ),
                byteLength: command.byteLength,
                contentType: command.contentType,
                expectedVersion: command.expectedVersion,
                originalFilename: command.originalFilename,
                sha256: command.sha256
            ),
            idempotencyKey: command.idempotencyKey,
            as: Components.Schemas.ArtifactPresignResponse.self,
            map: { try .init(api: $0) }
        )
    }

    func confirm(_ command: ActivityArtifactConfirmCommand) async throws -> ActivityArtifact {
        try await self.command(
            activityID: command.activityID,
            action: "artifacts/confirm",
            body: Components.Schemas.ArtifactConfirmCommand(
                expectedVersion: command.expectedVersion,
                objectKey: command.objectKey,
                uploadIdempotencyKey: command.uploadIdempotencyKey
            ),
            idempotencyKey: command.idempotencyKey,
            as: Components.Schemas.ArtifactResponse.self,
            map: { try .init(api: $0) }
        )
    }

    func executeSQL(_ command: SqlExecutionCommand) async throws -> SqlExecutionReceipt {
        guard SqlExecutionModel.queryReason(command.query) == nil else { throw SqlExecutionError.queryRejected }
        let body = Components.Schemas.SqlExecutionCommand(expectedVersion: command.expectedVersion, query: command.query)
        let receipt = try await sendSQL(
            method: .post, activityID: command.activityID,
            body: try NativeJSONCodec.encode(body), idempotencyKey: command.idempotencyKey,
            as: Components.Schemas.SqlExecutionResponse.self,
            map: { try SqlExecutionReceipt(api: $0, activityID: command.activityID) }
        )
        guard receipt.query.utf8.elementsEqual(command.query.utf8) else { throw SqlExecutionError.invalidResponse }
        return receipt
    }

    func fetchSQLHistory(activityID: Int) async throws -> [SqlExecutionReceipt] {
        try await sendSQL(method: .get, activityID: activityID,
                          as: Components.Schemas.SqlExecutionHistory.self) { response in
            guard response.items.count <= 20 else { throw SqlExecutionError.invalidResponse }
            let items = try response.items.map { try SqlExecutionReceipt(api: $0, activityID: activityID) }
            guard Set(items.map(\.id)).count == items.count else { throw SqlExecutionError.invalidResponse }
            return items
        }
    }

    private func sendSQL<Response: Decodable & Sendable, Value>(
        method: HTTPRequest.Method, activityID: Int, body: Data? = nil, idempotencyKey: String? = nil,
        as type: Response.Type, map: (Response) throws -> Value
    ) async throws -> Value {
        do {
            try Task.checkCancellation()
            let response = try await transport.send(.init(
                method: method, path: "\(path(activityID))/sql-executions", body: body,
                idempotencyKey: idempotencyKey, responseLimit: .standard
            ))
            guard let bytes = response.body, bytes.count <= 1024 * 1024 else { throw SqlExecutionError.invalidResponse }
            return try map(response.decoded(as: type))
        } catch is CancellationError {
            throw ActivityAPIError.cancelled
        } catch let error as SqlExecutionError {
            throw error
        } catch let error as NativeAPIError {
            switch error {
            case let .problem(problem):
                switch (problem.status, problem.code) {
                case (401, _): throw ActivityAPIError.unauthorized
                case (409, "sql_execution_conflict"): throw ActivityAPIError.conflict
                case (404, "sql_activity_not_found"), (503, "sql_execution_unavailable"):
                    throw SqlExecutionError.unavailable
                case (429, "sql_execution_busy"): throw SqlExecutionError.busy
                case (422, "invalid_sql_execution"): throw SqlExecutionError.queryRejected
                default: throw SqlExecutionError.network
                }
            case .emptyResponse, .decodingResponse, .responseTooLarge: throw SqlExecutionError.invalidResponse
            default: throw SqlExecutionError.network
            }
        } catch let error as ActivityAPIError {
            throw error
        } catch let error as URLError where error.code == .cancelled {
            throw ActivityAPIError.cancelled
        } catch {
            throw SqlExecutionError.network
        }
    }

    private func command<Body: Encodable, Response: Decodable & Sendable, Value>(
        activityID: Int,
        action: String,
        body: Body,
        idempotencyKey: String,
        as type: Response.Type,
        map: @escaping (Response) throws -> Value
    ) async throws -> Value {
        try await send(
            method: .post,
            path: "\(path(activityID))/\(action)",
            body: try NativeJSONCodec.encode(body),
            idempotencyKey: idempotencyKey,
            as: type,
            map: map
        )
    }

    private func send<Response: Decodable & Sendable, Value>(
        method: HTTPRequest.Method,
        path: String,
        body: Data? = nil,
        idempotencyKey: String? = nil,
        responseLimit: NativeAPIResponseLimit = .standard,
        as type: Response.Type,
        map: @escaping (Response) throws -> Value
    ) async throws -> Value {
        do {
            try Task.checkCancellation()
            let response = try await transport.send(.init(
                method: method,
                path: path,
                body: body,
                idempotencyKey: idempotencyKey,
                responseLimit: responseLimit
            ))
            let generated = try response.decoded(as: type)
            do {
                return try map(generated)
            } catch {
                throw ActivityAPIError.invalidResponse
            }
        } catch is CancellationError {
            throw ActivityAPIError.cancelled
        } catch let error as ActivityAPIError {
            throw error
        } catch let error as NativeAPIError {
            switch error {
            case let .problem(problem):
                switch problem.status {
                case 401: throw ActivityAPIError.unauthorized
                case 409: throw ActivityAPIError.conflict
                default: throw ActivityAPIError.network
                }
            case .emptyResponse, .decodingResponse:
                throw ActivityAPIError.invalidResponse
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

private enum ActivityAdapterError: Error {
    case invalidSchemaValue
}

private func generated<Value: RawRepresentable>(
    _ type: Value.Type, rawValue: String
) throws -> Value where Value.RawValue == String {
    guard let value = Value(rawValue: rawValue) else {
        throw ActivityAdapterError.invalidSchemaValue
    }
    return value
}

private extension ActivitySummary {
    init(api value: Components.Schemas.ActivityResponse) throws {
        self.init(
            id: value.id,
            studyDayID: value.studyDayId,
            state: try generated(ActivityState.self, rawValue: value.state.rawValue),
            optimisticVersion: value.optimisticVersion,
            classification: try generated(
                ActivityIncompleteClassification.self,
                rawValue: value.classification.rawValue
            ),
            strongerEvidenceID: value.strongerEvidenceId,
            activityFocusedSeconds: value.activityFocusedSeconds,
            dayFocusedMinutes: value.dayFocusedMinutes,
            hardStopRecommended: value.hardStopRecommended,
            openTimer: value.openTimer.map { .init(api: $0.value1) },
            sourceHidden: value.sourceHidden ?? false
        )
    }
}

private extension ActivityDetail {
    init(api value: Components.Schemas.ActivityDetailResponse) throws {
        self.init(
            id: value.id,
            studyDayID: value.studyDayId,
            state: try generated(ActivityState.self, rawValue: value.state.rawValue),
            optimisticVersion: value.optimisticVersion,
            classification: try generated(
                ActivityIncompleteClassification.self,
                rawValue: value.classification.rawValue
            ),
            strongerEvidenceID: value.strongerEvidenceId,
            activityFocusedSeconds: value.activityFocusedSeconds,
            dayFocusedMinutes: value.dayFocusedMinutes,
            hardStopRecommended: value.hardStopRecommended,
            openTimer: value.openTimer.map { .init(api: $0.value1) },
            sourceHidden: value.sourceHidden ?? false,
            taskContract: try .init(api: value.taskContract),
            committedOutput: try value.committedOutput.map { try .init(api: $0.value1) },
            selfReview: value.selfReview.map { .init(api: $0.value1) }
        )
    }
}

private extension ActivityTaskContract {
    init(api value: Components.Schemas.ActivityTaskContract) throws {
        self.init(
            stableID: value.stableId,
            block: try generated(ActivityBlock.self, rawValue: value.block.rawValue),
            objective: value.objective,
            timeboxMinutes: value.timeboxMinutes,
            required: value.required,
            sourceReferences: value.sourceReferences.map {
                .init(path: $0.path, anchor: $0.anchor)
            },
            requiredOutput: value.requiredOutput,
            passCriteria: value.passCriteria,
            evidenceRequirements: value.evidenceRequirements,
            allowedAIRole: try generated(ActivityAIRole.self, rawValue: value.allowedAiRole.rawValue),
            procedure: value.procedure.map {
                .init(phase: $0.phase, minutes: $0.minutes, requirement: $0.requirement)
            },
            constraints: value.constraints,
            exerciseType: value.exerciseType,
            mappingVersion: value.mappingVersion
        )
    }
}

private extension ActivityTimer {
    init(api value: Components.Schemas.TimerResponse) {
        self.init(
            id: value.id,
            startedAt: value.startedAt,
            lastHeartbeatAt: value.lastHeartbeatAt,
            countedSeconds: value.countedSeconds,
            lastClientSequence: value.lastClientSequence
        )
    }
}

private extension ActivityCommittedOutput {
    init(api value: Components.Schemas.CommittedOutputSummary) throws {
        self.init(
            attemptID: value.attemptId,
            attemptKind: value.attemptKind,
            commitmentSHA256: value.commitmentSha256,
            contractPayload: try .init(openAPIObject: value.contractPayload.additionalProperties),
            artifactIDs: value.artifactIds,
            committedAt: value.committedAt
        )
    }
}

private extension ActivitySelfReview {
    init(api value: Components.Schemas.SelfReviewSummary) {
        self.init(
            id: value.id,
            attemptID: value.attemptId,
            selfScore: value.selfScore,
            mainAnswer: value.mainAnswer,
            didWell: value.didWell,
            structureWeakness: value.structureWeakness,
            vaguePoints: value.vaguePoints,
            hesitationPoints: value.hesitationPoints,
            changeNext: value.changeNext,
            submittedAt: value.submittedAt
        )
    }
}

private extension ActivityCommitReceipt {
    init(api value: Components.Schemas.OutputCommitResponse) throws {
        self.init(
            activityID: value.activityId,
            state: try generated(ActivityState.self, rawValue: value.state.rawValue),
            optimisticVersion: value.optimisticVersion,
            attemptID: value.attemptId,
            commitmentSHA256: value.commitmentSha256,
            artifactIDs: value.artifactIds
        )
    }
}

private extension ActivitySelfReviewReceipt {
    init(api value: Components.Schemas.SelfReviewResponse) throws {
        self.init(
            activityID: value.activityId,
            state: try generated(ActivityState.self, rawValue: value.state.rawValue),
            optimisticVersion: value.optimisticVersion,
            selfReviewID: value.selfReviewId,
            attemptID: value.attemptId,
            selfScore: value.selfScore
        )
    }
}

private extension ActivityArtifactPresignResponse {
    init(api value: Components.Schemas.ArtifactPresignResponse) throws {
        self.init(
            artifactID: value.artifactId,
            objectKey: value.objectKey,
            reused: value.reused,
            upload: try value.upload.map { try .init(api: $0.value1) }
        )
    }
}

private extension ActivityPresignedUpload {
    init(api value: Components.Schemas.PresignedUploadResponse) throws {
        guard value.method == "PUT", let url = URL(string: value.url) else {
            throw ActivityAdapterError.invalidSchemaValue
        }
        self.init(
            url: url,
            headers: value.headers.additionalProperties,
            expiresSeconds: value.expiresSeconds
        )
    }
}

private extension ActivityArtifact {
    init(api value: Components.Schemas.ArtifactResponse) throws {
        self.init(
            id: value.id,
            sha256: value.sha256,
            byteLength: value.byteLength,
            contentType: value.contentType,
            originalFilename: value.originalFilename,
            artifactClass: try generated(ActivityArtifactClass.self, rawValue: value.artifactClass)
        )
    }
}

private extension Dictionary where Key == String, Value == ActivityJSONValue {
    init(openAPIObject value: OpenAPIObjectContainer) throws {
        var mapped: Self = [:]
        for (key, child) in value.value {
            mapped[key] = try .init(openAPIValue: child)
        }
        self = mapped
    }

    var openAPIObject: OpenAPIObjectContainer {
        get throws {
            var mapped: [String: (any Sendable)?] = [:]
            for (key, value) in self {
                mapped[key] = .some(try value.openAPIValue)
            }
            return try .init(unvalidatedValue: mapped)
        }
    }
}

private extension OpenAPIObjectContainer {
    init(activityJSONValues value: [String: ActivityJSONValue]) throws {
        self = try value.openAPIObject
    }
}

private extension ActivityJSONValue {
    init(openAPIValue value: (any Sendable)?) throws {
        switch value {
        case nil, is NSNull:
            self = .null
        case let value as Bool:
            self = .boolean(value)
        case let value as Int:
            self = .integer(value)
        case let value as Double:
            self = .decimal(value)
        case let value as String:
            self = .string(value)
        case let values as [(any Sendable)?]:
            self = .array(try values.map { try .init(openAPIValue: $0) })
        case let values as [String: (any Sendable)?]:
            var mapped: [String: Self] = [:]
            for (key, child) in values {
                mapped[key] = try .init(openAPIValue: child)
            }
            self = .object(mapped)
        default:
            throw ActivityAdapterError.invalidSchemaValue
        }
    }

    var openAPIValue: (any Sendable)? {
        get throws {
            switch self {
            case let .string(value):
                return value
            case let .integer(value):
                return value
            case let .decimal(value):
                return value
            case let .boolean(value):
                return value
            case let .array(values):
                let mapped: [(any Sendable)?] = try values.map { try $0.openAPIValue }
                return mapped
            case let .object(values):
                var mapped: [String: (any Sendable)?] = [:]
                for (key, value) in values {
                    mapped[key] = .some(try value.openAPIValue)
                }
                return mapped
            case .null:
                return nil
            }
        }
    }
}

private extension SqlExecutionReceipt {
    init(api value: Components.Schemas.SqlExecutionResponse, activityID: Int) throws {
        let source = value.result
        guard value.activityId == activityID, value.executionId > 0,
              value.query.utf8.count <= 64 * 1024,
              value.querySha256 == Self.queryHash(value.query),
              (1...32).contains(source.columns.count), Set(source.columns).count == source.columns.count,
              source.columns.allSatisfy({ !$0.isEmpty && $0.count <= 63 }),
              source.rows.count <= 1000, source.rowCount == source.rows.count,
              source.rows.allSatisfy({ $0.count == source.columns.count }),
              source.elapsedMs >= 0, source.exerciseVersion > 0,
              source.exerciseKey.range(of: "^[a-z_][a-z0-9_]{0,62}$", options: .regularExpression) != nil,
              source.resultSha256.range(of: "^[0-9a-f]{64}$", options: .regularExpression) != nil,
              let validation = SqlValidation(rawValue: source.validation.rawValue) else {
            throw SqlExecutionError.invalidResponse
        }
        let result = SqlExecutionResult(columns: source.columns, rows: source.rows, elapsedMS: source.elapsedMs,
                                        rowCount: source.rowCount, resultSHA256: source.resultSha256,
                                        validation: validation, exerciseKey: source.exerciseKey,
                                        exerciseVersion: source.exerciseVersion)
        guard try result.encodedRows().count <= 256 * 1024 else { throw SqlExecutionError.invalidResponse }
        self.init(executionID: value.executionId, activityID: value.activityId, query: value.query,
                  querySHA256: value.querySha256, result: result)
    }
}
