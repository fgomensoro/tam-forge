import AppKit
import SwiftUI

/// Settings > Claude: which of the two installed tokens the server's Claude worker uses, whether it is valid, and the command that replaces a slot's token. Tokens never pass through the app.
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
            Picker("Token slot", selection: Binding(
                get: { model.slot ?? .a },
                set: { newSlot in Task { await model.choose(newSlot) } }
            )) {
                ForEach(ClaudeTokenSlot.allCases, id: \.self) { slot in
                    Text(slot.label).tag(slot)
                }
            }
            .pickerStyle(.segmented)
            .labelsHidden()
            .disabled(model.isLoading || model.slot == nil)
            .accessibilityIdentifier("claudeSettingsSlot")
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
            if let switched = model.switchedSlot {
                Text("The worker switches to \(switched.label) on its next beat. Refresh in a minute to see its status.")
                    .organic(.small)
                    .fixedSize(horizontal: false, vertical: true)
            } else if let state = model.state {
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
            Text("To install or replace this slot's token, run this from the repository on your Mac. The token never passes through the app.")
                .organic(.small)
                .fixedSize(horizontal: false, vertical: true)
            HStack(spacing: Organic.Space.p12) {
                Text(rotateCommand)
                    .organic(.mono)
                    .textSelection(.enabled)
                    .accessibilityIdentifier("claudeSettingsCommand")
                Spacer(minLength: 0)
                Button("Copy") {
                    NSPasteboard.general.clearContents()
                    NSPasteboard.general.setString(rotateCommand, forType: .string)
                }
                .buttonStyle(OrganicSecondaryButtonStyle())
                .accessibilityIdentifier("claudeSettingsCopyCommand")
            }
        }
        .organicCard(radius: Organic.Radius.r24)
    }

    private var rotateCommand: String {
        ClaudeSettingsModel.rotateCommand(for: model.slot ?? .a)
    }

    private var statusTitle: String {
        if let switched = model.switchedSlot { return "Switched to \(switched.label)" }
        if let state = model.state { return state.title }
        return model.errorMessage == nil ? "Checking status" : "Status unavailable"
    }

    private var dotColor: Color {
        if model.isLoading || (model.state == nil && model.errorMessage == nil) { return Organic.Color.muted }
        return model.state == .ready ? Organic.Color.accent2_400 : Organic.Color.accent300
    }
}
