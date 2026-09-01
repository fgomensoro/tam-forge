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
        defer { open.cancel() }
        await assertCall(skills, count: 1)
        model.reset()
        await skills.resolve([assessedSkill()])
        await assertCall(portfolio, count: 1)
        await portfolio.resolve(portfolioPage())
        await open.value

        XCTAssertTrue(model.skills.isEmpty)
        XCTAssertNil(model.portfolioPage)
        XCTAssertEqual(model.skillState, .idle)
        XCTAssertEqual(model.portfolioState, .idle)
    }

    func testCallerCancellationSettlesOpenSectionsAfterCancellationResistantSuccess() async {
        let skills = DeferredValues<Result<[EvidenceSkill], EvidenceAPIError>>()
        let portfolio = DeferredValues<Result<EvidencePortfolioPage, EvidenceAPIError>>()
        let activity = DeferredValues<Result<EvidenceEventPage, EvidenceAPIError>>()
        let service = DeferredResultEvidenceService(
            skills: skills,
            portfolio: portfolio,
            activityPages: [41: activity]
        )
        let model = EvidenceLedgerModel(service: service)

        let open = Task { await model.open(activityID: 41) }
        await assertCall(skills, count: 1)
        await assertCall(portfolio, count: 1)
        await assertCall(activity, count: 1)
        open.cancel()
        await skills.resolve(.success([assessedSkill()]))
        await portfolio.resolve(.success(portfolioPage()))
        await activity.resolve(.success(.init(
            items: [event(id: 50, skill: "incident_communication")],
            nextCursor: nil
        )))
        await open.value

        XCTAssertTrue(model.skills.isEmpty)
        XCTAssertNil(model.portfolioPage)
        XCTAssertNil(model.activityPage)
        XCTAssertEqual(model.skillState, .idle)
        XCTAssertEqual(model.portfolioState, .idle)
        XCTAssertEqual(model.activityState, .idle)
    }

    func testCallerCancellationDoesNotPublishCancellationResistantErrors() async {
        let skills = DeferredValues<Result<[EvidenceSkill], EvidenceAPIError>>()
        let portfolio = DeferredValues<Result<EvidencePortfolioPage, EvidenceAPIError>>()
        let activity = DeferredValues<Result<EvidenceEventPage, EvidenceAPIError>>()
        let skill = DeferredValues<Result<EvidenceEventPage, EvidenceAPIError>>()
        let service = DeferredResultEvidenceService(
            skills: skills,
            portfolio: portfolio,
            skillPages: ["incident_communication": skill],
            activityPages: [41: activity]
        )
        let model = EvidenceLedgerModel(service: service)

        let open = Task { await model.open(activityID: 41) }
        await assertCall(skills, count: 1)
        await assertCall(portfolio, count: 1)
        await assertCall(activity, count: 1)
        open.cancel()
        await skills.resolve(.failure(.unavailable))
        await portfolio.resolve(.failure(.unavailable))
        await activity.resolve(.failure(.unavailable))
        await open.value

        let inspect = Task { await model.inspectSkill(slug: "incident_communication") }
        await assertCall(skill, count: 1)
        inspect.cancel()
        await skill.resolve(.failure(.unavailable))
        await inspect.value

        XCTAssertEqual(model.skillState, .idle)
        XCTAssertEqual(model.portfolioState, .idle)
        XCTAssertEqual(model.activityState, .idle)
        XCTAssertEqual(model.skillInspectorState, .idle)
        XCTAssertNil(model.skillError)
        XCTAssertNil(model.portfolioError)
        XCTAssertNil(model.activityInspectorError)
        XCTAssertNil(model.skillInspectorError)
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

    func testRefreshDoesNotCombineRetainedSnapshotWithNewEventsWhenSkillsFail() async {
        let service = EvidenceServiceStub(
            skillsResult: .success([assessedSkill()]),
            portfolioResult: .success(portfolioPage()),
            skillPageResults: [
                .success(.init(items: [event(id: 50, skill: "incident_communication")], nextCursor: nil)),
            ]
        )
        let model = EvidenceLedgerModel(service: service)

        await model.open(activityID: nil)
        await model.inspectSkill(slug: "incident_communication")
        service.skillsResult = .failure(.unavailable)
        await model.refresh()

        XCTAssertEqual(model.skillState, .failed)
        XCTAssertEqual(service.skillEvidenceRequests.count, 1)
        XCTAssertNil(model.skillPage)
        XCTAssertEqual(model.skillInspectorState, .idle)
    }

    func testSuccessfulSkillsRetryReloadsInspectorClearedByFailedRefresh() async {
        let service = EvidenceServiceStub(
            skillsResult: .success([assessedSkill()]),
            portfolioResult: .success(portfolioPage()),
            skillPageResults: [
                .success(.init(items: [event(id: 50, skill: "incident_communication")], nextCursor: nil)),
                .success(.init(items: [event(id: 49, skill: "incident_communication")], nextCursor: nil)),
            ]
        )
        let model = EvidenceLedgerModel(service: service)

        await model.open(activityID: nil)
        await model.inspectSkill(slug: "incident_communication")
        service.skillsResult = .failure(.unavailable)
        await model.refresh()

        service.skillsResult = .success([assessedSkill(name: "Recovered skill")])
        await model.retrySkills()

        XCTAssertEqual(model.skillState, .content)
        XCTAssertEqual(model.selectedSkillSlug, "incident_communication")
        XCTAssertEqual(model.selectedSkill?.name, "Recovered skill")
        XCTAssertEqual(model.skillInspectorState, .content)
        XCTAssertEqual(model.skillPage?.items.map(\.id), [49])
        XCTAssertEqual(service.skillEvidenceRequests.map(\.cursor), [nil, nil])
    }

    func testSuccessfulSkillsRetryReloadsInspectorReopenedAfterFailedRefresh() async {
        let service = EvidenceServiceStub(
            skillsResult: .success([assessedSkill()]),
            portfolioResult: .success(portfolioPage()),
            skillPageResults: [
                .success(.init(items: [event(id: 50, skill: "incident_communication")], nextCursor: nil)),
                .success(.init(items: [event(id: 49, skill: "incident_communication")], nextCursor: nil)),
                .success(.init(items: [event(id: 48, skill: "incident_communication")], nextCursor: nil)),
            ]
        )
        let model = EvidenceLedgerModel(service: service)

        await model.open(activityID: nil)
        await model.inspectSkill(slug: "incident_communication")
        service.skillsResult = .failure(.unavailable)
        await model.refresh()
        await model.inspectSkill(slug: "incident_communication")

        service.skillsResult = .success([assessedSkill(name: "Recovered skill")])
        await model.retrySkills()

        XCTAssertEqual(model.selectedSkill?.name, "Recovered skill")
        XCTAssertEqual(model.skillInspectorState, .content)
        XCTAssertEqual(model.skillPage?.items.map(\.id), [48])
        XCTAssertEqual(service.skillEvidenceRequests.map(\.cursor), [nil, nil, nil])
    }

    func testRefreshCannotCancelANewerSkillSelection() async {
        let skills = DeferredValues(values: [[
            assessedSkill(),
            assessedSkill(name: "Technical depth", slug: "technical_depth"),
        ]])
        let portfolio = DeferredValues(values: [
            EvidencePortfolioPage(items: [], nextCursor: nil),
            EvidencePortfolioPage(items: [], nextCursor: nil),
        ])
        let firstSkill = DeferredValues(values: [
            EvidenceEventPage(items: [event(id: 50, skill: "incident_communication")], nextCursor: nil),
        ])
        let newerSkill = DeferredValues<EvidenceEventPage>()
        let service = DeferredEvidenceService(
            skills: skills,
            portfolio: portfolio,
            skillPages: [
                "incident_communication": firstSkill,
                "technical_depth": newerSkill,
            ]
        )
        let model = EvidenceLedgerModel(service: service)
        await model.open(activityID: nil)
        await model.inspectSkill(slug: "incident_communication")

        let refresh = Task { await model.refresh() }
        defer { refresh.cancel() }
        await assertCall(skills, count: 2)
        let selection = Task { await model.inspectSkill(slug: "technical_depth") }
        defer { selection.cancel() }
        await assertCall(newerSkill, count: 1)
        await firstSkill.resolve(.init(items: [event(id: 48, skill: "incident_communication")], nextCursor: nil))
        await skills.resolve([
            assessedSkill(),
            assessedSkill(name: "Technical depth", slug: "technical_depth"),
        ], call: 2)
        await refresh.value
        await newerSkill.resolve(.init(items: [event(id: 49, skill: "technical_depth")], nextCursor: nil))
        await selection.value

        let staleReloadCount = await firstSkill.currentCallCount()
        XCTAssertEqual(staleReloadCount, 1)
        XCTAssertEqual(model.selectedSkillSlug, "technical_depth")
        XCTAssertEqual(model.skillPage?.items.map(\.id), [49])
        XCTAssertEqual(model.skillInspectorState, .content)
    }

    func testNewDestinationDiscardsCancellationResistantRefreshCompletion() async {
        let skills = DeferredValues<[EvidenceSkill]>()
        let portfolio = DeferredValues<EvidencePortfolioPage>()
        let service = DeferredEvidenceService(skills: skills, portfolio: portfolio)
        let model = EvidenceLedgerModel(service: service)

        let refresh = Task { await model.refresh() }
        defer { refresh.cancel() }
        await assertCall(skills, count: 1)
        let destination = Task { await model.open(activityID: 42) }
        defer { destination.cancel() }
        await skills.resolve([assessedSkill()])
        await assertCall(portfolio, count: 1)
        await portfolio.resolve(portfolioPage())
        await assertCall(skills, count: 2)
        await skills.resolve([unassessedSkill()])
        await assertCall(portfolio, count: 2)
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
        defer { firstSkill.cancel() }
        await assertCall(skillA, count: 1)
        let secondSkill = Task { await model.inspectSkill(slug: "technical_depth") }
        defer { secondSkill.cancel() }
        await assertCall(skillB, count: 1)
        await skillB.resolve(.init(items: [event(id: 62, skill: "technical_depth")], nextCursor: nil))
        await skillA.resolve(.init(items: [event(id: 51, skill: "incident_communication")], nextCursor: nil))
        await secondSkill.value
        await firstSkill.value

        let firstActivity = Task { await model.inspectActivity(activityID: 41) }
        defer { firstActivity.cancel() }
        await assertCall(activity41, count: 1)
        let secondActivity = Task { await model.inspectActivity(activityID: 42) }
        defer { secondActivity.cancel() }
        await assertCall(activity42, count: 1)
        await activity42.resolve(.init(items: [event(id: 63, skill: "technical_depth", activityID: 42)], nextCursor: nil))
        await activity41.resolve(.init(items: [event(id: 52, skill: "incident_communication")], nextCursor: nil))
        await secondActivity.value
        await firstActivity.value

        XCTAssertEqual(model.selectedSkillSlug, "technical_depth")
        XCTAssertEqual(model.skillPage?.items.map(\.id), [62])
        XCTAssertEqual(model.inspectedActivityID, 42)
        XCTAssertEqual(model.activityPage?.items.map(\.id), [63])
    }

    func testDeactivateDiscardsCancellationResistantInspectorCompletion() async {
        let page = DeferredValues<EvidenceEventPage>()
        let service = DeferredEvidenceService(
            skills: DeferredValues(values: [[assessedSkill()]]),
            portfolio: DeferredValues(values: [.init(items: [], nextCursor: nil)]),
            skillPages: ["incident_communication": page]
        )
        let model = EvidenceLedgerModel(service: service)

        let request = Task { await model.inspectSkill(slug: "incident_communication") }
        defer { request.cancel() }
        await assertCall(page, count: 1)
        model.deactivate()
        await page.resolve(.init(items: [event(id: 51, skill: "incident_communication")], nextCursor: nil))
        await request.value

        XCTAssertNil(model.skillPage)
        XCTAssertEqual(model.skillInspectorState, .idle)
    }

    func testRapidSkillsRetriesKeepNewestCancellationResistantResult() async {
        let skills = DeferredValues<[EvidenceSkill]>()
        let service = DeferredEvidenceService(
            skills: skills,
            portfolio: DeferredValues(values: [.init(items: [], nextCursor: nil)])
        )
        let model = EvidenceLedgerModel(service: service)

        let first = Task { await model.retrySkills() }
        defer { first.cancel() }
        await assertCall(skills, count: 1)
        let second = Task { await model.retrySkills() }
        defer { second.cancel() }
        await assertCall(skills, count: 2)
        await skills.resolve([assessedSkill(name: "Oldest")], call: 1)
        await first.value

        let third = Task { await model.retrySkills() }
        defer { third.cancel() }
        await assertCall(skills, count: 3)
        await skills.resolve([assessedSkill(name: "Newest")], call: 3)
        await third.value
        await skills.resolve([assessedSkill(name: "Older")], call: 2)
        await second.value

        XCTAssertEqual(model.skills.first?.name, "Newest")
        XCTAssertEqual(model.skillState, .content)
    }

    func testLineageTextLabelsKnownFieldsAndPreservesUnknownFallback() {
        let rendered = EvidenceLineageText.render(.object([
            "schema_version": .integer(1),
            "basis_code": .string("improving"),
            "dimension_score_id": .integer(550),
            "event_ids": .array([.integer(50), .integer(9)]),
            "future_basis": .object(["quoted\"key": .string("kept")]),
            "weight": .decimal(0.2),
        ]))

        XCTAssertEqual(
            rendered,
            "Basis: \"improving\"\nDimension score: 550\nEvidence events: [50, 9]\n\"future_basis\": {\"quoted\\\"key\": \"kept\"}\nSchema version: 1\nWeight: 0.2"
        )
    }

    private func assertCall<Value: Sendable>(
        _ deferred: DeferredValues<Value>,
        count: Int,
        file: StaticString = #filePath,
        line: UInt = #line
    ) async {
        let reached = await deferred.waitForCall(count: count)
        XCTAssertTrue(reached, "Request did not start before the timeout", file: file, line: line)
    }

    private func unassessedSkill() -> EvidenceSkill {
        .init(slug: "incident_communication", name: "Incident communication", baseline: "1", monthOneTarget: "2", finalTarget: "4", snapshot: nil)
    }

    private func assessedSkill(
        name: String = "Incident communication",
        slug: String = "incident_communication"
    ) -> EvidenceSkill {
        .init(
            slug: slug, name: name, baseline: "1", monthOneTarget: "2", finalTarget: "4",
            snapshot: .init(
                id: 71, formulaVersion: "formula-v1", snapshotDate: "2026-08-31", estimatedLevel: "3.125",
                confidence: "medium", trend: "improving", recency: "fresh", baselineTargetGap: "2.125",
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
    private var waiters: [Int: CheckedContinuation<Value, Never>] = [:]
    private var resolvedCalls: [Int: Value] = [:]
    private var callCount = 0

    init(values: [Value] = []) {
        self.values = values
    }

    func next() async -> Value {
        callCount += 1
        let call = callCount
        if !values.isEmpty { return values.removeFirst() }
        if let value = resolvedCalls.removeValue(forKey: call) { return value }
        return await withCheckedContinuation { waiters[call] = $0 }
    }

    func waitForCall(count: Int) async -> Bool {
        let clock = ContinuousClock()
        let deadline = clock.now.advanced(by: .seconds(1))
        while callCount < count {
            guard clock.now < deadline, !Task.isCancelled else { return false }
            try? await Task<Never, Never>.sleep(for: .milliseconds(5))
        }
        return true
    }

    func currentCallCount() -> Int { callCount }

    func resolve(_ value: Value, call: Int? = nil) {
        if let call {
            if let waiter = waiters.removeValue(forKey: call) {
                waiter.resume(returning: value)
            } else {
                resolvedCalls[call] = value
            }
            return
        }
        guard let call = waiters.keys.min(), let waiter = waiters.removeValue(forKey: call) else {
            values.append(value)
            return
        }
        waiter.resume(returning: value)
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
private final class DeferredResultEvidenceService: EvidenceServicing {
    let skills: DeferredValues<Result<[EvidenceSkill], EvidenceAPIError>>
    let portfolio: DeferredValues<Result<EvidencePortfolioPage, EvidenceAPIError>>
    let skillPages: [String: DeferredValues<Result<EvidenceEventPage, EvidenceAPIError>>]
    let activityPages: [Int: DeferredValues<Result<EvidenceEventPage, EvidenceAPIError>>]

    init(
        skills: DeferredValues<Result<[EvidenceSkill], EvidenceAPIError>>,
        portfolio: DeferredValues<Result<EvidencePortfolioPage, EvidenceAPIError>>,
        skillPages: [String: DeferredValues<Result<EvidenceEventPage, EvidenceAPIError>>] = [:],
        activityPages: [Int: DeferredValues<Result<EvidenceEventPage, EvidenceAPIError>>] = [:]
    ) {
        self.skills = skills
        self.portfolio = portfolio
        self.skillPages = skillPages
        self.activityPages = activityPages
    }

    func listSkills() async throws -> [EvidenceSkill] { try await skills.next().get() }
    func fetchSkill(slug: String) async throws -> EvidenceSkill {
        guard let skill = try await listSkills().first else { throw EvidenceAPIError.invalidResponse }
        return skill
    }
    func fetchSkillEvidence(slug: String, cursor: Int?) async throws -> EvidenceEventPage {
        guard let page = skillPages[slug] else { throw EvidenceAPIError.unavailable }
        return try await page.next().get()
    }
    func fetchActivityEvidence(activityID: Int, cursor: Int?) async throws -> EvidenceEventPage {
        guard let page = activityPages[activityID] else { throw EvidenceAPIError.unavailable }
        return try await page.next().get()
    }
    func fetchPortfolioHistory(cursor: Int?) async throws -> EvidencePortfolioPage {
        try await portfolio.next().get()
    }
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
