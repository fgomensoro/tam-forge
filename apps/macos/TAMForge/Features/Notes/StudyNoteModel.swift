import Foundation

/// Drives the study note panel for one activity. The note loads only when the learner
/// opens the panel; a missing note is an empty form, not an error. The Coach may draft it
/// where the block allows coaching; the learner edits and approves, and an approved note
/// is frozen as evidence on the server.
@MainActor
final class StudyNoteModel: ObservableObject {
    @Published private(set) var note: StudyNote?
    @Published private(set) var isOpened = false
    @Published private(set) var isBusy = false
    @Published private(set) var errorMessage: String?
    @Published var title = ""
    @Published var rule = ""
    @Published var explanation = ""
    @Published var example = ""
    @Published var misconceptionsText = ""
    @Published var sourcesText = ""
    @Published var flashcardsText = ""

    let activityID: Int
    private let api: any StudyNoteAPI
    private var validatedQueries: [NoteQueryItem] = []

    init(activityID: Int, api: any StudyNoteAPI) {
        self.activityID = activityID
        self.api = api
    }

    var isApproved: Bool { note?.isApproved ?? false }

    var canSave: Bool {
        !isApproved && !isBusy && !title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    var canApprove: Bool {
        guard let note, !note.isApproved, !isBusy else { return false }
        return !note.title.trimmingCharacters(in: .whitespaces).isEmpty
            && !note.rule.trimmingCharacters(in: .whitespaces).isEmpty
            && note.content == content
    }

    /// What the form holds, in the server's shape. Lines separate list items; a flashcard
    /// line is `question :: answer`.
    var content: StudyNoteContent {
        StudyNoteContent(
            title: title.trimmingCharacters(in: .whitespacesAndNewlines),
            rule: rule.trimmingCharacters(in: .whitespacesAndNewlines),
            explanation: explanation.trimmingCharacters(in: .whitespacesAndNewlines),
            example: example.trimmingCharacters(in: .whitespacesAndNewlines),
            misconceptions: Self.lines(misconceptionsText),
            validatedQueries: validatedQueries,
            sources: Self.lines(sourcesText),
            flashcards: Self.lines(flashcardsText).compactMap { line in
                let parts = line.components(separatedBy: " :: ")
                guard parts.count == 2 else { return nil }
                let question = parts[0].trimmingCharacters(in: .whitespaces)
                let answer = parts[1].trimmingCharacters(in: .whitespaces)
                guard !question.isEmpty, !answer.isEmpty else { return nil }
                return NoteFlashcardItem(question: question, answer: answer)
            }
        )
    }

    func open() async {
        isOpened = true
        await perform(missingIsEmpty: true) { try await self.api.note(activityID: self.activityID) }
    }

    func draft() async {
        await perform { try await self.api.draft(activityID: self.activityID) }
    }

    func save() async {
        guard canSave else { return }
        let content = self.content
        await perform { try await self.api.save(activityID: self.activityID, content: content) }
    }

    func approve() async {
        guard canApprove else { return }
        await perform { try await self.api.approve(activityID: self.activityID) }
    }

    func dismissError() {
        errorMessage = nil
    }

    private func perform(
        missingIsEmpty: Bool = false, _ operation: @escaping () async throws -> StudyNote
    ) async {
        isBusy = true
        defer { isBusy = false }
        do {
            let loaded = try await operation()
            note = loaded
            fill(from: loaded.content)
            errorMessage = nil
        } catch let error as StudyNoteAPIError {
            if error == .notFound, missingIsEmpty {
                note = nil
                errorMessage = nil
            } else if error != .cancelled {
                errorMessage = error.message
            }
        } catch {
            errorMessage = StudyNoteAPIError.network.message
        }
    }

    private func fill(from content: StudyNoteContent) {
        title = content.title
        rule = content.rule
        explanation = content.explanation
        example = content.example
        misconceptionsText = content.misconceptions.joined(separator: "\n")
        sourcesText = content.sources.joined(separator: "\n")
        flashcardsText = content.flashcards.map { "\($0.question) :: \($0.answer)" }.joined(separator: "\n")
        validatedQueries = content.validatedQueries
    }

    private static func lines(_ text: String) -> [String] {
        text.split(whereSeparator: \.isNewline)
            .map { $0.trimmingCharacters(in: .whitespaces) }
            .filter { !$0.isEmpty }
    }
}
