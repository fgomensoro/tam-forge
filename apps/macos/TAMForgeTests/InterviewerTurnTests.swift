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


@MainActor
final class InterviewPracticeModelTests: XCTestCase {
    private func entry(_ id: Int, _ heading: String, kind: ReferenceKind = .answerBank, body: String = "Because.") -> ReferenceEntry {
        ReferenceEntry(
            id: id, kind: kind, documentTitle: "bank", heading: heading, body: body,
            readinessLabel: "", readinessVerified: false
        )
    }

    func testOnlyAnswerBankQuestionsAreAskedAndTheirHeadingsAreCleaned() {
        let entries = [
            entry(1, "Q1. Why are you leaving DataNest? — READY"),
            entry(2, "Q2. Tell me about yourself — DRAFT, sin grabar"),
            entry(3, "EL MOLDE UNIVERSAL (para preguntas no vistas)"),
            entry(4, "Catalog", kind: .storyCatalog),
        ]
        let questions = InterviewPracticeModel.questions(from: entries)
        XCTAssertEqual(questions.map(\.prompt), ["Why are you leaving DataNest?", "Tell me about yourself"])
        XCTAssertEqual(questions.map(\.entry.id), [1, 2])
        // A bank with no numbered or question-shaped heading still offers all its entries.
        let plain = InterviewPracticeModel.questions(from: [entry(9, "Leaving DataNest")])
        XCTAssertEqual(plain.map(\.prompt), ["Leaving DataNest"])
    }

    func testAQuestionIsSpokenTheAnswerIsRecordedUninterruptedAndTheReferenceComesAfter() async {
        let voice = RecordingSynthesizer()
        let recorder = FakePracticeRecorder()
        let model = InterviewPracticeModel(synthesizer: voice, recorder: recorder, shuffle: { $0 })
        model.start(entries: [entry(1, "Q1. Why are you leaving? — READY", body: "Four anchors."), entry(2, "Q2. Tell me about yourself")])

        XCTAssertEqual(voice.utterances, ["Why are you leaving?"])
        XCTAssertEqual(model.current?.prompt, "Why are you leaving?")
        XCTAssertEqual(model.progress, "Question 1 of 2")
        XCTAssertFalse(model.canRevealReference)  // no peeking before the answer

        await model.beginAnswer()
        XCTAssertTrue(model.isAnswering)
        model.next()  // the interviewer cannot move on while the learner is answering
        XCTAssertEqual(model.current?.prompt, "Why are you leaving?")
        XCTAssertEqual(voice.utterances.count, 1)

        await model.endAnswer()
        XCTAssertFalse(model.isAnswering)
        XCTAssertEqual(model.answers.map(\.recordingID), [recorder.ids[0]])
        XCTAssertTrue(model.canRevealReference)
        model.revealReference()
        XCTAssertEqual(model.revealedReference, "Four anchors.")

        model.next()
        XCTAssertEqual(voice.utterances, ["Why are you leaving?", "Tell me about yourself"])
        XCTAssertNil(model.revealedReference)
        await model.beginAnswer()
        await model.endAnswer()
        model.next()
        XCTAssertTrue(model.isFinished)
        XCTAssertNil(model.current)
        XCTAssertEqual(model.answers.count, 2)
    }

    func testAnAnswerThatNeverStartedRecordingIsNotCounted() async {
        let recorder = FakePracticeRecorder()
        recorder.refuses = true
        let model = InterviewPracticeModel(synthesizer: RecordingSynthesizer(), recorder: recorder, shuffle: { $0 })
        model.start(entries: [entry(1, "Q1. Why?")])
        await model.beginAnswer()
        XCTAssertFalse(model.isAnswering)
        XCTAssertEqual(model.message, "The recording did not start. Check the Recording screen for the reason.")
        XCTAssertTrue(model.answers.isEmpty)
    }
}

@MainActor
private final class FakePracticeRecorder: PracticeRecording {
    var refuses = false
    private(set) var ids: [UUID] = []
    private(set) var isPracticeRecordingActive = false
    var lastPracticeRecordingID: UUID? { ids.last }

    func beginPracticeRecording() async {
        guard !refuses else { return }
        ids.append(UUID())
        isPracticeRecordingActive = true
    }

    func endPracticeRecording() async { isPracticeRecordingActive = false }
}
