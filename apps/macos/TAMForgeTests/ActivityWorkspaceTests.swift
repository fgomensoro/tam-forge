import XCTest
@testable import TAMForge

@MainActor
final class ActivityWorkspaceTests: XCTestCase {
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
    var confirmError: ActivityAPIError?
    var commits: [ActivityCommitCommand] = []
    var selfReviews: [ActivitySelfReviewCommand] = []
    var heartbeats: [ActivityHeartbeatCommand] = []
    var pauses: [ActivityHeartbeatCommand] = []
    var presigns: [ActivityArtifactPresignCommand] = []
    var confirms: [ActivityArtifactConfirmCommand] = []

    init(detail: ActivityDetail) {
        self.detail = detail
    }

    func fetch(activityID: Int) async throws -> ActivityDetail { detail }

    func start(activityID: Int, expectedVersion: Int, idempotencyKey: String) async throws -> ActivitySummary {
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
        detail.state = .paused
        detail.optimisticVersion += 1
        detail.openTimer = nil
        return detail.summary
    }

    func resume(activityID: Int, expectedVersion: Int, idempotencyKey: String) async throws -> ActivitySummary {
        detail.state = .active
        detail.optimisticVersion += 1
        detail.openTimer = .init(id: 7, startedAt: .distantPast, lastHeartbeatAt: .distantPast, countedSeconds: 0, lastClientSequence: 0)
        return detail.summary
    }

    func heartbeat(_ command: ActivityHeartbeatCommand) async throws -> ActivitySummary {
        heartbeats.append(command)
        if let heartbeatError { throw heartbeatError }
        detail.optimisticVersion += 1
        detail.openTimer?.lastClientSequence = command.clientSequence
        return detail.summary
    }

    func setSourceHidden(activityID: Int, expectedVersion: Int, hidden: Bool, idempotencyKey: String) async throws -> ActivityDetail {
        detail.sourceHidden = hidden
        detail.optimisticVersion += 1
        return detail
    }

    func commit(_ command: ActivityCommitCommand) async throws -> ActivityCommitReceipt {
        commits.append(command)
        if let detailAfterCommit { detail = detailAfterCommit }
        return .init(activityID: command.activityID, state: .outputCommitted, optimisticVersion: 4, attemptID: 72, commitmentSHA256: String(repeating: "a", count: 64), artifactIDs: command.artifactReferences.map(\.artifactID))
    }

    func submitSelfReview(_ command: ActivitySelfReviewCommand) async throws -> ActivitySelfReviewReceipt {
        selfReviews.append(command)
        if let detailAfterReview { detail = detailAfterReview }
        return .init(activityID: command.activityID, state: .selfReviewComplete, optimisticVersion: 5, selfReviewID: 80, attemptID: 72, selfScore: command.selfScore)
    }

    func classifyIncomplete(_ command: ActivityIncompleteCommand) async throws -> ActivitySummary {
        detail.state = .incomplete
        detail.classification = command.classification
        detail.optimisticVersion += 1
        return detail.summary
    }

    func presign(_ command: ActivityArtifactPresignCommand) async throws -> ActivityArtifactPresignResponse {
        presigns.append(command)
        return .init(
            artifactID: nil,
            objectKey: "written_output/1/activity-41/\(command.sha256)",
            reused: false,
            upload: .init(url: URL(string: "https://upload.example.test/item")!, headers: ["content-type": command.contentType], expiresSeconds: 60)
        )
    }

    func confirm(_ command: ActivityArtifactConfirmCommand) async throws -> ActivityArtifact {
        confirms.append(command)
        if let confirmError { throw confirmError }
        return .init(id: 90, sha256: String(repeating: "a", count: 64), byteLength: 5, contentType: "text/plain", originalFilename: "answer.txt", artifactClass: .writtenOutput)
    }
}

enum ActivityFixtures {
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
