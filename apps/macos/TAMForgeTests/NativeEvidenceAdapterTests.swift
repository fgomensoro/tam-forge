import Foundation
import XCTest

@MainActor
final class NativeEvidenceAdapterTests: XCTestCase {
    func testAllReadEndpointsUseValidatedBoundedBearerRequestsAndMapGeneratedProjections() async throws {
        let fixture = URLProtocolFixture()
        fixture.enqueue(.response(statusCode: 200, body: skillsBody(snapshot: nil)))
        fixture.enqueue(.response(statusCode: 200, body: skillBody(snapshot: snapshotBody())))
        fixture.enqueue(.response(statusCode: 200, body: evidencePageBody(nextCursor: nil, qualifying: true)))
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
        XCTAssertEqual(detail.snapshot?.estimatedLevel, "1.368")
        XCTAssertEqual(detail.snapshot?.snapshotDate, "2026-08-31")
        XCTAssertNil(detail.snapshot?.lastStrongEvidenceDate)
        XCTAssertEqual(detail.snapshot?.manifest[0].usedWeight, "0.308750")
        XCTAssertEqual(detail.snapshot?.confidenceBasis["unknown_basis"], .object([
            "items": .array([.integer(1), .object(["deep": .string("kept")])]),
        ]))
        XCTAssertEqual(detail.snapshot?.trendBasis["unknown_signal"], .array([.string("raw"), .boolean(true)]))
        XCTAssertEqual(skillPage.nextCursor, nil)
        XCTAssertEqual(activityPage.nextCursor, 39)
        XCTAssertEqual(activityPage.items[0].attemptID, nil)
        XCTAssertEqual(activityPage.items[0].performanceScore, "3.750")
        XCTAssertEqual(activityPage.items[0].effectiveWeight, "0.308750")
        XCTAssertEqual(
            activityPage.items[0].rawDimensionScores["nested"],
            .object(["items": .array([.integer(2), .object(["value": .string("kept")])])])
        )
        XCTAssertEqual(portfolio.items[0].totalScore, "16.500")
        XCTAssertEqual(portfolio.items[0].components[0].score, "3.500")

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
        fixture.enqueue(.response(statusCode: 200, body: portfolioPageWithDuplicateComponent()))
        fixture.enqueue(.response(statusCode: 200, body: portfolioPageWithImpossibleComponent()))
        let api = LiveEvidenceAPI(transport: transport(fixture))

        await assertInvalidResponse { _ = try await api.listSkills() }
        await assertInvalidResponse { _ = try await api.fetchPortfolioHistory(cursor: nil) }
        await assertInvalidResponse { _ = try await api.fetchPortfolioHistory(cursor: nil) }
        await assertInvalidResponse { _ = try await api.fetchPortfolioHistory(cursor: nil) }
        await assertInvalidResponse { _ = try await api.fetchPortfolioHistory(cursor: nil) }
    }

    func testPreservesServerAuthoritativePortfolioTotalWithoutRecomputingIt() async throws {
        let fixture = URLProtocolFixture()
        fixture.enqueue(.response(
            statusCode: 200,
            body: replacing(portfolioPageBody(nextCursor: nil), "16.500", "16.499")
        ))

        let page = try await LiveEvidenceAPI(transport: transport(fixture))
            .fetchPortfolioHistory(cursor: nil)

        XCTAssertEqual(page.items[0].totalScore, "16.499")
        XCTAssertEqual(page.items[0].components[0].score, "3.500")
    }

    func testRejectsSnapshotAndEventValuesOutsideBackendRanges() async {
        for body in [
            replacing(skillsBody(snapshot: snapshotBody()), [("\"baseline_target_gap\":\"-0.368\"", "\"baseline_target_gap\":\"-4.001\"")]),
            replacing(skillsBody(snapshot: snapshotBody()), [("\"total_effective_weight\":\"0.308750\"", "\"total_effective_weight\":\"-0.001\"")]),
            replacing(skillsBody(snapshot: snapshotBody()), [("\"effective_weight\":\"0.308750\"", "\"effective_weight\":\"1.501\"")]),
        ] {
            let fixture = URLProtocolFixture()
            fixture.enqueue(.response(statusCode: 200, body: body))
            await assertInvalidResponse { _ = try await LiveEvidenceAPI(transport: transport(fixture)).listSkills() }
        }

        for body in [
            replacing(evidencePageBody(nextCursor: nil), [("\"skill_impact\":\"0.500\"", "\"skill_impact\":\"0\"")]),
            replacing(evidencePageBody(nextCursor: nil), [("\"skill_impact\":\"0.500\"", "\"skill_impact\":\"1.001\"")]),
            replacing(evidencePageBody(nextCursor: nil), [("\"effective_weight\":\"0.308750\"", "\"effective_weight\":\"-0.001\"")]),
            replacing(evidencePageBody(nextCursor: nil), [("\"effective_weight\":\"0.308750\"", "\"effective_weight\":\"1.501\"")]),
        ] {
            let fixture = URLProtocolFixture()
            fixture.enqueue(.response(statusCode: 200, body: body))
            await assertInvalidResponse {
                _ = try await LiveEvidenceAPI(transport: transport(fixture))
                    .fetchSkillEvidence(slug: "incident_communication", cursor: nil)
            }
        }
    }

    func testRejectsIncoherentSnapshotRelationships() async {
        for body in [
            replacing(skillsBody(snapshot: snapshotBody()), [("\"baseline_target_gap\":\"-0.368\"", "\"baseline_target_gap\":\"-0.369\"")]),
            replacing(skillsBody(snapshot: snapshotBody()), [("\"total_effective_weight\":\"0.308750\"", "\"total_effective_weight\":\"0.308751\"")]),
            replacing(skillsBody(snapshot: snapshotBody()), [("\"inclusion_code\":\"included\"", "\"inclusion_code\":\"excluded_nonqualifying\"")]),
            replacing(skillsBody(snapshot: snapshotBody()), [("\"qualifying_event_count\":1", "\"qualifying_event_count\":2")]),
        ] {
            let fixture = URLProtocolFixture()
            fixture.enqueue(.response(statusCode: 200, body: body))
            await assertInvalidResponse { _ = try await LiveEvidenceAPI(transport: transport(fixture)).listSkills() }
        }
    }

    func testEnforcesQualifyingEvidenceCoherence() async throws {
        let validQualifying = evidencePageBody(nextCursor: nil, qualifying: true)
        let fixture = URLProtocolFixture()
        fixture.enqueue(.response(statusCode: 200, body: validQualifying))
        fixture.enqueue(.response(statusCode: 200, body: replacing(
            validQualifying,
            [("\"attempt_id\":81", "\"attempt_id\":null")]
        )))
        fixture.enqueue(.response(statusCode: 200, body: replacing(
            validQualifying,
            [("\"practice_mode\":\"independent_practice\"", "\"practice_mode\":\"guided_practice\"")]
        )))
        fixture.enqueue(.response(statusCode: 200, body: replacing(
            validQualifying,
            [("\"assistance\":\"no_ai\"", "\"assistance\":\"ai_during_attempt\"")]
        )))
        let api = LiveEvidenceAPI(transport: transport(fixture))

        let accepted = try await api.fetchSkillEvidence(slug: "incident_communication", cursor: nil)
        XCTAssertTrue(accepted.items[0].qualifyingForLevel)
        await assertInvalidResponse { _ = try await api.fetchSkillEvidence(slug: "incident_communication", cursor: nil) }
        await assertInvalidResponse { _ = try await api.fetchSkillEvidence(slug: "incident_communication", cursor: nil) }
        await assertInvalidResponse { _ = try await api.fetchSkillEvidence(slug: "incident_communication", cursor: nil) }
    }

    func testAcceptsSnapshotAndEventBackendRangeBoundaries() async throws {
        let fixture = URLProtocolFixture()
        fixture.enqueue(.response(statusCode: 200, body: replacing(
            skillsBody(snapshot: snapshotBody()),
            [
                ("\"estimated_level\":\"1.368\"", "\"estimated_level\":\"2.179\""),
                ("\"baseline_target_gap\":\"-0.368\"", "\"baseline_target_gap\":\"-1.179\""),
                ("\"month_one_target_gap\":\"0.632\"", "\"month_one_target_gap\":\"-0.179\""),
                ("\"final_target_gap\":\"2.632\"", "\"final_target_gap\":\"1.821\""),
                ("\"total_effective_weight\":\"0.308750\"", "\"total_effective_weight\":\"1.5\""),
                ("\"effective_weight\":\"0.308750\"", "\"effective_weight\":\"1.5\""),
            ]
        )))
        fixture.enqueue(.response(statusCode: 200, body: replacing(
            evidencePageBody(nextCursor: nil),
            [
                ("\"skill_impact\":\"0.500\"", "\"skill_impact\":\"0.000001\""),
                ("\"effective_weight\":\"0.308750\"", "\"effective_weight\":\"0\""),
            ]
        )))
        fixture.enqueue(.response(statusCode: 200, body: replacing(
            evidencePageBody(nextCursor: nil),
            [("\"effective_weight\":\"0.308750\"", "\"effective_weight\":\"1.5\"")]
        )))
        let api = LiveEvidenceAPI(transport: transport(fixture))

        let skills = try await api.listSkills()
        let zeroWeight = try await api.fetchSkillEvidence(slug: "incident_communication", cursor: nil)
        let maximumWeight = try await api.fetchSkillEvidence(slug: "incident_communication", cursor: nil)

        XCTAssertEqual(skills[0].snapshot?.baselineTargetGap, "-1.179")
        XCTAssertEqual(skills[0].snapshot?.manifest[0].usedWeight, "1.5")
        XCTAssertEqual(zeroWeight.items[0].skillImpact, "0.000001")
        XCTAssertEqual(zeroWeight.items[0].effectiveWeight, "0")
        XCTAssertEqual(maximumWeight.items[0].effectiveWeight, "1.5")
    }

    func testAdapterCodeContractRejectsValuesTheBackendCannotProduce() {
        XCTAssertTrue(EvidenceResponseContract.validSnapshotCodes(
            confidence: "medium", trend: "improving", recency: "fresh"
        ))
        XCTAssertFalse(EvidenceResponseContract.validSnapshotCodes(
            confidence: "moderate", trend: "improving", recency: "fresh"
        ))
        XCTAssertFalse(EvidenceResponseContract.validSnapshotCodes(
            confidence: "medium", trend: "improving", recency: "recent"
        ))
        XCTAssertTrue(EvidenceResponseContract.validQualification(
            reason: "qualifies", qualifies: true, attemptID: 81,
            practiceMode: "independent_practice", assistance: "no_ai"
        ))
        XCTAssertFalse(EvidenceResponseContract.validQualification(
            reason: "excluded_by_formula", qualifies: false, attemptID: nil,
            practiceMode: "guided_practice", assistance: "ai_during_attempt"
        ))
        XCTAssertFalse(EvidenceResponseContract.validQualification(
            reason: "missing_committed_attempt", qualifies: false, attemptID: 81,
            practiceMode: "independent_practice", assistance: "no_ai"
        ))
        XCTAssertFalse(EvidenceResponseContract.validQualification(
            reason: "excluded_by_formula", qualifies: false, attemptID: 81,
            practiceMode: "guided_practice", assistance: "no_ai"
        ))
        XCTAssertFalse(EvidenceResponseContract.validQualification(
            reason: "excluded_by_formula", qualifies: false, attemptID: 81,
            practiceMode: "independent_practice", assistance: "ai_hints_during_attempt"
        ))
        XCTAssertTrue(EvidenceResponseContract.validQualification(
            reason: "attempt_b", qualifies: false, attemptID: 81,
            practiceMode: "guided_practice", assistance: "ai_hints_during_attempt"
        ))
        XCTAssertTrue(EvidenceResponseContract.validQualification(
            reason: "missing_committed_attempt", qualifies: false, attemptID: nil,
            practiceMode: "independent_practice", assistance: "no_ai"
        ))
        XCTAssertTrue(EvidenceResponseContract.validQualification(
            reason: "nonqualifying_mode", qualifies: false, attemptID: 81,
            practiceMode: "guided_practice", assistance: "no_ai"
        ))
        XCTAssertTrue(EvidenceResponseContract.validQualification(
            reason: "assisted_during_attempt", qualifies: false, attemptID: 81,
            practiceMode: "independent_practice", assistance: "ai_hints_during_attempt"
        ))
        XCTAssertTrue(EvidenceResponseContract.validQualification(
            reason: "mapping_condition_not_met", qualifies: false, attemptID: 81,
            practiceMode: "independent_practice", assistance: "no_ai"
        ))
        XCTAssertFalse(EvidenceResponseContract.validQualification(
            reason: "Independent evidence", qualifies: true, attemptID: 81,
            practiceMode: "independent_practice", assistance: "no_ai"
        ))
        XCTAssertFalse(EvidenceResponseContract.validQualification(
            reason: "qualifies", qualifies: false, attemptID: nil,
            practiceMode: "guided_practice", assistance: "ai_during_attempt"
        ))
    }

    func testDebugFixturePaginationQueryRejectsBareEmptyDuplicateAndInvalidCursors() throws {
        XCTAssertNil(try NativeEvidenceFixtureQuery.cursor(
            from: URL(string: "https://fixture.invalid/api/v1/portfolio-judgment?limit=20")!,
            paginated: true
        ))
        XCTAssertEqual(try NativeEvidenceFixtureQuery.cursor(
            from: URL(string: "https://fixture.invalid/api/v1/portfolio-judgment?limit=20&cursor=91")!,
            paginated: true
        ), 91)
        XCTAssertNil(try NativeEvidenceFixtureQuery.cursor(
            from: URL(string: "https://fixture.invalid/api/v1/skills")!,
            paginated: false
        ))

        for suffix in [
            "?limit=20&cursor", "?limit=20&cursor=", "?limit=20&cursor=0",
            "?limit=20&cursor=-1", "?limit=20&cursor=bad", "?cursor=91",
            "?limit=20&cursor=91&cursor=90", "?limit=20&unknown=1",
        ] {
            XCTAssertThrowsError(try NativeEvidenceFixtureQuery.cursor(
                from: URL(string: "https://fixture.invalid/api/v1/portfolio-judgment\(suffix)")!,
                paginated: true
            ), suffix)
        }
        XCTAssertThrowsError(try NativeEvidenceFixtureQuery.cursor(
            from: URL(string: "https://fixture.invalid/api/v1/skills?cursor=91")!,
            paginated: false
        ))
    }

    func testDebugFixtureRequiresTheSelectedHTTPSOrigin() {
        XCTAssertTrue(NativeUIFixtureRequestValidator.hasExpectedOrigin(
            URL(string: "https://api.tamforge.invalid/api/v1/skills")!,
            environment: .production
        ))
        XCTAssertTrue(NativeUIFixtureRequestValidator.hasExpectedOrigin(
            URL(string: "https://api-preview.tamforge.invalid/api/v1/skills")!,
            environment: .preview
        ))
        for value in [
            "http://api.tamforge.invalid/api/v1/skills",
            "https://api-preview.tamforge.invalid/api/v1/skills",
            "https://api.tamforge.invalid:443/api/v1/skills",
            "https://attacker.invalid/api/v1/skills",
        ] {
            XCTAssertFalse(NativeUIFixtureRequestValidator.hasExpectedOrigin(
                URL(string: value)!,
                environment: .production
            ), value)
        }
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
            let data = replacing(
                skillsBody(snapshot: snapshotBody()),
                "\"estimated_level\":\"1.368\"",
                "\"estimated_level\":\"\(value)\""
            )
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
        defer { request.cancel() }
        let requestStarted = await waitForRequests(2, in: fixture)
        XCTAssertTrue(requestStarted, "Pending request did not start before the timeout")
        request.cancel()
        do { _ = try await request.value; XCTFail("Expected cancellation") }
        catch { XCTAssertEqual(error as? EvidenceAPIError, .cancelled) }
    }

    private func replacing(_ data: Data, _ old: String, _ new: String) -> Data {
        Data(String(decoding: data, as: UTF8.self).replacingOccurrences(of: old, with: new).utf8)
    }

    private func replacing(_ data: Data, _ replacements: [(String, String)]) -> Data {
        replacements.reduce(data) { replacing($0, $1.0, $1.1) }
    }

    private func waitForRequests(_ count: Int, in fixture: URLProtocolFixture) async -> Bool {
        let clock = ContinuousClock()
        let deadline = clock.now.advanced(by: .seconds(1))
        while fixture.requests.count < count {
            guard clock.now < deadline, !Task.isCancelled else { return false }
            try? await Task<Never, Never>.sleep(for: .milliseconds(5))
        }
        return true
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

    private func snapshotBody(estimatedLevel: String = "1.368") -> String {
        """
        {"id":71,"formula_version":"formula-v1","snapshot_date":"2026-08-31",
         "estimated_level":"\(estimatedLevel)","confidence":"low","trend":"insufficient_evidence","recency":"fresh",
         "baseline_target_gap":"-0.368","month_one_target_gap":"0.632","final_target_gap":"2.632",
         "total_effective_weight":"0.308750","qualifying_event_count":1,"exercise_type_count":1,
         "last_strong_evidence_date":null,
         "manifest":[{"event_id":501,"effective_weight":"0.308750","inclusion_code":"included"}],
         "confidence_basis":{"schema_version":1,"basis_code":"low_weight","event_ids":[501],"unknown_basis":{"items":[1,{"deep":"kept"}]}},
         "trend_basis":{"schema_version":1,"basis_code":"too_few_events","event_ids":[],"unknown_signal":["raw",true]}}
        """
    }

    private func evidencePageBody(nextCursor: Int?, eventID: Int = 501, qualifying: Bool = false) -> Data {
        let cursor = nextCursor.map(String.init) ?? "null"
        let attemptID = qualifying ? "81" : "null"
        let qualifies = qualifying ? "true" : "false"
        let reason = qualifying ? "qualifies" : "missing_committed_attempt"
        return Data("""
        {"items":[{
          "id":\(eventID),"activity_id":41,"attempt_id":\(attemptID),"skill_slug":"incident_communication",
          "exercise_type":"tam_case","mapping_version":"mapping-v1","formula_version":"formula-v1",
          "rubric_slug":"incident_rubric","rubric_version":"rubric-v1","evaluator":"human_coach",
          "practice_mode":"independent_practice","assistance":"no_ai","difficulty":"standard",
          "performance_score":"3.750","skill_impact":"0.500","effective_weight":"0.308750",
          "qualifying_for_level":\(qualifies),"qualification_reason":"\(reason)",
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
            {"slug":"impact_risk_assessment","score":"3.500"},
            {"slug":"explicit_prioritization","score":"2.500"},
            {"slug":"delegation_ownership","score":"2.500"},
            {"slug":"communication_control","score":"2.500"},
            {"slug":"proactive_work_protection","score":"1.500"},
            {"slug":"evidence_based_reprioritization","score":"2.500"},
            {"slug":"english_clarity","score":"1.500"}],
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

    private func portfolioPageWithDuplicateComponent() -> Data {
        var root = try! JSONSerialization.jsonObject(with: portfolioPageBody(nextCursor: nil)) as! [String: Any]
        var items = root["items"] as! [[String: Any]]
        var components = items[0]["components"] as! [[String: Any]]
        components.append(components[0])
        items[0]["components"] = components
        root["items"] = items
        return try! JSONSerialization.data(withJSONObject: root)
    }

    private func portfolioPageWithImpossibleComponent() -> Data {
        var root = try! JSONSerialization.jsonObject(with: portfolioPageBody(nextCursor: nil)) as! [String: Any]
        var items = root["items"] as! [[String: Any]]
        var components = items[0]["components"] as! [[String: Any]]
        components[0]["score"] = "4.500"
        components[3]["score"] = "1.500"
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
