import Combine
import Foundation

enum ActivityAPIError: Error, Equatable, Sendable {
    case unauthorized
    case conflict
    case network
    case cancelled
    case expiredPresign
    case invalidResponse
}

struct ActivityHeartbeatCommand: Equatable, Sendable {
    var activityID: Int
    var expectedVersion: Int
    var clientSequence: Int
    var idempotencyKey: String
}

struct ActivityCommitCommand: Equatable, Sendable {
    var activityID: Int
    var expectedVersion: Int
    var clientSequence: Int
    var output: [String: ActivityJSONValue]
    var artifactReferences: [ActivityArtifactReference]
    var idempotencyKey: String
}

struct ActivityCommitReceipt: Codable, Equatable, Sendable {
    var activityID: Int
    var state: ActivityState
    var optimisticVersion: Int
    var attemptID: Int
    var commitmentSHA256: String
    var artifactIDs: [Int]

    enum CodingKeys: String, CodingKey {
        case activityID = "activity_id"
        case state
        case optimisticVersion = "optimistic_version"
        case attemptID = "attempt_id"
        case commitmentSHA256 = "commitment_sha256"
        case artifactIDs = "artifact_ids"
    }
}

struct ActivitySelfReviewInput: Equatable, Sendable {
    var mainAnswer: String
    var didWell: String
    var structureWeakness: String
    var vaguePoints: String
    var hesitationPoints: String
    var changeNext: String
    var selfScore: Int

    var isComplete: Bool {
        (0...4).contains(selfScore) && [
            mainAnswer, didWell, structureWeakness, vaguePoints, hesitationPoints, changeNext,
        ].allSatisfy { !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
    }
}

struct ActivitySelfReviewCommand: Equatable, Sendable {
    var activityID: Int
    var expectedVersion: Int
    var idempotencyKey: String
    var input: ActivitySelfReviewInput

    var selfScore: Int { input.selfScore }
}

struct ActivitySelfReviewReceipt: Codable, Equatable, Sendable {
    var activityID: Int
    var state: ActivityState
    var optimisticVersion: Int
    var selfReviewID: Int
    var attemptID: Int
    var selfScore: Int

    enum CodingKeys: String, CodingKey {
        case activityID = "activity_id"
        case state
        case optimisticVersion = "optimistic_version"
        case selfReviewID = "self_review_id"
        case attemptID = "attempt_id"
        case selfScore = "self_score"
    }
}

struct ActivityIncompleteCommand: Equatable, Sendable {
    var activityID: Int
    var expectedVersion: Int
    var classification: ActivityIncompleteClassification
    var strongerEvidenceID: Int?
    var idempotencyKey: String
}

struct ActivityArtifactPresignCommand: Equatable, Sendable {
    var activityID: Int
    var expectedVersion: Int
    var artifactClass: ActivityArtifactClass
    var sha256: String
    var byteLength: Int
    var contentType: String
    var originalFilename: String
    var idempotencyKey: String
}

struct ActivityPresignedUpload: Decodable, Equatable, Sendable {
    var url: URL
    var headers: [String: String]
    var expiresSeconds: Int
}

struct ActivityArtifactPresignResponse: Decodable, Equatable, Sendable {
    var artifactID: Int?
    var objectKey: String
    var reused: Bool
    var upload: ActivityPresignedUpload?
}

struct ActivityArtifactConfirmCommand: Equatable, Sendable {
    var activityID: Int
    var expectedVersion: Int
    var uploadIdempotencyKey: String
    var objectKey: String
    var idempotencyKey: String
}

@MainActor
protocol ActivityAPI: AnyObject {
    func fetch(activityID: Int) async throws -> ActivityDetail
    func executeSQL(_ command: SqlExecutionCommand) async throws -> SqlExecutionReceipt
    func fetchSQLHistory(activityID: Int) async throws -> [SqlExecutionReceipt]
    func start(activityID: Int, expectedVersion: Int, idempotencyKey: String) async throws -> ActivitySummary
    func pause(_ command: ActivityHeartbeatCommand) async throws -> ActivitySummary
    func resume(activityID: Int, expectedVersion: Int, idempotencyKey: String) async throws -> ActivitySummary
    func heartbeat(_ command: ActivityHeartbeatCommand) async throws -> ActivitySummary
    func setSourceHidden(activityID: Int, expectedVersion: Int, hidden: Bool, idempotencyKey: String) async throws -> ActivityDetail
    func commit(_ command: ActivityCommitCommand) async throws -> ActivityCommitReceipt
    func submitSelfReview(_ command: ActivitySelfReviewCommand) async throws -> ActivitySelfReviewReceipt
    func classifyIncomplete(_ command: ActivityIncompleteCommand) async throws -> ActivitySummary
    func presign(_ command: ActivityArtifactPresignCommand) async throws -> ActivityArtifactPresignResponse
    func confirm(_ command: ActivityArtifactConfirmCommand) async throws -> ActivityArtifact
}

enum ActivityRecovery: Equatable, Sendable {
    case none
    case networkRetryNeeded
    case reloadedAfterConflict
    case authenticationRequired
    case cancelled
}

@MainActor
final class ActivityWorkspaceModel: ObservableObject {
    @Published private(set) var activity: ActivityDetail?
    @Published private(set) var draft: ActivityDraft
    @Published private(set) var recovery: ActivityRecovery = .none
    @Published private(set) var errorMessage: String?
    @Published private(set) var isLoading = false
    @Published private(set) var isCommandRunning = false
    @Published private(set) var uploadBlocksMutations = false
    @Published var hasAcknowledgedImmutability = false

    let sqlExecution: SqlExecutionModel
    private var sqlObservation: AnyCancellable?

    private let activityID: Int
    private let api: any ActivityAPI
    private let drafts: any ActivityDraftStoring
    private let timer: ActivityTimerCoordinator
    private let monotonicNow: () -> TimeInterval
    private let heartbeatSleep: @Sendable (Duration) async throws -> Void
    private var timerDisplay: ActivityTimerDisplay?
    private var heartbeatTask: Task<Void, Never>?
    private var reloadTask: Task<Void, Never>?
    private var cancelCommand: (() -> Void)?
    private var cancelLoad: (() -> Void)?
    private var lifetime = 0
    private var isVisible = true
    private var isSleeping = false
    private var heartbeatInFlight = false
    private weak var uploader: ActivityArtifactUploader?
    private var uploadObservation: AnyCancellable?

    init(
        activityID: Int,
        api: any ActivityAPI,
        drafts: any ActivityDraftStoring,
        timerJournal: any ActivityTimerJournaling = UserDefaultsActivityTimerJournal(),
        idempotency: @escaping @Sendable () -> String = { UUID().uuidString },
        monotonicNow: @escaping () -> TimeInterval = { ProcessInfo.processInfo.systemUptime },
        heartbeatSleep: @escaping @Sendable (Duration) async throws -> Void = { try await Task.sleep(for: $0) }
    ) {
        self.activityID = activityID
        self.api = api
        self.sqlExecution = SqlExecutionModel(api: api)
        self.drafts = drafts
        self.timer = ActivityTimerCoordinator(activityID: activityID, api: api, journal: timerJournal, idempotency: idempotency)
        self.monotonicNow = monotonicNow
        self.heartbeatSleep = heartbeatSleep
        self.draft = .init(kind: .writing, values: [:])
        self.sqlObservation = sqlExecution.objectWillChange.sink { [weak self] _ in
            self?.objectWillChange.send()
        }
    }

    deinit {
        heartbeatTask?.cancel()
        reloadTask?.cancel()
    }

    var artifactReferences: [ActivityArtifactReference] { draft.artifactReferences }
    private var available: Bool { isVisible && !isSleeping && recovery != .authenticationRequired }
    var canMutate: Bool { available && !isLoading && !isCommandRunning && !uploadBlocksMutations && !sqlExecution.isRunning }
    var canUpload: Bool { canMutate && (activity?.state == .active || activity?.state == .paused) }
    var canEditDraft: Bool { available && activity?.state.isEditable == true && (!isCommandRunning || heartbeatInFlight) }
    var canRetry: Bool { available && !isLoading && !isCommandRunning && recovery != .none }

    var showsSQLExecution: Bool { activity?.taskContract.block == .sql }
    var canRunSQL: Bool {
        showsSQLExecution && canMutate && canEditDraft && activity?.state == .active
            && !sqlExecution.isLoadingHistory && SqlExecutionModel.queryReason(draft.value(for: "query")) == nil
    }
    var canReadSQLHistory: Bool { showsSQLExecution && available && !isLoading && !isCommandRunning && !sqlExecution.isRunning && !sqlExecution.isLoadingHistory }

    func runSQL() async {
        guard canRunSQL, let activity else { return }
        do {
            try await sqlExecution.run(activityID: activity.id, expectedVersion: activity.optimisticVersion,
                                       query: draft.value(for: "query"))
        } catch { handle(error) }
    }

    func refreshSQLHistory() async {
        guard canReadSQLHistory else { return }
        do { try await sqlExecution.loadHistory(activityID: activityID) }
        catch { handle(error) }
    }

    func connect(uploader: ActivityArtifactUploader) {
        self.uploader = uploader
        uploadObservation = uploader.$state.combineLatest(uploader.$isRunning).sink { [weak self] value in
            self?.uploadBlocksMutations = value.1 || value.0 == .confirmationIndeterminate
        }
    }

    func appear() {
        isVisible = true
    }

    func disappear() {
        saveDraft()
        isVisible = false
        invalidateWork()
    }

    func open() async {
        guard available, !isLoading, !isCommandRunning, !sqlExecution.isRunning else { return }
        stopHeartbeat()
        isLoading = true
        let generation = lifetime
        let api = api
        let activityID = activityID
        let task = Task { try await api.fetch(activityID: activityID) }
        cancelLoad = { task.cancel() }
        defer {
            if generation == lifetime {
                isLoading = false
                cancelLoad = nil
                startHeartbeatIfNeeded()
            }
        }
        do {
            let detail = try await withTaskCancellationHandler {
                try await task.value
            } onCancel: { task.cancel() }
            guard generation == lifetime, available, !Task.isCancelled, !task.isCancelled else { return }
            if activity == nil {
                draft = drafts.load(activityID: detail.id) ?? .empty(for: detail)
            }
            receive(detail)
            if !detail.state.isEditable {
                // A remote read must not destroy our uncommitted local recovery copy.
                hasAcknowledgedImmutability = false
            }
            recovery = .none
            errorMessage = nil
            if showsSQLExecution { try await sqlExecution.loadHistory(activityID: activityID) }
        } catch {
            if generation == lifetime { handle(error) }
        }
    }

    func updateDraft(_ draft: ActivityDraft) {
        guard canEditDraft else { return }
        self.draft = draft
        sqlExecution.queryDidChange(draft.value(for: "query"))
        saveDraft()
    }

    func saveDraft() {
        guard isVisible, recovery != .authenticationRequired, let activity, activity.state.isEditable else { return }
        drafts.save(draft, activityID: activity.id)
    }

    var recoverableDraft: ActivityDraft? {
        guard let activity, !activity.state.isEditable,
              drafts.load(activityID: activity.id) != nil,
              draft != .empty(for: activity) else { return nil }
        return draft
    }

    func focusedSeconds(monotonicNow: TimeInterval? = nil) -> Int {
        guard available, recovery == .none else { return activity?.activityFocusedSeconds ?? 0 }
        return timerDisplay?.focusedSeconds(monotonicNow: monotonicNow ?? self.monotonicNow()) ?? 0
    }

    var canCommit: Bool {
        guard canMutate, let activity, activity.state == .active, hasAcknowledgedImmutability else { return false }
        guard activity.taskContract.block != .technicalLearning || activity.sourceHidden else { return false }
        return draft.isComplete(for: activity)
    }

    /// Attempt A remains independent until server-backed self-review completes.
    var canRequestFeedback: Bool { false }

    func start() async {
        guard let activity, activity.state == .ready else { return }
        await execute {
            try await self.api.start(activityID: activity.id, expectedVersion: activity.optimisticVersion, idempotencyKey: UUID().uuidString)
        } apply: { self.apply($0) }
    }

    func pause() async {
        guard let activity, activity.state == .active else { return }
        await execute { try await self.timer.pause(activity: activity) } apply: { self.apply($0) }
    }

    func resume() async {
        guard let activity, activity.state == .paused else { return }
        await execute {
            var current = activity
            if self.timer.pendingOperation != nil,
               let receipt = try await self.timer.heartbeat(activity: current) {
                current.apply(receipt)
            }
            guard current.state == .paused else { throw ActivityAPIError.conflict }
            return try await self.api.resume(activityID: current.id, expectedVersion: current.optimisticVersion, idempotencyKey: UUID().uuidString)
        } apply: { self.apply($0) }
    }

    func heartbeat(automatic: Bool = false) async {
        guard let activity, activity.state == .active else { return }
        // Heartbeats do not change optimistic_version. They may maintain focus during a
        // long PUT; user mutations and a pending pause still cannot cross that boundary.
        await execute(allowDuringUpload: automatic && timer.pendingOperation != .pause) {
            try await self.timer.heartbeat(activity: activity)
        } apply: {
            if let summary = $0 { self.apply(summary) }
        }
    }

    func setSourceHidden(_ hidden: Bool) async {
        guard let activity, activity.state.isEditable else { return }
        await execute {
            try await self.api.setSourceHidden(
                activityID: activity.id, expectedVersion: activity.optimisticVersion,
                hidden: hidden, idempotencyKey: UUID().uuidString
            )
        } apply: { self.receive($0) }
    }

    func attach(_ artifact: ActivityArtifact, role: ActivityArtifactLinkRole = .supporting) {
        guard canEditDraft else { return }
        let reference = ActivityArtifactReference(artifactID: artifact.id, linkRole: role)
        guard !artifactReferences.contains(reference) else { return }
        draft.artifactReferences.append(reference)
        saveDraft()
    }

    func upload(sourceURL: URL, artifactClass: ActivityArtifactClass) async {
        guard canUpload, let activity, let uploader else { return }
        let generation = lifetime
        do {
            let artifact = try await uploader.upload(
                sourceURL: sourceURL, activityID: activity.id,
                expectedVersion: activity.optimisticVersion, artifactClass: artifactClass
            )
            guard generation == lifetime, available, !Task.isCancelled else { return }
            attach(artifact)
            recovery = .none
            errorMessage = nil
            startHeartbeatIfNeeded()
        } catch {
            if generation == lifetime { handle(error) }
        }
    }

    func reconcileUpload() async {
        guard available, !isCommandRunning, !isLoading, let uploader,
              uploader.state == .confirmationIndeterminate, !uploader.isRunning else { return }
        let generation = lifetime
        do {
            let artifact = try await uploader.reconcile()
            guard generation == lifetime, available, !Task.isCancelled else { return }
            attach(artifact)
            recovery = .none
            errorMessage = nil
            startHeartbeatIfNeeded()
        } catch {
            if generation == lifetime { handle(error) }
        }
    }

    func cancelUpload() {
        uploader?.cancel()
    }

    func commit() async {
        guard let activity, canCommit, let output = draft.output(for: activity) else { return }
        let command = ActivityCommitCommand(
            activityID: activity.id, expectedVersion: activity.optimisticVersion,
            clientSequence: timer.nextSequence(for: activity), output: output,
            artifactReferences: artifactReferences, idempotencyKey: UUID().uuidString
        )
        let committed = await execute { try await self.api.commit(command) } apply: { receipt in
            self.activity?.state = receipt.state
            self.activity?.optimisticVersion = receipt.optimisticVersion
            self.activity?.openTimer = nil
            if let current = self.activity { self.receive(current) }
            self.timer.clearPending()
            self.clearDraft(for: activity)
            self.stopHeartbeat()
        }
        if committed { await open() }
    }

    func submitSelfReview(_ input: ActivitySelfReviewInput) async {
        guard let activity, activity.state == .outputCommitted, input.isComplete else { return }
        let submitted = await execute {
            try await self.api.submitSelfReview(.init(
                activityID: activity.id, expectedVersion: activity.optimisticVersion,
                idempotencyKey: UUID().uuidString, input: input
            ))
        } apply: { receipt in
            self.activity?.state = receipt.state
            self.activity?.optimisticVersion = receipt.optimisticVersion
        }
        if submitted { await open() }
    }

    func classifyIncomplete(as classification: ActivityIncompleteClassification, strongerEvidenceID: Int? = nil) async {
        guard canMutate, let activity, activity.state.isEditable else { return }
        guard (classification == .superseded) == (strongerEvidenceID != nil) else {
            errorMessage = "Superseded work needs one stronger evidence ID."
            return
        }
        await execute {
            try await self.api.classifyIncomplete(.init(
                activityID: activity.id, expectedVersion: activity.optimisticVersion, classification: classification,
                strongerEvidenceID: strongerEvidenceID, idempotencyKey: UUID().uuidString
            ))
        } apply: {
            self.apply($0)
            self.clearDraft(for: activity)
            self.timer.clearPending()
        }
    }

    func handleSleep() {
        saveDraft()
        isSleeping = true
        invalidateWork()
    }

    func handleWake() async {
        isSleeping = false
        await open()
    }

    func handleUploadError(_ error: Error) { handle(error) }
    func dismissError() { errorMessage = nil }

    @discardableResult
    private func execute<Value: Sendable>(
        allowDuringUpload: Bool = false,
        _ command: @escaping @MainActor () async throws -> Value,
        apply: (Value) -> Void
    ) async -> Bool {
        guard available, !isLoading, !isCommandRunning, !uploadBlocksMutations || allowDuringUpload,
              !sqlExecution.isRunning || allowDuringUpload else { return false }
        isCommandRunning = true
        heartbeatInFlight = allowDuringUpload
        let generation = lifetime
        let task = Task { try Task.checkCancellation(); return try await command() }
        cancelCommand = { task.cancel() }
        defer {
            if generation == lifetime {
                isCommandRunning = false
                heartbeatInFlight = false
                cancelCommand = nil
                startHeartbeatIfNeeded()
            }
        }
        do {
            let value = try await withTaskCancellationHandler {
                try await task.value
            } onCancel: { task.cancel() }
            guard generation == lifetime, available, !Task.isCancelled, !task.isCancelled else { return false }
            apply(value)
            recovery = .none
            errorMessage = nil
            return true
        } catch {
            if generation == lifetime { handle(error) }
            return false
        }
    }

    private func receive(_ detail: ActivityDetail) {
        activity = detail
        timerDisplay = ActivityTimerDisplay(activity: detail, monotonicNow: monotonicNow())
    }

    private func apply(_ summary: ActivitySummary) {
        guard var current = activity else { return }
        let previous = current
        current.apply(summary)
        guard current != previous else { return }
        receive(current)
        if current.state != .active { stopHeartbeat() }
    }

    private func clearDraft(for detail: ActivityDetail) {
        drafts.remove(activityID: detail.id)
        draft = .empty(for: detail)
        hasAcknowledgedImmutability = false
    }

    private func startHeartbeatIfNeeded() {
        guard available, recovery == .none, activity?.state == .active, heartbeatTask == nil else { return }
        let sleep = heartbeatSleep
        heartbeatTask = Task { [weak self] in
            while !Task.isCancelled {
                do { try await sleep(.seconds(15)); try Task.checkCancellation() }
                catch { return }
                guard let self, self.available, self.recovery == .none, self.activity?.state == .active else { return }
                await self.heartbeat(automatic: true)
            }
        }
    }

    private func stopHeartbeat() {
        heartbeatTask?.cancel()
        heartbeatTask = nil
    }

    private func invalidateWork() {
        lifetime += 1
        sqlExecution.invalidate()
        stopHeartbeat()
        reloadTask?.cancel()
        reloadTask = nil
        cancelCommand?()
        cancelCommand = nil
        cancelLoad?()
        cancelLoad = nil
        uploader?.cancel()
        isCommandRunning = false
        heartbeatInFlight = false
        isLoading = false
    }

    private func handle(_ error: Error) {
        stopHeartbeat()
        let activityError = error as? ActivityAPIError
        if error is CancellationError || activityError == .cancelled || (error as? URLError)?.code == .cancelled {
            recovery = .cancelled
            errorMessage = nil
            return
        }
        switch activityError {
        case .unauthorized:
            recovery = .authenticationRequired
            invalidateWork()
            sqlExecution.invalidate(clearHistory: true)
            drafts.remove(activityID: activityID)
            draft = .init(kind: .writing, values: [:])
            hasAcknowledgedImmutability = false
            timer.clearPending()
            errorMessage = "Your session expired. Sign in again."
        case .conflict:
            saveDraft()
            recovery = .reloadedAfterConflict
            errorMessage = "Activity changed elsewhere. Reloading server state; the local draft is preserved."
            let generation = lifetime
            reloadTask?.cancel()
            reloadTask = Task { [weak self] in
                guard let self, self.lifetime == generation, !Task.isCancelled else { return }
                await self.open()
            }
        case .network, .expiredPresign, .invalidResponse, .none, .cancelled:
            recovery = .networkRetryNeeded
            errorMessage = "Network action was not confirmed. Existing evidence and the in-memory draft remain unchanged."
        }
    }
}
