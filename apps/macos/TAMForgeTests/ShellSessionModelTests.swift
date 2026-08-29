import XCTest

@MainActor
final class ShellSessionModelTests: XCTestCase {
    func testSessionExpirationReturnsToLoginAndClearsFeatureState() async {
        let model = ShellSessionModel(actions: .authenticatedForTests, statusStream: nil)

        await model.restore()
        model.receive(StatusEvent.fixture(id: 12, eventType: "processing"))
        model.select(.activity(42))
        model.receive(.unauthorized)

        XCTAssertEqual(model.phase, .signedOut(.sessionExpired))
        XCTAssertTrue(model.statusHistory.isEmpty)
        XCTAssertEqual(model.selectedRoute, .today)
        XCTAssertFalse(model.isStatusStreamActive)
    }

    func testNavigationRestorationKeepsOnlyNonsensitiveRouteIdentifiers() {
        let model = ShellSessionModel(actions: .authenticatedForTests, statusStream: nil)

        model.select(.activity(42))
        XCTAssertEqual(model.restorationRouteID, "today")
        model.restoreRoute(from: "roadmaps")
        XCTAssertEqual(model.selectedRoute, .roadmaps)
        model.restoreRoute(from: "unknown-route")
        XCTAssertEqual(model.selectedRoute, .today)
    }

    func testBannersUseSafeUserFacingStates() async {
        let model = ShellSessionModel(actions: .authenticatedForTests, statusStream: nil)
        await model.restore()

        model.receive(.offline)
        XCTAssertEqual(model.banner, .offline)
        model.receive(.retrying)
        XCTAssertEqual(model.banner, .retrying)
        model.receive(StatusEvent.fixture(id: 1, eventType: "processing"))
        XCTAssertEqual(model.banner, .processing)
        model.receive(StatusEvent.fixture(id: 2, eventType: "processing_failure_requires_action"))
        XCTAssertEqual(model.banner, .actionRequired)
        model.receive(.unauthorized)
        XCTAssertEqual(model.banner, .permission)
    }

    func testStatusHistoryIsBounded() async {
        let model = ShellSessionModel(actions: .authenticatedForTests, statusStream: nil)
        await model.restore()

        for identifier in 1 ... 51 {
            model.receive(StatusEvent.fixture(id: identifier, eventType: "processing"))
        }

        XCTAssertEqual(model.statusHistory.count, 50)
        XCTAssertEqual(model.statusHistory.first?.id, 2)
        XCTAssertEqual(model.statusHistory.last?.id, 51)
    }

    func testSignInDoesNotStartWhenSessionIsAlreadyAuthenticated() async {
        let recorder = LoginRecorder()
        let model = ShellSessionModel(
            actions: ShellSessionActions(
                restore: { "frank" },
                login: { await recorder.record(); return "frank" },
                localLogout: {},
                logout: {}
            ),
            statusStream: nil,
            initialPhase: .signedIn("frank")
        )

        await model.signIn()

        let count = await recorder.count
        XCTAssertEqual(count, 0)
    }

    func testSignOutQuarantinesCredentialBeforeSignedOutUIAndDeferredLogout() async throws {
        let store = ShellCredentialStore(active: "refresh-token")
        let logoutGate = DeferredLogoutGate()
        let model = ShellSessionModel(
            actions: ShellSessionActions(
                restore: { "frank" },
                login: { "frank" },
                localLogout: { try quarantineActiveRefreshCredential(in: store) },
                logout: { await logoutGate.wait() }
            ),
            statusStream: nil,
            initialPhase: .signedIn("frank")
        )

        model.signOut()

        XCTAssertEqual(model.phase, .signedOut(.signedOut))
        XCTAssertNil(store.active)
        XCTAssertEqual(store.pending, "refresh-token")
        let deferredLogoutStarted = await logoutGate.waitUntilEntered()
        XCTAssertTrue(deferredLogoutStarted)
        XCTAssertNil(store.active)
        XCTAssertEqual(store.pending, "refresh-token")
        await logoutGate.open()
    }
}

private actor LoginRecorder {
    private(set) var count = 0

    func record() {
        count += 1
    }
}

private extension ShellSessionActions {
    static let authenticatedForTests = Self(
        restore: { "frank" },
        login: { "frank" },
        localLogout: {},
        logout: {}
    )
}

private final class ShellCredentialStore: RefreshCredentialStore, @unchecked Sendable {
    private let lock = NSLock()
    private var activeValue: String?
    private var pendingValue: String?

    init(active: String?) {
        activeValue = active
    }

    var active: String? { lock.withLock { activeValue } }
    var pending: String? { lock.withLock { pendingValue } }

    func activeRefreshToken() throws -> String? { active }

    func storeActiveRefreshToken(_ token: String) throws {
        lock.withLock { activeValue = token }
    }

    func removeActiveRefreshToken() throws {
        lock.withLock { activeValue = nil }
    }

    func pendingRevocationToken() throws -> String? { pending }

    func storePendingRevocationToken(_ token: String) throws {
        lock.withLock { pendingValue = token }
    }

    func removePendingRevocationToken() throws {
        lock.withLock { pendingValue = nil }
    }
}

private actor DeferredLogoutGate {
    private var entered = false
    private var continuation: CheckedContinuation<Void, Never>?

    func wait() async {
        entered = true
        await withCheckedContinuation { continuation = $0 }
    }

    func waitUntilEntered() async -> Bool {
        for _ in 0 ..< 10_000 {
            if entered { return true }
            await Task.yield()
        }
        return false
    }

    func open() {
        continuation?.resume()
        continuation = nil
    }
}

private extension StatusEvent {
    static func fixture(id: Int, eventType: String) -> Self {
        Self(
            id: id,
            eventType: eventType,
            aggregateType: "activity",
            aggregateID: 9,
            subjectID: 9,
            relatedID: nil,
            occurredAt: "2026-08-28T00:00:00Z"
        )
    }
}
