import Foundation
import XCTest

@MainActor
final class SqlExecutionTests: XCTestCase {
    func testBlankOversizeAndInactiveQueriesNeverExecuteOrChangeDraft() async {
        for state in [ActivityState.ready, .paused, .outputCommitted, .active] {
            let (workspace, api) = await workspace(state: state)
            for query in [" \n", String(repeating: "é", count: 32_769), "select 1"] {
                workspace.updateDraft(workspace.draft.setting("query", to: query))
                let original = workspace.draft
                await workspace.runSQL()
                XCTAssertEqual(workspace.draft, original)
            }
            XCTAssertEqual(api.sqlCommands.count, state == .active ? 1 : 0)
            workspace.disappear()
        }
    }

    func testUnconfirmedRetryBindsOriginalVersionAndEditedQueryGetsNewKey() async {
        let (workspace, api) = await workspace()
        api.sqlError = SqlExecutionError.network
        workspace.updateDraft(workspace.draft.setting("query", to: "select 1"))
        await workspace.runSQL()
        api.detail.optimisticVersion = 9
        await workspace.open()
        await workspace.runSQL()
        XCTAssertEqual(api.sqlCommands.count, 2)
        XCTAssertEqual(api.sqlCommands[0], api.sqlCommands[1])
        XCTAssertEqual(api.sqlCommands[1].expectedVersion, 3)
        workspace.updateDraft(workspace.draft.setting("query", to: "select 2"))
        await workspace.runSQL()
        XCTAssertNotEqual(api.sqlCommands[2].idempotencyKey, api.sqlCommands[0].idempotencyKey)
        XCTAssertEqual(api.sqlCommands[2].expectedVersion, 9)
        XCTAssertEqual(api.sqlCommands[2].query, "select 2")
        workspace.disappear()
    }

    func testPendingRunBlocksAnotherRunAndCommitButPreservesEditsAndFocusedTime() async {
        let (workspace, api) = await workspace()
        workspace.updateDraft(workspace.draft.setting("query", to: "select 1"))
        let entered = expectation(description: "Execution entered")
        var continuation: CheckedContinuation<Void, Never>?
        api.beforeSQL = {
            entered.fulfill()
            await withCheckedContinuation { continuation = $0 }
        }
        let running = Task { await workspace.runSQL() }
        await fulfillment(of: [entered], timeout: 1)
        XCTAssertTrue(workspace.sqlExecution.isRunning)
        XCTAssertFalse(workspace.canMutate)
        XCTAssertFalse(workspace.canCommit)
        XCTAssertTrue(workspace.canEditDraft)
        workspace.updateDraft(workspace.draft.setting("query", to: "select 2"))
        let edited = workspace.draft
        let seconds = workspace.focusedSeconds(monotonicNow: 100)
        await workspace.runSQL()
        await workspace.pause()
        await workspace.commit()
        continuation?.resume()
        await running.value
        XCTAssertEqual(api.sqlCommands.count, 1)
        XCTAssertTrue(api.pauses.isEmpty)
        XCTAssertEqual(workspace.draft, edited)
        XCTAssertEqual(workspace.sqlExecution.history.first?.query, "select 1")
        XCTAssertEqual(workspace.focusedSeconds(monotonicNow: 100), seconds)
        XCTAssertTrue(api.commits.isEmpty)
        XCTAssertTrue(api.selfReviews.isEmpty)
        workspace.disappear()
    }

    func testErrorsPreserveAllAuthoredFieldsAndNeverCommitOrReview() async {
        let errors: [Error] = [SqlExecutionError.network, SqlExecutionError.unavailable, ActivityAPIError.conflict]
        for error in errors {
            let (workspace, api) = await workspace()
            let draft = workspace.draft.setting("query", to: "select 1")
                .setting("explanation", to: "My explanation")
                .setting("business_meaning", to: "My interpretation")
                .setting("assistance_used", to: "hint_ladder")
            workspace.updateDraft(draft)
            api.sqlError = error
            await workspace.runSQL()
            XCTAssertEqual(workspace.draft, draft)
            XCTAssertTrue(api.commits.isEmpty)
            XCTAssertTrue(api.selfReviews.isEmpty)
            workspace.disappear()
        }
    }

    func testHistoryReopensOnCommittedActivityWithoutReplacingRecoverableDraft() async {
        let (workspace, api) = await workspace()
        workspace.updateDraft(workspace.draft.setting("query", to: "select 1"))
        await workspace.runSQL()
        workspace.updateDraft(workspace.draft.setting("query", to: "select 2"))
        api.detail.state = .outputCommitted
        await workspace.open()
        XCTAssertEqual(workspace.sqlExecution.history.map(\.query), ["select 1"])
        XCTAssertEqual(workspace.draft.value(for: "query"), "select 2")
        XCTAssertFalse(workspace.canRunSQL)
        workspace.disappear()
        let reopened = ActivityWorkspaceModel(activityID: 41, api: api, drafts: InMemoryActivityDraftStore(),
                                              timerJournal: InMemoryActivityTimerJournal())
        await reopened.open()
        XCTAssertEqual(reopened.sqlExecution.history.map(\.query), ["select 1"])
        XCTAssertTrue(api.commits.isEmpty)
        XCTAssertTrue(api.selfReviews.isEmpty)
        reopened.disappear()
    }

    func testHideAndSleepCancelLateReceiptAndForbidNewRuns() async {
        for sleep in [false, true] {
            let (workspace, api) = await workspace()
            workspace.updateDraft(workspace.draft.setting("query", to: "select 1"))
            let entered = expectation(description: "Execution entered")
            var continuation: CheckedContinuation<Void, Never>?
            api.beforeSQL = {
                entered.fulfill()
                await withCheckedContinuation { continuation = $0 }
            }
            let running = Task { await workspace.runSQL() }
            await fulfillment(of: [entered], timeout: 1)
            if sleep { workspace.handleSleep() } else { workspace.disappear() }
            continuation?.resume()
            await running.value
            await workspace.runSQL()
            XCTAssertEqual(api.sqlCommands.count, 1)
            XCTAssertTrue(workspace.sqlExecution.history.isEmpty)
            XCTAssertFalse(workspace.sqlExecution.isRunning)
            XCTAssertEqual(workspace.draft.value(for: "query"), "select 1")
            workspace.disappear()
        }
    }

    func testEditingAwayAndBackInvalidatesAnUnconfirmedRetry() async {
        let (workspace, api) = await workspace()
        api.sqlError = SqlExecutionError.network
        workspace.updateDraft(workspace.draft.setting("query", to: "select 1"))
        await workspace.runSQL()
        workspace.updateDraft(workspace.draft.setting("query", to: "select 2"))
        workspace.updateDraft(workspace.draft.setting("query", to: "select 1"))
        await workspace.runSQL()
        XCTAssertNotEqual(api.sqlCommands[0].idempotencyKey, api.sqlCommands[1].idempotencyKey)
        workspace.disappear()
    }

    func testAccumulatedResultsRemainBoundedToTwentyReceipts() async {
        let (workspace, api) = await workspace()
        workspace.updateDraft(workspace.draft.setting("query", to: "select 1"))
        for _ in 0..<22 { await workspace.runSQL() }
        XCTAssertEqual(workspace.sqlExecution.history.count, 20)
        XCTAssertEqual(workspace.sqlExecution.history.first?.id, 22)
        XCTAssertEqual(workspace.sqlExecution.history.last?.id, 3)
        XCTAssertEqual(Set(api.sqlCommands.map(\.idempotencyKey)).count, 22)
        workspace.disappear()
    }

    func testUnauthorizedUsesWorkspaceAuthenticationRecovery() async {
        let (workspace, api) = await workspace()
        workspace.updateDraft(workspace.draft.setting("query", to: "select 1"))
        api.sqlError = ActivityAPIError.unauthorized
        await workspace.runSQL()
        XCTAssertEqual(workspace.recovery, .authenticationRequired)
        XCTAssertFalse(workspace.canRunSQL)
        XCTAssertTrue(workspace.sqlExecution.history.isEmpty)
    }

    private func workspace(state: ActivityState = .active) async -> (ActivityWorkspaceModel, ActivityAPIStub) {
        var detail = ActivityFixtures.detail(state: state)
        detail.taskContract.block = .sql
        let api = ActivityAPIStub(detail: detail)
        let workspace = ActivityWorkspaceModel(activityID: 41, api: api, drafts: InMemoryActivityDraftStore(),
                                              timerJournal: InMemoryActivityTimerJournal(), monotonicNow: { 100 })
        await workspace.open()
        return (workspace, api)
    }
}

enum SqlTestFixtures {
    static func receipt(query: String = "select 1", id: Int = 1) -> SqlExecutionReceipt {
        .init(executionID: id, activityID: 41, query: query, querySHA256: SqlExecutionReceipt.queryHash(query),
              result: .init(columns: ["value"], rows: [["1"]], elapsedMS: 8, rowCount: 1,
                            resultSHA256: String(repeating: "a", count: 64), validation: .matched,
                            exerciseKey: "fixture", exerciseVersion: 1))
    }
}
