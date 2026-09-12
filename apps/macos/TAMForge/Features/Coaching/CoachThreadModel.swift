import Foundation

/// Drives the coach panel for one activity. The thread is loaded only when the
/// learner opens the panel, so an activity that never asks the coach never
/// touches the coaching endpoints.
@MainActor
final class CoachThreadModel: ObservableObject {
    @Published private(set) var thread: CoachThread?
    @Published private(set) var isOpened = false
    @Published private(set) var isBusy = false
    @Published private(set) var errorMessage: String?
    @Published var draft = ""

    let activityID: Int
    private let api: any CoachAPI

    init(activityID: Int, api: any CoachAPI) {
        self.activityID = activityID
        self.api = api
    }

    var canSend: Bool {
        guard let thread, thread.coachingAllowed, thread.committed, !isBusy else { return false }
        return !draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    func open() async {
        isOpened = true
        await perform { try await self.api.thread(activityID: self.activityID) }
    }

    func send() async {
        let text = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard canSend else { return }
        let sent = await perform { try await self.api.send(activityID: self.activityID, text: text) }
        if sent { draft = "" }
    }

    func accept(messageID: Int, index: Int) async {
        guard !isBusy else { return }
        await perform {
            try await self.api.acceptEvidence(activityID: self.activityID, messageID: messageID, index: index)
        }
    }

    func dismissError() {
        errorMessage = nil
    }

    @discardableResult
    private func perform(_ operation: @escaping () async throws -> CoachThread) async -> Bool {
        isBusy = true
        defer { isBusy = false }
        do {
            thread = try await operation()
            errorMessage = nil
            return true
        } catch let error as CoachAPIError {
            if error == .notAllowed, thread == nil {
                // The server refused the block; show that as a state, not an alert.
                thread = CoachThread(
                    activityID: activityID, threadID: nil, coachingAllowed: false,
                    committed: true, nextStep: "", messages: []
                )
            } else if error != .cancelled {
                errorMessage = error.message
            }
            return false
        } catch {
            errorMessage = CoachAPIError.network.message
            return false
        }
    }
}
