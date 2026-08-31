import Foundation
import XCTest

@MainActor
final class NativeActivityAdapterTests: XCTestCase {
    func testFetchMapsCompleteGeneratedDetailIncludingNestedContractValues() async throws {
        let fixture = URLProtocolFixture()
        fixture.enqueue(.response(statusCode: 200, body: detailBody()))
        let api = LiveActivityAPI(transport: transport(fixture))

        let detail = try await api.fetch(activityID: 41)

        XCTAssertEqual(detail.id, 41)
        XCTAssertEqual(detail.state, .outputCommitted)
        XCTAssertEqual(detail.openTimer?.lastClientSequence, 8)
        XCTAssertEqual(detail.selfReview?.changeNext, "Lead with impact")
        XCTAssertEqual(detail.committedOutput?.artifactIDs, [90, 91])
        XCTAssertEqual(
            detail.committedOutput?.contractPayload["large_integer"],
            .integer(9_007_199_254_740_993)
        )
        XCTAssertEqual(
            detail.committedOutput?.contractPayload["nested"],
            .object([
                "boolean": .boolean(true),
                "decimal": .decimal(3.75),
                "items": .array([.string("first"), .null]),
            ])
        )
    }

    func testFetchKeepsLargeGeneratedContractPayloadAboveStandardLimit() async throws {
        let fixture = URLProtocolFixture()
        let output = String(repeating: "a", count: 2_500_000)
        fixture.enqueue(.response(statusCode: 200, body: detailBody(largeOutput: output)))
        let api = LiveActivityAPI(transport: transport(fixture))

        let detail = try await api.fetch(activityID: 41)

        XCTAssertEqual(detail.committedOutput?.contractPayload["large_output"], .string(output))
    }

    func testCommitSendsGeneratedOutputContainerAndCallerIdempotencyKey() async throws {
        let fixture = URLProtocolFixture()
        fixture.enqueue(.response(statusCode: 200, body: outputCommitResponseBody()))
        let api = LiveActivityAPI(transport: transport(fixture))
        let command = ActivityCommitCommand(
            activityID: 41,
            expectedVersion: 7,
            clientSequence: 9,
            output: [
                "large_integer": .integer(9_007_199_254_740_993),
                "decimal": .decimal(3.75),
                "boolean": .boolean(true),
                "nullable": .null,
                "nested": .object(["values": .array([.integer(3), .null])]),
            ],
            artifactReferences: [
                .init(artifactID: 90, linkRole: .originalOutput),
                .init(artifactID: 91, linkRole: .supporting),
            ],
            idempotencyKey: "commit-41-9"
        )

        let receipt = try await api.commit(command)

        XCTAssertEqual(receipt.activityID, 41)
        XCTAssertEqual(receipt.artifactIDs, [90, 91])
        let request = try XCTUnwrap(fixture.requests.first)
        XCTAssertEqual(request.httpMethod, "POST")
        XCTAssertEqual(request.url?.path, "/api/v1/activities/41/commit-output")
        XCTAssertEqual(request.value(forHTTPHeaderField: "Idempotency-Key"), "commit-41-9")
        let body = try requestBody(request)
        let commandBody = try NativeJSONCodec.decode(Components.Schemas.CommitOutputCommand.self, from: body)
        XCTAssertEqual(commandBody.expectedVersion, 7)
        XCTAssertEqual(commandBody.clientSequence, 9)
        XCTAssertEqual(commandBody.artifactRefs?.map(\.artifactId), [90, 91])
        XCTAssertEqual(commandBody.artifactRefs?.map(\.linkRole.rawValue), ["original_output", "supporting"])
        XCTAssertEqual(commandBody.output.additionalProperties.value["large_integer"] as? Int, 9_007_199_254_740_993)
        XCTAssertEqual(commandBody.output.additionalProperties.value["decimal"] as? Double, 3.75)
        XCTAssertEqual(commandBody.output.additionalProperties.value["boolean"] as? Bool, true)
        XCTAssertTrue(commandBody.output.additionalProperties.value.keys.contains("nullable"))
        XCTAssertNil(commandBody.output.additionalProperties.value["nullable"]!)
    }

    func testPresignRejectsResponseMissingGeneratedRequiredMethod() async throws {
        let fixture = URLProtocolFixture()
        fixture.enqueue(.response(statusCode: 200, body: Data(#"""
        {
          "artifact_id": null,
          "object_key": "activities/41/answer.txt",
          "reused": false,
          "upload": {
            "url": "https://uploads.example.test/answer.txt",
            "headers": {"content-type": "text/plain"},
            "expires_seconds": 300
          }
        }
        """#.utf8)))
        let api = LiveActivityAPI(transport: transport(fixture))

        do {
            _ = try await api.presign(.init(
                activityID: 41,
                expectedVersion: 7,
                artifactClass: .writtenOutput,
                sha256: String(repeating: "a", count: 64),
                byteLength: 12,
                contentType: "text/plain",
                originalFilename: "answer.txt",
                idempotencyKey: "presign-41"
            ))
            XCTFail("Expected generated-schema response validation to fail")
        } catch let error as ActivityAPIError {
            XCTAssertEqual(error, .invalidResponse)
        }
    }

    func testStartRejectsAdditionalGeneratedResponseField() async throws {
        let fixture = URLProtocolFixture()
        fixture.enqueue(.response(statusCode: 200, body: Data(#"""
        {
          "id": 41,
          "study_day_id": 14,
          "state": "active",
          "optimistic_version": 8,
          "classification": "useful",
          "stronger_evidence_id": null,
          "activity_focused_seconds": 760,
          "day_focused_minutes": 13,
          "hard_stop_recommended": false,
          "open_timer": null,
          "unexpected": "not in ActivityResponse"
        }
        """#.utf8)))
        let api = LiveActivityAPI(transport: transport(fixture))

        do {
            _ = try await api.start(activityID: 41, expectedVersion: 7, idempotencyKey: "start-41")
            XCTFail("Expected generated-schema response validation to fail")
        } catch let error as ActivityAPIError {
            XCTAssertEqual(error, .invalidResponse)
        }
    }

    func testStartMapsGeneratedDefaultSourceVisibility() async throws {
        let fixture = URLProtocolFixture()
        fixture.enqueue(.response(statusCode: 200, body: activityResponseBody()))
        let api = LiveActivityAPI(transport: transport(fixture))

        let summary = try await api.start(activityID: 41, expectedVersion: 7, idempotencyKey: "start-41")

        XCTAssertEqual(summary.id, 41)
        XCTAssertEqual(summary.state, .active)
        XCTAssertFalse(summary.sourceHidden)
    }

    func testGeneratedLifecycleReceiptsMapToExistingDomainModels() async throws {
        let fixture = URLProtocolFixture()
        fixture.enqueue(.response(statusCode: 200, body: selfReviewResponseBody()))
        fixture.enqueue(.response(statusCode: 200, body: presignResponseBody()))
        fixture.enqueue(.response(statusCode: 200, body: artifactResponseBody()))
        let api = LiveActivityAPI(transport: transport(fixture))

        let selfReview = try await api.submitSelfReview(.init(
            activityID: 41,
            expectedVersion: 7,
            idempotencyKey: "review-41",
            input: .init(
                mainAnswer: "Answer",
                didWell: "Scope",
                structureWeakness: "Timeline",
                vaguePoints: "Impact",
                hesitationPoints: "Pause",
                changeNext: "Lead with impact",
                selfScore: 3
            )
        ))
        let presign = try await api.presign(.init(
            activityID: 41,
            expectedVersion: 8,
            artifactClass: .writtenOutput,
            sha256: String(repeating: "a", count: 64),
            byteLength: 12,
            contentType: "text/plain",
            originalFilename: "answer.txt",
            idempotencyKey: "presign-41"
        ))
        let artifact = try await api.confirm(.init(
            activityID: 41,
            expectedVersion: 8,
            uploadIdempotencyKey: "presign-41",
            objectKey: "activities/41/answer.txt",
            idempotencyKey: "confirm-41"
        ))

        XCTAssertEqual(selfReview.selfReviewID, 101)
        XCTAssertEqual(selfReview.state, .selfReviewComplete)
        XCTAssertEqual(presign.upload?.url, URL(string: "https://uploads.example.test/answer.txt"))
        XCTAssertEqual(presign.upload?.headers, ["content-type": "text/plain"])
        XCTAssertEqual(presign.upload?.expiresSeconds, 300)
        XCTAssertEqual(artifact.artifactClass, .writtenOutput)
        XCTAssertEqual(artifact.originalFilename, "answer.txt")
    }

    private func transport(_ fixture: URLProtocolFixture) -> NativeAPITransport {
        NativeAPITransport(baseURL: URL(string: "https://api.example.test")!, session: fixture.session())
    }

    private func requestBody(_ request: URLRequest) throws -> Data {
        if let body = request.httpBody { return body }
        let stream = try XCTUnwrap(request.httpBodyStream)
        stream.open()
        defer { stream.close() }

        var body = Data()
        var buffer = [UInt8](repeating: 0, count: 4_096)
        while true {
            let count = stream.read(&buffer, maxLength: buffer.count)
            if count == 0 { return body }
            if count < 0 { throw try XCTUnwrap(stream.streamError) }
            body.append(contentsOf: buffer.prefix(count))
        }
    }

    private func detailBody(largeOutput: String? = nil) -> Data {
        let largeOutputField = largeOutput.map { ", \"large_output\": \"\($0)\"" } ?? ""
        return Data(#"""
        {
          "id": 41,
          "study_day_id": 14,
          "state": "output_committed",
          "optimistic_version": 7,
          "classification": "useful",
          "stronger_evidence_id": null,
          "activity_focused_seconds": 745,
          "day_focused_minutes": 13,
          "hard_stop_recommended": true,
          "open_timer": {
            "id": 70,
            "started_at": "2026-08-31T12:00:00Z",
            "last_heartbeat_at": "2026-08-31T12:12:30.123456Z",
            "counted_seconds": 750,
            "last_client_sequence": 8
          },
          "source_hidden": true,
          "task_contract": {
            "stable_id": "P1-2026-08-31-I60",
            "block": "tam_case",
            "objective": "Map incident impact",
            "timebox_minutes": 60,
            "required": true,
            "source_references": [{"path": "TAM Practice/Docs/Case.md", "anchor": "Incident"}],
            "required_output": ["written"],
            "pass_criteria": ["scope"],
            "evidence_requirements": ["attempt"],
            "allowed_ai_role": "coach",
            "procedure": [{"phase": "attempt", "minutes": 20, "requirement": "Answer first"}],
            "constraints": ["No AI answer"],
            "exercise_type": null,
            "mapping_version": null
          },
          "committed_output": {
            "attempt_id": 81,
            "attempt_kind": "written",
            "commitment_sha256": "\#(String(repeating: "b", count: 64))",
            "contract_payload": {
              "large_integer": 9007199254740993,
              "nested": {
                "boolean": true,
                "decimal": 3.75,
                "items": ["first", null]
              }\#(largeOutputField)
            },
            "artifact_ids": [90, 91],
            "committed_at": "2026-08-31T12:13:00.5Z"
          },
          "self_review": {
            "id": 101,
            "attempt_id": 81,
            "self_score": 3,
            "main_answer": "Answer",
            "did_well": "Scope",
            "structure_weakness": "Timeline",
            "vague_points": "Impact",
            "hesitation_points": "Pause",
            "change_next": "Lead with impact",
            "submitted_at": "2026-08-31T12:14:00Z"
          }
        }
        """#.utf8)
    }

    private func outputCommitResponseBody() -> Data {
        Data(#"""
        {
          "activity_id": 41,
          "state": "output_committed",
          "optimistic_version": 8,
          "attempt_id": 81,
          "commitment_sha256": "\#(String(repeating: "b", count: 64))",
          "artifact_ids": [90, 91]
        }
        """#.utf8)
    }

    private func activityResponseBody() -> Data {
        Data(#"""
        {
          "id": 41,
          "study_day_id": 14,
          "state": "active",
          "optimistic_version": 8,
          "classification": "useful",
          "stronger_evidence_id": null,
          "activity_focused_seconds": 760,
          "day_focused_minutes": 13,
          "hard_stop_recommended": false,
          "open_timer": null
        }
        """#.utf8)
    }

    private func selfReviewResponseBody() -> Data {
        Data(#"""
        {
          "activity_id": 41,
          "state": "self_review_complete",
          "optimistic_version": 8,
          "self_review_id": 101,
          "attempt_id": 81,
          "self_score": 3
        }
        """#.utf8)
    }

    private func presignResponseBody() -> Data {
        Data(#"""
        {
          "artifact_id": null,
          "object_key": "activities/41/answer.txt",
          "reused": false,
          "upload": {
            "url": "https://uploads.example.test/answer.txt",
            "method": "PUT",
            "headers": {"content-type": "text/plain"},
            "expires_seconds": 300
          }
        }
        """#.utf8)
    }

    private func artifactResponseBody() -> Data {
        Data(#"""
        {
          "id": 90,
          "sha256": "\#(String(repeating: "a", count: 64))",
          "byte_length": 12,
          "content_type": "text/plain",
          "original_filename": "answer.txt",
          "artifact_class": "written_output"
        }
        """#.utf8)
    }
}
