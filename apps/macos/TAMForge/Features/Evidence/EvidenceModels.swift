import Foundation

enum EvidenceAPIError: Error, Equatable, Sendable {
    case invalidRequest
    case invalidResponse
    case unauthorized
    case unavailable
    case cancelled
}

struct EvidenceManifestEntry: Equatable, Sendable, Identifiable {
    let eventID: Int
    let usedWeight: String
    let inclusionCode: String

    var id: Int { eventID }
}

struct EvidenceSnapshot: Equatable, Sendable, Identifiable {
    let id: Int
    let formulaVersion: String
    let snapshotDate: String
    let estimatedLevel: String
    let confidence: String
    let trend: String
    let recency: String
    let baselineTargetGap: String
    let monthOneTargetGap: String
    let finalTargetGap: String
    let totalEffectiveWeight: String
    let qualifyingEventCount: Int
    let exerciseTypeCount: Int
    let lastStrongEvidenceDate: String?
    let manifest: [EvidenceManifestEntry]
    let confidenceBasis: [String: ActivityJSONValue]
    let trendBasis: [String: ActivityJSONValue]
}

struct EvidenceSkill: Equatable, Sendable, Identifiable {
    let slug: String
    let name: String
    let baseline: String
    let monthOneTarget: String
    let finalTarget: String
    let snapshot: EvidenceSnapshot?

    var id: String { slug }
}

struct EvidenceEvent: Equatable, Sendable, Identifiable {
    let id: Int
    let activityID: Int
    let attemptID: Int?
    let skillSlug: String
    let exerciseType: String
    let mappingVersion: String
    let formulaVersion: String
    let rubricSlug: String
    let rubricVersion: String
    let evaluator: String
    let practiceMode: String
    let assistance: String
    let difficulty: String
    let performanceScore: String
    let skillImpact: String
    let effectiveWeight: String
    let qualifyingForLevel: Bool
    let qualificationReason: String
    let rawDimensionScores: [String: ActivityJSONValue]
    let occurredAt: Date
}

struct EvidenceEventPage: Equatable, Sendable {
    let items: [EvidenceEvent]
    let nextCursor: Int?
}

struct EvidencePortfolioComponent: Equatable, Sendable, Identifiable {
    let slug: String
    let score: String

    var id: String { slug }
}

struct EvidencePortfolioScore: Equatable, Sendable, Identifiable {
    let id: Int
    let activityID: Int
    let attemptID: Int
    let formulaVersion: String
    let rubricVersion: String
    let totalScore: String
    let components: [EvidencePortfolioComponent]
    let trendBasis: [String: ActivityJSONValue]
    let scoredAt: Date
}

struct EvidencePortfolioPage: Equatable, Sendable {
    let items: [EvidencePortfolioScore]
    let nextCursor: Int?
}

enum EvidenceLoadState: Equatable {
    case idle
    case loading
    case content
    case empty
    case failed
}

@MainActor
protocol EvidenceServicing: AnyObject {
    func listSkills() async throws -> [EvidenceSkill]
    func fetchSkill(slug: String) async throws -> EvidenceSkill
    func fetchSkillEvidence(slug: String, cursor: Int?) async throws -> EvidenceEventPage
    func fetchActivityEvidence(activityID: Int, cursor: Int?) async throws -> EvidenceEventPage
    func fetchPortfolioHistory(cursor: Int?) async throws -> EvidencePortfolioPage
}

#if DEBUG
/// Strict parser shared by the synthetic UI-test transport and unit tests.
enum NativeEvidenceFixtureQuery {
    enum ValidationError: Error { case invalid }

    static func cursor(from url: URL, paginated: Bool) throws -> Int? {
        guard let components = URLComponents(url: url, resolvingAgainstBaseURL: false) else {
            throw ValidationError.invalid
        }
        let query = components.queryItems ?? []
        guard Set(query.map(\.name)).count == query.count else { throw ValidationError.invalid }
        guard paginated else {
            guard query.isEmpty else { throw ValidationError.invalid }
            return nil
        }
        guard query.allSatisfy({ ["cursor", "limit"].contains($0.name) }),
              query.first(where: { $0.name == "limit" })?.value == "20"
        else { throw ValidationError.invalid }
        guard let item = query.first(where: { $0.name == "cursor" }) else { return nil }
        guard let raw = item.value, !raw.isEmpty, let value = Int(raw), value > 0 else {
            throw ValidationError.invalid
        }
        return value
    }
}
#endif
