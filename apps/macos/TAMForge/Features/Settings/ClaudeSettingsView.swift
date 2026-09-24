import AppKit
import SwiftUI

/// Settings > Claude: whether the server's Claude worker runs with a valid token, and
/// the command that replaces the token. The token itself never passes through the app.
struct ClaudeSettingsView: View {
    @ObservedObject var session: ShellSessionModel
    @StateObject private var model: ClaudeSettingsModel

    init(session: ShellSessionModel, api: any ClaudeStatusAPI) {
        self.session = session
        _model = StateObject(wrappedValue: ClaudeSettingsModel(api: api))
    }

    var body: some View {
        VStack(alignment: .leading, spacing: Organic.Space.p20) {
            Text("Claude").organic(.h2)
            if case .signedIn = session.phase {
                status
                rotation
            } else {
                Text("Sign in to see Claude status.").organic(.body)
            }
        }
        .padding(Organic.Space.p28)
        .frame(width: 460, alignment: .leading)
        .background(Organic.Color.bg)
    }

    private var status: some View {
        VStack(alignment: .leading, spacing: Organic.Space.p8) {
            HStack(spacing: Organic.Space.p12) {
                OrganicStatusDot(color: dotColor)
                Text(statusTitle)
                    .organic(.strong)
                    .accessibilityIdentifier("claudeSettingsStatus")
                Spacer(minLength: 0)
                Button("Refresh") { Task { await model.refresh() } }
                    .buttonStyle(OrganicSecondaryButtonStyle())
                    .disabled(model.isLoading)
                    .accessibilityIdentifier("claudeSettingsRefresh")
            }
            if let state = model.state {
                Text(state.detail).organic(.small).fixedSize(horizontal: false, vertical: true)
            }
            if let errorMessage = model.errorMessage {
                Text(errorMessage).organic(.small, color: Organic.Color.danger)
            }
        }
        .organicCard(radius: Organic.Radius.r24)
        // Runs each time the signed-in branch appears, so signing in with the window open reads it too.
        .task { await model.refresh() }
    }

    private var rotation: some View {
        VStack(alignment: .leading, spacing: Organic.Space.p12) {
            Text("To change the token, run this from the repository on your Mac. The token never passes through the app.")
                .organic(.small)
                .fixedSize(horizontal: false, vertical: true)
            HStack(spacing: Organic.Space.p12) {
                Text(ClaudeSettingsModel.rotateCommand)
                    .organic(.mono)
                    .textSelection(.enabled)
                    .accessibilityIdentifier("claudeSettingsCommand")
                Spacer(minLength: 0)
                Button("Copy") {
                    NSPasteboard.general.clearContents()
                    NSPasteboard.general.setString(ClaudeSettingsModel.rotateCommand, forType: .string)
                }
                .buttonStyle(OrganicSecondaryButtonStyle())
                .accessibilityIdentifier("claudeSettingsCopyCommand")
            }
        }
        .organicCard(radius: Organic.Radius.r24)
    }

    private var statusTitle: String {
        if let state = model.state { return state.title }
        return model.errorMessage == nil ? "Checking status" : "Status unavailable"
    }

    private var dotColor: Color {
        if model.isLoading || (model.state == nil && model.errorMessage == nil) { return Organic.Color.muted }
        return model.state == .ready ? Organic.Color.accent2_400 : Organic.Color.accent300
    }
}
