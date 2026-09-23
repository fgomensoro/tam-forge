import SwiftUI

struct SqlExecutionPanel: View {
    @ObservedObject var workspace: ActivityWorkspaceModel
    @ObservedObject var model: SqlExecutionModel

    var body: some View {
        GroupBox("SQL execution") {
            VStack(alignment: .leading, spacing: 12) {
                HStack(spacing: Organic.Space.p12) {
                    if workspace.activity?.state.isEditable == true {
                        Button("Run") { Task { await workspace.runSQL() } }
                            .buttonStyle(.organicPrimary)
                            .disabled(!workspace.canRunSQL)
                            .accessibilityIdentifier("runSQL")
                    }
                    if model.isRunning { ProgressView("Running query…").controlSize(.small) }
                    if model.isLoadingHistory { ProgressView("Loading recent results…").controlSize(.small) }
                    Spacer(minLength: 0)
                    Button("Refresh results") { Task { await workspace.refreshSQLHistory() } }
                        .disabled(!workspace.canReadSQLHistory)
                }
                if workspace.activity?.state.isEditable == true {
                    if let reason = SqlExecutionModel.queryReason(workspace.draft.value(for: "query")) {
                        Text(reason).organic(.small)
                    } else if workspace.activity?.state != .active {
                        Text("Start or resume this activity to run SQL.").organic(.small)
                    }
                }
                if let message = model.errorMessage {
                    Text(message).organic(.small, color: Organic.Color.warning).accessibilityIdentifier("sqlExecutionError")
                }
                Text("Validation checks this exercise’s result and grain. It is not a competency score. Database elapsed time is separate from focused learning time.")
                    .organic(.caption)
                Text("Runs save receipts. Copy any result you want into your working output, then complete your explanation, business meaning and assistance before committing.")
                    .organic(.caption)
                if model.history.isEmpty && !model.isLoadingHistory {
                    Text("No recent execution receipts.").organic(.small)
                }
                ForEach(model.history) { receipt in
                    DisclosureGroup {
                        VStack(alignment: .leading, spacing: Organic.Space.p8) {
                            Text("Saved query").organic(.caption)
                            ScrollView { Text(receipt.query).frame(maxWidth: .infinity, alignment: .leading) }
                                .frame(maxHeight: 160)
                            Text("Returned columns and rows").organic(.caption)
                            ScrollView([.horizontal, .vertical]) { Text(receipt.result.displayText) }
                                .frame(maxHeight: 240)
                            Text("Exercise: \(receipt.result.exerciseKey) · version \(receipt.result.exerciseVersion)")
                                .organic(.caption)
                        }
                        .organic(.mono)
                        .textSelection(.enabled)
                    } label: {
                        VStack(alignment: .leading, spacing: 3) {
                            Text("Run \(receipt.executionID) · \(receipt.result.validation.title)")
                                .organic(.strong)
                            Text("\(receipt.result.rowCount) rows · \(receipt.result.elapsedMS) ms database time")
                                .organic(.caption)
                        }
                    }
                    .accessibilityIdentifier("sqlReceipt-\(receipt.executionID)")
                }
                Text("Up to 20 recent receipts within the history size limit. Saved queries and results are read-only here.")
                    .organic(.caption)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .accessibilityIdentifier("sqlExecutionPanel")
    }
}
