import Foundation

struct ReviewedDimension: Codable, Equatable, Sendable, Identifiable {
    let slug: String
    let name: String
    let score: Decimal
    let maximum: Decimal
    let rationale: String
    let evidence: String

    var id: String { slug }

    init(slug: String, name: String, score: Decimal, maximum: Decimal, rationale: String, evidence: String) {
        self.slug = slug
        self.name = name
        self.score = score
        self.maximum = maximum
        self.rationale = rationale
        self.evidence = evidence
    }

    // The server sends decimals as JSON strings ("3.5"); accept numbers too.
    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        slug = try container.decode(String.self, forKey: .slug)
        name = try container.decode(String.self, forKey: .name)
        score = try Self.decimal(container, .score)
        maximum = try Self.decimal(container, .maximum)
        rationale = try container.decode(String.self, forKey: .rationale)
        evidence = try container.decode(String.self, forKey: .evidence)
    }

    private static func decimal(_ container: KeyedDecodingContainer<CodingKeys>, _ key: CodingKeys) throws -> Decimal {
        if let text = try? container.decode(String.self, forKey: key), let value = Decimal(string: text) {
            return value
        }
        return try container.decode(Decimal.self, forKey: key)
    }

    enum CodingKeys: String, CodingKey {
        case slug, name, score, maximum, rationale, evidence
    }
}

struct ReviewFinding: Codable, Equatable, Sendable {
    let statement: String
    let instruction: String
}

/// The AI review of one activity: where it stands, then the scores and the reasoning.
struct ActivityReview: Codable, Equatable, Sendable {
    let activityID: Int
    let status: String
    let failureCategory: String?
    let reviewID: Int?
    let attemptID: Int?
    let rubricSlug: String?
    let rubricVersion: String?
    let model: String?
    let verdict: String?
    let dimensions: [ReviewedDimension]
    let strengths: [ReviewFinding]
    let corrections: [ReviewFinding]
    let nextPractice: String?
    let evidenceStatus: String?
    let evidenceEventIDs: [Int]
    let createdAt: Date?

    var isReady: Bool { status == "ready" }

    enum CodingKeys: String, CodingKey {
        case status, model, verdict, dimensions, strengths, corrections
        case activityID = "activity_id"
        case failureCategory = "failure_category"
        case reviewID = "review_id"
        case attemptID = "attempt_id"
        case rubricSlug = "rubric_slug"
        case rubricVersion = "rubric_version"
        case nextPractice = "next_practice"
        case evidenceStatus = "evidence_status"
        case evidenceEventIDs = "evidence_event_ids"
        case createdAt = "created_at"
    }
}

enum ReviewAPIError: Error, Equatable {
    case unauthorized
    case notFound
    case conflict
    case unavailable
    case invalidResponse
    case network
    case cancelled

    var message: String {
        switch self {
        case .unauthorized: "Sign in again to see the review."
        case .notFound: "This activity was not found on the server."
        case .conflict: "A review needs a committed attempt with its self-review, and only one review per block."
        case .unavailable: "Reviews are unavailable right now. Your work is unaffected; try again later."
        case .invalidResponse: "The server answered in a form this app cannot read."
        case .network: "The server could not be reached. Check the connection and try again."
        case .cancelled: "The review request was cancelled."
        }
    }
}
