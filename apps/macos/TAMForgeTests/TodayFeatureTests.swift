import Foundation
import XCTest

@MainActor
final class TodayFeatureTests: XCTestCase {
    func testLocalDateUsesSuppliedTimezoneInsteadOfUTC() {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "America/Los_Angeles")!
        let instant = ISO8601DateFormatter().date(from: "2026-08-28T06:30:00Z")!

        XCTAssertEqual(TodayLocalDate.string(for: instant, calendar: calendar), "2026-08-27")
    }

    func testInterviewTimeUsesTodayTimezone() {
        XCTAssertEqual(
            TodayDateTime.string(
                "2026-08-27T18:00:00Z",
                timezoneIdentifier: "America/Los_Angeles",
                locale: Locale(identifier: "en_US_POSIX")
            ),
            "Thu, Aug 27, 2026, 11:00 AM"
        )
    }

    func testGeneratedInterviewFractionalTimestampUsesTodayTimezone() throws {
        var payload = try XCTUnwrap(JSONSerialization.jsonObject(with: TodayFixture.wirePayload) as? [String: Any])
        payload["interviews"] = [[
            "id": 9, "company": "Example", "role": "TAM", "stage": "Technical",
            "starts_at": "2026-08-27T18:00:00.125Z", "expected_duration_minutes": 60,
            "privacy_permission_code": "permission_not_requested"
        ]]
        let wire = try NativeJSONCodec.decode(Components.Schemas.TodayResponse.self,
                                             from: JSONSerialization.data(withJSONObject: payload))
        let interview = try XCTUnwrap(TodaySnapshot(wire: wire).interviews.first)

        XCTAssertEqual(TodayDateTime.string(interview.startsAt, timezoneIdentifier: "America/Los_Angeles",
                                            locale: Locale(identifier: "en_US_POSIX")),
                       "Thu, Aug 27, 2026, 11:00 AM")
    }

    func testGeneratedTodayResponseMapsToLocalDomain() throws {
        let wire = try NativeJSONCodec.decode(
            Components.Schemas.TodayResponse.self,
            from: TodayFixture.wirePayload
        )

        let snapshot = TodaySnapshot(wire: wire)

        XCTAssertEqual(snapshot.localDate, "2026-08-27")
        XCTAssertEqual(snapshot.dayID, 8)
        XCTAssertEqual(snapshot.tasks.first?.stableID, "case-1")
        XCTAssertEqual(snapshot.tasks.first?.state, "self_review_complete")
        XCTAssertEqual(snapshot.primaryContinue?.kind, "close_day")
        XCTAssertEqual(snapshot.sourceUpdatedAt, "2026-08-27T20:00:00.000Z")
    }

    func testGeneratedDailyCloseCommandIncludesRequiredNullUnfinishedRequirement() throws {
        let command = try TodayDailyCloseDraft(
            strongestOutput: "Clear rollback recommendation.",
            repeatedMistake: "Customer impact came too late.",
            unfinishedClassification: .none,
            unfinishedRequirement: nil,
            evidenceConfirmed: true
        ).command(for: TodayFixture.snapshot)

        let data = try NativeJSONCodec.encode(
            Components.Schemas.DailyCloseCommand(domain: command),
            insertingRequiredNulls: ["unfinished_requirement"]
        )
        let payload = try XCTUnwrap(try JSONSerialization.jsonObject(with: data) as? [String: Any])

        XCTAssertTrue(payload.keys.contains("unfinished_requirement"))
        XCTAssertTrue(payload["unfinished_requirement"] is NSNull)
    }

    func testGeneratedDailyCloseResponseMapsToLocalDomain() throws {
        let wire = try NativeJSONCodec.decode(
            Components.Schemas.DailyCloseResponse.self,
            from: Data("""
            {"daily_close_id":9,"study_day_id":8,"day_status":"closed","closed_at":"2026-08-27T23:00:00Z","consequence":"none","replayed":false}
            """.utf8)
        )

        let response = TodayDailyCloseResponse(wire: wire)

        XCTAssertEqual(response.dailyCloseID, 9)
        XCTAssertEqual(response.dayStatus, "closed")
        XCTAssertEqual(response.closedAt, "2026-08-27T23:00:00.000Z")
    }

    func testContinueDestinationPreservesServerActionSemantics() {
        XCTAssertEqual(
            TodayDestination(action: .init(kind: "complete_self_review", targetID: 41, label: "Review", allowedAIRole: "none")),
            .some(.activity(id: 41, focus: .selfReview))
        )
        XCTAssertEqual(
            TodayDestination(action: .init(kind: "review_feedback", targetID: 42, label: "Feedback", allowedAIRole: "reviewer")),
            .some(.evidence(activityID: 42))
        )
        XCTAssertEqual(
            TodayDestination(action: .init(kind: "close_day", targetID: 43, label: "Close", allowedAIRole: "none")),
            .some(.dailyClose(activityID: 43))
        )
    }

    func testTaskOpenDestinationUsesActivityFocusOrDailyClose() {
        let workspaceTask = TodayTask(
            activityID: 41,
            roadmapOrder: 1,
            stableID: "case-1",
            block: "tam_case",
            state: "ready",
            objective: "Solve a customer incident.",
            timeboxMinutes: 60,
            sourceReferences: [],
            requiredOutput: [],
            passCriteria: [],
            allowedAIRole: "none",
            evidenceRequirements: [],
            required: true,
            optimisticVersion: 1
        )
        let reviewTask = TodayTask(
            activityID: 42,
            roadmapOrder: 2,
            stableID: "review-1",
            block: "communication_spoken",
            state: "output_committed",
            objective: "Review the saved output.",
            timeboxMinutes: 30,
            sourceReferences: [],
            requiredOutput: [],
            passCriteria: [],
            allowedAIRole: "none",
            evidenceRequirements: [],
            required: true,
            optimisticVersion: 1
        )

        XCTAssertEqual(TodayDestination(task: workspaceTask), .activity(id: 41, focus: .workspace))
        XCTAssertEqual(TodayDestination(task: reviewTask), .activity(id: 42, focus: .selfReview))
        XCTAssertEqual(TodayDestination(task: TodayFixture.snapshot.tasks[1]), .dailyClose(activityID: 70))
    }

    func testLoadRecomputesLocalDateAfterRollover() async {
        let clock = TodayClock(Date(timeIntervalSince1970: 1_777_800_000))
        let later = clock.value.addingTimeInterval(36 * 60 * 60)
        let client = TodayClientFixture(snapshot: TodayFixture.snapshot, closeResults: [])
        let model = TodayViewModel(client: client, now: { clock.value })

        await model.load()
        clock.value = later
        await model.retry()

        let dates = await client.fetchDates
        XCTAssertEqual(dates, [TodayLocalDate.string(for: clock.initialValue), TodayLocalDate.string(for: later)])
    }

    func testLateEarlierDateLoadCannotReplaceNewerDayAfterRollover() async {
        let clock = TodayClock(Date(timeIntervalSince1970: 1_777_800_000))
        let firstDate = TodayLocalDate.string(for: clock.value)
        let later = clock.value.addingTimeInterval(36 * 60 * 60)
        let secondDate = TodayLocalDate.string(for: later)
        let client = RolloverTodayClient()
        let model = TodayViewModel(client: client, now: { clock.value })

        let firstLoad = Task { await model.load() }
        await client.waitForRequest(firstDate)

        clock.value = later
        let secondLoad = Task { await model.load() }
        await client.waitForRequest(secondDate)
        await client.respond(to: secondDate, with: TodayFixture.snapshot(localDate: secondDate))
        await secondLoad.value

        await client.respond(to: firstDate, with: TodayFixture.snapshot(localDate: firstDate))
        await firstLoad.value

        XCTAssertEqual(model.snapshot?.localDate, secondDate)
    }

    func testTodayInvalidatesInterviewCorrectionAndFeedbackEventsOutsideTaskIDs() {
        let events = [
            StatusEvent(id: 1, eventType: "interview.scheduled", aggregateType: "interview", aggregateID: 100, subjectID: 100, relatedID: nil, occurredAt: "2026-08-27T20:00:00Z"),
            StatusEvent(id: 2, eventType: "correction.due", aggregateType: "correction", aggregateID: 101, subjectID: 101, relatedID: nil, occurredAt: "2026-08-27T20:00:00Z"),
            StatusEvent(id: 3, eventType: "feedback.ready", aggregateType: "feedback", aggregateID: 102, subjectID: 102, relatedID: nil, occurredAt: "2026-08-27T20:00:00Z"),
        ]

        XCTAssertTrue(events.allSatisfy { TodayStatusInvalidation.affects(snapshot: TodayFixture.snapshot, event: $0) })
    }

    func testDailyCloseUsesOnlyServerCompletedActivityEvidence() throws {
        let command = try TodayDailyCloseDraft(
            strongestOutput: "Clear rollback recommendation.",
            repeatedMistake: "Customer impact came too late.",
            unfinishedClassification: .none,
            unfinishedRequirement: nil,
            evidenceConfirmed: true
        ).command(for: TodayFixture.snapshot)

        XCTAssertEqual(command.evidenceManifest.activityIDs, [41])
        XCTAssertEqual(command.unfinishedClassification, .none)
        XCTAssertNil(command.unfinishedRequirement)
    }

    func testIndeterminateDailyCloseReconcilesThenRetainsIdempotencyKeyForRetry() async {
        let client = TodayClientFixture(
            snapshot: TodayFixture.snapshot,
            closeResults: [.failure(URLError(.networkConnectionLost)), .success(TodayFixture.closed)]
        )
        let model = TodayViewModel(
            client: client,
            now: { Date(timeIntervalSince1970: 0) },
            idempotencyKey: { "daily-close-2026-08-27-stable" }
        )
        await model.load()
        await model.close(
            TodayDailyCloseDraft(
                strongestOutput: "Clear rollback recommendation.",
                repeatedMistake: "Customer impact came too late.",
                unfinishedClassification: .none,
                unfinishedRequirement: nil,
                evidenceConfirmed: true
            )
        )

        XCTAssertEqual(model.closeState, .retryRequired)
        let fetchCount = await client.fetchCount
        XCTAssertEqual(fetchCount, 3)

        await model.retryClose()

        XCTAssertEqual(model.closeState, .closed(TodayFixture.closed))
        let requests = await client.closeRequests
        XCTAssertEqual(requests.map(\.idempotencyKey), [
            "daily-close-2026-08-27-stable",
            "daily-close-2026-08-27-stable",
        ])
        XCTAssertEqual(requests.map(\.localDate), ["2026-08-27", "2026-08-27"])
    }

    func testFailedOldDayCloseStaysRetriableWhenNewDayIsClosed() async throws {
        let clock = TodayClock(Date(timeIntervalSince1970: 1_777_800_000))
        let oldDate = TodayLocalDate.string(for: clock.value)
        let newDate = TodayLocalDate.string(for: clock.value.addingTimeInterval(36 * 60 * 60))
        let client = RolloverCloseTodayClient(snapshots: [
            oldDate: TodayFixture.snapshot(localDate: oldDate),
            newDate: TodayFixture.snapshot(localDate: newDate, dayStatus: "closed"),
        ])
        let model = TodayViewModel(
            client: client,
            now: { clock.value },
            idempotencyKey: { "daily-close-old-day-stable" }
        )
        await model.load()
        clock.value = clock.value.addingTimeInterval(36 * 60 * 60)

        await model.close(validDailyCloseDraft())

        XCTAssertEqual(model.closeState, .retryRequired)
        await model.retryClose()

        let requests = await client.closeRequests
        XCTAssertEqual(requests.map(\.localDate), [oldDate, oldDate])
        XCTAssertEqual(requests.map(\.idempotencyKey), ["daily-close-old-day-stable", "daily-close-old-day-stable"])
    }

    private func validDailyCloseDraft() -> TodayDailyCloseDraft {
        .init(
            strongestOutput: "Clear rollback recommendation.",
            repeatedMistake: "Customer impact came too late.",
            unfinishedClassification: .none,
            unfinishedRequirement: nil,
            evidenceConfirmed: true
        )
    }
}

private enum TodayFixture {
    static let wirePayload = Data("""
    {
      "local_date":"2026-08-27","timezone":"America/Los_Angeles","day_id":8,
      "day_type":"weekday","day_status":"in_progress",
      "roadmap":{"version_id":2,"version_key":"month-1-v1","version_number":1,"month":1,"week":1,"day":4},
      "total_planned_minutes":240,
      "time_policy":{"target_minutes":240,"acceptable_minimum":225,"hard_stop_minutes":255,"focused_minutes":65,"hard_stop_recommended":false},
      "required_blocks":[],
      "tasks":[
        {"activity_id":41,"roadmap_order":1,"stable_id":"case-1","block":"tam_case","state":"self_review_complete","objective":"Solve a customer incident.","timebox_minutes":60,"source_references":[],"required_output":["Incident update"],"pass_criteria":["Impact first"],"allowed_ai_role":"none","evidence_requirements":["Independent answer"],"required":true,"optimistic_version":1},
        {"activity_id":70,"roadmap_order":2,"stable_id":"daily-close","block":"daily_close","state":"ready","objective":"Close day.","timebox_minutes":15,"source_references":[],"required_output":[],"pass_criteria":[],"allowed_ai_role":"none","evidence_requirements":[],"required":true,"optimistic_version":1}
      ],
      "corrections":[],"interviews":[],"awaiting_self_reviews":[],"analyses":[],
      "primary_continue":{"kind":"close_day","target_id":70,"label":"Close study day","allowed_ai_role":"none"},
      "source_updated_at":"2026-08-27T20:00:00Z","read_model_version":"redacted-v1","etag":"\\\"redacted-v1\\\""
    }
    """.utf8)

    static let snapshot = try! JSONDecoder().decode(TodaySnapshot.self, from: wirePayload)

    static let closed = TodayDailyCloseResponse(
        dailyCloseID: 9,
        studyDayID: 8,
        dayStatus: "closed",
        closedAt: "2026-08-27T23:00:00Z",
        consequence: "none",
        replayed: false
    )

    static func snapshot(localDate: String, dayStatus: String? = nil) -> TodaySnapshot {
        let base = Self.snapshot
        return .init(
            localDate: localDate,
            timezone: base.timezone,
            dayID: base.dayID,
            dayType: base.dayType,
            dayStatus: dayStatus ?? base.dayStatus,
            roadmap: base.roadmap,
            totalPlannedMinutes: base.totalPlannedMinutes,
            timePolicy: base.timePolicy,
            requiredBlocks: base.requiredBlocks,
            tasks: base.tasks,
            corrections: base.corrections,
            interviews: base.interviews,
            awaitingSelfReviews: base.awaitingSelfReviews,
            analyses: base.analyses,
            primaryContinue: base.primaryContinue,
            sourceUpdatedAt: base.sourceUpdatedAt,
            readModelVersion: base.readModelVersion,
            etag: base.etag
        )
    }
}

private actor TodayClientFixture: TodayServicing {
    struct CloseRequest: Equatable, Sendable {
        let localDate: String
        let idempotencyKey: String
    }

    enum CloseResult: Sendable {
        case success(TodayDailyCloseResponse)
        case failure(URLError)
    }

    private let snapshot: TodaySnapshot
    private var results: [CloseResult]
    private(set) var fetchCount = 0
    private(set) var fetchDates: [String] = []
    private(set) var closeRequests: [CloseRequest] = []

    init(snapshot: TodaySnapshot, closeResults: [CloseResult]) {
        self.snapshot = snapshot
        results = closeResults
    }

    func fetchToday(localDate: String) async throws -> TodaySnapshot {
        fetchCount += 1
        fetchDates.append(localDate)
        return snapshot
    }

    func closeToday(
        localDate: String,
        command: TodayDailyCloseCommand,
        idempotencyKey: String
    ) async throws -> TodayDailyCloseResponse {
        closeRequests.append(.init(localDate: localDate, idempotencyKey: idempotencyKey))
        switch results.removeFirst() {
        case let .success(response): return response
        case let .failure(error): throw error
        }
    }
}

private final class TodayClock: @unchecked Sendable {
    private let lock = NSLock()
    let initialValue: Date
    private var date: Date

    init(_ value: Date) {
        initialValue = value
        date = value
    }

    var value: Date {
        get { lock.withLock { date } }
        set { lock.withLock { date = newValue } }
    }
}

private actor RolloverTodayClient: TodayServicing {
    private var responses: [String: CheckedContinuation<TodaySnapshot, Error>] = [:]
    private var requestWaiters: [String: CheckedContinuation<Void, Never>] = [:]

    func fetchToday(localDate: String) async throws -> TodaySnapshot {
        requestWaiters.removeValue(forKey: localDate)?.resume()
        return try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<TodaySnapshot, Error>) in
            responses[localDate] = continuation
        }
    }

    func closeToday(
        localDate _: String,
        command _: TodayDailyCloseCommand,
        idempotencyKey _: String
    ) async throws -> TodayDailyCloseResponse {
        throw CancellationError()
    }

    func waitForRequest(_ localDate: String) async {
        guard responses[localDate] == nil else { return }
        await withCheckedContinuation { requestWaiters[localDate] = $0 }
    }

    func respond(to localDate: String, with snapshot: TodaySnapshot) {
        responses.removeValue(forKey: localDate)?.resume(returning: snapshot)
    }
}

private struct RolloverCloseRequest: Equatable, Sendable {
    let localDate: String
    let idempotencyKey: String
}

private actor RolloverCloseTodayClient: TodayServicing {
    private let snapshots: [String: TodaySnapshot]
    private(set) var closeRequests: [RolloverCloseRequest] = []

    init(snapshots: [String: TodaySnapshot]) {
        self.snapshots = snapshots
    }

    func fetchToday(localDate: String) async throws -> TodaySnapshot {
        guard let snapshot = snapshots[localDate] else { throw URLError(.badURL) }
        return snapshot
    }

    func closeToday(
        localDate: String,
        command _: TodayDailyCloseCommand,
        idempotencyKey: String
    ) async throws -> TodayDailyCloseResponse {
        closeRequests.append(.init(localDate: localDate, idempotencyKey: idempotencyKey))
        throw URLError(.networkConnectionLost)
    }
}
