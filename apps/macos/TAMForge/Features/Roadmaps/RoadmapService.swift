import Foundation
import HTTPTypes
import OpenAPIRuntime
import OpenAPIURLSession

enum RoadmapJSONValue: Codable, Equatable, Sendable {
    case array([Self])
    case bool(Bool)
    case null
    case number(Double)
    case object([String: Self])
    case string(String)

    init(from decoder: any Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() { self = .null }
        else if let value = try? container.decode(Bool.self) { self = .bool(value) }
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
        guard case let .number(value) = self else { return nil }
        return Int(exactly: value)
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

protocol RoadmapServicing: Sendable {
    func stage(package: RoadmapPackage, idempotencyKey: String) async throws -> RoadmapImport
    func approve(importID: Int) async throws -> RoadmapVersion
    func retryMirror(versionID: Int) async throws -> RoadmapVersion
    func activate(versionID: Int) async throws -> RoadmapVersion
    func listVersions() async throws -> [RoadmapVersion]
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
    private let bearerToken: @Sendable () async -> String?
    private let transport: URLSessionTransport

    init(
        baseURL: URL,
        bearerToken: @escaping @Sendable () async -> String?,
        session: URLSession? = nil
    ) {
        self.baseURL = baseURL
        self.bearerToken = bearerToken
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
            return try await request(
                method: .post,
                path: "/api/v1/roadmap-imports",
                body: body,
                contentType: multipart.contentType,
                idempotencyKey: idempotencyKey,
                as: RoadmapImport.self
            )
        }
    }

    func approve(importID: Int) async throws -> RoadmapVersion {
        try await request(
            method: .post,
            path: "/api/v1/roadmap-imports/\(importID)/approve",
            as: RoadmapVersion.self
        )
    }

    func retryMirror(versionID: Int) async throws -> RoadmapVersion {
        try await request(
            method: .post,
            path: "/api/v1/roadmap-imports/\(versionID)/mirror/retry",
            as: RoadmapVersion.self
        )
    }

    func activate(versionID: Int) async throws -> RoadmapVersion {
        try await request(
            method: .post,
            path: "/api/v1/roadmap-versions/\(versionID)/activate",
            as: RoadmapVersion.self
        )
    }

    func listVersions() async throws -> [RoadmapVersion] {
        try await request(method: .get, path: "/api/v1/roadmap-versions", as: [RoadmapVersion].self)
    }

    private func request<Value: Decodable & Sendable>(
        method: HTTPRequest.Method,
        path: String,
        body: HTTPBody? = nil,
        contentType: String? = nil,
        idempotencyKey: String? = nil,
        as type: Value.Type
    ) async throws -> Value {
        var headers: HTTPFields = [:]
        if let token = await bearerToken(), !token.isEmpty {
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
        let data = try await Self.collect(responseBody, upTo: Self.maximumResponseBytes)
        guard (200 ... 299).contains(response.status.code) else {
            let problem = try? JSONDecoder().decode(RoadmapProblem.self, from: data ?? Data())
            throw RoadmapServiceError.problem(statusCode: response.status.code, code: problem?.code)
        }
        guard let data else { throw RoadmapServiceError.invalidResponse }
        do {
            return try JSONDecoder().decode(type, from: data)
        } catch {
            throw RoadmapServiceError.invalidResponse
        }
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

private struct RoadmapProblem: Decodable {
    let code: String?
}
