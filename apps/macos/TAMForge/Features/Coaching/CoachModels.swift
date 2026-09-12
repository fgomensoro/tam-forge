import Foundation

/// One evidence line the coach proposed; the learner decides whether it lands.
struct CoachEvidenceProposal: Codable, Equatable, Sendable, Identifiable {
    let index: Int
    let kind: String
    let text: String
    let accepted: Bool

    var id: Int { index }
}

struct CoachMessage: Codable, Equatable, Sendable, Identifiable {
    let id: Int
    let speaker: String
    let text: String
    let nextStep: String?
    let proposedEvidence: [CoachEvidenceProposal]
    let createdAt: Date

    var isCoach: Bool { speaker == "coach" }

    enum CodingKeys: String, CodingKey {
        case id, speaker, text
        case nextStep = "next_step"
        case proposedEvidence = "proposed_evidence"
        case createdAt = "created_at"
    }
}

/// The server's view of an activity's coaching thread. The server decides
/// whether coaching is allowed for the block; the app only renders that answer.
struct CoachThread: Codable, Equatable, Sendable {
    let activityID: Int
    let threadID: Int?
    let coachingAllowed: Bool
    let committed: Bool
    let nextStep: String
    let messages: [CoachMessage]

    enum CodingKeys: String, CodingKey {
        case activityID = "activity_id"
        case threadID = "thread_id"
        case coachingAllowed = "coaching_allowed"
        case committed, messages
        case nextStep = "next_step"
    }
}

enum CoachAPIError: Error, Equatable {
    case unauthorized
    case notAllowed
    case unavailable
    case conflict
    case invalidResponse
    case network
    case cancelled

    var message: String {
        switch self {
        case .unauthorized: "Sign in again to talk to the coach."
        case .notAllowed: "Coaching is not available for this block."
        case .unavailable: "The coach is unavailable right now. Your work is unaffected; try again later."
        case .conflict: "The coach thread changed on the server. Reload and try again."
        case .invalidResponse: "The coach answered in a form this app cannot read."
        case .network: "The coach could not be reached. Check the connection and try again."
        case .cancelled: "The coach request was cancelled."
        }
    }
}
