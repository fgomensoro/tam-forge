import SwiftUI

/// English classes: keep the session record (teacher, date, notes), record the class,
/// attach a recording made before or after, and open its transcript. Every class maps to
/// the TAM English skill.
struct ClassesView: View {
    @ObservedObject var model: ClassesModel
    @ObservedObject var coordinator: RecordingCoordinator

    var body: some View {
        HStack(alignment: .top, spacing: 16) {
            list.frame(width: 280)
            ScrollView { editor.padding() }
        }
        .padding()
        .task { await model.load() }
        .accessibilityIdentifier("classesScreen")
    }

    private var list: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text("English classes").font(.title2.weight(.semibold))
                Spacer()
                Button("New") { model.startNew() }.accessibilityIdentifier("classNew")
            }
            if model.classes.isEmpty {
                Text("No classes yet.").foregroundStyle(.secondary)
            }
            List(model.classes, selection: Binding(
                get: { model.selectedID },
                set: { id in if let record = model.classes.first(where: { $0.id == id }) { model.select(record) } }
            )) { record in
                VStack(alignment: .leading) {
                    Text(record.teacher).font(.body.weight(.medium))
                    Text("\(record.startsAt, style: .date) · \(record.expectedDurationMinutes) min")
                        .font(.caption).foregroundStyle(.secondary)
                }
                .tag(record.id)
            }
            .accessibilityIdentifier("classList")
        }
    }

    private var editor: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(model.isCreating ? "New class" : "Class").font(.headline)
            TextField("Teacher", text: $model.draft.teacher).accessibilityIdentifier("classTeacher")
            DatePicker("Starts", selection: $model.draft.startsAt)
            Stepper("Expected \(model.draft.expectedDurationMinutes) min", value: $model.draft.expectedDurationMinutes, in: 1...480, step: 5)
            VStack(alignment: .leading, spacing: 4) {
                Text("Teacher notes").font(.subheadline.weight(.medium))
                TextEditor(text: $model.draft.notes).frame(minHeight: 80).accessibilityIdentifier("classNotes")
            }
            Text("Evidence from this class maps to the TAM English skill.")
                .font(.caption).foregroundStyle(.secondary)
            HStack {
                Button(model.isCreating ? "Create" : "Save") { Task { await model.save() } }
                    .buttonStyle(.borderedProminent)
                    .disabled(!model.canSave)
                    .accessibilityIdentifier("classSave")
                if model.isBusy { ProgressView().controlSize(.small) }
            }
            if let selected = model.selected { recordings(selected) }
            if let message = model.errorMessage {
                Label(message, systemImage: "exclamationmark.triangle").foregroundStyle(.orange)
                    .accessibilityIdentifier("classError")
            }
        }
        .textFieldStyle(.roundedBorder)
    }

    @ViewBuilder
    private func recordings(_ record: EnglishClassRecord) -> some View {
        Divider()
        Text("Recordings").font(.headline)
        HStack {
            Button("Record this class") { Task { await coordinator.start(classID: record.id) } }
                .disabled(coordinator.phase.isActive)
                .accessibilityIdentifier("classRecord")
            if let last = coordinator.lastRecordingID,
               !record.recordings.contains(where: { $0.recordingID == last }) {
                Button("Attach the last recording") { Task { await model.attach(recordingID: last) } }
                    .accessibilityIdentifier("classAttachLast")
            }
        }
        if record.recordings.isEmpty {
            Text("No recordings attached.").foregroundStyle(.secondary)
        }
        ForEach(record.recordings) { recording in
            VStack(alignment: .leading, spacing: 6) {
                HStack {
                    if let startedAt = recording.startedAt { Text(startedAt, style: .time) }
                    Text(recording.state.replacingOccurrences(of: "_", with: " "))
                        .font(.caption).foregroundStyle(.secondary)
                    Spacer()
                    if recording.transcriptLineageAccepted {
                        Button("Open transcript") { Task { await model.openTranscript(recordingID: recording.recordingID) } }
                            .accessibilityIdentifier("classOpenTranscript")
                    } else {
                        Text("Transcript pending").font(.caption).foregroundStyle(.secondary)
                    }
                }
                if let analysis = model.analysis(for: recording) {
                    ForEach(analysis.turns) { turn in
                        HStack(alignment: .top, spacing: 8) {
                            Text(timestamp(turn.startMS)).font(.caption.monospacedDigit()).foregroundStyle(.secondary)
                            Text(turn.isLearner ? "You" : "Teacher").font(.caption.weight(.semibold)).frame(width: 60, alignment: .leading)
                            Text(turn.text).textSelection(.enabled)
                        }
                    }
                }
            }
            .padding(8)
            .background(.quaternary, in: RoundedRectangle(cornerRadius: 6))
        }
    }

    private func timestamp(_ milliseconds: Int) -> String {
        let seconds = milliseconds / 1000
        return String(format: "%d:%02d", seconds / 60, seconds % 60)
    }
}
