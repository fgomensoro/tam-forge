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

// MARK: - Timeline

/// One comparison score; in a trend the `slug` carries the interview id as text.
struct TimelineDimensionScore: Equatable, Sendable, Identifiable {
    let slug: String
    let score: Decimal
    var id: String { slug }
}

struct TimelineSkillEffect: Codable, Equatable, Sendable, Identifiable {
    let skillSlug: String
    let direction: String
    var id: String { skillSlug }

    enum CodingKeys: String, CodingKey {
        case direction
        case skillSlug = "skill_slug"
    }
}

struct TimelineGap: Codable, Equatable, Sendable, Identifiable {
    let statement: String
    let skillSlug: String
    var id: String { skillSlug + statement }

    enum CodingKeys: String, CodingKey {
        case statement
        case skillSlug = "skill_slug"
    }
}

/// One interview in sequence with its debrief's scores when it has one.
struct InterviewTimelineItem: Equatable, Sendable, Identifiable {
    let interviewID: Int
    let company: String
    let role: String
    let stage: String
    let startsAt: Date
    let status: String
    let hasDebrief: Bool
    let hiringProgression: String?
    let dimensions: [TimelineDimensionScore]
    let skillsAffected: [TimelineSkillEffect]
    let gaps: [TimelineGap]
    var id: Int { interviewID }

    func score(_ slug: String) -> Decimal? { dimensions.first { $0.slug == slug }?.score }
}

struct RecurringGap: Codable, Equatable, Sendable, Identifiable {
    let skillSlug: String
    let interviewCount: Int
    let statements: [String]
    var id: String { skillSlug }

    enum CodingKeys: String, CodingKey {
        case statements
        case skillSlug = "skill_slug"
        case interviewCount = "interview_count"
    }
}

struct DimensionTrend: Equatable, Sendable, Identifiable {
    let slug: String
    let name: String
    let scores: [TimelineDimensionScore]
    let latest: Decimal?
    let deltaFromFirst: Decimal?
    var id: String { slug }
}

struct InterviewTimeline: Equatable, Sendable {
    let items: [InterviewTimelineItem]
    let debriefed: Int
    let dimensionTrends: [DimensionTrend]
    let recurringGaps: [RecurringGap]

    static let empty = InterviewTimeline(items: [], debriefed: 0, dimensionTrends: [], recurringGaps: [])
}

private enum TimelineDecimal {
    static func decode<Keys: CodingKey>(_ container: KeyedDecodingContainer<Keys>, _ key: Keys) throws -> Decimal {
        if let text = try? container.decode(String.self, forKey: key), let value = Decimal(string: text) {
            return value
        }
        return try container.decode(Decimal.self, forKey: key)
    }

    static func decodeIfPresent<Keys: CodingKey>(_ container: KeyedDecodingContainer<Keys>, _ key: Keys) throws -> Decimal? {
        if try container.decodeNil(forKey: key) { return nil }
        return try decode(container, key)
    }
}

extension TimelineDimensionScore: Decodable {
    enum CodingKeys: String, CodingKey { case slug, score }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        slug = try container.decode(String.self, forKey: .slug)
        score = try TimelineDecimal.decode(container, .score)
    }
}

extension InterviewTimelineItem: Decodable {
    enum CodingKeys: String, CodingKey {
        case company, role, stage, status, dimensions, gaps
        case interviewID = "interview_id"
        case startsAt = "starts_at"
        case hasDebrief = "has_debrief"
        case hiringProgression = "hiring_progression"
        case skillsAffected = "skills_affected"
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        interviewID = try container.decode(Int.self, forKey: .interviewID)
        company = try container.decode(String.self, forKey: .company)
        role = try container.decode(String.self, forKey: .role)
        stage = try container.decode(String.self, forKey: .stage)
        startsAt = try container.decode(Date.self, forKey: .startsAt)
        status = try container.decode(String.self, forKey: .status)
        hasDebrief = try container.decode(Bool.self, forKey: .hasDebrief)
        hiringProgression = try container.decodeIfPresent(String.self, forKey: .hiringProgression)
        dimensions = try container.decodeIfPresent([TimelineDimensionScore].self, forKey: .dimensions) ?? []
        skillsAffected = try container.decodeIfPresent([TimelineSkillEffect].self, forKey: .skillsAffected) ?? []
        gaps = try container.decodeIfPresent([TimelineGap].self, forKey: .gaps) ?? []
    }
}

extension DimensionTrend: Decodable {
    enum CodingKeys: String, CodingKey {
        case slug, name, scores, latest
        case deltaFromFirst = "delta_from_first"
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        slug = try container.decode(String.self, forKey: .slug)
        name = try container.decode(String.self, forKey: .name)
        scores = try container.decode([TimelineDimensionScore].self, forKey: .scores)
        latest = try TimelineDecimal.decodeIfPresent(container, .latest)
        deltaFromFirst = try TimelineDecimal.decodeIfPresent(container, .deltaFromFirst)
    }
}

extension InterviewTimeline: Decodable {
    enum CodingKeys: String, CodingKey {
        case items, debriefed
        case dimensionTrends = "dimension_trends"
        case recurringGaps = "recurring_gaps"
    }
}

/// The two reference documents the Coach and the interview debrief may cite.
enum ReferenceKind: String, Codable, CaseIterable, Sendable, Identifiable {
    case answerBank = "answer_bank"
    case storyCatalog = "story_catalog"

    var id: String { rawValue }

    var title: String {
        switch self {
        case .answerBank: "Answer bank"
        case .storyCatalog: "Story catalog"
        }
    }
}

/// One entry of a reference document: a heading and the text under it. The readiness label
/// is what the document claimed ("READY", "DRAFT"); nothing here has been demonstrated.
struct ReferenceEntry: Codable, Equatable, Sendable, Identifiable {
    let id: Int
    let kind: ReferenceKind
    let documentTitle: String
    let heading: String
    let body: String
    let readinessLabel: String
    let readinessVerified: Bool

    enum CodingKeys: String, CodingKey {
        case id, kind, heading, body
        case documentTitle = "document_title"
        case readinessLabel = "readiness_label"
        case readinessVerified = "readiness_verified"
    }
}

/// What one import did: entries that were new, and entries the server already had.
struct ReferenceImportOutcome: Codable, Equatable, Sendable {
    let kind: ReferenceKind
    let created: Int
    let existing: Int
    let entries: [ReferenceEntry]
}
