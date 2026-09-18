import AppKit
import Darwin
import SwiftUI

@main
struct TAMForgeApp: App {
    let dependencies: AppDependencies

    init() {
        // One startup sweep; live uploads are protected by their OS-held file locks.
        _ = try? ActivityStagedFileStore().cleanupAbandonedCopies()
        #if DEBUG
            let arguments = ProcessInfo.processInfo.arguments
            let nativeFeatures: Set<NativeFeature> =
                arguments.contains("-ui-test-signed-in")
                    && !arguments.contains("-ui-test-native-features")
                ? [] : [.today, .roadmaps, .evidence, .recording, .interviews, .classes, .cards, .progress]
        #else
            let nativeFeatures: Set<NativeFeature> = [
                .today, .roadmaps, .evidence, .recording, .interviews, .classes, .cards, .progress,
            ]
        #endif
        self.init(
            dependencies: .live(
                environment: .selected(from: ProcessInfo.processInfo.environment),
                nativeFeatures: nativeFeatures
            ))
    }

    init(dependencies: AppDependencies) {
        self.dependencies = dependencies
        // Dark-only: the Organic palette has no light values. NSApp.appearance also
        // covers AppKit panels (open/save) that .preferredColorScheme cannot reach.
        NSApplication.shared.appearance = NSAppearance(named: .darkAqua)
    }

    var body: some Scene {
        // One workspace owns the authenticated session and its private in-memory drafts.
        Window("TAM Forge", id: "main") {
            NativeShellView(dependencies: dependencies)
                .preferredColorScheme(.dark)
        }
        .organicWindowChrome()
    }
}

#if DEBUG
    private enum LocalResourceProbe {
        static var isRequested: Bool {
            ProcessInfo.processInfo.environment["TAMFORGE_RESOURCE_RECEIPT"] == "1"
        }

        static func residentMemoryKiB() -> Int? {
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

    private struct LocalResourceProbeView: View {
        @State private var rssKiB = LocalResourceProbe.residentMemoryKiB() ?? 0
        @State private var samples: [Int] = []

        var body: some View {
            ZStack {
                Text(String(rssKiB))
                    .accessibilityIdentifier("resourceRSSKiB")
                Text(samples.map(String.init).joined(separator: ","))
                    .accessibilityIdentifier("resourceRSSSamples")
            }
            .font(.system(size: 1))
            .frame(width: 1, height: 1)
            .task {
                let clock = ContinuousClock()
                var nextSample = clock.now
                while !Task.isCancelled {
                    rssKiB = LocalResourceProbe.residentMemoryKiB() ?? rssKiB
                    samples.append(rssKiB)
                    nextSample = nextSample.advanced(by: .seconds(1))
                    try? await clock.sleep(until: nextSample)
                }
            }
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
        NativeSessionView(
            dependencies: dependencies,
            model: composition.session,
            services: composition.services,
            recording: composition.recording
        )
    }
}

private struct NativeSessionView: View {
    let dependencies: AppDependencies
    @ObservedObject var model: ShellSessionModel
    let services: NativeFeatureServices
    @ObservedObject var recording: RecordingCoordinator
    @SceneStorage("tamforge.shell.route") private var restoredRouteID = "today"
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        Group {
            switch model.phase {
            case .loading:
                ProgressView("Checking your secure session").accessibilityIdentifier(
                    "sessionLoading")
            case .signedOut:
                SignInView(
                    environmentLabel: dependencies.environment.displayName,
                    banner: model.banner,
                    onSignIn: { Task { await model.signIn() } }
                )
            case .signedIn:
                NativeWorkspaceView(
                    dependencies: dependencies,
                    session: model,
                    services: services,
                    recording: recording
                )
            }
        }
        .background(Organic.Color.bg)
        .frame(minWidth: Organic.Window.minimumSize.width, minHeight: Organic.Window.minimumSize.height)
        .task {
            model.restoreRoute(from: restoredRouteID)
            await model.restore()
        }
        .onChange(of: model.restorationRouteID) { _, value in restoredRouteID = value }
        .animation(reduceMotion ? nil : .easeInOut(duration: 0.2), value: model.banner)
        .safeAreaInset(edge: .bottom) {
            RecordingGlobalStatusView(coordinator: recording)
        }
        #if DEBUG
            .overlay(alignment: .bottomTrailing) {
                if LocalResourceProbe.isRequested { LocalResourceProbeView() }
            }
        #endif
    }
}

@MainActor
private struct NativeFeatureServices {
    let today: any TodayServicing
    let notifications: any NotificationServicing
    let roadmaps: any RoadmapServicing
    let activities: any ActivityAPI
    let evidence: any EvidenceServicing
    let coaching: any CoachAPI
    let notes: any StudyNoteAPI
    let recordings: any RecordingServerServicing
    let reviews: any ReviewAPI
    let interviews: any InterviewAPI
    let classes: any EnglishClassAPI
    let cards: any CardAPI
    let progress: any ProgressAPI
}

@MainActor
private final class NativeShellComposition: ObservableObject {
    let session: ShellSessionModel
    let services: NativeFeatureServices
    let recording: RecordingCoordinator

    init(dependencies: AppDependencies) {
        let bearerToken: NativeBearerTokenProvider
        let recordingBearerToken: RecordingBearerTokenProvider
        let refreshBearer: RecordingBearerRefresh
        let httpSession: URLSession?
        #if DEBUG
            let arguments = ProcessInfo.processInfo.arguments
            if arguments.contains("-ui-test-signed-out") || arguments.contains("-ui-test-signed-in")
            {
                session = ShellSessionModel(
                    actions: .init(
                        restore: { "UI test" }, login: { "UI test" }, localLogout: {}, logout: {}),
                    statusStream: nil,
                    initialPhase: arguments.contains("-ui-test-signed-out")
                        ? .signedOut(.signedOut) : .signedIn("UI test"),
                    initialBanner: arguments.contains("-ui-test-offline") ? .offline : nil
                )
                bearerToken = { "ui-test-only" }
                recordingBearerToken = {
                    .init(token: "ui-test-only", sessionGeneration: 0)
                }
                refreshBearer = { lease in lease }
                let configuration = URLSessionConfiguration.ephemeral
                configuration.protocolClasses = [NativeUIFixtureProtocol.self]
                httpSession = URLSession(configuration: configuration)
            } else {
                (session, bearerToken, recordingBearerToken, refreshBearer) = Self.liveSession(
                    dependencies
                )
                httpSession = nil
            }
        #else
            (session, bearerToken, recordingBearerToken, refreshBearer) = Self.liveSession(
                dependencies
            )
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
        let recordingServer = LiveRecordingServerClient(
            baseURL: dependencies.environment.apiBaseURL,
            bearerToken: recordingBearerToken,
            refreshBearer: refreshBearer,
            session: httpSession
        )
        services = NativeFeatureServices(
            today: NativeTodayAPIClient(transport: transport),
            notifications: NativeNotificationAPIClient(transport: transport),
            roadmaps: LiveRoadmapService(
                baseURL: dependencies.environment.apiBaseURL, bearerToken: bearerToken,
                session: httpSession, onUnauthorizedForRequest: onUnauthorizedForRequest
            ),
            activities: LiveActivityAPI(transport: transport),
            evidence: LiveEvidenceAPI(transport: transport),
            coaching: LiveCoachAPI(transport: transport),
            notes: LiveStudyNoteAPI(transport: transport),
            recordings: recordingServer,
            reviews: LiveReviewAPI(transport: transport),
            interviews: LiveInterviewAPI(transport: transport, recordings: recordingServer),
            classes: LiveEnglishClassAPI(transport: transport, recordings: recordingServer),
            cards: LiveCardAPI(transport: transport),
            progress: LiveProgressAPI(transport: transport)
        )
        #if DEBUG
            let isUITest = ProcessInfo.processInfo.arguments.contains("-ui-test-signed-out")
                || ProcessInfo.processInfo.arguments.contains("-ui-test-signed-in")
            let recordingSpool = isUITest
                ? EncryptedRecordingSpoolFactory(
                    rootURL: FileManager.default.temporaryDirectory.appendingPathComponent(
                        "TAMForgeUITestRecordingSpool", isDirectory: true
                    ),
                    keyStore: EphemeralRecordingKeyStore(),
                    reservationBytes: 0
                )
                : EncryptedRecordingSpoolFactory()
        #else
            let recordingSpool = EncryptedRecordingSpoolFactory()
        #endif

        // `try?` means a missing or unreadable model just switches transcription
        // off instead of failing app launch. CI and UI-test runners never have
        // the model installed (only scripts/dev/fetch_whisper_framework.sh runs
        // there, which fetches the runtime, not model weights), so this stays
        // nil and RecordingCoordinator.beginTranscription never starts there.
        let speechModelCatalog = SpeechModelCatalog()
        let transcriber: (any SpeechTranscribing)? =
            speechModelCatalog.transcriptionModelURL != nil
            ? try? WhisperTranscriber(catalog: speechModelCatalog)
            : nil
        // Shared by the coordinator (which populates it once a local
        // transcript is ready) and the upload pipeline (which retries a
        // failed or premature submission from it on a later pass). Created
        // once, here, since neither of those two depends on the other, and
        // handed the spool factory so each entry also survives inside the
        // recording's own encrypted spool directory: a transcript computed
        // in this launch is still submittable in the next one.
        let transcriptCache = RecordingTranscriptCache(spoolFactory: recordingSpool)
        recording = RecordingCoordinator(
            preflight: LiveRecordingPreflight(spoolRootURL: recordingSpool.rootURL),
            spoolFactory: recordingSpool,
            uploader: RecordingUploadPipeline(
                spoolFactory: recordingSpool,
                server: recordingServer,
                transcriptCache: transcriptCache
            ),
            server: recordingServer,
            transcriptCache: transcriptCache,
            environmentMonitor: LiveRecordingEnvironmentMonitor(),
            audioReader: recordingSpool,
            transcriber: transcriber
        )
        recording.activityLinkWriter = { [rootURL = recordingSpool.rootURL] recordingID, link in
            try RecordingLink.write(link, recordingID: recordingID, rootURL: rootURL)
        }
    }

    private static func liveSession(
        _ dependencies: AppDependencies
    ) -> (
        ShellSessionModel,
        NativeBearerTokenProvider,
        RecordingBearerTokenProvider,
        RecordingBearerRefresh
    ) {
        let store = KeychainCredentialStore()
        let authentication = NativeAuthenticationCoordinator(
            http: LiveNativeAuthHTTPClient(baseURL: dependencies.environment.apiBaseURL),
            credentialStore: store, oauthSession: SystemOAuthSession()
        )
        let bearerToken: NativeBearerTokenProvider = {
            try await authentication.currentAccessToken()
        }
        let recordingBearerToken: RecordingBearerTokenProvider = {
            try await authentication.recordingAccessTokenLease()
        }
        let refreshBearer: RecordingBearerRefresh = { lease in
            try await authentication.refreshedAccessTokenAfterUnauthorized(lease: lease)
        }
        let stream = StatusStreamClient(
            baseURL: dependencies.environment.apiBaseURL,
            bearerToken: { try await authentication.currentAccessToken() }
        )
        let session = ShellSessionModel(
            actions: .init(
                restore: {
                    _ = try await authentication.currentAccessToken()
                    return "Signed in"
                },
                login: { try await authentication.login() },
                localLogout: { try quarantineActiveRefreshCredential(in: store) },
                logout: { try? await authentication.logout() }
            ),
            statusStream: stream
        )
        return (session, bearerToken, recordingBearerToken, refreshBearer)
    }
}

/// Lifetime matches one signed-in workspace. No draft text is written to UserDefaults.
@MainActor
private final class NativeWorkspaceState: ObservableObject {
    let today: TodayViewModel
    let notifications: NotificationViewModel
    let roadmaps: RoadmapAdministrationModel
    let evidence: EvidenceLedgerModel
    let interviews: InterviewsModel
    let classes: ClassesModel
    let cards: CardsModel
    let progress: ProgressModel
    let drafts = InMemoryActivityDraftStore()
    let timerJournal: any ActivityTimerJournaling

    init(services: NativeFeatureServices, recording: RecordingCoordinator) {
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
        interviews = InterviewsModel(api: services.interviews)
        classes = ClassesModel(api: services.classes)
        cards = CardsModel(api: services.cards, coordinator: recording)
        progress = ProgressModel(api: services.progress)
        #if DEBUG
            let arguments = ProcessInfo.processInfo.arguments
            if arguments.contains("-ui-test-signed-in") || arguments.contains("-ui-test-signed-out")
            {
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
    @ObservedObject var recording: RecordingCoordinator
    @StateObject private var state: NativeWorkspaceState
    @State private var focusSelfReview = false
    @State private var showRecordingSignOutConfirmation = false

    init(
        dependencies: AppDependencies,
        session: ShellSessionModel,
        services: NativeFeatureServices,
        recording: RecordingCoordinator
    ) {
        self.dependencies = dependencies
        self.session = session
        self.services = services
        self.recording = recording
        _state = StateObject(wrappedValue: NativeWorkspaceState(services: services, recording: recording))
    }

    var body: some View {
        HStack(spacing: 0) {
            OrganicSidebar(
                features: dependencies.nativeFeatures,
                selected: session.selectedRoute,
                todayRemaining: state.today.snapshot.map { TodayTaskStatus.remainingCount(in: $0.tasks) },
                cardsDue: state.cards.remaining,
                isRecording: recording.phase.isActive,
                environmentLabel: dependencies.environment.displayName,
                statusState: session.statusState,
                login: loginName,
                onSelect: { session.select($0) },
                onSignOut: signOut
            )
            VStack(spacing: 0) {
                OrganicToolbar(breadcrumb: breadcrumb) {
                    if !dependencies.nativeFeatures.isEmpty {
                        NotificationPanelView(model: state.notifications)
                    }
                }
                // No outer ScrollView here: every current route (Today, Roadmaps,
                // Recording, Interviews, Classes, Cards, Progress, Evidence, Activity)
                // already owns a ScrollView with its own accessibilityIdentifier
                // ("activityWorkspaceScroll", "roadmapWorkspaceScroll", "evidenceLedger",
                // etc.), predating this shell. Wrapping routeDetail in a second, unlabeled
                // ScrollView double-nests every route and made the self-review TextEditor
                // in ActivityWorkspaceView intermittently unfocusable to XCUITest's
                // synthesized keyboard events (`testNativeFoundationParityJourney` failing
                // at the "Main answer or decision" field, 2 of 3 runs). Those feature views
                // are explicitly out of scope until stages 3-8 restyle them one at a time
                // (task-10-brief.md, "What this plan does not cover"), so the fix stays
                // here: let each route keep bounding and scrolling its own content inside
                // the width-capped column below, exactly as it did under NavigationSplitView.
                // The page padding the handoff specifies (32/36/40) is NOT applied here.
                // Wrapping routeDetail in frames or generous padding breaks the measurement
                // of whichever ScrollView the route owns: its scrollable range comes up short
                // and the tail of the content becomes unreachable at any scroll position.
                // Proven by bisection on 2026-09-18 — this minimal shape passes, and adding
                // .frame(maxWidth: 1120) or .frame(maxWidth: .infinity) fails 3/3 with the
                // Roadmaps approval checkbox outside the viewport (TAMForgeUITests:411),
                // which a human cannot click either. Each screen applies its own page padding
                // as stages 3-8 restyle it; that is where the handoff's 32/36/40 belongs.
                VStack(alignment: .leading, spacing: Organic.Space.p12) {
                    if let banner = session.banner { GlobalBannerView(banner: banner) }
                    routeDetail
                }
                .padding(.leading, Organic.Space.p12)
            }
            .background(Organic.Color.bg)
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
        .onDisappear {
            state.evidence.reset()
            Task { await recording.pauseUploadsForSignOut() }
        }
        .alert(
            "Stop recording before signing out?",
            isPresented: $showRecordingSignOutConfirmation
        ) {
            Button("Cancel", role: .cancel) {}
            Button("Stop and sign out") {
                Task {
                    await recording.stop()
                    await recording.pauseUploadsForSignOut()
                    session.signOut()
                }
            }
        } message: {
            Text("TAM Forge will seal the encrypted local recording before signing out.")
        }
    }

    private var loginName: String {
        if case .signedIn(let login) = session.phase { return login }
        return ""
    }

    private var breadcrumb: String {
        switch session.selectedRoute {
        case .today: "Today"
        case .roadmaps: "Roadmaps"
        case .recording: "Recording"
        case .interviews: "Interviews"
        case .classes: "English classes"
        case .cards: "Cards"
        case .progress: "Progress"
        case .evidence: "Evidence"
        case .activity(let identifier): "Today › Activity \(identifier)"
        }
    }

    private func signOut() {
        if recording.requiresStopBeforeSignOut {
            showRecordingSignOutConfirmation = true
        } else {
            Task {
                await recording.pauseUploadsForSignOut()
                session.signOut()
            }
        }
    }

    @ViewBuilder
    private var routeDetail: some View {
        switch session.selectedRoute {
        case .today where dependencies.nativeFeatures.contains(.today):
            TodayView(model: state.today, onNavigate: navigate)
        case .roadmaps where dependencies.nativeFeatures.contains(.roadmaps):
            RoadmapAdministrationView(model: state.roadmaps)
        case .recording where dependencies.nativeFeatures.contains(.recording):
            RecordingView(coordinator: recording)
        case .interviews where dependencies.nativeFeatures.contains(.interviews):
            InterviewsView(model: state.interviews, coordinator: recording)
        case .classes where dependencies.nativeFeatures.contains(.classes):
            ClassesView(model: state.classes, coordinator: recording)
        case .cards where dependencies.nativeFeatures.contains(.cards):
            CardsView(model: state.cards)
        case .progress where dependencies.nativeFeatures.contains(.progress):
            ProgressScreen(model: state.progress)
        case .evidence(let identifier) where dependencies.nativeFeatures.contains(.evidence):
            EvidenceLedgerView(
                model: state.evidence,
                onOpenActivity: { identifier in
                    focusSelfReview = false
                    session.select(.activity(identifier))
                },
                onShowAll: { session.select(.evidence(activityID: nil)) }
            )
            .task(id: identifier) { await state.evidence.open(activityID: identifier) }
        case .activity(let identifier) where dependencies.nativeFeatures.contains(.today):
            NativeActivityScreen(
                activityID: identifier, api: services.activities, coaching: services.coaching,
                notes: services.notes, recordings: services.recordings, recording: recording,
                reviews: services.reviews, drafts: state.drafts, timerJournal: state.timerJournal,
                focusSelfReview: focusSelfReview, cards: state.cards
            )
            .id(identifier)
        default:
            ContentUnavailableView("Native features are being prepared.", systemImage: "hammer")
                .accessibilityIdentifier("noNativeFeatures")
        }
    }

    private func navigate(_ destination: TodayDestination) {
        switch destination {
        case .activity(let identifier, let focus):
            focusSelfReview = focus == .selfReview
            session.select(.activity(identifier))
        case .evidence(let identifier):
            session.select(.evidence(activityID: identifier))
        case .dailyClose:
            break  // Today owns the daily-close form and command.
        }
    }
}

private struct NativeActivityScreen: View {
    @StateObject private var model: ActivityWorkspaceModel
    @StateObject private var uploader: ActivityArtifactUploader
    @StateObject private var coach: CoachThreadModel
    @StateObject private var note: StudyNoteModel
    @StateObject private var spoken: SpokenAttemptModel
    @StateObject private var review: ReviewModel
    let focusSelfReview: Bool
    let cards: CardsModel

    init(
        activityID: Int, api: any ActivityAPI, coaching: any CoachAPI, notes: any StudyNoteAPI,
        recordings: any RecordingServerServicing, recording: RecordingCoordinator, reviews: any ReviewAPI,
        drafts: any ActivityDraftStoring, timerJournal: any ActivityTimerJournaling, focusSelfReview: Bool,
        cards: CardsModel
    ) {
        _model = StateObject(
            wrappedValue: ActivityWorkspaceModel(
                activityID: activityID, api: api, drafts: drafts, timerJournal: timerJournal
            ))
        _uploader = StateObject(wrappedValue: ActivityArtifactUploader(api: api))
        _coach = StateObject(wrappedValue: CoachThreadModel(activityID: activityID, api: coaching))
        _note = StateObject(wrappedValue: StudyNoteModel(activityID: activityID, api: notes))
        _spoken = StateObject(
            wrappedValue: SpokenAttemptModel(
                activityID: activityID, coordinator: recording, server: recordings
            ))
        _review = StateObject(wrappedValue: ReviewModel(activityID: activityID, api: reviews))
        self.focusSelfReview = focusSelfReview
        self.cards = cards
    }

    var body: some View {
        ActivityWorkspaceView(
            model: model, uploader: uploader, focusSelfReview: focusSelfReview, coach: coach, note: note,
            spoken: spoken, aiReview: review, cards: cards
        )
    }
}
