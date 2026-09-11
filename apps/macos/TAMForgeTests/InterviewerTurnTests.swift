import XCTest

final class InterviewerTurnTests: XCTestCase {
    private func context() -> InterviewerContext {
        InterviewerContext(
            questionBank: ["Tell me about a renewal you nearly lost.", "What would you do differently?"],
            roleBrief: "Technical Account Manager, EMEA"
        )
    }

    func testATurnIsUninterruptibleOnceTheLearnerIsAnswering() throws {
        var turn = InterviewerTurn(context: context())
        _ = try turn.ask()
        XCTAssertEqual(turn.phase, .awaitingAnswer)

        XCTAssertThrowsError(try turn.ask()) { error in
            XCTAssertEqual(error as? InterviewerError, .cannotSpeakWhileAnswering)
        }
        XCTAssertThrowsError(try turn.askFollowUp("And then?")) { error in
            XCTAssertEqual(error as? InterviewerError, .cannotSpeakWhileAnswering)
        }
    }

    func testTheInterviewerNeverCoachesInAnyPhase() throws {
        var turn = InterviewerTurn(context: context())
        for _ in 0..<3 {
            XCTAssertThrowsError(try turn.coach("Try naming the trade-off.")) { error in
                XCTAssertEqual(error as? InterviewerError, .cannotCoach)
            }
            if turn.phase == .awaitingQuestion { _ = try turn.ask() } else if turn.phase == .awaitingAnswer { try turn.commitAnswer() }
        }
        XCTAssertEqual(turn.spoken.count, 1, "coaching must never reach the spoken transcript")
    }

    func testFollowUpsAreBoundedToTwoPerQuestion() throws {
        var turn = InterviewerTurn(context: context())
        _ = try turn.ask()
        try turn.commitAnswer()

        _ = try turn.askFollowUp("What did the customer say?")
        try turn.commitAnswer()
        _ = try turn.askFollowUp("And the outcome?")
        try turn.commitAnswer()
        XCTAssertEqual(turn.followUpsRemaining, 0)

        XCTAssertThrowsError(try turn.askFollowUp("One more?")) { error in
            XCTAssertEqual(error as? InterviewerError, .followUpLimitReached)
        }
    }

    func testFollowUpBudgetResetsWithEachNewQuestion() throws {
        var turn = InterviewerTurn(context: context())
        _ = try turn.ask()
        try turn.commitAnswer()
        _ = try turn.askFollowUp("Why?")
        try turn.commitAnswer()

        _ = try turn.ask()
        XCTAssertEqual(turn.followUpsRemaining, InterviewerTurn.maxFollowUps)
    }

    func testCommittingWithoutAnAnswerInProgressIsRefused() {
        var turn = InterviewerTurn(context: context())
        XCTAssertThrowsError(try turn.commitAnswer()) { error in
            XCTAssertEqual(error as? InterviewerError, .answerNotInProgress)
        }
    }

    func testRunningOutOfQuestionsIsReportedNotInvented() throws {
        var turn = InterviewerTurn(context: context())
        _ = try turn.ask(); try turn.commitAnswer()
        _ = try turn.ask(); try turn.commitAnswer()
        XCTAssertThrowsError(try turn.ask()) { error in
            XCTAssertEqual(error as? InterviewerError, .noQuestionsLeft)
        }
    }

    func testTheContextExposesNoWayToWrite() {
        // Every stored property is a `let`; the type has no mutating members. If a
        // setter or mutating method is ever added, this stops compiling as a value
        // that can be handed to the interviewer without a copy, which is the point.
        let context = self.context()
        let mirror = Mirror(reflecting: context)
        XCTAssertEqual(Set(mirror.children.compactMap(\.label)), ["questionBank", "roleBrief"])
    }

    func testSpeechGoesThroughTheLocalSynthesizerOnly() throws {
        let synthesizer = RecordingSynthesizer()
        var turn = InterviewerTurn(context: context())
        synthesizer.speak(try turn.ask())
        try turn.commitAnswer()
        synthesizer.speak(try turn.askFollowUp("Why?"))

        XCTAssertEqual(synthesizer.utterances, turn.spoken)
    }
}
