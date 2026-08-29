import Combine
import Foundation
import HTTPTypes

struct TodaySnapshot: Codable, Equatable, Sendable {
    let localDate: String
    let timezone: String
    let dayID: Int?
    let dayType: String
    let dayStatus: String
    let roadmap: TodayRoadmap
    let totalPlannedMinutes: Int
    let timePolicy: TodayTimePolicy
    let requiredBlocks: [TodayBlock]
    let tasks: [TodayTask]
    let corrections: [TodayCorrection]
    let interviews: [TodayInterview]
    let awaitingSelfReviews: [TodaySelfReview]
    let analyses: [TodayAnalysis]
    let primaryContinue: TodayContinueAction?
    let sourceUpdatedAt: String
    let readModelVersion: String
    let etag: String

    enum CodingKeys: String, CodingKey {
        case localDate = "local_date"
        case timezone
        case dayID = "day_id"
        case dayType = "day_type"
        case dayStatus = "day_status"
        case roadmap
        case totalPlannedMinutes = "total_planned_minutes"
        case timePolicy = "time_policy"
        case requiredBlocks = "required_blocks"
        case tasks, corrections, interviews
        case awaitingSelfReviews = "awaiting_self_reviews"
        case analyses
        case primaryContinue = "primary_continue"
        case sourceUpdatedAt = "source_updated_at"
        case readModelVersion = "read_model_version"
        case etag
    }
}

struct TodayRoadmap: Codable, Equatable, Sendable {
    let versionID: Int
    let versionKey: String
    let versionNumber: Int
    let month: Int
    let week: Int
    let day: Int

    enum CodingKeys: String, CodingKey {
        case versionID = "version_id"
        case versionKey = "version_key"
        case versionNumber = "version_number"
        case month, week, day
    }
}

struct TodayTimePolicy: Codable, Equatable, Sendable {
    let targetMinutes: Int
    let acceptableMinimum: Int
    let hardStopMinutes: Int
    let focusedMinutes: Int
    let hardStopRecommended: Bool

    enum CodingKeys: String, CodingKey {
        case targetMinutes = "target_minutes"
        case acceptableMinimum = "acceptable_minimum"
        case hardStopMinutes = "hard_stop_minutes"
        case focusedMinutes = "focused_minutes"
        case hardStopRecommended = "hard_stop_recommended"
    }
}

struct TodayBlock: Codable, Equatable, Sendable {
    let name: String
    let plannedMinutes: Int
    let activityIDs: [Int]

    enum CodingKeys: String, CodingKey {
        case name
        case plannedMinutes = "planned_minutes"
        case activityIDs = "activity_ids"
    }
}

struct TodayTask: Codable, Equatable, Sendable, Identifiable {
    let activityID: Int
    let roadmapOrder: Int
    let stableID: String
    let block: String
    let state: String
    let objective: String
    let timeboxMinutes: Int
    let sourceReferences: [TodaySourceReference]
    let requiredOutput: [String]
    let passCriteria: [String]
    let allowedAIRole: String
    let evidenceRequirements: [String]
    let required: Bool
    let optimisticVersion: Int

    var id: Int { activityID }

    enum CodingKeys: String, CodingKey {
        case activityID = "activity_id"
        case roadmapOrder = "roadmap_order"
        case stableID = "stable_id"
        case block, state, objective
        case timeboxMinutes = "timebox_minutes"
        case sourceReferences = "source_references"
        case requiredOutput = "required_output"
        case passCriteria = "pass_criteria"
        case allowedAIRole = "allowed_ai_role"
        case evidenceRequirements = "evidence_requirements"
        case required
        case optimisticVersion = "optimistic_version"
    }
}

struct TodaySourceReference: Codable, Equatable, Sendable {
    let path: String
    let anchor: String?
}

struct TodayCorrection: Codable, Equatable, Sendable, Identifiable {
    let id: Int
    let priority: Int
    let dueDate: String
    let instruction: String
    let status: String
    let attemptBActivityID: Int?

    enum CodingKeys: String, CodingKey {
        case id, priority, instruction, status
        case dueDate = "due_date"
        case attemptBActivityID = "attempt_b_activity_id"
    }
}

struct TodayInterview: Codable, Equatable, Sendable, Identifiable {
    let id: Int
    let company: String
    let role: String
    let stage: String
    let startsAt: String
    let expectedDurationMinutes: Int
    let privacyPermissionCode: String

    enum CodingKeys: String, CodingKey {
        case id, company, role, stage
        case startsAt = "starts_at"
        case expectedDurationMinutes = "expected_duration_minutes"
        case privacyPermissionCode = "privacy_permission_code"
    }
}

struct TodaySelfReview: Codable, Equatable, Sendable, Identifiable {
    let activityID: Int
    let objective: String
    let outputCommittedAt: String

    var id: Int { activityID }

    enum CodingKeys: String, CodingKey {
        case activityID = "activity_id"
        case objective
        case outputCommittedAt = "output_committed_at"
    }
}

struct TodayAnalysis: Codable, Equatable, Sendable, Identifiable {
    let activityID: Int
    let state: String
    let progressLabel: String
    let updatedAt: String

    var id: Int { activityID }

    enum CodingKeys: String, CodingKey {
        case activityID = "activity_id"
        case state
        case progressLabel = "progress_label"
        case updatedAt = "updated_at"
    }
}

struct TodayContinueAction: Codable, Equatable, Sendable {
    let kind: String
    let targetID: Int
    let label: String
    let allowedAIRole: String

    enum CodingKeys: String, CodingKey {
        case kind
        case targetID = "target_id"
        case label
        case allowedAIRole = "allowed_ai_role"
    }
}

enum TodayFocus: Equatable, Sendable {
    case workspace
    case selfReview
}

enum TodayDestination: Equatable, Sendable {
    case activity(id: Int, focus: TodayFocus)
    case evidence(activityID: Int)
    case dailyClose(activityID: Int)

    init?(action: TodayContinueAction) {
        switch action.kind {
        case "correction_warmup", "resume_activity", "start_activity":
            self = .activity(id: action.targetID, focus: .workspace)
        case "complete_self_review":
            self = .activity(id: action.targetID, focus: .selfReview)
        case "review_feedback":
            self = .evidence(activityID: action.targetID)
        case "close_day":
            self = .dailyClose(activityID: action.targetID)
        default:
            return nil
        }
    }
}

enum TodayUnfinishedClassification: String, Codable, CaseIterable, Equatable, Sendable {
    case none
    case required
    case useful
    case optional
    case superseded

    var title: String {
        switch self {
        case .none: "None"
        case .required: "Required — replace adaptive work"
        case .useful: "Useful — retrieval queue"
        case .optional: "Optional — drop"
        case .superseded: "Superseded by stronger evidence"
        }
    }
}

struct TodayEvidenceManifest: Codable, Equatable, Sendable {
    let schemaVersion: Int
    let activityIDs: [Int]
    let attemptIDs: [Int]
    let artifactIDs: [Int]
    let selfReviewIDs: [Int]

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case activityIDs = "activity_ids"
        case attemptIDs = "attempt_ids"
        case artifactIDs = "artifact_ids"
        case selfReviewIDs = "self_review_ids"
    }
}

struct TodayDailyCloseCommand: Codable, Equatable, Sendable {
    let evidenceConfirmed: Bool
    let evidenceManifest: TodayEvidenceManifest
    let strongestOutput: String
    let repeatedMistake: String
    let unfinishedClassification: TodayUnfinishedClassification
    let unfinishedRequirement: String?
    let correctionIDs: [Int]

    enum CodingKeys: String, CodingKey {
        case evidenceConfirmed = "evidence_confirmed"
        case evidenceManifest = "evidence_manifest"
        case strongestOutput = "strongest_output"
        case repeatedMistake = "repeated_mistake"
        case unfinishedClassification = "unfinished_classification"
        case unfinishedRequirement = "unfinished_requirement"
        case correctionIDs = "correction_ids"
    }
}

struct TodayDailyCloseResponse: Codable, Equatable, Sendable {
    let dailyCloseID: Int
    let studyDayID: Int
    let dayStatus: String
    let closedAt: String
    let consequence: String
    let replayed: Bool

    enum CodingKeys: String, CodingKey {
        case dailyCloseID = "daily_close_id"
        case studyDayID = "study_day_id"
        case dayStatus = "day_status"
        case closedAt = "closed_at"
        case consequence, replayed
    }
}

enum TodayDailyCloseValidationError: LocalizedError, Equatable {
    case evidenceNotConfirmed
    case noSavedEvidence
    case strongestOutputRequired
    case repeatedMistakeRequired
    case unfinishedRequirementRequired
    case unavailableCorrection

    var errorDescription: String? {
        switch self {
        case .evidenceNotConfirmed: "Confirm saved evidence before closing the day."
        case .noSavedEvidence: "Close the day only after saved activity evidence exists."
        case .strongestOutputRequired: "Name the strongest saved output."
        case .repeatedMistakeRequired: "Name one repeated mistake."
        case .unfinishedRequirementRequired: "Describe unfinished work or select None."
        case .unavailableCorrection: "Selected correction is no longer available. Refresh Today and try again."
        }
    }
}

struct TodayDailyCloseDraft: Equatable, Sendable {
    var strongestOutput: String
    var repeatedMistake: String
    var unfinishedClassification: TodayUnfinishedClassification
    var unfinishedRequirement: String?
    var evidenceConfirmed: Bool
    var correctionIDs: [Int] = []

    func command(for snapshot: TodaySnapshot) throws -> TodayDailyCloseCommand {
        let strongestOutput = strongestOutput.trimmingCharacters(in: .whitespacesAndNewlines)
        let repeatedMistake = repeatedMistake.trimmingCharacters(in: .whitespacesAndNewlines)
        let unfinishedRequirement = unfinishedRequirement?.trimmingCharacters(in: .whitespacesAndNewlines)
        guard evidenceConfirmed else { throw TodayDailyCloseValidationError.evidenceNotConfirmed }
        guard !strongestOutput.isEmpty else { throw TodayDailyCloseValidationError.strongestOutputRequired }
        guard !repeatedMistake.isEmpty else { throw TodayDailyCloseValidationError.repeatedMistakeRequired }
        let activityIDs = snapshot.tasks
            .filter { $0.block != "daily_close" && Self.evidenceStates.contains($0.state) }
            .map(\.activityID)
        guard !activityIDs.isEmpty else { throw TodayDailyCloseValidationError.noSavedEvidence }
        if unfinishedClassification == .none {
            guard unfinishedRequirement == nil || unfinishedRequirement?.isEmpty == true else {
                throw TodayDailyCloseValidationError.unfinishedRequirementRequired
            }
        } else if unfinishedRequirement?.isEmpty != false {
            throw TodayDailyCloseValidationError.unfinishedRequirementRequired
        }
        let selected = Array(Set(correctionIDs)).sorted()
        guard selected.count <= 2,
              Set(selected).isSubset(of: Set(snapshot.corrections.map(\.id)))
        else {
            throw TodayDailyCloseValidationError.unavailableCorrection
        }
        return TodayDailyCloseCommand(
            evidenceConfirmed: true,
            evidenceManifest: .init(
                schemaVersion: 1,
                activityIDs: activityIDs,
                attemptIDs: [],
                artifactIDs: [],
                selfReviewIDs: []
            ),
            strongestOutput: strongestOutput,
            repeatedMistake: repeatedMistake,
            unfinishedClassification: unfinishedClassification,
            unfinishedRequirement: unfinishedClassification == .none ? nil : unfinishedRequirement,
            correctionIDs: selected
        )
    }

    private static let evidenceStates: Set<String> = [
        "output_committed", "self_review_complete", "ai_processing", "feedback_ready",
        "correction_due", "demonstrated", "needs_work", "incomplete", "superseded",
    ]
}

enum TodayLocalDate {
    static func string(for date: Date = .now, calendar: Calendar = .autoupdatingCurrent) -> String {
        let formatter = DateFormatter()
        formatter.calendar = calendar
        formatter.timeZone = calendar.timeZone
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "yyyy-MM-dd"
        return formatter.string(from: date)
    }
}

enum TodayDateTime {
    static func string(
        _ value: String,
        timezoneIdentifier: String,
        locale: Locale = .current
    ) -> String {
        let parser = ISO8601DateFormatter()
        guard let date = parser.date(from: value) else { return value }
        let formatter = DateFormatter()
        formatter.locale = locale
        formatter.timeZone = TimeZone(identifier: timezoneIdentifier) ?? .autoupdatingCurrent
        formatter.dateFormat = "EEE, MMM d, yyyy, h:mm a"
        return formatter.string(from: date)
    }
}

protocol TodayServicing: Sendable {
    func fetchToday(localDate: String) async throws -> TodaySnapshot
    func closeToday(
        localDate: String,
        command: TodayDailyCloseCommand,
        idempotencyKey: String
    ) async throws -> TodayDailyCloseResponse
}

struct NativeTodayAPIClient: TodayServicing {
    let transport: NativeAPITransport

    func fetchToday(localDate: String) async throws -> TodaySnapshot {
        let response = try await transport.send(
            .init(method: .get, path: "/api/v1/today?date=\(localDate)")
        )
        return try response.decoded(as: TodaySnapshot.self)
    }

    func closeToday(
        localDate: String,
        command: TodayDailyCloseCommand,
        idempotencyKey: String
    ) async throws -> TodayDailyCloseResponse {
        let body = try JSONEncoder().encode(command)
        let response = try await transport.send(
            .init(
                method: .post,
                path: "/api/v1/today/\(localDate)/close",
                body: body,
                idempotencyKey: idempotencyKey
            )
        )
        return try response.decoded(as: TodayDailyCloseResponse.self)
    }
}

enum TodayLoadState: Equatable {
    case loading
    case content(TodaySnapshot)
    case empty(TodaySnapshot)
    case partial(TodaySnapshot)
    case stale(TodaySnapshot)
    case offline(TodaySnapshot?)
    case problem(TodaySnapshot?)

    var snapshot: TodaySnapshot? {
        switch self {
        case let .content(snapshot), let .empty(snapshot), let .partial(snapshot), let .stale(snapshot): snapshot
        case let .offline(snapshot), let .problem(snapshot): snapshot
        case .loading: nil
        }
    }
}

enum TodayCloseState: Equatable {
    case idle
    case submitting
    case retryRequired
    case validation(String)
    case closed(TodayDailyCloseResponse)
}

@MainActor
final class TodayViewModel: ObservableObject {
    @Published private(set) var state: TodayLoadState = .loading
    @Published private(set) var closeState: TodayCloseState = .idle

    private let client: any TodayServicing
    private let now: @Sendable () -> Date
    private let idempotencyKey: @Sendable () -> String
    private var requestedLocalDate: String?
    private var pendingClose: (localDate: String, command: TodayDailyCloseCommand, idempotencyKey: String)?
    private var latestStatusEventID = 0

    init(
        client: any TodayServicing,
        now: @escaping @Sendable () -> Date = { .now },
        idempotencyKey: @escaping @Sendable () -> String = { "daily-close-\(UUID().uuidString)" }
    ) {
        self.client = client
        self.now = now
        self.idempotencyKey = idempotencyKey
    }

    var snapshot: TodaySnapshot? { state.snapshot }

    func load() async {
        let date = requestedLocalDate ?? TodayLocalDate.string(for: now())
        requestedLocalDate = date
        let previous = state.snapshot
        if previous == nil { state = .loading }
        do {
            let snapshot = try await client.fetchToday(localDate: date)
            state = Self.presentationState(for: snapshot)
        } catch is CancellationError {
            return
        } catch {
            state = Self.failureState(for: error, previous: previous)
        }
    }

    func retry() async {
        await load()
    }

    func close(_ draft: TodayDailyCloseDraft) async {
        guard let snapshot else {
            closeState = .validation("Load Today before closing the day.")
            return
        }
        do {
            let command = try draft.command(for: snapshot)
            let submission = (snapshot.localDate, command, idempotencyKey())
            pendingClose = submission
            await submit(submission)
        } catch let error as TodayDailyCloseValidationError {
            closeState = .validation(error.localizedDescription)
        } catch {
            closeState = .validation("Daily close details are invalid. Review them and try again.")
        }
    }

    func retryClose() async {
        guard let pendingClose else { return }
        await submit(pendingClose)
    }

    func receive(_ event: StatusEvent) {
        guard event.id > latestStatusEventID else { return }
        latestStatusEventID = event.id
        guard let snapshot,
              TodayStatusInvalidation.affects(snapshot: snapshot, event: event)
        else { return }
        Task { [weak self] in await self?.load() }
    }

    private func submit(_ submission: (localDate: String, command: TodayDailyCloseCommand, idempotencyKey: String)) async {
        closeState = .submitting
        do {
            let response = try await client.closeToday(
                localDate: submission.localDate,
                command: submission.command,
                idempotencyKey: submission.idempotencyKey
            )
            pendingClose = nil
            closeState = .closed(response)
            await load()
        } catch is CancellationError {
            closeState = .idle
        } catch {
            await load()
            if snapshot?.dayStatus == "closed" || snapshot?.dayStatus == "incomplete" {
                pendingClose = nil
                closeState = .idle
            } else {
                closeState = .retryRequired
            }
        }
    }

    private static func presentationState(for snapshot: TodaySnapshot) -> TodayLoadState {
        guard snapshot.dayType != "sunday", snapshot.dayStatus != "off" else {
            return .content(snapshot)
        }
        if snapshot.tasks.isEmpty {
            let hasSupport = !snapshot.corrections.isEmpty || !snapshot.interviews.isEmpty
                || !snapshot.awaitingSelfReviews.isEmpty || !snapshot.analyses.isEmpty
                || snapshot.primaryContinue != nil
            return hasSupport ? .partial(snapshot) : .empty(snapshot)
        }
        return .content(snapshot)
    }

    private static func failureState(for error: Error, previous: TodaySnapshot?) -> TodayLoadState {
        if error is URLError { return .offline(previous) }
        if previous != nil { return .stale(previous!) }
        return .problem(nil)
    }
}

enum TodayStatusInvalidation {
    static func affects(snapshot: TodaySnapshot, event: StatusEvent) -> Bool {
        if event.aggregateType == "study_day", event.aggregateID == snapshot.dayID { return true }
        let taskIDs = Set(snapshot.tasks.map(\.activityID))
        return taskIDs.contains(event.aggregateID)
            || taskIDs.contains(event.subjectID)
            || event.relatedID.map(taskIDs.contains) == true
    }
}
