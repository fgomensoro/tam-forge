import Foundation
import XCTest

final class NativeParityFixtureTests: XCTestCase {
    func testSharedFixtureDecodesThroughGeneratedNativeContracts() throws {
        let fixture = try sharedFixture()
        let responses = try XCTUnwrap(fixture["responses"] as? [String: Any])

        let today = try NativeJSONCodec.decode(
            Components.Schemas.TodayResponse.self,
            from: responseData("today", in: responses)
        )
        let activity = try NativeJSONCodec.decode(
            Components.Schemas.ActivityDetailResponse.self,
            from: responseData("activity", in: responses)
        )
        let notifications = try NativeJSONCodec.decode(
            Components.Schemas.NotificationPage.self,
            from: responseData("notifications", in: responses)
        )
        let skills = try NativeJSONCodec.decode(
            Components.Schemas.SkillListResponse.self,
            from: responseData("skills", in: responses)
        )
        let portfolio = try NativeJSONCodec.decode(
            Components.Schemas.PortfolioHistoryResponse.self,
            from: responseData("portfolio", in: responses)
        )

        let reading = try XCTUnwrap(today.tasks.first(where: { $0.block.rawValue == "technical_learning" }))
        XCTAssertEqual(today.localDate, "2026-08-24")
        XCTAssertEqual(today.totalPlannedMinutes, 240)
        XCTAssertEqual(reading.timeboxMinutes, 45)
        XCTAssertEqual(reading.activityId, activity.id)
        XCTAssertEqual(reading.objective, activity.taskContract.objective)
        XCTAssertEqual(notifications.items.first?.notificationType.rawValue, "feedback_ready")
        XCTAssertNil(notifications.items.first?.readAt)
        XCTAssertTrue(skills.items.contains(where: { $0.latestSnapshot == nil }))
        XCTAssertEqual(skills.items.first?.latestSnapshot?.value1.manifest.count, 5)
        XCTAssertEqual(skills.items.first?.latestSnapshot?.value1.qualifyingEventCount, 3)
        XCTAssertEqual(portfolio.items.first?.totalScore, "14.000")
    }

    func testSharedFixtureCarriesOneExactIndependentJourney() throws {
        let fixture = try sharedFixture()
        let journey = try XCTUnwrap(fixture["journey"] as? [String: Any])
        XCTAssertEqual(
            journey["activity_states"] as? [String],
            ["ready", "active", "paused", "active", "output_committed", "self_review_complete"]
        )
        let output = try XCTUnwrap(journey["output"] as? [String: Any])
        XCTAssertEqual(output["kind"] as? String, "reading")
        XCTAssertEqual(output["key_ideas"] as? [String], [
            "HTTP requests carry explicit methods and resource paths.",
            "Status codes separate client and server failure classes.",
            "A TAM connects protocol evidence to customer impact.",
        ])
        let review = try XCTUnwrap(journey["self_review"] as? [String: Any])
        XCTAssertEqual(review["self_score"] as? Int, 3)
    }

    private func sharedFixture() throws -> [String: Any] {
        let url = try XCTUnwrap(
            Bundle(for: Self.self).url(
                forResource: "foundation-journey-v1",
                withExtension: "json"
            )
        )
        let value = try JSONSerialization.jsonObject(with: Data(contentsOf: url))
        return try XCTUnwrap(value as? [String: Any])
    }

    private func responseData(_ name: String, in responses: [String: Any]) throws -> Data {
        let value = try XCTUnwrap(responses[name])
        return try JSONSerialization.data(withJSONObject: value, options: [.sortedKeys])
    }
}
