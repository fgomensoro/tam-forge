import Foundation

enum AppEnvironment: Equatable, Sendable {
    case production
    case preview

    static func selected(from environment: [String: String]) -> Self {
        environment["TAMFORGE_ENV"]?.lowercased() == "preview" ? .preview : .production
    }

    var displayName: String {
        switch self {
        case .production:
            "Production environment"
        case .preview:
            "Preview environment"
        }
    }

    var apiBaseURL: URL {
        switch self {
        case .production:
            URL(string: "https://api.tamforge.invalid")!
        case .preview:
            URL(string: "https://api-preview.tamforge.invalid")!
        }
    }
}

protocol APIService: Sendable {
    var baseURL: URL { get }
}

protocol AuthenticationService: Sendable {
    func currentState() async -> AuthenticationState
}

protocol StatusService: Sendable {
    func currentStatus() async -> ServiceStatus
}

enum AuthenticationState: Equatable, Sendable {
    case unavailable
}

enum ServiceStatus: Equatable, Sendable {
    case unavailable

    var diagnosticText: String {
        switch self {
        case .unavailable:
            "Service status unavailable"
        }
    }
}

enum NativeFeature: Hashable, Sendable {
    case today
    case roadmaps
    case evidence
}

struct AppDependencies: Sendable {
    let environment: AppEnvironment
    let api: any APIService
    let authentication: any AuthenticationService
    let status: any StatusService
    let nativeFeatures: Set<NativeFeature>

    init(
        environment: AppEnvironment,
        api: any APIService,
        authentication: any AuthenticationService,
        status: any StatusService,
        nativeFeatures: Set<NativeFeature> = []
    ) {
        self.environment = environment
        self.api = api
        self.authentication = authentication
        self.status = status
        self.nativeFeatures = nativeFeatures
    }

    static func live(
        environment: AppEnvironment,
        nativeFeatures: Set<NativeFeature> = []
    ) -> Self {
        Self(
            environment: environment,
            api: UnconfiguredAPIService(baseURL: environment.apiBaseURL),
            authentication: UnconfiguredAuthenticationService(),
            status: UnconfiguredStatusService(),
            nativeFeatures: nativeFeatures
        )
    }

    var diagnosticSummary: String {
        "Environment: \(environment.displayName). Authentication: unavailable. Service status: unavailable."
    }

    /// The shell polls only a bounded notification summary while live SSE reconnects.
    /// It keeps server state authoritative and does not persist response bodies locally.
    func makeStatusFallbackPoller(
        accessToken: @escaping @Sendable () async -> String?,
        send: (@Sendable (String) async -> Void)? = nil
    ) -> @Sendable () async -> Void {
        let environment = environment
        return {
            guard let token = await accessToken(), !token.isEmpty else { return }
            if let send {
                await send(token)
                return
            }
            let transport = NativeAPITransport(
                environment: environment,
                bearerToken: { token }
            )
            _ = try? await transport.send(
                NativeAPIRequest(method: .get, path: "/api/v1/notifications?limit=1")
            )
        }
    }
}

private struct UnconfiguredAPIService: APIService {
    let baseURL: URL
}

private struct UnconfiguredAuthenticationService: AuthenticationService {
    func currentState() async -> AuthenticationState {
        .unavailable
    }
}

private struct UnconfiguredStatusService: StatusService {
    func currentStatus() async -> ServiceStatus {
        .unavailable
    }
}
