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
    @Published private(set) var artifactReferences: [ActivityArtifactReference] = []
    @Published private(set) var recovery: ActivityRecovery = .none
    @Published private(set) var errorMessage: String?
    @Published var hasAcknowledgedImmutability = false

    private let activityID: Int
    private let api: any ActivityAPI
    private let drafts: any ActivityDraftStoring
    private let timer: ActivityTimerCoordinator

    init(
        activityID: Int,
        api: any ActivityAPI,
        drafts: any ActivityDraftStoring,
        timerJournal: any ActivityTimerJournaling = UserDefaultsActivityTimerJournal(),
        idempotency: @escaping @Sendable () -> String = { UUID().uuidString }
    ) {
        self.activityID = activityID
        self.api = api
        self.drafts = drafts
        self.timer = ActivityTimerCoordinator(
            activityID: activityID,
            api: api,
            journal: timerJournal,
            idempotency: idempotency
        )
        self.draft = .init(kind: .writing, values: [:])
    }

    func open() async {
        do {
            let detail = try await api.fetch(activityID: activityID)
            activity = detail
            draft = detail.state.isEditable ? (drafts.load(activityID: detail.id) ?? .empty(for: detail)) : .empty(for: detail)
            if !detail.state.isEditable {
                drafts.remove(activityID: detail.id)
                artifactReferences = []
            }
            recovery = .none
            errorMessage = nil
        } catch {
            handle(error)
        }
    }

    func updateDraft(_ draft: ActivityDraft) {
        guard activity?.state.isEditable == true else { return }
        self.draft = draft
    }

    func saveDraft() {
        guard let activity, activity.state.isEditable else { return }
        drafts.save(draft, activityID: activity.id)
    }

    var canCommit: Bool {
        guard let activity, activity.state == .active, hasAcknowledgedImmutability else { return false }
        guard activity.taskContract.block != .technicalLearning || activity.sourceHidden else { return false }
        return draft.isComplete(for: activity)
    }

    /// Attempt A remains independent until server-backed self-review completes.
    var canRequestFeedback: Bool { false }

    func start() async {
        guard let activity, activity.state == .ready else { return }
        await applyMutation {
            try await api.start(activityID: activity.id, expectedVersion: activity.optimisticVersion, idempotencyKey: UUID().uuidString)
        }
    }

    func pause() async {
        guard let activity, activity.state == .active else { return }
        let command = timer.nextHeartbeatCommand(for: activity)
        timer.journal(command)
        do {
            apply(try await api.pause(command))
            timer.clearPending()
            recovery = .none
            errorMessage = nil
        } catch {
            let activityError = error as? ActivityAPIError
            if activityError == .conflict || activityError == .unauthorized {
                timer.clearPending()
            }
            handle(error)
        }
    }

    func resume() async {
        guard let activity, activity.state == .paused else { return }
        await applyMutation {
            try await api.resume(activityID: activity.id, expectedVersion: activity.optimisticVersion, idempotencyKey: UUID().uuidString)
        }
    }

    func heartbeat() async {
        guard let activity, activity.state == .active else { return }
        do {
            if let summary = try await timer.heartbeat(activity: activity) {
                apply(summary)
                recovery = .none
            }
        } catch {
            handle(error)
        }
    }

    func setSourceHidden(_ hidden: Bool) async {
        guard let activity, activity.state.isEditable else { return }
        do {
            self.activity = try await api.setSourceHidden(
                activityID: activity.id,
                expectedVersion: activity.optimisticVersion,
                hidden: hidden,
                idempotencyKey: UUID().uuidString
            )
        } catch {
            handle(error)
        }
    }

    func attach(_ artifact: ActivityArtifact, role: ActivityArtifactLinkRole = .supporting) {
        let reference = ActivityArtifactReference(artifactID: artifact.id, linkRole: role)
        guard !artifactReferences.contains(reference) else { return }
        artifactReferences.append(reference)
        saveDraft()
    }

    func commit() async {
        guard let activity, canCommit, let output = draft.output(for: activity) else { return }
        do {
            let command = ActivityCommitCommand(
                activityID: activity.id,
                expectedVersion: activity.optimisticVersion,
                clientSequence: timer.nextSequence(for: activity),
                output: output,
                artifactReferences: artifactReferences,
                idempotencyKey: UUID().uuidString
            )
            _ = try await api.commit(command)
            drafts.remove(activityID: activity.id)
            artifactReferences = []
            await open()
        } catch {
            handle(error)
        }
    }

    func submitSelfReview(_ input: ActivitySelfReviewInput) async {
        guard let activity, activity.state == .outputCommitted, input.isComplete else { return }
        do {
            _ = try await api.submitSelfReview(.init(
                activityID: activity.id,
                expectedVersion: activity.optimisticVersion,
                idempotencyKey: UUID().uuidString,
                input: input
            ))
            await open()
        } catch {
            handle(error)
        }
    }

    func classifyIncomplete(
        as classification: ActivityIncompleteClassification,
        strongerEvidenceID: Int? = nil
    ) async {
        guard let activity, activity.state.isEditable else { return }
        guard (classification == .superseded) == (strongerEvidenceID != nil) else {
            errorMessage = "Superseded work needs one stronger evidence ID."
            return
        }
        do {
            let summary = try await api.classifyIncomplete(.init(
                activityID: activity.id,
                expectedVersion: activity.optimisticVersion,
                classification: classification,
                strongerEvidenceID: strongerEvidenceID,
                idempotencyKey: UUID().uuidString
            ))
            apply(summary)
            drafts.remove(activityID: activity.id)
        } catch {
            handle(error)
        }
    }

    func handleSleep() {
        saveDraft()
    }

    func handleWake() async {
        await open()
    }

    func handleUploadError(_ error: Error) {
        handle(error)
    }

    func dismissError() {
        errorMessage = nil
    }

    private func applyMutation(_ command: () async throws -> ActivitySummary) async {
        do {
            apply(try await command())
            recovery = .none
            errorMessage = nil
        } catch {
            handle(error)
        }
    }

    private func apply(_ summary: ActivitySummary) {
        activity?.apply(summary)
    }

    private func handle(_ error: Error) {
        let activityError = error as? ActivityAPIError
        switch activityError {
        case .unauthorized:
            drafts.remove(activityID: activityID)
            artifactReferences = []
            recovery = .authenticationRequired
            errorMessage = "Your session expired. Sign in again; no new evidence was created."
        case .conflict:
            recovery = .reloadedAfterConflict
            errorMessage = "Activity changed elsewhere. Reloaded server state; no local command was repeated."
            Task { await open() }
        case .cancelled:
            recovery = .cancelled
            errorMessage = nil
        case .network, .expiredPresign, .invalidResponse, .none:
            recovery = .networkRetryNeeded
            errorMessage = "Network action was not confirmed. Existing evidence and in-memory draft remain unchanged."
        }
    }
}
