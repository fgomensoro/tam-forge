import Foundation
import OpenAPIRuntime
import OpenAPIURLSession

struct LiveNativeAuthHTTPClient: NativeAuthHTTPClient {
    private let client: Client

    init(baseURL: URL, session: URLSession? = nil) {
        let configuredSession: URLSession
        if let session {
            configuredSession = session
        } else {
            let configuration = URLSessionConfiguration.ephemeral
            configuration.urlCache = nil
            configuration.requestCachePolicy = .reloadIgnoringLocalAndRemoteCacheData
            configuration.timeoutIntervalForRequest = 15
            configuration.timeoutIntervalForResource = 60
            configuredSession = URLSession(configuration: configuration)
        }
        client = Client(
            serverURL: baseURL,
            transport: URLSessionTransport(configuration: .init(session: configuredSession))
        )
    }

    func start(codeChallenge: String) async throws -> URL {
        do {
            let output = try await client.nativeStartApiV1AuthNativeStartPost(
                body: .json(.init(codeChallenge: codeChallenge))
            )
            let response = try output.ok.body.json
            guard let url = URL(string: response.authorizationUrl),
                  url.scheme == "https",
                  url.host?.lowercased() == "github.com"
            else {
                throw NativeAuthenticationError.browserUnavailable
            }
            return url
        } catch let error as NativeAuthenticationError {
            throw error
        } catch {
            throw NativeAuthenticationError.browserUnavailable
        }
    }

    func exchange(code: String, codeVerifier: String) async throws -> NativeTokenPair {
        do {
            let output = try await client.nativeExchangeApiV1AuthNativeExchangePost(
                body: .json(.init(code: code, codeVerifier: codeVerifier))
            )
            return try output.ok.body.json.tokenPair
        } catch {
            throw NativeAuthenticationError.reauthenticationRequired
        }
    }

    func refresh(refreshToken: String) async throws -> NativeTokenPair {
        do {
            let output = try await client.nativeRefreshApiV1AuthNativeRefreshPost(
                body: .json(.init(refreshToken: refreshToken))
            )
            return try output.ok.body.json.tokenPair
        } catch {
            throw NativeAuthenticationError.reauthenticationRequired
        }
    }

    func revoke(refreshToken: String) async throws {
        do {
            let output = try await client.nativeRevokeApiV1AuthNativeRevokePost(
                body: .json(.init(refreshToken: refreshToken))
            )
            _ = try output.noContent
        } catch {
            throw NativeAuthenticationError.revocationPending
        }
    }
}

private extension Components.Schemas.NativeTokenResponse {
    var tokenPair: NativeTokenPair {
        NativeTokenPair(
            accessToken: accessToken,
            refreshToken: refreshToken,
            expiresIn: TimeInterval(expiresIn),
            githubLogin: githubLogin
        )
    }
}
