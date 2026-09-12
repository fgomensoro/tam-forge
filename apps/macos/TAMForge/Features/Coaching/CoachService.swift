import Foundation
import HTTPTypes

@MainActor
protocol CoachAPI {
    func thread(activityID: Int) async throws -> CoachThread
    func send(activityID: Int, text: String) async throws -> CoachThread
    func acceptEvidence(activityID: Int, messageID: Int, index: Int) async throws -> CoachThread
}

@MainActor
final class LiveCoachAPI: CoachAPI {
    private let transport: NativeAPITransport

    init(transport: NativeAPITransport) {
        self.transport = transport
    }

    func thread(activityID: Int) async throws -> CoachThread {
        try await request(.get, path: "\(path(activityID))")
    }

    func send(activityID: Int, text: String) async throws -> CoachThread {
        let body = try JSONSerialization.data(withJSONObject: ["text": text], options: [.sortedKeys])
        return try await request(.post, path: "\(path(activityID))/messages", body: body)
    }

    func acceptEvidence(activityID: Int, messageID: Int, index: Int) async throws -> CoachThread {
        let body = try JSONSerialization.data(
            withJSONObject: ["message_id": messageID, "index": index], options: [.sortedKeys]
        )
        return try await request(.post, path: "\(path(activityID))/evidence", body: body)
    }

    private func request(_ method: HTTPRequest.Method, path: String, body: Data? = nil) async throws -> CoachThread {
        do {
            try Task.checkCancellation()
            let response = try await transport.send(.init(method: method, path: path, body: body))
            return try response.decoded(as: CoachThread.self)
        } catch is CancellationError {
            throw CoachAPIError.cancelled
        } catch let error as NativeAPIError {
            throw Self.translate(error)
        } catch let error as URLError where error.code == .cancelled {
            throw CoachAPIError.cancelled
        } catch {
            throw CoachAPIError.network
        }
    }

    static func translate(_ error: NativeAPIError) -> CoachAPIError {
        switch error {
        case let .problem(problem):
            switch (problem.status, problem.code) {
            case (401, _): return .unauthorized
            case (_, "coaching_not_allowed"), (403, _): return .notAllowed
            case (_, "coach_unavailable"), (503, _): return .unavailable
            case (409, _): return .conflict
            default: return .network
            }
        case .emptyResponse, .decodingResponse:
            return .invalidResponse
        default:
            return .network
        }
    }

    private func path(_ activityID: Int) -> String {
        "/api/v1/activities/\(activityID)/coach"
    }
}
