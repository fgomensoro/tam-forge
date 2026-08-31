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
            VStack(alignment: .leading, spacing: 20) {
                Text("Governed curriculum")
                    .font(.headline)
                    .foregroundStyle(.secondary)
                Text("Roadmaps")
                    .font(.largeTitle)
                    .accessibilityIdentifier("roadmapsTitle")
                Text("Obsidian remains your authored source. TAM Forge imports a versioned snapshot only after you inspect and approve its changes.")
                    .foregroundStyle(.secondary)

                sourcePackage
                if model.isBusy && model.roadmapImport == nil {
                    ProgressView("Uploading package…")
                        .accessibilityIdentifier("roadmapUploadStatus")
                }
                if let errorMessage = model.errorMessage {
                    Text(errorMessage)
                        .foregroundStyle(.red)
                        .accessibilityIdentifier("roadmapError")
                }
                if let roadmapImport = model.roadmapImport {
                    validationReport(roadmapImport)
                    if roadmapImport.isValidated {
                        semanticDiff(roadmapImport.semanticDiff)
                        approvalGate(roadmapImport)
                    }
                }
                if !model.versions.isEmpty { history }
            }
            .padding()
            .frame(maxWidth: 900, alignment: .leading)
        }
        .accessibilityIdentifier("roadmapWorkspaceScroll")
        .task { await model.loadHistory() }
    }

    private var sourcePackage: some View {
        GroupBox("1. Source package") {
            VStack(alignment: .leading, spacing: 12) {
                Text("Choose one ZIP or folder. TAM Forge never reads your Obsidian vault automatically.")
                    .foregroundStyle(.secondary)
                Text(model.selection?.displayName ?? "No package selected")
                    .accessibilityIdentifier("roadmapSelection")
                HStack {
                    Button("Choose ZIP or folder") { model.choosePackage() }
                        .disabled(model.isBusy)
                    Button("Review package") { model.beginStage() }
                        .disabled(model.selection == nil || model.isBusy)
                    if model.isBusy && model.roadmapImport == nil {
                        Button("Cancel upload") { model.cancelUpload() }
                            .accessibilityIdentifier("roadmapCancelUploadButton")
                    } else if model.roadmapImport != nil {
                        Button("Cancel review") { model.cancelReview() }
                            .disabled(model.isBusy)
                    }
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private func validationReport(_ roadmapImport: RoadmapImport) -> some View {
        GroupBox("2. Validation") {
            VStack(alignment: .leading, spacing: 8) {
                if roadmapImport.isValidated {
                    Text("Validation passed")
                        .font(.headline)
                    let report = roadmapImport.validationReport.objectValue ?? [:]
                    HStack {
                        metric("tasks", report["task_count"]?.integerValue)
                        metric("resources", report["resource_count"]?.integerValue)
                        metric("exit criteria", report["exit_criterion_count"]?.integerValue)
                    }
                    if let hash = report["normalized_hash"]?.stringValue {
                        Text("Normalized content hash")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        Text(hash)
                            .font(.system(.caption, design: .monospaced))
                            .textSelection(.enabled)
                    }
                    Text("Approval creates an immutable roadmap version; it never overwrites an earlier roadmap.")
                        .foregroundStyle(.secondary)
                } else {
                    Text("Validation needs attention")
                        .font(.headline)
                    validationIssues(roadmapImport.validationReport)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private func metric(_ label: String, _ value: Int?) -> some View {
        Text("\(value ?? 0) \(label)")
            .font(.subheadline)
            .padding(.vertical, 4)
            .padding(.horizontal, 8)
            .background(.quaternary, in: Capsule())
    }

    @ViewBuilder
    private func validationIssues(_ report: RoadmapJSONValue) -> some View {
        let issues = report.objectValue?["issues"]?.arrayValue ?? []
        if issues.isEmpty {
            Text("The package could not be validated.")
        } else {
            ForEach(Array(issues.enumerated()), id: \.offset) { _, issue in
                let values = issue.objectValue ?? [:]
                VStack(alignment: .leading, spacing: 2) {
                    Text(values["message"]?.stringValue ?? "The package could not be validated.")
                    if let path = values["path"]?.stringValue {
                        Text(path)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
            }
        }
    }

    private func semanticDiff(_ diff: RoadmapJSONValue) -> some View {
        GroupBox("3. Semantic comparison") {
            let summary = diff.objectValue?["summary"]?.objectValue ?? [:]
            VStack(alignment: .leading, spacing: 8) {
                Text("What this roadmap changes")
                    .font(.headline)
                HStack {
                    metric("added", summary["added"]?.integerValue)
                    metric("removed", summary["removed"]?.integerValue)
                    metric("changed", summary["changed"]?.integerValue)
                    metric("unchanged", summary["unchanged"]?.integerValue)
                }
                semanticDiffSection("Assignments and time", section: diff.objectValue?["tasks"])
                semanticDiffSection("Pass criteria", section: diff.objectValue?["pass_contracts"])
                semanticDiffSection("Assigned resources", section: diff.objectValue?["resources"])
                semanticDiffSection("Month exit criteria", section: diff.objectValue?["exit_criteria"])
                if (summary["added"]?.integerValue ?? 0) + (summary["removed"]?.integerValue ?? 0) + (summary["changed"]?.integerValue ?? 0) == 0 {
                    Text("No learning requirement changes were detected.")
                        .foregroundStyle(.secondary)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    @ViewBuilder
    private func semanticDiffSection(_ title: String, section: RoadmapJSONValue?) -> some View {
        let isExpanded = expandedDiffSections.contains(title)
        let entries = isExpanded
            ? RoadmapSemanticDiffPresentation.allChangedEntries(in: section)
            : RoadmapSemanticDiffPresentation.changedEntries(in: section)
        if !entries.isEmpty {
            VStack(alignment: .leading, spacing: 8) {
                Text(title).font(.headline)
                LazyVStack(alignment: .leading, spacing: 8) {
                    ForEach(entries) { entry in
                        VStack(alignment: .leading, spacing: 4) {
                            HStack {
                                Text(entry.key).font(.system(.body, design: .monospaced))
                                Text(entry.status).font(.caption).foregroundStyle(.secondary)
                            }
                            ForEach(entry.fields) { field in
                                VStack(alignment: .leading, spacing: 2) {
                                    Text(field.label).font(.subheadline).bold()
                                    if isExpanded {
                                        Text("Before")
                                            .font(.caption)
                                            .foregroundStyle(.secondary)
                                        Text(field.before)
                                            .foregroundStyle(.secondary)
                                            .fixedSize(horizontal: false, vertical: true)
                                            .textSelection(.enabled)
                                        Text("After")
                                            .font(.caption)
                                            .foregroundStyle(.secondary)
                                        Text(field.after)
                                            .fixedSize(horizontal: false, vertical: true)
                                            .textSelection(.enabled)
                                    } else {
                                        HStack(alignment: .top, spacing: 6) {
                                            Text(field.before).foregroundStyle(.secondary).lineLimit(2)
                                            Image(systemName: "arrow.right").accessibilityHidden(true)
                                            Text(field.after).lineLimit(2)
                                        }
                                    }
                                }
                            }
                        }
                        .padding(8)
                        .background(.quaternary, in: RoundedRectangle(cornerRadius: 8))
                    }
                }
                Button(isExpanded ? "Show bounded preview" : "Inspect all changes, fields, and values") {
                    if isExpanded {
                        expandedDiffSections.remove(title)
                    } else {
                        expandedDiffSections.insert(title)
                    }
                }
                if !isExpanded, RoadmapSemanticDiffPresentation.hasMoreEntries(in: section) {
                    Text("Showing first \(RoadmapSemanticDiffPresentation.maximumEntriesPerSection) changes. Inspect complete details before approval.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
        }
    }

    private func approvalGate(_ roadmapImport: RoadmapImport) -> some View {
        GroupBox("4. Approve, mirror, then activate") {
            VStack(alignment: .leading, spacing: 12) {
                if let version = model.version {
                    versionGate(version)
                } else {
                    Toggle(
                        "I reviewed the validation and semantic changes. Create an immutable roadmap version.",
                        isOn: $model.approvalConfirmed
                    )
                    .accessibilityIdentifier("roadmapApprovalConfirmation")
                    Text("Approval record · import #\(roadmapImport.id)")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    Button(model.isBusy ? "Approving…" : "Approve roadmap") {
                        Task { await model.approve() }
                    }
                    .disabled(!model.approvalConfirmed || model.isBusy)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    @ViewBuilder
    private func versionGate(_ version: RoadmapVersion) -> some View {
        Text("Version \(version.versionKey) \(version.state)")
            .font(.headline)
        Text("Month \(version.monthNumber) · mirror: \(version.mirrorStatus.replacingOccurrences(of: "_", with: " "))")
            .foregroundStyle(.secondary)
        if version.mirrorStatus == "failed" {
            Text("Private mirror failed: \(version.mirrorErrorCode ?? "unknown")")
                .foregroundStyle(.red)
            Button("Retry private mirror") { Task { await model.retryMirror(version) } }
                .disabled(model.isBusy)
        } else if version.mirrorStatus == "synced" {
            Text("Private mirror synced · \(version.mirrorRef ?? "reference unavailable")")
                .foregroundStyle(.secondary)
        }
        if version.monthNumber > 1 {
            Text("Month 1 exit review must be complete and marked eligible before Month 2 can activate.")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        if version.state == "active" {
            Text("Month \(version.monthNumber) is active")
                .foregroundStyle(.green)
        } else {
            Button("Activate Month \(version.monthNumber)") { Task { await model.activate(version) } }
                .disabled(model.isBusy || !version.canActivate)
        }
    }

    private var history: some View {
        GroupBox("Roadmap versions") {
            VStack(alignment: .leading, spacing: 10) {
                ForEach(model.versions) { item in
                    HStack(alignment: .firstTextBaseline) {
                        Text(item.versionKey).fontWeight(.semibold)
                        Text("Month \(item.monthNumber)")
                        Text(item.state)
                        Spacer()
                        Text("mirror: \(item.mirrorStatus.replacingOccurrences(of: "_", with: " "))")
                            .foregroundStyle(.secondary)
                        if item.mirrorStatus == "failed" {
                            Button("Retry mirror") { Task { await model.retryMirror(item) } }
                                .disabled(model.isBusy)
                        }
                        if item.canActivate {
                            Button("Activate") { Task { await model.activate(item) } }
                                .disabled(model.isBusy)
                        }
                    }
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }
}
