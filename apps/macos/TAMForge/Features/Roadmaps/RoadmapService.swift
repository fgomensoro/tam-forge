import Foundation
import HTTPTypes
import OpenAPIRuntime
import OpenAPIURLSession

enum RoadmapJSONValue: Codable, Equatable, Sendable {
    case array([Self])
    case bool(Bool)
    case integer(Int)
    case null
    case number(Double)
    case object([String: Self])
    case string(String)

    init(from decoder: any Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() { self = .null }
        else if let value = try? container.decode(Bool.self) { self = .bool(value) }
        else if let value = try? container.decode(Int.self) { self = .integer(value) }
        else if let value = try? container.decode(Double.self) { self = .number(value) }
        else if let value = try? container.decode(String.self) { self = .string(value) }
        else if let value = try? container.decode([String: Self].self) { self = .object(value) }
        else { self = .array(try container.decode([Self].self)) }
    }

    func encode(to encoder: any Encoder) throws {
        var container = encoder.singleValueContainer()
        switch self {
        case let .array(value): try container.encode(value)
        case let .bool(value): try container.encode(value)
        case let .integer(value): try container.encode(value)
        case .null: try container.encodeNil()
        case let .number(value): try container.encode(value)
        case let .object(value): try container.encode(value)
        case let .string(value): try container.encode(value)
        }
    }

    var objectValue: [String: Self]? {
        guard case let .object(value) = self else { return nil }
        return value
    }

    var arrayValue: [Self]? {
        guard case let .array(value) = self else { return nil }
        return value
    }

    var stringValue: String? {
        guard case let .string(value) = self else { return nil }
        return value
    }

    var integerValue: Int? {
        switch self {
        case let .integer(value): value
        case let .number(value): Int(exactly: value)
        default: nil
        }
    }
}

private enum RoadmapJSONValueError: Error {
    case unsupportedOpenAPIValue
}

private extension RoadmapJSONValue {
    init(openAPIObject value: OpenAPIObjectContainer) throws {
        var mapped: [String: Self] = [:]
        for (key, child) in value.value {
            mapped[key] = try .init(openAPIValue: child)
        }
        self = .object(mapped)
    }

    init(openAPIValue value: (any Sendable)?) throws {
        switch value {
        case nil, is NSNull: self = .null
        case let value as Bool: self = .bool(value)
        case let value as Int: self = .integer(value)
        case let value as Double: self = .number(value)
        case let value as String: self = .string(value)
        case let values as [(any Sendable)?]:
            self = .array(try values.map { try .init(openAPIValue: $0) })
        case let values as [String: (any Sendable)?]:
            var mapped: [String: Self] = [:]
            for (key, child) in values {
                mapped[key] = try .init(openAPIValue: child)
            }
            self = .object(mapped)
        default:
            throw RoadmapJSONValueError.unsupportedOpenAPIValue
        }
    }
}

struct RoadmapImport: Codable, Equatable, Sendable, Identifiable {
    let id: Int
    let status: String
    let validationReport: RoadmapJSONValue
    let semanticDiff: RoadmapJSONValue
    let failureCode: String?

    enum CodingKeys: String, CodingKey {
        case id, status
        case validationReport = "validation_report"
        case semanticDiff = "semantic_diff"
        case failureCode = "failure_code"
    }

    var isValidated: Bool {
        status == "validated" && validationReport.objectValue?["accepted"] == .bool(true)
    }
}

struct RoadmapVersion: Codable, Equatable, Sendable, Identifiable {
    let id: Int
    let versionKey: String
    let versionNumber: Int
    let monthNumber: Int
    let state: String
    let mirrorStatus: String
    let mirrorRef: String?
    let mirrorErrorCode: String?

    enum CodingKeys: String, CodingKey {
        case id, state
        case versionKey = "version_key"
        case versionNumber = "version_number"
        case monthNumber = "month_number"
        case mirrorStatus = "mirror_status"
        case mirrorRef = "mirror_ref"
        case mirrorErrorCode = "mirror_error_code"
    }

    var canActivate: Bool {
        state == "approved" && ["synced", "not_required"].contains(mirrorStatus)
    }
}

extension RoadmapImport {
    init(wire value: Components.Schemas.RoadmapImportResponse) throws {
        self.init(
            id: value.id,
            status: value.status,
            validationReport: try .init(openAPIObject: value.validationReport.additionalProperties),
            semanticDiff: try .init(openAPIObject: value.semanticDiff.additionalProperties),
            failureCode: value.failureCode
        )
    }
}

extension RoadmapVersion {
    init(wire value: Components.Schemas.RoadmapVersionResponse) {
        self.init(
            id: value.id,
            versionKey: value.versionKey,
            versionNumber: value.versionNumber,
            monthNumber: value.monthNumber,
            state: value.state,
            mirrorStatus: value.mirrorStatus,
            mirrorRef: value.mirrorRef,
            mirrorErrorCode: value.mirrorErrorCode
        )
    }
}

/// A scheme the planner proposed, or that failed validation. Frank approves it by
/// staging it; nothing is applied on the server until then.
struct SchemeProposal: Equatable, Sendable {
    let yamlText: String
    let summary: RoadmapJSONValue
    let issues: [String]

    var accepted: Bool { issues.isEmpty }
}

extension SchemeProposal {
    init(wire value: Components.Schemas.SchemeProposalResponse) throws {
        self.init(
            yamlText: value.yamlText,
            summary: try .init(openAPIObject: value.summary.additionalProperties),
            issues: value.issues
        )
    }
}

protocol RoadmapServicing: Sendable {
    func stage(package: RoadmapPackage, idempotencyKey: String) async throws -> RoadmapImport
    func approve(importID: Int) async throws -> RoadmapVersion
    func retryMirror(versionID: Int) async throws -> RoadmapVersion
    func activate(versionID: Int) async throws -> RoadmapVersion
    func listVersions() async throws -> [RoadmapVersion]
    func proposeScheme(importID: Int, instruction: String) async throws -> SchemeProposal
    func stageScheme(importID: Int, yamlText: String) async throws -> RoadmapImport
    func proposeReforecast(versionID: Int, instruction: String) async throws -> SchemeProposal
    func stageReforecast(versionID: Int, yamlText: String) async throws -> RoadmapImport
    func exportVersion(versionID: Int) async throws -> Data
}

enum RoadmapServiceError: Error, Equatable, Sendable {
    case invalidResponse
    case responseTooLarge
    case problem(statusCode: Int, code: String?)
}

struct LiveRoadmapService: RoadmapServicing, Sendable {
    private static let maximumResponseBytes = 2 * 1024 * 1024
    private static let maximumMultipartBytes = 65 * 1024 * 1024
    private static let idempotencyHeader = HTTPField.Name("Idempotency-Key")!

    private let baseURL: URL
    private let bearerToken: NativeBearerTokenProvider
    private let transport: URLSessionTransport
    private let onUnauthorizedForRequest: NativeUnauthorizedHandlerFactory

    init(
        baseURL: URL,
        bearerToken: @escaping NativeBearerTokenProvider,
        session: URLSession? = nil,
        onUnauthorized: @escaping @Sendable () -> Void = {},
        onUnauthorizedForRequest: NativeUnauthorizedHandlerFactory? = nil
    ) {
        self.baseURL = baseURL
        self.bearerToken = bearerToken
        self.onUnauthorizedForRequest = onUnauthorizedForRequest ?? { onUnauthorized }
        self.transport = URLSessionTransport(
            configuration: .init(session: session ?? Self.makeSession())
        )
    }

    func stage(package: RoadmapPackage, idempotencyKey: String) async throws -> RoadmapImport {
        try await package.withSecurityScopedAccess {
            let multipart = try RoadmapMultipartBody.makeWithoutAccess(for: package)
            defer { multipart.remove() }
            let body = try NativeMultipartFile(
                fileURL: multipart.fileURL,
                contentType: multipart.contentType,
                maximumBytes: Self.maximumMultipartBytes
            ).httpBody()
            let response: Components.Schemas.RoadmapImportResponse = try await request(
                method: .post,
                path: "/api/v1/roadmap-imports",
                body: body,
                contentType: multipart.contentType,
                idempotencyKey: idempotencyKey,
                as: Components.Schemas.RoadmapImportResponse.self
            )
            do {
                return try .init(wire: response)
            } catch {
                throw RoadmapServiceError.invalidResponse
            }
        }
    }

    func approve(importID: Int) async throws -> RoadmapVersion {
        let response: Components.Schemas.RoadmapVersionResponse = try await request(
            method: .post,
            path: "/api/v1/roadmap-imports/\(importID)/approve",
            as: Components.Schemas.RoadmapVersionResponse.self
        )
        return .init(wire: response)
    }

    func retryMirror(versionID: Int) async throws -> RoadmapVersion {
        let response: Components.Schemas.RoadmapVersionResponse = try await request(
            method: .post,
            path: "/api/v1/roadmap-imports/\(versionID)/mirror/retry",
            as: Components.Schemas.RoadmapVersionResponse.self
        )
        return .init(wire: response)
    }

    func activate(versionID: Int) async throws -> RoadmapVersion {
        // The first activation creates the learner settings server-side, so it
        // carries this Mac's timezone; Today materializes days in that zone.
        let body = try NativeJSONCodec.encode(
            Components.Schemas.ActivateRoadmapVersionRequest(timezone: TimeZone.current.identifier)
        )
        let response: Components.Schemas.RoadmapVersionResponse = try await request(
            method: .post,
            path: "/api/v1/roadmap-versions/\(versionID)/activate",
            body: .init(body),
            contentType: "application/json",
            as: Components.Schemas.RoadmapVersionResponse.self
        )
        return .init(wire: response)
    }

    func listVersions() async throws -> [RoadmapVersion] {
        let response: [Components.Schemas.RoadmapVersionResponse] = try await request(
            method: .get,
            path: "/api/v1/roadmap-versions",
            as: [Components.Schemas.RoadmapVersionResponse].self
        )
        return response.map(RoadmapVersion.init(wire:))
    }

    func proposeScheme(importID: Int, instruction: String) async throws -> SchemeProposal {
        try await propose(path: "/api/v1/roadmap-imports/\(importID)/scheme-proposals", instruction: instruction)
    }

    func stageScheme(importID: Int, yamlText: String) async throws -> RoadmapImport {
        try await stageScheme(path: "/api/v1/roadmap-imports/\(importID)/scheme", yamlText: yamlText)
    }

    func proposeReforecast(versionID: Int, instruction: String) async throws -> SchemeProposal {
        try await propose(path: "/api/v1/roadmap-versions/\(versionID)/scheme-proposals", instruction: instruction)
    }

    func stageReforecast(versionID: Int, yamlText: String) async throws -> RoadmapImport {
        try await stageScheme(path: "/api/v1/roadmap-versions/\(versionID)/reforecasts", yamlText: yamlText)
    }

    func exportVersion(versionID: Int) async throws -> Data {
        let data = try await send(method: .get, path: "/api/v1/roadmap-versions/\(versionID)/export")
        guard let data, !data.isEmpty else { throw RoadmapServiceError.invalidResponse }
        return data
    }

    private func propose(path: String, instruction: String) async throws -> SchemeProposal {
        let body = try NativeJSONCodec.encode(
            Components.Schemas.SchemeProposalRequest(instruction: instruction)
        )
        let response: Components.Schemas.SchemeProposalResponse = try await request(
            method: .post,
            path: path,
            body: .init(body),
            contentType: "application/json",
            as: Components.Schemas.SchemeProposalResponse.self
        )
        do {
            return try .init(wire: response)
        } catch {
            throw RoadmapServiceError.invalidResponse
        }
    }

    private func stageScheme(path: String, yamlText: String) async throws -> RoadmapImport {
        let body = try NativeJSONCodec.encode(Components.Schemas.SchemeTextRequest(yamlText: yamlText))
        let response: Components.Schemas.RoadmapImportResponse = try await request(
            method: .post,
            path: path,
            body: .init(body),
            contentType: "application/json",
            as: Components.Schemas.RoadmapImportResponse.self
        )
        do {
            return try .init(wire: response)
        } catch {
            throw RoadmapServiceError.invalidResponse
        }
    }

    private func request<Value: Decodable & Sendable>(
        method: HTTPRequest.Method,
        path: String,
        body: HTTPBody? = nil,
        contentType: String? = nil,
        idempotencyKey: String? = nil,
        as type: Value.Type
    ) async throws -> Value {
        let data = try await send(
            method: method,
            path: path,
            body: body,
            contentType: contentType,
            idempotencyKey: idempotencyKey
        )
        guard let data else { throw RoadmapServiceError.invalidResponse }
        do {
            return try NativeJSONCodec.decode(type, from: data)
        } catch {
            throw RoadmapServiceError.invalidResponse
        }
    }

    /// One authenticated round trip; the bytes of a 2xx body, or a problem error.
    private func send(
        method: HTTPRequest.Method,
        path: String,
        body: HTTPBody? = nil,
        contentType: String? = nil,
        idempotencyKey: String? = nil
    ) async throws -> Data? {
        var headers: HTTPFields = [:]
        let onUnauthorized = await onUnauthorizedForRequest()
        if let token = try await resolveNativeBearerToken(using: bearerToken, onUnauthorized: onUnauthorized), !token.isEmpty {
            headers[.authorization] = "Bearer \(token)"
        }
        if let contentType { headers[.contentType] = contentType }
        if let idempotencyKey { headers[Self.idempotencyHeader] = idempotencyKey }
        let request = HTTPRequest(
            method: method,
            scheme: nil,
            authority: nil,
            path: path,
            headerFields: headers
        )
        let (response, responseBody) = try await transport.send(
            request,
            body: body,
            baseURL: baseURL,
            operationID: "roadmap-request"
        )
        if response.status.code == 401 { onUnauthorized() }
        let data = try await Self.collect(responseBody, upTo: Self.maximumResponseBytes)
        guard (200 ... 299).contains(response.status.code) else {
            let problem = data.flatMap {
                try? NativeJSONCodec.decode(Components.Schemas.ProblemResponse.self, from: $0)
            }
            throw RoadmapServiceError.problem(statusCode: response.status.code, code: problem?.code)
        }
        return data
    }

    private static func collect(_ body: HTTPBody?, upTo maximumBytes: Int) async throws -> Data? {
        guard let body else { return nil }
        var result = Data()
        for try await chunk in body {
            guard chunk.count <= maximumBytes - result.count else {
                throw RoadmapServiceError.responseTooLarge
            }
            result.append(contentsOf: chunk)
        }
        return result
    }

    private static func makeSession() -> URLSession {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.urlCache = nil
        configuration.requestCachePolicy = .reloadIgnoringLocalAndRemoteCacheData
        configuration.timeoutIntervalForRequest = 30
        configuration.timeoutIntervalForResource = 120
        return URLSession(configuration: configuration)
    }
}
