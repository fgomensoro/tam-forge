import XCTest

final class TodayTaskStatusTests: XCTestCase {
    private func task(_ state: String, order: Int = 1) -> TodayTask {
        TodayTask(
            activityID: order, roadmapOrder: order, stableID: "task-\(order)", block: "deep_work",
            state: state, objective: "Objective \(order)", timeboxMinutes: 35, sourceReferences: [],
            requiredOutput: [], passCriteria: [], allowedAIRole: "none", evidenceRequirements: [],
            required: true, optimisticVersion: 1
        )
    }

    func testInFlightStatesAreCurrent() {
        for state in ["active", "paused", "output_committed"] {
            XCTAssertEqual(TodayTaskStatus(rawState: state), .current, "\(state) should be current")
        }
    }

    func testCompletedStatesAreDone() {
        for state in ["self_review_complete", "ai_processing", "feedback_ready", "demonstrated", "superseded"] {
            XCTAssertEqual(TodayTaskStatus(rawState: state), .done, "\(state) should be done")
        }
    }

    func testStatesThatStillOweWorkAreReady() {
        for state in ["ready", "needs_work", "correction_due", "incomplete"] {
            XCTAssertEqual(TodayTaskStatus(rawState: state), .ready, "\(state) should be ready")
        }
    }

    func testUnknownStateFallsBackToReady() {
        XCTAssertEqual(TodayTaskStatus(rawState: "something_new_from_the_server"), .ready)
    }

    func testRemainingCountExcludesOnlyDoneTasks() {
        let tasks = [
            task("demonstrated", order: 1), task("active", order: 2),
            task("ready", order: 3), task("needs_work", order: 4),
        ]
        XCTAssertEqual(TodayTaskStatus.remainingCount(in: tasks), 3)
    }

    func testRemainingCountIsZeroForAnEmptyDay() {
        XCTAssertEqual(TodayTaskStatus.remainingCount(in: []), 0)
    }
}
