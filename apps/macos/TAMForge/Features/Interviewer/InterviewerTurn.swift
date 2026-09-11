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
