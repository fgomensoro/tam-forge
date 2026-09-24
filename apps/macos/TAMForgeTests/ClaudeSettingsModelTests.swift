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
        XCTAssertEqual(ClaudeTokenState(status: "needs_attention", reason: "processing_failure"), .serviceProblem)
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

    func testAFailedRefreshClearsAnEarlierStateAndSaysSo() async {
        let api = FlakyClaudeStatusAPI()
        let model = ClaudeSettingsModel(api: api)

        await model.refresh()
        XCTAssertEqual(model.state, .ready)
        XCTAssertNil(model.errorMessage)

        await model.refresh()
        XCTAssertNil(model.state)
        XCTAssertNotNil(model.errorMessage)
    }
}

@MainActor
private final class FlakyClaudeStatusAPI: ClaudeStatusAPI {
    private var calls = 0

    func claudeState() async throws -> ClaudeTokenState {
        calls += 1
        if calls == 1 { return .ready }
        throw URLError(.notConnectedToInternet)
    }
}
