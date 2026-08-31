import Foundation
import XCTest

@MainActor
final class NativeEvidenceAdapterTests: XCTestCase {
    func testAllReadEndpointsUseValidatedBoundedBearerRequestsAndMapGeneratedProjections() async throws {
        let fixture = URLProtocolFixture()
        fixture.enqueue(.response(statusCode: 200, body: skillsBody(snapshot: nil)))
        fixture.enqueue(.response(statusCode: 200, body: skillBody(snapshot: snapshotBody())))
        fixture.enqueue(.response(statusCode: 200, body: evidencePageBody(nextCursor: nil)))
        fixture.enqueue(.response(statusCode: 200, body: evidencePageBody(nextCursor: 39, eventID: 39)))
        fixture.enqueue(.response(statusCode: 200, body: portfolioPageBody(nextCursor: nil)))
        let recorder = EvidenceDiagnosticRecorder()
        let api = LiveEvidenceAPI(transport: NativeAPITransport(
            baseURL: URL(string: "https://api.example.test")!,
            bearerToken: { "evidence-test-token" },
            session: fixture.session(),
            diagnostics: { recorder.record($0) }
        ))

        let skills = try await api.listSkills()
        let detail = try await api.fetchSkill(slug: "incident_communication")
        let skillPage = try await api.fetchSkillEvidence(slug: "incident_communication", cursor: nil)
        let activityPage = try await api.fetchActivityEvidence(activityID: 41, cursor: 40)
        let portfolio = try await api.fetchPortfolioHistory(cursor: nil)

        XCTAssertNil(skills[0].snapshot, "A null snapshot is not a zero score")
        XCTAssertEqual(detail.snapshot?.estimatedLevel, "3.125")
        XCTAssertEqual(detail.snapshot?.snapshotDate, "2026-08-31")
        XCTAssertEqual(detail.snapshot?.lastStrongEvidenceDate, "2026-08-30")
        XCTAssertEqual(detail.snapshot?.manifest[0].usedWeight, "0.125")
        XCTAssertEqual(detail.snapshot?.confidenceBasis["unknown_basis"], .object([
            "items": .array([.integer(1), .object(["deep": .string("kept")])]),
        ]))
        XCTAssertEqual(detail.snapshot?.trendBasis["unknown_signal"], .array([.string("raw"), .boolean(true)]))
        XCTAssertEqual(skillPage.nextCursor, nil)
        XCTAssertEqual(activityPage.nextCursor, 39)
        XCTAssertEqual(activityPage.items[0].attemptID, nil)
        XCTAssertEqual(activityPage.items[0].performanceScore, "3.750")
        XCTAssertEqual(activityPage.items[0].effectiveWeight, "0.875")
        XCTAssertEqual(
            activityPage.items[0].rawDimensionScores["nested"],
            .object(["items": .array([.integer(2), .object(["value": .string("kept")])])])
        )
        XCTAssertEqual(portfolio.items[0].totalScore, "16.500")
        XCTAssertEqual(portfolio.items[0].components[0].score, "2.250")

        let requests = fixture.requests
        XCTAssertEqual(requests.map(\.httpMethod), Array(repeating: "GET", count: 5))
        XCTAssertTrue(requests.allSatisfy { $0.httpBody == nil && $0.httpBodyStream == nil })
        XCTAssertEqual(requests[0].url?.path, "/api/v1/skills")
        XCTAssertEqual(requests[1].url?.path, "/api/v1/skills/incident_communication")
        XCTAssertEqual(requests[2].url?.path, "/api/v1/skills/incident_communication/evidence")
        XCTAssertEqual(requests[2].url?.query, "limit=20")
        XCTAssertEqual(requests[3].url?.path, "/api/v1/activities/41/evidence")
        XCTAssertEqual(requests[3].url?.query, "limit=20&cursor=40")
        XCTAssertEqual(requests[4].url?.path, "/api/v1/portfolio-judgment")
        XCTAssertEqual(requests[4].url?.query, "limit=20")
        XCTAssertTrue(requests.allSatisfy { $0.value(forHTTPHeaderField: "Authorization") == "Bearer evidence-test-token" })
        XCTAssertEqual(NativeAPIResponseLimit.standard.bytes, 2 * 1024 * 1024)
        XCTAssertFalse(recorder.text.contains("evidence-test-token"))
        XCTAssertFalse(recorder.text.contains("3.750"))
    }

    func testRejectsInvalidSlugAndNonpositiveActivityWithoutRequests() async throws {
        let fixture = URLProtocolFixture()
        let api = LiveEvidenceAPI(transport: transport(fixture))

        await assertInvalidRequest { _ = try await api.fetchSkill(slug: "bad/path") }
        await assertInvalidRequest { _ = try await api.fetchSkillEvidence(slug: "Bad", cursor: nil) }
        await assertInvalidRequest { _ = try await api.fetchActivityEvidence(activityID: 0, cursor: nil) }
        await assertInvalidRequest { _ = try await api.fetchActivityEvidence(activityID: 41, cursor: 0) }

        XCTAssertTrue(fixture.requests.isEmpty)
    }

    func testRejectsMalformedDecimalAndMapsGeneratedDecodeFailureSafely() async throws {
        let fixture = URLProtocolFixture()
        fixture.enqueue(.response(statusCode: 200, body: skillsBody(snapshot: snapshotBody(estimatedLevel: "1e3"))))
        fixture.enqueue(.response(statusCode: 200, body: Data(#"{"items":[],"next_cursor":null,"unexpected":true}"#.utf8)))
        let api = LiveEvidenceAPI(transport: transport(fixture))

        await assertInvalidResponse { _ = try await api.listSkills() }
        await assertInvalidResponse { _ = try await api.fetchPortfolioHistory(cursor: nil) }
    }

    func testRejectsScoresOutsideTheirDeclaredScalesAndIncompletePortfolioComponents() async {
        let fixture = URLProtocolFixture()
        fixture.enqueue(.response(statusCode: 200, body: skillsBody(snapshot: snapshotBody(estimatedLevel: "4.001"))))
        fixture.enqueue(.response(statusCode: 200, body: replacing(portfolioPageBody(nextCursor: nil), "16.500", "20.001")))
        fixture.enqueue(.response(statusCode: 200, body: portfolioPageMissingLastComponent()))
        let api = LiveEvidenceAPI(transport: transport(fixture))

        await assertInvalidResponse { _ = try await api.listSkills() }
        await assertInvalidResponse { _ = try await api.fetchPortfolioHistory(cursor: nil) }
        await assertInvalidResponse { _ = try await api.fetchPortfolioHistory(cursor: nil) }
    }

    func testMapsUnauthorizedAndSafeProblemStatusesWithoutProblemDetail() async throws {
        let fixture = URLProtocolFixture()
        fixture.enqueue(.response(statusCode: 401, body: problemBody(status: 401, detail: "secret response detail")))
        fixture.enqueue(.response(statusCode: 422, body: problemBody(status: 422, detail: "secret response detail")))
        let api = LiveEvidenceAPI(transport: transport(fixture))

        do {
            _ = try await api.listSkills()
            XCTFail("Expected unauthorized error")
        } catch let error as EvidenceAPIError {
            XCTAssertEqual(error, .unauthorized)
        }
        do {
            _ = try await api.fetchPortfolioHistory(cursor: nil)
            XCTFail("Expected safe unavailable error")
        } catch let error as EvidenceAPIError {
            XCTAssertEqual(error, .unavailable)
        }
    }

    private func transport(_ fixture: URLProtocolFixture) -> NativeAPITransport {
        NativeAPITransport(baseURL: URL(string: "https://api.example.test")!, session: fixture.session())
    }

    func testRejectsWrongSkillScopeDuplicateIDsAndNonprogressingCursor() async {
        for (body, cursor) in [
            (replacing(evidencePageBody(nextCursor: nil), "incident_communication", "other_skill"), nil),
            (Data("{\"items\":[],\"next_cursor\":40}".utf8), 40),
        ] as [(Data, Int?)] {
            let fixture = URLProtocolFixture()
            fixture.enqueue(.response(statusCode: 200, body: body))
            let api = LiveEvidenceAPI(transport: transport(fixture))
            await assertInvalidResponse { _ = try await api.fetchSkillEvidence(slug: "incident_communication", cursor: cursor) }
        }
        let fixture = URLProtocolFixture()
        let object = try! JSONSerialization.jsonObject(with: evidencePageBody(nextCursor: nil)) as! [String: Any]
        let item = (object["items"] as! [Any])[0]
        fixture.enqueue(.response(statusCode: 200, body: try! JSONSerialization.data(withJSONObject: ["items": [item, item], "next_cursor": NSNull()])))
        let api = LiveEvidenceAPI(transport: transport(fixture))
        await assertInvalidResponse { _ = try await api.fetchActivityEvidence(activityID: 41, cursor: nil) }
    }

    func testRequiredNullableKeysCannotBeOmitted() async {
        let fixture = URLProtocolFixture()
        fixture.enqueue(.response(statusCode: 200, body: Data(#"{"items":[]}"#.utf8)))
        var skill = try! JSONSerialization.jsonObject(with: skillBody(snapshot: nil)) as! [String: Any]
        skill.removeValue(forKey: "latest_snapshot")
        fixture.enqueue(.response(statusCode: 200, body: try! JSONSerialization.data(withJSONObject: skill)))
        let api = LiveEvidenceAPI(transport: transport(fixture))
        await assertInvalidResponse { _ = try await api.fetchPortfolioHistory(cursor: nil) }
        await assertInvalidResponse { _ = try await api.fetchSkill(slug: "incident_communication") }
    }

    func testMalformedDecimalsDatesAndOversizeFailClosed() async {
        for value in ["", "+", "NaN", "1e3", "1.5x", "2\n"] {
            let fixture = URLProtocolFixture()
            let data = replacing(skillsBody(snapshot: snapshotBody()), "3.125", value)
            fixture.enqueue(.response(statusCode: 200, body: data))
            let api = LiveEvidenceAPI(transport: transport(fixture))
            await assertInvalidResponse { _ = try await api.listSkills() }
        }
        for body in [replacing(skillsBody(snapshot: snapshotBody()), "2026-08-31", "2026-02-30"), Data(repeating: 32, count: 2 * 1024 * 1024 + 1)] {
            let fixture = URLProtocolFixture()
            fixture.enqueue(.response(statusCode: 200, body: body))
            let api = LiveEvidenceAPI(transport: transport(fixture))
            await assertInvalidResponse { _ = try await api.listSkills() }
        }
    }

    func testErrorAllowlistOfflineAndCancellation() async throws {
        for status in [403, 404, 409, 422, 500] {
            let fixture = URLProtocolFixture()
            fixture.enqueue(.response(statusCode: status, body: problemBody(status: status, detail: "private details")))
            do { _ = try await LiveEvidenceAPI(transport: transport(fixture)).listSkills(); XCTFail("Expected failure") }
            catch { XCTAssertEqual(error as? EvidenceAPIError, .unavailable) }
        }
        let fixture = URLProtocolFixture()
        fixture.enqueue(.error(URLError(.notConnectedToInternet)))
        do { _ = try await LiveEvidenceAPI(transport: transport(fixture)).listSkills(); XCTFail("Expected offline failure") }
        catch { XCTAssertEqual(error as? EvidenceAPIError, .unavailable) }
        fixture.enqueue(.pending)
        let api = LiveEvidenceAPI(transport: transport(fixture))
        let request = Task { try await api.listSkills() }
        while fixture.requests.count < 2 { await Task.yield() }
        request.cancel()
        do { _ = try await request.value; XCTFail("Expected cancellation") }
        catch { XCTAssertEqual(error as? EvidenceAPIError, .cancelled) }
    }

    private func replacing(_ data: Data, _ old: String, _ new: String) -> Data {
        Data(String(decoding: data, as: UTF8.self).replacingOccurrences(of: old, with: new).utf8)
    }

    private func assertInvalidRequest(
        _ operation: () async throws -> Void,
        file: StaticString = #filePath,
        line: UInt = #line
    ) async {
        do {
            try await operation()
            XCTFail("Expected invalid request", file: file, line: line)
        } catch let error as EvidenceAPIError {
            XCTAssertEqual(error, .invalidRequest, file: file, line: line)
        } catch {
            XCTFail("Unexpected error \(error)", file: file, line: line)
        }
    }

    private func assertInvalidResponse(
        _ operation: () async throws -> Void,
        file: StaticString = #filePath,
        line: UInt = #line
    ) async {
        do {
            try await operation()
            XCTFail("Expected invalid response", file: file, line: line)
        } catch let error as EvidenceAPIError {
            XCTAssertEqual(error, .invalidResponse, file: file, line: line)
        } catch {
            XCTFail("Unexpected error \(error)", file: file, line: line)
        }
    }

    private func skillsBody(snapshot: String?) -> Data {
        let item = String(data: skillBody(snapshot: snapshot), encoding: .utf8)!
        return Data("""
        {"items":[\(item)]}
        """.utf8)
    }

    private func skillBody(snapshot: String?) -> Data {
        Data("""
        {"slug":"incident_communication","name":"Incident communication",
         "baseline":"1.000","month_one_target":"2.000","final_target":"4.000",
         "latest_snapshot":\(snapshot ?? "null")}
        """.utf8)
    }

    private func snapshotBody(estimatedLevel: String = "3.125") -> String {
        """
        {"id":71,"formula_version":"v1","snapshot_date":"2026-08-31",
         "estimated_level":"\(estimatedLevel)","confidence":"moderate","trend":"improving","recency":"recent",
         "baseline_target_gap":"2.125","month_one_target_gap":"1.125","final_target_gap":"0.875",
         "total_effective_weight":"1.250","qualifying_event_count":2,"exercise_type_count":1,
         "last_strong_evidence_date":"2026-08-30",
         "manifest":[{"event_id":501,"effective_weight":"0.125","inclusion_code":"discounted_same_day"}],
         "confidence_basis":{"known_count":2,"unknown_basis":{"items":[1,{"deep":"kept"}]}},
         "trend_basis":{"window":"30d","unknown_signal":["raw",true]}}
        """
    }

    private func evidencePageBody(nextCursor: Int?, eventID: Int = 501) -> Data {
        let cursor = nextCursor.map(String.init) ?? "null"
        return Data("""
        {"items":[{
          "id":\(eventID),"activity_id":41,"attempt_id":null,"skill_slug":"incident_communication",
          "exercise_type":"tam_case","mapping_version":"mapping-v1","formula_version":"formula-v1",
          "rubric_slug":"incident_rubric","rubric_version":"rubric-v1","evaluator":"human_coach",
          "practice_mode":"independent_practice","assistance":"no_ai","difficulty":"standard",
          "performance_score":"3.750","skill_impact":"0.500","effective_weight":"0.875",
          "qualifying_for_level":true,"qualification_reason":"Independent evidence",
          "raw_dimension_scores":{"clarity":3,"nested":{"items":[2,{"value":"kept"}]}},
          "occurred_at":"2026-08-31T12:00:00Z"
        }],"next_cursor":\(cursor)}
        """.utf8)
    }

    private func portfolioPageBody(nextCursor: Int?) -> Data {
        let cursor = nextCursor.map(String.init) ?? "null"
        return Data("""
        {"items":[{
          "id":91,"activity_id":41,"attempt_id":81,"formula_version":"portfolio-v1","rubric_version":"rubric-v1",
          "total_score":"16.500","components":[
            {"slug":"impact_risk_assessment","score":"2.250"},
            {"slug":"explicit_prioritization","score":"2.250"},
            {"slug":"delegation_ownership","score":"2.250"},
            {"slug":"communication_control","score":"2.250"},
            {"slug":"proactive_work_protection","score":"2.500"},
            {"slug":"evidence_based_reprioritization","score":"2.500"},
            {"slug":"english_clarity","score":"2.500"}],
          "trend_basis":{"prior_total":"15.000","unknown_basis":{"items":[1,2]}},
          "scored_at":"2026-08-31T12:00:00Z"
        }],"next_cursor":\(cursor)}
        """.utf8)
    }

    private func portfolioPageMissingLastComponent() -> Data {
        var root = try! JSONSerialization.jsonObject(with: portfolioPageBody(nextCursor: nil)) as! [String: Any]
        var items = root["items"] as! [[String: Any]]
        var components = items[0]["components"] as! [[String: Any]]
        components.removeLast()
        items[0]["components"] = components
        root["items"] = items
        return try! JSONSerialization.data(withJSONObject: root)
    }

    private func problemBody(status: Int, detail: String) -> Data {
        Data("{\"title\":\"Unavailable\",\"status\":\(status),\"detail\":\"\(detail)\"}".utf8)
    }
}

private final class EvidenceDiagnosticRecorder: @unchecked Sendable {
    private let lock = NSLock()
    private var entries: [NativeAPIDiagnostic] = []

    var text: String { lock.withLock { entries.map(\.description).joined(separator: "\\n") } }
    func record(_ diagnostic: NativeAPIDiagnostic) { lock.withLock { entries.append(diagnostic) } }
}
