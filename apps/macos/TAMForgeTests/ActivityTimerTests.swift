import XCTest

@MainActor
final class ActivityTimerTests: XCTestCase {
    func testReplayedHeartbeatReceiptCannotRollBackNewerVersionOrSequence() async {
        for version in [3, 8] {
            let detail = ActivityFixtures.detail(state: .active)
            let api = ActivityAPIStub(detail: detail)
            let journal = InMemoryActivityTimerJournal()
            var now: TimeInterval = 100
            let model = ActivityWorkspaceModel(activityID: 41, api: api,
                                               drafts: InMemoryActivityDraftStore(), timerJournal: journal,
                                               monotonicNow: { now })
            await model.open()
            api.heartbeatError = .network
            await model.heartbeat()
            var receipt = detail.summary
            receipt.openTimer?.lastClientSequence = 5
            api.heartbeatError = nil
            api.heartbeatResponse = receipt
            api.detail.optimisticVersion = version
            api.detail.activityFocusedSeconds = 200
            api.detail.openTimer?.lastClientSequence = 10
            await model.open()
            now = 110

            await model.heartbeat()

            XCTAssertEqual(model.activity?.optimisticVersion, version)
            XCTAssertEqual(model.activity?.activityFocusedSeconds, 200)
            XCTAssertEqual(model.activity?.openTimer?.lastClientSequence, 10)
            XCTAssertEqual(model.focusedSeconds(), 210)
            XCTAssertNil(journal.load(activityID: 41))
            model.disappear()
        }
    }

    func testResumeReconcilesPendingPauseBeforeStartingAnotherTimer() async {
        let api = ActivityAPIStub(detail: ActivityFixtures.detail(state: .active))
        let journal = InMemoryActivityTimerJournal()
        let model = ActivityWorkspaceModel(activityID: 41, api: api,
                                           drafts: InMemoryActivityDraftStore(), timerJournal: journal)
        await model.open()
        api.pauseError = .network
        await model.pause()
        api.detail = ActivityFixtures.detail(state: .paused, version: 4)
        api.pauseError = nil
        api.pauseResponse = api.detail.summary
        await model.open()

        await model.resume()

        XCTAssertEqual(api.pauses.count, 2)
        XCTAssertEqual(api.pauses.first, api.pauses.last)
        XCTAssertEqual(api.resumeVersions, [4])
        XCTAssertNil(journal.load(activityID: 41))
        XCTAssertEqual(model.activity?.state, .active)
        model.disappear()
    }

    func testWorkspaceRetainsMonotonicAnchorAcrossTicksUntilNextServerSnapshot() async {
        let detail = ActivityFixtures.detail(state: .active)
        let api = ActivityAPIStub(detail: detail)
        var now: TimeInterval = 100
        let model = ActivityWorkspaceModel(activityID: detail.id, api: api,
                                           drafts: InMemoryActivityDraftStore(),
                                           timerJournal: InMemoryActivityTimerJournal(), monotonicNow: { now })
        await model.open()
        defer { model.disappear() }
        now = 110
        XCTAssertEqual(model.focusedSeconds(), 130)
        model.updateDraft(model.draft.setting("audience", to: "Peer"))
        now = 115
        XCTAssertEqual(model.focusedSeconds(), 135)

        api.detail.activityFocusedSeconds = 140
        now = 120
        await model.open()
        now = 125
        XCTAssertEqual(model.focusedSeconds(), 145)
        model.handleSleep()
        now = 1_000
        XCTAssertEqual(model.focusedSeconds(), 140)
    }

    func testDisappearCancelsAutomaticHeartbeatWait() async {
        let started = expectation(description: "Heartbeat sleep started")
        let cancelled = expectation(description: "Heartbeat sleep cancelled")
        let model = ActivityWorkspaceModel(
            activityID: 41, api: ActivityAPIStub(detail: ActivityFixtures.detail(state: .active)),
            drafts: InMemoryActivityDraftStore(), timerJournal: InMemoryActivityTimerJournal(),
            heartbeatSleep: { duration in
                XCTAssertEqual(duration, .seconds(15))
                started.fulfill()
                do { try await Task.sleep(for: .seconds(30)) }
                catch { cancelled.fulfill(); throw error }
            }
        )
        await model.open()
        await fulfillment(of: [started], timeout: 1)

        model.disappear()

        await fulfillment(of: [cancelled], timeout: 1)
        XCTAssertFalse(model.canMutate)
    }

    func testSleepCancelsHeartbeatAndLateResponseCannotReplaceSnapshot() async {
        let detail = ActivityFixtures.detail(state: .active)
        let api = ActivityAPIStub(detail: detail)
        let model = ActivityWorkspaceModel(activityID: 41, api: api,
                                           drafts: InMemoryActivityDraftStore(), timerJournal: InMemoryActivityTimerJournal())
        await model.open()
        let gate = ActivityTestGate()
        api.beforeHeartbeat = { await gate.wait() }
        let heartbeat = Task { await model.heartbeat() }
        await fulfillment(of: [gate.entered], timeout: 1)

        model.handleSleep()
        api.detail.activityFocusedSeconds = 999
        gate.release()
        await heartbeat.value

        XCTAssertEqual(model.activity?.activityFocusedSeconds, 120)
        XCTAssertFalse(model.canMutate)
        await model.handleWake()
        XCTAssertEqual(model.activity?.activityFocusedSeconds, 999)
        XCTAssertTrue(model.canMutate)
        model.disappear()
    }

    func testAutomaticHeartbeatRunsAfterFifteenSecondsWhileActive() async {
        let detail = ActivityFixtures.detail(state: .active)
        let api = ActivityAPIStub(detail: detail)
        let heartbeat = expectation(description: "Automatic 15-second heartbeat")
        api.beforeHeartbeat = { heartbeat.fulfill() }
        let model = ActivityWorkspaceModel(activityID: detail.id, api: api,
                                           drafts: InMemoryActivityDraftStore(),
                                           timerJournal: InMemoryActivityTimerJournal())

        await model.open()
        await fulfillment(of: [heartbeat], timeout: 17)
        model.handleSleep()

        XCTAssertEqual(api.heartbeats.count, 1)
    }

    func testHeartbeatRetryPreservesOriginalExpectedVersionAfterReload() async throws {
        let detail = ActivityFixtures.detail(state: .active)
        let api = ActivityAPIStub(detail: detail)
        api.heartbeatError = .network
        let journal = InMemoryActivityTimerJournal()
        let timer = ActivityTimerCoordinator(activityID: detail.id, api: api, journal: journal)
        await XCTAssertThrowsErrorAsync { _ = try await timer.heartbeat(activity: detail) }
        let original = try XCTUnwrap(api.heartbeats.first)
        var refreshed = detail
        refreshed.optimisticVersion = 8
        let recreated = ActivityTimerCoordinator(activityID: detail.id, api: api, journal: journal)

        await XCTAssertThrowsErrorAsync { _ = try await recreated.heartbeat(activity: refreshed) }

        XCTAssertEqual(api.heartbeats.last, original)
    }

    func testPauseReconcilesLostHeartbeatBeforeCreatingDistinctPauseCommand() async throws {
        let detail = ActivityFixtures.detail(state: .active)
        let api = ActivityAPIStub(detail: detail)
        let model = ActivityWorkspaceModel(activityID: detail.id, api: api,
                                           drafts: InMemoryActivityDraftStore(),
                                           timerJournal: InMemoryActivityTimerJournal())
        await model.open()
        api.heartbeatError = .network
        await model.heartbeat()
        let original = try XCTUnwrap(api.heartbeats.first)
        api.heartbeatError = nil

        await model.pause()

        XCTAssertEqual(api.heartbeats, [original, original])
        let pause = try XCTUnwrap(api.pauses.first)
        XCTAssertEqual(pause.clientSequence, original.clientSequence + 1)
        XCTAssertNotEqual(pause.idempotencyKey, original.idempotencyKey)
        XCTAssertEqual(model.activity?.state, .paused)
    }

    func testPauseDoesNotProceedWhilePriorHeartbeatRemainsIndeterminate() async {
        let detail = ActivityFixtures.detail(state: .active)
        let api = ActivityAPIStub(detail: detail)
        api.heartbeatError = .network
        let model = ActivityWorkspaceModel(activityID: detail.id, api: api,
                                           drafts: InMemoryActivityDraftStore(),
                                           timerJournal: InMemoryActivityTimerJournal())
        await model.open()
        await model.heartbeat()

        await model.pause()

        XCTAssertEqual(api.heartbeats.count, 2)
        XCTAssertTrue(api.pauses.isEmpty)
        XCTAssertEqual(model.recovery, .networkRetryNeeded)
    }

    func testPendingPauseNeverReplaysAsHeartbeatAfterModelRecreation() async throws {
        let detail = ActivityFixtures.detail(state: .active)
        let api = ActivityAPIStub(detail: detail)
        let journal = InMemoryActivityTimerJournal()
        let first = ActivityWorkspaceModel(activityID: detail.id, api: api,
                                           drafts: InMemoryActivityDraftStore(), timerJournal: journal)
        await first.open()
        api.pauseError = .network
        await first.pause()
        let original = try XCTUnwrap(api.pauses.first)
        first.handleSleep()
        api.pauseError = nil
        api.detail.optimisticVersion = 8
        let recreated = ActivityWorkspaceModel(activityID: detail.id, api: api,
                                               drafts: InMemoryActivityDraftStore(), timerJournal: journal)
        await recreated.open()

        await recreated.heartbeat()

        XCTAssertTrue(api.heartbeats.isEmpty)
        XCTAssertEqual(api.pauses, [original, original])
        XCTAssertEqual(recreated.activity?.state, .paused)
        XCTAssertNil(journal.load(activityID: detail.id))
    }

    func testHeartbeatCannotRacePause() async {
        let detail = ActivityFixtures.detail(state: .active)
        let api = ActivityAPIStub(detail: detail)
        let model = ActivityWorkspaceModel(activityID: detail.id, api: api,
                                           drafts: InMemoryActivityDraftStore(),
                                           timerJournal: InMemoryActivityTimerJournal())
        await model.open()
        let gate = ActivityTestGate()
        api.beforeHeartbeat = { await gate.wait() }
        let beating = Task { await model.heartbeat() }
        await fulfillment(of: [gate.entered], timeout: 1)

        await model.pause()

        XCTAssertTrue(api.pauses.isEmpty)
        gate.release()
        await beating.value
    }

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
        XCTAssertEqual(journal.load(activityID: detail.id), .init(operation: .pause, expectedVersion: 3, clientSequence: 5, idempotencyKey: "pause-41-stable"))
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
