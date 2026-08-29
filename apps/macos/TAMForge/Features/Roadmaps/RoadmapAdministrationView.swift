import SwiftUI

struct RoadmapAdministrationView: View {
    @StateObject private var model: RoadmapAdministrationModel

    init(service: any RoadmapServicing) {
        _model = StateObject(wrappedValue: RoadmapAdministrationModel(service: service))
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
                    if model.roadmapImport != nil {
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
                }
                if (summary["added"]?.integerValue ?? 0) + (summary["removed"]?.integerValue ?? 0) + (summary["changed"]?.integerValue ?? 0) == 0 {
                    Text("No learning requirement changes were detected.")
                        .foregroundStyle(.secondary)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
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
