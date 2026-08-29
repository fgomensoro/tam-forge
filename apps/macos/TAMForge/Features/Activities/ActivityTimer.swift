import Foundation

struct ActivityTimerDisplay: Equatable, Sendable {
    private let focusedSeconds: Int
    private let anchoredAt: TimeInterval?

    init(activity: ActivityDetail, monotonicNow: TimeInterval = ProcessInfo.processInfo.systemUptime) {
        focusedSeconds = activity.activityFocusedSeconds
        anchoredAt = activity.state == .active ? monotonicNow : nil
    }

    func focusedSeconds(monotonicNow: TimeInterval = ProcessInfo.processInfo.systemUptime) -> Int {
        guard let anchoredAt else { return focusedSeconds }
        return focusedSeconds + max(0, Int(monotonicNow - anchoredAt))
    }
}

struct ActivityPendingHeartbeat: Codable, Equatable, Sendable {
    var clientSequence: Int
    var idempotencyKey: String
}

@MainActor
protocol ActivityTimerJournaling: AnyObject {
    func load(activityID: Int) -> ActivityPendingHeartbeat?
    func save(_ heartbeat: ActivityPendingHeartbeat, activityID: Int)
    func remove(activityID: Int)
}

@MainActor
final class InMemoryActivityTimerJournal: ActivityTimerJournaling {
    private var entries: [Int: ActivityPendingHeartbeat] = [:]

    func load(activityID: Int) -> ActivityPendingHeartbeat? { entries[activityID] }
    func save(_ heartbeat: ActivityPendingHeartbeat, activityID: Int) { entries[activityID] = heartbeat }
    func remove(activityID: Int) { entries.removeValue(forKey: activityID) }
}

@MainActor
final class UserDefaultsActivityTimerJournal: ActivityTimerJournaling {
    private let defaults: UserDefaults
    private let encoder = JSONEncoder()
    private let decoder = JSONDecoder()

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
    }

    func load(activityID: Int) -> ActivityPendingHeartbeat? {
        guard let data = defaults.data(forKey: key(activityID)) else { return nil }
        return try? decoder.decode(ActivityPendingHeartbeat.self, from: data)
    }

    func save(_ heartbeat: ActivityPendingHeartbeat, activityID: Int) {
        guard let data = try? encoder.encode(heartbeat) else { return }
        defaults.set(data, forKey: key(activityID))
    }

    func remove(activityID: Int) {
        defaults.removeObject(forKey: key(activityID))
    }

    private func key(_ activityID: Int) -> String {
        "tamforge.activity.\(activityID).pending-heartbeat.v1"
    }
}

@MainActor
final class ActivityTimerCoordinator {
    private let activityID: Int
    private let api: any ActivityAPI
    private let journal: any ActivityTimerJournaling
    private let idempotency: @Sendable () -> String

    init(
        activityID: Int,
        api: any ActivityAPI,
        journal: any ActivityTimerJournaling,
        idempotency: @escaping @Sendable () -> String = { UUID().uuidString }
    ) {
        self.activityID = activityID
        self.api = api
        self.journal = journal
        self.idempotency = idempotency
    }

    func nextSequence(for activity: ActivityDetail) -> Int {
        let server = activity.openTimer?.lastClientSequence ?? 0
        let pending = journal.load(activityID: activityID)?.clientSequence ?? 0
        return max(server, pending) + 1
    }

    func nextHeartbeatCommand(for activity: ActivityDetail) -> ActivityHeartbeatCommand {
        let pending = journal.load(activityID: activityID) ?? .init(
            clientSequence: nextSequence(for: activity),
            idempotencyKey: idempotency()
        )
        return .init(
            activityID: activityID,
            expectedVersion: activity.optimisticVersion,
            clientSequence: pending.clientSequence,
            idempotencyKey: pending.idempotencyKey
        )
    }

    func journal(_ command: ActivityHeartbeatCommand) {
        journal.save(
            .init(clientSequence: command.clientSequence, idempotencyKey: command.idempotencyKey),
            activityID: activityID
        )
    }

    func heartbeat(activity: ActivityDetail) async throws -> ActivitySummary? {
        guard activity.state == .active else { return nil }
        let command = nextHeartbeatCommand(for: activity)
        journal(command)
        do {
            let summary = try await api.heartbeat(command)
            journal.remove(activityID: activityID)
            return summary
        } catch {
            if error as? ActivityAPIError == .conflict || error as? ActivityAPIError == .unauthorized {
                journal.remove(activityID: activityID)
            }
            throw error
        }
    }

    func clearPending() {
        journal.remove(activityID: activityID)
    }
}
