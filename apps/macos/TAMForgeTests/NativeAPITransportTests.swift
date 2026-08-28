import Foundation
import HTTPTypes
import OpenAPIRuntime
import XCTest

final class NativeAPITransportTests: XCTestCase {
    func testRequestUsesBaseURLBearerAndCallerIdempotencyKey() async throws {
        let fixture = URLProtocolFixture()
        fixture.enqueue(.response(statusCode: 200, body: #"{"value":"ok"}"#.data(using: .utf8)!))
        let transport = NativeAPITransport(
            baseURL: URL(string: "https://api.example.test/api")!,
            bearerToken: { "test-bearer-token" },
            session: fixture.session()
        )

        let response = try await transport.send(
            NativeAPIRequest(
                method: .post,
                path: "/v1/commands",
                body: #"{"command":"start"}"#.data(using: .utf8)!,
                idempotencyKey: "stable-command-key"
            )
        )

        XCTAssertEqual(response.statusCode, 200)
        XCTAssertEqual(
            try response.decoded(as: ValuePayload.self),
            ValuePayload(value: "ok")
        )
        let request = try XCTUnwrap(fixture.requests.first)
        XCTAssertEqual(request.httpMethod, "POST")
        XCTAssertEqual(request.url?.absoluteString, "https://api.example.test/api/v1/commands")
        XCTAssertEqual(request.value(forHTTPHeaderField: "Authorization"), "Bearer test-bearer-token")
        XCTAssertEqual(request.value(forHTTPHeaderField: "Idempotency-Key"), "stable-command-key")
    }

    func testNoContentReturnsTypedEmptySuccess() async throws {
        let fixture = URLProtocolFixture()
        fixture.enqueue(.response(statusCode: 204, body: nil))
        let transport = NativeAPITransport(baseURL: URL(string: "https://api.example.test")!, session: fixture.session())

        let response = try await transport.send(NativeAPIRequest(method: .post, path: "/logout"))

        XCTAssertEqual(response.statusCode, 204)
        XCTAssertNil(response.body)
    }

    func testProblemDetailsMapAndMalformedBodiesFailClosed() async throws {
        let fixture = URLProtocolFixture()
        fixture.enqueue(
            .response(
                statusCode: 400,
                body: #"{"type":"https://example.test/problem","title":"Invalid command","status":400,"detail":"Fix input"}"#.data(using: .utf8)!
            )
        )
        fixture.enqueue(.response(statusCode: 500, body: Data("not-json".utf8)))
        let transport = NativeAPITransport(baseURL: URL(string: "https://api.example.test")!, session: fixture.session())

        do {
            _ = try await transport.send(NativeAPIRequest(method: .post, path: "/commands"))
            XCTFail("Expected problem details")
        } catch let error as NativeAPIError {
            XCTAssertEqual(
                error,
                .problem(
                    APIProblem(
                        type: "https://example.test/problem",
                        title: "Invalid command",
                        status: 400,
                        detail: "Fix input",
                        instance: nil
                    )
                )
            )
        }

        do {
            _ = try await transport.send(NativeAPIRequest(method: .get, path: "/commands"))
            XCTFail("Expected malformed problem fallback")
        } catch let error as NativeAPIError {
            XCTAssertEqual(error, .malformedProblem(statusCode: 500))
        }
    }

    func testUnauthorizedNotifiesAndDiagnosticsRedactSecrets() async throws {
        let fixture = URLProtocolFixture()
        fixture.enqueue(.response(statusCode: 401, body: #"{"title":"Unauthorized","status":401}"#.data(using: .utf8)!))
        let recorder = DiagnosticRecorder()
        let transport = NativeAPITransport(
            baseURL: URL(string: "https://api.example.test")!,
            bearerToken: { "test-bearer-token" },
            session: fixture.session(),
            onUnauthorized: { recorder.didNotifyUnauthorized() },
            diagnostics: { recorder.record($0) }
        )

        do {
            _ = try await transport.send(
                NativeAPIRequest(
                    method: .post,
                    path: "/commands",
                    body: Data("secret-body".utf8),
                    idempotencyKey: "secret-key"
                )
            )
            XCTFail("Expected unauthorized problem")
        } catch is NativeAPIError {
        }

        XCTAssertEqual(recorder.unauthorizedNotifications, 1)
        XCTAssertFalse(recorder.text.contains("test-bearer-token"))
        XCTAssertFalse(recorder.text.contains("secret-body"))
        XCTAssertFalse(recorder.text.contains("secret-key"))
    }

    func testRetryKeepsCallerIdempotencyKey() async throws {
        let fixture = URLProtocolFixture()
        fixture.enqueue(.error(URLError(.timedOut)))
        fixture.enqueue(.response(statusCode: 200, body: #"{"value":"ok"}"#.data(using: .utf8)!))
        let transport = NativeAPITransport(
            baseURL: URL(string: "https://api.example.test")!,
            retryPolicy: RetryPolicy(maximumAttempts: 2),
            session: fixture.session()
        )

        _ = try await transport.send(
            NativeAPIRequest(method: .post, path: "/commands", idempotencyKey: "stable-command-key")
        )

        XCTAssertEqual(fixture.requests.count, 2)
        XCTAssertEqual(
            fixture.requests.map { $0.value(forHTTPHeaderField: "Idempotency-Key") },
            ["stable-command-key", "stable-command-key"]
        )
    }

    func testCancellationPropagates() async throws {
        let fixture = URLProtocolFixture()
        fixture.enqueue(.pending)
        let transport = NativeAPITransport(baseURL: URL(string: "https://api.example.test")!, session: fixture.session())
        let task = Task { try await transport.send(NativeAPIRequest(method: .get, path: "/wait")) }

        await fixture.waitForRequest()
        task.cancel()

        do {
            _ = try await task.value
            XCTFail("Expected cancellation")
        } catch is CancellationError {
        }
    }

    func testMultipartFileStreamsFromDiskWithinBound() async throws {
        let fileURL = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)
        let payload = Data(repeating: 0x61, count: 4)
        try payload.write(to: fileURL)
        defer { try? FileManager.default.removeItem(at: fileURL) }

        let file = try NativeMultipartFile(
            fileURL: fileURL,
            contentType: "application/octet-stream",
            maximumBytes: 4
        )
        let streamed = try await Data(collecting: file.httpBody(), upTo: 4)

        XCTAssertEqual(streamed, payload)
        XCTAssertThrowsError(
            try NativeMultipartFile(
                fileURL: fileURL,
                contentType: "application/octet-stream",
                maximumBytes: 3
            )
        ) { error in
            XCTAssertEqual(error as? NativeMultipartFileError, .payloadTooLarge(maximumBytes: 3))
        }
    }
}

private struct ValuePayload: Codable, Equatable, Sendable {
    let value: String
}

private final class DiagnosticRecorder: @unchecked Sendable {
    private let lock = NSLock()
    private var entries: [NativeAPIDiagnostic] = []
    private var notifications = 0

    var text: String {
        lock.withLock { entries.map(\.description).joined(separator: "\n") }
    }

    var unauthorizedNotifications: Int {
        lock.withLock { notifications }
    }

    func record(_ diagnostic: NativeAPIDiagnostic) {
        lock.withLock { entries.append(diagnostic) }
    }

    func didNotifyUnauthorized() {
        lock.withLock { notifications += 1 }
    }
}

private final class URLProtocolFixture: @unchecked Sendable {
    fileprivate static let store = FixtureStore()

    init() {
        Self.store.reset()
    }

    func enqueue(_ outcome: Outcome) {
        Self.store.enqueue(outcome)
    }

    var requests: [URLRequest] {
        Self.store.requests
    }

    func session() -> URLSession {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [FixtureProtocol.self]
        return URLSession(configuration: configuration)
    }

    func waitForRequest() async {
        while requests.isEmpty {
            await Task.yield()
        }
    }

    enum Outcome: Sendable {
        case response(statusCode: Int, body: Data?)
        case error(URLError)
        case pending
    }
}

private final class FixtureProtocol: URLProtocol {
    private var isPending = false

    override class func canInit(with request: URLRequest) -> Bool { true }

    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        let outcome = URLProtocolFixture.store.dequeue(request)
        switch outcome {
        case let .response(statusCode, body):
            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: statusCode,
                httpVersion: "HTTP/1.1",
                headerFields: ["Content-Type": "application/problem+json"]
            )!
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            if let body {
                client?.urlProtocol(self, didLoad: body)
            }
            client?.urlProtocolDidFinishLoading(self)
        case let .error(error):
            client?.urlProtocol(self, didFailWithError: error)
        case .pending:
            isPending = true
        }
    }

    override func stopLoading() {
        if isPending {
            client?.urlProtocol(self, didFailWithError: URLError(.cancelled))
        }
    }

}

private final class FixtureStore: @unchecked Sendable {
    private let lock = NSLock()
    private var outcomes: [URLProtocolFixture.Outcome] = []
    private var capturedRequests: [URLRequest] = []

    var requests: [URLRequest] {
        lock.withLock { capturedRequests }
    }

    func enqueue(_ outcome: URLProtocolFixture.Outcome) {
        lock.withLock { outcomes.append(outcome) }
    }

    func reset() {
        lock.withLock {
            outcomes.removeAll()
            capturedRequests.removeAll()
        }
    }

    func dequeue(_ request: URLRequest) -> URLProtocolFixture.Outcome {
        lock.withLock {
            capturedRequests.append(request)
            return outcomes.removeFirst()
        }
    }
}
