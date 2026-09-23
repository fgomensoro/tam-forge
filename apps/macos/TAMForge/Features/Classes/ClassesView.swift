import SwiftUI

/// English classes: keep the session record (teacher, date, notes), record the class,
/// attach a recording made before or after, and open its transcript. Every class maps to
/// the TAM English skill.
struct ClassesView: View {
    @ObservedObject var model: ClassesModel
    @ObservedObject var coordinator: RecordingCoordinator

    var body: some View {
        HStack(alignment: .top, spacing: 0) {
            list
                .frame(width: 300)
                .frame(maxHeight: .infinity, alignment: .top)
                .overlay(alignment: .trailing) {
                    Rectangle().fill(Organic.Color.divider).frame(width: 1)
                }
            ScrollView {
                editor
                    .padding(.top, Organic.Space.p28)
                    .padding(.horizontal, Organic.Space.p36)
                    .padding(.bottom, Organic.Space.p40)
                    .frame(maxWidth: 820, alignment: .leading)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        .task { await model.load() }
        .accessibilityIdentifier("classesScreen")
    }

    // MARK: - List

    private var list: some View {
        VStack(alignment: .leading, spacing: Organic.Space.p14) {
            HStack(spacing: 10) {
                Text("English classes")
                    .font(Organic.Font.figtree(.semibold, size: 24))
                    .tracking(-0.48)
                    .foregroundStyle(Organic.Color.text)
                    .accessibilityAddTraits(.isHeader)
                Spacer(minLength: 0)
                Button { model.startNew() } label: {
                    Image(systemName: "plus")
                        .font(Organic.Font.figtree(.semibold, size: 16))
                        .foregroundStyle(Organic.Color.neutral900)
                        .frame(width: 34, height: 34)
                        .background(Organic.Color.accent400, in: Circle())
                        .contentShape(Circle())
                }
                .buttonStyle(.plain)
                .help("New class")
                .accessibilityLabel("New")
                .accessibilityIdentifier("classNew")
            }
            .padding(.horizontal, Organic.Space.p8)
            if model.classes.isEmpty {
                Text("No classes yet.")
                    .organic(.body, color: Organic.Color.muted)
                    .padding(.horizontal, Organic.Space.p8)
            }
            ScrollView {
                VStack(alignment: .leading, spacing: Organic.Space.p4) {
                    ForEach(model.classes) { record in
                        classRow(record)
                    }
                }
            }
            .accessibilityIdentifier("classList")
        }
        .padding(.vertical, Organic.Space.p28)
        .padding(.horizontal, Organic.Space.p18)
    }

    private func classRow(_ record: EnglishClassRecord) -> some View {
        let isSelected = record.id == model.selectedID
        return Button { model.select(record) } label: {
            VStack(alignment: .leading, spacing: 3) {
                Text(record.teacher).organic(.strong)
                Text("\(record.startsAt.formatted(.dateTime.month(.abbreviated).day())) · \(record.expectedDurationMinutes) min · \(recordingCount(record.recordings.count))")
                    .organic(.caption)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.vertical, Organic.Space.p12)
            .padding(.horizontal, Organic.Space.p14)
            .background(
                isSelected ? Organic.Color.accentOn : Color.clear,
                in: RoundedRectangle(cornerRadius: Organic.Radius.r20, style: .continuous)
            )
            .contentShape(RoundedRectangle(cornerRadius: Organic.Radius.r20, style: .continuous))
        }
        .buttonStyle(.plain)
        .accessibilityAddTraits(isSelected ? .isSelected : [])
    }

    // MARK: - Detail

    private var editor: some View {
        VStack(alignment: .leading, spacing: Organic.Space.p24) {
            OrganicPageHeader(kicker: "Maps to TAM English", title: headerTitle, subtitle: headerSubtitle) {
                if let selected = model.selected { recordButton(selected) }
            }
            Grid(alignment: .topLeading, horizontalSpacing: Organic.Space.p12, verticalSpacing: 0) {
                GridRow {
                    OrganicFieldLabel(title: "Teacher") {
                        TextField("Teacher", text: $model.draft.teacher)
                            .organicField()
                            .accessibilityIdentifier("classTeacher")
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    OrganicFieldLabel(title: "Starts") {
                        DatePicker("Starts", selection: $model.draft.startsAt)
                            .labelsHidden()
                            .datePickerStyle(.field)
                            .organicField()
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    OrganicFieldLabel(title: "Expected") {
                        HStack(spacing: Organic.Space.p8) {
                            Text("\(model.draft.expectedDurationMinutes) min")
                                .organic(.body, color: Organic.Color.text)
                            Spacer(minLength: 0)
                            Stepper("Expected \(model.draft.expectedDurationMinutes) min", value: $model.draft.expectedDurationMinutes, in: 1...480, step: 5)
                                .labelsHidden()
                        }
                        .organicField()
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
            }
            OrganicFieldLabel(title: "Teacher notes") {
                TextEditor(text: $model.draft.notes)
                    .organicEditor(minHeight: 96)
                    .accessibilityIdentifier("classNotes")
            }
            HStack(spacing: Organic.Space.p12) {
                Button(model.isCreating ? "Create" : "Save") { Task { await model.save() } }
                    .buttonStyle(.organicPrimary)
                    .disabled(!model.canSave)
                    .accessibilityIdentifier("classSave")
                if model.isBusy { ProgressView().controlSize(.small) }
            }
            if let selected = model.selected { recordings(selected) }
            if let message = model.errorMessage {
                OrganicNotice(systemImage: "exclamationmark.triangle", tint: Organic.Color.danger, message: message)
                    .accessibilityIdentifier("classError")
            }
        }
    }

    private var headerTitle: String {
        guard let record = model.selected else { return "New class" }
        return "Class with \(record.teacher) · \(record.startsAt.formatted(.dateTime.weekday(.abbreviated).month(.abbreviated).day()))"
    }

    private var headerSubtitle: String {
        guard let record = model.selected else { return "Evidence from this class maps to the TAM English skill." }
        var parts = [
            record.startsAt.formatted(date: .omitted, time: .shortened),
            "\(record.expectedDurationMinutes) min expected",
            recordingCount(record.recordings.count),
        ]
        if record.recordings.contains(where: \.transcriptLineageAccepted) { parts.append("transcript ready") }
        return parts.joined(separator: " · ")
    }

    private func recordButton(_ record: EnglishClassRecord) -> some View {
        Button { Task { await coordinator.start(classID: record.id) } } label: {
            HStack(spacing: Organic.Space.p8) {
                Circle().fill(Organic.Color.neutral900).frame(width: 10, height: 10)
                Text("Record this class")
            }
        }
        .buttonStyle(.organicPrimary)
        .disabled(coordinator.phase.isActive)
        .accessibilityIdentifier("classRecord")
    }

    // MARK: - Recordings

    private func recordings(_ record: EnglishClassRecord) -> some View {
        VStack(alignment: .leading, spacing: Organic.Space.p14) {
            HStack(spacing: Organic.Space.p12) {
                Text("Recordings").organic(.title).accessibilityAddTraits(.isHeader)
                Spacer(minLength: 0)
                if let last = coordinator.lastRecordingID,
                   !record.recordings.contains(where: { $0.recordingID == last }) {
                    Button("Attach the last recording") { Task { await model.attach(recordingID: last) } }
                        .accessibilityIdentifier("classAttachLast")
                }
            }
            if record.recordings.isEmpty {
                Text("No recordings attached.").organic(.body, color: Organic.Color.muted)
            }
            ForEach(record.recordings) { recording in
                recordingCard(recording)
            }
        }
    }

    private func recordingCard(_ recording: ClassRecordingSummary) -> some View {
        VStack(alignment: .leading, spacing: Organic.Space.p14) {
            HStack(spacing: Organic.Space.p12) {
                Text(recordingTitle(recording)).organic(.title)
                Spacer(minLength: 0)
                if recording.transcriptLineageAccepted {
                    Button("Open transcript") { Task { await model.openTranscript(recordingID: recording.recordingID) } }
                        .accessibilityIdentifier("classOpenTranscript")
                } else {
                    Text("Transcript pending").organic(.caption)
                }
            }
            if let analysis = model.analysis(for: recording) {
                Grid(alignment: .topLeading, horizontalSpacing: 10, verticalSpacing: Organic.Space.p14) {
                    ForEach(analysis.turns) { turn in
                        GridRow {
                            Text(timestamp(turn.startMS))
                                .font(Organic.Font.tabular(.regular, size: 13))
                                .foregroundStyle(Organic.Color.faint)
                                .frame(width: 44, alignment: .leading)
                            Text(turn.isLearner ? "You" : "Teacher")
                                .font(Organic.Font.figtree(.semibold, size: 13))
                                .foregroundStyle(turn.isLearner ? Organic.Color.accent300 : Organic.Color.accent2_300)
                                .frame(width: 64, alignment: .leading)
                            Text(turn.text)
                                .font(Organic.Font.figtree(.regular, size: 13))
                                .foregroundStyle(Organic.Color.body)
                                .lineSpacing(3)
                                .textSelection(.enabled)
                                .fixedSize(horizontal: false, vertical: true)
                                .frame(maxWidth: .infinity, alignment: .leading)
                        }
                    }
                }
            }
        }
        .padding(.horizontal, Organic.Space.p24)
        .padding(.vertical, 22)
        .frame(maxWidth: .infinity, alignment: .leading)
        .organicCard(radius: Organic.Radius.r28, padding: 0)
    }

    private func recordingTitle(_ recording: ClassRecordingSummary) -> String {
        var parts = ["Recording"]
        if let startedAt = recording.startedAt { parts.append(startedAt.formatted(date: .omitted, time: .shortened)) }
        parts.append(recording.state.replacingOccurrences(of: "_", with: " "))
        return parts.joined(separator: " · ")
    }

    private func recordingCount(_ count: Int) -> String {
        switch count {
        case 0: "no recording"
        case 1: "1 recording"
        default: "\(count) recordings"
        }
    }

    private func timestamp(_ milliseconds: Int) -> String {
        let seconds = milliseconds / 1000
        return String(format: "%d:%02d", seconds / 60, seconds % 60)
    }
}
