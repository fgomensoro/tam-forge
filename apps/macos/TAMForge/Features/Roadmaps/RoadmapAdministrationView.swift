import SwiftUI

struct RoadmapSemanticDiffField: Equatable, Identifiable {
    let name: String
    let label: String
    let before: String
    let after: String

    var id: String { name }
}

struct RoadmapSemanticDiffEntry: Equatable, Identifiable {
    let key: String
    let status: String
    let fields: [RoadmapSemanticDiffField]

    var id: String { key }
}

enum RoadmapSemanticDiffPresentation {
    static let maximumEntriesPerSection = 12
    static let maximumFieldsPerEntry = 8
    static let maximumValueCharacters = 280
    private static let fieldLabels = [
        "objective": "Assignment",
        "timebox_minutes": "Timebox",
        "required": "Required coverage",
        "required_output": "Required output",
        "pass_criteria": "Pass criteria",
        "evidence_requirements": "Evidence requirements",
        "allowed_ai_role": "Allowed AI role",
    ]

    static func changedEntries(in section: RoadmapJSONValue?) -> [RoadmapSemanticDiffEntry] {
        Array(entries(in: section, preview: true).prefix(maximumEntriesPerSection))
    }

    static func allChangedEntries(in section: RoadmapJSONValue?) -> [RoadmapSemanticDiffEntry] {
        entries(in: section, preview: false)
    }

    static func hasMoreEntries(in section: RoadmapJSONValue?) -> Bool {
        entries(in: section, preview: true).count > maximumEntriesPerSection
    }

    private static func entries(in section: RoadmapJSONValue?, preview: Bool) -> [RoadmapSemanticDiffEntry] {
        (section?.objectValue?["entries"]?.arrayValue ?? []).compactMap { value in
            guard let entry = value.objectValue,
                  let key = entry["key"]?.stringValue,
                  let status = entry["status"]?.stringValue,
                  status != "unchanged"
            else { return nil }
            let fieldValues: [RoadmapJSONValue]
            if status == "added" || status == "removed" {
                // These statuses carry whole payloads instead of field-level changes.
                let before = entry["before"]?.objectValue ?? [:]
                let after = entry["after"]?.objectValue ?? [:]
                fieldValues = Set(before.keys).union(after.keys).sorted().map { name in
                    .object([
                        "name": .string(name),
                        "before": before[name] ?? .null,
                        "after": after[name] ?? .null,
                    ])
                }
            } else {
                fieldValues = entry["fields"]?.arrayValue ?? []
            }
            let fields = fieldValues.compactMap { value -> RoadmapSemanticDiffField? in
                guard let field = value.objectValue,
                      let name = field["name"]?.stringValue
                else { return nil }
                return .init(
                    name: name,
                    label: fieldLabels[name] ?? name.replacingOccurrences(of: "_", with: " "),
                    before: display(field["before"], preview: preview),
                    after: display(field["after"], preview: preview)
                )
            }
            return .init(
                key: key,
                status: status,
                fields: preview ? Array(fields.prefix(maximumFieldsPerEntry)) : fields
            )
        }
    }

    private static func display(_ value: RoadmapJSONValue?, preview: Bool) -> String {
        let text: String
        switch value {
        case nil, .null: text = "None"
        case let .array(items): text = items.map { display($0, preview: preview) }.joined(separator: " · ")
        case let .bool(value): text = String(value)
        case let .integer(value): text = String(value)
        case let .number(value):
            if value.rounded() == value, let integer = Int(exactly: value) {
                text = String(integer)
            } else {
                text = String(value)
            }
        case let .object(value):
            let keys = value.keys.sorted()
            let displayedKeys = preview ? Array(keys.prefix(maximumFieldsPerEntry)) : keys
            let fields = displayedKeys.map { key in
                "\(key): \(display(value[key], preview: preview))"
            }
            text = "{ \(fields.joined(separator: ", ")) }"
        case let .string(value): text = value
        }
        return preview ? String(text.prefix(maximumValueCharacters)) : text
    }
}

struct RoadmapAdministrationView: View {
    @StateObject private var model: RoadmapAdministrationModel
    @State private var expandedDiffSections: Set<String> = []

    init(service: any RoadmapServicing) {
        _model = StateObject(wrappedValue: RoadmapAdministrationModel(service: service))
    }

    init(model: RoadmapAdministrationModel) {
        _model = StateObject(wrappedValue: model)
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Organic.Space.p24) {
                // OrganicPageHeader's shape, written out so the title Text keeps its own
                // identifier literal (the header primitive would take it as a parameter).
                VStack(alignment: .leading, spacing: 6) {
                    Text("Governed curriculum").organic(.kicker, color: Organic.Color.accent400)
                    Text("Roadmaps")
                        .organic(.h1)
                        .accessibilityAddTraits(.isHeader)
                        .accessibilityIdentifier("roadmapsTitle")
                    Text("Obsidian remains your authored source. TAM Forge imports a versioned snapshot only after you inspect and approve its changes.")
                        .organic(.body, color: Organic.Color.muted)
                        .fixedSize(horizontal: false, vertical: true)
                        .frame(maxWidth: 680, alignment: .leading)
                }

                sourcePackage
                if model.isBusy && model.roadmapImport == nil {
                    ProgressView("Uploading package…")
                        .controlSize(.small)
                        .accessibilityIdentifier("roadmapUploadStatus")
                }
                if let errorMessage = model.errorMessage {
                    noticeStrip(tint: Organic.Color.danger) {
                        HStack(alignment: .top, spacing: Organic.Space.p14) {
                            noticeIcon("exclamationmark.triangle", tint: Organic.Color.danger)
                            Text(errorMessage)
                                .organic(.small, color: Organic.Color.neutral300)
                                .fixedSize(horizontal: false, vertical: true)
                                .accessibilityIdentifier("roadmapError")
                        }
                    }
                }
                if let roadmapImport = model.roadmapImport {
                    validationReport(roadmapImport)
                    schemeEditor
                    if roadmapImport.isValidated {
                        semanticDiff(roadmapImport.semanticDiff)
                        approvalGate(roadmapImport)
                    }
                } else if model.reforecastTarget != nil {
                    schemeEditor
                }
                // Kept last, as before: UI tests scroll a fixed number of steps to reach the approval gate.
                if !model.versions.isEmpty { history }
            }
            .frame(maxWidth: 960, alignment: .leading)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .accessibilityIdentifier("roadmapWorkspaceScroll")
        .task { await model.loadHistory() }
    }

    private var step: Int {
        guard let roadmapImport = model.roadmapImport else { return model.reforecastTarget != nil ? 3 : 1 }
        if model.version != nil { return 5 }
        return roadmapImport.isValidated ? 4 : 2
    }

    // MARK: 1

    private var sourcePackage: some View {
        RoadmapStep(number: 1, title: "Source package", current: step) {
            Text("Choose one ZIP or folder. TAM Forge never reads your Obsidian vault automatically.")
                .organic(.small)
            HStack(spacing: Organic.Space.p12) {
                Image(systemName: model.selection == nil ? "shippingbox" : "shippingbox.fill")
                    .foregroundStyle(model.selection == nil ? Organic.Color.faint : Organic.Color.accent2_300)
                    .accessibilityHidden(true)
                Text(model.selection?.displayName ?? "No package selected")
                    .organic(model.selection == nil ? .body : .strong, color: model.selection == nil ? Organic.Color.muted : nil)
                    .accessibilityIdentifier("roadmapSelection")
            }
            .padding(.horizontal, Organic.Space.p16)
            .padding(.vertical, 10)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Organic.Color.bg, in: Capsule(style: .continuous))
            HStack(spacing: Organic.Space.p8) {
                Button("Choose ZIP or folder") { model.choosePackage() }
                    .disabled(model.isBusy)
                Button("Review package") { model.beginStage() }
                    .buttonStyle(.organicPrimary)
                    .disabled(model.selection == nil || model.isBusy)
                if model.isBusy && model.roadmapImport == nil {
                    Button("Cancel upload") { model.cancelUpload() }
                        .buttonStyle(.organicLink)
                        .accessibilityIdentifier("roadmapCancelUploadButton")
                } else if model.roadmapImport != nil {
                    Button("Cancel review") { model.cancelReview() }
                        .buttonStyle(.organicLink)
                        .disabled(model.isBusy)
                }
            }
        }
    }

    // MARK: 2

    private func validationReport(_ roadmapImport: RoadmapImport) -> some View {
        RoadmapStep(number: 2, title: "Validation", current: step) {
            if roadmapImport.isValidated {
                statusLine("Validation passed", systemImage: "checkmark.circle.fill", tint: Organic.Color.success)
                let report = roadmapImport.validationReport.objectValue ?? [:]
                HStack(spacing: Organic.Space.p8) {
                    metric("tasks", report["task_count"]?.integerValue)
                    metric("resources", report["resource_count"]?.integerValue)
                    metric("exit criteria", report["exit_criterion_count"]?.integerValue)
                }
                schemeSummary(report["scheme_summary"])
                if let hash = report["normalized_hash"]?.stringValue {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("Normalized content hash").organic(.kicker)
                        Text(hash).organic(.mono, color: Organic.Color.neutral300).textSelection(.enabled)
                    }
                }
                Text("Approval creates an immutable roadmap version; it never overwrites an earlier roadmap.")
                    .organic(.small)
            } else {
                statusLine("Validation needs attention", systemImage: "exclamationmark.triangle.fill", tint: Organic.Color.warning)
                validationIssues(roadmapImport.validationReport)
            }
        }
    }

    /// Days and budgets when the package carries a scheme; nothing for a legacy map.
    @ViewBuilder
    private func schemeSummary(_ value: RoadmapJSONValue?) -> some View {
        if let summary = value?.objectValue, let days = summary["study_days"]?.integerValue, days > 0 {
            let budgets = summary["budget_minutes"]?.objectValue ?? [:]
            let ordered = budgets.keys.compactMap(Int.init).sorted()
            let preview = ordered.prefix(7).map { day in
                "Day \(day): \(budgets[String(day)]?.integerValue ?? 0) min"
            }
            VStack(alignment: .leading, spacing: 4) {
                Text("\(days) study day\(days == 1 ? "" : "s") · \(summary["program"]?.stringValue ?? "scheme")")
                    .organic(.strong)
                    .accessibilityIdentifier("roadmapSchemeSummary")
                Text(preview.joined(separator: " · ") + (ordered.count > 7 ? " · …" : ""))
                    .organic(.caption)
            }
        }
    }

    @ViewBuilder
    private func validationIssues(_ report: RoadmapJSONValue) -> some View {
        let issues = report.objectValue?["issues"]?.arrayValue ?? []
        if issues.isEmpty {
            Text("The package could not be validated.").organic(.body)
        } else {
            VStack(alignment: .leading, spacing: 6) {
                ForEach(Array(issues.enumerated()), id: \.offset) { _, issue in
                    let values = issue.objectValue ?? [:]
                    VStack(alignment: .leading, spacing: 2) {
                        Text(values["message"]?.stringValue ?? "The package could not be validated.").organic(.body)
                        if let path = values["path"]?.stringValue {
                            Text(path).organic(.mono, color: Organic.Color.muted)
                        }
                    }
                    .padding(Organic.Space.p12)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(Organic.Color.fill04, in: RoundedRectangle(cornerRadius: Organic.Radius.r20, style: .continuous))
                }
            }
        }
    }

    // MARK: 3

    private var schemeEditor: some View {
        RoadmapStep(number: 3, title: "Scheme", current: step) {
            if let target = model.reforecastTarget {
                Text("Reforecast of \(target.versionKey): remaining work redistributed from today. Approving stages a new version; nothing changes until you activate it.")
                    .organic(.small)
            } else {
                Text("The scheme decides days, blocks and minutes. Generate one with the planner or paste your own, then attach it to review the result.")
                    .organic(.small)
            }
            TextField("Instruction for the planner (optional)", text: $model.plannerInstruction)
                .organicField(onSurface: true)
                .accessibilityIdentifier("roadmapPlannerInstruction")
            HStack(spacing: Organic.Space.p8) {
                if model.reforecastTarget == nil {
                    Button(model.isBusy ? "Working…" : "Generate with AI") {
                        Task { await model.generateScheme() }
                    }
                    .disabled(!model.canGenerateScheme)
                    .accessibilityIdentifier("roadmapGenerateSchemeButton")
                } else if let target = model.reforecastTarget {
                    Button(model.isBusy ? "Working…" : "Propose reforecast") {
                        Task { await model.proposeReforecast(target) }
                    }
                    .disabled(model.isBusy)
                    .accessibilityIdentifier("roadmapProposeReforecastButton")
                }
                Button(model.reforecastTarget == nil ? "Attach scheme" : "Stage reforecast") {
                    Task { await model.attachScheme() }
                }
                .buttonStyle(.organicPrimary)
                .disabled(!model.canAttachScheme)
                .accessibilityIdentifier("roadmapAttachSchemeButton")
            }
            TextEditor(text: $model.schemeDraft)
                .organicEditor(minHeight: 160, monospaced: true, onSurface: true)
                .frame(maxHeight: 320)
                .accessibilityIdentifier("roadmapSchemeDraft")
            ForEach(Array(model.schemeIssues.enumerated()), id: \.offset) { _, issue in
                Label(issue, systemImage: "exclamationmark.circle")
                    .organic(.caption, color: Organic.Color.danger)
            }
            if let summary = model.schemeSummary {
                schemeSummary(summary)
            }
        }
    }

    // MARK: 4

    private func semanticDiff(_ diff: RoadmapJSONValue) -> some View {
        let summary = diff.objectValue?["summary"]?.objectValue ?? [:]
        let added = summary["added"]?.integerValue ?? 0
        let removed = summary["removed"]?.integerValue ?? 0
        let changed = summary["changed"]?.integerValue ?? 0
        return RoadmapStep(number: 4, title: "Semantic comparison", current: step) {
            Text("What this roadmap changes").organic(.small)
            HStack(spacing: Organic.Space.p16) {
                Text("+\(added) added").organic(.small, color: Organic.Color.accent2_300)
                Text("\(changed) changed").organic(.small, color: Organic.Color.accent300)
                Text("\(removed) removed").organic(.small, color: Organic.Color.muted)
                Text("\(summary["unchanged"]?.integerValue ?? 0) unchanged").organic(.small, color: Organic.Color.faint)
            }
            semanticDiffSection("Assignments and time", section: diff.objectValue?["tasks"])
            semanticDiffSection("Pass criteria", section: diff.objectValue?["pass_contracts"])
            semanticDiffSection("Assigned resources", section: diff.objectValue?["resources"])
            semanticDiffSection("Month exit criteria", section: diff.objectValue?["exit_criteria"])
            if added + removed + changed == 0 {
                Text("No learning requirement changes were detected.").organic(.small)
            }
        }
    }

    @ViewBuilder
    private func semanticDiffSection(_ title: String, section: RoadmapJSONValue?) -> some View {
        let isExpanded = expandedDiffSections.contains(title)
        let entries = isExpanded
            ? RoadmapSemanticDiffPresentation.allChangedEntries(in: section)
            : RoadmapSemanticDiffPresentation.changedEntries(in: section)
        if !entries.isEmpty {
            VStack(alignment: .leading, spacing: Organic.Space.p8) {
                Text(title).organic(.kicker)
                // Deliberately eager. A collapsed section shows at most
                // `maximumEntriesPerSection` (12) entries, so laziness saves nothing, and
                // these rows are tall and wildly uneven (before/after text blocks). A
                // LazyVStack sizes the rows it has not realised by estimate, so the
                // ScrollView's content height, and with it the end of its scroll range,
                // moved every time rows realised. Four of these sections make up most of a
                // ~10,500pt page, and the estimate ran far enough short that the approval
                // gate below them could not be scrolled into the viewport at all.
                VStack(alignment: .leading, spacing: Organic.Space.p8) {
                    ForEach(entries) { entry in
                        VStack(alignment: .leading, spacing: Organic.Space.p8) {
                            HStack(spacing: Organic.Space.p8) {
                                Text(entry.key).organic(.mono, color: Organic.Color.text)
                                OrganicTag(
                                    text: entry.status,
                                    background: entry.status == "added" ? Organic.Color.sageOn : (entry.status == "changed" ? Organic.Color.accentOn : Organic.Color.fill08),
                                    foreground: entry.status == "added" ? Organic.Color.accent2_200 : (entry.status == "changed" ? Organic.Color.accent300 : Organic.Color.neutral300)
                                )
                            }
                            ForEach(entry.fields) { field in
                                if isExpanded {
                                    VStack(alignment: .leading, spacing: 4) {
                                        Text(field.label).organic(.strong)
                                        // Not the kicker role: it uppercases, the macOS accessibility
                                        // value is the rendered string, and the UI tests match these as written.
                                        Text("Before").organic(.caption)
                                        Text(field.before).organic(.small).fixedSize(horizontal: false, vertical: true).textSelection(.enabled)
                                        Text("After").organic(.caption)
                                        Text(field.after).organic(.small, color: Organic.Color.text).fixedSize(horizontal: false, vertical: true).textSelection(.enabled)
                                    }
                                } else {
                                    Grid(alignment: .topLeading, horizontalSpacing: Organic.Space.p16, verticalSpacing: 0) {
                                        GridRow {
                                            Text(field.label).organic(.small, color: Organic.Color.muted).frame(width: 140, alignment: .leading)
                                            Text(field.before).organic(.small, color: Organic.Color.faint).strikethrough(color: Organic.Color.faint).lineLimit(2)
                                                .frame(maxWidth: .infinity, alignment: .leading)
                                            Text(field.after).organic(.small, color: Organic.Color.text).lineLimit(2)
                                                .frame(maxWidth: .infinity, alignment: .leading)
                                        }
                                    }
                                }
                            }
                        }
                        .padding(Organic.Space.p14)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(Organic.Color.fill04, in: RoundedRectangle(cornerRadius: Organic.Radius.r20, style: .continuous))
                    }
                }
                Button(isExpanded ? "Show bounded preview" : "Inspect all changes, fields, and values") {
                    if isExpanded { expandedDiffSections.remove(title) } else { expandedDiffSections.insert(title) }
                }
                .buttonStyle(.organicLink)
                if !isExpanded, RoadmapSemanticDiffPresentation.hasMoreEntries(in: section) {
                    Text("Showing first \(RoadmapSemanticDiffPresentation.maximumEntriesPerSection) changes. Inspect complete details before approval.")
                        .organic(.caption)
                }
            }
        }
    }

    // MARK: 5

    private func approvalGate(_ roadmapImport: RoadmapImport) -> some View {
        RoadmapStep(number: 5, title: "Approve, mirror, then activate", current: step) {
            // The page-level error sits above the fold by the time the learner is down
            // here, so the outcome of this block's buttons is repeated next to them.
            if let notice = model.notice {
                noticeStrip(tint: Organic.Color.success) {
                    Label {
                        Text(notice).organic(.small, color: Organic.Color.neutral300).fixedSize(horizontal: false, vertical: true)
                    } icon: {
                        noticeIcon("checkmark.circle.fill", tint: Organic.Color.success)
                    }
                    .accessibilityIdentifier("roadmapNotice")
                }
            }
            if let errorMessage = model.errorMessage {
                noticeStrip(tint: Organic.Color.danger) {
                    Label {
                        Text(errorMessage).organic(.small, color: Organic.Color.neutral300).fixedSize(horizontal: false, vertical: true)
                    } icon: {
                        noticeIcon("exclamationmark.triangle.fill", tint: Organic.Color.danger)
                    }
                    .accessibilityIdentifier("roadmapApprovalError")
                }
            }
            if let version = model.version {
                versionGate(version)
            } else {
                Toggle(
                    "I reviewed the validation and semantic changes. Create an immutable roadmap version.",
                    isOn: $model.approvalConfirmed
                )
                .accessibilityIdentifier("roadmapApprovalConfirmation")
                HStack {
                    Text("Approval record · import #\(roadmapImport.id)").organic(.caption)
                    Spacer()
                    Button(model.isBusy ? "Approving…" : "Approve roadmap") {
                        Task { await model.approve() }
                    }
                    .buttonStyle(.organicPrimary)
                    .disabled(!model.approvalConfirmed || model.isBusy)
                }
            }
        }
    }

    @ViewBuilder
    private func versionGate(_ version: RoadmapVersion) -> some View {
        HStack(spacing: Organic.Space.p8) {
            Text("Version \(version.versionKey)").organic(.title)
            RoadmapStateTag(state: version.state)
        }
        Text("Month \(version.monthNumber) · mirror: \(version.mirrorStatus.replacingOccurrences(of: "_", with: " "))")
            .organic(.small)
        if version.mirrorStatus == "failed" {
            OrganicNotice(systemImage: "exclamationmark.triangle", tint: Organic.Color.danger,
                          message: "Private mirror failed: \(version.mirrorErrorCode ?? "unknown")") {
                Button("Retry private mirror") { Task { await model.retryMirror(version) } }
                    .disabled(model.isBusy)
            }
        } else if version.mirrorStatus == "synced" {
            Text("Private mirror synced · \(version.mirrorRef ?? "reference unavailable")")
                .organic(.mono, color: Organic.Color.muted)
        }
        if version.monthNumber > 1 {
            Text("Month 1 exit review must be complete and marked eligible before Month 2 can activate.")
                .organic(.caption)
        }
        HStack(spacing: Organic.Space.p8) {
            if version.state == "active" {
                statusLine("Month \(version.monthNumber) is active", systemImage: "checkmark.circle.fill", tint: Organic.Color.success)
                Spacer()
                Button("Reforecast…") { Task { await model.proposeReforecast(version) } }
                    .disabled(model.isBusy)
                    .accessibilityIdentifier("roadmapReforecastButton")
            } else {
                Button("Activate Month \(version.monthNumber)") { Task { await model.activate(version) } }
                    .buttonStyle(.organicPrimary)
                    .disabled(model.isBusy || !version.canActivate)
                Spacer()
            }
            Button("Export package") { Task { await model.exportVersion(version) } }
                .disabled(model.isBusy)
                .accessibilityIdentifier("roadmapExportButton")
        }
    }

    // MARK: Versions

    private var history: some View {
        VStack(alignment: .leading, spacing: Organic.Space.p12) {
            OrganicSectionTitle(title: "Roadmap versions", detail: "One active at a time")
            VStack(spacing: 10) {
                ForEach(model.versions) { item in
                    HStack(spacing: Organic.Space.p18) {
                        Text(item.versionKey)
                            .font(Organic.Font.tabular(.semibold, size: 18))
                            .foregroundStyle(Organic.Color.text)
                            .frame(width: 120, alignment: .leading)
                        RoadmapStateTag(state: item.state)
                        Text("Month \(item.monthNumber)").organic(.small, color: Organic.Color.neutral300)
                        Spacer(minLength: Organic.Space.p12)
                        HStack(spacing: 6) {
                            OrganicStatusDot(color: item.mirrorStatus == "synced" ? Organic.Color.accent2_400 : (item.mirrorStatus == "failed" ? Organic.Color.accent400 : Organic.Color.faint), diameter: 7)
                            Text("mirror: \(item.mirrorStatus.replacingOccurrences(of: "_", with: " "))").organic(.caption)
                        }
                        if item.mirrorStatus == "failed" {
                            Button("Retry mirror") { Task { await model.retryMirror(item) } }
                                .disabled(model.isBusy)
                        }
                        if item.canActivate {
                            Button("Activate") { Task { await model.activate(item) } }
                                .buttonStyle(.organicPrimary)
                                .disabled(model.isBusy)
                        }
                        if item.state == "active" {
                            Button("Reforecast…") { Task { await model.proposeReforecast(item) } }
                                .disabled(model.isBusy)
                        }
                        Button("Export") { Task { await model.exportVersion(item) } }
                            .disabled(model.isBusy)
                    }
                    .padding(.horizontal, Organic.Space.p24)
                    .padding(.vertical, Organic.Space.p18)
                    .background(
                        RoundedRectangle(cornerRadius: Organic.Radius.r26, style: .continuous)
                            .fill(item.state == "active" ? Organic.Color.accent2.opacity(0.14) : Organic.Color.surface)
                    )
                }
            }
        }
    }

    // MARK: Pieces

    /// One Text rather than OrganicMetric's two: the parity journey matches the whole
    /// "158 tasks" string as a single static text.
    private func metric(_ label: String, _ value: Int?) -> some View {
        let number = Text("\(value ?? 0)")
            .font(Organic.Font.tabular(.semibold, size: 15))
            .foregroundStyle(Organic.Color.text)
        let caption = Text(label)
            .font(OrganicText.caption.font)
            .foregroundStyle(Organic.Color.muted)
        return Text("\(number) \(caption)")
            .padding(.horizontal, Organic.Space.p14)
            .padding(.vertical, 7)
            .background(Organic.Color.fill06, in: Capsule(style: .continuous))
    }

    /// An icon and a Text side by side; the Text stays a plain static text, as the UI
    /// tests query "Validation passed" and "Month N is active" that way.
    private func statusLine(_ text: String, systemImage: String, tint: Color) -> some View {
        HStack(spacing: Organic.Space.p8) {
            Image(systemName: systemImage).foregroundStyle(tint).accessibilityHidden(true)
            Text(text).organic(.strong, color: tint)
        }
    }

    /// OrganicNotice's strip around caller-built content, so an identified element keeps
    /// the element type it had before the restyle.
    private func noticeStrip<Message: View>(tint: Color, @ViewBuilder message: () -> Message) -> some View {
        message()
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, Organic.Space.p20)
            .padding(.vertical, Organic.Space.p16)
            .background(tint.opacity(0.12), in: RoundedRectangle(cornerRadius: Organic.Radius.r24, style: .continuous))
    }

    private func noticeIcon(_ systemImage: String, tint: Color) -> some View {
        Image(systemName: systemImage)
            .font(.system(size: 15, weight: .semibold))
            .foregroundStyle(tint)
            .frame(width: 20)
            .accessibilityHidden(true)
    }
}

/// A numbered step card. Done steps get a sage check, the current one a
/// terracotta number, later ones a quiet outline.
private struct RoadmapStep<Content: View>: View {
    let number: Int
    let title: String
    let current: Int
    @ViewBuilder var content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: Organic.Space.p14) {
            HStack(spacing: Organic.Space.p12) {
                ZStack {
                    Circle().fill(badgeFill)
                    if number < current {
                        Image(systemName: "checkmark").font(.system(size: 11, weight: .bold)).foregroundStyle(Organic.Color.neutral900)
                    } else {
                        Text("\(number)").font(Organic.Font.tabular(.semibold, size: 13))
                            .foregroundStyle(number == current ? Organic.Color.neutral900 : Organic.Color.muted)
                    }
                }
                .frame(width: 26, height: 26)
                .accessibilityHidden(true)
                Text(title).organic(.title).accessibilityAddTraits(.isHeader)
            }
            VStack(alignment: .leading, spacing: Organic.Space.p12) { content }
                .padding(.leading, 38)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, Organic.Space.p24)
        .padding(.vertical, 22)
        .background(RoundedRectangle(cornerRadius: Organic.Radius.r28, style: .continuous).fill(Organic.Color.surface))
    }

    private var badgeFill: Color {
        if number < current { return Organic.Color.accent2_400 }
        if number == current { return Organic.Color.accent400 }
        return Organic.Color.fill08
    }
}

private struct RoadmapStateTag: View {
    let state: String

    var body: some View {
        switch state {
        case "active":
            OrganicTag(text: state, background: Organic.Color.accent2.opacity(0.28), foreground: Organic.Color.accent2_200)
        case "validated", "approved", "staged":
            OrganicTag(text: state, background: Organic.Color.accentOn, foreground: Organic.Color.accent300)
        default:
            OrganicTag(text: state)
        }
    }
}
