import AVFoundation
import Foundation

/// The practice Interviewer: one turn at a time, no coaching, and nothing it can write to.
///
/// Three properties make this role different from every other one, and all three are
/// enforced by the shape of the types rather than by discipline at the call site.
///
/// A turn is uninterruptible. Once the learner starts answering, the interviewer has no
/// way to speak until the answer is committed. An interviewer that can interject is not
/// running an interview, it is running a conversation, and the thing being practised is
/// the uninterrupted answer.
///
/// Follow-ups are bounded. A real interviewer asks one or two and moves on; an unbounded
/// queue turns one question into a viva and quietly eats the session.
///
/// Its memory is read-only. `InterviewerContext` exposes no mutation at all, so this role
/// cannot write into memory another role will later read. That isolation is the reason a
/// practice interview does not leak into the tutor's view of what the learner knows.
enum InterviewerPhase: String, Equatable, Sendable {
    case awaitingQuestion
    case speaking
    case awaitingAnswer
    case answerCommitted
    case finished
}

/// What the interviewer may read. There is deliberately no setter and no mutating method.
struct InterviewerContext: Equatable, Sendable {
    let questionBank: [String]
    let roleBrief: String

    init(questionBank: [String], roleBrief: String) {
        self.questionBank = questionBank
        self.roleBrief = roleBrief
    }
}

enum InterviewerError: Error, Equatable {
    case noQuestionsLeft
    case cannotSpeakWhileAnswering
    case cannotCoach
    case followUpLimitReached
    case answerNotInProgress
    case turnAlreadyCommitted
}

/// One interviewer turn, driven forward only by events it accepts in its current phase.
struct InterviewerTurn: Equatable, Sendable {
    /// A real interviewer asks one or two and moves on.
    static let maxFollowUps = 2

    private(set) var phase: InterviewerPhase
    private(set) var askedIndex: Int
    private(set) var followUpsAsked: Int
    private(set) var spoken: [String]

    let context: InterviewerContext

    init(context: InterviewerContext) {
        self.context = context
        phase = .awaitingQuestion
        askedIndex = -1
        followUpsAsked = 0
        spoken = []
    }

    var followUpsRemaining: Int { Self.maxFollowUps - followUpsAsked }

    /// Ask the next question from the bank and speak it.
    mutating func ask() throws -> String {
        guard phase == .awaitingQuestion || phase == .answerCommitted else {
            throw InterviewerError.cannotSpeakWhileAnswering
        }
        let next = askedIndex + 1
        guard next < context.questionBank.count else { throw InterviewerError.noQuestionsLeft }
        askedIndex = next
        followUpsAsked = 0
        phase = .awaitingAnswer
        let question = context.questionBank[next]
        spoken.append(question)
        return question
    }

    /// Ask a follow-up on the question just answered, while any remain.
    mutating func askFollowUp(_ text: String) throws -> String {
        guard phase == .answerCommitted else { throw InterviewerError.cannotSpeakWhileAnswering }
        guard followUpsAsked < Self.maxFollowUps else {
            throw InterviewerError.followUpLimitReached
        }
        followUpsAsked += 1
        phase = .awaitingAnswer
        spoken.append(text)
        return text
    }

    /// Coaching is not a thing this role does, in any phase.
    mutating func coach(_ text: String) throws -> Never {
        throw InterviewerError.cannotCoach
    }

    mutating func commitAnswer() throws {
        guard phase == .awaitingAnswer else { throw InterviewerError.answerNotInProgress }
        phase = .answerCommitted
    }

    mutating func finish() {
        phase = .finished
    }
}

/// The boundary the interviewer speaks through. Local by construction: there is no URL,
/// no credential and no remote option to configure.
protocol LocalSpeechSynthesizing: AnyObject, Sendable {
    func speak(_ text: String)
}

final class RecordingSynthesizer: LocalSpeechSynthesizing, @unchecked Sendable {
    private(set) var utterances: [String] = []

    func speak(_ text: String) {
        utterances.append(text)
    }
}


/// The Mac's own voice asks the question. Nothing leaves the machine.
final class SystemSpeechSynthesizer: NSObject, LocalSpeechSynthesizing, @unchecked Sendable {
    private let synthesizer = AVSpeechSynthesizer()

    func speak(_ text: String) {
        let utterance = AVSpeechUtterance(string: text)
        utterance.voice = AVSpeechSynthesisVoice(language: "en-US")
        utterance.rate = AVSpeechUtteranceDefaultSpeechRate * 0.95
        DispatchQueue.main.async { [synthesizer] in
            synthesizer.stopSpeaking(at: .immediate)
            synthesizer.speak(utterance)
        }
    }
}

/// What free practice needs from the recorder: start, stop, the recording it made, and that
/// recording's local transcript.
@MainActor
protocol PracticeRecording: AnyObject {
    var isPracticeRecordingActive: Bool { get }
    var lastPracticeRecordingID: UUID? { get }
    func beginPracticeRecording() async
    func endPracticeRecording() async
    /// The local transcript of that recording once it is ready. Nil when transcription
    /// failed, when nothing is transcribing that recording, or when the wait is cancelled.
    /// The transcription queue has one slot and defers under memory or thermal pressure, so
    /// this may wait without bound: the caller owns the timeout.
    func practiceTranscript(for recordingID: UUID) async -> String?
}

extension RecordingCoordinator: PracticeRecording {
    var isPracticeRecordingActive: Bool { phase.isActive }
    var lastPracticeRecordingID: UUID? { lastRecordingID }
    func beginPracticeRecording() async { await start() }
    func endPracticeRecording() async { await stop() }

    func practiceTranscript(for recordingID: UUID) async -> String? {
        for await state in $transcriptState.values {
            switch state {
            case let .ready(id, result) where id == recordingID: return result.text
            case let .running(id) where id == recordingID: continue
            case let .deferred(id, _) where id == recordingID: continue
            default: return nil  // failed, idle, or the slot now belongs to another recording
            }
        }
        return nil
    }
}

/// Where the interviewer's follow-up comes from. Returns nil when there is nothing to ask;
/// throws when the role is unavailable. Either way the session moves on.
@MainActor
protocol PracticeFollowUpProviding: AnyObject {
    func followUp(
        question: String, referenceAnswer: String, transcript: String, priorFollowUps: [String]
    ) async throws -> String?
}

/// One question of a practice round: the prompt the interviewer says, and the learner's own
/// reference answer it came from, shown only after the answer is recorded.
struct PracticeQuestion: Equatable, Sendable, Identifiable {
    let entry: ReferenceEntry
    let prompt: String

    var id: Int { entry.id }
}

struct PracticeAnswer: Equatable, Sendable, Identifiable {
    let question: PracticeQuestion
    let recordingID: UUID
    /// Set together when this answer responds to a follow-up: what the interviewer asked,
    /// and the recording of the answer it followed.
    var followUpQuestion: String? = nil
    var parentRecordingID: UUID? = nil

    var id: UUID { recordingID }
}

/// Free interview practice, whenever the learner wants: the interviewer asks one answer-bank
/// question aloud, the learner answers uninterrupted while it records, and only then may
/// they compare against their own reference answer. It never coaches and never counts as a
/// block's attempt; each answer, including each answer to a follow-up, is an ordinary
/// recording the speech pipeline transcribes.
@MainActor
final class InterviewPracticeModel: ObservableObject {
    /// How long the interviewer may think before the session moves on without a follow-up.
    /// It covers the local transcript, which has no bound of its own, and the request.
    nonisolated static let followUpTimeout: Duration = .seconds(45)
    nonisolated static let followUpsEnabledKey = "interviewer.followUpsEnabled"

    @Published private(set) var questions: [PracticeQuestion] = []
    @Published private(set) var turn: InterviewerTurn?
    @Published private(set) var isAnswering = false
    @Published private(set) var answers: [PracticeAnswer] = []
    @Published private(set) var revealedReference: String?
    @Published private(set) var message: String?
    /// The follow-up the learner is being asked right now, if any.
    @Published private(set) var currentFollowUp: String?
    @Published private(set) var isPreparingFollowUp = false
    /// On by default; off trades the probing for volume. Remembered across launches.
    @Published var followUpsEnabled: Bool {
        didSet { defaults.set(followUpsEnabled, forKey: Self.followUpsEnabledKey) }
    }

    private let synthesizer: any LocalSpeechSynthesizing
    private let recorder: (any PracticeRecording)?
    private let followUps: (any PracticeFollowUpProviding)?
    private let followUpTimeout: Duration
    private let defaults: UserDefaults
    private let shuffle: ([PracticeQuestion]) -> [PracticeQuestion]
    private var askedFollowUps: [String] = []
    private var followUpRequest: UUID?

    init(
        synthesizer: any LocalSpeechSynthesizing, recorder: (any PracticeRecording)?,
        followUps: (any PracticeFollowUpProviding)? = nil,
        followUpTimeout: Duration = InterviewPracticeModel.followUpTimeout,
        defaults: UserDefaults = .standard,
        shuffle: @escaping ([PracticeQuestion]) -> [PracticeQuestion] = { $0.shuffled() }
    ) {
        self.synthesizer = synthesizer
        self.recorder = recorder
        self.followUps = followUps
        self.followUpTimeout = followUpTimeout
        self.defaults = defaults
        self.shuffle = shuffle
        followUpsEnabled = defaults.object(forKey: Self.followUpsEnabledKey) as? Bool ?? true
    }

    /// The answer bank's questions: numbered headings ("Q1. …") or ones that end in "?",
    /// with the numbering and the readiness note removed. A bank with neither offers all.
    static func questions(from entries: [ReferenceEntry]) -> [PracticeQuestion] {
        let bank = entries.filter { $0.kind == .answerBank }
        let shaped = bank.filter { entry in
            entry.heading.range(of: #"^Q\d+[.:)]"#, options: .regularExpression) != nil
                || prompt(from: entry.heading).hasSuffix("?")
        }
        return (shaped.isEmpty ? bank : shaped).map { PracticeQuestion(entry: $0, prompt: prompt(from: $0.heading)) }
    }

    static func prompt(from heading: String) -> String {
        var text = heading
        if let range = text.range(of: #"^Q\d+[.:)]\s*"#, options: .regularExpression) { text.removeSubrange(range) }
        if let range = text.range(of: #"\s+[—–-]\s+[^?]*$"#, options: .regularExpression) { text.removeSubrange(range) }
        return text.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    var isRunning: Bool { turn != nil && !isFinished }
    var isFinished: Bool { turn?.phase == .finished }
    var current: PracticeQuestion? {
        guard let turn, !isFinished, questions.indices.contains(turn.askedIndex) else { return nil }
        return questions[turn.askedIndex]
    }
    var progress: String {
        guard let turn, current != nil else { return "" }
        return "Question \(turn.askedIndex + 1) of \(questions.count)"
    }
    var canBeginAnswer: Bool { turn?.phase == .awaitingAnswer && !isAnswering && recorder != nil }
    /// What the interviewer last said for this question: the follow-up, or the question.
    var spokenPrompt: String? { currentFollowUp ?? current?.prompt }
    var canRevealReference: Bool {
        turn?.phase == .answerCommitted && revealedReference == nil && !isPreparingFollowUp
    }
    var canMoveOn: Bool { turn?.phase == .answerCommitted }

    func start(entries: [ReferenceEntry]) {
        let picked = shuffle(Self.questions(from: entries))
        guard !picked.isEmpty else {
            message = "Import your answer bank first: there is nothing to ask yet."
            return
        }
        questions = picked
        answers = []
        revealedReference = nil
        message = nil
        abandonFollowUp()
        turn = InterviewerTurn(context: InterviewerContext(questionBank: picked.map(\.prompt), roleBrief: ""))
        askNext()
    }

    func repeatQuestion() {
        guard let spokenPrompt, !isAnswering else { return }
        synthesizer.speak(spokenPrompt)
    }

    /// The learner starts talking: the recording starts and the interviewer goes silent.
    func beginAnswer() async {
        guard canBeginAnswer, let recorder else { return }
        let before = recorder.lastPracticeRecordingID
        await recorder.beginPracticeRecording()
        guard recorder.isPracticeRecordingActive, recorder.lastPracticeRecordingID != before else {
            message = "The recording did not start. Check the Recording screen for the reason."
            return
        }
        message = nil
        isAnswering = true
    }

    func endAnswer() async {
        guard isAnswering, let recorder, let current else { return }
        await recorder.endPracticeRecording()
        isAnswering = false
        try? turn?.commitAnswer()
        if let id = recorder.lastPracticeRecordingID {
            // An answer to a follow-up links to the answer that follow-up was asked about.
            let parent = currentFollowUp == nil ? nil : answers.last?.recordingID
            answers.append(PracticeAnswer(
                question: current, recordingID: id,
                followUpQuestion: currentFollowUp, parentRecordingID: parent
            ))
        }
    }

    /// After a committed answer: wait for its local transcript, ask the role for a
    /// follow-up, and speak it if there is one and the limit allows. A missing transcript,
    /// a failed request, a timeout or "nothing to ask" all leave the turn committed, so the
    /// learner moves on exactly as before. Never runs while an answer is in progress.
    func considerFollowUp() async {
        guard followUpsEnabled, followUps != nil, recorder != nil,
              let turn, turn.phase == .answerCommitted, turn.followUpsRemaining > 0,
              let question = current, let answer = answers.last, answer.question == question
        else { return }
        let request = UUID()
        followUpRequest = request
        isPreparingFollowUp = true
        let prior = askedFollowUps
        let text = await Self.firstResult(within: followUpTimeout) { [weak self] in
            await self?.requestFollowUp(for: answer, prior: prior)
        }
        guard followUpRequest == request else { return }  // the learner moved on meanwhile
        followUpRequest = nil
        isPreparingFollowUp = false
        guard let text, let spoken = try? self.turn?.askFollowUp(text) else { return }
        revealedReference = nil
        currentFollowUp = spoken
        askedFollowUps.append(spoken)
        synthesizer.speak(spoken)
    }

    private func requestFollowUp(for answer: PracticeAnswer, prior: [String]) async -> String? {
        guard let recorder, let followUps,
              let transcript = await recorder.practiceTranscript(for: answer.recordingID),
              !transcript.isEmpty
        else { return nil }
        let reply = try? await followUps.followUp(
            question: answer.question.prompt, referenceAnswer: answer.question.entry.body,
            transcript: transcript, priorFollowUps: prior
        )
        let trimmed = (reply ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? nil : trimmed
    }

    /// The work's result, or nil once the timeout passes. Whichever loses is cancelled.
    private nonisolated static func firstResult(
        within timeout: Duration, of work: @escaping @MainActor @Sendable () async -> String?
    ) async -> String? {
        await withTaskGroup(of: String?.self) { group in
            group.addTask { await work() }
            group.addTask {
                try? await Task.sleep(for: timeout)
                return nil
            }
            let first = await group.next() ?? nil
            group.cancelAll()
            return first
        }
    }

    private func abandonFollowUp() {
        followUpRequest = nil
        isPreparingFollowUp = false
        currentFollowUp = nil
        askedFollowUps = []
    }

    func revealReference() {
        guard canRevealReference, let current else { return }
        revealedReference = current.entry.body
    }

    func next() {
        guard canMoveOn else { return }
        abandonFollowUp()
        revealedReference = nil
        askNext()
    }

    func stop() {
        guard !isAnswering else { return }
        abandonFollowUp()
        turn?.finish()
    }

    private func askNext() {
        do {
            if let question = try turn?.ask() { synthesizer.speak(question) }
        } catch {
            turn?.finish()
        }
    }
}
