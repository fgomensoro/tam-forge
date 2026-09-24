import Foundation
import XCTest

@MainActor
final class ClaudeSettingsModelTests: XCTestCase {
    func testEveryHeartbeatReasonMapsToOneState() {
        XCTAssertEqual(ClaudeTokenState(status: "ok", reason: "none"), .ready)
        XCTAssertEqual(ClaudeTokenState(status: "needs_attention", reason: "auth"), .tokenRefused)
        XCTAssertEqual(ClaudeTokenState(status: "needs_attention", reason: "quota"), .quotaSpent)
        XCTAssertEqual(ClaudeTokenState(status: "needs_attention", reason: "permission_required"), .disabled)
        XCTAssertEqual(ClaudeTokenState(status: "unknown", reason: "stale"), .notReporting)
        XCTAssertEqual(ClaudeTokenState(status: "unknown", reason: "not_observed"), .notReporting)
        XCTAssertEqual(ClaudeTokenState(status: "needs_attention", reason: "service"), .serviceProblem)
    }

    func testTheLiveClientReadsTheClaudeComponentOfOpsStatus() async throws {
        let fixture = URLProtocolFixture()
        fixture.enqueue(.response(statusCode: 200, body: Data("""
        {"status": "degraded", "ready": true, "components": {
          "database": {"status": "ok", "reason": "none"},
          "claude": {"status": "needs_attention", "reason": "auth"}}}
        """.utf8)))
        let api = LiveClaudeStatusAPI(transport: NativeAPITransport(
            baseURL: URL(string: "https://api.example.test")!, session: fixture.session()
        ))

        let state = try await api.claudeState()

        XCTAssertEqual(state, .tokenRefused)
        XCTAssertEqual(fixture.requests.first?.url?.path, "/ops/status")
    }

    func testAFailedRefreshClearsTheStateAndSaysSo() async {
        let model = ClaudeSettingsModel(api: FailingClaudeStatusAPI())

        await model.refresh()

        XCTAssertNil(model.state)
        XCTAssertNotNil(model.errorMessage)
    }
}

@MainActor
private final class FailingClaudeStatusAPI: ClaudeStatusAPI {
    func claudeState() async throws -> ClaudeTokenState { throw URLError(.notConnectedToInternet) }
}
