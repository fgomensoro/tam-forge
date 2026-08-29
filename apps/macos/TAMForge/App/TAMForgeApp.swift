import SwiftUI

@main
struct TAMForgeApp: App {
    let dependencies: AppDependencies

    init() {
        let arguments = ProcessInfo.processInfo.arguments
#if DEBUG
        let nativeFeatures: Set<NativeFeature> = arguments.contains("-ui-test-native-features")
            ? [.today, .roadmaps]
            : []
#else
        let nativeFeatures: Set<NativeFeature> = []
#endif
        self.init(
            dependencies: .live(
                environment: .selected(from: ProcessInfo.processInfo.environment),
                nativeFeatures: nativeFeatures
            )
        )
    }

    init(dependencies: AppDependencies) {
        self.dependencies = dependencies
    }

    var body: some Scene {
        WindowGroup {
            NativeShellView(dependencies: dependencies)
        }
    }
}

private struct NativeShellView: View {
    let dependencies: AppDependencies
    @StateObject private var model: ShellSessionModel
    @SceneStorage("tamforge.shell.route") private var restoredRouteID = "today"
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    init(dependencies: AppDependencies) {
        self.dependencies = dependencies
        _model = StateObject(wrappedValue: Self.makeModel(dependencies: dependencies))
    }

    var body: some View {
        Group {
            switch model.phase {
            case .loading:
                ProgressView("Checking your secure session")
                    .accessibilityIdentifier("sessionLoading")
            case .signedOut:
                signedOutView
            case .signedIn:
                signedInView
            }
        }
        .padding(24)
        .frame(minWidth: 720, minHeight: 460)
        .task {
            model.restoreRoute(from: restoredRouteID)
            await model.restore()
        }
        .onChange(of: model.restorationRouteID) { _, routeID in
            restoredRouteID = routeID
        }
        .animation(reduceMotion ? nil : .easeInOut(duration: 0.2), value: model.banner)
    }

    private var signedOutView: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("TAM Forge")
                .font(.largeTitle)
                .accessibilityIdentifier("shellTitle")
            Text(dependencies.environment.displayName)
                .accessibilityIdentifier("environmentLabel")
            Text("Sign in to continue your study workspace.")
            if let banner = model.banner {
                GlobalBannerView(banner: banner)
            }
            Button("Sign in") {
                Task { await model.signIn() }
            }
            .accessibilityIdentifier("signInButton")
            .keyboardShortcut(.defaultAction)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
    }

    private var signedInView: some View {
        NavigationSplitView {
            List {
                if dependencies.nativeFeatures.contains(.today) {
                    Button {
                        model.select(.today)
                    } label: {
                        Label("Today", systemImage: "sun.max")
                    }
                    .accessibilityIdentifier("todayNavigation")
                }

                if dependencies.nativeFeatures.contains(.roadmaps) {
                    Button {
                        model.select(.roadmaps)
                    } label: {
                        Label("Roadmaps", systemImage: "map")
                    }
                    .accessibilityIdentifier("roadmapsNavigation")
                }
            }
            .navigationTitle("TAM Forge")
        } detail: {
            VStack(alignment: .leading, spacing: 16) {
                HStack {
                    Text(dependencies.environment.displayName)
                        .accessibilityIdentifier("environmentLabel")
                    Spacer()
                    Button("Sign out") { model.signOut() }
                        .accessibilityIdentifier("signOutButton")
                }
                if let banner = model.banner {
                    GlobalBannerView(banner: banner)
                }
                routeDetail
            }
            .padding(.leading, 12)
        }
    }

    @ViewBuilder
    private var routeDetail: some View {
        if !isAvailable(model.selectedRoute) {
            ContentUnavailableView(
                "Native features are being prepared.",
                systemImage: "hammer"
            )
            .accessibilityIdentifier("noNativeFeatures")
        } else {
            availableRouteDetail
        }
    }

    @ViewBuilder
    private var availableRouteDetail: some View {
        switch model.selectedRoute {
        case .today:
            Text("Today")
                .font(.largeTitle)
            if model.statusHistory.isEmpty {
                ContentUnavailableView("No status updates yet.", systemImage: "bell")
                    .accessibilityIdentifier("statusEmpty")
            } else {
                List(model.statusHistory) { event in
                    HStack {
                        Text(event.eventType.replacingOccurrences(of: "_", with: " "))
                        Spacer()
                        if event.aggregateType == "activity" {
                            Button("Open activity") { model.select(.activity(event.aggregateID)) }
                                .accessibilityLabel("Open related activity")
                        }
                    }
                }
            }
        case .roadmaps:
            Text("Roadmaps")
                .font(.largeTitle)
        case let .activity(identifier):
            Text("Activity")
                .font(.largeTitle)
            Text("Activity \(identifier)")
            Button("Back to Today") { model.select(.today) }
        }
    }

    private func isAvailable(_ route: ShellRoute) -> Bool {
        switch route {
        case .today, .activity:
            dependencies.nativeFeatures.contains(.today)
        case .roadmaps:
            dependencies.nativeFeatures.contains(.roadmaps)
        }
    }

    @MainActor
    private static func makeModel(dependencies: AppDependencies) -> ShellSessionModel {
#if DEBUG
        let arguments = ProcessInfo.processInfo.arguments
        if arguments.contains("-ui-test-signed-out") {
            return ShellSessionModel(
                actions: .uiTest,
                statusStream: nil,
                initialPhase: .signedOut(.signedOut)
            )
        }
        if arguments.contains("-ui-test-signed-in") {
            return ShellSessionModel(
                actions: .uiTest,
                statusStream: nil,
                initialPhase: .signedIn("UI test"),
                initialBanner: arguments.contains("-ui-test-offline") ? .offline : nil
            )
        }
#endif
        let credentialStore = KeychainCredentialStore()
        let authentication = NativeAuthenticationCoordinator(
            http: LiveNativeAuthHTTPClient(baseURL: dependencies.environment.apiBaseURL),
            credentialStore: credentialStore,
            oauthSession: SystemOAuthSession()
        )
        let stream = StatusStreamClient(
            baseURL: dependencies.environment.apiBaseURL,
            bearerToken: { try await authentication.currentAccessToken() },
            fallbackPoll: dependencies.makeStatusFallbackPoller {
                try? await authentication.currentAccessToken()
            }
        )
        return ShellSessionModel(
            actions: ShellSessionActions(
                restore: { _ = try await authentication.currentAccessToken(); return "Signed in" },
                login: { try await authentication.login() },
                localLogout: { try quarantineActiveRefreshCredential(in: credentialStore) },
                logout: { try? await authentication.logout() }
            ),
            statusStream: stream
        )
    }
}

private extension ShellSessionActions {
    static let uiTest = Self(
        restore: { "UI test" },
        login: { "UI test" },
        localLogout: {},
        logout: {}
    )
}
