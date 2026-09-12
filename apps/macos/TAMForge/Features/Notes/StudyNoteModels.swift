import Foundation

struct NoteQueryItem: Codable, Equatable, Sendable {
    let query: String
    let result: String
}

struct NoteFlashcardItem: Codable, Equatable, Sendable {
    let question: String
    let answer: String
}

/// The fields the learner edits. Status, assistance and assessment are recorded by the
/// server from what happened; the app never sends them.
struct StudyNoteContent: Codable, Equatable, Sendable {
    var title: String
    var rule: String
    var explanation: String
    var example: String
    var misconceptions: [String]
    var validatedQueries: [NoteQueryItem]
    var sources: [String]
    var flashcards: [NoteFlashcardItem]

    enum CodingKeys: String, CodingKey {
        case title, rule, explanation, example, misconceptions, sources, flashcards
        case validatedQueries = "validated_queries"
    }

    static let empty = StudyNoteContent(
        title: "", rule: "", explanation: "", example: "", misconceptions: [],
        validatedQueries: [], sources: [], flashcards: []
    )
}

struct StudyNote: Codable, Equatable, Sendable {
    let id: Int
    let activityID: Int
    let stableID: String
    let localDate: String
    let status: String
    let draftedBy: String
    let assistance: String
    let assessmentStatus: String
    let title: String
    let rule: String
    let explanation: String
    let example: String
    let misconceptions: [String]
    let validatedQueries: [NoteQueryItem]
    let sources: [String]
    let flashcards: [NoteFlashcardItem]
    let artifactID: Int?
    let contentSHA256: String?
    let updatedAt: Date
    let approvedAt: Date?

    var isApproved: Bool { status == "approved" }

    var content: StudyNoteContent {
        StudyNoteContent(
            title: title, rule: rule, explanation: explanation, example: example,
            misconceptions: misconceptions, validatedQueries: validatedQueries,
            sources: sources, flashcards: flashcards
        )
    }

    enum CodingKeys: String, CodingKey {
        case id, status, assistance, title, rule, explanation, example, misconceptions, sources, flashcards
        case activityID = "activity_id"
        case stableID = "stable_id"
        case localDate = "local_date"
        case draftedBy = "drafted_by"
        case assessmentStatus = "assessment_status"
        case validatedQueries = "validated_queries"
        case artifactID = "artifact_id"
        case contentSHA256 = "content_sha256"
        case updatedAt = "updated_at"
        case approvedAt = "approved_at"
    }
}

enum StudyNoteAPIError: Error, Equatable {
    case unauthorized
    case notFound
    case conflict
    case unavailable
    case invalidResponse
    case network
    case cancelled

    var message: String {
        switch self {
        case .unauthorized: "Sign in again to work on the note."
        case .notFound: "There is no note for this block yet."
        case .conflict: "The note cannot change here: it is approved, or the block has nothing committed yet."
        case .unavailable: "Notes are unavailable right now. Your work is unaffected; try again later."
        case .invalidResponse: "The server answered in a form this app cannot read."
        case .network: "The server could not be reached. Check the connection and try again."
        case .cancelled: "The note request was cancelled."
        }
    }
}
