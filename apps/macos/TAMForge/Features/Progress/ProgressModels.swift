import Foundation

/// A decimal the server sends as a string; older payloads sent numbers.
enum ProgressDecimal {
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

struct ProgressSkillPoint: Equatable, Sendable, Identifiable {
    let snapshotDate: String
    let estimatedLevel: Decimal
    var id: String { snapshotDate }
}

struct ProgressSkill: Equatable, Sendable, Identifiable {
    let slug: String
    let name: String
    let baseline: Decimal
    let monthOneTarget: Decimal
    let finalTarget: Decimal
    let latestLevel: Decimal?
    let confidence: String?
    let trend: String?
    let points: [ProgressSkillPoint]

    var id: String { slug }
    var current: Decimal { latestLevel ?? baseline }
    /// Where the skill stands between its baseline and its final target, clamped to 0...1.
    var progressFraction: Double {
        let span = finalTarget - baseline
        guard span > 0 else { return latestLevel == nil ? 0 : 1 }
        let fraction = NSDecimalNumber(decimal: (current - baseline) / span).doubleValue
        return min(max(fraction, 0), 1)
    }
}

struct ProgressWeek: Equatable, Sendable, Identifiable {
    let weekStart: String
    let plannedMinutes: Int
    let focusedMinutes: Int
    let studyDays: Int
    let closedDays: Int
    var id: String { weekStart }
    var completion: Double {
        plannedMinutes > 0 ? min(Double(focusedMinutes) / Double(plannedMinutes), 1) : 0
    }
}

struct ProgressAssessment: Equatable, Sendable, Identifiable {
    let reviewID: Int
    let activityID: Int
    let taskStableID: String
    let localDate: String
    let rubricSlug: String
    let block: String
    let averageScore: Decimal
    let dimensionCount: Int
    let verdict: String
    var id: Int { reviewID }
}

struct ProgressInterview: Equatable, Sendable, Identifiable {
    let interviewID: Int
    let company: String
    let role: String
    let stage: String
    let startsAt: Date
    let status: String
    let recordingCount: Int
    var id: Int { interviewID }
}

/// One contract of an assessment day and how it went.
struct ProgressAssessmentContract: Equatable, Sendable, Identifiable {
    let activityID: Int
    let taskStableID: String
    let contractType: String
    let result: String
    let averageScore: Decimal?
    var id: Int { activityID }
}

/// A Saturday: its contracts and the average of the ones the reviewer scored.
struct ProgressAssessmentDay: Equatable, Sendable, Identifiable {
    let studyDayID: Int
    let localDate: String
    let dayStatus: String
    let contracts: [ProgressAssessmentContract]
    let scoredContracts: Int
    let averageScore: Decimal?
    var id: Int { studyDayID }
}

struct ProgressReport: Equatable, Sendable {
    let skills: [ProgressSkill]
    let weeks: [ProgressWeek]
    let assessments: [ProgressAssessment]
    let assessmentDays: [ProgressAssessmentDay]
    let interviews: [ProgressInterview]

    static let empty = ProgressReport(skills: [], weeks: [], assessments: [], assessmentDays: [], interviews: [])
}

extension ProgressSkillPoint: Decodable {
    enum CodingKeys: String, CodingKey {
        case snapshotDate = "snapshot_date"
        case estimatedLevel = "estimated_level"
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        snapshotDate = try container.decode(String.self, forKey: .snapshotDate)
        estimatedLevel = try ProgressDecimal.decode(container, .estimatedLevel)
    }
}

extension ProgressSkill: Decodable {
    enum CodingKeys: String, CodingKey {
        case slug, name, baseline, confidence, trend, points
        case monthOneTarget = "month_one_target"
        case finalTarget = "final_target"
        case latestLevel = "latest_level"
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        slug = try container.decode(String.self, forKey: .slug)
        name = try container.decode(String.self, forKey: .name)
        baseline = try ProgressDecimal.decode(container, .baseline)
        monthOneTarget = try ProgressDecimal.decode(container, .monthOneTarget)
        finalTarget = try ProgressDecimal.decode(container, .finalTarget)
        latestLevel = try ProgressDecimal.decodeIfPresent(container, .latestLevel)
        confidence = try container.decodeIfPresent(String.self, forKey: .confidence)
        trend = try container.decodeIfPresent(String.self, forKey: .trend)
        points = try container.decode([ProgressSkillPoint].self, forKey: .points)
    }
}

extension ProgressWeek: Decodable {
    enum CodingKeys: String, CodingKey {
        case weekStart = "week_start"
        case plannedMinutes = "planned_minutes"
        case focusedMinutes = "focused_minutes"
        case studyDays = "study_days"
        case closedDays = "closed_days"
    }
}

extension ProgressAssessment: Decodable {
    enum CodingKeys: String, CodingKey {
        case verdict
        case reviewID = "review_id"
        case activityID = "activity_id"
        case taskStableID = "task_stable_id"
        case localDate = "local_date"
        case rubricSlug = "rubric_slug"
        case block
        case averageScore = "average_score"
        case dimensionCount = "dimension_count"
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        reviewID = try container.decode(Int.self, forKey: .reviewID)
        activityID = try container.decode(Int.self, forKey: .activityID)
        taskStableID = try container.decode(String.self, forKey: .taskStableID)
        localDate = try container.decode(String.self, forKey: .localDate)
        rubricSlug = try container.decode(String.self, forKey: .rubricSlug)
        block = try container.decodeIfPresent(String.self, forKey: .block) ?? ""
        averageScore = try ProgressDecimal.decode(container, .averageScore)
        dimensionCount = try container.decode(Int.self, forKey: .dimensionCount)
        verdict = try container.decode(String.self, forKey: .verdict)
    }
}

extension ProgressInterview: Decodable {
    enum CodingKeys: String, CodingKey {
        case company, role, stage, status
        case interviewID = "interview_id"
        case startsAt = "starts_at"
        case recordingCount = "recording_count"
    }
}

extension ProgressAssessmentContract: Decodable {
    enum CodingKeys: String, CodingKey {
        case result
        case activityID = "activity_id"
        case taskStableID = "task_stable_id"
        case contractType = "contract_type"
        case averageScore = "average_score"
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        activityID = try container.decode(Int.self, forKey: .activityID)
        taskStableID = try container.decode(String.self, forKey: .taskStableID)
        contractType = try container.decode(String.self, forKey: .contractType)
        result = try container.decode(String.self, forKey: .result)
        averageScore = try ProgressDecimal.decodeIfPresent(container, .averageScore)
    }
}

extension ProgressAssessmentDay: Decodable {
    enum CodingKeys: String, CodingKey {
        case contracts
        case studyDayID = "study_day_id"
        case localDate = "local_date"
        case dayStatus = "day_status"
        case scoredContracts = "scored_contracts"
        case averageScore = "average_score"
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        studyDayID = try container.decode(Int.self, forKey: .studyDayID)
        localDate = try container.decode(String.self, forKey: .localDate)
        dayStatus = try container.decode(String.self, forKey: .dayStatus)
        contracts = try container.decode([ProgressAssessmentContract].self, forKey: .contracts)
        scoredContracts = try container.decode(Int.self, forKey: .scoredContracts)
        averageScore = try ProgressDecimal.decodeIfPresent(container, .averageScore)
    }
}

extension ProgressReport: Decodable {
    enum CodingKeys: String, CodingKey {
        case skills, weeks, assessments, interviews
        case assessmentDays = "assessment_days"
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        skills = try container.decode([ProgressSkill].self, forKey: .skills)
        weeks = try container.decode([ProgressWeek].self, forKey: .weeks)
        assessments = try container.decode([ProgressAssessment].self, forKey: .assessments)
        assessmentDays = try container.decodeIfPresent([ProgressAssessmentDay].self, forKey: .assessmentDays) ?? []
        interviews = try container.decode([ProgressInterview].self, forKey: .interviews)
    }
}

enum ProgressAPIError: Error, Equatable {
    case unauthorized
    case unavailable
    case invalidResponse
    case network
    case cancelled

    var message: String {
        switch self {
        case .unauthorized: "Sign in again to see your progress."
        case .unavailable: "Progress is unavailable right now. Try again later."
        case .invalidResponse: "The server answered in a form this app cannot read."
        case .network: "The server could not be reached. Check the connection and try again."
        case .cancelled: "The request was cancelled."
        }
    }
}
