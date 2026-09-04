import SwiftUI

struct SqlExecutionPanel: View {
    @ObservedObject var workspace: ActivityWorkspaceModel
    @ObservedObject var model: SqlExecutionModel

    var body: some View {
        GroupBox("SQL execution") {
            VStack(alignment: .leading, spacing: 12) {
                HStack {
                    if workspace.activity?.state.isEditable == true {
                        Button("Run") { Task { await workspace.runSQL() } }
                            .disabled(!workspace.canRunSQL)
                            .accessibilityIdentifier("runSQL")
                    }
                    if model.isRunning { ProgressView("Running query…").controlSize(.small) }
                    if model.isLoadingHistory { ProgressView("Loading recent results…").controlSize(.small) }
                    Spacer()
                    Button("Refresh results") { Task { await workspace.refreshSQLHistory() } }
                        .disabled(!workspace.canReadSQLHistory)
                }
                if workspace.activity?.state.isEditable == true {
                    if let reason = SqlExecutionModel.queryReason(workspace.draft.value(for: "query")) {
                        Text(reason).foregroundStyle(.secondary)
                    } else if workspace.activity?.state != .active {
                        Text("Start or resume this activity to run SQL.").foregroundStyle(.secondary)
                    }
                }
                if let message = model.errorMessage {
                    Text(message).foregroundStyle(.orange).accessibilityIdentifier("sqlExecutionError")
                }
                Text("Validation checks this exercise’s result and grain. It is not a competency score. Database elapsed time is separate from focused learning time.")
                    .font(.caption).foregroundStyle(.secondary)
                Text("Runs save receipts. Copy any result you want into your working output, then complete your explanation, business meaning and assistance before committing.")
                    .font(.caption).foregroundStyle(.secondary)
                if model.history.isEmpty && !model.isLoadingHistory {
                    Text("No recent execution receipts.").foregroundStyle(.secondary)
                }
                ForEach(model.history) { receipt in
                    DisclosureGroup {
                        VStack(alignment: .leading, spacing: 8) {
                            Text("Saved query").font(.subheadline.weight(.medium))
                            ScrollView { Text(receipt.query).frame(maxWidth: .infinity, alignment: .leading) }
                                .frame(maxHeight: 160)
                            Text("Returned columns and rows").font(.subheadline.weight(.medium))
                            ScrollView([.horizontal, .vertical]) { Text(receipt.result.displayText) }
                                .frame(maxHeight: 240)
                            Text("Exercise: \(receipt.result.exerciseKey) · version \(receipt.result.exerciseVersion)")
                                .font(.caption)
                        }
                        .font(.body.monospaced())
                        .textSelection(.enabled)
                    } label: {
                        VStack(alignment: .leading, spacing: 3) {
                            Text("Run \(receipt.executionID) · \(receipt.result.validation.title)")
                            Text("\(receipt.result.rowCount) rows · \(receipt.result.elapsedMS) ms database time")
                                .font(.caption).foregroundStyle(.secondary)
                        }
                    }
                    .accessibilityIdentifier("sqlReceipt-\(receipt.executionID)")
                }
                Text("Up to 20 recent receipts within the history size limit. Saved queries and results are read-only here.")
                    .font(.caption).foregroundStyle(.secondary)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .accessibilityIdentifier("sqlExecutionPanel")
    }
}
