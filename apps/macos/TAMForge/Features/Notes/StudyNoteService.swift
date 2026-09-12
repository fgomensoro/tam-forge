import Foundation
import HTTPTypes

@MainActor
protocol StudyNoteAPI {
    func note(activityID: Int) async throws -> StudyNote
    func draft(activityID: Int) async throws -> StudyNote
    func save(activityID: Int, content: StudyNoteContent) async throws -> StudyNote
    func approve(activityID: Int) async throws -> StudyNote
}

@MainActor
final class LiveStudyNoteAPI: StudyNoteAPI {
    private let transport: NativeAPITransport

    init(transport: NativeAPITransport) {
        self.transport = transport
    }

    func note(activityID: Int) async throws -> StudyNote {
        try await request(.get, path: path(activityID))
    }

    func draft(activityID: Int) async throws -> StudyNote {
        try await request(.post, path: "\(path(activityID))/draft")
    }

    func save(activityID: Int, content: StudyNoteContent) async throws -> StudyNote {
        let body = try NativeJSONCodec.encode(content)
        return try await request(.put, path: path(activityID), body: body)
    }

    func approve(activityID: Int) async throws -> StudyNote {
        try await request(.post, path: "\(path(activityID))/approve")
    }

    private func request(_ method: HTTPRequest.Method, path: String, body: Data? = nil) async throws -> StudyNote {
        do {
            try Task.checkCancellation()
            let response = try await transport.send(.init(method: method, path: path, body: body))
            return try response.decoded(as: StudyNote.self)
        } catch is CancellationError {
            throw StudyNoteAPIError.cancelled
        } catch let error as NativeAPIError {
            throw Self.translate(error)
        } catch let error as URLError where error.code == .cancelled {
            throw StudyNoteAPIError.cancelled
        } catch {
            throw StudyNoteAPIError.network
        }
    }

    static func translate(_ error: NativeAPIError) -> StudyNoteAPIError {
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

    private func path(_ activityID: Int) -> String {
        "/api/v1/activities/\(activityID)/note"
    }
}
