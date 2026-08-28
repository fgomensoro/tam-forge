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

struct AppDependencies: Sendable {
    let environment: AppEnvironment
    let api: any APIService
    let authentication: any AuthenticationService
    let status: any StatusService

    static func live(environment: AppEnvironment) -> Self {
        Self(
            environment: environment,
            api: UnconfiguredAPIService(baseURL: environment.apiBaseURL),
            authentication: UnconfiguredAuthenticationService(),
            status: UnconfiguredStatusService()
        )
    }

    var diagnosticSummary: String {
        "Environment: \(environment.displayName). Authentication: unavailable. Service status: unavailable."
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
