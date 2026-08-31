import XCTest

final class AppDependenciesTests: XCTestCase {
    func testNativeFeatureSetIncludesEvidenceWithoutChangingEnvironment() {
        let features: Set<NativeFeature> = [.today, .roadmaps, .evidence]
        let dependencies = AppDependencies.live(environment: .preview, nativeFeatures: features)

        XCTAssertEqual(dependencies.nativeFeatures, features)
        XCTAssertEqual(dependencies.api.baseURL.host, "api-preview.tamforge.invalid")
    }

    func testPreviewEnvironmentSelectsPreviewServices() async {
        let dependencies = AppDependencies.live(environment: .preview)

        XCTAssertEqual(dependencies.environment, .preview)
        XCTAssertTrue(dependencies.nativeFeatures.isEmpty)
        XCTAssertEqual(dependencies.api.baseURL.host, "api-preview.tamforge.invalid")
        let authenticationState = await dependencies.authentication.currentState()
        let serviceStatus = await dependencies.status.currentStatus()
        XCTAssertEqual(authenticationState, .unavailable)
        XCTAssertEqual(serviceStatus, .unavailable)
    }

    func testStatusFallbackDoesNotSendWithoutAnAccessToken() async {
        let recorder = StatusFallbackRecorder()
        let poll = AppDependencies.live(environment: .preview).makeStatusFallbackPoller(
            accessToken: { nil },
            send: { token in await recorder.record(token) }
        )

        await poll()

        let tokens = await recorder.tokens
        XCTAssertEqual(tokens, [])
    }

    @MainActor
    func testEnvironmentSelectionRedactsProcessSecretsFromDiagnostics() {
        let token = "test-token-must-not-appear"
        let environment = AppEnvironment.selected(
            from: ["TAMFORGE_ENV": "preview", "TAMFORGE_API_TOKEN": token]
        )
        let dependencies = AppDependencies.live(environment: environment)

        XCTAssertEqual(dependencies.environment, .preview)
        XCTAssertFalse(dependencies.diagnosticSummary.contains(token))
        XCTAssertEqual(
            dependencies.diagnosticSummary,
            "Environment: Preview environment. Authentication: unavailable. Service status: unavailable."
        )
    }

    func testContainerAcceptsProtocolServicesWithoutGlobalState() async {
        let dependencies = AppDependencies(
            environment: .preview,
            api: StubAPIService(),
            authentication: StubAuthenticationService(),
            status: StubStatusService()
        )

        XCTAssertEqual(dependencies.api.baseURL.host, "test.invalid")
        let authenticationState = await dependencies.authentication.currentState()
        let serviceStatus = await dependencies.status.currentStatus()
        XCTAssertEqual(authenticationState, .unavailable)
        XCTAssertEqual(serviceStatus, .unavailable)
    }
}

private actor StatusFallbackRecorder {
    private(set) var tokens: [String] = []

    func record(_ token: String) {
        tokens.append(token)
    }
}

private struct StubAPIService: APIService {
    let baseURL = URL(string: "https://test.invalid")!
}

private struct StubAuthenticationService: AuthenticationService {
    func currentState() async -> AuthenticationState {
        .unavailable
    }
}

private struct StubStatusService: StatusService {
    func currentStatus() async -> ServiceStatus {
        .unavailable
    }
}
