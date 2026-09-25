import XCTest

final class TaskGuideTests: XCTestCase {
    private func detail(block: ActivityBlock, state: ActivityState, sourceHidden: Bool = false) -> ActivityDetail {
        var detail = ActivityFixtures.detail(state: state)
        detail.taskContract.block = block
        detail.sourceHidden = sourceHidden
        return detail
    }

    func testEveryBlockHasStepsThatEndInCommitOrLater() {
        for block in ActivityBlock.allCases {
            let steps = TaskGuide.steps(for: block)
            XCTAssertFalse(steps.isEmpty, "\(block) has no steps")
            XCTAssertTrue(steps.contains("Commit"), "\(block) never commits")
        }
    }

    func testTheInterviewBlockListsTheCoachedCycle() {
        XCTAssertEqual(
            TaskGuide.steps(for: .communicationSpoken),
            ["Read the question", "Independent Attempt A, written or recorded", "Commit", "Self-review", "Coach: two corrections"]
        )
    }

    func testBeforeTheCommitTheAttemptStepIsCurrent() {
        for state in [ActivityState.ready, .active, .paused] {
            XCTAssertEqual(TaskGuide.currentStep(for: detail(block: .communicationSpoken, state: state)), 1)
        }
    }

    func testTechnicalLearningPointsAtHidingTheSourceUntilItIsHidden() {
        XCTAssertEqual(TaskGuide.currentStep(for: detail(block: .technicalLearning, state: .active)), 1)
        XCTAssertEqual(TaskGuide.currentStep(for: detail(block: .technicalLearning, state: .active, sourceHidden: true)), 2)
    }

    func testAfterTheCommitTheSelfReviewIsCurrent() {
        let steps = TaskGuide.steps(for: .sql)
        XCTAssertEqual(TaskGuide.currentStep(for: detail(block: .sql, state: .outputCommitted)), steps.firstIndex(of: "Self-review"))
    }

    func testAfterTheSelfReviewTheCoachOrTheLastStepIsCurrent() {
        for state in [ActivityState.selfReviewComplete, .aiProcessing, .feedbackReady, .correctionDue, .demonstrated, .needsWork] {
            XCTAssertEqual(TaskGuide.currentStep(for: detail(block: .tamCase, state: state)), 5, "\(state)")
            XCTAssertEqual(TaskGuide.currentStep(for: detail(block: .careerPipeline, state: state)), 4, "\(state)")
        }
    }

    func testIncompleteAndSupersededHaveNoCurrentStep() {
        XCTAssertNil(TaskGuide.currentStep(for: detail(block: .sql, state: .incomplete)))
        XCTAssertNil(TaskGuide.currentStep(for: detail(block: .sql, state: .superseded)))
    }
}
