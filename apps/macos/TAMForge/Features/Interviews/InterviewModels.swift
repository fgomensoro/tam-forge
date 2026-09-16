import Foundation

struct InterviewRecordingSummary: Codable, Equatable, Sendable, Identifiable {
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

/// One real interview: the record Frank keeps, plus the recordings attached to it.
struct InterviewRecord: Codable, Equatable, Sendable, Identifiable {
    let id: Int
    let company: String
    let role: String
    let stage: String
    let startsAt: Date
    let expectedDurationMinutes: Int
    let status: String
    let privacyPermissionCode: String
    let recordings: [InterviewRecordingSummary]
    let createdAt: Date
    let updatedAt: Date

    enum CodingKeys: String, CodingKey {
        case id, company, role, stage, status, recordings
        case startsAt = "starts_at"
        case expectedDurationMinutes = "expected_duration_minutes"
        case privacyPermissionCode = "privacy_permission_code"
        case createdAt = "created_at"
        case updatedAt = "updated_at"
    }
}

/// What the learner edits; status and privacy are closed vocabularies on the server.
struct InterviewDraft: Codable, Equatable, Sendable {
    var company: String
    var role: String
    var stage: String
    var startsAt: Date
    var expectedDurationMinutes: Int
    var status: String
    var privacyPermissionCode: String

    static let statuses = ["scheduled", "completed", "cancelled", "rescheduled"]
    static let privacyCodes = [
        "permission_not_requested", "permission_granted", "permission_denied", "recording_prohibited",
    ]

    static func empty(now: Date = Date()) -> InterviewDraft {
        InterviewDraft(
            company: "", role: "", stage: "", startsAt: now, expectedDurationMinutes: 45,
            status: "scheduled", privacyPermissionCode: "permission_not_requested"
        )
    }

    init(company: String, role: String, stage: String, startsAt: Date, expectedDurationMinutes: Int,
         status: String, privacyPermissionCode: String) {
        self.company = company
        self.role = role
        self.stage = stage
        self.startsAt = startsAt
        self.expectedDurationMinutes = expectedDurationMinutes
        self.status = status
        self.privacyPermissionCode = privacyPermissionCode
    }

    init(record: InterviewRecord) {
        self.init(
            company: record.company, role: record.role, stage: record.stage, startsAt: record.startsAt,
            expectedDurationMinutes: record.expectedDurationMinutes, status: record.status,
            privacyPermissionCode: record.privacyPermissionCode
        )
    }

    var isValid: Bool {
        !company.trimmingCharacters(in: .whitespaces).isEmpty
            && !role.trimmingCharacters(in: .whitespaces).isEmpty
            && !stage.trimmingCharacters(in: .whitespaces).isEmpty
            && (1...480).contains(expectedDurationMinutes)
    }

    enum CodingKeys: String, CodingKey {
        case company, role, stage, status
        case startsAt = "starts_at"
        case expectedDurationMinutes = "expected_duration_minutes"
        case privacyPermissionCode = "privacy_permission_code"
    }
}

enum InterviewAPIError: Error, Equatable {
    case unauthorized
    case notFound
    case conflict
    case unavailable
    case invalidResponse
    case network
    case cancelled

    var message: String {
        switch self {
        case .unauthorized: "Sign in again to manage interviews."
        case .notFound: "That interview or recording was not found on the server."
        case .conflict: "That recording already belongs to another interview."
        case .unavailable: "Interviews are unavailable right now. Try again later."
        case .invalidResponse: "The server answered in a form this app cannot read."
        case .network: "The server could not be reached. Check the connection and try again."
        case .cancelled: "The request was cancelled."
        }
    }
}
