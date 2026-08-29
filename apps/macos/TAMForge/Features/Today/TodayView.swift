import SwiftUI

struct TodayView: View {
    @ObservedObject var model: TodayViewModel
    let onNavigate: (TodayDestination) -> Void
    @State private var showingDailyClose = false

    var body: some View {
        Group {
            switch model.state {
            case .loading:
                ProgressView("Preparing Today…")
                    .accessibilityLabel("Preparing Today")
            case .empty:
                ContentUnavailableView(
                    "Today has no assigned work",
                    systemImage: "calendar",
                    description: Text("Your roadmap and saved evidence are unchanged.")
                )
            case let .content(snapshot), let .partial(snapshot), let .stale(snapshot):
                today(snapshot, stale: isStale)
            case let .offline(snapshot):
                unavailable(
                    snapshot: snapshot,
                    title: "Today is offline",
                    detail: "Saved work is unchanged. Reconnect to refresh Today."
                )
            case let .problem(snapshot):
                unavailable(
                    snapshot: snapshot,
                    title: "Today could not be loaded",
                    detail: "Your roadmap and saved evidence are unchanged."
                )
            }
        }
        .task { await model.load() }
    }

    private var isStale: Bool {
        if case .stale = model.state { return true }
        return false
    }

    @ViewBuilder
    private func unavailable(snapshot: TodaySnapshot?, title: String, detail: String) -> some View {
        if let snapshot {
            VStack(spacing: 12) {
                Text(title).font(.headline).accessibilityAddTraits(.isHeader)
                Text(detail).foregroundStyle(.secondary)
                today(snapshot, stale: true)
            }
        } else {
            ContentUnavailableView {
                Label(title, systemImage: "exclamationmark.triangle")
            } description: {
                Text(detail)
            } actions: {
                Button("Retry") { Task { await model.retry() } }
                    .accessibilityIdentifier("todayRetryButton")
            }
        }
    }

    private func today(_ snapshot: TodaySnapshot, stale: Bool) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                header(snapshot, stale: stale)
                if snapshot.dayType == "sunday" || snapshot.dayStatus == "off" {
                    GroupBox("Protected rest") {
                        Text("Sunday is off. No study, catch-up, or study reminders. Background processing may continue.")
                    }
                    .accessibilityIdentifier("todaySundayOff")
                } else {
                    activeDay(snapshot)
                }
            }
            .padding()
        }
        .accessibilityIdentifier("todayScreen")
    }

    private func header(_ snapshot: TodaySnapshot, stale: Bool) -> some View {
        HStack(alignment: .top) {
            VStack(alignment: .leading, spacing: 4) {
                Text("Your learning day").font(.subheadline).foregroundStyle(.secondary)
                Text("Today").font(.largeTitle).bold().accessibilityAddTraits(.isHeader)
                Text("Month \(snapshot.roadmap.month) · Week \(snapshot.roadmap.week) · Day \(snapshot.roadmap.day)")
                Text("\(snapshot.localDate) · \(snapshot.timezone)")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            Spacer()
            VStack(alignment: .trailing, spacing: 4) {
                Text("\(snapshot.totalPlannedMinutes) planned minutes").bold()
                Text("\(snapshot.timePolicy.focusedMinutes) focused · hard stop \(snapshot.timePolicy.hardStopMinutes)")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                if stale { Text("Showing last available Today").font(.caption).foregroundStyle(.orange) }
            }
            .accessibilityElement(children: .combine)
            .accessibilityLabel("Daily time policy. \(snapshot.totalPlannedMinutes) planned minutes, \(snapshot.timePolicy.focusedMinutes) focused minutes, hard stop \(snapshot.timePolicy.hardStopMinutes) minutes")
        }
    }

    @ViewBuilder
    private func activeDay(_ snapshot: TodaySnapshot) -> some View {
        if snapshot.dayType == "saturday" {
            Text("Saturday · 120-minute maximum").foregroundStyle(.secondary)
        }
        if snapshot.timePolicy.hardStopRecommended {
            Label("The day hard stop has been reached. Save safely and stop; TAM Forge will not add work.", systemImage: "stop.circle")
                .foregroundStyle(.orange)
                .accessibilityIdentifier("todayHardStopNotice")
        }
        if let action = snapshot.primaryContinue, let destination = TodayDestination(action: action) {
            Button {
                if case .dailyClose = destination {
                    showingDailyClose = true
                } else {
                    onNavigate(destination)
                }
            } label: {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Continue").font(.caption).foregroundStyle(.secondary)
                    Text(action.label).font(.headline)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .buttonStyle(.borderedProminent)
            .accessibilityLabel("Continue: \(action.label)")
            .accessibilityIdentifier("todayContinueButton")
        }
        if showingDailyClose {
            DailyCloseForm(snapshot: snapshot, model: model)
        }
        support(snapshot)
        tasks(snapshot.tasks)
    }

    private func support(_ snapshot: TodaySnapshot) -> some View {
        Grid(horizontalSpacing: 18, verticalSpacing: 18) {
            GridRow {
                supportCard("Carryovers", subtitle: "Two corrections maximum", lines: snapshot.corrections.map { "\($0.priority). \($0.instruction)" }, empty: "None due today.")
                supportCard("Scheduled", subtitle: "Real interviews", lines: snapshot.interviews.map { "\($0.company) · \($0.role) · \($0.stage)\n\(TodayDateTime.string($0.startsAt, timezoneIdentifier: snapshot.timezone)) · \($0.expectedDurationMinutes) minutes" }, empty: "No interview scheduled today.")
            }
            GridRow {
                supportCard("Self-review due", subtitle: "Independent reflection", lines: snapshot.awaitingSelfReviews.map(\.objective), empty: "Nothing waiting.")
                supportCard("Feedback status", subtitle: "Asynchronous analysis", lines: snapshot.analyses.map { $0.state == "ready" ? "Feedback ready" : "Processing needs attention" }, empty: "No new analysis.")
            }
        }
    }

    private func supportCard(_ title: String, subtitle: String, lines: [String], empty: String) -> some View {
        GroupBox {
            VStack(alignment: .leading, spacing: 6) {
                Text(subtitle).font(.caption).foregroundStyle(.secondary)
                if lines.isEmpty { Text(empty).foregroundStyle(.secondary) }
                else { ForEach(lines, id: \.self) { Text($0) } }
            }
        } label: {
            Text(title).font(.headline)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func tasks(_ tasks: [TodayTask]) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Stable roadmap spine").font(.caption).foregroundStyle(.secondary)
            Text("Required work").font(.title2).bold().accessibilityAddTraits(.isHeader)
            ForEach(tasks) { task in TodayTaskCard(task: task) }
        }
        .accessibilityIdentifier("todayTasks")
    }
}

private struct TodayTaskCard: View {
    let task: TodayTask

    var body: some View {
        GroupBox {
            VStack(alignment: .leading, spacing: 10) {
                HStack(alignment: .top) {
                    Text(String(format: "%02d", task.roadmapOrder)).monospacedDigit().foregroundStyle(.secondary)
                    VStack(alignment: .leading, spacing: 4) {
                        Text(task.block.replacingOccurrences(of: "_", with: " ").capitalized).font(.caption).foregroundStyle(.secondary)
                        Text(task.objective).font(.headline)
                    }
                    Spacer()
                    Text(task.state.replacingOccurrences(of: "_", with: " ")).font(.caption)
                }
                Text("\(task.timeboxMinutes) minutes · Allowed AI role: \(task.allowedAIRole == "none" ? "None" : task.allowedAIRole) · \(task.required ? "Required" : "Adaptive")")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                DisclosureGroup("Task contract") {
                    taskList("Required output", task.requiredOutput)
                    taskList("Pass criteria", task.passCriteria)
                    taskList("Evidence", task.evidenceRequirements)
                    if task.sourceReferences.isEmpty {
                        Text("Assigned source: No source assigned")
                    } else {
                        Text("Assigned source: \(task.sourceReferences.map { $0.path + ($0.anchor.map { " · \($0)" } ?? "") }.joined(separator: ", "))")
                    }
                }
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Task \(task.roadmapOrder). \(task.objective). \(task.timeboxMinutes) minutes.")
    }

    @ViewBuilder
    private func taskList(_ title: String, _ values: [String]) -> some View {
        if !values.isEmpty {
            Text(title).font(.subheadline).bold()
            ForEach(values, id: \.self) { Text("• \($0)") }
        }
    }
}

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
            VStack(alignment: .leading, spacing: 12) {
                Text("Confirm evidence, name the strongest output and repeated mistake, then stop. Unused time does not create extra work.")
                TextEditor(text: $strongestOutput).frame(minHeight: 72).accessibilityLabel("Strongest output")
                TextEditor(text: $repeatedMistake).frame(minHeight: 72).accessibilityLabel("Repeated mistake")
                Picker("Unfinished work", selection: $unfinishedClassification) {
                    ForEach(TodayUnfinishedClassification.allCases, id: \.self) { Text($0.title).tag($0) }
                }
                if unfinishedClassification != .none {
                    TextEditor(text: $unfinishedRequirement).frame(minHeight: 72).accessibilityLabel("Unfinished requirement")
                }
                if !snapshot.corrections.isEmpty {
                    Text("Corrections selected for tomorrow · \(correctionIDs.count) of 2").font(.subheadline)
                    ForEach(snapshot.corrections) { correction in
                        Toggle(correction.instruction, isOn: correctionBinding(correction.id))
                            .disabled(correctionIDs.count >= 2 && !correctionIDs.contains(correction.id))
                    }
                }
                Toggle("I confirmed today’s saved evidence and will not add catch-up work.", isOn: $evidenceConfirmed)
                    .accessibilityIdentifier("todayEvidenceConfirmation")
                closeMessage
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
                .disabled(!canClose || isSubmitting)
                .accessibilityIdentifier("todayCloseDayButton")
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

    private var closeTitle: String {
        isSubmitting ? "Closing…" : "Close day"
    }

    @ViewBuilder
    private var closeMessage: some View {
        switch model.closeState {
        case .idle, .submitting: EmptyView()
        case .retryRequired:
            VStack(alignment: .leading) {
                Text("We could not confirm daily close. Today was refreshed before retrying.").foregroundStyle(.orange)
                Button("Retry close") { Task { await model.retryClose() } }
            }
        case let .validation(message): Text(message).foregroundStyle(.red)
        case let .closed(response): Text(response.replayed ? "Daily close already saved." : "Daily close saved.").foregroundStyle(.green)
        }
    }

    private func correctionBinding(_ id: Int) -> Binding<Bool> {
        Binding(
            get: { correctionIDs.contains(id) },
            set: { selected in
                if selected { correctionIDs.insert(id) }
                else { correctionIDs.remove(id) }
            }
        )
    }
}
