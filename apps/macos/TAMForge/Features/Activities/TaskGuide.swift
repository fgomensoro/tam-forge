import Foundation

/// The block's steps, spelled out from its procedure, and which one the learner is on.
/// Nothing here comes from the AI: the list is the block type's contract and the
/// current step is read off the activity state.
enum TaskGuide {
    private struct Plan {
        let steps: [String]
        let attempt: Int
        let coach: Int?
    }

    private static func plan(for block: ActivityBlock) -> Plan {
        switch block {
        case .communicationSpoken:
            Plan(steps: ["Read the question", "Independent Attempt A, written or recorded", "Commit", "Self-review", "Coach: two corrections"], attempt: 1, coach: 4)
        case .technicalLearning:
            Plan(steps: ["Read the source", "Hide the source", "Recall attempt", "Commit", "Self-review", "Coach and note"], attempt: 2, coach: 5)
        case .sql:
            Plan(steps: ["Read the problem", "Query and run", "Explain and business meaning", "Commit", "Self-review", "Coach"], attempt: 1, coach: 5)
        case .tamCase:
            Plan(steps: ["Read the prompt", "Discovery and assumptions", "Final artifact", "Commit", "Self-review", "Coach"], attempt: 1, coach: 5)
        case .careerPipeline:
            Plan(steps: ["Pick the action", "Do it", "Record it", "Commit", "Self-review"], attempt: 1, coach: nil)
        case .correctionWarmup:
            Plan(steps: ["Read the correction", "Attempt", "Commit", "Self-review"], attempt: 1, coach: nil)
        case .dailyClose:
            Plan(steps: ["Outputs and actual time, 5 min", "Recall items, 5 min", "Competency evidence, 3 min", "Exact next action, 2 min", "Commit", "Self-review"], attempt: 0, coach: nil)
        case .saturdayAssessment:
            Plan(steps: ["Read the prompt", "Independent attempt, no AI", "Commit", "Self-review"], attempt: 1, coach: nil)
        }
    }

    static func steps(for block: ActivityBlock) -> [String] {
        plan(for: block).steps
    }

    static func currentStep(for activity: ActivityDetail) -> Int? {
        let block = activity.taskContract.block
        let plan = plan(for: block)
        switch activity.state {
        case .ready, .active, .paused:
            if block == .technicalLearning, !activity.sourceHidden { return plan.attempt - 1 }
            return plan.attempt
        case .outputCommitted:
            return plan.steps.firstIndex(of: "Self-review")
        case .selfReviewComplete, .aiProcessing, .feedbackReady, .correctionDue, .demonstrated, .needsWork:
            return plan.coach ?? plan.steps.count - 1
        case .incomplete, .superseded:
            return nil
        }
    }
}
