import AppKit
import AuthenticationServices
import CryptoKit
import Foundation
import Security

struct NativeTokenPair: Equatable, Sendable {
    let accessToken: String
    let refreshToken: String
    let expiresIn: TimeInterval
    let githubLogin: String
}

protocol NativeAuthHTTPClient: Sendable {
    func start(codeChallenge: String) async throws -> URL
    func exchange(code: String, codeVerifier: String) async throws -> NativeTokenPair
    func refresh(refreshToken: String) async throws -> NativeTokenPair
    func revoke(refreshToken: String) async throws
}

func quarantineActiveRefreshCredential(in store: any RefreshCredentialStore) throws {
    guard let active = try store.activeRefreshToken() else { return }
    if let pending = try store.pendingRevocationToken(), pending != active {
        throw NativeAuthenticationError.credentialStorageFailed
    }
    try store.storePendingRevocationToken(active)
    try store.removeActiveRefreshToken()
}

@MainActor
protocol NativeOAuthSession: AnyObject, Sendable {
    func authenticate(url: URL, callbackScheme: String) async throws -> URL
}

enum NativeAuthenticationError: Error, Equatable {
    case invalidCallback
    case noStoredCredential
    case credentialStorageFailed
    case reauthenticationRequired
    case revocationPending
    case browserUnavailable
    case browserCancelled
    case randomGenerationFailed
    case authenticationInProgress
}

actor NativeAuthenticationCoordinator {
    static let callbackScheme = "tamforge"
    static let callbackHost = "auth"
    static let callbackPath = "/callback"

    private let http: any NativeAuthHTTPClient
    private let credentialStore: any RefreshCredentialStore
    private let oauthSession: any NativeOAuthSession
    private let now: @Sendable () -> Date
    private var accessToken: String?
    private var accessExpiresAt: Date?
    private var refreshTask: Task<String, Error>?
    private var sessionGeneration = 0
    private var loginInProgress = false

    init(
        http: any NativeAuthHTTPClient,
        credentialStore: any RefreshCredentialStore,
        oauthSession: any NativeOAuthSession,
        now: @escaping @Sendable () -> Date = Date.init
    ) {
        self.http = http
        self.credentialStore = credentialStore
        self.oauthSession = oauthSession
        self.now = now
    }

    @discardableResult
    func login() async throws -> String {
        guard !loginInProgress else {
            throw NativeAuthenticationError.authenticationInProgress
        }
        loginInProgress = true
        defer { loginInProgress = false }

        invalidateSession()
        let generation = sessionGeneration
        try await retryPendingRevocation()
        try requireCurrentSession(generation)
        if try credentialStore.activeRefreshToken() != nil {
            try await revokeActiveCredential()
            try requireCurrentSession(generation)
        }
        let verifier = try Self.makePKCEVerifier()
        let challenge = Self.pkceChallenge(verifier)
        let authorizationURL = try await http.start(codeChallenge: challenge)
        try requireCurrentSession(generation)
        let callbackURL = try await oauthSession.authenticate(
            url: authorizationURL,
            callbackScheme: Self.callbackScheme
        )
        try requireCurrentSession(generation)
        let code = try Self.exchangeCode(from: callbackURL)
        let pair = try await http.exchange(code: code, codeVerifier: verifier)
        guard generation == sessionGeneration else {
            try? await http.revoke(refreshToken: pair.refreshToken)
            throw NativeAuthenticationError.reauthenticationRequired
        }
        do {
            try credentialStore.storeActiveRefreshToken(pair.refreshToken)
        } catch {
            try? await http.revoke(refreshToken: pair.refreshToken)
            clearAccessToken()
            throw NativeAuthenticationError.credentialStorageFailed
        }
        apply(pair)
        return pair.githubLogin
    }

    func currentAccessToken() async throws -> String {
        if try credentialStore.pendingRevocationToken() != nil {
            throw NativeAuthenticationError.revocationPending
        }
        if let accessToken,
            let accessExpiresAt,
            accessExpiresAt.timeIntervalSince(now()) > 30
        {
            return accessToken
        }
        return try await rotateAccessToken()
    }

    func refreshedAccessTokenAfterUnauthorized() async throws -> String {
        clearAccessToken()
        return try await rotateAccessToken()
    }

    func performAuthenticated<Value: Sendable>(
        _ operation: @escaping @Sendable (String) async throws -> Value
    ) async throws -> Value {
        let token = try await currentAccessToken()
        do {
            return try await operation(token)
        } catch {
            guard Self.isUnauthorized(error) else { throw error }
            clearAccessToken()
            let replacement = try await rotateAccessToken()
            return try await operation(replacement)
        }
    }

    func logout() async throws {
        invalidateSession()
        try await revokeActiveCredential()
    }

    private func revokeActiveCredential() async throws {
        try quarantineActiveRefreshCredential(in: credentialStore)
        try await retryPendingRevocation()
    }

    func retryPendingRevocation() async throws {
        guard let pending = try credentialStore.pendingRevocationToken() else { return }
        do {
            try await http.revoke(refreshToken: pending)
            if try credentialStore.activeRefreshToken() == pending {
                try credentialStore.removeActiveRefreshToken()
            }
            if try credentialStore.pendingRevocationToken() == pending {
                try credentialStore.removePendingRevocationToken()
            }
        } catch {
            throw NativeAuthenticationError.revocationPending
        }
    }

    private func rotateAccessToken() async throws -> String {
        if let refreshTask {
            return try await refreshTask.value
        }
        guard let refreshToken = try credentialStore.activeRefreshToken() else {
            throw NativeAuthenticationError.noStoredCredential
        }
        let generation = sessionGeneration
        let task = Task { [self] in
            try await refreshAccessToken(
                refreshToken: refreshToken,
                generation: generation
            )
        }
        refreshTask = task
        do {
            let token = try await task.value
            if generation == sessionGeneration {
                refreshTask = nil
            }
            return token
        } catch {
            if generation == sessionGeneration {
                refreshTask = nil
            }
            throw error
        }
    }

    private func refreshAccessToken(
        refreshToken: String,
        generation: Int
    ) async throws -> String {
        let pair: NativeTokenPair
        do {
            pair = try await http.refresh(refreshToken: refreshToken)
        } catch {
            guard generation == sessionGeneration else {
                throw NativeAuthenticationError.reauthenticationRequired
            }
            clearAccessToken()
            do {
                try credentialStore.storePendingRevocationToken(refreshToken)
                try credentialStore.removeActiveRefreshToken()
            } catch {
                throw NativeAuthenticationError.credentialStorageFailed
            }
            throw NativeAuthenticationError.reauthenticationRequired
        }

        guard generation == sessionGeneration else {
            try? await http.revoke(refreshToken: pair.refreshToken)
            throw NativeAuthenticationError.reauthenticationRequired
        }
        do {
            guard try credentialStore.pendingRevocationToken() == nil else {
                clearAccessToken()
                try? await http.revoke(refreshToken: pair.refreshToken)
                throw NativeAuthenticationError.reauthenticationRequired
            }
        } catch let error as NativeAuthenticationError {
            throw error
        } catch {
            clearAccessToken()
            try? await http.revoke(refreshToken: pair.refreshToken)
            throw NativeAuthenticationError.credentialStorageFailed
        }
        do {
            try credentialStore.storeActiveRefreshToken(pair.refreshToken)
        } catch {
            clearAccessToken()
            do {
                try credentialStore.storePendingRevocationToken(refreshToken)
                try credentialStore.removeActiveRefreshToken()
            } catch {
                throw NativeAuthenticationError.credentialStorageFailed
            }
            try? await http.revoke(refreshToken: pair.refreshToken)
            throw NativeAuthenticationError.reauthenticationRequired
        }
        if try credentialStore.pendingRevocationToken() != nil {
            if try credentialStore.activeRefreshToken() == pair.refreshToken {
                try credentialStore.removeActiveRefreshToken()
            }
            clearAccessToken()
            try? await http.revoke(refreshToken: pair.refreshToken)
            throw NativeAuthenticationError.reauthenticationRequired
        }
        apply(pair)
        return pair.accessToken
    }

    private func apply(_ pair: NativeTokenPair) {
        accessToken = pair.accessToken
        accessExpiresAt = now().addingTimeInterval(pair.expiresIn)
    }

    private func clearAccessToken() {
        accessToken = nil
        accessExpiresAt = nil
    }

    private func invalidateSession() {
        sessionGeneration &+= 1
        refreshTask?.cancel()
        refreshTask = nil
        clearAccessToken()
    }

    private func requireCurrentSession(_ generation: Int) throws {
        guard generation == sessionGeneration else {
            throw NativeAuthenticationError.reauthenticationRequired
        }
    }

    static func exchangeCode(from callbackURL: URL) throws -> String {
        guard callbackURL.scheme == callbackScheme,
            callbackURL.host == callbackHost,
            callbackURL.path == callbackPath,
            callbackURL.fragment == nil,
            let components = URLComponents(url: callbackURL, resolvingAgainstBaseURL: false)
        else {
            throw NativeAuthenticationError.invalidCallback
        }
        let codes = (components.queryItems ?? []).filter { $0.name == "code" }
        guard codes.count == 1,
            let code = codes[0].value,
            isNativeOpaqueToken(code),
            components.queryItems?.count == 1
        else {
            throw NativeAuthenticationError.invalidCallback
        }
        return code
    }

    static func makePKCEVerifier() throws -> String {
        var bytes = [UInt8](repeating: 0, count: 32)
        guard SecRandomCopyBytes(kSecRandomDefault, bytes.count, &bytes) == errSecSuccess else {
            throw NativeAuthenticationError.randomGenerationFailed
        }
        return Data(bytes).base64URLEncodedString()
    }

    static func pkceChallenge(_ verifier: String) -> String {
        Data(SHA256.hash(data: Data(verifier.utf8))).base64URLEncodedString()
    }

    private static func isUnauthorized(_ error: Error) -> Bool {
        guard let apiError = error as? NativeAPIError else { return false }
        return switch apiError {
        case .problem(let problem):
            problem.status == 401
        case .malformedProblem(let statusCode):
            statusCode == 401
        default:
            false
        }
    }
}

@MainActor
final class SystemOAuthSession: NSObject, NativeOAuthSession,
    ASWebAuthenticationPresentationContextProviding
{
    private var session: ASWebAuthenticationSession?
    private var anchor: ASPresentationAnchor?

    func authenticate(url: URL, callbackScheme: String) async throws -> URL {
        guard session == nil,
            let anchor = NSApplication.shared.keyWindow ?? NSApplication.shared.windows.first
        else {
            throw NativeAuthenticationError.browserUnavailable
        }
        self.anchor = anchor
        return try await withCheckedThrowingContinuation { continuation in
            let session = ASWebAuthenticationSession(
                url: url,
                callbackURLScheme: callbackScheme
            ) { [weak self] callbackURL, error in
                Task { @MainActor in
                    self?.session = nil
                    self?.anchor = nil
                    if let callbackURL {
                        continuation.resume(returning: callbackURL)
                    } else if let authError = error as? ASWebAuthenticationSessionError,
                        authError.code == .canceledLogin
                    {
                        continuation.resume(throwing: NativeAuthenticationError.browserCancelled)
                    } else {
                        continuation.resume(throwing: NativeAuthenticationError.browserUnavailable)
                    }
                }
            }
            session.presentationContextProvider = self
            session.prefersEphemeralWebBrowserSession = true
            self.session = session
            guard session.start() else {
                self.session = nil
                self.anchor = nil
                continuation.resume(throwing: NativeAuthenticationError.browserUnavailable)
                return
            }
        }
    }

    func presentationAnchor(for _: ASWebAuthenticationSession) -> ASPresentationAnchor {
        return anchor ?? ASPresentationAnchor()
    }
}

func isNativeOpaqueToken(_ token: String) -> Bool {
    let bytes = Array(token.utf8)
    return bytes.count == 43
        && bytes.allSatisfy {
            (65...90).contains($0)
                || (97...122).contains($0)
                || (48...57).contains($0)
                || $0 == 45
                || $0 == 95
        }
}

extension Data {
    fileprivate func base64URLEncodedString() -> String {
        base64EncodedString()
            .replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "=", with: "")
    }
}
