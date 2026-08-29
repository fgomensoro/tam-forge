import Foundation
import Security
import XCTest

final class NativeAuthenticationTests: XCTestCase {
    func testLoginBindsPKCEAndKeepsAccessTokenOutOfCredentialStore() async throws {
        let http = FakeNativeAuthHTTPClient()
        let store = MemoryCredentialStore()
        let oauth = await MainActor.run { FakeOAuthSession() }
        let coordinator = NativeAuthenticationCoordinator(
            http: http,
            credentialStore: store,
            oauthSession: oauth,
            now: { Date(timeIntervalSince1970: 1_000) }
        )

        let login = try await coordinator.login()
        let capturedVerifier = await http.exchangeVerifier
        let capturedChallenge = await http.startChallenge
        let verifier = try XCTUnwrap(capturedVerifier)
        let challenge = try XCTUnwrap(capturedChallenge)
        let callbackScheme = await MainActor.run { oauth.callbackScheme }

        XCTAssertEqual(login, "fgomensoro")
        XCTAssertEqual(NativeAuthenticationCoordinator.pkceChallenge(verifier), challenge)
        XCTAssertEqual(store.active, token("r"))
        XCTAssertFalse(store.allStoredValues.contains(token("a")))
        XCTAssertEqual(callbackScheme, "tamforge")
    }

    func testConcurrentAccessRefreshesOnceAndRotatesStoredCredential() async throws {
        let http = FakeNativeAuthHTTPClient()
        let store = MemoryCredentialStore(active: token("r"))
        let oauth = await MainActor.run { FakeOAuthSession() }
        let coordinator = NativeAuthenticationCoordinator(
            http: http,
            credentialStore: store,
            oauthSession: oauth
        )

        async let first = coordinator.currentAccessToken()
        async let second = coordinator.currentAccessToken()
        let values = try await [first, second]

        XCTAssertEqual(values, [token("b"), token("b")])
        let refreshCalls = await http.refreshCalls
        XCTAssertEqual(refreshCalls, 1)
        XCTAssertEqual(store.active, token("s"))
    }

    func testUnauthorizedResponseRefreshesAndRetriesOnlyOnce() async throws {
        let http = FakeNativeAuthHTTPClient()
        let store = MemoryCredentialStore()
        let oauth = await MainActor.run { FakeOAuthSession() }
        let coordinator = NativeAuthenticationCoordinator(
            http: http,
            credentialStore: store,
            oauthSession: oauth
        )
        _ = try await coordinator.login()
        let attempts = AttemptCounter()

        let result = try await coordinator.performAuthenticated { token in
            if await attempts.next() == 1 {
                throw NativeAPIError.problem(
                    APIProblem(type: nil, title: "Unauthorized", status: 401, detail: nil, instance: nil)
                )
            }
            return token
        }

        XCTAssertEqual(result, token("b"))
        let attemptCount = await attempts.value
        let refreshCalls = await http.refreshCalls
        XCTAssertEqual(attemptCount, 2)
        XCTAssertEqual(refreshCalls, 1)
    }

    func testIndeterminateRotationClearsOldCredentialAndRequiresLogin() async throws {
        let http = FakeNativeAuthHTTPClient()
        await http.setRefreshFailure(true)
        let store = MemoryCredentialStore(active: token("r"))
        let oauth = await MainActor.run { FakeOAuthSession() }
        let coordinator = NativeAuthenticationCoordinator(
            http: http,
            credentialStore: store,
            oauthSession: oauth
        )

        do {
            _ = try await coordinator.currentAccessToken()
            XCTFail("Expected reauthentication")
        } catch let error as NativeAuthenticationError {
            XCTAssertEqual(error, .reauthenticationRequired)
        }
        XCTAssertNil(store.active)
        XCTAssertEqual(store.pending, token("r"))
    }

    func testOfflineLogoutMovesRefreshToPendingUntilServerAcknowledges() async throws {
        let http = FakeNativeAuthHTTPClient()
        let store = MemoryCredentialStore()
        let oauth = await MainActor.run { FakeOAuthSession() }
        let coordinator = NativeAuthenticationCoordinator(
            http: http,
            credentialStore: store,
            oauthSession: oauth
        )
        _ = try await coordinator.login()
        await http.setRevokeFailure(true)

        do {
            try await coordinator.logout()
            XCTFail("Expected pending revocation")
        } catch let error as NativeAuthenticationError {
            XCTAssertEqual(error, .revocationPending)
        }
        XCTAssertNil(store.active)
        XCTAssertEqual(store.pending, token("r"))

        await http.setRevokeFailure(false)
        try await coordinator.retryPendingRevocation()
        XCTAssertNil(store.pending)
    }

    func testSuccessfulLoginAndLogoutLeavesNoLocalCredential() async throws {
        let http = FakeNativeAuthHTTPClient()
        let store = MemoryCredentialStore()
        let oauth = await MainActor.run { FakeOAuthSession() }
        let coordinator = NativeAuthenticationCoordinator(
            http: http,
            credentialStore: store,
            oauthSession: oauth
        )

        _ = try await coordinator.login()
        try await coordinator.logout()

        XCTAssertNil(store.active)
        XCTAssertNil(store.pending)
        let revokeCalls = await http.revokeCalls
        XCTAssertEqual(revokeCalls, 1)
    }

    func testPendingRevocationRecoversCrashBetweenKeychainWrites() async throws {
        let http = FakeNativeAuthHTTPClient()
        let store = MemoryCredentialStore(active: token("r"), pending: token("r"))
        let oauth = await MainActor.run { FakeOAuthSession() }
        let coordinator = NativeAuthenticationCoordinator(
            http: http,
            credentialStore: store,
            oauthSession: oauth
        )

        try await coordinator.retryPendingRevocation()

        XCTAssertNil(store.active)
        XCTAssertNil(store.pending)
    }

    func testCompletedRevocationDoesNotRemoveNewerPendingToken() async throws {
        let http = FakeNativeAuthHTTPClient()
        await http.pauseRevoke()
        let store = MemoryCredentialStore(pending: token("r"))
        let oauth = await MainActor.run { FakeOAuthSession() }
        let coordinator = NativeAuthenticationCoordinator(
            http: http,
            credentialStore: store,
            oauthSession: oauth
        )

        let retry = Task { try await coordinator.retryPendingRevocation() }
        await http.waitForRevokeStart()
        try store.storePendingRevocationToken(token("s"))
        await http.resumeRevoke()
        try await retry.value

        XCTAssertEqual(store.pending, token("s"))
    }

    func testCallbackRejectsExtraOrMalformedValues() throws {
        XCTAssertEqual(
            try NativeAuthenticationCoordinator.exchangeCode(
                from: URL(string: "tamforge://auth/callback?code=\(token("e"))")!
            ),
            token("e")
        )
        for rawURL in [
            "tamforge://wrong/callback?code=\(token("e"))",
            "tamforge://auth/callback?code=short",
            "tamforge://auth/callback?code=\(token("e"))&state=secret",
        ] {
            XCTAssertThrowsError(
                try NativeAuthenticationCoordinator.exchangeCode(from: URL(string: rawURL)!)
            )
        }
    }

    func testKeychainFallbackQueryIsGenericNonSynchronizableAndMapsDeniedPaths() throws {
        let tokenData = Data(token("r").utf8)
        let primaryQuery = KeychainCredentialStore.dataProtectionQuery(
            account: KeychainCredentialStore.activeAccount
        )
        let fallbackQuery = try XCTUnwrap(
            KeychainCredentialStore.fallbackQuery(
                account: KeychainCredentialStore.activeAccount,
                after: errSecMissingEntitlement
            )
        )
        let item = KeychainCredentialStore.itemToAdd(
            tokenData: tokenData,
            account: KeychainCredentialStore.activeAccount
        )
        let dataProtectionItem = KeychainCredentialStore.itemToAdd(
            tokenData: tokenData,
            account: KeychainCredentialStore.activeAccount,
            query: primaryQuery
        )

        XCTAssertEqual(primaryQuery[kSecUseDataProtectionKeychain as String] as? Bool, true)
        XCTAssertNil(fallbackQuery[kSecUseDataProtectionKeychain as String])
        XCTAssertNil(
            KeychainCredentialStore.fallbackQuery(
                account: KeychainCredentialStore.activeAccount,
                after: errSecAuthFailed
            )
        )
        XCTAssertEqual(item[kSecClass as String] as? String, kSecClassGenericPassword as String)
        XCTAssertEqual(item[kSecAttrSynchronizable as String] as? Bool, false)
        XCTAssertNil(item[kSecUseDataProtectionKeychain as String])
        XCTAssertNil(item[kSecAttrAccessible as String])
        XCTAssertEqual(
            dataProtectionItem[kSecAttrAccessible as String] as? String,
            kSecAttrAccessibleWhenUnlockedThisDeviceOnly as String
        )
        XCTAssertNil(try KeychainCredentialStore.decodedRead(status: errSecItemNotFound, value: nil))
        XCTAssertThrowsError(
            try KeychainCredentialStore.decodedRead(
                status: errSecInteractionNotAllowed,
                value: nil
            )
        ) { error in
            XCTAssertEqual(error as? KeychainCredentialError, .accessDenied)
        }
        XCTAssertEqual(
            try KeychainCredentialStore.decodedRead(
                status: errSecSuccess,
                value: tokenData as CFData
            ),
            token("r")
        )
    }

    func testLogoutPreventsLateRefreshFromRestoringCredentials() async throws {
        let http = FakeNativeAuthHTTPClient()
        await http.pauseRefresh()
        let store = MemoryCredentialStore(active: token("r"))
        let oauth = await MainActor.run { FakeOAuthSession() }
        let coordinator = NativeAuthenticationCoordinator(
            http: http,
            credentialStore: store,
            oauthSession: oauth
        )

        let refresh = Task { try await coordinator.currentAccessToken() }
        await http.waitForRefreshStart()
        try await coordinator.logout()
        await http.resumeRefresh()

        do {
            _ = try await refresh.value
            XCTFail("Expected stale refresh rejection")
        } catch let error as NativeAuthenticationError {
            XCTAssertEqual(error, .reauthenticationRequired)
        }
        XCTAssertNil(store.active)
        XCTAssertNil(store.pending)
    }

    func testLogoutPreventsLateLoginFromRestoringCredentials() async throws {
        let http = FakeNativeAuthHTTPClient()
        await http.pauseExchange()
        let store = MemoryCredentialStore()
        let oauth = await MainActor.run { FakeOAuthSession() }
        let coordinator = NativeAuthenticationCoordinator(
            http: http,
            credentialStore: store,
            oauthSession: oauth
        )

        let login = Task { try await coordinator.login() }
        await http.waitForExchangeStart()
        try await coordinator.logout()
        await http.resumeExchange()

        do {
            _ = try await login.value
            XCTFail("Expected stale login rejection")
        } catch let error as NativeAuthenticationError {
            XCTAssertEqual(error, .reauthenticationRequired)
        }
        XCTAssertNil(store.active)
        XCTAssertNil(store.pending)
    }

    func testConcurrentLoginIsRejectedWithoutCreatingSecondSession() async throws {
        let http = FakeNativeAuthHTTPClient()
        await http.pauseExchange()
        let store = MemoryCredentialStore()
        let oauth = await MainActor.run { FakeOAuthSession() }
        let coordinator = NativeAuthenticationCoordinator(
            http: http,
            credentialStore: store,
            oauthSession: oauth
        )

        let first = Task { try await coordinator.login() }
        await http.waitForExchangeStart()

        do {
            _ = try await coordinator.login()
            XCTFail("Expected concurrent login rejection")
        } catch let error as NativeAuthenticationError {
            XCTAssertEqual(error, .authenticationInProgress)
        }

        await http.resumeExchange()
        let login = try await first.value
        XCTAssertEqual(login, "fgomensoro")
        XCTAssertEqual(store.active, token("r"))
        let revokeCalls = await http.revokeCalls
        XCTAssertEqual(revokeCalls, 0)
    }
}

private actor FakeNativeAuthHTTPClient: NativeAuthHTTPClient {
    private(set) var startChallenge: String?
    private(set) var exchangeVerifier: String?
    private(set) var refreshCalls = 0
    private(set) var revokeCalls = 0
    private var refreshFailure = false
    private var revokeFailure = false
    private var refreshPaused = false
    private var exchangePaused = false
    private var revokePaused = false
    private let refreshGate = AsyncGate()
    private let exchangeGate = AsyncGate()
    private let revokeGate = AsyncGate()

    func start(codeChallenge: String) async throws -> URL {
        startChallenge = codeChallenge
        return URL(string: "https://github.com/login/oauth/authorize")!
    }

    func exchange(code: String, codeVerifier: String) async throws -> NativeTokenPair {
        XCTAssertEqual(code, token("e"))
        exchangeVerifier = codeVerifier
        if exchangePaused { await exchangeGate.wait() }
        return NativeTokenPair(
            accessToken: token("a"),
            refreshToken: token("r"),
            expiresIn: 900,
            githubLogin: "fgomensoro"
        )
    }

    func refresh(refreshToken: String) async throws -> NativeTokenPair {
        XCTAssertTrue(refreshToken == token("r") || refreshToken == token("s"))
        refreshCalls += 1
        if refreshPaused { await refreshGate.wait() }
        await Task.yield()
        if refreshFailure { throw TestError.offline }
        return NativeTokenPair(
            accessToken: token("b"),
            refreshToken: token("s"),
            expiresIn: 900,
            githubLogin: "fgomensoro"
        )
    }

    func revoke(refreshToken: String) async throws {
        XCTAssertTrue(refreshToken == token("r") || refreshToken == token("s"))
        revokeCalls += 1
        if revokePaused { await revokeGate.wait() }
        if revokeFailure { throw TestError.offline }
    }

    func setRefreshFailure(_ value: Bool) {
        refreshFailure = value
    }

    func setRevokeFailure(_ value: Bool) {
        revokeFailure = value
    }

    func pauseRefresh() {
        refreshPaused = true
    }

    func waitForRefreshStart() async {
        await refreshGate.waitUntilEntered()
    }

    func resumeRefresh() async {
        await refreshGate.open()
        refreshPaused = false
    }

    func pauseExchange() {
        exchangePaused = true
    }

    func waitForExchangeStart() async {
        await exchangeGate.waitUntilEntered()
    }

    func resumeExchange() async {
        await exchangeGate.open()
        exchangePaused = false
    }

    func pauseRevoke() {
        revokePaused = true
    }

    func waitForRevokeStart() async {
        await revokeGate.waitUntilEntered()
    }

    func resumeRevoke() async {
        await revokeGate.open()
        revokePaused = false
    }
}

@MainActor
private final class FakeOAuthSession: NativeOAuthSession {
    private(set) var callbackScheme: String?

    func authenticate(url: URL, callbackScheme: String) async throws -> URL {
        XCTAssertEqual(url.host, "github.com")
        self.callbackScheme = callbackScheme
        return URL(string: "tamforge://auth/callback?code=\(token("e"))")!
    }
}

private final class MemoryCredentialStore: RefreshCredentialStore, @unchecked Sendable {
    private let lock = NSLock()
    private var activeValue: String?
    private var pendingValue: String?
    private var storedValues: [String] = []

    init(active: String? = nil, pending: String? = nil) {
        activeValue = active
        pendingValue = pending
        if let active { storedValues.append(active) }
        if let pending { storedValues.append(pending) }
    }

    var active: String? { lock.withLock { activeValue } }
    var pending: String? { lock.withLock { pendingValue } }
    var allStoredValues: [String] { lock.withLock { storedValues } }

    func activeRefreshToken() throws -> String? { active }

    func storeActiveRefreshToken(_ token: String) throws {
        lock.withLock {
            activeValue = token
            storedValues.append(token)
        }
    }

    func removeActiveRefreshToken() throws {
        lock.withLock { activeValue = nil }
    }

    func pendingRevocationToken() throws -> String? { pending }

    func storePendingRevocationToken(_ token: String) throws {
        lock.withLock {
            pendingValue = token
            storedValues.append(token)
        }
    }

    func removePendingRevocationToken() throws {
        lock.withLock { pendingValue = nil }
    }
}

private actor AttemptCounter {
    private(set) var value = 0

    func next() -> Int {
        value += 1
        return value
    }
}

private actor AsyncGate {
    private var entered = false
    private var continuation: CheckedContinuation<Void, Never>?

    func wait() async {
        entered = true
        await withCheckedContinuation { continuation = $0 }
    }

    func waitUntilEntered() async {
        while !entered {
            await Task.yield()
        }
    }

    func open() {
        continuation?.resume()
        continuation = nil
    }
}

private enum TestError: Error {
    case offline
}

private func token(_ character: String) -> String {
    String(repeating: character, count: 43)
}
