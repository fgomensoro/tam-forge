import Foundation

/// Drives the review panel for one activity. The review loads only when the learner
/// opens the panel; the Claude worker on the server produces it, the app only asks
/// for it and shows it.
@MainActor
final class ReviewModel: ObservableObject {
    @Published private(set) var review: ActivityReview?
    @Published private(set) var isOpened = false
    @Published private(set) var isBusy = false
    @Published private(set) var errorMessage: String?

    let activityID: Int
    private let api: any ReviewAPI

    init(activityID: Int, api: any ReviewAPI) {
        self.activityID = activityID
        self.api = api
    }

    var canRequest: Bool {
        guard let review, !isBusy else { return false }
        return review.status == "not_requested" || review.status == "needs_attention"
    }

    var isPending: Bool {
        guard let review else { return false }
        return review.status == "queued" || review.status == "running"
    }

    func open() async {
        isOpened = true
        await perform { try await self.api.review(activityID: self.activityID) }
    }

    func refresh() async {
        await perform { try await self.api.review(activityID: self.activityID) }
    }

    func request() async {
        guard canRequest else { return }
        await perform { try await self.api.requestReview(activityID: self.activityID) }
    }

    func dismissError() {
        errorMessage = nil
    }

    private func perform(_ operation: @escaping () async throws -> ActivityReview) async {
        isBusy = true
        defer { isBusy = false }
        do {
            review = try await operation()
            errorMessage = nil
        } catch let error as ReviewAPIError {
            if error != .cancelled { errorMessage = error.message }
        } catch {
            errorMessage = ReviewAPIError.network.message
        }
    }
}
