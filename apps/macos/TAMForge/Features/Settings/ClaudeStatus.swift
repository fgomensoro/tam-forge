import Foundation

/// Which of the two tokens installed on the server the Claude worker uses.
enum ClaudeTokenSlot: String, CaseIterable, Codable, Sendable {
    case a, b

    var label: String { "Slot \(rawValue.uppercased())" }
}

/// The `claude` component of `GET /ops/status`, as the Settings pane shows it.
/// The server's closed reason vocabulary lives in observability/logging.py.
enum ClaudeTokenState: Equatable, Sendable {
    case ready
    case tokenRefused
    case quotaSpent
    case disabled
    case notReporting
    case serviceProblem

    init(status: String, reason: String) {
        switch (status, reason) {
        case ("ok", _): self = .ready
        case (_, "auth"): self = .tokenRefused
        case (_, "quota"): self = .quotaSpent
        case (_, "permission_required"): self = .disabled
        case (_, "stale"), (_, "not_observed"): self = .notReporting
        default: self = .serviceProblem
        }
    }

    var title: String {
        switch self {
        case .ready: "Ready"
        case .tokenRefused: "Token missing or refused"
        case .quotaSpent: "Quota spent"
        case .disabled: "Disabled on the server"
        case .notReporting: "Worker not reporting"
        case .serviceProblem: "Service problem"
        }
    }

    var detail: String {
        switch self {
        case .ready: "The server's Claude worker is running with a valid token."
        case .tokenRefused: "Install or rotate this slot's token with the command below."
        case .quotaSpent: "This slot's quota is used up. Switch to the other slot or wait for the reset."
        case .disabled: "Claude is off, has no current privacy attestation, or the worker sees a credential other than the subscription token."
        case .notReporting: "The Claude worker has not sent a heartbeat in the last minute."
        case .serviceProblem: "The worker is up but its last step failed. Check its logs on the host."
        }
    }
}

@MainActor
protocol ClaudeStatusAPI {
    func claudeState() async throws -> ClaudeTokenState
    func activeSlot() async throws -> ClaudeTokenSlot
    func chooseSlot(_ slot: ClaudeTokenSlot) async throws
}

@MainActor
final class LiveClaudeStatusAPI: ClaudeStatusAPI {
    private static let slotPath = "/ops/claude/slot"

    private let transport: NativeAPITransport

    init(transport: NativeAPITransport) {
        self.transport = transport
    }

    func claudeState() async throws -> ClaudeTokenState {
        let snapshot = try await transport.send(.init(method: .get, path: "/ops/status"))
            .decoded(as: OperationalStatus.self)
        guard let claude = snapshot.components["claude"] else { return .notReporting }
        return ClaudeTokenState(status: claude.status, reason: claude.reason)
    }

    func activeSlot() async throws -> ClaudeTokenSlot {
        try await transport.send(.init(method: .get, path: Self.slotPath))
            .decoded(as: SlotChoice.self).slot
    }

    /// Sends only the slot name; the tokens stay on the server.
    func chooseSlot(_ slot: ClaudeTokenSlot) async throws {
        let body = try JSONEncoder().encode(SlotChoice(slot: slot))
        _ = try await transport.send(.init(method: .put, path: Self.slotPath, body: body))
    }
}

private struct OperationalStatus: Decodable, Sendable {
    struct Component: Decodable, Sendable {
        let status: String
        let reason: String
    }

    let components: [String: Component]
}

private struct SlotChoice: Codable, Sendable {
    let slot: ClaudeTokenSlot
}

@MainActor
final class ClaudeSettingsModel: ObservableObject {
    static func rotateCommand(for slot: ClaudeTokenSlot) -> String {
        "make rotate-claude-token SLOT=\(slot.rawValue)"
    }

    @Published private(set) var state: ClaudeTokenState?
    @Published private(set) var slot: ClaudeTokenSlot?
    /// Set right after a switch: the worker picks the new slot up on its next beat, so the
    /// status read at that moment would still describe the previous slot.
    @Published private(set) var switchedSlot: ClaudeTokenSlot?
    @Published private(set) var errorMessage: String?
    @Published private(set) var isLoading = false

    private let api: any ClaudeStatusAPI

    init(api: any ClaudeStatusAPI) {
        self.api = api
    }

    func refresh() async {
        isLoading = true
        defer { isLoading = false }
        do {
            slot = try await api.activeSlot()
            state = try await api.claudeState()
            switchedSlot = nil
            errorMessage = nil
        } catch {
            slot = nil
            state = nil
            switchedSlot = nil
            errorMessage = "Could not read the server status. Try again."
        }
    }

    func choose(_ newSlot: ClaudeTokenSlot) async {
        guard newSlot != slot else { return }
        isLoading = true
        defer { isLoading = false }
        do {
            try await api.chooseSlot(newSlot)
            slot = newSlot
            switchedSlot = newSlot
            state = nil
            errorMessage = nil
        } catch {
            errorMessage = "Could not switch the slot. Try again."
        }
    }
}
