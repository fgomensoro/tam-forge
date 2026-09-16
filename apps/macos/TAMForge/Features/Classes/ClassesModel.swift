import Foundation

/// The English classes section: the list, one session being edited, its recordings' transcripts.
@MainActor
final class ClassesModel: ObservableObject {
    @Published private(set) var classes: [EnglishClassRecord] = []
    @Published private(set) var selectedID: Int?
    @Published var draft = EnglishClassDraft.empty()
    @Published private(set) var analyses: [UUID: RecordingAnalysis] = [:]
    @Published private(set) var isBusy = false
    @Published private(set) var errorMessage: String?

    private let api: any EnglishClassAPI

    init(api: any EnglishClassAPI) {
        self.api = api
    }

    var selected: EnglishClassRecord? { classes.first { $0.id == selectedID } }
    var isCreating: Bool { selectedID == nil }
    var canSave: Bool { draft.isValid && !isBusy }

    func load() async {
        await perform { self.classes = try await self.api.list() }
    }

    func startNew() {
        selectedID = nil
        draft = .empty()
    }

    func select(_ record: EnglishClassRecord) {
        selectedID = record.id
        draft = EnglishClassDraft(record: record)
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

    func attach(recordingID: UUID) async {
        guard let id = selectedID else { return }
        await perform { self.replace(try await self.api.attach(recordingID: recordingID, to: id)) }
    }

    func openTranscript(recordingID: UUID) async {
        await perform { self.analyses[recordingID] = try await self.api.analysis(recordingID: recordingID) }
    }

    func analysis(for recording: ClassRecordingSummary) -> RecordingAnalysis? {
        analyses[recording.recordingID]
    }

    func dismissError() { errorMessage = nil }

    private func replace(_ record: EnglishClassRecord) {
        if let index = classes.firstIndex(where: { $0.id == record.id }) {
            classes[index] = record
        } else {
            classes.insert(record, at: 0)
        }
        draft = EnglishClassDraft(record: record)
    }

    private func perform(_ operation: @escaping () async throws -> Void) async {
        isBusy = true
        defer { isBusy = false }
        do {
            try await operation()
            errorMessage = nil
        } catch let error as EnglishClassAPIError {
            if error != .cancelled { errorMessage = error.message }
        } catch {
            errorMessage = EnglishClassAPIError.network.message
        }
    }
}
