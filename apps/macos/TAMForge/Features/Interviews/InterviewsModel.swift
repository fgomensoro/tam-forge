import Foundation

/// The Interviews section: the list, one record being edited, and its recordings' transcripts.
@MainActor
final class InterviewsModel: ObservableObject {
    @Published private(set) var interviews: [InterviewRecord] = []
    @Published private(set) var selectedID: Int?
    @Published var draft = InterviewDraft.empty()
    @Published private(set) var analyses: [UUID: RecordingAnalysis] = [:]
    @Published private(set) var isBusy = false
    @Published private(set) var errorMessage: String?

    private let api: any InterviewAPI

    init(api: any InterviewAPI) {
        self.api = api
    }

    var selected: InterviewRecord? { interviews.first { $0.id == selectedID } }
    var isCreating: Bool { selectedID == nil }
    var canSave: Bool { draft.isValid && !isBusy }

    func load() async {
        await perform { self.interviews = try await self.api.list() }
    }

    func startNew() {
        selectedID = nil
        draft = .empty()
    }

    func select(_ record: InterviewRecord) {
        selectedID = record.id
        draft = InterviewDraft(record: record)
    }

    func save() async {
        guard canSave else { return }
        let draft = self.draft
        await perform {
            let saved = self.isCreating
                ? try await self.api.create(draft)
                : try await self.api.update(id: self.selectedID!, draft: draft)
            self.replace(saved)
            self.selectedID = saved.id
        }
    }

    /// Attach a recording made before or after the record existed.
    func attach(recordingID: UUID) async {
        guard let id = selectedID else { return }
        await perform {
            let saved = try await self.api.attach(recordingID: recordingID, to: id)
            self.replace(saved)
        }
    }

    /// Open the transcript of one attached recording: the server's speaker turns.
    func openTranscript(recordingID: UUID) async {
        await perform {
            self.analyses[recordingID] = try await self.api.analysis(recordingID: recordingID)
        }
    }

    func analysis(for recording: InterviewRecordingSummary) -> RecordingAnalysis? {
        analyses[recording.recordingID]
    }

    func dismissError() { errorMessage = nil }

    private func replace(_ record: InterviewRecord) {
        if let index = interviews.firstIndex(where: { $0.id == record.id }) {
            interviews[index] = record
        } else {
            interviews.insert(record, at: 0)
        }
        draft = InterviewDraft(record: record)
    }

    private func perform(_ operation: @escaping () async throws -> Void) async {
        isBusy = true
        defer { isBusy = false }
        do {
            try await operation()
            errorMessage = nil
        } catch let error as InterviewAPIError {
            if error != .cancelled { errorMessage = error.message }
        } catch {
            errorMessage = InterviewAPIError.network.message
        }
    }
}
