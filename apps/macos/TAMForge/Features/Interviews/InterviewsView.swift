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
            wrappedValue: InterviewPracticeModel(
                synthesizer: SystemSpeechSynthesizer(), recorder: coordinator, followUps: model
            )
        )
    }

    var body: some View {
        HStack(alignment: .top, spacing: 0) {
            // The shell already pads the route column, so the list keeps only the
            // gutter before its hairline and the detail only the gutter after it.
            list
                .padding(.trailing, Organic.Space.p18)
                .frame(width: 300)
                .frame(maxHeight: .infinity, alignment: .top)
                .overlay(alignment: .trailing) {
                    Rectangle().fill(Organic.Color.divider).frame(width: 1)
                }
            ScrollView {
                VStack(alignment: .leading, spacing: Organic.Space.p24) {
                    header
                    editor
                    timelineSection
                    practiceSection
                    referenceSection
                }
                .frame(maxWidth: 820, alignment: .leading)
                .padding(.leading, Organic.Space.p36)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
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

    // MARK: - List

    private var list: some View {
        VStack(alignment: .leading, spacing: Organic.Space.p14) {
            HStack(spacing: 10) {
                Text("Interviews")
                    .font(Organic.Font.figtree(.semibold, size: 24))
                    .tracking(-0.48)
                    .foregroundStyle(Organic.Color.text)
                    .accessibilityAddTraits(.isHeader)
                Spacer(minLength: 0)
                Button { model.startNew() } label: {
                    Text("+")
                        .font(Organic.Font.figtree(.regular, size: 20))
                        .foregroundStyle(Organic.Color.neutral900)
                        .frame(width: 34, height: 34)
                        .background(Organic.Color.accent400, in: Circle())
                        .contentShape(Circle())
                }
                .buttonStyle(.plain)
                .accessibilityLabel("New")
                .help("New interview")
                .accessibilityIdentifier("interviewNew")
            }
            .padding(.horizontal, Organic.Space.p8)
            if model.interviews.isEmpty {
                Text("No interviews yet.").organic(.small).padding(.horizontal, Organic.Space.p8)
            }
            List(model.interviews) { record in
                let selected = record.id == model.selectedID
                Button { model.select(record) } label: {
                    VStack(alignment: .leading, spacing: 3) {
                        Text("\(record.company) · \(record.role)").organic(.strong)
                        Text("\(record.stage) · \(record.startsAt, style: .date) · \(record.status)").organic(.caption)
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.vertical, Organic.Space.p12)
                    .padding(.horizontal, Organic.Space.p14)
                    .background(
                        selected ? Organic.Color.accentOn : Color.clear,
                        in: RoundedRectangle(cornerRadius: Organic.Radius.r20, style: .continuous)
                    )
                    .contentShape(RoundedRectangle(cornerRadius: Organic.Radius.r20, style: .continuous))
                }
                .buttonStyle(.plain)
                .accessibilityAddTraits(selected ? .isSelected : [])
                .listRowInsets(EdgeInsets(top: 2, leading: 0, bottom: 2, trailing: 0))
                .listRowSeparator(.hidden)
                .listRowBackground(Color.clear)
            }
            .listStyle(.plain)
            .scrollContentBackground(.hidden)
            .accessibilityIdentifier("interviewList")
        }
    }

    // MARK: - Detail header and editor

    private var header: some View {
        OrganicPageHeader(
            kicker: model.selected.map { record in
                "\(record.status.capitalized) · \(record.privacyPermissionCode.replacingOccurrences(of: "_", with: " "))"
            },
            title: model.selected.map { "\($0.company) · \($0.role)" } ?? "New interview",
            subtitle: model.selected.map { record in
                "\(record.stage) · \(record.startsAt.formatted(date: .abbreviated, time: .shortened)) · \(record.expectedDurationMinutes) min expected"
            }
        ) {
            if let selected = model.selected { recordButton(selected) }
        }
    }

    private func recordButton(_ interview: InterviewRecord) -> some View {
        let prohibited = interview.privacyPermissionCode == "recording_prohibited"
        return VStack(alignment: .trailing, spacing: 6) {
            Button {
                Task { await coordinator.start(interviewID: interview.id) }
            } label: {
                HStack(spacing: Organic.Space.p8) {
                    Circle().fill(Organic.Color.neutral900).frame(width: 10, height: 10)
                    Text("Record this interview")
                }
            }
            .buttonStyle(.organicPrimary)
            .disabled(coordinator.phase.isActive || prohibited)
            .accessibilityIdentifier("interviewRecord")
            if prohibited {
                Text("Recording is prohibited for this interview.")
                    .organic(.caption, color: Organic.Color.accent300)
            }
        }
    }

    private var editor: some View {
        VStack(alignment: .leading, spacing: Organic.Space.p24) {
            Grid(alignment: .topLeading, horizontalSpacing: Organic.Space.p12, verticalSpacing: Organic.Space.p14) {
                GridRow {
                    OrganicFieldLabel(title: "Company") {
                        TextField("Company", text: $model.draft.company)
                            .organicField()
                            .accessibilityIdentifier("interviewCompany")
                    }
                    OrganicFieldLabel(title: "Role") {
                        TextField("Role", text: $model.draft.role)
                            .organicField()
                            .accessibilityIdentifier("interviewRole")
                    }
                    OrganicFieldLabel(title: "Stage") {
                        TextField("Stage (screen, technical, panel…)", text: $model.draft.stage)
                            .organicField()
                            .accessibilityIdentifier("interviewStage")
                    }
                }
                GridRow {
                    OrganicFieldLabel(title: "Starts") {
                        DatePicker("Starts", selection: $model.draft.startsAt).labelsHidden()
                    }
                    OrganicFieldLabel(title: "Expected") {
                        Stepper("\(model.draft.expectedDurationMinutes) min", value: $model.draft.expectedDurationMinutes, in: 1...480, step: 5)
                    }
                    OrganicFieldLabel(title: "Status") {
                        Picker("Status", selection: $model.draft.status) {
                            ForEach(InterviewDraft.statuses, id: \.self) { Text($0.capitalized).tag($0) }
                        }
                        .labelsHidden()
                    }
                }
                GridRow(alignment: .bottom) {
                    OrganicFieldLabel(title: "Recording permission") {
                        Picker("Recording permission", selection: $model.draft.privacyPermissionCode) {
                            ForEach(InterviewDraft.privacyCodes, id: \.self) {
                                Text($0.replacingOccurrences(of: "_", with: " ")).tag($0)
                            }
                        }
                        .labelsHidden()
                    }
                    .gridCellColumns(2)
                    HStack(spacing: Organic.Space.p12) {
                        Button(model.isCreating ? "Create" : "Save") { Task { await model.save() } }
                            .buttonStyle(.organicSecondary)
                            .disabled(!model.canSave)
                            .accessibilityIdentifier("interviewSave")
                        if model.isBusy { ProgressView().controlSize(.small) }
                    }
                }
            }
            if let selected = model.selected { recordings(selected) }
            if let message = model.errorMessage {
                OrganicNotice(systemImage: "exclamationmark.triangle", tint: Organic.Color.danger, message: message)
                    .accessibilityElement(children: .combine)
                    .accessibilityIdentifier("interviewError")
            }
        }
    }

    private func recordings(_ interview: InterviewRecord) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .firstTextBaseline) {
                Text("Recordings").organic(.title)
                Spacer(minLength: 0)
                if let last = coordinator.lastRecordingID,
                   !interview.recordings.contains(where: { $0.recordingID == last }) {
                    Button("Attach the last recording") { Task { await model.attach(recordingID: last) } }
                        .accessibilityIdentifier("interviewAttachLast")
                }
            }
            if interview.recordings.isEmpty {
                Text("No recordings attached.").organic(.small)
            }
            ForEach(interview.recordings) { recording in
                VStack(alignment: .leading, spacing: Organic.Space.p8) {
                    HStack(spacing: Organic.Space.p8) {
                        if let startedAt = recording.startedAt {
                            Text(startedAt, style: .time).font(Organic.Font.tabular(.semibold, size: 13)).foregroundStyle(Organic.Color.text)
                        }
                        Text(recording.state.replacingOccurrences(of: "_", with: " ")).organic(.caption)
                        Spacer()
                        if recording.transcriptLineageAccepted {
                            Button("Open transcript") { Task { await model.openTranscript(recordingID: recording.recordingID) } }
                                .accessibilityIdentifier("interviewOpenTranscript")
                        } else {
                            Text("Transcript pending").organic(.caption)
                        }
                    }
                    if let analysis = model.analysis(for: recording) {
                        if analysis.turns.isEmpty {
                            Text(analysis.status == "published" ? "No speech in this recording." : "Transcript \(analysis.status.replacingOccurrences(of: "_", with: " ")).")
                                .organic(.caption)
                        }
                        ForEach(analysis.turns) { turn in
                            HStack(alignment: .firstTextBaseline, spacing: Organic.Space.p8) {
                                Text(timestamp(turn.startMS))
                                    .font(Organic.Font.tabular(.regular, size: 12))
                                    .foregroundStyle(Organic.Color.faint)
                                    .frame(width: 44, alignment: .leading)
                                Text(turn.isLearner ? "You" : "Interviewer")
                                    .font(Organic.Font.figtree(.semibold, size: 12))
                                    .foregroundStyle(turn.isLearner ? Organic.Color.accent300 : Organic.Color.accent2_300)
                                    .frame(width: 64, alignment: .leading)
                                Text(turn.text).organic(.small, color: Organic.Color.body).textSelection(.enabled)
                            }
                        }
                    }
                }
                .padding(Organic.Space.p14)
                .background(Organic.Color.fill04, in: RoundedRectangle(cornerRadius: Organic.Radius.r20, style: .continuous))
            }
        }
    }

    // MARK: - Timeline

    /// The sequence of interviews on Frank's four comparison dimensions, and the gaps that
    /// keep coming back. Hiring progression sits apart: advancing is not proof of better
    /// communication.
    private var timelineSection: some View {
        VStack(alignment: .leading, spacing: Organic.Space.p14) {
            HStack(alignment: .firstTextBaseline) {
                Text("Interview timeline").organic(.title)
                Spacer(minLength: Organic.Space.p12)
                Text("Debriefed · hiring progression sits apart").organic(.caption)
            }
            let debriefed = model.timeline.items.filter(\.hasDebrief)
            if debriefed.isEmpty {
                Text("Debrief an interview to see it here.").organic(.small)
                    .accessibilityIdentifier("interviewTimelineEmpty")
            } else {
                VStack(alignment: .leading, spacing: 0) {
                    timelineRow {
                        Text("Interview").organic(.kicker)
                    } scores: { trend in
                        Text(trend.name).organic(.kicker).lineLimit(2)
                    } hiring: {
                        Text("Hiring").organic(.kicker)
                    }
                    .timelineHairline()
                    ForEach(debriefed) { item in
                        timelineRow {
                            VStack(alignment: .leading, spacing: 2) {
                                Text("\(item.company) · \(item.stage)")
                                    .font(Organic.Font.figtree(.semibold, size: 13))
                                    .foregroundStyle(Organic.Color.text)
                                    .lineLimit(1)
                                Text(item.startsAt, style: .date)
                                    .font(Organic.Font.figtree(.regular, size: 11))
                                    .foregroundStyle(Organic.Color.muted)
                            }
                        } scores: { trend in
                            Text(item.score(trend.slug).map { "\($0)" } ?? "–")
                                .font(Organic.Font.tabular(.regular, size: 13))
                                .foregroundStyle(Organic.Color.body)
                        } hiring: {
                            Text(item.hiringProgression ?? "").organic(.caption).lineLimit(2)
                        }
                        .timelineHairline()
                        .accessibilityIdentifier("interviewTimelineRow-\(item.interviewID)")
                    }
                    timelineRow {
                        Text("Change since first")
                            .font(Organic.Font.figtree(.regular, size: 12))
                            .foregroundStyle(Organic.Color.accent2_300)
                    } scores: { trend in
                        Text(trend.deltaFromFirst.map { delta in (delta >= 0 ? "+" : "") + "\(delta)" } ?? "–")
                            .font(Organic.Font.tabular(.regular, size: 13))
                            .foregroundStyle((trend.deltaFromFirst ?? 0) > 0 ? Organic.Color.accent2_300 : Organic.Color.muted)
                    } hiring: {
                        EmptyView()
                    }
                }
            }
            ForEach(model.timeline.recurringGaps) { gap in
                VStack(alignment: .leading, spacing: 4) {
                    Text("Recurring gap · \(gap.skillSlug.replacingOccurrences(of: "_", with: " ")) · \(gap.interviewCount) interviews")
                        .font(Organic.Font.figtree(.semibold, size: 13))
                        .foregroundStyle(Organic.Color.text)
                    ForEach(gap.statements, id: \.self) { statement in
                        Text(statement).organic(.small, color: Organic.Color.neutral300)
                    }
                }
                .padding(.top, 6)
                .accessibilityIdentifier("interviewRecurringGap-\(gap.skillSlug)")
            }
        }
        .padding(.vertical, 22)
        .padding(.horizontal, Organic.Space.p24)
        .frame(maxWidth: .infinity, alignment: .leading)
        .organicCard(radius: Organic.Radius.r28, padding: 0)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("interviewTimeline")
    }

    /// One row of the timeline table: interview column, one column per dimension, hiring.
    private func timelineRow<First: View, Score: View, Hiring: View>(
        @ViewBuilder first: () -> First,
        @ViewBuilder scores: @escaping (DimensionTrend) -> Score,
        @ViewBuilder hiring: () -> Hiring
    ) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: Organic.Space.p12) {
            first().frame(width: 170, alignment: .leading)
            ForEach(model.timelineColumns) { trend in
                scores(trend).frame(width: 90, alignment: .leading)
            }
            hiring().frame(minWidth: 100, alignment: .leading)
        }
        .padding(.vertical, 10)
    }

    // MARK: - Practice

    /// Free practice: the interviewer asks the answer bank aloud, one question at a time.
    private var practiceSection: some View {
        GroupBox("Practice your answers aloud") {
            VStack(alignment: .leading, spacing: Organic.Space.p12) {
                Toggle("Follow-up questions", isOn: $practice.followUpsEnabled)
                    .toggleStyle(.switch)
                    .font(Organic.Font.figtree(.regular, size: 13))
                    .foregroundStyle(Organic.Color.body)
                    .accessibilityIdentifier("practiceFollowUpsToggle")
                Text("On: after an answer the interviewer may ask up to two follow-ups, each after a wait of about ten seconds, on weak spots and sometimes on good answers too. Off: straight to the next question.")
                    .font(Organic.Font.figtree(.regular, size: 11))
                    .foregroundStyle(Organic.Color.muted)
                if let question = practice.current {
                    Text(practice.progress).organic(.caption)
                    Text(practice.spokenPrompt ?? question.prompt).organic(.h3).textSelection(.enabled)
                        .accessibilityIdentifier("practiceQuestion")
                    if practice.currentFollowUp != nil {
                        Text("Follow-up to: \(question.prompt)")
                            .font(Organic.Font.figtree(.regular, size: 11))
                            .foregroundStyle(Organic.Color.muted)
                            .accessibilityIdentifier("practiceFollowUpContext")
                    }
                    HStack(spacing: Organic.Space.p8) {
                        if practice.isAnswering {
                            Button("Stop, that is my answer") {
                                Task {
                                    await practice.endAnswer()
                                    guard let answer = practice.answers.last else { return }
                                    // The answer goes to the server now; the interviewer thinks meanwhile.
                                    Task { await model.submitPracticeAnswer(answer) }
                                    await practice.considerFollowUp()
                                }
                            }
                                .buttonStyle(.organicPrimary)
                                .accessibilityIdentifier("practiceEndAnswer")
                            Text("Recording. The interviewer will not interrupt.").organic(.caption)
                        } else if practice.canMoveOn {
                            Button("Show my reference answer") { practice.revealReference() }
                                .disabled(!practice.canRevealReference)
                            Button("Next question") { practice.next() }
                                .buttonStyle(.organicPrimary)
                                .accessibilityIdentifier("practiceNext")
                            if practice.isPreparingFollowUp {
                                Text("The interviewer is thinking about a follow-up. You can move on.")
                                    .font(Organic.Font.figtree(.regular, size: 11))
                                    .foregroundStyle(Organic.Color.muted)
                                    .accessibilityIdentifier("practiceFollowUpPending")
                            }
                        } else {
                            Button("Record my answer") { Task { await practice.beginAnswer() } }
                                .buttonStyle(.organicPrimary)
                                .disabled(!practice.canBeginAnswer || coordinator.phase.isActive)
                                .accessibilityIdentifier("practiceBeginAnswer")
                            Button(practice.currentFollowUp == nil ? "Repeat the question" : "Repeat the follow-up") { practice.repeatQuestion() }
                        }
                        Spacer()
                        Button("End practice") { practice.stop() }.disabled(practice.isAnswering)
                    }
                    if let reference = practice.revealedReference {
                        Text(reference).organic(.body).textSelection(.enabled)
                            .padding(Organic.Space.p14)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .background(Organic.Color.fill04, in: RoundedRectangle(cornerRadius: Organic.Radius.r20, style: .continuous))
                            .accessibilityIdentifier("practiceReference")
                    }
                } else {
                    Text("The interviewer asks your answer bank questions aloud, one at a time, in random order. You answer without interruptions while it records, and only then compare with your own reference answer. Each answer is a recording: it is transcribed like any other and you can open it from the Recording screen.")
                        .organic(.caption)
                    HStack(spacing: Organic.Space.p12) {
                        Button(practice.isFinished ? "Practice again" : "Start practice") {
                            practice.start(entries: model.references)
                        }
                        .buttonStyle(.organicPrimary)
                        .disabled(model.references(of: .answerBank).isEmpty || coordinator.phase.isActive)
                        .accessibilityIdentifier("practiceStart")
                        if practice.isFinished {
                            Text("Round finished: \(practice.answers.count) answer\(practice.answers.count == 1 ? "" : "s") recorded.")
                                .organic(.caption)
                        } else if model.references(of: .answerBank).isEmpty {
                            Text("Import your answer bank below to start.").organic(.caption)
                        }
                    }
                }
                if let message = practice.message {
                    OrganicNotice(systemImage: "exclamationmark.triangle", tint: Organic.Color.warning, message: message)
                        .accessibilityElement(children: .combine)
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
                Text("Your practice answers").organic(.strong)
                Spacer()
                Button("Refresh reviews") { Task { await model.refreshPracticeReviews() } }
                    .disabled(model.isBusy)
                    .accessibilityIdentifier("practiceRefresh")
            }
            if !model.unsentPracticeAnswers.isEmpty {
                Text("\(model.unsentPracticeAnswers.count) answer\(model.unsentPracticeAnswers.count == 1 ? "" : "s") still uploading. Refresh in a moment.")
                    .organic(.caption)
            }
            ForEach(model.practiceReviews) { review in
                VStack(alignment: .leading, spacing: 4) {
                    HStack(alignment: .firstTextBaseline) {
                        Text(review.question).organic(.strong)
                        Spacer()
                        Text(review.statusLabel).organic(.caption)
                    }
                    if let followUp = review.followUpQuestion {
                        Text("Follow-up: \(followUp)")
                            .font(Organic.Font.figtree(.regular, size: 11))
                            .foregroundStyle(Organic.Color.body)
                    }
                    ForEach(review.dimensions) { dimension in
                        HStack(alignment: .firstTextBaseline) {
                            Text("\(dimension.name): \(NSDecimalNumber(decimal: dimension.score).stringValue) / 4")
                                .font(Organic.Font.tabular(.semibold, size: 12))
                                .foregroundStyle(Organic.Color.body)
                            Text("“\(dimension.evidence)” \(dimension.note)").organic(.caption)
                        }
                    }
                    ForEach(review.fixes) { fix in
                        Text("Say “\(fix.sayInstead)” instead of “\(fix.heard)”. \(fix.why)")
                            .organic(.caption, color: Organic.Color.body)
                    }
                    if !review.referenceCoverage.isEmpty {
                        Text(review.referenceCoverage).organic(.caption)
                    }
                    Button("Open transcript") { Task { await model.openTranscript(recordingID: review.recordingID) } }
                        .buttonStyle(.organicLink)
                    if let analysis = model.analyses[review.recordingID] {
                        ForEach(Array(analysis.turns.enumerated()), id: \.offset) { _, turn in
                            Text("\(turn.speaker == "learner" ? "You" : "Interviewer"): \(turn.text)")
                                .organic(.caption)
                        }
                    }
                }
                .padding(.vertical, 2)
            }
        }
    }

    // MARK: - Reference

    /// The answer bank and the story catalog: what the Coach and the debrief may cite.
    private var referenceSection: some View {
        GroupBox("Interview reference") {
            VStack(alignment: .leading, spacing: Organic.Space.p12) {
                Text("Import your answer bank and your story catalog as Markdown, one heading per entry. The Coach and the interview debrief cite them; nothing is treated as demonstrated until a recording shows it. Importing the same file again adds nothing.")
                    .organic(.caption)
                HStack(spacing: Organic.Space.p8) {
                    ForEach(ReferenceKind.allCases) { kind in
                        Button("Import \(kind.title.lowercased())…") { importingReferenceKind = kind }
                            .disabled(model.isBusy)
                            .accessibilityIdentifier("referenceImport-\(kind.rawValue)")
                    }
                }
                if let outcome = model.referenceOutcome {
                    Text("\(outcome.kind.title): \(outcome.created) new, \(outcome.existing) already known.")
                        .organic(.caption, color: Organic.Color.success)
                        .accessibilityIdentifier("referenceImportOutcome")
                }
                ForEach(ReferenceKind.allCases) { kind in
                    let entries = model.references(of: kind)
                    if !entries.isEmpty {
                        Text("\(kind.title) · \(entries.count)").organic(.strong)
                        ForEach(entries) { entry in
                            HStack(alignment: .firstTextBaseline) {
                                Text(entry.heading).organic(.small, color: Organic.Color.body).lineLimit(2)
                                Spacer()
                                if !entry.readinessLabel.isEmpty {
                                    Text(entry.readinessLabel).organic(.caption)
                                }
                            }
                        }
                    }
                }
                if model.references.isEmpty {
                    Text("Nothing imported yet.").organic(.small)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private func timestamp(_ milliseconds: Int) -> String {
        let seconds = milliseconds / 1000
        return String(format: "%d:%02d", seconds / 60, seconds % 60)
    }
}

private extension View {
    /// The table's row rule: a 1 pt `divider` hairline under the row.
    func timelineHairline() -> some View {
        overlay(alignment: .bottom) {
            Rectangle().fill(Organic.Color.divider).frame(height: 1)
        }
    }
}
