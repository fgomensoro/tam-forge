import SwiftUI

// Organic Today: the "Focus" layout from TAM Forge - Mac.dc.html (1a).
// Logic, states and UI-test hooks are unchanged from the previous TodayView;
// only presentation moved to the Organic content layer.

struct TodayView: View {
    @ObservedObject var model: TodayViewModel
    let onNavigate: (TodayDestination) -> Void
    @State private var showingDailyClose = false

    var body: some View {
        Group {
            switch model.state {
            case .loading:
                ProgressView("Preparing Today…")
                    .controlSize(.small)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                    .accessibilityLabel("Preparing Today")
            case .empty:
                OrganicEmptyState(
                    systemImage: "calendar",
                    title: "Today has no assigned work",
                    message: "Your roadmap and saved evidence are unchanged."
                )
            case let .content(snapshot), let .partial(snapshot), let .stale(snapshot):
                today(snapshot, stale: isStale)
            case let .offline(snapshot):
                unavailable(snapshot: snapshot, systemImage: "wifi.slash", title: "Today is offline",
                            detail: "Saved work is unchanged. Reconnect to refresh Today.")
            case let .problem(snapshot):
                unavailable(snapshot: snapshot, systemImage: "exclamationmark.triangle", title: "Today could not be loaded",
                            detail: "Your roadmap and saved evidence are unchanged.")
            }
        }
        .task { await model.load() }
    }

    private var isStale: Bool {
        if case .stale = model.state { return true }
        return false
    }

    @ViewBuilder
    private func unavailable(snapshot: TodaySnapshot?, systemImage: String, title: String, detail: String) -> some View {
        if let snapshot {
            today(snapshot, stale: true, notice: (systemImage, title, detail))
        } else {
            OrganicEmptyState(systemImage: systemImage, title: title, message: detail) {
                Button("Retry") { Task { await model.retry() } }
                    .buttonStyle(.organicPrimary)
                    .accessibilityIdentifier("todayRetryButton")
            }
        }
    }

    private func today(_ snapshot: TodaySnapshot, stale: Bool, notice: (String, String, String)? = nil) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Organic.Space.p28) {
                header(snapshot)
                if let notice {
                    TodayStateCard(systemImage: notice.0, title: notice.1, message: notice.2) {
                        retryButton
                    }
                } else if stale {
                    TodayStateCard(systemImage: "clock.arrow.circlepath", message: "Showing the last available Today.") {
                        retryButton
                    }
                }
                if snapshot.dayType == "sunday" || snapshot.dayStatus == "off" {
                    TodayStateCard(
                        systemImage: "leaf",
                        tint: Organic.Color.success,
                        title: "Protected rest",
                        message: "Sunday is off. No study, catch-up, or study reminders. Background processing may continue."
                    )
                    .accessibilityElement(children: .contain)
                    .accessibilityIdentifier("todaySundayOff")
                } else {
                    activeDay(snapshot)
                }
            }
            .frame(maxWidth: 1040, alignment: .leading)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.bottom, Organic.Space.p8)
        }
        .accessibilityIdentifier("todayScreen")
    }

    private var retryButton: some View {
        Button("Retry") { Task { await model.retry() } }
            .accessibilityIdentifier("todayRetryButton")
    }

    // MARK: Header

    private func header(_ snapshot: TodaySnapshot) -> some View {
        let policy = snapshot.timePolicy
        let planned = max(snapshot.totalPlannedMinutes, 1)
        let done = snapshot.tasks.filter { TodayTaskStatus(rawState: $0.state) == .done }.count
        return HStack(alignment: .bottom, spacing: Organic.Space.p24) {
            VStack(alignment: .leading, spacing: 6) {
                Text("Month \(snapshot.roadmap.month) · Week \(snapshot.roadmap.week) · Day \(snapshot.roadmap.day)")
                    .organic(.kicker, color: Organic.Color.accent400)
                // The handoff sets the Today greeting at 32 pt; the shared h1 role is the 28 pt page title.
                Text("Today")
                    .font(Organic.Font.figtree(.semibold, size: 32))
                    .tracking(-0.64)
                    .foregroundStyle(Organic.Color.text)
                    .accessibilityAddTraits(.isHeader)
                Text("\(policy.focusedMinutes) of \(snapshot.totalPlannedMinutes) focused minutes. Hard stop at \(policy.hardStopMinutes) — nothing gets added past it.")
                    .font(Organic.Font.figtree(.regular, size: 15))
                    .foregroundStyle(Organic.Color.muted)
                    .fixedSize(horizontal: false, vertical: true)
                Text("\(snapshot.localDate) · \(snapshot.timezone)").organic(.caption, color: Organic.Color.faint)
            }
            Spacer(minLength: Organic.Space.p24)
            HStack(spacing: Organic.Space.p14) {
                TodayRing(fraction: Double(policy.focusedMinutes) / Double(planned))
                VStack(alignment: .leading, spacing: 2) {
                    Text("\(done) of \(snapshot.tasks.count) done")
                        .font(Organic.Font.figtree(.semibold, size: 13))
                        .foregroundStyle(Organic.Color.text)
                    Text("\(snapshot.totalPlannedMinutes) planned minutes").organic(.small)
                }
            }
            .fixedSize()
            .accessibilityElement(children: .combine)
            .accessibilityLabel("Daily time policy. \(snapshot.totalPlannedMinutes) planned minutes, \(policy.focusedMinutes) focused minutes, hard stop \(policy.hardStopMinutes) minutes")
        }
    }

    // MARK: Active day

    @ViewBuilder
    private func activeDay(_ snapshot: TodaySnapshot) -> some View {
        if snapshot.dayType == "saturday" {
            OrganicTag(text: "Saturday · 120-minute maximum")
        }
        if snapshot.timePolicy.hardStopRecommended {
            TodayStateCard(
                systemImage: "stop.circle",
                message: "The day hard stop has been reached. Save safely and stop; TAM Forge will not add work."
            )
            .accessibilityElement(children: .combine)
            .accessibilityIdentifier("todayHardStopNotice")
        }
        let heroID = heroTaskID(snapshot)
        if let action = snapshot.primaryContinue, let destination = TodayDestination(action: action) {
            TodayHeroCard(
                action: action,
                task: snapshot.tasks.first { $0.activityID == heroID },
                onContinue: { open(destination) }
            )
        }
        if showingDailyClose {
            DailyCloseForm(snapshot: snapshot, model: model)
        }
        tasks(snapshot.tasks.filter { $0.activityID != heroID })
        support(snapshot)
    }

    /// The task the hero card stands for. It leaves the row list, since the hero's
    /// Continue button already opens it.
    private func heroTaskID(_ snapshot: TodaySnapshot) -> Int? {
        guard let action = snapshot.primaryContinue, let destination = TodayDestination(action: action) else { return nil }
        switch destination {
        case let .activity(id, _): return id
        case let .dailyClose(id): return id
        case .evidence: return nil
        }
    }

    private func open(_ destination: TodayDestination) {
        if case .dailyClose = destination { showingDailyClose = true } else { onNavigate(destination) }
    }

    // MARK: Support strip

    private func support(_ snapshot: TodaySnapshot) -> some View {
        let feedbackReady = snapshot.analyses.contains { $0.state == "ready" }
        return HStack(alignment: .top, spacing: Organic.Space.p12) {
            TodaySupportCard(
                title: "Carryovers",
                value: snapshot.corrections.isEmpty ? "None due" : "\(snapshot.corrections.count) of 2",
                lines: snapshot.corrections.map { "\($0.priority). \($0.instruction)" },
                empty: "Two corrections maximum"
            )
            TodaySupportCard(
                title: "Interview",
                value: snapshot.interviews.first.map { TodayDateTime.string($0.startsAt, timezoneIdentifier: snapshot.timezone) } ?? "No interview",
                lines: snapshot.interviews.map { "\($0.company) · \($0.role) · \($0.stage) · \($0.expectedDurationMinutes) min" },
                empty: "Real interviews appear here"
            )
            TodaySupportCard(
                title: "Self-review due",
                value: snapshot.awaitingSelfReviews.isEmpty ? "Nothing waiting" : "\(snapshot.awaitingSelfReviews.count) waiting",
                lines: snapshot.awaitingSelfReviews.map(\.objective),
                empty: "Independent reflection"
            )
            TodaySupportCard(
                title: "Feedback",
                value: snapshot.analyses.isEmpty ? "No new analysis" : (feedbackReady ? "Ready" : "Processing"),
                lines: snapshot.analyses.map { $0.state == "ready" ? "Feedback ready" : "Processing needs attention" },
                empty: "Asynchronous analysis",
                highlighted: feedbackReady
            )
        }
        .fixedSize(horizontal: false, vertical: true)
    }

    // MARK: Task list

    private func tasks(_ tasks: [TodayTask]) -> some View {
        let remaining = tasks
            .filter { TodayTaskStatus(rawState: $0.state) != .done }
            .reduce(0) { $0 + $1.timeboxMinutes }
        return VStack(alignment: .leading, spacing: Organic.Space.p12) {
            OrganicSectionTitle(
                title: "Rest of the day",
                detail: "Stable roadmap spine · \(remaining) min remaining"
            )
            VStack(spacing: 6) {
                ForEach(tasks) { task in
                    TodayTaskRow(task: task) { open(TodayDestination(task: task)) }
                }
            }
        }
        .accessibilityIdentifier("todayTasks")
    }
}

// MARK: - Pieces

/// The 76 pt focused-minutes ring: an 8 pt track around a 60 pt `bg` disc.
private struct TodayRing: View {
    let fraction: Double

    var body: some View {
        let clamped = min(max(fraction, 0), 1)
        ZStack {
            Circle().inset(by: 4).stroke(Organic.Color.fill10, lineWidth: 8)
            Circle()
                .inset(by: 4)
                .trim(from: 0, to: clamped)
                .stroke(Organic.Color.accent400, lineWidth: 8)
                .rotationEffect(.degrees(-90))
            Circle().fill(Organic.Color.bg).frame(width: 60, height: 60)
            Text("\(Int((clamped * 100).rounded()))%")
                .font(Organic.Font.tabular(.semibold, size: 18))
                .foregroundStyle(Organic.Color.text)
        }
        .frame(width: 76, height: 76)
    }
}

/// Offline, stale, hard-stop and rest-day states: a `surface` card, r24, tinted icon.
private struct TodayStateCard<Actions: View>: View {
    let systemImage: String
    var tint: Color = Organic.Color.warning
    var title: String?
    let message: String
    @ViewBuilder var actions: Actions

    var body: some View {
        HStack(alignment: .top, spacing: Organic.Space.p14) {
            Image(systemName: systemImage)
                .font(Organic.Font.figtree(.semibold, size: 15))
                .foregroundStyle(tint)
                .frame(width: 20)
                .padding(.top, 1)
            VStack(alignment: .leading, spacing: 2) {
                if let title { Text(title).organic(.strong) }
                Text(message).organic(.small, color: Organic.Color.neutral300)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: 0)
            actions
        }
        .padding(.horizontal, Organic.Space.p20)
        .padding(.vertical, Organic.Space.p16)
        .background(Organic.Color.surface, in: RoundedRectangle(cornerRadius: Organic.Radius.r24, style: .continuous))
    }
}

private extension TodayStateCard where Actions == EmptyView {
    init(systemImage: String, tint: Color = Organic.Color.warning, title: String? = nil, message: String) {
        self.init(systemImage: systemImage, tint: tint, title: title, message: message) { EmptyView() }
    }
}

private struct TodayHeroCard: View {
    let action: TodayContinueAction
    let task: TodayTask?
    let onContinue: () -> Void
    @State private var showingContract = false

    var body: some View {
        VStack(alignment: .leading, spacing: 22) {
            HStack(alignment: .top, spacing: Organic.Space.p16) {
                if let task {
                    Text(String(format: "%02d", task.roadmapOrder))
                        .font(Organic.Font.tabular(.semibold, size: 26))
                        .foregroundStyle(Organic.Color.accent400)
                }
                VStack(alignment: .leading, spacing: 6) {
                    HStack(spacing: Organic.Space.p8) {
                        Text("Continue").organic(.kicker, color: Organic.Color.accent300)
                        if let task {
                            OrganicTag(text: TodayFormat.block(task.block), background: Organic.Color.accentOn, foreground: Organic.Color.accent300)
                            OrganicTag(text: task.required ? "Required" : "Adaptive")
                        }
                        OrganicTag(text: "AI: \(TodayFormat.role(action.allowedAIRole))")
                    }
                    Text(task?.objective ?? action.label)
                        .organic(.h2)
                        .lineSpacing(2)
                        .fixedSize(horizontal: false, vertical: true)
                    if let task {
                        Text("\(task.timeboxMinutes) minutes · \(TodayFormat.state(task.state))")
                            .organic(.body, color: Organic.Color.muted)
                    }
                }
            }
            HStack(spacing: 10) {
                Button(action: onContinue) {
                    Label(action.label, systemImage: "play.fill")
                }
                .buttonStyle(OrganicPrimaryButtonStyle())
                .accessibilityLabel("Continue: \(action.label)")
                .accessibilityIdentifier("todayContinueButton")
                if let task {
                    Button("Open task contract") { showingContract.toggle() }
                        .buttonStyle(OrganicSecondaryButtonStyle(size: 14))
                        .popover(isPresented: $showingContract, arrowEdge: .bottom) {
                            TodayTaskContract(task: task).padding(Organic.Space.p20).frame(width: 380)
                        }
                }
            }
        }
        .padding(.horizontal, 30)
        .padding(.vertical, Organic.Space.p28)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: Organic.Radius.r32, style: .continuous)
                .fill(Organic.Color.surface)
                .shadow(color: Organic.Shadow.large.color, radius: Organic.Shadow.large.radius, x: 0, y: Organic.Shadow.large.y)
        )
    }
}

/// A "Rest of the day" pill row: order · dot · block · objective · minutes · state.
private struct TodayTaskRow: View {
    let task: TodayTask
    let onOpen: () -> Void
    @State private var showingContract = false

    var body: some View {
        let status = TodayTaskStatus(rawState: task.state)
        HStack(spacing: Organic.Space.p16) {
            Text(String(format: "%02d", task.roadmapOrder))
                .font(Organic.Font.tabular(.semibold, size: 15))
                .foregroundStyle(Organic.Color.muted)
                .frame(width: 26, alignment: .leading)
            OrganicStatusDot(color: status.dot)
            Text(TodayFormat.block(task.block))
                .organic(.caption)
                .lineLimit(1)
                .frame(width: 150, alignment: .leading)
            Text(task.objective)
                .organic(.body, color: Organic.Color.text)
                .strikethrough(status == .done, color: Organic.Color.muted)
                .lineLimit(2)
                .frame(maxWidth: .infinity, alignment: .leading)
            Text("\(task.timeboxMinutes) min")
                .organic(.caption)
                .frame(width: 64, alignment: .trailing)
            Text(TodayFormat.state(task.state))
                .font(Organic.Font.figtree(.regular, size: 11))
                .foregroundStyle(Organic.Color.neutral300)
                .lineLimit(1)
                .padding(.horizontal, 10)
                .padding(.vertical, 2)
                .frame(width: 96)
                .background(Organic.Color.fill08, in: Capsule(style: .continuous))
            Button {
                showingContract.toggle()
            } label: {
                Image(systemName: "doc.text").font(Organic.Font.figtree(.semibold, size: 13))
            }
            .buttonStyle(.organicLink)
            .help("Task contract")
            .accessibilityLabel("Task contract")
            .popover(isPresented: $showingContract, arrowEdge: .bottom) {
                TodayTaskContract(task: task).padding(Organic.Space.p20).frame(width: 380)
            }
            Button(task.block == "daily_close" ? "Open daily close" : "Open", action: onOpen)
                .accessibilityIdentifier("todayTaskOpen-\(task.activityID)")
        }
        .padding(.vertical, Organic.Space.p12)
        .padding(.horizontal, Organic.Space.p16)
        .background(status == .current ? Organic.Color.accentOn : .clear, in: Capsule(style: .continuous))
        .opacity(status == .done ? 0.55 : 1)
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Task \(task.roadmapOrder). \(task.objective). \(task.timeboxMinutes) minutes.")
    }
}

private extension TodayTaskStatus {
    var dot: Color {
        switch self {
        case .done: Organic.Color.accent2_400
        case .current: Organic.Color.accent400
        case .ready: Organic.Color.faint
        }
    }
}

private struct TodayTaskContract: View {
    let task: TodayTask

    var body: some View {
        VStack(alignment: .leading, spacing: Organic.Space.p14) {
            VStack(alignment: .leading, spacing: 4) {
                Text("Task contract").organic(.title)
                Text("\(task.timeboxMinutes) minutes · Allowed AI role: \(TodayFormat.role(task.allowedAIRole)) · \(task.required ? "Required" : "Adaptive")")
                    .organic(.caption)
            }
            section("Required output", task.requiredOutput)
            section("Pass criteria", task.passCriteria)
            section("Evidence", task.evidenceRequirements)
            VStack(alignment: .leading, spacing: 4) {
                Text("Assigned source").organic(.kicker)
                Text(task.sourceReferences.isEmpty
                     ? "No source assigned"
                     : task.sourceReferences.map { $0.path + ($0.anchor.map { " · \($0)" } ?? "") }.joined(separator: "\n"))
                    .organic(.small, color: Organic.Color.body)
            }
        }
    }

    @ViewBuilder
    private func section(_ title: String, _ values: [String]) -> some View {
        if !values.isEmpty {
            VStack(alignment: .leading, spacing: 4) {
                Text(title).organic(.kicker)
                ForEach(values, id: \.self) { Text("• \($0)").organic(.small, color: Organic.Color.body) }
            }
        }
    }
}

private struct TodaySupportCard: View {
    let title: String
    let value: String
    let lines: [String]
    let empty: String
    var highlighted = false

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title)
                .organic(.kicker, color: highlighted ? Organic.Color.accent2_300 : Organic.Color.muted)
            Text(value)
                .font(Organic.Font.tabular(.semibold, size: 16))
                .tracking(-0.16)
                .foregroundStyle(Organic.Color.text)
                .lineLimit(1)
            if lines.isEmpty {
                Text(empty).organic(.caption)
            } else {
                ForEach(lines.prefix(2), id: \.self) {
                    Text($0).organic(.caption, color: highlighted ? Organic.Color.neutral300 : nil).lineLimit(2)
                }
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .padding(.horizontal, Organic.Space.p18)
        .padding(.vertical, Organic.Space.p16)
        .background(
            RoundedRectangle(cornerRadius: Organic.Radius.r22, style: .continuous)
                .fill(highlighted ? Organic.Color.sageOn : Organic.Color.fill04)
        )
    }
}

private enum TodayFormat {
    static func block(_ raw: String) -> String { raw.replacingOccurrences(of: "_", with: " ").capitalized }
    static func state(_ raw: String) -> String { raw.replacingOccurrences(of: "_", with: " ") }
    static func role(_ raw: String) -> String { raw == "none" ? "None" : raw }
}

// MARK: - Daily close

private struct DailyCloseForm: View {
    let snapshot: TodaySnapshot
    @ObservedObject var model: TodayViewModel
    @State private var strongestOutput = ""
    @State private var repeatedMistake = ""
    @State private var unfinishedClassification: TodayUnfinishedClassification = .none
    @State private var unfinishedRequirement = ""
    @State private var evidenceConfirmed = false
    @State private var correctionIDs = Set<Int>()

    var body: some View {
        GroupBox("Close the study day") {
            VStack(alignment: .leading, spacing: Organic.Space.p16) {
                Text("Confirm evidence, name the strongest output and repeated mistake, then stop. Unused time does not create extra work.")
                    .organic(.small)
                HStack(alignment: .top, spacing: Organic.Space.p14) {
                    OrganicFieldLabel(title: "Strongest output") {
                        TextEditor(text: $strongestOutput).organicEditor(minHeight: 84, onSurface: true)
                            .accessibilityLabel("Strongest output")
                    }
                    OrganicFieldLabel(title: "Repeated mistake") {
                        TextEditor(text: $repeatedMistake).organicEditor(minHeight: 84, onSurface: true)
                            .accessibilityLabel("Repeated mistake")
                    }
                }
                OrganicFieldLabel(title: "Unfinished work") {
                    Picker("Unfinished work", selection: $unfinishedClassification) {
                        ForEach(TodayUnfinishedClassification.allCases, id: \.self) { Text($0.title).tag($0) }
                    }
                    .labelsHidden()
                    .fixedSize()
                }
                if unfinishedClassification != .none {
                    TextEditor(text: $unfinishedRequirement).organicEditor(minHeight: 72, onSurface: true)
                        .accessibilityLabel("Unfinished requirement")
                }
                if !snapshot.corrections.isEmpty {
                    VStack(alignment: .leading, spacing: Organic.Space.p8) {
                        Text("Corrections for tomorrow · \(correctionIDs.count) of 2").organic(.kicker)
                        ForEach(snapshot.corrections) { correction in
                            Toggle(correction.instruction, isOn: correctionBinding(correction.id))
                                .disabled(correctionIDs.count >= 2 && !correctionIDs.contains(correction.id))
                        }
                    }
                }
                HStack(alignment: .center, spacing: Organic.Space.p12) {
                    Toggle("I confirmed today’s saved evidence and will not add catch-up work.", isOn: $evidenceConfirmed)
                        .accessibilityIdentifier("todayEvidenceConfirmation")
                    Spacer(minLength: Organic.Space.p12)
                    Button(closeTitle) {
                        Task {
                            await model.close(
                                .init(
                                    strongestOutput: strongestOutput,
                                    repeatedMistake: repeatedMistake,
                                    unfinishedClassification: unfinishedClassification,
                                    unfinishedRequirement: unfinishedClassification == .none ? nil : unfinishedRequirement,
                                    evidenceConfirmed: evidenceConfirmed,
                                    correctionIDs: Array(correctionIDs)
                                )
                            )
                        }
                    }
                    .buttonStyle(.organicPrimary)
                    .disabled(!canClose || isSubmitting)
                    .accessibilityIdentifier("todayCloseDayButton")
                }
                closeMessage
            }
        }
        .accessibilityIdentifier("todayDailyClose")
    }

    private var canClose: Bool {
        evidenceConfirmed && !strongestOutput.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && !repeatedMistake.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && (unfinishedClassification == .none || !unfinishedRequirement.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
    }

    private var isSubmitting: Bool {
        if case .submitting = model.closeState { return true }
        return false
    }

    private var closeTitle: String { isSubmitting ? "Closing…" : "Close day" }

    @ViewBuilder
    private var closeMessage: some View {
        switch model.closeState {
        case .idle, .submitting: EmptyView()
        case .retryRequired:
            OrganicNotice(systemImage: "arrow.clockwise", message: "We could not confirm daily close. Today was refreshed before retrying.") {
                Button("Retry close") { Task { await model.retryClose() } }
            }
        case let .validation(message):
            OrganicNotice(systemImage: "exclamationmark.circle", tint: Organic.Color.danger, message: message)
        case let .closed(response):
            OrganicNotice(systemImage: "checkmark.circle", tint: Organic.Color.success,
                          message: response.replayed ? "Daily close already saved." : "Daily close saved.")
        }
    }

    private func correctionBinding(_ id: Int) -> Binding<Bool> {
        Binding(
            get: { correctionIDs.contains(id) },
            set: { selected in
                if selected { correctionIDs.insert(id) } else { correctionIDs.remove(id) }
            }
        )
    }
}
