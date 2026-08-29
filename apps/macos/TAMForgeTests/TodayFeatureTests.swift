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
        XCTAssertEqual(fetchCount, 2)

        await model.retryClose()

        XCTAssertEqual(model.closeState, .closed(TodayFixture.closed))
        let requests = await client.closeRequests
        XCTAssertEqual(requests.map(\.idempotencyKey), [
            "daily-close-2026-08-27-stable",
            "daily-close-2026-08-27-stable",
        ])
    }
}

private enum TodayFixture {
    static let snapshot = try! JSONDecoder().decode(TodaySnapshot.self, from: Data("""
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
    """.utf8))

    static let closed = TodayDailyCloseResponse(
        dailyCloseID: 9,
        studyDayID: 8,
        dayStatus: "closed",
        closedAt: "2026-08-27T23:00:00Z",
        consequence: "none",
        replayed: false
    )
}

private actor TodayClientFixture: TodayServicing {
    struct CloseRequest: Equatable, Sendable {
        let idempotencyKey: String
    }

    enum CloseResult: Sendable {
        case success(TodayDailyCloseResponse)
        case failure(URLError)
    }

    private let snapshot: TodaySnapshot
    private var results: [CloseResult]
    private(set) var fetchCount = 0
    private(set) var closeRequests: [CloseRequest] = []

    init(snapshot: TodaySnapshot, closeResults: [CloseResult]) {
        self.snapshot = snapshot
        results = closeResults
    }

    func fetchToday(localDate: String) async throws -> TodaySnapshot {
        fetchCount += 1
        return snapshot
    }

    func closeToday(
        localDate: String,
        command: TodayDailyCloseCommand,
        idempotencyKey: String
    ) async throws -> TodayDailyCloseResponse {
        closeRequests.append(.init(idempotencyKey: idempotencyKey))
        switch results.removeFirst() {
        case let .success(response): return response
        case let .failure(error): throw error
        }
    }
}
