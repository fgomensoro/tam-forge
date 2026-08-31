import Foundation
import HTTPTypes
import OpenAPIRuntime
import XCTest

final class NativeAPITransportTests: XCTestCase {
    func testIndeterminateAuthenticationExpiresWithoutSendingAnonymousRequest() async throws {
        let fixture = URLProtocolFixture()
        let recorder = DiagnosticRecorder()
        let transport = NativeAPITransport(
            baseURL: URL(string: "https://api.example.test")!,
            bearerToken: { throw NativeAuthenticationError.reauthenticationRequired },
            session: fixture.session(), onUnauthorized: { recorder.didNotifyUnauthorized() }
        )
        do {
            _ = try await transport.send(.init(method: .get, path: "/protected"))
            XCTFail("Expected reauthentication requirement")
        } catch let error as NativeAuthenticationError {
            XCTAssertEqual(error, .reauthenticationRequired)
        }
        XCTAssertTrue(fixture.requests.isEmpty)
        XCTAssertEqual(recorder.unauthorizedNotifications, 1)
    }

    func testBearerAcquisitionFailureDoesNotSendAnonymousRequest() async throws {
        let fixture = URLProtocolFixture()
        fixture.enqueue(.response(statusCode: 401, body: Data("{}".utf8)))
        let recorder = DiagnosticRecorder()
        let transport = NativeAPITransport(
            baseURL: URL(string: "https://api.example.test")!,
            bearerToken: { throw URLError(.cannotConnectToHost) },
            session: fixture.session(), onUnauthorized: { recorder.didNotifyUnauthorized() }
        )
        do {
            _ = try await transport.send(.init(method: .get, path: "/protected"))
            XCTFail("Expected token acquisition failure")
        } catch let error as URLError {
            XCTAssertEqual(error.code, .cannotConnectToHost)
        } catch { XCTFail("Token failure must retain its retryable classification") }
        XCTAssertTrue(fixture.requests.isEmpty)
        XCTAssertEqual(recorder.unauthorizedNotifications, 0)
    }

    func testGeneratedResponseAcceptsPlainAndFractionalRFC3339Dates() throws {
        for timestamp in ["2026-08-27T12:00:00Z", "2026-08-27T12:00:00.123456Z"] {
            let body = Data("""
            {"id":1,"notification_type":"feedback_ready","subject_kind":"activity","subject_id":41,
             "created_at":"\(timestamp)","read_at":null}
            """.utf8)
            let response = NativeAPIResponse(statusCode: 200, body: body)
            let item = try response.decoded(as: Components.Schemas.NotificationResponse.self)
            XCTAssertEqual(item.id, 1)
            XCTAssertNil(item.readAt)
            XCTAssertGreaterThan(item.createdAt.timeIntervalSince1970, 1_700_000_000)
        }
    }

    func testGeneratedRequiredNullableCommandWritesExplicitNullWithoutLosingFields() throws {
        let command = Components.Schemas.DailyCloseCommand(
            correctionIds: [], evidenceConfirmed: true,
            evidenceManifest: .init(activityIds: [41], schemaVersion: 1),
            repeatedMistake: "Impact late", strongestOutput: "Saved attempt",
            unfinishedClassification: .none, unfinishedRequirement: nil
        )
        let body = try NativeJSONCodec.encode(command, insertingRequiredNulls: ["unfinished_requirement"])
        let object = try XCTUnwrap(JSONSerialization.jsonObject(with: body) as? [String: Any])
        XCTAssertTrue(object["unfinished_requirement"] is NSNull)
        XCTAssertEqual(object["strongest_output"] as? String, "Saved attempt")
        XCTAssertEqual(object["evidence_confirmed"] as? Bool, true)
        let decoded = try JSONDecoder().decode(Components.Schemas.DailyCloseCommand.self, from: body)
        XCTAssertEqual(decoded.evidenceManifest.activityIds, [41])
    }

    func testActivityOutputOptInAcceptsValidPayloadLargerThanOrdinaryResponses() async throws {
        let fixture = URLProtocolFixture()
        let payload = Data(repeating: 0x61, count: 2_501_832)
        fixture.enqueue(.response(statusCode: 200, body: payload))
        let transport = NativeAPITransport(baseURL: URL(string: "https://api.example.test")!, session: fixture.session())

        let response = try await transport.send(.init(
            method: .get, path: "/api/v1/activities/41", responseLimit: .activityOutput
        ))

        XCTAssertEqual(response.body, payload)
        XCTAssertEqual(NativeAPIResponseLimit.activityOutput.bytes, 96 * 1024 * 1024)
    }

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
                body: #"{"type":"https://example.test/problem","title":"Invalid command","status":400,"detail":"Fix input","code":"invalid_command"}"#.data(using: .utf8)!
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
                        instance: nil,
                        code: "invalid_command"
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

    func testProblemCodeRemainsOptionalForNonconformingUpstreamBodies() async throws {
        let fixture = URLProtocolFixture()
        fixture.enqueue(
            .response(
                statusCode: 403,
                body: #"{"title":"Forbidden","status":403}"#.data(using: .utf8)!
            )
        )
        let transport = NativeAPITransport(baseURL: URL(string: "https://api.example.test")!, session: fixture.session())

        do {
            _ = try await transport.send(NativeAPIRequest(method: .get, path: "/commands"))
            XCTFail("Expected problem details")
        } catch let error as NativeAPIError {
            XCTAssertEqual(
                error,
                .problem(
                    APIProblem(
                        type: nil,
                        title: "Forbidden",
                        status: 403,
                        detail: nil,
                        instance: nil,
                        code: nil
                    )
                )
            )
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

    func testOversizedSuccessfulResponseMapsToNativeError() async throws {
        let fixture = URLProtocolFixture()
        fixture.enqueue(.response(statusCode: 200, body: Data(repeating: 0x61, count: 2 * 1024 * 1024 + 1)))
        let transport = NativeAPITransport(baseURL: URL(string: "https://api.example.test")!, session: fixture.session())

        do {
            _ = try await transport.send(NativeAPIRequest(method: .get, path: "/large-response"))
            XCTFail("Expected oversized response error")
        } catch let error as NativeAPIError {
            XCTAssertEqual(error, .responseTooLarge)
        }
    }

    func testMutationsWithoutIdempotencyKeyDoNotRetry() async throws {
        for method: HTTPRequest.Method in [.post, .put, .patch, .delete] {
            let fixture = URLProtocolFixture()
            fixture.enqueue(.error(URLError(.timedOut)))
            fixture.enqueue(.response(statusCode: 204, body: nil))
            let transport = NativeAPITransport(
                baseURL: URL(string: "https://api.example.test")!,
                retryPolicy: RetryPolicy(maximumAttempts: 2),
                session: fixture.session()
            )

            do {
                _ = try await transport.send(NativeAPIRequest(method: method, path: "/mutation"))
                XCTFail("Expected one timed-out \(method.rawValue) attempt")
            } catch let error as URLError {
                XCTAssertEqual(error.code, .timedOut)
            }
            XCTAssertEqual(fixture.requests.count, 1, "\(method.rawValue) must not retry without a key")
        }
    }

    func testSafeMethodsRetryWithoutIdempotencyKey() async throws {
        for method: HTTPRequest.Method in [.get, .head, .options, .trace] {
            let fixture = URLProtocolFixture()
            fixture.enqueue(.error(URLError(.timedOut)))
            fixture.enqueue(.response(statusCode: 204, body: nil))
            let transport = NativeAPITransport(
                baseURL: URL(string: "https://api.example.test")!,
                retryPolicy: RetryPolicy(maximumAttempts: 2),
                session: fixture.session()
            )

            let response = try await transport.send(NativeAPIRequest(method: method, path: "/safe"))

            XCTAssertEqual(response.statusCode, 204)
            XCTAssertEqual(fixture.requests.count, 2, "\(method.rawValue) should retry once")
        }
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

    func testMultipartFileFailsClosedIfItGrowsAfterValidation() async throws {
        let fileURL = try makeTemporaryFile(contents: Data("four".utf8))
        defer { try? FileManager.default.removeItem(at: fileURL) }
        let file = try NativeMultipartFile(fileURL: fileURL, contentType: "application/octet-stream")

        try Data("four-more".utf8).write(to: fileURL)

        try await assertFileChanged(file)
    }

    func testMultipartFileFailsClosedIfItShrinksAfterValidation() async throws {
        let fileURL = try makeTemporaryFile(contents: Data("four".utf8))
        defer { try? FileManager.default.removeItem(at: fileURL) }
        let file = try NativeMultipartFile(fileURL: fileURL, contentType: "application/octet-stream")

        try Data("x".utf8).write(to: fileURL)

        try await assertFileChanged(file)
    }

    func testMultipartFileFailsClosedIfItIsReplacedAfterValidation() async throws {
        let fileURL = try makeTemporaryFile(contents: Data("four".utf8))
        let replacementURL = try makeTemporaryFile(contents: Data("next".utf8))
        defer {
            try? FileManager.default.removeItem(at: fileURL)
            try? FileManager.default.removeItem(at: replacementURL)
        }
        let file = try NativeMultipartFile(fileURL: fileURL, contentType: "application/octet-stream")

        _ = try FileManager.default.replaceItemAt(fileURL, withItemAt: replacementURL)

        try await assertFileChanged(file)
    }

    private func makeTemporaryFile(contents: Data) throws -> URL {
        let fileURL = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try contents.write(to: fileURL)
        return fileURL
    }

    private func assertFileChanged(
        _ multipartFile: NativeMultipartFile,
        file sourceFile: StaticString = #filePath,
        line: UInt = #line
    ) async throws {
        var emittedByteCount: Int64 = 0
        do {
            for try await chunk in multipartFile.httpBody() {
                emittedByteCount += Int64(chunk.count)
            }
            XCTFail("Expected changed file to fail", file: sourceFile, line: line)
        } catch {
            XCTAssertEqual(error as? NativeMultipartFileError, .fileChanged, file: sourceFile, line: line)
        }
        XCTAssertLessThanOrEqual(
            emittedByteCount,
            multipartFile.byteCount,
            file: sourceFile,
            line: line
        )
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

final class URLProtocolFixture: @unchecked Sendable {
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
