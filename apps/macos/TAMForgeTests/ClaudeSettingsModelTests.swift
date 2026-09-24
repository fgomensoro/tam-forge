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

    func testTheLiveClientReadsAndSwitchesTheSlot() async throws {
        let fixture = URLProtocolFixture()
        fixture.enqueue(.response(statusCode: 200, body: Data(#"{"slot": "b"}"#.utf8)))
        fixture.enqueue(.response(statusCode: 200, body: Data(#"{"slot": "a"}"#.utf8)))
        let api = LiveClaudeStatusAPI(transport: NativeAPITransport(
            baseURL: URL(string: "https://api.example.test")!, session: fixture.session()
        ))

        let slot = try await api.activeSlot()
        try await api.chooseSlot(.a)

        XCTAssertEqual(slot, .b)
        XCTAssertEqual(fixture.requests.map(\.httpMethod), ["GET", "PUT"])
        XCTAssertEqual(fixture.requests.map { $0.url?.path }, ["/ops/claude/slot", "/ops/claude/slot"])
    }

    func testChoosingASlotSwitchesAndShowsThePendingSwitch() async {
        let api = SlotRecordingAPI()
        let model = ClaudeSettingsModel(api: api)
        await model.refresh()
        XCTAssertEqual(model.slot, .a)

        await model.choose(.b)

        XCTAssertEqual(api.chosen, [.b])
        XCTAssertEqual(model.slot, .b)
        XCTAssertEqual(model.switchedSlot, .b)
        XCTAssertNil(model.state)

        await model.choose(.b)
        XCTAssertEqual(api.chosen, [.b])

        await model.refresh()
        XCTAssertNil(model.switchedSlot)
    }

    func testTheRotationCommandNamesTheSlot() {
        XCTAssertEqual(ClaudeSettingsModel.rotateCommand(for: .a), "make rotate-claude-token SLOT=a")
        XCTAssertEqual(ClaudeSettingsModel.rotateCommand(for: .b), "make rotate-claude-token SLOT=b")
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

    func activeSlot() async throws -> ClaudeTokenSlot { .a }
    func chooseSlot(_ slot: ClaudeTokenSlot) async throws {}
}

@MainActor
private final class SlotRecordingAPI: ClaudeStatusAPI {
    private(set) var chosen: [ClaudeTokenSlot] = []
    private var current: ClaudeTokenSlot = .a

    func claudeState() async throws -> ClaudeTokenState { .quotaSpent }
    func activeSlot() async throws -> ClaudeTokenSlot { current }
    func chooseSlot(_ slot: ClaudeTokenSlot) async throws {
        chosen.append(slot)
        current = slot
    }
}
