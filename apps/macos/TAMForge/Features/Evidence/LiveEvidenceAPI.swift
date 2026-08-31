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
        try EvidenceDecimal.validate(
            [value.baseline, value.monthOneTarget, value.finalTarget],
            within: Decimal(0) ... Decimal(4)
        )
        guard LiveEvidenceAPI.isValidSlug(value.slug), !value.name.isEmpty else {
            throw EvidenceAdapterError.invalidSchemaValue
        }
        self.init(
            slug: value.slug,
            name: value.name,
            baseline: value.baseline,
            monthOneTarget: value.monthOneTarget,
            finalTarget: value.finalTarget,
            snapshot: try value.latestSnapshot.map { try .init(api: $0.value1) }
        )
    }
}

private extension EvidenceSnapshot {
    init(api value: Components.Schemas.SkillSnapshotResponse) throws {
        try EvidenceDecimal.validate([value.estimatedLevel], within: Decimal(0) ... Decimal(4))
        try EvidenceDecimal.validate([
            value.baselineTargetGap, value.monthOneTargetGap,
            value.finalTargetGap, value.totalEffectiveWeight,
        ])
        let manifest = try value.manifest.map(EvidenceManifestEntry.init(api:))
        guard value.id > 0, value.qualifyingEventCount >= 0, value.exerciseTypeCount >= 0,
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
        try EvidenceDecimal.validate([value.effectiveWeight])
        guard value.eventId > 0 else { throw EvidenceAdapterError.invalidSchemaValue }
        self.init(eventID: value.eventId, usedWeight: value.effectiveWeight, inclusionCode: value.inclusionCode.rawValue)
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
        try EvidenceDecimal.validate([value.skillImpact, value.effectiveWeight])
        guard value.id > 0, value.activityId > 0, value.attemptId.map({ $0 > 0 }) ?? true,
              LiveEvidenceAPI.isValidSlug(value.skillSlug)
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
        try EvidenceDecimal.validate(
            [value.totalScore] + value.components.map(\.score),
            within: Decimal(0) ... Decimal(20)
        )
        guard value.id > 0, value.activityId > 0, value.attemptId > 0,
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
    private static let pattern = try! NSRegularExpression(
        pattern: "^[+-]?(?:[0-9]+(?:\\.[0-9]*)?|\\.[0-9]+)$"
    )

    static func validate(_ values: [String], within range: ClosedRange<Decimal>? = nil) throws {
        guard values.allSatisfy({ value in
            let full = NSRange(value.startIndex..<value.endIndex, in: value)
            guard pattern.firstMatch(in: value, range: full)?.range == full else { return false }
            guard let range else { return true }
            guard let number = Decimal(string: value, locale: Locale(identifier: "en_US_POSIX")) else { return false }
            return range.contains(number)
        }) else { throw EvidenceAdapterError.invalidSchemaValue }
    }
}

private enum EvidencePortfolioContract {
    static let componentSlugs: Set<String> = [
        "impact_risk_assessment",
        "explicit_prioritization",
        "delegation_ownership",
        "communication_control",
        "proactive_work_protection",
        "evidence_based_reprioritization",
        "english_clarity",
    ]
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
