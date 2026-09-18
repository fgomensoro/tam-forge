import Foundation
import HTTPTypes

@MainActor
protocol InterviewAPI {
    func list() async throws -> [InterviewRecord]
    func create(_ draft: InterviewDraft) async throws -> InterviewRecord
    func update(id: Int, draft: InterviewDraft) async throws -> InterviewRecord
    func attach(recordingID: UUID, to id: Int) async throws -> InterviewRecord
    func analysis(recordingID: UUID) async throws -> RecordingAnalysis
    func timeline() async throws -> InterviewTimeline
    func references() async throws -> [ReferenceEntry]
    func importReference(kind: ReferenceKind, title: String, markdown: String) async throws -> ReferenceImportOutcome
    func practiceAnswers() async throws -> [PracticeAnswerReview]
    func submitPracticeAnswer(question: String, recordingID: UUID, referenceID: Int?) async throws -> PracticeAnswerReview
}

@MainActor
final class LiveInterviewAPI: InterviewAPI {
    private let transport: NativeAPITransport
    private let recordings: any RecordingServerServicing

    init(transport: NativeAPITransport, recordings: any RecordingServerServicing) {
        self.transport = transport
        self.recordings = recordings
    }

    func list() async throws -> [InterviewRecord] {
        struct Page: Decodable { let items: [InterviewRecord] }
        return try await request(.get, path: "/api/v1/interviews", as: Page.self).items
    }

    func create(_ draft: InterviewDraft) async throws -> InterviewRecord {
        try await request(.post, path: "/api/v1/interviews", body: try NativeJSONCodec.encode(draft), as: InterviewRecord.self)
    }

    func update(id: Int, draft: InterviewDraft) async throws -> InterviewRecord {
        try await request(.put, path: "/api/v1/interviews/\(id)", body: try NativeJSONCodec.encode(draft), as: InterviewRecord.self)
    }

    func attach(recordingID: UUID, to id: Int) async throws -> InterviewRecord {
        let body = try JSONSerialization.data(
            withJSONObject: ["recording_id": recordingID.uuidString.lowercased()], options: [.sortedKeys]
        )
        return try await request(.post, path: "/api/v1/interviews/\(id)/recordings", body: body, as: InterviewRecord.self)
    }

    func analysis(recordingID: UUID) async throws -> RecordingAnalysis {
        do {
            return try await recordings.analysis(recordingID: recordingID)
        } catch {
            throw InterviewAPIError.network
        }
    }

    func timeline() async throws -> InterviewTimeline {
        try await request(.get, path: "/api/v1/interviews/timeline", as: InterviewTimeline.self)
    }

    func references() async throws -> [ReferenceEntry] {
        struct Page: Decodable { let items: [ReferenceEntry] }
        return try await request(.get, path: "/api/v1/reference-material", as: Page.self).items
    }

    func importReference(kind: ReferenceKind, title: String, markdown: String) async throws -> ReferenceImportOutcome {
        let body = try JSONSerialization.data(
            withJSONObject: ["kind": kind.rawValue, "title": title, "markdown": markdown], options: [.sortedKeys]
        )
        return try await request(.post, path: "/api/v1/reference-material", body: body, as: ReferenceImportOutcome.self)
    }

    func practiceAnswers() async throws -> [PracticeAnswerReview] {
        struct Page: Decodable { let items: [PracticeAnswerReview] }
        return try await request(.get, path: "/api/v1/practice-answers", as: Page.self).items
    }

    func submitPracticeAnswer(question: String, recordingID: UUID, referenceID: Int?) async throws -> PracticeAnswerReview {
        var payload: [String: Any] = ["question": question, "recording_id": recordingID.uuidString.lowercased()]
        if let referenceID { payload["reference_material_id"] = referenceID }
        let body = try JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys])
        return try await request(.post, path: "/api/v1/practice-answers", body: body, as: PracticeAnswerReview.self)
    }

    private func request<Value: Decodable & Sendable>(
        _ method: HTTPRequest.Method, path: String, body: Data? = nil, as type: Value.Type
    ) async throws -> Value {
        do {
            try Task.checkCancellation()
            let response = try await transport.send(.init(method: method, path: path, body: body))
            return try response.decoded(as: type)
        } catch is CancellationError {
            throw InterviewAPIError.cancelled
        } catch let error as NativeAPIError {
            throw Self.translate(error)
        } catch let error as URLError where error.code == .cancelled {
            throw InterviewAPIError.cancelled
        } catch {
            throw InterviewAPIError.network
        }
    }

    static func translate(_ error: NativeAPIError) -> InterviewAPIError {
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
