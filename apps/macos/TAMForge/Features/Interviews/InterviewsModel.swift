import Foundation

/// The Interviews section: the list, one record being edited, and its recordings' transcripts.
@MainActor
final class InterviewsModel: ObservableObject {
    @Published private(set) var interviews: [InterviewRecord] = []
    @Published private(set) var selectedID: Int?
    @Published var draft = InterviewDraft.empty()
    @Published private(set) var analyses: [UUID: RecordingAnalysis] = [:]
    @Published private(set) var timeline: InterviewTimeline = .empty
    @Published private(set) var references: [ReferenceEntry] = []
    @Published private(set) var referenceOutcome: ReferenceImportOutcome?
    @Published private(set) var practiceReviews: [PracticeAnswerReview] = []
    /// Answers recorded this session that the server has not accepted yet, usually
    /// because the recording was still uploading. Every refresh sends them again.
    @Published private(set) var unsentPracticeAnswers: [PracticeAnswer] = []
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
        await perform {
            self.interviews = try await self.api.list()
            self.timeline = try await self.api.timeline()
            self.references = try await self.api.references()
            self.practiceReviews = try await self.api.practiceAnswers()
        }
    }

    /// Send one recorded practice answer for review. The call is safe to repeat: the server
    /// stores the answer once and queues its review when the transcript has arrived.
    func submitPracticeAnswer(_ answer: PracticeAnswer) async {
        if !unsentPracticeAnswers.contains(answer) { unsentPracticeAnswers.append(answer) }
        await refreshPracticeReviews()
    }

    /// Retry what the server has not accepted, nudge the answers still waiting for their
    /// transcript, and reload the list.
    func refreshPracticeReviews() async {
        await perform {
            for answer in self.unsentPracticeAnswers {
                _ = try await self.api.submitPracticeAnswer(
                    question: answer.question.prompt, recordingID: answer.recordingID,
                    referenceID: answer.question.entry.id
                )
                self.unsentPracticeAnswers.removeAll { $0 == answer }
            }
            let listed = try await self.api.practiceAnswers()
            for waiting in listed where waiting.isWaiting {
                _ = try await self.api.submitPracticeAnswer(
                    question: waiting.question, recordingID: waiting.recordingID,
                    referenceID: waiting.referenceMaterialID
                )
            }
            self.practiceReviews = listed.contains(where: \.isWaiting)
                ? try await self.api.practiceAnswers() : listed
        }
    }

    /// The maximum the server accepts for one reference document.
    static let maximumReferenceCharacters = 1_048_576

    func references(of kind: ReferenceKind) -> [ReferenceEntry] {
        references.filter { $0.kind == kind }
    }

    /// Send one document (the answer bank or the story catalog) to be split into entries.
    /// Importing the same document again adds nothing: the server matches entries by content.
    func importReference(kind: ReferenceKind, title: String, markdown: String) async {
        let text = markdown.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, text.count <= Self.maximumReferenceCharacters else {
            errorMessage = "The document is empty or larger than the server accepts."
            return
        }
        let name = title.trimmingCharacters(in: .whitespacesAndNewlines)
        await perform {
            self.referenceOutcome = nil
            let outcome = try await self.api.importReference(
                kind: kind, title: name.isEmpty ? kind.title : name, markdown: text
            )
            self.referenceOutcome = outcome
            self.references = try await self.api.references()
        }
    }

    /// Read a chosen file inside the sandbox's security scope and import it.
    func importReference(kind: ReferenceKind, fileURL: URL) async {
        let isScoped = fileURL.startAccessingSecurityScopedResource()
        defer { if isScoped { fileURL.stopAccessingSecurityScopedResource() } }
        guard let markdown = try? String(contentsOf: fileURL, encoding: .utf8) else {
            errorMessage = "The file could not be read as UTF-8 text."
            return
        }
        await importReference(
            kind: kind, title: fileURL.deletingPathExtension().lastPathComponent, markdown: markdown
        )
    }

    /// The comparison dimensions in tracker order, for the timeline table's columns.
    var timelineColumns: [DimensionTrend] { timeline.dimensionTrends }

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
