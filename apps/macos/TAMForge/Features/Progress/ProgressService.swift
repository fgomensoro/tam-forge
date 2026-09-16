import Foundation
import HTTPTypes

@MainActor
protocol ProgressAPI {
    func read() async throws -> ProgressReport
}

@MainActor
final class LiveProgressAPI: ProgressAPI {
    private let transport: NativeAPITransport

    init(transport: NativeAPITransport) {
        self.transport = transport
    }

    func read() async throws -> ProgressReport {
        do {
            try Task.checkCancellation()
            let response = try await transport.send(.init(method: .get, path: "/api/v1/progress"))
            return try response.decoded(as: ProgressReport.self)
        } catch is CancellationError {
            throw ProgressAPIError.cancelled
        } catch let error as NativeAPIError {
            throw Self.translate(error)
        } catch let error as URLError where error.code == .cancelled {
            throw ProgressAPIError.cancelled
        } catch {
            throw ProgressAPIError.network
        }
    }

    static func translate(_ error: NativeAPIError) -> ProgressAPIError {
        switch error {
        case let .problem(problem):
            switch problem.status {
            case 401: return .unauthorized
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
