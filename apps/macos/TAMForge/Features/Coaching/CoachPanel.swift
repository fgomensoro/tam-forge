import SwiftUI

/// The after-commit coach conversation. The coach speaks only in blocks whose
/// scheme allows it and only after Attempt A is committed; the server enforces
/// both and the panel renders whatever it answers.
struct CoachPanel: View {
    @ObservedObject var model: CoachThreadModel

    var body: some View {
        GroupBox("Coach") {
            VStack(alignment: .leading, spacing: 12) {
                if !model.isOpened {
                    Text("Ask the coach about the attempt you just committed. It never writes evidence for you; it proposes lines you accept.")
                        .organic(.small)
                    Button("Open coach") { Task { await model.open() } }
                        .accessibilityIdentifier("coachOpen")
                } else if let thread = model.thread {
                    if thread.coachingAllowed {
                        conversation(thread)
                    } else {
                        Label("Coaching is not available for this block.", systemImage: "lock")
                            .organic(.small)
                            .accessibilityIdentifier("coachNotAllowed")
                    }
                } else if model.isBusy {
                    ProgressView("Opening coach…")
                        .controlSize(.small)
                } else {
                    Button("Retry") { Task { await model.open() } }
                }
                if let message = model.errorMessage {
                    Label(message, systemImage: "exclamationmark.triangle")
                        .organic(.small, color: Organic.Color.warning)
                        .accessibilityIdentifier("coachError")
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .accessibilityIdentifier("coachPanel")
    }

    @ViewBuilder
    private func conversation(_ thread: CoachThread) -> some View {
        if !thread.nextStep.isEmpty {
            Label(thread.nextStep, systemImage: "arrow.turn.down.right")
                .organic(.small, color: Organic.Color.accent300)
                .accessibilityIdentifier("coachNextStep")
        }
        ForEach(thread.messages) { message in
            VStack(alignment: .leading, spacing: 6) {
                Text(message.isCoach ? "Coach" : "You")
                    .organic(.kicker, color: message.isCoach ? Organic.Color.accent2_300 : Organic.Color.accent300)
                Text(message.text)
                    .organic(.small, color: Organic.Color.body)
                    .textSelection(.enabled)
                ForEach(message.proposedEvidence) { proposal in
                    HStack(alignment: .top, spacing: Organic.Space.p8) {
                        Text("\(proposal.kind): \(proposal.text)")
                        Spacer(minLength: 0)
                        if proposal.accepted {
                            Label("Accepted", systemImage: "checkmark.circle")
                                .foregroundStyle(Organic.Color.success)
                        } else {
                            Button("Accept") {
                                Task { await model.accept(messageID: message.id, index: proposal.index) }
                            }
                            .disabled(model.isBusy)
                        }
                    }
                    .organic(.small, color: Organic.Color.body)
                    .padding(Organic.Space.p12)
                    .background(Organic.Color.fill04, in: RoundedRectangle(cornerRadius: Organic.Radius.r20, style: .continuous))
                }
            }
            .padding(.vertical, 4)
        }
        TextEditor(text: $model.draft)
            .accessibilityIdentifier("coachDraft")
            .organicEditor(minHeight: 60, onSurface: true)
        HStack {
            if model.isBusy { ProgressView().controlSize(.small) }
            Spacer(minLength: 0)
            Button("Send") { Task { await model.send() } }
                .buttonStyle(.organicPrimary)
                .keyboardShortcut(.return, modifiers: [.command])
                .disabled(!model.canSend)
                .accessibilityIdentifier("coachSend")
        }
    }
}
