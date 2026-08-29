import XCTest
@testable import TAMForge

@MainActor
final class ActivityTimerTests: XCTestCase {
    func testMonotonicInterpolationNeverUsesWallClock() {
        let detail = ActivityFixtures.detail(state: .active)
        let display = ActivityTimerDisplay(activity: detail, monotonicNow: 100)

        XCTAssertEqual(display.focusedSeconds(monotonicNow: 130), 150)
        XCTAssertEqual(display.focusedSeconds(monotonicNow: 95), 120)
    }

    func testHeartbeatReusesJournaledSequenceAndKeyUntilAcknowledged() async throws {
        let detail = ActivityFixtures.detail(state: .active)
        let api = ActivityAPIStub(detail: detail)
        api.heartbeatError = .network
        let journal = InMemoryActivityTimerJournal()
        let timer = ActivityTimerCoordinator(activityID: detail.id, api: api, journal: journal, idempotency: { "heartbeat-41-stable" })

        await XCTAssertThrowsErrorAsync { _ = try await timer.heartbeat(activity: detail) }
        XCTAssertEqual(api.heartbeats.first?.clientSequence, 5)
        XCTAssertEqual(api.heartbeats.first?.idempotencyKey, "heartbeat-41-stable")

        api.heartbeatError = nil
        let resumed = ActivityTimerCoordinator(activityID: detail.id, api: api, journal: journal, idempotency: { "new-key-must-not-be-used" })
        _ = try await resumed.heartbeat(activity: detail)

        XCTAssertEqual(api.heartbeats.map(\.clientSequence), [5, 5])
        XCTAssertEqual(api.heartbeats.map(\.idempotencyKey), ["heartbeat-41-stable", "heartbeat-41-stable"])
        XCTAssertNil(journal.load(activityID: detail.id))
    }

    func testPauseRetainsItsExactJournaledCommandUntilAcknowledged() async throws {
        let detail = ActivityFixtures.detail(state: .active)
        let api = ActivityAPIStub(detail: detail)
        api.pauseError = .network
        let journal = InMemoryActivityTimerJournal()
        let model = ActivityWorkspaceModel(
            activityID: detail.id,
            api: api,
            drafts: InMemoryActivityDraftStore(),
            timerJournal: journal,
            idempotency: { "pause-41-stable" }
        )

        await model.open()
        await model.pause()
        XCTAssertEqual(journal.load(activityID: detail.id), .init(clientSequence: 5, idempotencyKey: "pause-41-stable"))
        api.pauseError = nil
        await model.pause()

        XCTAssertEqual(api.pauses.map(\.clientSequence), [5, 5])
        XCTAssertEqual(api.pauses.map(\.idempotencyKey), ["pause-41-stable", "pause-41-stable"])
        XCTAssertNil(journal.load(activityID: detail.id))
    }

    func testWakeReloadsServerStateInsteadOfCountingSleepLocally() async throws {
        let detail = ActivityFixtures.detail(state: .active)
        let api = ActivityAPIStub(detail: detail)
        let model = ActivityWorkspaceModel(activityID: detail.id, api: api, drafts: InMemoryActivityDraftStore())

        await model.open()
        model.handleSleep()
        api.detail.activityFocusedSeconds = 145
        await model.handleWake()

        XCTAssertEqual(model.activity?.activityFocusedSeconds, 145)
    }

    func testConflictReloadsInsteadOfInventingNewTimerCommand() async throws {
        let detail = ActivityFixtures.detail(state: .active)
        let api = ActivityAPIStub(detail: detail)
        api.heartbeatError = .conflict
        let model = ActivityWorkspaceModel(activityID: detail.id, api: api, drafts: InMemoryActivityDraftStore())

        await model.open()
        await model.heartbeat()

        XCTAssertEqual(model.recovery, .reloadedAfterConflict)
        XCTAssertEqual(model.activity?.optimisticVersion, detail.optimisticVersion)
    }
}
