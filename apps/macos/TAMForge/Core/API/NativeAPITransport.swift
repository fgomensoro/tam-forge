import Darwin
import Foundation
import HTTPTypes
import OpenAPIRuntime
import OpenAPIURLSession

struct NativeAPIRequest: Sendable {
    let method: HTTPRequest.Method
    let path: String
    let body: Data?
    let idempotencyKey: String?

    init(
        method: HTTPRequest.Method,
        path: String,
        body: Data? = nil,
        idempotencyKey: String? = nil
    ) {
        self.method = method
        self.path = path
        self.body = body
        self.idempotencyKey = idempotencyKey
    }

    fileprivate var allowsRetry: Bool {
        if idempotencyKey != nil {
            return true
        }
        switch method.rawValue {
        case "GET", "HEAD", "OPTIONS", "TRACE":
            return true
        default:
            return false
        }
    }
}

struct NativeAPIResponse: Sendable {
    let statusCode: Int
    let body: Data?

    func decoded<Value: Decodable & Sendable>(as type: Value.Type) throws -> Value {
        guard let body else { throw NativeAPIError.emptyResponse }
        do {
            return try JSONDecoder().decode(Value.self, from: body)
        } catch {
            throw NativeAPIError.decodingResponse
        }
    }
}

struct APIProblem: Codable, Equatable, Sendable {
    let type: String?
    let title: String?
    let status: Int?
    let detail: String?
    let instance: String?
    let code: String?
}

enum NativeAPIError: Error, Equatable {
    case invalidPath
    case emptyResponse
    case decodingResponse
    case responseTooLarge
    case malformedProblem(statusCode: Int)
    case problem(APIProblem)
}

struct RetryPolicy: Sendable {
    let maximumAttempts: Int

    init(maximumAttempts: Int = 1) {
        precondition(maximumAttempts > 0, "maximumAttempts must be positive")
        self.maximumAttempts = maximumAttempts
    }

    fileprivate func shouldRetry(_ error: URLError) -> Bool {
        switch error.code {
        case .timedOut, .cannotConnectToHost, .networkConnectionLost, .notConnectedToInternet:
            true
        default:
            false
        }
    }
}

struct TimeoutPolicy: Sendable {
    let request: TimeInterval
    let resource: TimeInterval

    static let standard = Self(request: 15, resource: 60)
}

struct NativeAPIDiagnostic: Sendable, CustomStringConvertible, Equatable {
    let method: String
    let path: String
    let statusCode: Int?

    var description: String {
        let status = statusCode.map(String.init) ?? "transport-error"
        return "HTTP \(method) \(path) \(status)"
    }
}

struct NativeAPITransport: Sendable {
    private static let maximumResponseBytes = 2 * 1024 * 1024
    private static let maximumProblemBytes = 64 * 1024
    private static let idempotencyKeyHeader = HTTPField.Name("Idempotency-Key")!

    private let baseURL: URL
    private let bearerToken: @Sendable () async -> String?
    private let retryPolicy: RetryPolicy
    private let transport: URLSessionTransport
    private let onUnauthorized: @Sendable () -> Void
    private let diagnostics: @Sendable (NativeAPIDiagnostic) -> Void

    init(
        baseURL: URL,
        bearerToken: @escaping @Sendable () async -> String? = { nil },
        retryPolicy: RetryPolicy = .init(),
        timeoutPolicy: TimeoutPolicy = .standard,
        session: URLSession? = nil,
        onUnauthorized: @escaping @Sendable () -> Void = {},
        diagnostics: @escaping @Sendable (NativeAPIDiagnostic) -> Void = { _ in }
    ) {
        self.baseURL = baseURL
        self.bearerToken = bearerToken
        self.retryPolicy = retryPolicy
        self.transport = URLSessionTransport(
            configuration: .init(session: session ?? Self.makeSession(timeoutPolicy: timeoutPolicy))
        )
        self.onUnauthorized = onUnauthorized
        self.diagnostics = diagnostics
    }

    init(
        environment: AppEnvironment,
        bearerToken: @escaping @Sendable () async -> String? = { nil },
        retryPolicy: RetryPolicy = .init(),
        timeoutPolicy: TimeoutPolicy = .standard,
        session: URLSession? = nil,
        onUnauthorized: @escaping @Sendable () -> Void = {},
        diagnostics: @escaping @Sendable (NativeAPIDiagnostic) -> Void = { _ in }
    ) {
        self.init(
            baseURL: environment.apiBaseURL,
            bearerToken: bearerToken,
            retryPolicy: retryPolicy,
            timeoutPolicy: timeoutPolicy,
            session: session,
            onUnauthorized: onUnauthorized,
            diagnostics: diagnostics
        )
    }

    func send(_ request: NativeAPIRequest) async throws -> NativeAPIResponse {
        var attempt = 1
        while true {
            try Task.checkCancellation()
            do {
                return try await sendOnce(request)
            } catch is CancellationError {
                throw CancellationError()
            } catch let error as URLError where Task.isCancelled || error.code == .cancelled {
                throw CancellationError()
            } catch let error as URLError where request.allowsRetry && retryPolicy.shouldRetry(error) && attempt < retryPolicy.maximumAttempts {
                attempt += 1
            }
        }
    }

    private func sendOnce(_ request: NativeAPIRequest) async throws -> NativeAPIResponse {
        guard request.path.hasPrefix("/"), !request.path.hasPrefix("//") else {
            throw NativeAPIError.invalidPath
        }

        var headers: HTTPFields = [:]
        if let token = await bearerToken() {
            headers[.authorization] = "Bearer \(token)"
        }
        if let idempotencyKey = request.idempotencyKey {
            headers[Self.idempotencyKeyHeader] = idempotencyKey
        }
        if request.body != nil {
            headers[.contentType] = "application/json"
        }

        let httpRequest = HTTPRequest(
            method: request.method,
            scheme: nil,
            authority: nil,
            path: request.path,
            headerFields: headers
        )
        let (response, responseBody) = try await transport.send(
            httpRequest,
            body: request.body.map(HTTPBody.init),
            baseURL: baseURL,
            operationID: "native-request"
        )
        let statusCode = response.status.code
        diagnostics(
            NativeAPIDiagnostic(
                method: request.method.rawValue,
                path: Self.redactedPath(request.path),
                statusCode: statusCode
            )
        )

        if statusCode == 401 {
            onUnauthorized()
        }
        if (200...299).contains(statusCode) {
            if statusCode == 204 {
                return NativeAPIResponse(statusCode: statusCode, body: nil)
            }
            do {
                return NativeAPIResponse(
                    statusCode: statusCode,
                    body: try await Self.collect(responseBody, upTo: Self.maximumResponseBytes)
                )
            } catch is ResponseLimitError {
                throw NativeAPIError.responseTooLarge
            }
        }

        let problemData: Data?
        do {
            problemData = try await Self.collect(responseBody, upTo: Self.maximumProblemBytes)
        } catch {
            throw NativeAPIError.malformedProblem(statusCode: statusCode)
        }
        guard let problemData,
              let problem = try? JSONDecoder().decode(APIProblem.self, from: problemData)
        else {
            throw NativeAPIError.malformedProblem(statusCode: statusCode)
        }
        throw NativeAPIError.problem(problem)
    }

    private static func collect(_ body: HTTPBody?, upTo maximumBytes: Int) async throws -> Data? {
        guard let body else { return nil }
        var result = Data()
        for try await chunk in body {
            guard chunk.count <= maximumBytes - result.count else {
                throw ResponseLimitError()
            }
            result.append(contentsOf: chunk)
        }
        return result
    }

    private static func makeSession(timeoutPolicy: TimeoutPolicy) -> URLSession {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.urlCache = nil
        configuration.requestCachePolicy = .reloadIgnoringLocalAndRemoteCacheData
        configuration.timeoutIntervalForRequest = timeoutPolicy.request
        configuration.timeoutIntervalForResource = timeoutPolicy.resource
        return URLSession(configuration: configuration)
    }

    private static func redactedPath(_ path: String) -> String {
        String(path.prefix { $0 != "?" })
    }
}

private struct ResponseLimitError: Error {}

struct NativeMultipartFile: Sendable {
    static let defaultMaximumBytes = 50 * 1024 * 1024
    private static let chunkSize = 64 * 1024

    let fileURL: URL
    let contentType: String
    let byteCount: Int64
    private let identity: FileIdentity

    init(fileURL: URL, contentType: String, maximumBytes: Int = Self.defaultMaximumBytes) throws {
        let identity = try FileIdentity.read(from: fileURL)
        guard identity.byteCount <= Int64(maximumBytes) else {
            throw NativeMultipartFileError.payloadTooLarge(maximumBytes: maximumBytes)
        }
        self.fileURL = fileURL
        self.contentType = contentType
        self.byteCount = identity.byteCount
        self.identity = identity
    }

    /// A repeatable, file-backed part body for the generated multipart API inputs.
    func httpBody() -> HTTPBody {
        HTTPBody(
            FileChunkSequence(
                fileURL: fileURL,
                identity: identity,
                byteCount: byteCount,
                chunkSize: Self.chunkSize
            ),
            length: .known(byteCount),
            iterationBehavior: .multiple
        )
    }
}

enum NativeMultipartFileError: Error, Equatable {
    case notRegularFile
    case payloadTooLarge(maximumBytes: Int)
    case fileChanged
}

private struct FileIdentity: Sendable, Equatable {
    let device: UInt64
    let inode: UInt64
    let byteCount: Int64

    static func read(from fileURL: URL) throws -> Self {
        var metadata = Darwin.stat()
        guard Darwin.lstat(fileURL.path, &metadata) == 0,
              (metadata.st_mode & S_IFMT) == S_IFREG
        else {
            throw NativeMultipartFileError.notRegularFile
        }
        return Self(
            device: UInt64(metadata.st_dev),
            inode: UInt64(metadata.st_ino),
            byteCount: metadata.st_size
        )
    }

    static func read(from handle: FileHandle) throws -> Self {
        var metadata = Darwin.stat()
        guard Darwin.fstat(handle.fileDescriptor, &metadata) == 0,
              (metadata.st_mode & S_IFMT) == S_IFREG
        else {
            throw NativeMultipartFileError.fileChanged
        }
        return Self(
            device: UInt64(metadata.st_dev),
            inode: UInt64(metadata.st_ino),
            byteCount: metadata.st_size
        )
    }
}

private struct FileChunkSequence: AsyncSequence, Sendable {
    typealias Element = HTTPBody.ByteChunk

    let fileURL: URL
    let identity: FileIdentity
    let byteCount: Int64
    let chunkSize: Int

    func makeAsyncIterator() -> Iterator {
        Iterator(
            fileURL: fileURL,
            identity: identity,
            byteCount: byteCount,
            chunkSize: chunkSize
        )
    }

    struct Iterator: AsyncIteratorProtocol {
        private let fileURL: URL
        private let identity: FileIdentity
        private let chunkSize: Int
        private var handle: FileHandle?
        private var remainingBytes: Int64

        init(fileURL: URL, identity: FileIdentity, byteCount: Int64, chunkSize: Int) {
            self.fileURL = fileURL
            self.identity = identity
            self.chunkSize = chunkSize
            self.remainingBytes = byteCount
        }

        mutating func next() async throws -> HTTPBody.ByteChunk? {
            do {
                try Task.checkCancellation()
                if handle == nil {
                    let opened = try FileHandle(forReadingFrom: fileURL)
                    guard try FileIdentity.read(from: opened) == identity else {
                        try? opened.close()
                        throw NativeMultipartFileError.fileChanged
                    }
                    handle = opened
                }
                guard let handle else { throw NativeMultipartFileError.fileChanged }
                guard try FileIdentity.read(from: handle) == identity else {
                    throw NativeMultipartFileError.fileChanged
                }
                guard remainingBytes > 0 else {
                    closeHandle()
                    return nil
                }
                let count = Int(Swift.min(Int64(chunkSize), remainingBytes))
                guard let data = try handle.read(upToCount: count),
                      !data.isEmpty,
                      Int64(data.count) <= remainingBytes
                else {
                    throw NativeMultipartFileError.fileChanged
                }
                remainingBytes -= Int64(data.count)
                return ArraySlice(data)
            } catch {
                closeHandle()
                if error is CancellationError {
                    throw CancellationError()
                }
                if let multipartError = error as? NativeMultipartFileError {
                    throw multipartError
                }
                throw NativeMultipartFileError.fileChanged
            }
        }

        private mutating func closeHandle() {
            try? handle?.close()
            handle = nil
        }
    }
}
