import Foundation

struct ClassRecordingSummary: Codable, Equatable, Sendable, Identifiable {
    let recordingID: UUID
    let state: String
    let startedAt: Date?
    let transcriptLineageAccepted: Bool

    var id: UUID { recordingID }

    enum CodingKeys: String, CodingKey {
        case state
        case recordingID = "recording_id"
        case startedAt = "started_at"
        case transcriptLineageAccepted = "transcript_lineage_accepted"
    }
}

/// One English class session; its recordings' evidence maps to the TAM English skill.
struct EnglishClassRecord: Codable, Equatable, Sendable, Identifiable {
    let id: Int
    let teacher: String
    let startsAt: Date
    let expectedDurationMinutes: Int
    let notes: String
    let skillSlug: String
    let recordings: [ClassRecordingSummary]
    let createdAt: Date
    let updatedAt: Date

    enum CodingKeys: String, CodingKey {
        case id, teacher, notes, recordings
        case startsAt = "starts_at"
        case expectedDurationMinutes = "expected_duration_minutes"
        case skillSlug = "skill_slug"
        case createdAt = "created_at"
        case updatedAt = "updated_at"
    }
}

struct EnglishClassDraft: Codable, Equatable, Sendable {
    var teacher: String
    var startsAt: Date
    var expectedDurationMinutes: Int
    var notes: String

    static func empty(now: Date = Date()) -> EnglishClassDraft {
        EnglishClassDraft(teacher: "", startsAt: now, expectedDurationMinutes: 60, notes: "")
    }

    init(teacher: String, startsAt: Date, expectedDurationMinutes: Int, notes: String) {
        self.teacher = teacher
        self.startsAt = startsAt
        self.expectedDurationMinutes = expectedDurationMinutes
        self.notes = notes
    }

    init(record: EnglishClassRecord) {
        self.init(
            teacher: record.teacher, startsAt: record.startsAt,
            expectedDurationMinutes: record.expectedDurationMinutes, notes: record.notes
        )
    }

    var isValid: Bool {
        !teacher.trimmingCharacters(in: .whitespaces).isEmpty && (1...480).contains(expectedDurationMinutes)
    }

    enum CodingKeys: String, CodingKey {
        case teacher, notes
        case startsAt = "starts_at"
        case expectedDurationMinutes = "expected_duration_minutes"
    }
}

enum EnglishClassAPIError: Error, Equatable {
    case unauthorized
    case notFound
    case conflict
    case unavailable
    case invalidResponse
    case network
    case cancelled

    var message: String {
        switch self {
        case .unauthorized: "Sign in again to manage classes."
        case .notFound: "That class or recording was not found on the server."
        case .conflict: "That recording already belongs to another class."
        case .unavailable: "Classes are unavailable right now. Try again later."
        case .invalidResponse: "The server answered in a form this app cannot read."
        case .network: "The server could not be reached. Check the connection and try again."
        case .cancelled: "The request was cancelled."
        }
    }
}
