import Combine
import Foundation

enum ShellRoute: Equatable, Sendable {
    case today
    case roadmaps
    case activity(Int)

    var restorationID: String {
        switch self {
        case .roadmaps:
            "roadmaps"
        case .today, .activity:
            "today"
        }
    }

    static func restored(from identifier: String) -> Self {
        identifier == "roadmaps" ? .roadmaps : .today
    }
}

enum SignedOutReason: Equatable, Sendable {
    case signedOut
    case sessionExpired
}

enum ShellSessionPhase: Equatable, Sendable {
    case loading
    case signedOut(SignedOutReason)
    case signedIn(String)
}

struct ShellSessionActions: Sendable {
    let restore: @Sendable () async throws -> String
    let login: @Sendable () async throws -> String
    let localLogout: @Sendable () throws -> Void
    let logout: @Sendable () async -> Void
}

@MainActor
final class ShellSessionModel: ObservableObject {
    private static let maximumStatusHistory = 50

    @Published private(set) var phase: ShellSessionPhase
    @Published private(set) var selectedRoute: ShellRoute = .today
    @Published private(set) var statusHistory: [StatusEvent] = []
    @Published private(set) var banner: GlobalBanner?
    @Published private(set) var isStatusStreamActive = false
    @Published private(set) var statusState: StatusStreamState = .connecting
    @Published private(set) var featureRefreshVersion = 0

    private let actions: ShellSessionActions
    private let statusStream: StatusStreamClient?
    private var statusTask: Task<Void, Never>?
    private var authenticationGeneration = 0

    init(
        actions: ShellSessionActions,
        statusStream: StatusStreamClient?,
        initialPhase: ShellSessionPhase = .loading,
        initialBanner: GlobalBanner? = nil
    ) {
        self.actions = actions
        self.statusStream = statusStream
        phase = initialPhase
        banner = initialBanner
    }

    func restore() async {
        guard case .loading = phase else { return }
        let generation = authenticationGeneration
        do {
            let login = try await actions.restore()
            guard generation == authenticationGeneration else { return }
            phase = .signedIn(login)
            startStatusStream()
        } catch {
            guard generation == authenticationGeneration else { return }
            enterSignedOut(reason: .signedOut, banner: nil, revokingCredentials: false)
        }
    }

    func signIn() async {
        guard case .signedOut = phase else { return }
        authenticationGeneration += 1
        let generation = authenticationGeneration
        phase = .loading
        do {
            let login = try await actions.login()
            guard generation == authenticationGeneration else { return }
            clearSensitiveFeatureState()
            phase = .signedIn(login)
            banner = nil
            startStatusStream()
        } catch {
            guard generation == authenticationGeneration else { return }
            enterSignedOut(reason: .signedOut, banner: .actionRequired, revokingCredentials: false)
        }
    }

    func signOut() {
        enterSignedOut(reason: .signedOut, banner: nil, revokingCredentials: true)
    }

    func unauthorizedHandlerForCurrentSession() -> NativeUnauthorizedHandler {
        let generation = authenticationGeneration
        return { [weak self] in
            Task { @MainActor in self?.receive(.unauthorized, generation: generation) }
        }
    }

    func select(_ route: ShellRoute) {
        selectedRoute = route
    }

    func restoreRoute(from identifier: String) {
        selectedRoute = .restored(from: identifier)
    }

    var restorationRouteID: String {
        selectedRoute.restorationID
    }

    func receive(_ event: StatusEvent, generation: Int? = nil) {
        if let generation, generation != authenticationGeneration { return }
        guard case .signedIn = phase else { return }
        featureRefreshVersion += 1
        statusHistory.append(event)
        if statusHistory.count > Self.maximumStatusHistory {
            statusHistory.removeFirst(statusHistory.count - Self.maximumStatusHistory)
        }

        if event.eventType.contains("failure") || event.eventType.contains("action") {
            banner = .actionRequired
        } else if event.eventType.contains("processing") {
            banner = .processing
        }
    }

    func receive(_ state: StatusStreamState, generation: Int? = nil) {
        if let generation, generation != authenticationGeneration { return }
        guard case .signedIn = phase else { return }
        statusState = state
        if state == .retrying || state == .live { featureRefreshVersion += 1 }
        switch state {
        case .connecting, .live:
            if state == .live { banner = nil }
        case .offline:
            banner = .offline
        case .retrying:
            banner = .retrying
        case .unauthorized:
            enterSignedOut(reason: .sessionExpired, banner: .permission, revokingCredentials: true)
        }
    }

    deinit {
        statusTask?.cancel()
    }

    private func startStatusStream() {
        guard statusTask == nil, let statusStream else { return }
        isStatusStreamActive = true
        let generation = authenticationGeneration
        statusTask = Task { [weak self, statusStream] in
            await statusStream.run(
                onEvent: { [weak self] event in
                    await self?.receive(event, generation: generation)
                },
                onState: { [weak self] state in
                    await self?.receive(state, generation: generation)
                }
            )
        }
    }

    private func enterSignedOut(
        reason: SignedOutReason,
        banner: GlobalBanner?,
        revokingCredentials: Bool
    ) {
        if revokingCredentials {
            do {
                try actions.localLogout()
            } catch {
                self.banner = .actionRequired
                return
            }
        }
        authenticationGeneration += 1
        statusTask?.cancel()
        statusTask = nil
        isStatusStreamActive = false
        clearSensitiveFeatureState()
        phase = .signedOut(reason)
        self.banner = banner
        if revokingCredentials {
            Task { [actions] in await actions.logout() }
        }
    }

    private func clearSensitiveFeatureState() {
        statusHistory.removeAll(keepingCapacity: false)
        featureRefreshVersion = 0
        statusState = .connecting
        selectedRoute = .today
    }
}
