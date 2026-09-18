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

    private static let suite = "InterviewPracticeModelTests"

    private func freshDefaults() -> UserDefaults {
        let defaults = UserDefaults(suiteName: Self.suite)!
        defaults.removePersistentDomain(forName: Self.suite)
        return defaults
    }

    private func practice(
        _ recorder: FakePracticeRecorder, _ followUps: FakeFollowUps?, voice: RecordingSynthesizer = RecordingSynthesizer(),
        timeout: Duration = .seconds(5), defaults: UserDefaults? = nil
    ) -> InterviewPracticeModel {
        InterviewPracticeModel(
            synthesizer: voice, recorder: recorder, followUps: followUps, followUpTimeout: timeout,
            defaults: defaults ?? freshDefaults(), shuffle: { $0 }
        )
    }

    private func answer(_ model: InterviewPracticeModel) async {
        await model.beginAnswer()
        await model.endAnswer()
        await model.considerFollowUp()
    }

    func testAFollowUpIsSpokenAfterTheAnswerAndItsAnswerIsLinkedToTheFirst() async {
        let voice = RecordingSynthesizer()
        let recorder = FakePracticeRecorder()
        let followUps = FakeFollowUps()
        followUps.replies = ["What exactly did you change for that customer?", nil]
        let model = practice(recorder, followUps, voice: voice)
        model.start(entries: [entry(1, "Q1. Tell me about a difficult customer", body: "Four anchors."), entry(2, "Q2. Why us?")])

        await model.beginAnswer()
        await model.endAnswer()
        model.revealReference()
        XCTAssertEqual(model.revealedReference, "Four anchors.")
        await model.considerFollowUp()

        XCTAssertEqual(voice.utterances, ["Tell me about a difficult customer", "What exactly did you change for that customer?"])
        XCTAssertEqual(model.currentFollowUp, "What exactly did you change for that customer?")
        XCTAssertEqual(model.spokenPrompt, "What exactly did you change for that customer?")
        XCTAssertEqual(model.progress, "Question 1 of 2")  // still the same question
        XCTAssertNil(model.revealedReference)  // no reading the reference while answering the follow-up
        XCTAssertTrue(model.canBeginAnswer)
        XCTAssertFalse(model.canMoveOn)
        XCTAssertEqual(followUps.requests.first, FakeFollowUps.Request(
            question: "Tell me about a difficult customer", referenceAnswer: "Four anchors.",
            transcript: recorder.transcript!, priorFollowUps: []
        ))
        XCTAssertEqual(recorder.transcriptRequests, [recorder.ids[0]])

        await answer(model)  // the reply to this one is nil: no second follow-up
        XCTAssertEqual(model.answers.count, 2)
        XCTAssertNil(model.answers[0].followUpQuestion)
        XCTAssertNil(model.answers[0].parentRecordingID)
        XCTAssertEqual(model.answers[1].followUpQuestion, "What exactly did you change for that customer?")
        XCTAssertEqual(model.answers[1].parentRecordingID, recorder.ids[0])
        XCTAssertEqual(model.answers[1].question, model.answers[0].question)
        XCTAssertEqual(followUps.requests[1].priorFollowUps, ["What exactly did you change for that customer?"])
        XCTAssertTrue(model.canMoveOn)

        model.next()
        XCTAssertNil(model.currentFollowUp)
        XCTAssertEqual(model.spokenPrompt, "Why us?")
    }

    func testFollowUpsStopAtTwoPerQuestionAndTheThirdIsNeverRequested() async {
        let recorder = FakePracticeRecorder()
        let followUps = FakeFollowUps()
        followUps.replies = ["What exactly did you change?", "How do you know it improved?", "And then what happened?"]
        let model = practice(recorder, followUps)
        model.start(entries: [entry(1, "Q1. Tell me about a difficult customer")])

        await answer(model)
        await answer(model)
        await answer(model)

        XCTAssertEqual(followUps.requests.count, 2)
        XCTAssertEqual(model.answers.count, 3)
        XCTAssertEqual(model.answers[2].parentRecordingID, recorder.ids[1])  // a chain, not a star
        XCTAssertEqual(model.turn?.followUpsRemaining, 0)
        XCTAssertTrue(model.canMoveOn)
    }

    func testATranscriptThatNeverArrivesMovesOnAfterTheTimeout() async {
        let recorder = FakePracticeRecorder()
        recorder.transcriptNeverArrives = true
        let followUps = FakeFollowUps()
        followUps.replies = ["What exactly did you change?"]
        let model = practice(recorder, followUps, timeout: .milliseconds(50))
        model.start(entries: [entry(1, "Q1. Why?"), entry(2, "Q2. Why us?")])

        await answer(model)

        XCTAssertTrue(followUps.requests.isEmpty)
        XCTAssertFalse(model.isPreparingFollowUp)
        XCTAssertNil(model.currentFollowUp)
        XCTAssertTrue(model.canMoveOn)
        model.next()
        XCTAssertEqual(model.spokenPrompt, "Why us?")
        XCTAssertEqual(InterviewPracticeModel.followUpTimeout, .seconds(45))
    }

    func testAFailedTranscriptOrAFailedRequestMovesOnWithoutAFollowUp() async {
        let recorder = FakePracticeRecorder()
        let followUps = FakeFollowUps()
        followUps.failure = InterviewAPIError.unavailable
        let voice = RecordingSynthesizer()
        let model = practice(recorder, followUps, voice: voice)
        model.start(entries: [entry(1, "Q1. Why?"), entry(2, "Q2. Why us?")])

        await answer(model)  // the role is down: a 503 surfaces as a thrown error
        XCTAssertEqual(followUps.requests.count, 1)
        XCTAssertNil(model.currentFollowUp)
        XCTAssertNil(model.message)  // moving on is not an error the learner has to read
        XCTAssertTrue(model.canMoveOn)

        model.next()
        recorder.transcript = nil  // transcription failed, or nothing is transcribing
        followUps.failure = nil
        followUps.replies = ["What exactly did you change?"]
        await answer(model)
        XCTAssertEqual(followUps.requests.count, 1)
        XCTAssertEqual(voice.utterances, ["Why?", "Why us?"])
        XCTAssertTrue(model.canMoveOn)
    }

    func testTheSwitchTurnsFollowUpsOffAndTheChoiceIsRemembered() async {
        let defaults = freshDefaults()
        let recorder = FakePracticeRecorder()
        let followUps = FakeFollowUps()
        followUps.replies = ["What exactly did you change?"]
        let model = practice(recorder, followUps, defaults: defaults)
        XCTAssertTrue(model.followUpsEnabled)  // on by default

        model.followUpsEnabled = false
        model.start(entries: [entry(1, "Q1. Why?")])
        await answer(model)
        XCTAssertTrue(followUps.requests.isEmpty)
        XCTAssertTrue(recorder.transcriptRequests.isEmpty)
        XCTAssertTrue(model.canMoveOn)

        XCTAssertEqual(defaults.object(forKey: InterviewPracticeModel.followUpsEnabledKey) as? Bool, false)
        XCTAssertFalse(practice(recorder, followUps, defaults: defaults).followUpsEnabled)
    }

    func testMovingOnWhileTheInterviewerThinksDropsTheFollowUp() async {
        let voice = RecordingSynthesizer()
        let recorder = FakePracticeRecorder()
        let followUps = FakeFollowUps()
        followUps.replies = ["What exactly did you change?"]
        followUps.delay = .milliseconds(200)
        let model = practice(recorder, followUps, voice: voice)
        model.start(entries: [entry(1, "Q1. Why?"), entry(2, "Q2. Why us?")])
        await model.beginAnswer()
        await model.endAnswer()

        let thinking = Task { await model.considerFollowUp() }
        try? await Task.sleep(for: .milliseconds(40))
        XCTAssertTrue(model.isPreparingFollowUp)
        XCTAssertFalse(model.canRevealReference)
        model.next()
        await thinking.value

        XCTAssertEqual(voice.utterances, ["Why?", "Why us?"])
        XCTAssertNil(model.currentFollowUp)
        XCTAssertFalse(model.isPreparingFollowUp)
        XCTAssertTrue(model.canBeginAnswer)
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
    var transcript: String? = "I had an unhappy customer and I worked hard to improve things for them."
    var transcriptNeverArrives = false
    private(set) var ids: [UUID] = []
    private(set) var transcriptRequests: [UUID] = []
    private(set) var isPracticeRecordingActive = false
    var lastPracticeRecordingID: UUID? { ids.last }

    func beginPracticeRecording() async {
        guard !refuses else { return }
        ids.append(UUID())
        isPracticeRecordingActive = true
    }

    func endPracticeRecording() async { isPracticeRecordingActive = false }

    func practiceTranscript(for recordingID: UUID) async -> String? {
        transcriptRequests.append(recordingID)
        if transcriptNeverArrives {
            try? await Task.sleep(for: .seconds(30))
            return nil
        }
        return transcript
    }
}

@MainActor
private final class FakeFollowUps: PracticeFollowUpProviding {
    struct Request: Equatable {
        let question: String
        let referenceAnswer: String
        let transcript: String
        let priorFollowUps: [String]
    }

    var replies: [String?] = []
    var failure: (any Error)?
    var delay: Duration?
    private(set) var requests: [Request] = []

    func followUp(
        question: String, referenceAnswer: String, transcript: String, priorFollowUps: [String]
    ) async throws -> String? {
        requests.append(Request(
            question: question, referenceAnswer: referenceAnswer,
            transcript: transcript, priorFollowUps: priorFollowUps
        ))
        if let delay { try? await Task.sleep(for: delay) }
        if let failure { throw failure }
        return replies.isEmpty ? nil : replies.removeFirst()
    }
}
