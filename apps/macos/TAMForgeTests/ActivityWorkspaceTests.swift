import XCTest

@MainActor
final class ActivityWorkspaceTests: XCTestCase {
    func testLiveActivityReadDecodesValidCommittedOutputLargerThanTwoMiB() async throws {
        var detail = ActivityFixtures.detail(state: .outputCommitted, version: 4)
        let text = String(repeating: "a", count: 2_500_000)
        let draft = ActivityFixtures.completeWritingDraft(for: detail).setting("draft_markdown", to: text)
        detail.committedOutput = .init(
            attemptID: 72, attemptKind: "A", commitmentSHA256: String(repeating: "a", count: 64),
            contractPayload: ["output": .object(try XCTUnwrap(draft.output(for: detail)))],
            artifactIDs: [], committedAt: Date(timeIntervalSince1970: 1_700_000_000)
        )
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        let body = try encoder.encode(detail)
        XCTAssertGreaterThan(body.count, 2 * 1024 * 1024)
        ActivityOutputProtocol.response.set(body)
        defer { ActivityOutputProtocol.response.set(nil) }
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [ActivityOutputProtocol.self]
        let session = URLSession(configuration: configuration)
        defer { session.invalidateAndCancel() }
        let api = LiveActivityAPI(transport: NativeAPITransport(
            baseURL: URL(string: "https://activity.example.test")!, session: session
        ))

        let fetched = try await api.fetch(activityID: 41)

        XCTAssertEqual(fetched, detail)
    }

    func testReloadPreservesCurrentDraftInsteadOfOlderSavedText() async {
        let detail = ActivityFixtures.detail(state: .active)
        let api = ActivityAPIStub(detail: detail)
        let drafts = InMemoryActivityDraftStore()
        let model = ActivityWorkspaceModel(activityID: detail.id, api: api, drafts: drafts,
                                           timerJournal: InMemoryActivityTimerJournal())
        await model.open()
        model.updateDraft(model.draft.setting("draft_markdown", to: "Older saved text"))
        model.saveDraft()
        model.updateDraft(model.draft.setting("draft_markdown", to: "Current unsaved text"))

        await model.open()

        XCTAssertEqual(model.draft.value(for: "draft_markdown"), "Current unsaved text")
        XCTAssertTrue(api.commits.isEmpty)
    }

    func testConflictReloadPreservesCurrentDraftAndUploadedReferences() async {
        let detail = ActivityFixtures.detail(state: .active)
        let api = ActivityAPIStub(detail: detail)
        let model = ActivityWorkspaceModel(activityID: detail.id, api: api,
                                           drafts: InMemoryActivityDraftStore(),
                                           timerJournal: InMemoryActivityTimerJournal())
        await model.open()
        model.attach(ActivityFixtures.artifact, role: .originalOutput)
        model.updateDraft(model.draft.setting("draft_markdown", to: "Unsaved after attachment"))
        api.sourceError = .conflict
        let reloaded = expectation(description: "Conflict reload finishes")
        api.beforeFetch = { reloaded.fulfill() }

        await model.setSourceHidden(true)
        await fulfillment(of: [reloaded], timeout: 1)

        XCTAssertEqual(model.draft.value(for: "draft_markdown"), "Unsaved after attachment")
        XCTAssertEqual(model.artifactReferences, [.init(artifactID: 90, linkRole: .originalOutput)])
    }

    func testRemoteFinalizationPreservesLocalDraftWithoutMakingEvidenceEditable() async {
        for state in [ActivityState.outputCommitted, .incomplete] {
            let detail = ActivityFixtures.detail(state: .active)
            let api = ActivityAPIStub(detail: detail)
            let drafts = InMemoryActivityDraftStore()
            let model = ActivityWorkspaceModel(activityID: detail.id, api: api, drafts: drafts,
                                               timerJournal: InMemoryActivityTimerJournal())
            await model.open()
            model.updateDraft(model.draft.setting("draft_markdown", to: "Local copy differs from remote evidence"))
            model.attach(ActivityFixtures.artifact, role: .originalOutput)
            api.detail.state = state
            api.detail.optimisticVersion += 1

            await model.open()

            XCTAssertEqual(model.activity?.state, state)
            XCTAssertEqual(model.draft.value(for: "draft_markdown"), "Local copy differs from remote evidence")
            XCTAssertEqual(model.artifactReferences, [.init(artifactID: 90, linkRole: .originalOutput)])
            XCTAssertEqual(drafts.load(activityID: detail.id), model.draft)
            XCTAssertEqual(model.recoverableDraft, model.draft)
            XCTAssertFalse(model.canEditDraft)
            XCTAssertFalse(model.canCommit)
            model.disappear()

            let restored = ActivityWorkspaceModel(activityID: detail.id, api: api, drafts: drafts,
                                                  timerJournal: InMemoryActivityTimerJournal())
            await restored.open()
            XCTAssertEqual(restored.draft.value(for: "draft_markdown"), "Local copy differs from remote evidence")
            XCTAssertFalse(restored.canEditDraft)
            restored.disappear()
        }
    }

    func testSharedDraftStoreRestoresArtifactReferencesWithRoles() async {
        let detail = ActivityFixtures.detail(state: .active)
        let api = ActivityAPIStub(detail: detail)
        let drafts = InMemoryActivityDraftStore()
        let first = ActivityWorkspaceModel(activityID: detail.id, api: api, drafts: drafts,
                                           timerJournal: InMemoryActivityTimerJournal())
        await first.open()
        first.updateDraft(ActivityFixtures.completeWritingDraft(for: detail))
        first.attach(ActivityFixtures.artifact, role: .originalOutput)
        first.saveDraft()

        let restored = ActivityWorkspaceModel(activityID: detail.id, api: api, drafts: drafts,
                                              timerJournal: InMemoryActivityTimerJournal())
        await restored.open()
        restored.hasAcknowledgedImmutability = true
        XCTAssertEqual(restored.artifactReferences, [.init(artifactID: 90, linkRole: .originalOutput)])
        await restored.commit()

        XCTAssertEqual(api.commits.first?.artifactReferences, [.init(artifactID: 90, linkRole: .originalOutput)])
    }

    func testCommitReceiptLocksEditingWhenFollowupFetchFails() async {
        let detail = ActivityFixtures.detail(state: .active)
        let api = ActivityAPIStub(detail: detail)
        let drafts = InMemoryActivityDraftStore()
        let model = ActivityWorkspaceModel(activityID: detail.id, api: api, drafts: drafts,
                                           timerJournal: InMemoryActivityTimerJournal())
        await model.open()
        model.updateDraft(ActivityFixtures.completeWritingDraft(for: detail))
        model.saveDraft()
        model.hasAcknowledgedImmutability = true
        api.fetchError = .network

        await model.commit()

        XCTAssertEqual(model.activity?.state, .outputCommitted)
        XCTAssertEqual(model.activity?.optimisticVersion, 4)
        XCTAssertNil(model.activity?.openTimer)
        XCTAssertFalse(model.canCommit)
        XCTAssertNil(drafts.load(activityID: detail.id))
        XCTAssertNil(model.recoverableDraft)
        let lockedDraft = model.draft
        model.updateDraft(model.draft.setting("draft_markdown", to: "Cannot edit evidence"))
        XCTAssertEqual(model.draft, lockedDraft)
        await model.commit()
        XCTAssertEqual(api.commits.count, 1)
    }

    func testCommitCannotRaceAnotherCommitOrMutation() async {
        let detail = ActivityFixtures.detail(state: .active)
        let api = ActivityAPIStub(detail: detail)
        let model = ActivityWorkspaceModel(activityID: detail.id, api: api,
                                           drafts: InMemoryActivityDraftStore(),
                                           timerJournal: InMemoryActivityTimerJournal())
        await model.open()
        model.updateDraft(ActivityFixtures.completeWritingDraft(for: detail))
        model.hasAcknowledgedImmutability = true
        let gate = ActivityTestGate()
        api.beforeCommit = { await gate.wait() }
        let committing = Task { await model.commit() }
        await fulfillment(of: [gate.entered], timeout: 1)
        // A duplicate must not enter the held request, so it must not wait on this gate.
        api.beforeCommit = nil

        XCTAssertFalse(model.canCommit)
        await model.commit()
        await model.pause()
        await model.setSourceHidden(true)
        await model.classifyIncomplete(as: .optional)

        XCTAssertEqual(api.commits.count, 1)
        XCTAssertTrue(api.pauses.isEmpty)
        XCTAssertTrue(api.sourceChanges.isEmpty)
        XCTAssertTrue(api.classifications.isEmpty)
        gate.release()
        await committing.value
    }

    func testStartCannotRaceDuplicateStart() async {
        let detail = ActivityFixtures.detail()
        let api = ActivityAPIStub(detail: detail)
        let model = ActivityWorkspaceModel(activityID: detail.id, api: api,
                                           drafts: InMemoryActivityDraftStore(),
                                           timerJournal: InMemoryActivityTimerJournal())
        await model.open()
        let gate = ActivityTestGate()
        api.beforeStart = { await gate.wait() }
        let starting = Task { await model.start() }
        await fulfillment(of: [gate.entered], timeout: 1)
        api.beforeStart = nil

        await model.start()

        XCTAssertEqual(api.startCount, 1)
        gate.release()
        await starting.value
    }

    func testAuthenticationFailureRejectsLateArtifactAndDraftSaves() async {
        let detail = ActivityFixtures.detail(state: .active)
        let api = ActivityAPIStub(detail: detail)
        let drafts = InMemoryActivityDraftStore()
        let model = ActivityWorkspaceModel(activityID: detail.id, api: api, drafts: drafts,
                                           timerJournal: InMemoryActivityTimerJournal())
        await model.open()
        model.updateDraft(ActivityFixtures.completeWritingDraft(for: detail))
        model.hasAcknowledgedImmutability = true

        model.handleUploadError(ActivityAPIError.unauthorized)
        model.attach(ActivityFixtures.artifact)
        model.saveDraft()

        XCTAssertTrue(model.artifactReferences.isEmpty)
        XCTAssertNil(drafts.load(activityID: detail.id))
        XCTAssertFalse(model.canCommit)
    }

    func testLateFetchCannotRestoreDraftAfterAuthenticationFailure() async {
        let detail = ActivityFixtures.detail(state: .active)
        let api = ActivityAPIStub(detail: detail)
        let drafts = InMemoryActivityDraftStore()
        let model = ActivityWorkspaceModel(activityID: detail.id, api: api, drafts: drafts,
                                           timerJournal: InMemoryActivityTimerJournal())
        await model.open()
        model.updateDraft(ActivityFixtures.completeWritingDraft(for: detail))
        let gate = ActivityTestGate()
        api.beforeFetch = { await gate.wait() }
        let loading = Task { await model.open() }
        await fulfillment(of: [gate.entered], timeout: 1)

        model.handleUploadError(ActivityAPIError.unauthorized)
        gate.release()
        await loading.value

        XCTAssertEqual(model.recovery, .authenticationRequired)
        XCTAssertNil(drafts.load(activityID: detail.id))
        XCTAssertFalse(model.canCommit)
    }

    func testFirstLoadFailureRemainsRetryableAfterDismissingError() async {
        let api = ActivityAPIStub(detail: ActivityFixtures.detail())
        api.fetchError = .network
        let model = ActivityWorkspaceModel(activityID: 41, api: api,
                                           drafts: InMemoryActivityDraftStore(),
                                           timerJournal: InMemoryActivityTimerJournal())
        await model.open()
        model.dismissError()

        XCTAssertNil(model.activity)
        XCTAssertEqual(model.recovery, .networkRetryNeeded)
        XCTAssertNil(model.errorMessage)
        api.fetchError = nil
        await model.open()
        XCTAssertNotNil(model.activity)
        XCTAssertEqual(model.recovery, .none)
    }

    func testDraftPersistsAcrossModelRecreationWithoutCreatingEvidence() async throws {
        let api = ActivityAPIStub(detail: ActivityFixtures.detail())
        let drafts = InMemoryActivityDraftStore()
        let first = ActivityWorkspaceModel(activityID: 41, api: api, drafts: drafts)

        await first.open()
        first.updateDraft(first.draft.setting("requested_action", to: "Confirm rollback."))
        first.saveDraft()

        let restored = ActivityWorkspaceModel(activityID: 41, api: api, drafts: drafts)
        await restored.open()

        XCTAssertEqual(restored.draft.value(for: "requested_action"), "Confirm rollback.")
        XCTAssertTrue(api.commits.isEmpty)
        XCTAssertTrue(api.selfReviews.isEmpty)
    }

    func testIndependentAttemptRequiresActiveTimerClosedSourceAndAcknowledgement() async throws {
        var detail = ActivityFixtures.detail(state: .ready)
        detail.taskContract.block = .technicalLearning
        let api = ActivityAPIStub(detail: detail)
        let model = ActivityWorkspaceModel(activityID: detail.id, api: api, drafts: InMemoryActivityDraftStore())

        await model.open()
        model.updateDraft(ActivityFixtures.completeReadingDraft(for: detail))
        model.hasAcknowledgedImmutability = true
        XCTAssertFalse(model.canCommit)

        await model.start()
        XCTAssertFalse(model.canCommit)

        await model.setSourceHidden(true)
        XCTAssertTrue(model.canCommit)
    }

    func testCommitRemovesDraftAndSelfReviewRemainsOnlyNextAllowedStep() async throws {
        let detail = ActivityFixtures.detail(state: .active)
        let api = ActivityAPIStub(detail: detail)
        api.detailAfterCommit = ActivityFixtures.detail(state: .outputCommitted, version: 4)
        api.detailAfterReview = ActivityFixtures.detail(state: .selfReviewComplete, version: 5, selfReview: .init(
            id: 80,
            attemptID: 72,
            selfScore: 3,
            mainAnswer: "Recommend rollback.",
            didWell: "Led with the decision.",
            structureWeakness: "Risk came late.",
            vaguePoints: "Checkpoint was vague.",
            hesitationPoints: "Before mitigation.",
            changeNext: "Name the checkpoint.",
            submittedAt: .distantPast
        ))
        let drafts = InMemoryActivityDraftStore()
        let model = ActivityWorkspaceModel(activityID: detail.id, api: api, drafts: drafts)

        await model.open()
        model.updateDraft(ActivityFixtures.completeWritingDraft(for: detail))
        model.hasAcknowledgedImmutability = true
        await model.commit()

        XCTAssertEqual(model.activity?.state, .outputCommitted)
        XCTAssertNil(drafts.load(activityID: detail.id))
        XCTAssertEqual(api.commits.count, 1)
        XCTAssertFalse(model.canRequestFeedback)

        await model.submitSelfReview(ActivityFixtures.selfReview)
        XCTAssertEqual(model.activity?.state, .selfReviewComplete)
        XCTAssertEqual(api.selfReviews.count, 1)
        XCTAssertFalse(model.canRequestFeedback)
    }

    func testSQLDraftCarriesResultAndAssistanceMetadata() throws {
        var detail = ActivityFixtures.detail(state: .active)
        detail.taskContract.block = .sql
        detail.taskContract.timeboxMinutes = 20
        detail.activityFocusedSeconds = 1_500
        var draft = ActivityDraft.empty(for: detail)
        [
            "audience": "Operations lead",
            "query": "SELECT count(*) FROM incidents;",
            "result": "42",
            "validation": "Compared with the incident export.",
            "explanation": "Counts all incident rows.",
            "business_meaning": "The queue needs triage.",
            "assistance_used": "hint_ladder",
        ].forEach { draft = draft.setting($0.key, to: $0.value) }

        let output = try XCTUnwrap(draft.output(for: detail))

        XCTAssertEqual(output["kind"], .string("sql"))
        XCTAssertEqual(output["result"], .string("42"))
        XCTAssertEqual(output["assistance_used"], .string("hint_ladder"))
        XCTAssertEqual(output["solving_seconds"], .integer(1_200))
    }

    func testUnauthorizedDropsLocalDraftAndDoesNotPretendMutationSucceeded() async throws {
        let detail = ActivityFixtures.detail(state: .ready)
        let api = ActivityAPIStub(detail: detail)
        api.startError = .unauthorized
        let drafts = InMemoryActivityDraftStore()
        let model = ActivityWorkspaceModel(activityID: detail.id, api: api, drafts: drafts)

        await model.open()
        model.updateDraft(model.draft.setting("requested_action", to: "Keep only locally until auth fails."))
        model.saveDraft()
        await model.start()

        XCTAssertEqual(model.activity?.state, .ready)
        XCTAssertEqual(model.recovery, .authenticationRequired)
        XCTAssertNil(drafts.load(activityID: detail.id))
    }

    func testUnauthorizedUploadDropsDraftAndArtifactReferences() async throws {
        let detail = ActivityFixtures.detail(state: .active)
        let drafts = InMemoryActivityDraftStore()
        let model = ActivityWorkspaceModel(activityID: detail.id, api: ActivityAPIStub(detail: detail), drafts: drafts)

        await model.open()
        model.updateDraft(ActivityFixtures.completeWritingDraft(for: detail))
        model.attach(.init(
            id: 90,
            sha256: String(repeating: "a", count: 64),
            byteLength: 5,
            contentType: "text/plain",
            originalFilename: "redacted.txt",
            artifactClass: .writtenOutput
        ))
        model.handleUploadError(ActivityAPIError.unauthorized)

        XCTAssertEqual(model.recovery, .authenticationRequired)
        XCTAssertTrue(model.artifactReferences.isEmpty)
        XCTAssertNil(drafts.load(activityID: detail.id))
    }
}

@MainActor
final class ActivityAPIStub: ActivityAPI {
    var detail: ActivityDetail
    var detailAfterCommit: ActivityDetail?
    var detailAfterReview: ActivityDetail?
    var startError: ActivityAPIError?
    var heartbeatError: ActivityAPIError?
    var pauseError: ActivityAPIError?
    var heartbeatResponse: ActivitySummary?
    var pauseResponse: ActivitySummary?
    var resumeVersions: [Int] = []
    var confirmError: ActivityAPIError?
    var fetchError: ActivityAPIError?
    var sourceError: ActivityAPIError?
    var beforeFetch: (() async throws -> Void)?
    var beforeStart: (() async throws -> Void)?
    var beforeCommit: (() async throws -> Void)?
    var beforeHeartbeat: (() async throws -> Void)?
    var beforeConfirm: (() async throws -> Void)?
    var beforePresign: (() async throws -> Void)?
    var startCount = 0
    var sourceChanges: [Bool] = []
    var classifications: [ActivityIncompleteCommand] = []
    var commits: [ActivityCommitCommand] = []
    var selfReviews: [ActivitySelfReviewCommand] = []
    var heartbeats: [ActivityHeartbeatCommand] = []
    var pauses: [ActivityHeartbeatCommand] = []
    var presigns: [ActivityArtifactPresignCommand] = []
    var confirms: [ActivityArtifactConfirmCommand] = []

    init(detail: ActivityDetail) {
        self.detail = detail
    }

    func fetch(activityID: Int) async throws -> ActivityDetail {
        try await beforeFetch?()
        if let fetchError { throw fetchError }
        return detail
    }

    func start(activityID: Int, expectedVersion: Int, idempotencyKey: String) async throws -> ActivitySummary {
        startCount += 1
        try await beforeStart?()
        if let startError { throw startError }
        detail.state = .active
        detail.optimisticVersion += 1
        detail.openTimer = .init(
            id: 7,
            startedAt: .distantPast,
            lastHeartbeatAt: .distantPast,
            countedSeconds: 0,
            lastClientSequence: 0
        )
        return detail.summary
    }

    func pause(_ command: ActivityHeartbeatCommand) async throws -> ActivitySummary {
        pauses.append(command)
        if let pauseError { throw pauseError }
        if let pauseResponse { return pauseResponse }
        detail.state = .paused
        detail.optimisticVersion += 1
        detail.openTimer = nil
        return detail.summary
    }

    func resume(activityID: Int, expectedVersion: Int, idempotencyKey: String) async throws -> ActivitySummary {
        resumeVersions.append(expectedVersion)
        detail.state = .active
        detail.optimisticVersion += 1
        detail.openTimer = .init(id: 7, startedAt: .distantPast, lastHeartbeatAt: .distantPast, countedSeconds: 0, lastClientSequence: 0)
        return detail.summary
    }

    func heartbeat(_ command: ActivityHeartbeatCommand) async throws -> ActivitySummary {
        heartbeats.append(command)
        try await beforeHeartbeat?()
        if let heartbeatError { throw heartbeatError }
        if let heartbeatResponse { return heartbeatResponse }
        // Backend heartbeats advance the timer sequence, not the activity version.
        detail.openTimer?.lastClientSequence = command.clientSequence
        return detail.summary
    }

    func setSourceHidden(activityID: Int, expectedVersion: Int, hidden: Bool, idempotencyKey: String) async throws -> ActivityDetail {
        sourceChanges.append(hidden)
        if let sourceError { throw sourceError }
        detail.sourceHidden = hidden
        detail.optimisticVersion += 1
        return detail
    }

    func commit(_ command: ActivityCommitCommand) async throws -> ActivityCommitReceipt {
        commits.append(command)
        try await beforeCommit?()
        if let detailAfterCommit { detail = detailAfterCommit }
        return .init(activityID: command.activityID, state: .outputCommitted, optimisticVersion: 4, attemptID: 72, commitmentSHA256: String(repeating: "a", count: 64), artifactIDs: command.artifactReferences.map(\.artifactID))
    }

    func submitSelfReview(_ command: ActivitySelfReviewCommand) async throws -> ActivitySelfReviewReceipt {
        selfReviews.append(command)
        if let detailAfterReview { detail = detailAfterReview }
        return .init(activityID: command.activityID, state: .selfReviewComplete, optimisticVersion: 5, selfReviewID: 80, attemptID: 72, selfScore: command.selfScore)
    }

    func classifyIncomplete(_ command: ActivityIncompleteCommand) async throws -> ActivitySummary {
        classifications.append(command)
        detail.state = .incomplete
        detail.classification = command.classification
        detail.optimisticVersion += 1
        return detail.summary
    }

    func presign(_ command: ActivityArtifactPresignCommand) async throws -> ActivityArtifactPresignResponse {
        presigns.append(command)
        try await beforePresign?()
        return .init(
            artifactID: nil,
            objectKey: "written_output/1/activity-41/\(command.sha256)",
            reused: false,
            upload: .init(url: URL(string: "https://upload.example.test/item")!, headers: ["content-type": command.contentType], expiresSeconds: 60)
        )
    }

    func confirm(_ command: ActivityArtifactConfirmCommand) async throws -> ActivityArtifact {
        confirms.append(command)
        try await beforeConfirm?()
        if let confirmError { throw confirmError }
        return .init(id: 90, sha256: String(repeating: "a", count: 64), byteLength: 5, contentType: "text/plain", originalFilename: "answer.txt", artifactClass: .writtenOutput)
    }
}

enum ActivityFixtures {
    static let artifact = ActivityArtifact(
        id: 90, sha256: String(repeating: "a", count: 64), byteLength: 5,
        contentType: "text/plain", originalFilename: "answer.txt", artifactClass: .writtenOutput
    )
    static func detail(
        state: ActivityState = .ready,
        version: Int = 3,
        selfReview: ActivitySelfReview? = nil
    ) -> ActivityDetail {
        .init(
            id: 41,
            studyDayID: 8,
            state: state,
            optimisticVersion: version,
            classification: .required,
            strongerEvidenceID: nil,
            activityFocusedSeconds: 120,
            dayFocusedMinutes: 2,
            hardStopRecommended: false,
            openTimer: state == .active ? .init(id: 7, startedAt: .distantPast, lastHeartbeatAt: .distantPast, countedSeconds: 120, lastClientSequence: 4) : nil,
            sourceHidden: false,
            taskContract: .init(
                stableID: "redacted-writing-41",
                block: .communicationSpoken,
                objective: "Write a concise customer incident update.",
                timeboxMinutes: 35,
                required: true,
                sourceReferences: [.init(path: "Redacted Week.md", anchor: "Incident update")],
                requiredOutput: ["Independent draft"],
                passCriteria: ["States impact and next action"],
                evidenceRequirements: ["Committed Attempt A"],
                allowedAIRole: .none,
                procedure: [.init(phase: "Draft", minutes: 30, requirement: "Write without AI.")],
                constraints: ["No AI before commitment."],
                exerciseType: "writing",
                mappingVersion: "redacted-v1"
            ),
            committedOutput: nil,
            selfReview: selfReview
        )
    }

    static func completeWritingDraft(for detail: ActivityDetail) -> ActivityDraft {
        var draft = ActivityDraft.empty(for: detail)
        [
            "audience": "Technical lead",
            "requested_action": "Confirm rollback.",
            "facts": "Errors rose after release.",
            "unknowns": "Regional scope.",
            "tone": "Calm and direct",
            "word_or_character_limit": "150 words",
            "draft_markdown": "We recommend a rollback.",
            "self_edit_notes": "Removed speculation.",
        ].forEach { draft = draft.setting($0.key, to: $0.value) }
        return draft
    }

    static func completeReadingDraft(for detail: ActivityDetail) -> ActivityDraft {
        var draft = ActivityDraft.empty(for: detail)
        [
            "audience": "Peer TAM",
            "key_idea_1": "Request boundary",
            "key_idea_2": "Response boundary",
            "key_idea_3": "Failure boundary",
            "boundary_or_failure": "Timeout",
            "tam_customer_example": "Trace request IDs",
            "unresolved_question": "Retry policy",
        ].forEach { draft = draft.setting($0.key, to: $0.value) }
        return draft
    }

    static let selfReview = ActivitySelfReviewInput(
        mainAnswer: "Recommend rollback.",
        didWell: "Led with decision.",
        structureWeakness: "Risk came late.",
        vaguePoints: "Checkpoint vague.",
        hesitationPoints: "Before mitigation.",
        changeNext: "Name checkpoint.",
        selfScore: 3
    )
}

/// Holds a request at its real asynchronous boundary, including a late, noncooperative response.
@MainActor
final class ActivityTestGate {
    let entered = XCTestExpectation(description: "Request reached suspension point")
    private var continuation: CheckedContinuation<Void, Never>?

    func wait() async {
        await withCheckedContinuation { continuation in
            self.continuation = continuation
            entered.fulfill()
        }
    }

    func release() {
        continuation?.resume()
        continuation = nil
    }
}

private final class ActivityOutputResponse: @unchecked Sendable {
    private let lock = NSLock()
    private var body: Data?
    func set(_ body: Data?) { lock.withLock { self.body = body } }
    func get() -> Data? { lock.withLock { body } }
}

private final class ActivityOutputProtocol: URLProtocol {
    static let response = ActivityOutputResponse()
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        client?.urlProtocol(self, didReceive: HTTPURLResponse(
            url: request.url!, statusCode: 200, httpVersion: nil,
            headerFields: ["Content-Type": "application/json"]
        )!, cacheStoragePolicy: .notAllowed)
        if let body = Self.response.get() { client?.urlProtocol(self, didLoad: body) }
        client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() {}
}
