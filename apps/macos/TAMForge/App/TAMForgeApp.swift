import Darwin
import SwiftUI

@main
struct TAMForgeApp: App {
    let dependencies: AppDependencies

    init() {
        // One startup sweep; live uploads are protected by their OS-held file locks.
        _ = try? ActivityStagedFileStore().cleanupAbandonedCopies()
#if DEBUG
        LocalResourceSampler.startIfRequested()
        let arguments = ProcessInfo.processInfo.arguments
        let nativeFeatures: Set<NativeFeature> = arguments.contains("-ui-test-signed-in")
            && !arguments.contains("-ui-test-native-features") ? [] : [.today, .roadmaps, .evidence]
#else
        let nativeFeatures: Set<NativeFeature> = [.today, .roadmaps, .evidence]
#endif
        self.init(dependencies: .live(
            environment: .selected(from: ProcessInfo.processInfo.environment),
            nativeFeatures: nativeFeatures
        ))
    }

    init(dependencies: AppDependencies) { self.dependencies = dependencies }

    var body: some Scene {
        // One workspace owns the authenticated session and its private in-memory drafts.
        Window("TAM Forge", id: "main") { NativeShellView(dependencies: dependencies) }
    }
}

#if DEBUG
private enum LocalResourceSampler {
    static func startIfRequested(
        environment: [String: String] = ProcessInfo.processInfo.environment
    ) {
        guard let path = environment["TAMFORGE_RESOURCE_RECEIPT_SAMPLES_PATH"] else { return }
        let url = URL(fileURLWithPath: path)
        try? FileManager.default.removeItem(at: url)
        FileManager.default.createFile(atPath: path, contents: nil)

        Task.detached(priority: .utility) {
            guard let handle = try? FileHandle(forWritingTo: url) else { return }
            defer { try? handle.close() }
            while !Task.isCancelled {
                if let rssKiB = residentMemoryKiB() {
                    try? handle.write(contentsOf: Data("\(rssKiB)\n".utf8))
                }
                try? await Task.sleep(for: .seconds(1))
            }
        }
    }

    private static func residentMemoryKiB() -> Int? {
        var info = mach_task_basic_info()
        var count = mach_msg_type_number_t(
            MemoryLayout<mach_task_basic_info>.size / MemoryLayout<natural_t>.size
        )
        let status = withUnsafeMutablePointer(to: &info) { pointer in
            pointer.withMemoryRebound(to: integer_t.self, capacity: Int(count)) {
                task_info(
                    mach_task_self_, task_flavor_t(MACH_TASK_BASIC_INFO), $0, &count
                )
            }
        }
        guard status == KERN_SUCCESS else { return nil }
        return Int(info.resident_size / 1024)
    }
}
#endif

private struct NativeShellView: View {
    let dependencies: AppDependencies
    @StateObject private var composition: NativeShellComposition

    init(dependencies: AppDependencies) {
        self.dependencies = dependencies
        _composition = StateObject(wrappedValue: NativeShellComposition(dependencies: dependencies))
    }

    var body: some View {
        NativeSessionView(dependencies: dependencies, model: composition.session, services: composition.services)
    }
}

private struct NativeSessionView: View {
    let dependencies: AppDependencies
    @ObservedObject var model: ShellSessionModel
    let services: NativeFeatureServices
    @SceneStorage("tamforge.shell.route") private var restoredRouteID = "today"
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        Group {
            switch model.phase {
            case .loading:
                ProgressView("Checking your secure session").accessibilityIdentifier("sessionLoading")
            case .signedOut:
                VStack(alignment: .leading, spacing: 16) {
                    Text("TAM Forge").font(.largeTitle).accessibilityIdentifier("shellTitle")
                    Text(dependencies.environment.displayName).accessibilityIdentifier("environmentLabel")
                    Text("Sign in to continue your study workspace.")
                    if let banner = model.banner { GlobalBannerView(banner: banner) }
                    Button("Sign in") { Task { await model.signIn() } }
                        .accessibilityIdentifier("signInButton")
                        .keyboardShortcut(.defaultAction)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            case .signedIn:
                NativeWorkspaceView(dependencies: dependencies, session: model, services: services)
            }
        }
        .padding(24)
        .frame(minWidth: 900, minHeight: 640)
        .task {
            model.restoreRoute(from: restoredRouteID)
            await model.restore()
        }
        .onChange(of: model.restorationRouteID) { _, value in restoredRouteID = value }
        .animation(reduceMotion ? nil : .easeInOut(duration: 0.2), value: model.banner)
    }
}

@MainActor
private struct NativeFeatureServices {
    let today: any TodayServicing
    let notifications: any NotificationServicing
    let roadmaps: any RoadmapServicing
    let activities: any ActivityAPI
    let evidence: any EvidenceServicing
}

@MainActor
private final class NativeShellComposition: ObservableObject {
    let session: ShellSessionModel
    let services: NativeFeatureServices

    init(dependencies: AppDependencies) {
        let bearerToken: NativeBearerTokenProvider
        let httpSession: URLSession?
#if DEBUG
        let arguments = ProcessInfo.processInfo.arguments
        if arguments.contains("-ui-test-signed-out") || arguments.contains("-ui-test-signed-in") {
            session = ShellSessionModel(
                actions: .init(restore: { "UI test" }, login: { "UI test" }, localLogout: {}, logout: {}),
                statusStream: nil,
                initialPhase: arguments.contains("-ui-test-signed-out") ? .signedOut(.signedOut) : .signedIn("UI test"),
                initialBanner: arguments.contains("-ui-test-offline") ? .offline : nil
            )
            bearerToken = { "ui-test-only" }
            let configuration = URLSessionConfiguration.ephemeral
            configuration.protocolClasses = [NativeUIFixtureProtocol.self]
            httpSession = URLSession(configuration: configuration)
        } else {
            (session, bearerToken) = Self.liveSession(dependencies)
            httpSession = nil
        }
#else
        (session, bearerToken) = Self.liveSession(dependencies)
        httpSession = nil
#endif
        let onUnauthorizedForRequest: NativeUnauthorizedHandlerFactory = { [weak session] in
            guard let session else { return {} }
            return await session.unauthorizedHandlerForCurrentSession()
        }
        let transport = NativeAPITransport(
            environment: dependencies.environment, bearerToken: bearerToken,
            session: httpSession, onUnauthorizedForRequest: onUnauthorizedForRequest
        )
        services = NativeFeatureServices(
            today: NativeTodayAPIClient(transport: transport),
            notifications: NativeNotificationAPIClient(transport: transport),
            roadmaps: LiveRoadmapService(
                baseURL: dependencies.environment.apiBaseURL, bearerToken: bearerToken,
                session: httpSession, onUnauthorizedForRequest: onUnauthorizedForRequest
            ),
            activities: LiveActivityAPI(transport: transport),
            evidence: LiveEvidenceAPI(transport: transport)
        )
    }

    private static func liveSession(
        _ dependencies: AppDependencies
    ) -> (ShellSessionModel, NativeBearerTokenProvider) {
        let store = KeychainCredentialStore()
        let authentication = NativeAuthenticationCoordinator(
            http: LiveNativeAuthHTTPClient(baseURL: dependencies.environment.apiBaseURL),
            credentialStore: store, oauthSession: SystemOAuthSession()
        )
        let bearerToken: NativeBearerTokenProvider = { try await authentication.currentAccessToken() }
        let stream = StatusStreamClient(
            baseURL: dependencies.environment.apiBaseURL,
            bearerToken: { try await authentication.currentAccessToken() }
        )
        let session = ShellSessionModel(
            actions: .init(
                restore: { _ = try await authentication.currentAccessToken(); return "Signed in" },
                login: { try await authentication.login() },
                localLogout: { try quarantineActiveRefreshCredential(in: store) },
                logout: { try? await authentication.logout() }
            ),
            statusStream: stream
        )
        return (session, bearerToken)
    }
}

/// Lifetime matches one signed-in workspace. No draft text is written to UserDefaults.
@MainActor
private final class NativeWorkspaceState: ObservableObject {
    let today: TodayViewModel
    let notifications: NotificationViewModel
    let roadmaps: RoadmapAdministrationModel
    let evidence: EvidenceLedgerModel
    let drafts = InMemoryActivityDraftStore()
    let timerJournal: any ActivityTimerJournaling

    init(services: NativeFeatureServices) {
#if DEBUG
        if let fixedNow = NativeParityUIFixture.fixedNow() {
            today = TodayViewModel(client: services.today, now: { fixedNow })
        } else {
            today = TodayViewModel(client: services.today)
        }
#else
        today = TodayViewModel(client: services.today)
#endif
        notifications = NotificationViewModel(client: services.notifications)
        roadmaps = RoadmapAdministrationModel(service: services.roadmaps)
        evidence = EvidenceLedgerModel(service: services.evidence)
#if DEBUG
        let arguments = ProcessInfo.processInfo.arguments
        if arguments.contains("-ui-test-signed-in") || arguments.contains("-ui-test-signed-out") {
            // Fixture activity IDs must never share persistent recovery commands with real study work.
            timerJournal = InMemoryActivityTimerJournal()
        } else {
            timerJournal = UserDefaultsActivityTimerJournal()
        }
#else
        timerJournal = UserDefaultsActivityTimerJournal()
#endif
    }
}

private struct NativeWorkspaceView: View {
    let dependencies: AppDependencies
    @ObservedObject var session: ShellSessionModel
    let services: NativeFeatureServices
    @StateObject private var state: NativeWorkspaceState
    @State private var focusSelfReview = false

    init(dependencies: AppDependencies, session: ShellSessionModel, services: NativeFeatureServices) {
        self.dependencies = dependencies
        self.session = session
        self.services = services
        _state = StateObject(wrappedValue: NativeWorkspaceState(services: services))
    }

    var body: some View {
        NavigationSplitView {
            List {
                if dependencies.nativeFeatures.contains(.today) {
                    Button { session.select(.today) } label: { Label("Today", systemImage: "sun.max") }
                        .accessibilityIdentifier("todayNavigation")
                }
                if dependencies.nativeFeatures.contains(.roadmaps) {
                    Button { session.select(.roadmaps) } label: { Label("Roadmaps", systemImage: "map") }
                        .accessibilityIdentifier("roadmapsNavigation")
                }
                if dependencies.nativeFeatures.contains(.evidence) {
                    Button { session.select(.evidence(activityID: nil)) } label: {
                        Label("Evidence", systemImage: "list.bullet.rectangle")
                    }
                    .accessibilityIdentifier("evidenceNavigation")
                }
            }
            .navigationTitle("TAM Forge")
        } detail: {
            VStack(alignment: .leading, spacing: 12) {
                HStack {
                    Text(dependencies.environment.displayName).accessibilityIdentifier("environmentLabel")
                    Spacer()
                    if !dependencies.nativeFeatures.isEmpty {
                        if session.isStatusStreamActive { NotificationConnectionStatusView(state: session.statusState) }
                        NotificationPanelView(model: state.notifications)
                    }
                    Button("Sign out") { session.signOut() }.accessibilityIdentifier("signOutButton")
                }
                if let banner = session.banner { GlobalBannerView(banner: banner) }
                routeDetail
            }
            .padding(.leading, 12)
        }
        .task(id: session.featureRefreshVersion) {
            guard session.featureRefreshVersion > 0 else { return }
            // Coalesce event bursts without dropping all but the final event.
            // Reconnect retries invalidate these reads too: polling updates the UI,
            // rather than fetching and discarding an unused notification summary.
            do { try await Task.sleep(for: .milliseconds(150)) } catch { return }
            await state.today.load()
            guard !Task.isCancelled else { return }
            await state.notifications.load()
            guard !Task.isCancelled else { return }
            if case .evidence = session.selectedRoute {
                await state.evidence.refresh()
            } else {
                state.evidence.markStale()
            }
        }
        .onChange(of: session.selectedRoute) { oldRoute, newRoute in
            guard case .evidence = oldRoute else { return }
            if case .evidence = newRoute { return }
            state.evidence.deactivate()
        }
        // Close this generation on logout/expiry. A fresh sign-in gets a new model;
        // canceled or noncooperative reads cannot publish into the retired workspace.
        .onDisappear { state.evidence.reset() }
    }

    @ViewBuilder
    private var routeDetail: some View {
        switch session.selectedRoute {
        case .today where dependencies.nativeFeatures.contains(.today):
            TodayView(model: state.today, onNavigate: navigate)
        case .roadmaps where dependencies.nativeFeatures.contains(.roadmaps):
            RoadmapAdministrationView(model: state.roadmaps)
        case let .evidence(identifier) where dependencies.nativeFeatures.contains(.evidence):
            EvidenceLedgerView(
                model: state.evidence,
                onOpenActivity: { identifier in
                    focusSelfReview = false
                    session.select(.activity(identifier))
                },
                onShowAll: { session.select(.evidence(activityID: nil)) }
            )
            .task(id: identifier) { await state.evidence.open(activityID: identifier) }
        case let .activity(identifier) where dependencies.nativeFeatures.contains(.today):
            NativeActivityScreen(
                activityID: identifier, api: services.activities, drafts: state.drafts,
                timerJournal: state.timerJournal, focusSelfReview: focusSelfReview
            )
            .id(identifier)
        default:
            ContentUnavailableView("Native features are being prepared.", systemImage: "hammer")
                .accessibilityIdentifier("noNativeFeatures")
        }
    }

    private func navigate(_ destination: TodayDestination) {
        switch destination {
        case let .activity(identifier, focus):
            focusSelfReview = focus == .selfReview
            session.select(.activity(identifier))
        case let .evidence(identifier):
            session.select(.evidence(activityID: identifier))
        case .dailyClose:
            break // Today owns the daily-close form and command.
        }
    }
}

private struct NativeActivityScreen: View {
    @StateObject private var model: ActivityWorkspaceModel
    @StateObject private var uploader: ActivityArtifactUploader
    let focusSelfReview: Bool

    init(activityID: Int, api: any ActivityAPI, drafts: any ActivityDraftStoring,
         timerJournal: any ActivityTimerJournaling, focusSelfReview: Bool) {
        _model = StateObject(wrappedValue: ActivityWorkspaceModel(
            activityID: activityID, api: api, drafts: drafts, timerJournal: timerJournal
        ))
        _uploader = StateObject(wrappedValue: ActivityArtifactUploader(api: api))
        self.focusSelfReview = focusSelfReview
    }

    var body: some View {
        ActivityWorkspaceView(model: model, uploader: uploader, focusSelfReview: focusSelfReview)
    }
}
