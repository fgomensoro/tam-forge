import Foundation
import XCTest

@MainActor
final class EvidenceLedgerTests: XCTestCase {
    func testOpenKeepsPortfolioWhenSkillLoadFails() async {
        let service = EvidenceServiceStub(
            skillsResult: .failure(EvidenceAPIError.unavailable),
            portfolioResult: .success(portfolioPage())
        )
        let model = EvidenceLedgerModel(service: service)

        await model.open(activityID: nil)

        XCTAssertEqual(model.skillState, .failed)
        XCTAssertEqual(model.portfolioState, .content)
        XCTAssertEqual(model.portfolioPage?.items.map(\.id), [91])
        XCTAssertTrue(model.canRetrySkills)
        XCTAssertFalse(model.canRetryPortfolio)
    }

    func testOpenKeepsSkillsWhenPortfolioLoadFailsAndRetriesOnlyPortfolio() async {
        let service = EvidenceServiceStub(
            skillsResult: .success([assessedSkill()]),
            portfolioResult: .failure(EvidenceAPIError.unavailable)
        )
        let model = EvidenceLedgerModel(service: service)

        await model.open(activityID: nil)

        XCTAssertEqual(model.skillState, .content)
        XCTAssertEqual(model.skills.map(\.slug), ["incident_communication"])
        XCTAssertEqual(model.portfolioState, .failed)
        XCTAssertTrue(model.canRetryPortfolio)

        service.portfolioResult = .success(portfolioPage())
        await model.retryPortfolio()

        XCTAssertEqual(model.skillState, .content)
        XCTAssertEqual(model.portfolioState, .content)
        XCTAssertEqual(model.portfolioPage?.items.map(\.id), [91])
    }

    func testOpenShowsUnassessedAndScopedEmptyActivityWithoutInventingZero() async {
        let service = EvidenceServiceStub(
            skillsResult: .success([unassessedSkill()]),
            portfolioResult: .success(.init(items: [], nextCursor: nil)),
            activityPageResult: .success(.init(items: [], nextCursor: nil))
        )
        let model = EvidenceLedgerModel(service: service)

        await model.open(activityID: 41)

        XCTAssertEqual(model.skills.first?.snapshot, nil)
        XCTAssertEqual(model.portfolioState, .empty)
        XCTAssertEqual(model.activityState, .empty)
        XCTAssertEqual(model.activeActivityID, 41)
        XCTAssertNil(model.activityPage?.nextCursor)
    }

    func testSkillOlderReplacesPageAndFailedRetryKeepsCursor() async {
        let service = EvidenceServiceStub(
            skillsResult: .success([assessedSkill()]),
            portfolioResult: .success(.init(items: [], nextCursor: nil)),
            skillPageResults: [
                .success(.init(items: [
                    event(id: 50, skill: "incident_communication"),
                    event(id: 40, skill: "incident_communication"),
                ], nextCursor: 40)),
                .failure(EvidenceAPIError.unavailable),
                .success(.init(items: [event(id: 39, skill: "incident_communication")], nextCursor: nil)),
            ]
        )
        let model = EvidenceLedgerModel(service: service)

        await model.open(activityID: nil)
        await model.inspectSkill(slug: "incident_communication")
        await model.loadOlderSkillEvidence()

        XCTAssertEqual(model.skillPage?.items.map(\.id), [50, 40])
        XCTAssertEqual(model.skillPage?.nextCursor, 40)
        XCTAssertEqual(model.skillInspectorState, .failed)
        XCTAssertTrue(model.canRetrySkillInspector)

        await model.retrySkillEvidence()

        XCTAssertEqual(model.skillPage?.items.map(\.id), [39])
        XCTAssertNil(model.skillPage?.nextCursor)
        XCTAssertEqual(service.skillEvidenceRequests.map(\.cursor), [nil, 40, 40])
    }

    func testRejectsWrongScopeDuplicateIDsAndNonprogressingCursorWithoutReplacingVisiblePage() async {
        let service = EvidenceServiceStub(
            skillsResult: .success([assessedSkill()]),
            portfolioResult: .success(.init(items: [], nextCursor: nil)),
            skillPageResults: [
                .success(.init(items: [
                    event(id: 50, skill: "incident_communication"),
                    event(id: 40, skill: "incident_communication"),
                ], nextCursor: 40)),
                .success(.init(items: [event(id: 39, skill: "other"), event(id: 39, skill: "other")], nextCursor: 40)),
            ]
        )
        let model = EvidenceLedgerModel(service: service)

        await model.open(activityID: nil)
        await model.inspectSkill(slug: "incident_communication")
        await model.loadOlderSkillEvidence()

        XCTAssertEqual(model.skillPage?.items.map(\.id), [50, 40])
        XCTAssertEqual(model.skillPage?.nextCursor, 40)
        XCTAssertEqual(model.skillInspectorState, .failed)
        XCTAssertTrue(model.skillInspectorError?.contains("could not be used") == true)
    }

    func testResetDiscardsCancellationResistantLateOpenCompletion() async {
        let skills = DeferredValues<[EvidenceSkill]>()
        let portfolio = DeferredValues<EvidencePortfolioPage>()
        let service = DeferredEvidenceService(skills: skills, portfolio: portfolio)
        let model = EvidenceLedgerModel(service: service)

        let open = Task { await model.open(activityID: nil) }
        await skills.waitForCall(count: 1)
        model.reset()
        await skills.resolve([assessedSkill()])
        await portfolio.waitForCall(count: 1)
        await portfolio.resolve(portfolioPage())
        await open.value

        XCTAssertTrue(model.skills.isEmpty)
        XCTAssertNil(model.portfolioPage)
        XCTAssertEqual(model.skillState, .idle)
        XCTAssertEqual(model.portfolioState, .idle)
    }

    func testStaleMarkDoesNotFetchAndRefreshReplacesVisibleSections() async {
        let service = EvidenceServiceStub(
            skillsResult: .success([assessedSkill()]),
            portfolioResult: .success(portfolioPage())
        )
        let model = EvidenceLedgerModel(service: service)

        await model.open(activityID: nil)
        let callsBeforeStale = service.listSkillsCallCount
        model.markStale()

        XCTAssertTrue(model.isStale)
        XCTAssertEqual(service.listSkillsCallCount, callsBeforeStale)

        await model.refresh()

        XCTAssertFalse(model.isStale)
        XCTAssertEqual(service.listSkillsCallCount, callsBeforeStale + 1)
    }

    func testNewDestinationDiscardsCancellationResistantRefreshCompletion() async {
        let skills = DeferredValues<[EvidenceSkill]>()
        let portfolio = DeferredValues<EvidencePortfolioPage>()
        let service = DeferredEvidenceService(skills: skills, portfolio: portfolio)
        let model = EvidenceLedgerModel(service: service)

        let refresh = Task { await model.refresh() }
        await skills.waitForCall(count: 1)
        let destination = Task { await model.open(activityID: 42) }
        await skills.resolve([assessedSkill()])
        await portfolio.waitForCall(count: 1)
        await portfolio.resolve(portfolioPage())
        await skills.waitForCall(count: 2)
        await skills.resolve([unassessedSkill()])
        await portfolio.waitForCall(count: 2)
        await portfolio.resolve(.init(items: [], nextCursor: nil))
        await destination.value
        await refresh.value

        XCTAssertEqual(model.activeActivityID, 42)
        XCTAssertEqual(model.skills.map(\.slug), ["incident_communication"])
        XCTAssertEqual(model.skills.first?.snapshot, nil)
        XCTAssertEqual(model.portfolioState, .empty)
    }

    func testRapidSkillAndActivityInspectorSwitchesKeepOnlyLatestScope() async {
        let skillA = DeferredValues<EvidenceEventPage>()
        let skillB = DeferredValues<EvidenceEventPage>()
        let activity41 = DeferredValues<EvidenceEventPage>()
        let activity42 = DeferredValues<EvidenceEventPage>()
        let service = DeferredEvidenceService(
            skills: DeferredValues(values: [[assessedSkill()]]),
            portfolio: DeferredValues(values: [.init(items: [], nextCursor: nil)]),
            skillPages: ["incident_communication": skillA, "technical_depth": skillB],
            activityPages: [41: activity41, 42: activity42]
        )
        let model = EvidenceLedgerModel(service: service)

        let firstSkill = Task { await model.inspectSkill(slug: "incident_communication") }
        await skillA.waitForCall(count: 1)
        let secondSkill = Task { await model.inspectSkill(slug: "technical_depth") }
        await skillB.waitForCall(count: 1)
        await skillB.resolve(.init(items: [event(id: 62, skill: "technical_depth")], nextCursor: nil))
        await skillA.resolve(.init(items: [event(id: 51, skill: "incident_communication")], nextCursor: nil))
        await secondSkill.value
        await firstSkill.value

        let firstActivity = Task { await model.inspectActivity(activityID: 41) }
        await activity41.waitForCall(count: 1)
        let secondActivity = Task { await model.inspectActivity(activityID: 42) }
        await activity42.waitForCall(count: 1)
        await activity42.resolve(.init(items: [event(id: 63, skill: "technical_depth", activityID: 42)], nextCursor: nil))
        await activity41.resolve(.init(items: [event(id: 52, skill: "incident_communication")], nextCursor: nil))
        await secondActivity.value
        await firstActivity.value

        XCTAssertEqual(model.selectedSkillSlug, "technical_depth")
        XCTAssertEqual(model.skillPage?.items.map(\.id), [62])
        XCTAssertEqual(model.inspectedActivityID, 42)
        XCTAssertEqual(model.activityPage?.items.map(\.id), [63])
    }

    private func unassessedSkill() -> EvidenceSkill {
        .init(slug: "incident_communication", name: "Incident communication", baseline: "1", monthOneTarget: "2", finalTarget: "4", snapshot: nil)
    }

    private func assessedSkill() -> EvidenceSkill {
        .init(
            slug: "incident_communication", name: "Incident communication", baseline: "1", monthOneTarget: "2", finalTarget: "4",
            snapshot: .init(
                id: 71, formulaVersion: "formula-v1", snapshotDate: "2026-08-31", estimatedLevel: "3.125",
                confidence: "moderate", trend: "improving", recency: "recent", baselineTargetGap: "2.125",
                monthOneTargetGap: "1.125", finalTargetGap: "0.875", totalEffectiveWeight: "1.250",
                qualifyingEventCount: 2, exerciseTypeCount: 1, lastStrongEvidenceDate: nil,
                manifest: [.init(eventID: 50, usedWeight: "0.125", inclusionCode: "included")],
                confidenceBasis: [:], trendBasis: [:]
            )
        )
    }

    private func event(id: Int, skill: String, activityID: Int = 41) -> EvidenceEvent {
        .init(
            id: id, activityID: activityID, attemptID: nil, skillSlug: skill, exerciseType: "tam_case",
            mappingVersion: "mapping-v1", formulaVersion: "formula-v1", rubricSlug: "incident_rubric",
            rubricVersion: "rubric-v1", evaluator: "human_coach", practiceMode: "independent_practice",
            assistance: "no_ai", difficulty: "standard", performanceScore: "3.750", skillImpact: "0.500",
            effectiveWeight: "0.875", qualifyingForLevel: true, qualificationReason: "Independent evidence",
            rawDimensionScores: [:], occurredAt: Date(timeIntervalSince1970: 1_788_080_000)
        )
    }

    private func portfolioPage() -> EvidencePortfolioPage {
        .init(items: [.init(
            id: 91, activityID: 41, attemptID: 81, formulaVersion: "portfolio-v1", rubricVersion: "rubric-v1",
            totalScore: "16.500", components: [.init(slug: "impact", score: "2.250")], trendBasis: [:],
            scoredAt: Date(timeIntervalSince1970: 1_788_080_000)
        )], nextCursor: nil)
    }
}

private actor DeferredValues<Value: Sendable> {
    private var values: [Value]
    private var waiters: [CheckedContinuation<Value, Never>] = []
    private var callCount = 0
    private var callWaiters: [(Int, CheckedContinuation<Void, Never>)] = []

    init(values: [Value] = []) {
        self.values = values
    }

    func next() async -> Value {
        callCount += 1
        releaseCallWaiters()
        if !values.isEmpty { return values.removeFirst() }
        return await withCheckedContinuation { waiters.append($0) }
    }

    func waitForCall(count: Int) async {
        guard callCount < count else { return }
        await withCheckedContinuation { callWaiters.append((count, $0)) }
    }

    func resolve(_ value: Value) {
        if waiters.isEmpty {
            values.append(value)
        } else {
            waiters.removeFirst().resume(returning: value)
        }
    }

    private func releaseCallWaiters() {
        let ready = callWaiters.filter { $0.0 <= callCount }
        callWaiters.removeAll { $0.0 <= callCount }
        ready.forEach { $0.1.resume() }
    }
}

@MainActor
private final class DeferredEvidenceService: EvidenceServicing {
    let skills: DeferredValues<[EvidenceSkill]>
    let portfolio: DeferredValues<EvidencePortfolioPage>
    let skillPages: [String: DeferredValues<EvidenceEventPage>]
    let activityPages: [Int: DeferredValues<EvidenceEventPage>]

    init(
        skills: DeferredValues<[EvidenceSkill]>,
        portfolio: DeferredValues<EvidencePortfolioPage>,
        skillPages: [String: DeferredValues<EvidenceEventPage>] = [:],
        activityPages: [Int: DeferredValues<EvidenceEventPage>] = [:]
    ) {
        self.skills = skills
        self.portfolio = portfolio
        self.skillPages = skillPages
        self.activityPages = activityPages
    }

    func listSkills() async throws -> [EvidenceSkill] { await skills.next() }
    func fetchSkill(slug: String) async throws -> EvidenceSkill {
        guard let skill = try await listSkills().first else { throw EvidenceAPIError.invalidResponse }
        return skill
    }
    func fetchSkillEvidence(slug: String, cursor: Int?) async throws -> EvidenceEventPage {
        guard let page = skillPages[slug] else { throw EvidenceAPIError.unavailable }
        return await page.next()
    }
    func fetchActivityEvidence(activityID: Int, cursor: Int?) async throws -> EvidenceEventPage {
        guard let page = activityPages[activityID] else { throw EvidenceAPIError.unavailable }
        return await page.next()
    }
    func fetchPortfolioHistory(cursor: Int?) async throws -> EvidencePortfolioPage { await portfolio.next() }
}

@MainActor
private final class EvidenceServiceStub: EvidenceServicing {
    struct EvidenceRequest: Equatable {
        let slug: String
        let cursor: Int?
    }

    var skillsResult: Result<[EvidenceSkill], EvidenceAPIError>
    var portfolioResult: Result<EvidencePortfolioPage, EvidenceAPIError>
    var activityPageResult: Result<EvidenceEventPage, EvidenceAPIError>
    var skillPageResults: [Result<EvidenceEventPage, EvidenceAPIError>]
    private(set) var listSkillsCallCount = 0
    private(set) var skillEvidenceRequests: [EvidenceRequest] = []

    init(
        skillsResult: Result<[EvidenceSkill], EvidenceAPIError>,
        portfolioResult: Result<EvidencePortfolioPage, EvidenceAPIError>,
        activityPageResult: Result<EvidenceEventPage, EvidenceAPIError> = .success(.init(items: [], nextCursor: nil)),
        skillPageResults: [Result<EvidenceEventPage, EvidenceAPIError>] = []
    ) {
        self.skillsResult = skillsResult
        self.portfolioResult = portfolioResult
        self.activityPageResult = activityPageResult
        self.skillPageResults = skillPageResults
    }

    func listSkills() async throws -> [EvidenceSkill] {
        listSkillsCallCount += 1
        return try skillsResult.get()
    }

    func fetchSkill(slug: String) async throws -> EvidenceSkill {
        guard let skill = try skillsResult.get().first else { throw EvidenceAPIError.invalidResponse }
        return skill
    }

    func fetchSkillEvidence(slug: String, cursor: Int?) async throws -> EvidenceEventPage {
        skillEvidenceRequests.append(.init(slug: slug, cursor: cursor))
        guard !skillPageResults.isEmpty else { throw EvidenceAPIError.unavailable }
        return try skillPageResults.removeFirst().get()
    }

    func fetchActivityEvidence(activityID: Int, cursor: Int?) async throws -> EvidenceEventPage {
        try activityPageResult.get()
    }

    func fetchPortfolioHistory(cursor: Int?) async throws -> EvidencePortfolioPage {
        try portfolioResult.get()
    }
}
