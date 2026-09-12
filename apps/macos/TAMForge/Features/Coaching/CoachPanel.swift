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
                        .foregroundStyle(.secondary)
                    Button("Open coach") { Task { await model.open() } }
                        .accessibilityIdentifier("coachOpen")
                } else if let thread = model.thread {
                    if thread.coachingAllowed {
                        conversation(thread)
                    } else {
                        Label("Coaching is not available for this block.", systemImage: "lock")
                            .foregroundStyle(.secondary)
                            .accessibilityIdentifier("coachNotAllowed")
                    }
                } else if model.isBusy {
                    ProgressView("Opening coach…")
                } else {
                    Button("Retry") { Task { await model.open() } }
                }
                if let message = model.errorMessage {
                    Label(message, systemImage: "exclamationmark.triangle")
                        .foregroundStyle(.orange)
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
                .accessibilityIdentifier("coachNextStep")
        }
        ForEach(thread.messages) { message in
            VStack(alignment: .leading, spacing: 6) {
                Text(message.isCoach ? "Coach" : "You")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
                Text(message.text)
                    .textSelection(.enabled)
                ForEach(message.proposedEvidence) { proposal in
                    HStack(alignment: .top) {
                        Text("\(proposal.kind): \(proposal.text)")
                        Spacer()
                        if proposal.accepted {
                            Label("Accepted", systemImage: "checkmark.circle")
                                .foregroundStyle(.green)
                        } else {
                            Button("Accept") {
                                Task { await model.accept(messageID: message.id, index: proposal.index) }
                            }
                            .disabled(model.isBusy)
                        }
                    }
                    .font(.callout)
                    .padding(8)
                    .background(.quaternary, in: RoundedRectangle(cornerRadius: 6))
                }
            }
            .padding(.vertical, 4)
        }
        TextEditor(text: $model.draft)
            .frame(minHeight: 60)
            .accessibilityIdentifier("coachDraft")
        HStack {
            if model.isBusy { ProgressView().controlSize(.small) }
            Spacer()
            Button("Send") { Task { await model.send() } }
                .keyboardShortcut(.return, modifiers: [.command])
                .disabled(!model.canSend)
                .accessibilityIdentifier("coachSend")
        }
    }
}
