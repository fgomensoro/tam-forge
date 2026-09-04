import Foundation
import XCTest

@MainActor
final class NativeSqlAdapterTests: XCTestCase {
    func testExecutionSendsExactRouteBodyAndRetryKeyAndMapsNullableRows() async throws {
        let fixture = URLProtocolFixture()
        fixture.enqueue(.response(statusCode: 200, body: try receiptBody()))
        let api = api(fixture)
        let receipt = try await api.executeSQL(.init(activityID: 41, expectedVersion: 7,
                                                    query: "select 1", idempotencyKey: "sql-original"))
        let request = try XCTUnwrap(fixture.requests.first)
        XCTAssertEqual(request.httpMethod, "POST")
        XCTAssertEqual(request.url?.path, "/api/v1/activities/41/sql-executions")
        XCTAssertEqual(request.value(forHTTPHeaderField: "Idempotency-Key"), "sql-original")
        let json = try XCTUnwrap(JSONSerialization.jsonObject(with: requestBody(request)) as? [String: Any])
        XCTAssertEqual(Set(json.keys), ["query", "expected_version"])
        XCTAssertEqual(json["query"] as? String, "select 1")
        XCTAssertEqual(json["expected_version"] as? Int, 7)
        XCTAssertEqual(receipt.query, "select 1")
        XCTAssertEqual(receipt.result.rows, [["1"], [nil]])
        XCTAssertEqual(receipt.result.validation, .wrongGrain)
        XCTAssertEqual(receipt.result.elapsedMS, 12)
    }

    func testHistoryUsesGETAndRejectsUnboundedOrMalformedReceipts() async throws {
        let valid = try JSONSerialization.jsonObject(with: receiptBody())
        for count in [1, 21] {
            let fixture = URLProtocolFixture()
            fixture.enqueue(.response(statusCode: 200, body: try JSONSerialization.data(withJSONObject: ["items": Array(repeating: valid, count: count)])))
            do {
                let items = try await api(fixture).fetchSQLHistory(activityID: 41)
                XCTAssertEqual(count, 1)
                XCTAssertEqual(items.first?.query, "select 1")
            } catch let error as SqlExecutionError {
                XCTAssertEqual(count, 21)
                XCTAssertEqual(error, .invalidResponse)
            }
            XCTAssertEqual(fixture.requests.first?.httpMethod, "GET")
            XCTAssertEqual(fixture.requests.first?.url?.path, "/api/v1/activities/41/sql-executions")
        }
        for body in [try receiptBody(rowCount: 1001), try receiptBody(query: String(repeating: "é", count: 32_769)),
                     try receiptBody(activityID: 99), try receiptBody(columns: []),
                     try receiptBody(cell: String(repeating: "x", count: 270_000))] {
            let fixture = URLProtocolFixture()
            fixture.enqueue(.response(statusCode: 200, body: body))
            do {
                _ = try await api(fixture).executeSQL(.init(activityID: 41, expectedVersion: 7, query: "select 1", idempotencyKey: "sql"))
                XCTFail("Malformed or oversized receipt must be refused")
            } catch let error as SqlExecutionError { XCTAssertEqual(error, .invalidResponse) }
        }
    }

    func testHistoryRetainsOneMiBEnvelopeAndStandardTransportLimit() async throws {
        for size in [1_100_000, 2_200_000] {
            let fixture = URLProtocolFixture()
            fixture.enqueue(.response(statusCode: 200, body: Data(("{\"items\":[]}" + String(repeating: " ", count: size)).utf8)))
            do {
                _ = try await api(fixture).fetchSQLHistory(activityID: 41)
                XCTFail("Oversized history must be refused")
            } catch let error as SqlExecutionError { XCTAssertEqual(error, .invalidResponse) }
        }
    }

    func testClosedProblemMappingNeverExposesServerQueryOrExceptionText() async throws {
        let cases: [(Int, String, Error)] = [
            (401, "unauthorized", ActivityAPIError.unauthorized),
            (409, "sql_execution_conflict", ActivityAPIError.conflict),
            (404, "sql_activity_not_found", SqlExecutionError.unavailable),
            (422, "invalid_sql_execution", SqlExecutionError.queryRejected),
            (429, "sql_execution_busy", SqlExecutionError.busy),
            (503, "sql_execution_unavailable", SqlExecutionError.unavailable),
            (503, "unknown", SqlExecutionError.network),
        ]
        for (status, code, expected) in cases {
            let fixture = URLProtocolFixture()
            fixture.enqueue(.response(statusCode: status, body: try JSONSerialization.data(withJSONObject: ["status": status, "code": code, "detail": "SECRET QUERY OR DRIVER TEXT"])))
            do {
                _ = try await api(fixture).executeSQL(.init(activityID: 41, expectedVersion: 7, query: "select 1", idempotencyKey: "sql"))
                XCTFail("Expected closed SQL error")
            } catch let error as SqlExecutionError {
                XCTAssertEqual(error, expected as? SqlExecutionError)
                XCTAssertFalse(error.message.contains("SECRET"))
            } catch let error as ActivityAPIError { XCTAssertEqual(error, expected as? ActivityAPIError) }
        }
    }

    private func api(_ fixture: URLProtocolFixture) -> LiveActivityAPI {
        LiveActivityAPI(transport: .init(baseURL: URL(string: "https://api.example.test")!, session: fixture.session()))
    }

    private func receiptBody(query: String = "select 1", activityID: Int = 41, rowCount: Int = 2,
                             columns: [String] = ["value"], cell: String = "1") throws -> Data {
        try JSONSerialization.data(withJSONObject: [
            "execution_id": 1, "activity_id": activityID, "query": query,
            "query_sha256": SqlExecutionReceipt.queryHash(query),
            "result": ["columns": columns, "rows": [[cell], [NSNull()]], "elapsed_ms": 12,
                       "row_count": rowCount, "result_sha256": String(repeating: "a", count: 64),
                       "validation": "wrong_grain", "exercise_key": "fixture", "exercise_version": 1],
        ])
    }

    private func requestBody(_ request: URLRequest) throws -> Data {
        if let body = request.httpBody { return body }
        let stream = try XCTUnwrap(request.httpBodyStream)
        stream.open()
        defer { stream.close() }
        var body = Data()
        var buffer = [UInt8](repeating: 0, count: 4096)
        while true {
            let count = stream.read(&buffer, maxLength: buffer.count)
            if count == 0 { return body }
            if count < 0 { throw try XCTUnwrap(stream.streamError) }
            body.append(contentsOf: buffer.prefix(count))
        }
    }
}
