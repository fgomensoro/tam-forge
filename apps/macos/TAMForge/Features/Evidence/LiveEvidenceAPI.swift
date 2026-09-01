import Foundation
import HTTPTypes
import OpenAPIRuntime

@MainActor
final class LiveEvidenceAPI: EvidenceServicing {
    private static let pageLimit = 20
    private let transport: NativeAPITransport

    init(transport: NativeAPITransport) {
        self.transport = transport
    }

    func listSkills() async throws -> [EvidenceSkill] {
        try await send(
            path: "/api/v1/skills",
            as: Components.Schemas.SkillListResponse.self,
            requiredNulls: .skillList,
            map: {
                let skills = try $0.items.map(EvidenceSkill.init(api:))
                guard Set(skills.map(\.slug)).count == skills.count else {
                    throw EvidenceAdapterError.invalidSchemaValue
                }
                return skills
            }
        )
    }

    func fetchSkill(slug: String) async throws -> EvidenceSkill {
        try await send(
            path: try skillPath(slug),
            as: Components.Schemas.SkillSummaryResponse.self,
            requiredNulls: .skillSummary,
            map: {
                let skill = try EvidenceSkill(api: $0)
                guard skill.slug == slug else { throw EvidenceAdapterError.invalidSchemaValue }
                return skill
            }
        )
    }

    func fetchSkillEvidence(slug: String, cursor: Int?) async throws -> EvidenceEventPage {
        try await send(
            path: try evidencePath(prefix: "\(skillPath(slug))/evidence", cursor: cursor),
            as: Components.Schemas.EvidenceEventPage.self,
            requiredNulls: .eventPage,
            map: {
                let page = try EvidenceEventPage(api: $0)
                try EvidencePageValidator.events(page, scope: .skill(slug), requestedCursor: cursor)
                return page
            }
        )
    }

    func fetchActivityEvidence(activityID: Int, cursor: Int?) async throws -> EvidenceEventPage {
        guard activityID > 0 else { throw EvidenceAPIError.invalidRequest }
        return try await send(
            path: try evidencePath(prefix: "/api/v1/activities/\(activityID)/evidence", cursor: cursor),
            as: Components.Schemas.EvidenceEventPage.self,
            requiredNulls: .eventPage,
            map: {
                let page = try EvidenceEventPage(api: $0)
                try EvidencePageValidator.events(page, scope: .activity(activityID), requestedCursor: cursor)
                return page
            }
        )
    }

    func fetchPortfolioHistory(cursor: Int?) async throws -> EvidencePortfolioPage {
        try await send(
            path: try evidencePath(prefix: "/api/v1/portfolio-judgment", cursor: cursor),
            as: Components.Schemas.PortfolioHistoryResponse.self,
            requiredNulls: .page,
            map: {
                let page = try EvidencePortfolioPage(api: $0)
                try EvidencePageValidator.portfolio(page, requestedCursor: cursor)
                return page
            }
        )
    }

    private func send<Response: Decodable & Sendable, Value>(
        path: String,
        as type: Response.Type,
        requiredNulls: EvidenceRequiredNulls = .none,
        map: (Response) throws -> Value
    ) async throws -> Value {
        do {
            try Task.checkCancellation()
            let response = try await transport.send(.init(method: .get, path: path))
            try requiredNulls.validate(response.body)
            return try map(response.decoded(as: type))
        } catch is CancellationError {
            throw EvidenceAPIError.cancelled
        } catch let error as EvidenceAPIError {
            throw error
        } catch let error as NativeAPIError {
            switch error {
            case let .problem(problem) where problem.status == 401:
                throw EvidenceAPIError.unauthorized
            case .emptyResponse, .decodingResponse, .responseTooLarge:
                throw EvidenceAPIError.invalidResponse
            case .invalidPath, .malformedProblem, .problem:
                throw EvidenceAPIError.unavailable
            }
        } catch let error as URLError where error.code == .cancelled {
            throw EvidenceAPIError.cancelled
        } catch is EvidenceAdapterError {
            throw EvidenceAPIError.invalidResponse
        } catch is EvidenceContractError {
            throw EvidenceAPIError.invalidResponse
        } catch {
            throw EvidenceAPIError.unavailable
        }
    }

    private func skillPath(_ slug: String) throws -> String {
        guard Self.isValidSlug(slug),
              let encoded = slug.addingPercentEncoding(withAllowedCharacters: .alphanumerics.union(.init(charactersIn: "_-")))
        else { throw EvidenceAPIError.invalidRequest }
        return "/api/v1/skills/\(encoded)"
    }

    private func evidencePath(prefix: String, cursor: Int?) throws -> String {
        if let cursor, cursor <= 0 { throw EvidenceAPIError.invalidRequest }
        let cursorQuery = cursor.map { "&cursor=\($0)" } ?? ""
        return "\(prefix)?limit=\(Self.pageLimit)\(cursorQuery)"
    }

    nonisolated fileprivate static func isValidSlug(_ value: String) -> Bool {
        value.range(of: "^[a-z][a-z0-9_]{0,63}$", options: .regularExpression) != nil
    }
}

private enum EvidenceAdapterError: Error { case invalidSchemaValue }

private enum EvidenceRequiredNulls: Equatable {
    case none
    case skillList
    case skillSummary
    case eventPage
    case page

    func validate(_ data: Data?) throws {
        guard self != .none else { return }
        guard let data,
              let root = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
        else { throw EvidenceAdapterError.invalidSchemaValue }

        switch self {
        case .none:
            return
        case .skillList:
            guard let items = root["items"] as? [[String: Any]] else {
                throw EvidenceAdapterError.invalidSchemaValue
            }
            try items.forEach(Self.validateSkill)
        case .skillSummary:
            try Self.validateSkill(root)
        case .eventPage:
            guard root.keys.contains("next_cursor"),
                  let items = root["items"] as? [[String: Any]],
                  items.allSatisfy({ $0.keys.contains("attempt_id") })
            else { throw EvidenceAdapterError.invalidSchemaValue }
        case .page:
            guard root.keys.contains("next_cursor") else {
                throw EvidenceAdapterError.invalidSchemaValue
            }
        }
    }

    private static func validateSkill(_ value: [String: Any]) throws {
        guard value.keys.contains("latest_snapshot") else {
            throw EvidenceAdapterError.invalidSchemaValue
        }
        if let snapshot = value["latest_snapshot"] as? [String: Any],
           !snapshot.keys.contains("last_strong_evidence_date") {
            throw EvidenceAdapterError.invalidSchemaValue
        }
    }
}

private extension EvidenceSkill {
    init(api value: Components.Schemas.SkillSummaryResponse) throws {
        let targets = try [value.baseline, value.monthOneTarget, value.finalTarget].map {
            try EvidenceDecimal.parse($0, within: Decimal(0) ... Decimal(4))
        }
        guard LiveEvidenceAPI.isValidSlug(value.slug), !value.name.isEmpty else {
            throw EvidenceAdapterError.invalidSchemaValue
        }
        self.init(
            slug: value.slug,
            name: value.name,
            baseline: value.baseline,
            monthOneTarget: value.monthOneTarget,
            finalTarget: value.finalTarget,
            snapshot: try value.latestSnapshot.map {
                try .init(
                    api: $0.value1,
                    baseline: targets[0],
                    monthOneTarget: targets[1],
                    finalTarget: targets[2]
                )
            }
        )
    }
}

private extension EvidenceSnapshot {
    init(
        api value: Components.Schemas.SkillSnapshotResponse,
        baseline: Decimal,
        monthOneTarget: Decimal,
        finalTarget: Decimal
    ) throws {
        let estimate = try EvidenceDecimal.parse(value.estimatedLevel, within: Decimal(0) ... Decimal(4))
        let gaps = try [
            value.baselineTargetGap, value.monthOneTargetGap,
            value.finalTargetGap,
        ].map { try EvidenceDecimal.parse($0, within: Decimal(-4) ... Decimal(4)) }
        let totalEffectiveWeight = try EvidenceDecimal.parse(value.totalEffectiveWeight)
        let manifest = try value.manifest.map(EvidenceManifestEntry.init(api:))
        let contributing = manifest.filter { EvidenceSnapshotContract.contributingCodes.contains($0.inclusionCode) }
        let manifestWeight = try contributing.reduce(Decimal.zero) {
            $0 + (try EvidenceDecimal.parse($1.usedWeight))
        }
        guard value.id > 0, value.qualifyingEventCount >= 0, value.exerciseTypeCount >= 0,
              totalEffectiveWeight >= 0,
              gaps == [baseline - estimate, monthOneTarget - estimate, finalTarget - estimate],
              manifestWeight == totalEffectiveWeight,
              contributing.count == value.qualifyingEventCount,
              value.exerciseTypeCount <= value.qualifyingEventCount,
              EvidenceResponseContract.validSnapshotCodes(
                confidence: value.confidence, trend: value.trend, recency: value.recency
              ),
              Set(manifest.map(\.eventID)).count == manifest.count
        else { throw EvidenceAdapterError.invalidSchemaValue }
        self.init(
            id: value.id,
            formulaVersion: value.formulaVersion,
            snapshotDate: try EvidenceDate.only(value.snapshotDate),
            estimatedLevel: value.estimatedLevel,
            confidence: value.confidence,
            trend: value.trend,
            recency: value.recency,
            baselineTargetGap: value.baselineTargetGap,
            monthOneTargetGap: value.monthOneTargetGap,
            finalTargetGap: value.finalTargetGap,
            totalEffectiveWeight: value.totalEffectiveWeight,
            qualifyingEventCount: value.qualifyingEventCount,
            exerciseTypeCount: value.exerciseTypeCount,
            lastStrongEvidenceDate: try value.lastStrongEvidenceDate.map(EvidenceDate.only),
            manifest: manifest,
            confidenceBasis: try .init(openAPIObject: value.confidenceBasis.additionalProperties),
            trendBasis: try .init(openAPIObject: value.trendBasis.additionalProperties)
        )
    }
}

private extension EvidenceManifestEntry {
    init(api value: Components.Schemas.SnapshotManifestItem) throws {
        let weight = try EvidenceDecimal.parse(
            value.effectiveWeight,
            within: Decimal(0) ... EvidenceDecimal.maximumEventWeight
        )
        let code = value.inclusionCode.rawValue
        let validWeight = switch code {
        case "discounted_same_day": weight > 0
        case "excluded_nonqualifying", "excluded_outside_window": weight == 0
        default: true
        }
        guard value.eventId > 0, validWeight else { throw EvidenceAdapterError.invalidSchemaValue }
        self.init(eventID: value.eventId, usedWeight: value.effectiveWeight, inclusionCode: code)
    }
}

private extension EvidenceEventPage {
    init(api value: Components.Schemas.EvidenceEventPage) throws {
        self.init(items: try value.items.map(EvidenceEvent.init(api:)), nextCursor: value.nextCursor)
    }
}

private extension EvidenceEvent {
    init(api value: Components.Schemas.EvidenceEventResponse) throws {
        try EvidenceDecimal.validate([value.performanceScore], within: Decimal(0) ... Decimal(4))
        let skillImpact = try EvidenceDecimal.parse(value.skillImpact, within: Decimal(0) ... Decimal(1))
        try EvidenceDecimal.validate(
            [value.effectiveWeight],
            within: Decimal(0) ... EvidenceDecimal.maximumEventWeight
        )
        guard value.id > 0, value.activityId > 0, value.attemptId.map({ $0 > 0 }) ?? true,
              skillImpact > 0,
              LiveEvidenceAPI.isValidSlug(value.skillSlug),
              EvidenceResponseContract.validQualification(
                reason: value.qualificationReason,
                qualifies: value.qualifyingForLevel,
                attemptID: value.attemptId,
                practiceMode: value.practiceMode,
                assistance: value.assistance
              )
        else { throw EvidenceAdapterError.invalidSchemaValue }
        self.init(
            id: value.id,
            activityID: value.activityId,
            attemptID: value.attemptId,
            skillSlug: value.skillSlug,
            exerciseType: value.exerciseType,
            mappingVersion: value.mappingVersion,
            formulaVersion: value.formulaVersion,
            rubricSlug: value.rubricSlug,
            rubricVersion: value.rubricVersion,
            evaluator: value.evaluator,
            practiceMode: value.practiceMode,
            assistance: value.assistance,
            difficulty: value.difficulty,
            performanceScore: value.performanceScore,
            skillImpact: value.skillImpact,
            effectiveWeight: value.effectiveWeight,
            qualifyingForLevel: value.qualifyingForLevel,
            qualificationReason: value.qualificationReason,
            rawDimensionScores: try .init(openAPIObject: value.rawDimensionScores.additionalProperties),
            occurredAt: value.occurredAt
        )
    }
}

private extension EvidencePortfolioPage {
    init(api value: Components.Schemas.PortfolioHistoryResponse) throws {
        self.init(items: try value.items.map(EvidencePortfolioScore.init(api:)), nextCursor: value.nextCursor)
    }
}

private extension EvidencePortfolioScore {
    init(api value: Components.Schemas.PortfolioScoreResponse) throws {
        _ = try EvidenceDecimal.parse(value.totalScore, within: Decimal(0) ... Decimal(20))
        try value.components.forEach {
            guard let maximum = EvidencePortfolioContract.componentMaximums[$0.slug] else {
                throw EvidenceAdapterError.invalidSchemaValue
            }
            _ = try EvidenceDecimal.parse($0.score, within: Decimal(0) ... maximum)
        }
        guard value.id > 0, value.activityId > 0, value.attemptId > 0,
              value.components.count == EvidencePortfolioContract.componentSlugs.count,
              Set(value.components.map(\.slug)) == EvidencePortfolioContract.componentSlugs
        else { throw EvidenceAdapterError.invalidSchemaValue }
        self.init(
            id: value.id,
            activityID: value.activityId,
            attemptID: value.attemptId,
            formulaVersion: value.formulaVersion,
            rubricVersion: value.rubricVersion,
            totalScore: value.totalScore,
            components: value.components.map { .init(slug: $0.slug, score: $0.score) },
            trendBasis: try .init(openAPIObject: value.trendBasis.additionalProperties),
            scoredAt: value.scoredAt
        )
    }
}

private enum EvidenceDecimal {
    static let maximumEventWeight = Decimal(
        string: "1.5",
        locale: Locale(identifier: "en_US_POSIX")
    )!
    private static let pattern = try! NSRegularExpression(
        pattern: "^[+-]?(?:[0-9]+(?:\\.[0-9]*)?|\\.[0-9]+)$"
    )

    static func validate(_ values: [String], within range: ClosedRange<Decimal>? = nil) throws {
        _ = try values.map { try parse($0, within: range) }
    }

    static func parse(_ value: String, within range: ClosedRange<Decimal>? = nil) throws -> Decimal {
        let full = NSRange(value.startIndex..<value.endIndex, in: value)
        guard pattern.firstMatch(in: value, range: full)?.range == full,
              let number = Decimal(string: value, locale: Locale(identifier: "en_US_POSIX")),
              range.map({ $0.contains(number) }) ?? true
        else { throw EvidenceAdapterError.invalidSchemaValue }
        return number
    }
}

private enum EvidencePortfolioContract {
    static let componentMaximums: [String: Decimal] = [
        "impact_risk_assessment": 4,
        "explicit_prioritization": 3,
        "delegation_ownership": 3,
        "communication_control": 3,
        "proactive_work_protection": 2,
        "evidence_based_reprioritization": 3,
        "english_clarity": 2,
    ]
    static let componentSlugs = Set(componentMaximums.keys)
}

private enum EvidenceSnapshotContract {
    static let contributingCodes: Set<String> = ["included", "discounted_same_day"]
}

enum EvidenceResponseContract {
    private static let confidence: Set<String> = ["low", "medium", "high"]
    private static let trend: Set<String> = ["improving", "stable", "declining", "insufficient_evidence"]
    private static let recency: Set<String> = ["fresh", "aging", "stale", "no_qualifying_evidence"]
    private static let qualificationReasons: Set<String> = [
        "qualifies", "nonqualifying_mode", "assisted_during_attempt", "attempt_b",
        "missing_committed_attempt", "mapping_condition_not_met", "excluded_by_formula",
    ]
    private static let qualifyingModes: Set<String> = [
        "independent_practice", "timed_assessment", "mock_interview", "real_interview",
    ]
    private static let evidenceModes: Set<String> = qualifyingModes.union([
        "exposure_only", "guided_practice", "pipeline_only",
    ])
    private static let qualifyingAssistance: Set<String> = ["no_ai", "ai_after_committed_attempt"]
    private static let assistanceCodes: Set<String> = qualifyingAssistance.union([
        "ai_hints_during_attempt", "ai_co_created", "ai_generated",
    ])

    static func validSnapshotCodes(confidence: String, trend: String, recency: String) -> Bool {
        Self.confidence.contains(confidence) && Self.trend.contains(trend) && Self.recency.contains(recency)
    }

    static func validQualification(
        reason: String,
        qualifies: Bool,
        attemptID: Int?,
        practiceMode: String,
        assistance: String
    ) -> Bool {
        guard qualificationReasons.contains(reason),
              evidenceModes.contains(practiceMode),
              assistanceCodes.contains(assistance),
              qualifies == (reason == "qualifies")
        else {
            return false
        }
        if attemptID == nil { return reason == "missing_committed_attempt" }
        if reason == "missing_committed_attempt" { return false }
        if reason == "attempt_b" { return true }
        if !qualifyingModes.contains(practiceMode) { return reason == "nonqualifying_mode" }
        if reason == "nonqualifying_mode" { return false }
        if !qualifyingAssistance.contains(assistance) {
            return reason == "assisted_during_attempt"
        }
        return reason != "assisted_during_attempt"
    }
}

private enum EvidenceDate {
    static func only(_ value: String) throws -> String {
        let parts = value.split(separator: "-", omittingEmptySubsequences: false)
        guard parts.count == 3, parts[0].count == 4, parts[1].count == 2, parts[2].count == 2,
              let year = Int(parts[0]), let month = Int(parts[1]), let day = Int(parts[2])
        else { throw EvidenceAdapterError.invalidSchemaValue }
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(secondsFromGMT: 0)!
        let components = DateComponents(calendar: calendar, timeZone: calendar.timeZone, year: year, month: month, day: day)
        guard let date = calendar.date(from: components),
              calendar.dateComponents([.year, .month, .day], from: date) == DateComponents(year: year, month: month, day: day)
        else {
            throw EvidenceAdapterError.invalidSchemaValue
        }
        return value
    }
}

private extension Dictionary where Key == String, Value == ActivityJSONValue {
    init(openAPIObject value: OpenAPIObjectContainer) throws {
        var mapped: Self = [:]
        for (key, child) in value.value { mapped[key] = try .init(openAPIValue: child) }
        self = mapped
    }
}

private extension ActivityJSONValue {
    init(openAPIValue value: (any Sendable)?) throws {
        switch value {
        case nil, is NSNull:
            self = .null
        case let value as Bool:
            self = .boolean(value)
        case let value as Int:
            self = .integer(value)
        case let value as Double:
            self = .decimal(value)
        case let value as String:
            self = .string(value)
        case let values as [(any Sendable)?]:
            self = .array(try values.map { try .init(openAPIValue: $0) })
        case let values as [String: (any Sendable)?]:
            var mapped: [String: Self] = [:]
            for (key, child) in values { mapped[key] = try .init(openAPIValue: child) }
            self = .object(mapped)
        default:
            throw EvidenceAdapterError.invalidSchemaValue
        }
    }
}
