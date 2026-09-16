import Foundation
import HTTPTypes

@MainActor
protocol EnglishClassAPI {
    func list() async throws -> [EnglishClassRecord]
    func create(_ draft: EnglishClassDraft) async throws -> EnglishClassRecord
    func update(id: Int, draft: EnglishClassDraft) async throws -> EnglishClassRecord
    func attach(recordingID: UUID, to id: Int) async throws -> EnglishClassRecord
    func analysis(recordingID: UUID) async throws -> RecordingAnalysis
}

@MainActor
final class LiveEnglishClassAPI: EnglishClassAPI {
    private let transport: NativeAPITransport
    private let recordings: any RecordingServerServicing

    init(transport: NativeAPITransport, recordings: any RecordingServerServicing) {
        self.transport = transport
        self.recordings = recordings
    }

    func list() async throws -> [EnglishClassRecord] {
        struct Page: Decodable { let items: [EnglishClassRecord] }
        return try await request(.get, path: "/api/v1/english-classes", as: Page.self).items
    }

    func create(_ draft: EnglishClassDraft) async throws -> EnglishClassRecord {
        try await request(.post, path: "/api/v1/english-classes", body: try NativeJSONCodec.encode(draft), as: EnglishClassRecord.self)
    }

    func update(id: Int, draft: EnglishClassDraft) async throws -> EnglishClassRecord {
        try await request(.put, path: "/api/v1/english-classes/\(id)", body: try NativeJSONCodec.encode(draft), as: EnglishClassRecord.self)
    }

    func attach(recordingID: UUID, to id: Int) async throws -> EnglishClassRecord {
        let body = try JSONSerialization.data(
            withJSONObject: ["recording_id": recordingID.uuidString.lowercased()], options: [.sortedKeys]
        )
        return try await request(.post, path: "/api/v1/english-classes/\(id)/recordings", body: body, as: EnglishClassRecord.self)
    }

    func analysis(recordingID: UUID) async throws -> RecordingAnalysis {
        do {
            return try await recordings.analysis(recordingID: recordingID)
        } catch {
            throw EnglishClassAPIError.network
        }
    }

    private func request<Value: Decodable & Sendable>(
        _ method: HTTPRequest.Method, path: String, body: Data? = nil, as type: Value.Type
    ) async throws -> Value {
        do {
            try Task.checkCancellation()
            let response = try await transport.send(.init(method: method, path: path, body: body))
            return try response.decoded(as: type)
        } catch is CancellationError {
            throw EnglishClassAPIError.cancelled
        } catch let error as NativeAPIError {
            throw Self.translate(error)
        } catch let error as URLError where error.code == .cancelled {
            throw EnglishClassAPIError.cancelled
        } catch {
            throw EnglishClassAPIError.network
        }
    }

    static func translate(_ error: NativeAPIError) -> EnglishClassAPIError {
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
