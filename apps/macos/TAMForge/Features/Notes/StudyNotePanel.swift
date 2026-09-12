import SwiftUI

/// The end-of-block study note. The Coach drafts where allowed; the learner edits and
/// approves; approval freezes the note as evidence in the database and the object store.
struct StudyNotePanel: View {
    @ObservedObject var model: StudyNoteModel

    var body: some View {
        GroupBox("Study note") {
            VStack(alignment: .leading, spacing: 12) {
                if !model.isOpened {
                    Text("A polished note for this block: rule, example, corrected misconceptions, sources and card-ready Q/A. Approving it stores it as evidence.")
                        .foregroundStyle(.secondary)
                    Button("Open note") { Task { await model.open() } }
                        .accessibilityIdentifier("noteOpen")
                } else if model.isApproved, let note = model.note {
                    approved(note)
                } else {
                    editor
                }
                if let message = model.errorMessage {
                    Label(message, systemImage: "exclamationmark.triangle")
                        .foregroundStyle(.orange)
                        .accessibilityIdentifier("noteError")
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .accessibilityIdentifier("studyNotePanel")
    }

    @ViewBuilder
    private func approved(_ note: StudyNote) -> some View {
        Label("Approved and stored as evidence (\(note.assistance)).", systemImage: "checkmark.seal")
            .accessibilityIdentifier("noteApproved")
        Text(note.title).font(.headline)
        Text(note.rule)
        if !note.flashcards.isEmpty {
            Text("\(note.flashcards.count) card-ready Q/A").font(.caption).foregroundStyle(.secondary)
        }
    }

    @ViewBuilder
    private var editor: some View {
        HStack {
            Button("Draft with the coach") { Task { await model.draft() } }
                .disabled(model.isBusy)
                .accessibilityIdentifier("noteDraft")
            if let note = model.note {
                Text("Drafted by \(note.draftedBy) · \(note.assistance)")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            Spacer()
            if model.isBusy { ProgressView().controlSize(.small) }
        }
        TextField("Title", text: $model.title)
            .textFieldStyle(.roundedBorder)
            .accessibilityIdentifier("noteTitle")
        NoteField(title: "Rule", text: $model.rule, minimumHeight: 48)
        NoteField(title: "Explanation", text: $model.explanation, minimumHeight: 72)
        NoteField(title: "Example", text: $model.example, minimumHeight: 72)
        NoteField(title: "Corrected misconceptions (one per line)", text: $model.misconceptionsText, minimumHeight: 48)
        NoteField(title: "Sources (one per line)", text: $model.sourcesText, minimumHeight: 48)
        NoteField(title: "Card-ready Q/A (question :: answer, one per line)", text: $model.flashcardsText, minimumHeight: 72)
        HStack {
            Button("Save draft") { Task { await model.save() } }
                .disabled(!model.canSave)
                .accessibilityIdentifier("noteSave")
            Spacer()
            Button("Approve as evidence") { Task { await model.approve() } }
                .disabled(!model.canApprove)
                .accessibilityIdentifier("noteApprove")
                .help("Save the draft first; approval freezes the saved note.")
        }
    }
}

private struct NoteField: View {
    var title: String
    @Binding var text: String
    var minimumHeight: CGFloat

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title).font(.subheadline.weight(.medium))
            TextEditor(text: $text)
                .frame(minHeight: minimumHeight)
                .accessibilityLabel(title)
        }
    }
}
