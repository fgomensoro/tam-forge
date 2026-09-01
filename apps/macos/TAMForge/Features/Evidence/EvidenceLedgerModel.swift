import Combine
import Foundation

@MainActor
final class EvidenceLedgerModel: ObservableObject {
    @Published private(set) var skills: [EvidenceSkill] = []
    @Published private(set) var portfolioPage: EvidencePortfolioPage?
    @Published private(set) var activityPage: EvidenceEventPage?
    @Published private(set) var skillPage: EvidenceEventPage?
    @Published private(set) var activeActivityID: Int?
    @Published private(set) var selectedSkillSlug: String?
    @Published private(set) var inspectedActivityID: Int?
    @Published private(set) var skillState: EvidenceLoadState = .idle
    @Published private(set) var portfolioState: EvidenceLoadState = .idle
    @Published private(set) var activityState: EvidenceLoadState = .idle
    @Published private(set) var skillInspectorState: EvidenceLoadState = .idle
    @Published private(set) var skillInspectorError: String?
    @Published private(set) var skillError: String?
    @Published private(set) var portfolioError: String?
    @Published private(set) var activityInspectorError: String?
    @Published private(set) var isStale = false

    private let service: any EvidenceServicing
    private var lifetime = 0
    private var skillsRequest = 0
    private var skillRequest = 0
    private var activityRequest = 0
    private var portfolioRequest = 0
    private var skillsTask: Task<[EvidenceSkill], Error>?
    private var portfolioTask: Task<EvidencePortfolioPage, Error>?
    private var skillTask: Task<EvidenceEventPage, Error>?
    private var activityTask: Task<EvidenceEventPage, Error>?
    private var skillCursor: Int?
    private var activityCursor: Int?
    private var portfolioCursor: Int?
    private var failedSkillCursor: Int?
    private var failedActivityCursor: Int?
    private var failedPortfolioCursor: Int?
    private var active = true

    var canRetrySkills: Bool { skillState == .failed }
    var canRetryPortfolio: Bool { portfolioState == .failed }
    var canRetrySkillInspector: Bool { skillInspectorState == .failed && selectedSkillSlug != nil }
    var canRetryActivityInspector: Bool { activityState == .failed && inspectedActivityID != nil }
    var selectedSkill: EvidenceSkill? { skills.first { $0.slug == selectedSkillSlug } }
    var isNewestSkillPage: Bool { skillCursor == nil }
    var isNewestActivityPage: Bool { activityCursor == nil }
    var isNewestPortfolioPage: Bool { portfolioCursor == nil }

    func skillName(for slug: String) -> String? {
        skills.first { $0.slug == slug }?.name
    }

    init(service: any EvidenceServicing) { self.service = service }

    func open(activityID: Int?) async {
        beginDestination(clearPrivateState: true)
        activeActivityID = activityID
        await loadDestination(skillReload: nil)
    }

    func refresh() async {
        guard active else { return }
        beginDestination(clearPrivateState: false)
        let selectedSkill = selectedSkillSlug
        clearSkillPage(keepSelection: true)
        let reload = selectedSkill.map { SkillReload(slug: $0, request: skillRequest) }
        await loadDestination(skillReload: reload)
    }

    func markStale() {
        invalidateAllRequests()
        isStale = true
        restoreSectionStates()
    }

    func deactivate() {
        active = false
        invalidateAllRequests()
        restoreSectionStates()
    }

    func reset() {
        active = false
        invalidateAllRequests()
        clearAllPrivateState()
    }

    func showAllEvidence() {
        activeActivityID = nil
        clearActivityInspector()
    }

    func dismissSkillInspector() {
        clearSkillPage(keepSelection: false)
    }

    func clearActivityInspector() {
        activityRequest &+= 1
        activityTask?.cancel()
        activityTask = nil
        activityPage = nil
        inspectedActivityID = nil
        activityCursor = nil
        failedActivityCursor = nil
        activityState = .idle
        activityInspectorError = nil
    }

    func inspectSkill(slug: String) async {
        guard active else { return }
        selectedSkillSlug = slug
        clearSkillPage(keepSelection: true)
        await requestSkillPage(slug: slug, cursor: nil)
    }

    func loadOlderSkillEvidence() async {
        guard active, let slug = selectedSkillSlug, let cursor = skillPage?.nextCursor else { return }
        await requestSkillPage(slug: slug, cursor: cursor)
    }

    func loadNewestSkillEvidence() async {
        guard active, let slug = selectedSkillSlug else { return }
        await requestSkillPage(slug: slug, cursor: nil)
    }

    func retrySkillEvidence() async {
        guard active, let slug = selectedSkillSlug else { return }
        await requestSkillPage(slug: slug, cursor: failedSkillCursor)
    }

    func retrySkills() async {
        guard active else { return }
        let generation = lifetime
        let selectedSkill = selectedSkillSlug
        if selectedSkill != nil { clearSkillPage(keepSelection: true) }
        let reload = selectedSkill.map { SkillReload(slug: $0, request: skillRequest) }
        let loaded = await loadSkills(generation: generation)
        if loaded { await reloadSkillIfStillCurrent(reload, generation: generation) }
    }

    func inspectActivity(activityID: Int) async {
        guard active, activityID > 0 else { return }
        clearActivityInspector()
        activeActivityID = activityID
        inspectedActivityID = activityID
        await requestActivityPage(activityID: activityID, cursor: nil, generation: lifetime)
    }

    func loadOlderActivityEvidence() async {
        guard active, let activityID = inspectedActivityID, let cursor = activityPage?.nextCursor else { return }
        await requestActivityPage(activityID: activityID, cursor: cursor, generation: lifetime)
    }

    func loadNewestActivityEvidence() async {
        guard active, let activityID = inspectedActivityID else { return }
        await requestActivityPage(activityID: activityID, cursor: nil, generation: lifetime)
    }

    func retryActivityEvidence() async {
        guard active, let activityID = inspectedActivityID else { return }
        await requestActivityPage(activityID: activityID, cursor: failedActivityCursor, generation: lifetime)
    }

    func loadOlderPortfolio() async {
        guard active, let cursor = portfolioPage?.nextCursor else { return }
        await requestPortfolioPage(cursor: cursor, generation: lifetime)
    }

    func loadNewestPortfolio() async {
        guard active else { return }
        await requestPortfolioPage(cursor: nil, generation: lifetime)
    }

    func retryPortfolio() async {
        guard active else { return }
        await requestPortfolioPage(cursor: failedPortfolioCursor, generation: lifetime)
    }

    private func beginDestination(clearPrivateState: Bool) {
        active = true
        invalidateAllRequests()
        if clearPrivateState { clearAllPrivateState() }
        isStale = false
    }

    private func loadDestination(skillReload: SkillReload?) async {
        let generation = lifetime
        async let skillsLoaded = loadSkills(generation: generation)
        async let portfolioDone: Void = requestPortfolioPage(cursor: nil, generation: generation)
        if let id = activeActivityID {
            inspectedActivityID = id
            await requestActivityPage(activityID: id, cursor: nil, generation: generation)
        }
        let (loaded, _) = await (skillsLoaded, portfolioDone)
        if loaded { await reloadSkillIfStillCurrent(skillReload, generation: generation) }
    }

    private func reloadSkillIfStillCurrent(_ reload: SkillReload?, generation: Int) async {
        guard let reload, generation == lifetime, active,
              selectedSkillSlug == reload.slug, skillRequest == reload.request,
              skillInspectorState == .idle, skillPage == nil
        else { return }
        guard skills.contains(where: { $0.slug == reload.slug }) else {
            clearSkillPage(keepSelection: false)
            return
        }
        await requestSkillPage(slug: reload.slug, cursor: nil)
    }

    @discardableResult
    private func loadSkills(generation: Int) async -> Bool {
        skillsRequest &+= 1
        let request = skillsRequest
        skillsTask?.cancel()
        skillState = .loading
        skillError = nil
        let task = Task { [service] in try await service.listSkills() }
        skillsTask = task
        defer {
            if request == skillsRequest {
                skillsTask = nil
                settleLoadingState(for: .skills)
            }
        }
        do {
            let value = try await withTaskCancellationHandler {
                try await task.value
            } onCancel: { task.cancel() }
            guard publishable(generation: generation, taskCancelled: task.isCancelled), request == skillsRequest else { return false }
            skills = value
            skillState = value.isEmpty ? .empty : .content
            return true
        } catch {
            handle(error, generation: generation, section: .skills, cursor: nil, request: request)
            return false
        }
    }

    private func requestPortfolioPage(cursor: Int?, generation: Int) async {
        portfolioRequest &+= 1
        let request = portfolioRequest
        portfolioTask?.cancel()
        portfolioState = .loading
        portfolioError = nil
        let task = Task { [service] in try await service.fetchPortfolioHistory(cursor: cursor) }
        portfolioTask = task
        defer {
            if request == portfolioRequest {
                portfolioTask = nil
                settleLoadingState(for: .portfolio)
            }
        }
        do {
            let page = try await withTaskCancellationHandler {
                try await task.value
            } onCancel: { task.cancel() }
            guard publishable(generation: generation, taskCancelled: task.isCancelled), request == portfolioRequest else { return }
            try EvidencePageValidator.portfolio(page, requestedCursor: cursor)
            portfolioPage = page
            portfolioCursor = cursor
            failedPortfolioCursor = nil
            portfolioState = page.items.isEmpty ? .empty : .content
        } catch { handle(error, generation: generation, section: .portfolio, cursor: cursor, request: request) }
    }

    private func requestSkillPage(slug: String, cursor: Int?) async {
        let generation = lifetime
        skillRequest &+= 1
        let request = skillRequest
        skillTask?.cancel()
        skillInspectorState = .loading
        skillInspectorError = nil
        let task = Task { [service] in try await service.fetchSkillEvidence(slug: slug, cursor: cursor) }
        skillTask = task
        defer {
            if request == skillRequest {
                skillTask = nil
                settleLoadingState(for: .skillInspector)
            }
        }
        do {
            let page = try await withTaskCancellationHandler {
                try await task.value
            } onCancel: { task.cancel() }
            guard publishable(generation: generation, taskCancelled: task.isCancelled), request == skillRequest, selectedSkillSlug == slug else { return }
            try EvidencePageValidator.events(page, scope: .skill(slug), requestedCursor: cursor)
            skillPage = page
            skillCursor = cursor
            failedSkillCursor = nil
            skillInspectorState = page.items.isEmpty ? .empty : .content
        } catch { handle(error, generation: generation, section: .skillInspector, cursor: cursor, request: request) }
    }

    private func requestActivityPage(activityID: Int, cursor: Int?, generation: Int) async {
        activityRequest &+= 1
        let request = activityRequest
        activityTask?.cancel()
        activityState = .loading
        activityInspectorError = nil
        let task = Task { [service] in try await service.fetchActivityEvidence(activityID: activityID, cursor: cursor) }
        activityTask = task
        defer {
            if request == activityRequest {
                activityTask = nil
                settleLoadingState(for: .activityInspector)
            }
        }
        do {
            let page = try await withTaskCancellationHandler {
                try await task.value
            } onCancel: { task.cancel() }
            guard publishable(generation: generation, taskCancelled: task.isCancelled), request == activityRequest, inspectedActivityID == activityID else { return }
            try EvidencePageValidator.events(page, scope: .activity(activityID), requestedCursor: cursor)
            activityPage = page
            activityCursor = cursor
            failedActivityCursor = nil
            activityState = page.items.isEmpty ? .empty : .content
        } catch { handle(error, generation: generation, section: .activityInspector, cursor: cursor, request: request) }
    }

    private func publishable(generation: Int, taskCancelled: Bool) -> Bool {
        active && generation == lifetime && !taskCancelled && !Task.isCancelled
    }

    private func handle(_ error: Error, generation: Int, section: Section, cursor: Int?, request: Int? = nil) {
        guard active, generation == lifetime, !Task.isCancelled,
              !isCancellation(error), requestMatches(section, request)
        else { return }
        if error as? EvidenceAPIError == .unauthorized { reset(); return }
        let message = error is EvidenceContractError || error as? EvidenceAPIError == .invalidResponse
            ? "Evidence response could not be used. Retry."
            : "Evidence could not be loaded. Retry."
        switch section {
        case .skills:
            skillState = .failed; skillError = message
        case .portfolio:
            portfolioState = .failed; portfolioError = message; failedPortfolioCursor = cursor
        case .skillInspector:
            skillInspectorState = .failed; skillInspectorError = message; failedSkillCursor = cursor
        case .activityInspector:
            activityState = .failed; activityInspectorError = message; failedActivityCursor = cursor
        }
    }

    private func settleLoadingState(for section: Section) {
        switch section {
        case .skills where skillState == .loading:
            skillState = skills.isEmpty ? .idle : .content
        case .portfolio where portfolioState == .loading:
            portfolioState = portfolioPage.map { $0.items.isEmpty ? .empty : .content } ?? .idle
        case .skillInspector where skillInspectorState == .loading:
            skillInspectorState = skillPage.map { $0.items.isEmpty ? .empty : .content } ?? .idle
        case .activityInspector where activityState == .loading:
            activityState = activityPage.map { $0.items.isEmpty ? .empty : .content } ?? .idle
        default:
            break
        }
    }

    private func requestMatches(_ section: Section, _ request: Int?) -> Bool {
        guard let request else { return true }
        return switch section {
        case .skills: request == skillsRequest
        case .portfolio: request == portfolioRequest
        case .skillInspector: request == skillRequest
        case .activityInspector: request == activityRequest
        }
    }

    private func isCancellation(_ error: Error) -> Bool {
        error is CancellationError || error as? EvidenceAPIError == .cancelled
    }

    private func invalidateAllRequests() {
        lifetime &+= 1
        skillsRequest &+= 1
        skillRequest &+= 1
        activityRequest &+= 1
        portfolioRequest &+= 1
        skillsTask?.cancel(); portfolioTask?.cancel(); skillTask?.cancel(); activityTask?.cancel()
        skillsTask = nil; portfolioTask = nil; skillTask = nil; activityTask = nil
    }

    private func clearAllPrivateState() {
        skills = []; portfolioPage = nil; skillPage = nil; activityPage = nil
        activeActivityID = nil; selectedSkillSlug = nil; inspectedActivityID = nil
        skillState = .idle; portfolioState = .idle; skillInspectorState = .idle; activityState = .idle
        skillError = nil; portfolioError = nil; skillInspectorError = nil; activityInspectorError = nil
        skillCursor = nil; activityCursor = nil; portfolioCursor = nil
        failedSkillCursor = nil; failedActivityCursor = nil; failedPortfolioCursor = nil
        isStale = false
    }

    private func clearSkillPage(keepSelection: Bool) {
        skillRequest &+= 1; skillTask?.cancel(); skillTask = nil
        skillPage = nil; skillCursor = nil; failedSkillCursor = nil
        skillInspectorState = .idle; skillInspectorError = nil
        if !keepSelection { selectedSkillSlug = nil }
    }

    private func restoreSectionStates() {
        skillState = skills.isEmpty ? .idle : .content
        portfolioState = portfolioPage.map { $0.items.isEmpty ? .empty : .content } ?? .idle
        skillInspectorState = skillPage.map { $0.items.isEmpty ? .empty : .content } ?? .idle
        activityState = activityPage.map { $0.items.isEmpty ? .empty : .content } ?? .idle
    }

    private enum Section { case skills, portfolio, skillInspector, activityInspector }
    private struct SkillReload { let slug: String; let request: Int }
}

enum EvidenceEventScope {
    case skill(String)
    case activity(Int)

    func contains(_ event: EvidenceEvent) -> Bool {
        switch self {
        case let .skill(slug): event.skillSlug == slug
        case let .activity(id): event.activityID == id
        }
    }
}

enum EvidenceContractError: Error { case invalidPayload }

enum EvidencePageValidator {
    static func events(_ page: EvidenceEventPage, scope: EvidenceEventScope, requestedCursor: Int?) throws {
        let ids = page.items.map(\.id)
        guard page.items.count <= 20, ids.allSatisfy({ $0 > 0 }), Set(ids).count == ids.count,
              zip(ids, ids.dropFirst()).allSatisfy({ $0 > $1 }), page.items.allSatisfy(scope.contains),
              page.nextCursor.map({ $0 > 0 }) ?? true,
              page.nextCursor.map({ !ids.isEmpty && $0 == ids.last }) ?? true,
              requestedCursor.map({ cursor in ids.allSatisfy { $0 < cursor } && (page.nextCursor.map { $0 < cursor } ?? true) }) ?? true
        else { throw EvidenceContractError.invalidPayload }
    }

    static func portfolio(_ page: EvidencePortfolioPage, requestedCursor: Int?) throws {
        let ids = page.items.map(\.id)
        guard page.items.count <= 20, ids.allSatisfy({ $0 > 0 }), Set(ids).count == ids.count,
              zip(ids, ids.dropFirst()).allSatisfy({ $0 > $1 }), page.nextCursor.map({ $0 > 0 }) ?? true,
              page.nextCursor.map({ !ids.isEmpty && $0 == ids.last }) ?? true,
              requestedCursor.map({ cursor in ids.allSatisfy { $0 < cursor } && (page.nextCursor.map { $0 < cursor } ?? true) }) ?? true
        else { throw EvidenceContractError.invalidPayload }
    }
}
