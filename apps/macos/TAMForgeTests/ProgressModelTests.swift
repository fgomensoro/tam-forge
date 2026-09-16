import Foundation
import XCTest

@MainActor
final class ProgressModelTests: XCTestCase {
    private let payload = """
    {"skills": [
       {"slug": "a", "name": "A", "baseline": "2", "month_one_target": "2.5", "final_target": "3",
        "latest_level": "2.750", "confidence": "medium", "trend": "up",
        "points": [{"snapshot_date": "2026-09-16", "estimated_level": "2.750"}]},
       {"slug": "b", "name": "B", "baseline": "1", "month_one_target": "2", "final_target": "3",
        "latest_level": null, "confidence": null, "trend": null, "points": []}],
     "weeks": [{"week_start": "2026-09-14", "planned_minutes": 600, "focused_minutes": 420, "study_days": 5, "closed_days": 3}],
     "assessments": [{"review_id": 3, "activity_id": 41, "task_stable_id": "p0-w00-d00-warmup", "local_date": "2026-09-16",
       "rubric_slug": "tam_block", "block": "tam_case", "average_score": "3.00", "dimension_count": 6, "verdict": "Correct.", "reviewed_at": "2026-09-16T12:00:00Z"}],
     "assessment_days": [{"study_day_id": 6, "local_date": "2026-08-29", "day_status": "closed", "planned_minutes": 120, "focused_minutes": 110,
       "contracts": [{"activity_id": 61, "task_stable_id": "m1-w1-d06-sql", "contract_type": "saturday_sql", "exercise_type": "sql_no_ai_timed_assessment",
         "activity_state": "feedback_ready", "result": "scored", "average_score": "3.00", "dimension_count": 6, "review_id": 9, "evidence_event_ids": [1]},
         {"activity_id": 62, "task_stable_id": "m1-w1-d06-case", "contract_type": "saturday_case", "exercise_type": null, "activity_state": "planned",
         "result": "not_attempted", "average_score": null, "dimension_count": 0, "review_id": null, "evidence_event_ids": []}],
       "scored_contracts": 1, "average_score": "3.00"}],
     "interviews": [{"interview_id": 2, "company": "Coframe", "role": "TAM", "stage": "screen",
       "starts_at": "2026-09-10T17:00:00Z", "status": "completed", "recording_count": 1}]}
    """

    func testTheReportDecodesDecimalsAndNullsAndSummarisesSkills() async throws {
        let report = try NativeJSONCodec.decode(ProgressReport.self, from: Data(payload.utf8))
        XCTAssertEqual(report.skills.count, 2)
        XCTAssertEqual(report.skills[0].latestLevel, Decimal(string: "2.750"))
        XCTAssertNil(report.skills[1].latestLevel)
        XCTAssertEqual(report.skills[0].progressFraction, 0.75, accuracy: 0.001)
        XCTAssertEqual(report.skills[1].progressFraction, 0)
        XCTAssertEqual(report.weeks[0].completion, 0.7, accuracy: 0.001)
        XCTAssertEqual(report.assessments[0].averageScore, Decimal(string: "3.00"))
        XCTAssertEqual(report.interviews[0].company, "Coframe")
        XCTAssertEqual(report.assessments[0].block, "tam_case")
        XCTAssertEqual(report.assessmentDays[0].averageScore, Decimal(string: "3.00"))
        XCTAssertEqual(report.assessmentDays[0].contracts.map(\.result), ["scored", "not_attempted"])
        XCTAssertNil(report.assessmentDays[0].contracts[1].averageScore)

        let api = FakeProgressAPI(report: report)
        let model = ProgressModel(api: api)
        await model.load()
        XCTAssertTrue(model.hasLoaded)
        XCTAssertEqual(model.skillsOnTarget, 1)
        XCTAssertEqual(model.recentWeeks.map(\.weekStart), ["2026-09-14"])
        XCTAssertNil(model.errorMessage)
    }

    func testProblemsBecomeMessagesAndKeepTheLastReport() async throws {
        let report = try NativeJSONCodec.decode(ProgressReport.self, from: Data(payload.utf8))
        let api = FakeProgressAPI(report: report)
        let model = ProgressModel(api: api)
        await model.load()
        api.failure = .unavailable
        await model.load()
        XCTAssertEqual(model.errorMessage, ProgressAPIError.unavailable.message)
        XCTAssertEqual(model.report, report)
    }
}

@MainActor
private final class FakeProgressAPI: ProgressAPI {
    var report: ProgressReport
    var failure: ProgressAPIError?

    init(report: ProgressReport) { self.report = report }

    func read() async throws -> ProgressReport {
        if let failure { throw failure }
        return report
    }
}
