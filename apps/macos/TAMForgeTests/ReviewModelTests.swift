import Foundation
import XCTest

@MainActor
final class ReviewModelTests: XCTestCase {
    func testOpeningLoadsTheReviewAndRequestIsOfferedOnlyWhenNothingIsQueued() async {
        let api = FakeReviewAPI(review: review(status: "not_requested"))
        let model = ReviewModel(activityID: 41, api: api)

        await model.open()
        XCTAssertTrue(model.canRequest)
        XCTAssertFalse(model.isPending)

        api.review = review(status: "queued")
        await model.request()

        XCTAssertEqual(api.calls, ["review:41", "request:41"])
        XCTAssertFalse(model.canRequest)
        XCTAssertTrue(model.isPending)
    }

    func testAReadyReviewCarriesScoresFindingsAndTheEvidenceStatus() async {
        let api = FakeReviewAPI(review: review(status: "ready"))
        let model = ReviewModel(activityID: 41, api: api)

        await model.open()

        XCTAssertEqual(model.review?.verdict, "Correct, weak close.")
        XCTAssertEqual(model.review?.dimensions.first?.score, Decimal(string: "3.5"))
        XCTAssertEqual(model.review?.corrections.count, 2)
        XCTAssertEqual(model.review?.evidenceStatus, "recorded")
        XCTAssertFalse(model.canRequest)
    }

    func testProblemsBecomeMessages() async {
        let api = FakeReviewAPI(review: review(status: "not_requested"))
        api.failure = .conflict
        let model = ReviewModel(activityID: 41, api: api)

        await model.open()

        XCTAssertEqual(model.errorMessage, ReviewAPIError.conflict.message)
        XCTAssertNil(model.review)
    }

    func testTheLiveClientDecodesTheServerShapeAndTranslatesProblems() async throws {
        let fixture = URLProtocolFixture()
        fixture.enqueue(.response(statusCode: 200, body: Data("""
        {"activity_id": 41, "status": "ready", "failure_category": null, "review_id": 3, "attempt_id": 11,
         "rubric_slug": "tam_block", "rubric_version": "seed-v1", "model": "claude-fable-5-1",
         "verdict": "Correct.", "dimensions": [{"slug": "correctness", "name": "Correctness", "score": "3.5",
         "maximum": "4", "rationale": "Right.", "evidence": "200"}], "strengths": [{"statement": "a", "instruction": ""}],
         "corrections": [{"statement": "b", "instruction": "c"}], "next_practice": "again",
         "evidence_status": "recorded", "evidence_event_ids": [9], "created_at": "2026-09-16T10:00:00Z"}
        """.utf8)))
        let api = LiveReviewAPI(transport: NativeAPITransport(
            baseURL: URL(string: "https://api.example.test")!, session: fixture.session()
        ))

        let review = try await api.review(activityID: 41)

        XCTAssertTrue(review.isReady)
        XCTAssertEqual(review.dimensions.first?.maximum, 4)
        XCTAssertEqual(fixture.requests.first?.url?.path, "/api/v1/activities/41/review")
        XCTAssertEqual(LiveReviewAPI.translate(.problem(problem(status: 409))), .conflict)
        XCTAssertEqual(LiveReviewAPI.translate(.problem(problem(status: 503))), .unavailable)
        XCTAssertEqual(LiveReviewAPI.translate(.decodingResponse), .invalidResponse)
    }

    private func problem(status: Int) -> APIProblem {
        APIProblem(type: nil, title: nil, status: status, detail: nil, instance: nil, code: nil)
    }

    private func review(status: String) -> ActivityReview {
        let ready = status == "ready"
        return ActivityReview(
            activityID: 41, status: status, failureCategory: nil, reviewID: ready ? 3 : nil,
            attemptID: ready ? 11 : nil, rubricSlug: ready ? "tam_block" : nil,
            rubricVersion: ready ? "seed-v1" : nil, model: ready ? "claude-fable-5-1" : nil,
            verdict: ready ? "Correct, weak close." : nil,
            dimensions: ready ? [ReviewedDimension(
                slug: "correctness", name: "Correctness", score: Decimal(string: "3.5")!, maximum: 4,
                rationale: "Right idea.", evidence: "200 means accepted"
            )] : [],
            strengths: ready ? [ReviewFinding(statement: "a", instruction: ""), ReviewFinding(statement: "b", instruction: "")] : [],
            corrections: ready ? [ReviewFinding(statement: "c", instruction: "x"), ReviewFinding(statement: "d", instruction: "y")] : [],
            nextPractice: ready ? "again" : nil, evidenceStatus: ready ? "recorded" : nil,
            evidenceEventIDs: ready ? [9, 10] : [], createdAt: ready ? Date(timeIntervalSince1970: 0) : nil
        )
    }
}

@MainActor
private final class FakeReviewAPI: ReviewAPI {
    var review: ActivityReview
    var failure: ReviewAPIError?
    private(set) var calls: [String] = []

    init(review: ActivityReview) {
        self.review = review
    }

    func review(activityID: Int) async throws -> ActivityReview {
        calls.append("review:\(activityID)")
        if let failure { throw failure }
        return review
    }

    func requestReview(activityID: Int) async throws -> ActivityReview {
        calls.append("request:\(activityID)")
        if let failure { throw failure }
        return review
    }
}
