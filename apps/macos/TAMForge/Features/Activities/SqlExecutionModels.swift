import CryptoKit
import Foundation

struct SqlExecutionCommand: Equatable, Sendable {
    let activityID: Int
    let expectedVersion: Int
    let query: String
    let idempotencyKey: String

    static func == (lhs: Self, rhs: Self) -> Bool {
        lhs.activityID == rhs.activityID && lhs.expectedVersion == rhs.expectedVersion
            && lhs.query.utf8.elementsEqual(rhs.query.utf8)
            && lhs.idempotencyKey.utf8.elementsEqual(rhs.idempotencyKey.utf8)
    }
}

enum SqlExecutionError: Error, Equatable, Sendable {
    case unavailable, busy, queryRejected, network, invalidResponse

    var message: String {
        switch self {
        case .unavailable: "SQL execution is unavailable for this activity. Your working output is preserved."
        case .busy: "The SQL runner is busy. Try again shortly."
        case .queryRejected: "The query could not produce a supported result within the execution limits. Review it and try again."
        case .network: "SQL execution was not confirmed. Retry to check the same request. Your working output is preserved."
        case .invalidResponse: "The SQL response could not be verified. Your working output is preserved."
        }
    }
}

enum SqlValidation: String, Equatable, Sendable {
    case matched, mismatch
    case wrongGrain = "wrong_grain"

    var title: String {
        switch self {
        case .matched: "Matched expected result"
        case .mismatch: "Result mismatch"
        case .wrongGrain: "Wrong result grain"
        }
    }
}

struct SqlExecutionResult: Equatable, Sendable {
    let columns: [String]
    let rows: [[String?]]
    let elapsedMS: Int
    let rowCount: Int
    let resultSHA256: String
    let validation: SqlValidation
    let exerciseKey: String
    let exerciseVersion: Int

    func encodedRows(prettyPrinted: Bool = false) throws -> Data {
        let cells: [[Any]] = rows.map { $0.map { $0.map { $0 as Any } ?? NSNull() } }
        return try JSONSerialization.data(withJSONObject: ["columns": columns, "rows": cells],
                                          options: prettyPrinted ? [.prettyPrinted, .withoutEscapingSlashes] : [.withoutEscapingSlashes])
    }

    var displayText: String {
        guard let data = try? encodedRows(prettyPrinted: true), let text = String(data: data, encoding: .utf8) else { return "Result unavailable." }
        return text
    }
}

struct SqlExecutionReceipt: Identifiable, Equatable, Sendable {
    let executionID: Int
    let activityID: Int
    let query: String
    let querySHA256: String
    let result: SqlExecutionResult

    var id: Int { executionID }

    // Account for JSON escaping when bounding accumulated in-memory history.
    var historyByteCount: Int {
        guard let queryBytes = try? JSONSerialization.data(withJSONObject: [query]),
              let resultBytes = try? result.encodedRows() else { return 1024 * 1024 }
        return queryBytes.count + resultBytes.count + result.exerciseKey.utf8.count + 1024
    }

    static func queryHash(_ query: String) -> String {
        SHA256.hash(data: Data(query.utf8)).map { String(format: "%02x", $0) }.joined()
    }
}

extension ActivityAPI {
    func executeSQL(_ command: SqlExecutionCommand) async throws -> SqlExecutionReceipt {
        throw SqlExecutionError.unavailable
    }

    func fetchSQLHistory(activityID: Int) async throws -> [SqlExecutionReceipt] {
        throw SqlExecutionError.unavailable
    }
}
