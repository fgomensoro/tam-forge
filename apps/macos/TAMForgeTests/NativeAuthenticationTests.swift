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

    func testKeychainContractIsGenericDeviceOnlyAndMapsDeniedPaths() throws {
        let tokenData = Data(token("r").utf8)
        let item = KeychainCredentialStore.itemToAdd(
            tokenData: tokenData,
            account: KeychainCredentialStore.activeAccount
        )

        XCTAssertEqual(item[kSecClass as String] as? String, kSecClassGenericPassword as String)
        XCTAssertEqual(item[kSecAttrSynchronizable as String] as? Bool, false)
        XCTAssertEqual(
            item[kSecAttrAccessible as String] as? String,
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
}

private actor FakeNativeAuthHTTPClient: NativeAuthHTTPClient {
    private(set) var startChallenge: String?
    private(set) var exchangeVerifier: String?
    private(set) var refreshCalls = 0
    private(set) var revokeCalls = 0
    private var refreshFailure = false
    private var revokeFailure = false

    func start(codeChallenge: String) async throws -> URL {
        startChallenge = codeChallenge
        return URL(string: "https://github.com/login/oauth/authorize")!
    }

    func exchange(code: String, codeVerifier: String) async throws -> NativeTokenPair {
        XCTAssertEqual(code, token("e"))
        exchangeVerifier = codeVerifier
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
        XCTAssertEqual(refreshToken, token("r"))
        revokeCalls += 1
        if revokeFailure { throw TestError.offline }
    }

    func setRefreshFailure(_ value: Bool) {
        refreshFailure = value
    }

    func setRevokeFailure(_ value: Bool) {
        revokeFailure = value
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

private enum TestError: Error {
    case offline
}

private func token(_ character: String) -> String {
    String(repeating: character, count: 43)
}
