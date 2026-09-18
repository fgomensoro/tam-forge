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

/// What free practice needs from the recorder: start, stop, and the recording it made.
@MainActor
protocol PracticeRecording: AnyObject {
    var isPracticeRecordingActive: Bool { get }
    var lastPracticeRecordingID: UUID? { get }
    func beginPracticeRecording() async
    func endPracticeRecording() async
}

extension RecordingCoordinator: PracticeRecording {
    var isPracticeRecordingActive: Bool { phase.isActive }
    var lastPracticeRecordingID: UUID? { lastRecordingID }
    func beginPracticeRecording() async { await start() }
    func endPracticeRecording() async { await stop() }
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

    var id: UUID { recordingID }
}

/// Free interview practice, whenever the learner wants: the interviewer asks one answer-bank
/// question aloud, the learner answers uninterrupted while it records, and only then may
/// they compare against their own reference answer. It never coaches and never counts as a
/// block's attempt; each answer is an ordinary recording the speech pipeline transcribes.
@MainActor
final class InterviewPracticeModel: ObservableObject {
    @Published private(set) var questions: [PracticeQuestion] = []
    @Published private(set) var turn: InterviewerTurn?
    @Published private(set) var isAnswering = false
    @Published private(set) var answers: [PracticeAnswer] = []
    @Published private(set) var revealedReference: String?
    @Published private(set) var message: String?

    private let synthesizer: any LocalSpeechSynthesizing
    private let recorder: (any PracticeRecording)?
    private let shuffle: ([PracticeQuestion]) -> [PracticeQuestion]

    init(
        synthesizer: any LocalSpeechSynthesizing, recorder: (any PracticeRecording)?,
        shuffle: @escaping ([PracticeQuestion]) -> [PracticeQuestion] = { $0.shuffled() }
    ) {
        self.synthesizer = synthesizer
        self.recorder = recorder
        self.shuffle = shuffle
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
    var canRevealReference: Bool { turn?.phase == .answerCommitted && revealedReference == nil }
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
        turn = InterviewerTurn(context: InterviewerContext(questionBank: picked.map(\.prompt), roleBrief: ""))
        askNext()
    }

    func repeatQuestion() {
        guard let current, !isAnswering else { return }
        synthesizer.speak(current.prompt)
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
            answers.append(PracticeAnswer(question: current, recordingID: id))
        }
    }

    func revealReference() {
        guard canRevealReference, let current else { return }
        revealedReference = current.entry.body
    }

    func next() {
        guard canMoveOn else { return }
        revealedReference = nil
        askNext()
    }

    func stop() {
        guard !isAnswering else { return }
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
