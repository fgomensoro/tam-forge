import Foundation
import XCTest

final class RoadmapMultipartTests: XCTestCase {
    func testTokenFailureNeverSendsAnAnonymousRoadmapRequest() async throws {
        let fixture = URLProtocolFixture()
        fixture.enqueue(.response(statusCode: 200, body: Data("[]".utf8)))
        let service = LiveRoadmapService(
            baseURL: URL(string: "https://api.example.test")!,
            bearerToken: { throw URLError(.notConnectedToInternet) }, session: fixture.session()
        )
        do {
            _ = try await service.listVersions()
            XCTFail("Expected token acquisition failure")
        } catch let error as URLError {
            XCTAssertEqual(error.code, .notConnectedToInternet)
        }
        XCTAssertTrue(fixture.requests.isEmpty)
    }

    func testLiveServiceStagesWithCallerIdempotencyKey() async throws {
        let recorder = RoadmapURLProtocol.recorder
        recorder.resetResponse()
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [RoadmapURLProtocol.self]
        let service = LiveRoadmapService(
            baseURL: URL(string: "https://api.example.test")!,
            bearerToken: { "redacted-token" },
            session: URLSession(configuration: configuration)
        )
        let package = try zipPackage()

        let response = try await service.stage(package: package, idempotencyKey: "roadmap-stable-key")

        XCTAssertEqual(response.id, 17)
        XCTAssertEqual(recorder.requests.last?.url?.path, "/api/v1/roadmap-imports")
        XCTAssertEqual(recorder.requests.last?.value(forHTTPHeaderField: "Idempotency-Key"), "roadmap-stable-key")
        XCTAssertEqual(recorder.requests.last?.value(forHTTPHeaderField: "Authorization"), "Bearer redacted-token")
    }

    func testLiveServiceKeepsSecurityScopeOpenUntilUploadStarts() async throws {
        let recorder = RoadmapURLProtocol.recorder
        recorder.resetResponse()
        let scope = ScopeRecorder()
        recorder.setScopeChecker { scope.isOpen }
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [RoadmapURLProtocol.self]
        let service = LiveRoadmapService(
            baseURL: URL(string: "https://api.example.test")!,
            bearerToken: { nil },
            session: URLSession(configuration: configuration)
        )
        let fileURL = try temporaryFile(contents: Data("redacted zip".utf8))
        defer { try? FileManager.default.removeItem(at: fileURL) }
        let package = RoadmapPackage.zip(
            try RoadmapLocalFile(url: fileURL, maximumBytes: 1024),
            scope: RoadmapSecurityScope(start: { scope.start() }, stop: { scope.stop() })
        )

        _ = try await service.stage(package: package, idempotencyKey: "roadmap-stable-key")

        XCTAssertEqual(recorder.scopeStates.last, true)
        XCTAssertEqual(scope.starts, 1)
        XCTAssertEqual(scope.stops, 1)
    }

    func testLiveServiceRejectsOversizedResponseWithoutRetainingIt() async throws {
        let recorder = RoadmapURLProtocol.recorder
        recorder.setResponse(Data(repeating: 0x78, count: 2 * 1024 * 1024 + 1))
        defer { recorder.resetResponse() }
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [RoadmapURLProtocol.self]
        let service = LiveRoadmapService(
            baseURL: URL(string: "https://api.example.test")!,
            bearerToken: { nil },
            session: URLSession(configuration: configuration)
        )

        do {
            _ = try await service.stage(package: try zipPackage(), idempotencyKey: "roadmap-stable-key")
            XCTFail("Expected bounded response failure")
        } catch let error as RoadmapServiceError {
            XCTAssertEqual(error, .responseTooLarge)
        }
    }

    func testLiveServiceCallsUnauthorizedBeforeReadingMalformed401Body() async throws {
        DeferredUnauthorizedRoadmapURLProtocol.reset()
        defer { DeferredUnauthorizedRoadmapURLProtocol.releaseBody() }
        let callback = expectation(description: "unauthorized callback")
        let callbackBox = TestExpectationBox(callback)
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [DeferredUnauthorizedRoadmapURLProtocol.self]
        let service = LiveRoadmapService(
            baseURL: URL(string: "https://api.example.test")!,
            bearerToken: { nil },
            session: URLSession(configuration: configuration),
            onUnauthorized: { callbackBox.fulfill() }
        )
        let package = try zipPackage()

        let task = Task { () -> RoadmapServiceError? in
            do {
                _ = try await service.stage(package: package, idempotencyKey: "roadmap-stable-key")
                return nil
            } catch {
                return error as? RoadmapServiceError
            }
        }
        await fulfillment(of: [callback], timeout: 1)
        XCTAssertFalse(DeferredUnauthorizedRoadmapURLProtocol.didDeliverBody)

        DeferredUnauthorizedRoadmapURLProtocol.releaseBody()
        let result = await task.value
        XCTAssertEqual(result, .problem(statusCode: 401, code: nil))
    }

    func testFolderMultipartUsesNormalizedPathsAndGenericFilenames() async throws {
        let directory = try temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let fileURL = directory.appendingPathComponent("private-source-name.md")
        try Data("redacted body".utf8).write(to: fileURL)
        let file = try RoadmapLocalFile(url: fileURL, maximumBytes: 1024)
        let entry = try RoadmapFolderEntry(relativePath: "Week 1/README.md", file: file)
        let package = RoadmapPackage.folder(try RoadmapFolderPackage(entries: [entry]))

        let body = try await RoadmapMultipartBody.make(for: package)
        defer { body.remove() }
        let requestBody = try XCTUnwrap(String(data: Data(contentsOf: body.fileURL), encoding: .utf8))

        XCTAssertTrue(body.contentType.hasPrefix("multipart/form-data; boundary="))
        XCTAssertTrue(requestBody.contains("name=\"package_kind\"\r\n\r\nfolder_entries"))
        XCTAssertTrue(requestBody.contains("name=\"paths\"\r\n\r\nWeek 1/README.md"))
        XCTAssertTrue(requestBody.contains("name=\"files\"; filename=\"roadmap-file\""))
        XCTAssertTrue(requestBody.contains("redacted body"))
        XCTAssertFalse(requestBody.contains("private-source-name.md"))
        XCTAssertFalse(requestBody.contains(directory.path))
    }

    func testScopeReleasesAfterCancelledMultipartBuild() async throws {
        let fileURL = try temporaryFile(contents: Data("redacted body".utf8))
        defer { try? FileManager.default.removeItem(at: fileURL) }
        let recorder = ScopeRecorder()
        let file = try RoadmapLocalFile(url: fileURL, maximumBytes: 1024)
        let package = RoadmapPackage.zip(
            file,
            scope: RoadmapSecurityScope(
                start: { recorder.start() },
                stop: { recorder.stop() }
            )
        )

        let body = try await RoadmapMultipartBody.make(for: package)
        body.remove()

        XCTAssertEqual(recorder.starts, 1)
        XCTAssertEqual(recorder.stops, 1)
    }

    private func temporaryDirectory() throws -> URL {
        try FileManager.default.url(
            for: .itemReplacementDirectory,
            in: .userDomainMask,
            appropriateFor: FileManager.default.temporaryDirectory,
            create: true
        )
    }

    private func temporaryFile(contents: Data) throws -> URL {
        let fileURL = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try contents.write(to: fileURL)
        return fileURL
    }

    private func zipPackage() throws -> RoadmapPackage {
        let fileURL = try temporaryFile(contents: Data("redacted zip".utf8))
        addTeardownBlock { try? FileManager.default.removeItem(at: fileURL) }
        return .zip(try RoadmapLocalFile(url: fileURL, maximumBytes: 1024))
    }
}

private final class ScopeRecorder: @unchecked Sendable {
    private let lock = NSLock()
    private var startCount = 0
    private var stopCount = 0
    private var open = false

    var starts: Int { lock.withLock { startCount } }
    var stops: Int { lock.withLock { stopCount } }
    var isOpen: Bool { lock.withLock { open } }

    func start() -> Bool {
        lock.withLock {
            startCount += 1
            open = true
        }
        return true
    }

    func stop() {
        lock.withLock {
            stopCount += 1
            open = false
        }
    }
}

private final class RoadmapRequestRecorder: @unchecked Sendable {
    private let lock = NSLock()
    private var recordedRequests: [URLRequest] = []
    private var recordedScopeStates: [Bool?] = []
    private var scopeChecker: (@Sendable () -> Bool)?
    private var responseData = RoadmapRequestRecorder.defaultResponse

    private static let defaultResponse = Data("""
    {"id":17,"status":"validated","validation_report":{"accepted":true},"semantic_diff":{},"failure_code":null}
    """.utf8)

    var requests: [URLRequest] { lock.withLock { recordedRequests } }
    var scopeStates: [Bool?] { lock.withLock { recordedScopeStates } }

    func setScopeChecker(_ checker: @escaping @Sendable () -> Bool) {
        lock.withLock { scopeChecker = checker }
    }

    func setResponse(_ data: Data) {
        lock.withLock { responseData = data }
    }

    func resetResponse() {
        setResponse(Self.defaultResponse)
    }

    var response: Data { lock.withLock { responseData } }

    func record(_ request: URLRequest) {
        lock.withLock {
            recordedRequests.append(request)
            recordedScopeStates.append(scopeChecker?())
        }
    }
}

private final class RoadmapURLProtocol: URLProtocol {
    static let recorder = RoadmapRequestRecorder()

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        Self.recorder.record(request)
        let response = HTTPURLResponse(
            url: request.url!,
            statusCode: 201,
            httpVersion: nil,
            headerFields: ["Content-Type": "application/json"]
        )!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: Self.recorder.response)
        client?.urlProtocolDidFinishLoading(self)
    }

    override func stopLoading() {}
}

private final class DeferredUnauthorizedRoadmapURLProtocol: URLProtocol {
    private static let responseGate = DeferredUnauthorizedResponseGate()

    static var didDeliverBody: Bool { responseGate.didDeliverBody }

    static func reset() {
        responseGate.reset()
    }

    static func releaseBody() {
        responseGate.release()
    }

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        let response = HTTPURLResponse(
            url: request.url!,
            statusCode: 401,
            httpVersion: nil,
            headerFields: ["Content-Type": "application/json"]
        )!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        let client = client
        let gate = Self.responseGate
        DispatchQueue.global(qos: .userInitiated).async {
            gate.wait()
            gate.markDelivered()
            client?.urlProtocol(self, didLoad: Data("not valid JSON".utf8))
            client?.urlProtocolDidFinishLoading(self)
        }
    }

    override func stopLoading() { Self.releaseBody() }
}

private final class DeferredUnauthorizedResponseGate: @unchecked Sendable {
    private let lock = NSLock()
    private var bodyRelease = DispatchSemaphore(value: 0)
    private var deliveredBody = false

    var didDeliverBody: Bool { lock.withLock { deliveredBody } }

    func reset() {
        lock.withLock {
            bodyRelease = DispatchSemaphore(value: 0)
            deliveredBody = false
        }
    }

    func release() {
        lock.withLock { bodyRelease }.signal()
    }

    func wait() {
        lock.withLock { bodyRelease }.wait()
    }

    func markDelivered() {
        lock.withLock { deliveredBody = true }
    }
}

private final class TestExpectationBox: @unchecked Sendable {
    private let expectation: XCTestExpectation

    init(_ expectation: XCTestExpectation) {
        self.expectation = expectation
    }

    func fulfill() {
        expectation.fulfill()
    }
}
