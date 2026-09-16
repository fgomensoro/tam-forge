import Foundation
import HTTPTypes

@MainActor
protocol CardAPI {
    func due(on localDate: String) async throws -> [CardRecord]
    func create(_ draft: CardDraft) async throws -> CardRecord
    func review(cardID: Int, grade: Int, reviewedOn: String, mode: String, recordingID: UUID?) async throws -> CardReviewOutcome
    func importRoadmapVersion(_ versionID: Int) async throws -> CardImportOutcome
}

@MainActor
final class LiveCardAPI: CardAPI {
    private let transport: NativeAPITransport

    init(transport: NativeAPITransport) {
        self.transport = transport
    }

    func due(on localDate: String) async throws -> [CardRecord] {
        struct Page: Decodable { let items: [CardRecord] }
        return try await request(.get, path: "/api/v1/cards/due?date=\(localDate)", as: Page.self).items
    }

    func create(_ draft: CardDraft) async throws -> CardRecord {
        try await request(.post, path: "/api/v1/cards", body: try NativeJSONCodec.encode(draft), as: CardRecord.self)
    }

    func review(cardID: Int, grade: Int, reviewedOn: String, mode: String, recordingID: UUID?) async throws -> CardReviewOutcome {
        var payload: [String: Any] = ["grade": grade, "reviewed_on": reviewedOn, "mode": mode]
        if let recordingID { payload["recording_id"] = recordingID.uuidString.lowercased() }
        let body = try JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys])
        return try await request(.post, path: "/api/v1/cards/\(cardID)/reviews", body: body, as: CardReviewOutcome.self)
    }

    func importRoadmapVersion(_ versionID: Int) async throws -> CardImportOutcome {
        try await request(.post, path: "/api/v1/cards/imports/roadmap-versions/\(versionID)", as: CardImportOutcome.self)
    }

    private func request<Value: Decodable & Sendable>(
        _ method: HTTPRequest.Method, path: String, body: Data? = nil, as type: Value.Type
    ) async throws -> Value {
        do {
            try Task.checkCancellation()
            let response = try await transport.send(.init(method: method, path: path, body: body))
            return try response.decoded(as: type)
        } catch is CancellationError {
            throw CardAPIError.cancelled
        } catch let error as NativeAPIError {
            throw Self.translate(error)
        } catch let error as URLError where error.code == .cancelled {
            throw CardAPIError.cancelled
        } catch {
            throw CardAPIError.network
        }
    }

    static func translate(_ error: NativeAPIError) -> CardAPIError {
        switch error {
        case let .problem(problem):
            switch problem.status {
            case 401: return .unauthorized
            case 404: return .notFound
            case 422: return .invalid
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
