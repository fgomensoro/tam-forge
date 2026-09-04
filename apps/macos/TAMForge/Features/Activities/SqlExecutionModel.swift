import Combine
import Foundation

/// Owns immutable receipts and retry identity; learner evidence belongs to the workspace.
@MainActor
final class SqlExecutionModel: ObservableObject {
    @Published private(set) var history: [SqlExecutionReceipt] = []
    @Published private(set) var isRunning = false
    @Published private(set) var isLoadingHistory = false
    @Published private(set) var errorMessage: String?

    private let api: any ActivityAPI
    private var pending: SqlExecutionCommand?
    private var cancelWork: (() -> Void)?
    private var lifetime = 0

    init(api: any ActivityAPI) { self.api = api }

    static func queryReason(_ query: String) -> String? {
        if query.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { return "Enter a query to run." }
        if query.utf8.count > 64 * 1024 { return "Run accepts up to 64 KiB of SQL. The saved query has not been shortened." }
        return nil
    }

    func queryDidChange(_ query: String) {
        if pending?.query != query { pending = nil }
    }

    func run(activityID: Int, expectedVersion: Int, query: String) async throws {
        guard !isRunning, !isLoadingHistory, Self.queryReason(query) == nil else { return }
        queryDidChange(query)
        let command = pending ?? .init(activityID: activityID, expectedVersion: expectedVersion,
                                       query: query, idempotencyKey: UUID().uuidString)
        pending = command
        isRunning = true
        errorMessage = nil
        let generation = lifetime
        let task = Task { try Task.checkCancellation(); return try await api.executeSQL(command) }
        cancelWork = { task.cancel() }
        defer {
            if generation == lifetime { isRunning = false; cancelWork = nil }
        }
        do {
            let receipt = try await withTaskCancellationHandler { try await task.value } onCancel: { task.cancel() }
            guard generation == lifetime, !Task.isCancelled, !task.isCancelled else { return }
            guard receipt.activityID == command.activityID, receipt.query == command.query,
                  receipt.querySHA256 == SqlExecutionReceipt.queryHash(command.query) else {
                throw SqlExecutionError.invalidResponse
            }
            history = Array(([receipt] + history.filter { $0.id != receipt.id }).prefix(20))
            while history.reduce(0, { $0 + $1.historyByteCount }) > 1024 * 1024 { history.removeLast() }
            if pending == command { pending = nil }
        } catch {
            guard generation == lifetime, !Task.isCancelled, !task.isCancelled else { return }
            if error as? ActivityAPIError == .unauthorized { throw error }
            if error as? ActivityAPIError == .conflict {
                if pending == command { pending = nil }
                errorMessage = "The activity changed. Server state is reloading; your working output is preserved."
                throw error
            }
            if error is CancellationError || error as? ActivityAPIError == .cancelled { return }
            let sqlError = error as? SqlExecutionError ?? .network
            // Only an explicit rejection is a confirmed terminal request. Network,
            // availability, busy and malformed receipts retain the entire original body.
            if sqlError == .queryRejected, pending == command { pending = nil }
            errorMessage = sqlError.message
        }
    }

    func loadHistory(activityID: Int) async throws {
        guard !isRunning, !isLoadingHistory else { return }
        isLoadingHistory = true
        let generation = lifetime
        let task = Task { try Task.checkCancellation(); return try await api.fetchSQLHistory(activityID: activityID) }
        cancelWork = { task.cancel() }
        defer {
            if generation == lifetime { isLoadingHistory = false; cancelWork = nil }
        }
        do {
            let items = try await withTaskCancellationHandler { try await task.value } onCancel: { task.cancel() }
            guard generation == lifetime, !Task.isCancelled, !task.isCancelled else { return }
            guard items.count <= 20, items.allSatisfy({ $0.activityID == activityID }),
                  Set(items.map(\.id)).count == items.count else { throw SqlExecutionError.invalidResponse }
            history = items
            errorMessage = nil
        } catch {
            guard generation == lifetime, !Task.isCancelled, !task.isCancelled else { return }
            if error as? ActivityAPIError == .unauthorized { throw error }
            if error is CancellationError || error as? ActivityAPIError == .cancelled { return }
            errorMessage = (error as? SqlExecutionError ?? .network).message
        }
    }

    func invalidate(clearHistory: Bool = false) {
        lifetime += 1
        cancelWork?()
        cancelWork = nil
        isRunning = false
        isLoadingHistory = false
        if clearHistory {
            history = []
            pending = nil
            errorMessage = nil
        }
    }
}
