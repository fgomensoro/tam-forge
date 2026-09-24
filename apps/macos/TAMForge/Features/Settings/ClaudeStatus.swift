import Foundation

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
        case .tokenRefused: "Token expired or refused"
        case .quotaSpent: "Quota spent"
        case .disabled: "Disabled on the server"
        case .notReporting: "Worker not reporting"
        case .serviceProblem: "Service problem"
        }
    }

    var detail: String {
        switch self {
        case .ready: "The server's Claude worker is running with a valid token."
        case .tokenRefused: "Rotate the token with the command below."
        case .quotaSpent: "The subscription quota is used up. Wait for it to reset; a new token does not help."
        case .disabled: "Claude is off or has no current privacy attestation on the server."
        case .notReporting: "The Claude worker has not sent a heartbeat in the last minute."
        case .serviceProblem: "The worker is up but its compatibility check failed. Check its logs on the host."
        }
    }
}

@MainActor
protocol ClaudeStatusAPI {
    func claudeState() async throws -> ClaudeTokenState
}

@MainActor
final class LiveClaudeStatusAPI: ClaudeStatusAPI {
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
}

private struct OperationalStatus: Decodable, Sendable {
    struct Component: Decodable, Sendable {
        let status: String
        let reason: String
    }

    let components: [String: Component]
}

@MainActor
final class ClaudeSettingsModel: ObservableObject {
    static let rotateCommand = "make rotate-claude-token"

    @Published private(set) var state: ClaudeTokenState?
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
            state = try await api.claudeState()
            errorMessage = nil
        } catch {
            state = nil
            errorMessage = "Could not read the server status. Try again."
        }
    }
}
