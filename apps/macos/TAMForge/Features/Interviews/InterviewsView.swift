import SwiftUI

/// Real interviews: list and edit the records, attach a recording before or after,
/// and open each recording's transcript.
struct InterviewsView: View {
    @ObservedObject var model: InterviewsModel
    @ObservedObject var coordinator: RecordingCoordinator
    @StateObject private var practice: InterviewPracticeModel
    @State private var importingReferenceKind: ReferenceKind?

    init(model: InterviewsModel, coordinator: RecordingCoordinator) {
        self.model = model
        self.coordinator = coordinator
        _practice = StateObject(
            wrappedValue: InterviewPracticeModel(synthesizer: SystemSpeechSynthesizer(), recorder: coordinator)
        )
    }

    var body: some View {
        HStack(alignment: .top, spacing: 16) {
            list.frame(width: 280)
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    practiceSection
                    editor
                    timelineSection
                    referenceSection
                }
                .padding()
            }
        }
        .padding()
        .task { await model.load() }
        .accessibilityIdentifier("interviewsScreen")
        .onChange(of: coordinator.transcriptState) { _, state in
            // A transcript just finished on this Mac: the answers waiting for it can queue.
            if case .ready = state { Task { await model.refreshPracticeReviews() } }
        }
        .fileImporter(
            isPresented: Binding(
                get: { importingReferenceKind != nil },
                set: { if !$0 { importingReferenceKind = nil } }
            ),
            allowedContentTypes: [.plainText, .text, .item],
            allowsMultipleSelection: false
        ) { result in
            guard let kind = importingReferenceKind, let url = try? result.get().first else { return }
            Task { await model.importReference(kind: kind, fileURL: url) }
        }
    }

    /// Free practice: the interviewer asks the answer bank aloud, one question at a time.
    private var practiceSection: some View {
        GroupBox("Practice your answers aloud") {
            VStack(alignment: .leading, spacing: 10) {
                if let question = practice.current {
                    Text(practice.progress).font(.caption).foregroundStyle(.secondary)
                    Text(question.prompt).font(.title3).textSelection(.enabled)
                        .accessibilityIdentifier("practiceQuestion")
                    HStack {
                        if practice.isAnswering {
                            Button("Stop, that is my answer") {
                                Task {
                                    await practice.endAnswer()
                                    if let answer = practice.answers.last { await model.submitPracticeAnswer(answer) }
                                }
                            }
                                .accessibilityIdentifier("practiceEndAnswer")
                            Text("Recording. The interviewer will not interrupt.")
                                .font(.caption).foregroundStyle(.secondary)
                        } else if practice.canMoveOn {
                            Button("Show my reference answer") { practice.revealReference() }
                                .disabled(!practice.canRevealReference)
                            Button("Next question") { practice.next() }
                                .accessibilityIdentifier("practiceNext")
                        } else {
                            Button("Record my answer") { Task { await practice.beginAnswer() } }
                                .disabled(!practice.canBeginAnswer || coordinator.phase.isActive)
                                .accessibilityIdentifier("practiceBeginAnswer")
                            Button("Repeat the question") { practice.repeatQuestion() }
                        }
                        Spacer()
                        Button("End practice") { practice.stop() }.disabled(practice.isAnswering)
                    }
                    if let reference = practice.revealedReference {
                        Text(reference).textSelection(.enabled)
                            .padding(8)
                            .background(Color.secondary.opacity(0.08), in: RoundedRectangle(cornerRadius: 6))
                            .accessibilityIdentifier("practiceReference")
                    }
                } else {
                    Text("The interviewer asks your answer bank questions aloud, one at a time, in random order. You answer without interruptions while it records, and only then compare with your own reference answer. Each answer is a recording: it is transcribed like any other and you can open it from the Recording screen.")
                        .font(.caption).foregroundStyle(.secondary)
                    HStack {
                        Button(practice.isFinished ? "Practice again" : "Start practice") {
                            practice.start(entries: model.references)
                        }
                        .disabled(model.references(of: .answerBank).isEmpty || coordinator.phase.isActive)
                        .accessibilityIdentifier("practiceStart")
                        if practice.isFinished {
                            Text("Round finished: \(practice.answers.count) answer\(practice.answers.count == 1 ? "" : "s") recorded.")
                                .font(.caption).foregroundStyle(.secondary)
                        } else if model.references(of: .answerBank).isEmpty {
                            Text("Import your answer bank below to start.").font(.caption).foregroundStyle(.secondary)
                        }
                    }
                }
                if let message = practice.message {
                    Label(message, systemImage: "exclamationmark.triangle").foregroundStyle(Color.orange)
                        .accessibilityIdentifier("practiceMessage")
                }
                practiceReviews
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    /// Each recorded answer and what the reviewer made of it.
    @ViewBuilder
    private var practiceReviews: some View {
        if !model.practiceReviews.isEmpty || !model.unsentPracticeAnswers.isEmpty {
            Divider()
            HStack {
                Text("Your practice answers").font(.headline)
                Spacer()
                Button("Refresh reviews") { Task { await model.refreshPracticeReviews() } }
                    .disabled(model.isBusy)
                    .accessibilityIdentifier("practiceRefresh")
            }
            if !model.unsentPracticeAnswers.isEmpty {
                Text("\(model.unsentPracticeAnswers.count) answer\(model.unsentPracticeAnswers.count == 1 ? "" : "s") still uploading. Refresh in a moment.")
                    .font(.caption).foregroundStyle(.secondary)
            }
            ForEach(model.practiceReviews) { review in
                VStack(alignment: .leading, spacing: 4) {
                    HStack(alignment: .firstTextBaseline) {
                        Text(review.question).fontWeight(.medium)
                        Spacer()
                        Text(review.statusLabel).font(.caption).foregroundStyle(.secondary)
                    }
                    ForEach(review.dimensions) { dimension in
                        HStack(alignment: .firstTextBaseline) {
                            Text("\(dimension.name): \(NSDecimalNumber(decimal: dimension.score).stringValue) / 4")
                                .font(.caption).monospacedDigit()
                            Text("“\(dimension.evidence)” \(dimension.note)")
                                .font(.caption).foregroundStyle(.secondary)
                        }
                    }
                    ForEach(review.fixes) { fix in
                        Text("Say “\(fix.sayInstead)” instead of “\(fix.heard)”. \(fix.why)")
                            .font(.caption)
                    }
                    if !review.referenceCoverage.isEmpty {
                        Text(review.referenceCoverage).font(.caption).foregroundStyle(.secondary)
                    }
                    Button("Open transcript") { Task { await model.openTranscript(recordingID: review.recordingID) } }
                        .buttonStyle(.link).font(.caption)
                    if let analysis = model.analyses[review.recordingID] {
                        ForEach(Array(analysis.turns.enumerated()), id: \.offset) { _, turn in
                            Text("\(turn.speaker == "learner" ? "You" : "Interviewer"): \(turn.text)")
                                .font(.caption).foregroundStyle(.secondary)
                        }
                    }
                }
                .padding(.vertical, 2)
            }
        }
    }

    /// The answer bank and the story catalog: what the Coach and the debrief may cite.
    private var referenceSection: some View {
        GroupBox("Interview reference") {
            VStack(alignment: .leading, spacing: 10) {
                Text("Import your answer bank and your story catalog as Markdown, one heading per entry. The Coach and the interview debrief cite them; nothing is treated as demonstrated until a recording shows it. Importing the same file again adds nothing.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                HStack {
                    ForEach(ReferenceKind.allCases) { kind in
                        Button("Import \(kind.title.lowercased())…") { importingReferenceKind = kind }
                            .disabled(model.isBusy)
                            .accessibilityIdentifier("referenceImport-\(kind.rawValue)")
                    }
                }
                if let outcome = model.referenceOutcome {
                    Text("\(outcome.kind.title): \(outcome.created) new, \(outcome.existing) already known.")
                        .font(.caption)
                        .accessibilityIdentifier("referenceImportOutcome")
                }
                ForEach(ReferenceKind.allCases) { kind in
                    let entries = model.references(of: kind)
                    if !entries.isEmpty {
                        Text("\(kind.title) · \(entries.count)").font(.headline)
                        ForEach(entries) { entry in
                            HStack(alignment: .firstTextBaseline) {
                                Text(entry.heading).lineLimit(2)
                                Spacer()
                                if !entry.readinessLabel.isEmpty {
                                    Text(entry.readinessLabel).font(.caption).foregroundStyle(.secondary)
                                }
                            }
                        }
                    }
                }
                if model.references.isEmpty {
                    Text("Nothing imported yet.").foregroundStyle(.secondary)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private var list: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text("Interviews").font(.title2.weight(.semibold))
                Spacer()
                Button("New") { model.startNew() }.accessibilityIdentifier("interviewNew")
            }
            if model.interviews.isEmpty {
                Text("No interviews yet.").foregroundStyle(.secondary)
            }
            List(model.interviews, selection: Binding(
                get: { model.selectedID },
                set: { id in if let record = model.interviews.first(where: { $0.id == id }) { model.select(record) } }
            )) { record in
                VStack(alignment: .leading) {
                    Text("\(record.company) · \(record.role)").font(.body.weight(.medium))
                    Text("\(record.stage) · \(record.startsAt, style: .date) · \(record.status)")
                        .font(.caption).foregroundStyle(.secondary)
                }
                .tag(record.id)
            }
            .accessibilityIdentifier("interviewList")
        }
    }

    /// The sequence of interviews on Frank's four comparison dimensions, and the gaps that
    /// keep coming back. Hiring progression sits apart: advancing is not proof of better
    /// communication.
    private var timelineSection: some View {
        GroupBox("Interview timeline") {
            VStack(alignment: .leading, spacing: 10) {
                let debriefed = model.timeline.items.filter(\.hasDebrief)
                if debriefed.isEmpty {
                    Text("Debrief an interview to see it here.").foregroundStyle(.secondary)
                        .accessibilityIdentifier("interviewTimelineEmpty")
                } else {
                    HStack(spacing: 8) {
                        Text("Interview").font(.caption.weight(.semibold)).frame(width: 150, alignment: .leading)
                        ForEach(model.timelineColumns) { trend in
                            Text(trend.name).font(.caption.weight(.semibold)).frame(width: 90, alignment: .leading).lineLimit(2)
                        }
                        Text("Hiring").font(.caption.weight(.semibold)).frame(minWidth: 100, alignment: .leading)
                    }
                    ForEach(debriefed) { item in
                        HStack(spacing: 8) {
                            VStack(alignment: .leading) {
                                Text("\(item.company) · \(item.stage)").font(.body.weight(.medium)).lineLimit(1)
                                Text(item.startsAt, style: .date).font(.caption).foregroundStyle(.secondary)
                            }
                            .frame(width: 150, alignment: .leading)
                            ForEach(model.timelineColumns) { trend in
                                Text(item.score(trend.slug).map { "\($0)" } ?? "–")
                                    .font(.body.monospacedDigit()).frame(width: 90, alignment: .leading)
                            }
                            Text(item.hiringProgression ?? "").font(.caption).foregroundStyle(.secondary)
                                .frame(minWidth: 100, alignment: .leading).lineLimit(2)
                        }
                        .accessibilityIdentifier("interviewTimelineRow-\(item.interviewID)")
                    }
                    HStack(spacing: 8) {
                        Text("Change since first").font(.caption).frame(width: 150, alignment: .leading)
                        ForEach(model.timelineColumns) { trend in
                            Text(trend.deltaFromFirst.map { delta in (delta >= 0 ? "+" : "") + "\(delta)" } ?? "–")
                                .font(.caption.monospacedDigit()).frame(width: 90, alignment: .leading)
                        }
                    }
                }
                if !model.timeline.recurringGaps.isEmpty {
                    Text("Recurring gaps").font(.subheadline.weight(.medium))
                    ForEach(model.timeline.recurringGaps) { gap in
                        VStack(alignment: .leading, spacing: 2) {
                            Text("\(gap.skillSlug.replacingOccurrences(of: "_", with: " ")) · \(gap.interviewCount) interviews")
                                .font(.body.weight(.medium))
                            ForEach(gap.statements, id: \.self) { statement in
                                Text(statement).font(.caption).foregroundStyle(.secondary)
                            }
                        }
                        .accessibilityIdentifier("interviewRecurringGap-\(gap.skillSlug)")
                    }
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .accessibilityIdentifier("interviewTimeline")
    }

    private var editor: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(model.isCreating ? "New interview" : "Interview").font(.headline)
            TextField("Company", text: $model.draft.company).accessibilityIdentifier("interviewCompany")
            TextField("Role", text: $model.draft.role).accessibilityIdentifier("interviewRole")
            TextField("Stage (screen, technical, panel…)", text: $model.draft.stage)
                .accessibilityIdentifier("interviewStage")
            DatePicker("Starts", selection: $model.draft.startsAt)
            Stepper("Expected \(model.draft.expectedDurationMinutes) min", value: $model.draft.expectedDurationMinutes, in: 1...480, step: 5)
            Picker("Status", selection: $model.draft.status) {
                ForEach(InterviewDraft.statuses, id: \.self) { Text($0.capitalized).tag($0) }
            }
            Picker("Recording permission", selection: $model.draft.privacyPermissionCode) {
                ForEach(InterviewDraft.privacyCodes, id: \.self) {
                    Text($0.replacingOccurrences(of: "_", with: " ")).tag($0)
                }
            }
            HStack {
                Button(model.isCreating ? "Create" : "Save") { Task { await model.save() } }
                    .buttonStyle(.borderedProminent)
                    .disabled(!model.canSave)
                    .accessibilityIdentifier("interviewSave")
                if model.isBusy { ProgressView().controlSize(.small) }
            }
            if let selected = model.selected { recordings(selected) }
            if let message = model.errorMessage {
                Label(message, systemImage: "exclamationmark.triangle").foregroundStyle(.orange)
                    .accessibilityIdentifier("interviewError")
            }
        }
        .textFieldStyle(.roundedBorder)
    }

    @ViewBuilder
    private func recordings(_ interview: InterviewRecord) -> some View {
        Divider()
        Text("Recordings").font(.headline)
        HStack {
            Button("Record this interview") {
                Task { await coordinator.start(interviewID: interview.id) }
            }
            .disabled(coordinator.phase.isActive || interview.privacyPermissionCode == "recording_prohibited")
            .accessibilityIdentifier("interviewRecord")
            if let last = coordinator.lastRecordingID,
               !interview.recordings.contains(where: { $0.recordingID == last }) {
                Button("Attach the last recording") { Task { await model.attach(recordingID: last) } }
                    .accessibilityIdentifier("interviewAttachLast")
            }
        }
        if interview.privacyPermissionCode == "recording_prohibited" {
            Text("Recording is prohibited for this interview.").font(.caption).foregroundStyle(.orange)
        }
        if interview.recordings.isEmpty {
            Text("No recordings attached.").foregroundStyle(.secondary)
        }
        ForEach(interview.recordings) { recording in
            VStack(alignment: .leading, spacing: 6) {
                HStack {
                    if let startedAt = recording.startedAt { Text(startedAt, style: .time) }
                    Text(recording.state.replacingOccurrences(of: "_", with: " "))
                        .font(.caption).foregroundStyle(.secondary)
                    Spacer()
                    if recording.transcriptLineageAccepted {
                        Button("Open transcript") { Task { await model.openTranscript(recordingID: recording.recordingID) } }
                            .accessibilityIdentifier("interviewOpenTranscript")
                    } else {
                        Text("Transcript pending").font(.caption).foregroundStyle(.secondary)
                    }
                }
                if let analysis = model.analysis(for: recording) {
                    if analysis.turns.isEmpty {
                        Text(analysis.status == "published" ? "No speech in this recording." : "Transcript \(analysis.status.replacingOccurrences(of: "_", with: " ")).")
                            .font(.caption).foregroundStyle(.secondary)
                    }
                    ForEach(analysis.turns) { turn in
                        HStack(alignment: .top, spacing: 8) {
                            Text(timestamp(turn.startMS)).font(.caption.monospacedDigit()).foregroundStyle(.secondary)
                            Text(turn.isLearner ? "You" : "Interviewer").font(.caption.weight(.semibold)).frame(width: 72, alignment: .leading)
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
