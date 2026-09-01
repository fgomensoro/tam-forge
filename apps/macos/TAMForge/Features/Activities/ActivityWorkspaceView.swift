import AppKit
import SwiftUI
import UniformTypeIdentifiers

struct ActivityWorkspaceView: View {
    @ObservedObject private var model: ActivityWorkspaceModel
    @ObservedObject private var uploader: ActivityArtifactUploader
    @State private var isImporterPresented = false
    @State private var review = ActivitySelfReviewInput(
        mainAnswer: "", didWell: "", structureWeakness: "", vaguePoints: "", hesitationPoints: "", changeNext: "", selfScore: 0
    )
    @State private var incompleteClassification: ActivityIncompleteClassification = .required
    @State private var strongerEvidenceID = ""
    @State private var artifactClass: ActivityArtifactClass = .writtenOutput
    private let focusSelfReview: Bool

    init(model: ActivityWorkspaceModel, uploader: ActivityArtifactUploader, focusSelfReview: Bool = false) {
        self.model = model
        self.uploader = uploader
        self.focusSelfReview = focusSelfReview
    }

    var body: some View {
        Group {
            if let activity = model.activity {
                content(for: activity)
            } else if model.recovery != .none {
                ContentUnavailableView {
                    Label("Activity could not be opened", systemImage: "exclamationmark.arrow.trianglehead.2.clockwise.rotate.90")
                } description: {
                    Text("Your draft remains in memory. Retry when the connection is available.")
                } actions: {
                    Button("Retry") { Task { await model.open() } }
                        .disabled(!model.canRetry)
                }
            } else {
                ProgressView("Opening activity…")
                    .accessibilityLabel("Opening activity")
            }
        }
        .task {
            model.connect(uploader: uploader)
            model.appear()
            await model.open()
        }
        .onDisappear { model.disappear() }
        .onReceive(NSWorkspace.shared.notificationCenter.publisher(for: NSWorkspace.willSleepNotification)) { _ in
            model.handleSleep()
        }
        .onReceive(NSWorkspace.shared.notificationCenter.publisher(for: NSWorkspace.didWakeNotification)) { _ in
            Task { await model.handleWake() }
        }
        .alert("Activity needs attention", isPresented: hasError) {
            Button("OK", role: .cancel) {}
        } message: {
            Text(model.errorMessage ?? "")
        }
    }

    private func content(for activity: ActivityDetail) -> some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 20) {
                    header(activity)
                    status(activity)
                    if model.canRetry {
                        Button("Retry server sync") { Task { await model.open() } }
                    }
                    if activity.hardStopRecommended {
                        Label("Daily hard stop reached. Save safely and stop; no extra work will be added.", systemImage: "stop.circle")
                            .foregroundStyle(.orange)
                    }
                    if activity.state.isEditable {
                        timerControls(activity)
                        sourcePanel(activity)
                        outputEditor(activity)
                            .disabled(!model.canEditDraft)
                        artifactPanel(activity)
                        commitPanel(activity)
                        incompletePanel(activity)
                    } else {
                        committedOutput(activity)
                        if let draft = model.recoverableDraft { recoveredDraftPanel(draft) }
                    }
                    if activity.state == .outputCommitted { selfReviewPanel(activity).id("activitySelfReview") }
                    if activity.selfReview != nil { reviewComplete(activity) }
                    Label("AI feedback remains unavailable until a server-backed self-review. This app cannot create an AI Attempt A.", systemImage: "lock")
                        .foregroundStyle(.secondary)
                        .accessibilityLabel("AI feedback locked until self-review")
                    contractPanel(activity)
                }
                .padding()
            }
            .accessibilityIdentifier("activityWorkspaceScroll")
            .task(id: activity.state) {
                if focusSelfReview && activity.state == .outputCommitted {
                    proxy.scrollTo("activitySelfReview", anchor: .top)
                }
            }
            .fileImporter(
                isPresented: $isImporterPresented,
                allowedContentTypes: [.item],
                allowsMultipleSelection: false
            ) { result in
                guard let sourceURL = try? result.get().first else { return }
                Task {
                    await model.upload(sourceURL: sourceURL, artifactClass: artifactClass)
                }
            }
        }
    }

    private func header(_ activity: ActivityDetail) -> some View {
        HStack(alignment: .top) {
            VStack(alignment: .leading, spacing: 6) {
                Text(activity.taskContract.block.rawValue.replacingOccurrences(of: "_", with: " "))
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Text(activity.taskContract.objective)
                    .font(.title2.weight(.semibold))
                    .accessibilityAddTraits(.isHeader)
            }
            Spacer()
            TimelineView(.periodic(from: .now, by: 1)) { _ in
                let seconds = model.focusedSeconds()
                VStack(alignment: .trailing) {
                    Text(timerText(seconds))
                        .font(.title3.monospacedDigit())
                    Text("\(activity.taskContract.timeboxMinutes) min")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                .accessibilityElement(children: .ignore)
                .accessibilityLabel("Focused time")
                .accessibilityValue(timerText(seconds))
            }
        }
    }

    private func status(_ activity: ActivityDetail) -> some View {
        HStack(spacing: 12) {
            Text(activity.state.rawValue.replacingOccurrences(of: "_", with: " "))
            Text("AI role: \(activity.taskContract.allowedAIRole.rawValue)")
            Text(activity.taskContract.required ? "Required" : "Adaptive")
        }
        .font(.caption)
        .foregroundStyle(.secondary)
    }

    private func timerControls(_ activity: ActivityDetail) -> some View {
        GroupBox("Focused timer") {
            HStack {
                switch activity.state {
                case .ready:
                    Button("Start activity") { Task { await model.start() } }
                case .active:
                    Text("Timer running")
                    Button("Pause") { Task { await model.pause() } }
                    Button("Sync now") { Task { await model.heartbeat() } }
                case .paused:
                    Button("Resume") { Task { await model.resume() } }
                default:
                    EmptyView()
                }
            }
        }
        .disabled(!model.canMutate)
        .accessibilityLabel("Focused timer controls")
    }

    private func sourcePanel(_ activity: ActivityDetail) -> some View {
        GroupBox("Assigned source") {
            VStack(alignment: .leading, spacing: 10) {
                Picker("Artifact type", selection: $artifactClass) {
                    ForEach(ActivityArtifactClass.allCases, id: \.self) { artifactClass in
                        Text(artifactClass.rawValue.replacingOccurrences(of: "_", with: " "))
                            .tag(artifactClass)
                    }
                }
                HStack {
                    Text(activity.sourceHidden ? "Source hidden" : "Source available")
                    Spacer()
                    Button(activity.sourceHidden ? "Reveal source" : "Hide source") {
                        Task { await model.setSourceHidden(!activity.sourceHidden) }
                    }
                    .disabled(!model.canMutate)
                }
                if activity.sourceHidden {
                    Text("Closed-source mode is active. Recall from memory before reopening material.")
                        .foregroundStyle(.secondary)
                } else {
                    ForEach(Array(activity.taskContract.sourceReferences.enumerated()), id: \.offset) { _, source in
                        Text(source.anchor.map { "\(source.path) · \($0)" } ?? source.path)
                            .textSelection(.enabled)
                    }
                }
                if activity.taskContract.block == .technicalLearning && !activity.sourceHidden {
                    Text("Hide assigned source before committing recall.")
                        .foregroundStyle(.orange)
                }
            }
        }
    }

    private func outputEditor(_ activity: ActivityDetail) -> some View {
        GroupBox("Working output") {
            VStack(alignment: .leading, spacing: 12) {
                let allowed = ActivityDraft.allowedKinds(for: activity.taskContract.block)
                if allowed.count > 1 {
                    Picker("Output type", selection: draftKindBinding(activity)) {
                        ForEach(allowed, id: \.self) { Text($0.rawValue).tag($0) }
                    }
                }
                ForEach(ActivityEditorField.fields(for: model.draft.kind), id: \.key) { field in
                    BoundedTextEditor(
                        title: field.title,
                        value: draftValueBinding(field.key),
                        minimumHeight: field.minimumHeight,
                        limit: field.limit
                    )
                }
                if model.draft.kind == .sql {
                    Picker("Assistance used", selection: draftValueBinding("assistance_used")) {
                        Text("None").tag("none")
                        Text("Coach preparation").tag("coach_preparation")
                        Text("Hint ladder").tag("hint_ladder")
                        Text("Time expired").tag("time_expired")
                        Text("Reference only").tag("reference_only")
                    }
                }
            }
        }
    }

    private func artifactPanel(_ activity: ActivityDetail) -> some View {
        GroupBox("Supporting artifact") {
            VStack(alignment: .leading, spacing: 10) {
                HStack {
                    Button("Choose file…") { isImporterPresented = true }
                        .disabled(!model.canUpload)
                    Text(uploadMessage)
                        .foregroundStyle(.secondary)
                    if uploader.isRunning {
                        Button("Cancel") { model.cancelUpload() }
                    }
                }
                if uploader.state == .confirmationIndeterminate {
                    Button("Reconcile upload") {
                        Task { await model.reconcileUpload() }
                    }
                    .disabled(uploader.isRunning || model.isCommandRunning || model.isLoading)
                    Button("Abandon upload") { model.cancelUpload() }
                    Text("Upload may have reached storage. Reconcile before repeating confirmation.")
                        .foregroundStyle(.orange)
                }
                if !model.artifactReferences.isEmpty {
                    Text("\(model.artifactReferences.count) attached artifact\(model.artifactReferences.count == 1 ? "" : "s")")
                }
                Text("Any file type is supported. File bytes stream from a temporary copy and are deleted after completion or cancellation.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .accessibilityLabel("Supporting artifact upload")
    }

    private func commitPanel(_ activity: ActivityDetail) -> some View {
        GroupBox("Commit independent Attempt A") {
            VStack(alignment: .leading, spacing: 10) {
                Toggle("I understand this output becomes immutable evidence.", isOn: $model.hasAcknowledgedImmutability)
                    .accessibilityIdentifier("activityImmutabilityAcknowledgment")
                Button("Commit Attempt A") { Task { await model.commit() } }
                    .disabled(!model.canCommit)
                Text("Draft remains only in memory until commitment; it is not evidence.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
    }

    private func incompletePanel(_ activity: ActivityDetail) -> some View {
        GroupBox("Classify unfinished work") {
            HStack {
                Picker("Classification", selection: $incompleteClassification) {
                    ForEach(ActivityIncompleteClassification.allCases, id: \.self) { Text($0.rawValue).tag($0) }
                }
                if incompleteClassification == .superseded {
                    TextField("Stronger evidence ID", text: $strongerEvidenceID)
                        .frame(maxWidth: 160)
                }
                Button("Classify") {
                    let evidenceID = Int(strongerEvidenceID)
                    Task { await model.classifyIncomplete(as: incompleteClassification, strongerEvidenceID: evidenceID) }
                }
                .disabled(!model.canMutate || (incompleteClassification == .superseded && Int(strongerEvidenceID) == nil))
            }
        }
    }

    private func committedOutput(_ activity: ActivityDetail) -> some View {
        GroupBox("Immutable Attempt A") {
            VStack(alignment: .leading, spacing: 8) {
                Text("Attempt A is committed and read-only.")
                    .font(.headline)
                if let payload = activity.committedOutput?.contractPayload["output"] {
                    Text(payload.rendered(prefixLimit: 64 * 1024))
                        .font(.body.monospaced())
                        .textSelection(.enabled)
                }
                if let digest = activity.committedOutput?.commitmentSHA256 {
                    Text(digest).font(.caption.monospaced()).textSelection(.enabled)
                }
            }
        }
    }

    private func selfReviewPanel(_ activity: ActivityDetail) -> some View {
        GroupBox("Mandatory self-review") {
            VStack(alignment: .leading, spacing: 10) {
                Text("Complete this before feedback can exist. Your self-score stays separate from future analysis.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                ForEach(ActivitySelfReviewField.allCases, id: \.self) { field in
                    BoundedTextEditor(title: field.title, value: reviewBinding(field), minimumHeight: 72, limit: 8_192)
                }
                Picker("My self-score", selection: $review.selfScore) {
                    ForEach(0...4, id: \.self) { Text("\($0)").tag($0) }
                }
                .pickerStyle(.menu)
                .accessibilityIdentifier("activitySelfScore")
                Button("Submit self-review") { Task { await model.submitSelfReview(review) } }
                    .disabled(!review.isComplete || !model.canMutate)
            }
        }
    }

    private func recoveredDraftPanel(_ draft: ActivityDraft) -> some View {
        GroupBox("Recovered local draft — not evidence") {
            VStack(alignment: .leading, spacing: 10) {
                Text("The activity was finalized elsewhere. Your different local draft remains read-only in memory. Expand and copy any text you need before signing out; server evidence is unchanged.")
                ForEach(draft.values.keys.sorted().filter { !draft.value(for: $0).isEmpty }, id: \.self) { key in
                    DisclosureGroup(key.replacingOccurrences(of: "_", with: " ")) {
                        Text(draft.value(for: key))
                            .textSelection(.enabled)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }
                ForEach(Array(draft.artifactReferences.enumerated()), id: \.offset) { _, reference in
                    Text("Retained artifact #\(reference.artifactID) · \(reference.linkRole.rawValue)")
                        .textSelection(.enabled)
                }
            }
        }
    }

    private func reviewComplete(_ activity: ActivityDetail) -> some View {
        GroupBox("Self-review complete") {
            Text("Your score: \(activity.selfReview?.selfScore ?? 0) / 4. AI analysis has not been requested.")
                .accessibilityIdentifier("activitySelfReviewSummary")
        }
    }

    private func contractPanel(_ activity: ActivityDetail) -> some View {
        GroupBox("What good looks like") {
            VStack(alignment: .leading, spacing: 12) {
                ContractItems(title: "Required output", values: activity.taskContract.requiredOutput)
                ContractItems(title: "Pass criteria", values: activity.taskContract.passCriteria)
                ContractItems(title: "Evidence required", values: activity.taskContract.evidenceRequirements)
                ContractItems(title: "Constraints", values: activity.taskContract.constraints)
                if !activity.taskContract.procedure.isEmpty {
                    Text("Assigned procedure").font(.headline)
                    ForEach(Array(activity.taskContract.procedure.enumerated()), id: \.offset) { _, step in
                        VStack(alignment: .leading, spacing: 2) {
                            Text(step.minutes.map { "\(step.phase) · \($0) min" } ?? step.phase).bold()
                            Text(step.requirement)
                        }
                    }
                }
            }
        }
    }

    private var hasError: Binding<Bool> {
        .init(get: { model.errorMessage != nil }, set: { if !$0 { model.dismissError() } })
    }

    private var uploadMessage: String {
        switch uploader.state {
        case .idle: "Optional"
        case .preparing: "Preparing secure temporary copy…"
        case .uploading: "Uploading…"
        case .confirming: "Confirming…"
        case .confirmationIndeterminate: "Needs reconciliation"
        case .complete: "Uploaded"
        case .cancelled: uploader.isRunning ? "Cancelling; cleaning temporary copy…" : "Cancelled; temporary copy deleted"
        case .failed: "Upload failed; temporary copy deleted"
        }
    }

    private func draftValueBinding(_ key: String) -> Binding<String> {
        .init(get: { model.draft.value(for: key) }, set: { model.updateDraft(model.draft.setting(key, to: $0)) })
    }

    private func draftKindBinding(_ activity: ActivityDetail) -> Binding<ActivityOutputKind> {
        .init(get: { model.draft.kind }, set: { model.updateDraft(model.draft.changingKind(to: $0, for: activity)) })
    }

    private func reviewBinding(_ field: ActivitySelfReviewField) -> Binding<String> {
        .init(get: { field.value(in: review) }, set: { field.set($0, in: &review) })
    }

    private func timerText(_ seconds: Int) -> String {
        "\(seconds / 60):\(String(format: "%02d", seconds % 60))"
    }
}

private struct ActivityEditorField {
    var key: String
    var title: String
    var minimumHeight: CGFloat = 72
    var limit: Int = 4 * 1024 * 1024

    static func fields(for kind: ActivityOutputKind) -> [Self] {
        let base = [Self(key: "prompt", title: "Prompt"), Self(key: "audience", title: "Audience")]
        switch kind {
        case .reading:
            return base + [
                .init(key: "key_idea_1", title: "Key idea 1"), .init(key: "key_idea_2", title: "Key idea 2"), .init(key: "key_idea_3", title: "Key idea 3"),
                .init(key: "boundary_or_failure", title: "Boundary or failure mode"), .init(key: "tam_customer_example", title: "TAM or customer example"), .init(key: "unresolved_question", title: "Unresolved question"),
            ]
        case .sql:
            return base + [
                .init(key: "query", title: "SQL query", minimumHeight: 160), .init(key: "result", title: "Result", minimumHeight: 120),
                .init(key: "validation", title: "Validation"), .init(key: "explanation", title: "Query explanation"), .init(key: "business_meaning", title: "Business meaning"),
            ]
        case .`case`:
            return base + [
                .init(key: "canonical_prompt", title: "Canonical prompt"), .init(key: "canonical_facts", title: "Canonical facts, one per line"), .init(key: "discovery_questions", title: "Discovery questions, one per line"),
                .init(key: "assumptions", title: "Assumptions, one per line"), .init(key: "working_notes", title: "Working notes", minimumHeight: 160), .init(key: "final_artifact", title: "Final artifact", minimumHeight: 220),
                .init(key: "decisions", title: "Decisions, one per line"), .init(key: "risks", title: "Risks, one per line"), .init(key: "unresolved_questions", title: "Unresolved questions, one per line"),
            ]
        case .writing:
            return base + [
                .init(key: "requested_action", title: "Requested action"), .init(key: "facts", title: "Facts, one per line"), .init(key: "unknowns", title: "Unknowns, one per line"),
                .init(key: "tone", title: "Tone"), .init(key: "word_or_character_limit", title: "Word or character limit"), .init(key: "draft_markdown", title: "Independent draft", minimumHeight: 240), .init(key: "self_edit_notes", title: "Self-edit notes"),
            ]
        case .pipeline:
            return base + [
                .init(key: "company", title: "Company"), .init(key: "role", title: "Role"), .init(key: "stage", title: "Stage"),
                .init(key: "completed_action", title: "Completed action"), .init(key: "artifact_summary", title: "Saved artifact"), .init(key: "next_action", title: "Next action"),
            ]
        }
    }
}

private struct BoundedTextEditor: View {
    var title: String
    @Binding var value: String
    var minimumHeight: CGFloat
    var limit: Int

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title).font(.subheadline.weight(.medium))
            TextEditor(text: Binding(get: { value }, set: { next in
                if next.utf8.count <= limit { value = next }
            }))
            .frame(minHeight: minimumHeight)
            .font(.body.monospaced())
            .accessibilityLabel(title)
        }
    }
}

private struct ContractItems: View {
    var title: String
    var values: [String]

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title).font(.headline)
            ForEach(values, id: \.self) { value in Text("• \(value)") }
        }
    }
}

private enum ActivitySelfReviewField: CaseIterable {
    case mainAnswer, didWell, structureWeakness, vaguePoints, hesitationPoints, changeNext

    var title: String {
        switch self {
        case .mainAnswer: "Main answer or decision"
        case .didWell: "What I did well"
        case .structureWeakness: "Where structure was weak"
        case .vaguePoints: "Where I became vague"
        case .hesitationPoints: "Where I hesitated"
        case .changeNext: "What I will change"
        }
    }

    func value(in review: ActivitySelfReviewInput) -> String {
        switch self {
        case .mainAnswer: review.mainAnswer
        case .didWell: review.didWell
        case .structureWeakness: review.structureWeakness
        case .vaguePoints: review.vaguePoints
        case .hesitationPoints: review.hesitationPoints
        case .changeNext: review.changeNext
        }
    }

    func set(_ value: String, in review: inout ActivitySelfReviewInput) {
        switch self {
        case .mainAnswer: review.mainAnswer = value
        case .didWell: review.didWell = value
        case .structureWeakness: review.structureWeakness = value
        case .vaguePoints: review.vaguePoints = value
        case .hesitationPoints: review.hesitationPoints = value
        case .changeNext: review.changeNext = value
        }
    }
}

private extension ActivityJSONValue {
    func rendered(prefixLimit: Int) -> String {
        let rendered: String
        switch self {
        case let .string(value): rendered = value
        case let .integer(value): rendered = String(value)
        case let .decimal(value): rendered = String(value)
        case let .boolean(value): rendered = String(value)
        case let .array(values): rendered = values.map { $0.rendered(prefixLimit: prefixLimit) }.joined(separator: "\n")
        case let .object(values): rendered = values.sorted { $0.key < $1.key }.map { "\($0.key): \($0.value.rendered(prefixLimit: prefixLimit))" }.joined(separator: "\n")
        case .null: rendered = ""
        }
        return rendered.count > prefixLimit ? String(rendered.prefix(prefixLimit)) + "\n[truncated]" : rendered
    }
}
