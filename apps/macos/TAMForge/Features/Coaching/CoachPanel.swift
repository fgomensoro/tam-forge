import SwiftUI

/// The coach, floating in the corner of every screen: a bubble that opens the panel
/// above it. The shell lays it over the detail column, outside every route's scroll view.
struct CoachOverlay: View {
    @ObservedObject var model: CoachThreadModel

    var body: some View {
        VStack(alignment: .trailing, spacing: Organic.Space.p12) {
            if model.isPresented {
                CoachPanel(model: model)
            }
            Button { Task { await model.toggle() } } label: {
                Image(systemName: "bubble.left.and.bubble.right.fill")
                    .font(Organic.Font.figtree(.semibold, size: 20))
                    .foregroundStyle(Organic.Color.neutral900)
                    .frame(width: 52, height: 52)
                    .background(
                        Circle()
                            .fill(model.isPresented ? Organic.Color.accent500 : Organic.Color.accent400)
                            .shadow(
                                color: Organic.Shadow.large.color, radius: Organic.Shadow.large.radius,
                                x: Organic.Shadow.large.x, y: Organic.Shadow.large.y
                            )
                    )
                    .contentShape(Circle())
            }
            .buttonStyle(.plain)
            .help("Coach")
            .accessibilityLabel("Coach")
            .accessibilityIdentifier("coachBubble")
        }
        .organicContentTheme()
    }
}

/// The conversation about the screen the owner is on. On an activity it shows the
/// activity's thread, with the next step, the assistance note and evidence to accept;
/// everywhere else it shows the owner's general thread.
struct CoachPanel: View {
    @ObservedObject var model: CoachThreadModel

    var body: some View {
        VStack(alignment: .leading, spacing: Organic.Space.p12) {
            header
            conversation
            composer
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .organicCard(radius: Organic.Radius.r26, padding: Organic.Space.p20, shadowed: true)
        .frame(width: 380)
        .frame(maxHeight: 520)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("coachPanel")
    }

    private var header: some View {
        HStack(alignment: .top, spacing: Organic.Space.p8) {
            VStack(alignment: .leading, spacing: Organic.Space.p4) {
                Text("Coach").organic(.kicker, color: Organic.Color.accent2_300)
                Text(model.title)
                    .organic(.title)
                    .lineLimit(2)
                    .accessibilityIdentifier("coachContextTitle")
            }
            Spacer(minLength: 0)
            Button { model.isPresented = false } label: {
                Image(systemName: "xmark").font(Organic.Font.figtree(.semibold, size: 13))
            }
            .buttonStyle(.organicLink)
            .help("Close the coach")
            .accessibilityLabel("Close coach")
        }
    }

    private var conversation: some View {
        ScrollViewReader { proxy in
            ScrollView {
                VStack(alignment: .leading, spacing: Organic.Space.p12) {
                    if let thread = model.shownActivityThread { guidance(thread) }
                    if model.messages.isEmpty { Text(emptyHint).organic(.small) }
                    ForEach(model.messages) { message in
                        row(message).id(message.id)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .onChange(of: model.messages.last?.id, initial: true) { _, newest in
                guard let newest else { return }
                withAnimation { proxy.scrollTo(newest, anchor: .bottom) }
            }
        }
    }

    private var emptyHint: String {
        model.activityID == nil
            ? "Ask about this screen or the day's plan."
            : "Ask for a recall question or a hint. Help before the commit is recorded as assistance."
    }

    @ViewBuilder
    private func guidance(_ thread: CoachThread) -> some View {
        if !thread.nextStep.isEmpty {
            Label(thread.nextStep, systemImage: "arrow.turn.down.right")
                .organic(.small, color: Organic.Color.accent300)
                .accessibilityIdentifier("coachNextStep")
        }
        if let mode = thread.assistanceMode, mode != "none" {
            Label("Recorded as assisted: \(mode.replacingOccurrences(of: "_", with: " "))", systemImage: "hand.raised")
                .organic(.small, color: Organic.Color.warning)
                .accessibilityIdentifier("coachAssistanceMode")
        }
    }

    private func row(_ message: CoachMessage) -> some View {
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
        .padding(.vertical, Organic.Space.p4)
    }

    @ViewBuilder
    private var composer: some View {
        TextEditor(text: $model.draft)
            .accessibilityIdentifier("coachDraft")
            .organicEditor(minHeight: 60, onSurface: true)
            .frame(maxHeight: 96)
        HStack {
            if model.isBusy { ProgressView().controlSize(.small) }
            Spacer(minLength: 0)
            Button("Send") { Task { await model.send() } }
                .buttonStyle(.organicPrimary)
                .keyboardShortcut(.return, modifiers: [.command])
                .disabled(!model.canSend)
                .accessibilityIdentifier("coachSend")
        }
        if let message = model.errorMessage {
            Label(message, systemImage: "exclamationmark.triangle")
                .organic(.small, color: Organic.Color.warning)
                .accessibilityIdentifier("coachError")
        }
    }
}
