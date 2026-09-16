import Foundation
import HTTPTypes

@MainActor
protocol ReviewAPI {
    func review(activityID: Int) async throws -> ActivityReview
    func requestReview(activityID: Int) async throws -> ActivityReview
}

@MainActor
final class LiveReviewAPI: ReviewAPI {
    private let transport: NativeAPITransport

    init(transport: NativeAPITransport) {
        self.transport = transport
    }

    func review(activityID: Int) async throws -> ActivityReview {
        try await request(.get, activityID: activityID)
    }

    func requestReview(activityID: Int) async throws -> ActivityReview {
        try await request(.post, activityID: activityID)
    }

    private func request(_ method: HTTPRequest.Method, activityID: Int) async throws -> ActivityReview {
        do {
            try Task.checkCancellation()
            let response = try await transport.send(
                .init(method: method, path: "/api/v1/activities/\(activityID)/review")
            )
            return try response.decoded(as: ActivityReview.self)
        } catch is CancellationError {
            throw ReviewAPIError.cancelled
        } catch let error as NativeAPIError {
            throw Self.translate(error)
        } catch let error as URLError where error.code == .cancelled {
            throw ReviewAPIError.cancelled
        } catch {
            throw ReviewAPIError.network
        }
    }

    static func translate(_ error: NativeAPIError) -> ReviewAPIError {
        switch error {
        case let .problem(problem):
            switch problem.status {
            case 401: return .unauthorized
            case 404: return .notFound
            case 409: return .conflict
            case 503: return .unavailable
            default: return .network
            }
        case .emptyResponse, .decodingResponse:
            return .invalidResponse
        default:
            return .network
        }
    }
}
