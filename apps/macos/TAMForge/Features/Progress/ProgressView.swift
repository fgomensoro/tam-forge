import SwiftUI

/// Progress: the 14 skills over time against their targets, real versus planned minutes per
/// week, and the last assessments and interviews.
struct ProgressScreen: View {
    @ObservedObject var model: ProgressModel

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 26) {
                header
                if let message = model.errorMessage {
                    OrganicNotice(systemImage: "exclamationmark.triangle", tint: Organic.Color.danger, message: message)
                        .accessibilityIdentifier("progressError")
                }
                ProgressColumns {
                    skills
                    VStack(alignment: .leading, spacing: Organic.Space.p24) {
                        weeks
                        assessmentDays
                    }
                }
                ProgressColumns {
                    assessments
                    interviews
                }
            }
            .frame(maxWidth: 1008, alignment: .leading)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .task { await model.load() }
        .accessibilityIdentifier("progressScreen")
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 6) {
            OrganicPageHeader(title: "Progress") {
                HStack(spacing: Organic.Space.p12) {
                    if model.isLoading { SwiftUI.ProgressView().controlSize(.small) }
                    Button("Refresh") { Task { await model.load() } }
                        .disabled(model.isLoading)
                        .accessibilityIdentifier("progressRefresh")
                }
            }
            Text("\(model.skillsOnTarget) of \(model.report.skills.count) skills at or past the month-one target.")
                .organic(.body, color: Organic.Color.muted)
                .accessibilityIdentifier("progressSkillsSummary")
        }
    }

    // MARK: Skills

    private var skills: some View {
        card("Skills against targets", detail: "level · baseline → M1 → final", spacing: Organic.Space.p16) {
            if model.report.skills.isEmpty, model.hasLoaded {
                Text("No skills yet. Seed the configuration and complete a block.").organic(.small)
            }
            ForEach(model.report.skills) { skill in
                VStack(alignment: .leading, spacing: 6) {
                    HStack(alignment: .firstTextBaseline) {
                        Text(skill.name)
                            .font(Organic.Font.figtree(.semibold, size: 13))
                            .foregroundStyle(Organic.Color.text)
                        Spacer(minLength: Organic.Space.p12)
                        Text(levelLabel(skill))
                            .font(Organic.Font.tabular(.regular, size: 13))
                            .foregroundStyle(Organic.Color.muted)
                    }
                    skillTrack(skill)
                    if !skill.points.isEmpty {
                        Text(skill.points.map { "\($0.snapshotDate): \($0.estimatedLevel)" }.joined(separator: "  ·  "))
                            .organic(.caption, color: Organic.Color.faint)
                            .lineLimit(2)
                    }
                }
                .accessibilityIdentifier("progressSkill-\(skill.slug)")
            }
        }
        .organicCard(radius: Organic.Radius.r30, padding: 0)
    }

    /// 10 pt track from baseline to final target; sage once the latest level reaches M1, with a
    /// 2×16 pt tick where M1 sits.
    private func skillTrack(_ skill: ProgressSkill) -> some View {
        let reachedMonthOne = skill.latestLevel.map { $0 >= skill.monthOneTarget } ?? false
        return GeometryReader { geometry in
            ZStack(alignment: .leading) {
                Capsule().fill(Organic.Color.fill08)
                Capsule()
                    .fill(reachedMonthOne ? Organic.Color.accent2_400 : Organic.Color.accent400)
                    .frame(width: geometry.size.width * skill.progressFraction)
                Rectangle()
                    .fill(Organic.Color.text)
                    .frame(width: 2, height: 16)
                    .offset(x: geometry.size.width * skill.monthOneFraction - 1)
            }
            .frame(height: 10)
        }
        .frame(height: 10)
    }

    // MARK: Weeks

    private var weeks: some View {
        card("Minutes per week") {
            if model.recentWeeks.isEmpty, model.hasLoaded {
                Text("No study days yet.").organic(.small)
            }
            if !model.recentWeeks.isEmpty {
                HStack(alignment: .bottom, spacing: 10) {
                    ForEach(model.recentWeeks) { week in
                        let isLatest = week.id == model.recentWeeks.last?.id
                        VStack(spacing: 6) {
                            UnevenRoundedRectangle(
                                topLeadingRadius: Organic.Radius.pill,
                                bottomLeadingRadius: 8,
                                bottomTrailingRadius: 8,
                                topTrailingRadius: Organic.Radius.pill
                            )
                            .fill(isLatest ? Organic.Color.accent400 : Organic.Color.accent2_500)
                            .frame(height: 100 * week.completion)
                            .frame(maxWidth: .infinity)
                            Text(String(week.weekStart.suffix(5)))
                                .font(Organic.Font.tabular(.regular, size: 11))
                                .foregroundStyle(Organic.Color.muted)
                        }
                        .frame(maxWidth: .infinity)
                        .help(weekLine(week))
                        .accessibilityElement(children: .ignore)
                        .accessibilityLabel(weekLine(week))
                        .accessibilityIdentifier("progressWeek-\(week.weekStart)")
                    }
                }
                .frame(height: 120, alignment: .bottom)
            }
            if let latest = model.recentWeeks.last {
                Text(weekLine(latest)).organic(.caption)
            }
        }
        .organicCard(radius: Organic.Radius.r30, padding: 0)
    }

    private func weekLine(_ week: ProgressWeek) -> String {
        "Week of \(week.weekStart): \(week.focusedMinutes) / \(week.plannedMinutes) focused · \(week.closedDays) of \(week.studyDays) days closed"
    }

    // MARK: Saturday assessments

    private var assessmentDays: some View {
        card("Saturday assessments", spacing: 10) {
            if model.report.assessmentDays.isEmpty, model.hasLoaded {
                Text("No assessment days yet.").organic(.small)
            }
            ForEach(model.report.assessmentDays) { day in
                VStack(alignment: .leading, spacing: 4) {
                    HStack(alignment: .firstTextBaseline) {
                        Text("\(day.localDate) · \(day.dayStatus)").organic(.small, color: Organic.Color.body)
                        Spacer(minLength: Organic.Space.p12)
                        Text(day.averageScore.map { "\($0) avg · \(day.scoredContracts)/\(day.contracts.count) scored" } ?? "not scored yet")
                            .font(Organic.Font.tabular(.regular, size: 13))
                            .foregroundStyle(day.averageScore == nil ? Organic.Color.muted : Organic.Color.accent2_200)
                    }
                    ForEach(day.contracts) { contract in
                        HStack(alignment: .firstTextBaseline) {
                            Text("\(contract.contractType.replacingOccurrences(of: "_", with: " ")) · \(contract.result.replacingOccurrences(of: "_", with: " "))")
                                .organic(.caption)
                            Spacer(minLength: Organic.Space.p12)
                            Text(contract.averageScore.map { "\($0)" } ?? "–")
                                .font(Organic.Font.tabular(.regular, size: 12))
                                .foregroundStyle(contract.averageScore == nil ? Organic.Color.muted : Organic.Color.accent2_200)
                        }
                    }
                }
                .accessibilityIdentifier("progressAssessmentDay-\(day.studyDayID)")
            }
        }
        .background(Organic.Color.sageOn, in: RoundedRectangle(cornerRadius: Organic.Radius.r30, style: .continuous))
    }

    // MARK: Assessments and interviews

    private var assessments: some View {
        card("Last assessments") {
            if model.report.assessments.isEmpty, model.hasLoaded {
                Text("No reviewer assessments yet.").organic(.small)
            }
            ForEach(model.report.assessments) { assessment in
                VStack(alignment: .leading, spacing: 2) {
                    HStack(alignment: .firstTextBaseline, spacing: Organic.Space.p8) {
                        Text(assessment.taskStableID)
                            .font(Organic.Font.figtree(.semibold, size: 13))
                            .foregroundStyle(Organic.Color.text)
                        Text(assessment.localDate).organic(.caption)
                        Spacer(minLength: Organic.Space.p12)
                        Text("\(assessment.averageScore) avg over \(assessment.dimensionCount)")
                            .font(Organic.Font.tabular(.regular, size: 13))
                            .foregroundStyle(Organic.Color.muted)
                    }
                    Text(assessment.verdict).organic(.caption).lineLimit(2)
                }
                .accessibilityIdentifier("progressAssessment-\(assessment.reviewID)")
            }
        }
        .organicCard(radius: Organic.Radius.r30, padding: 0)
    }

    private var interviews: some View {
        card("Last interviews") {
            if model.report.interviews.isEmpty, model.hasLoaded {
                Text("No interviews recorded yet.").organic(.small)
            }
            ForEach(model.report.interviews) { interview in
                VStack(alignment: .leading, spacing: 2) {
                    HStack(alignment: .firstTextBaseline, spacing: Organic.Space.p8) {
                        Text("\(interview.company) · \(interview.role)")
                            .font(Organic.Font.figtree(.semibold, size: 13))
                            .foregroundStyle(Organic.Color.text)
                        Text(interview.stage).organic(.caption)
                        Spacer(minLength: Organic.Space.p12)
                        Text(interview.startsAt, style: .date).organic(.caption)
                    }
                    Text("\(interview.status) · \(interview.recordingCount) rec").organic(.caption)
                }
                .accessibilityIdentifier("progressInterview-\(interview.interviewID)")
            }
        }
        .organicCard(radius: Organic.Radius.r30, padding: 0)
    }

    // MARK: Helpers

    /// The handoff's Progress card: 16 pt title with an optional 12 pt legend, padding 24/26.
    /// The fill is applied by the caller (surface for most, sage for Saturday assessments).
    private func card<Content: View>(
        _ title: String,
        detail: String? = nil,
        spacing: CGFloat = Organic.Space.p14,
        @ViewBuilder content: () -> Content
    ) -> some View {
        VStack(alignment: .leading, spacing: spacing) {
            HStack(alignment: .firstTextBaseline) {
                Text(title).organic(.title)
                Spacer(minLength: Organic.Space.p12)
                if let detail { Text(detail).organic(.caption) }
            }
            content()
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, 26)
        .padding(.vertical, Organic.Space.p24)
    }

    private func levelLabel(_ skill: ProgressSkill) -> String {
        let latest = skill.latestLevel.map { "\($0)" } ?? "no estimate"
        return "\(latest) · \(skill.baseline) → \(skill.monthOneTarget) → \(skill.finalTarget)"
    }
}

extension ProgressSkill {
    /// Where the month-one target sits on the same baseline-to-final track as `progressFraction`,
    /// clamped to 0...1. A skill with no span puts the marker at the end.
    var monthOneFraction: Double {
        let span = finalTarget - baseline
        guard span > 0 else { return 1 }
        let fraction = NSDecimalNumber(decimal: (monthOneTarget - baseline) / span).doubleValue
        return min(max(fraction, 0), 1)
    }
}

/// The handoff's `minmax(0, 1.4fr) minmax(0, 1fr)` grid with a 24 pt gap: two columns, eager,
/// as tall as the taller one.
private struct ProgressColumns: Layout {
    private let gap: CGFloat = Organic.Space.p24

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let width = proposal.width ?? 1008
        let (left, right) = widths(width)
        let widths: [CGFloat] = [left, right]
        let height = zip(subviews, widths)
            .map { subview, width in subview.sizeThatFits(ProposedViewSize(width: width, height: nil)).height }
            .max() ?? 0
        return CGSize(width: width, height: height)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        let (left, right) = widths(bounds.width)
        var x = bounds.minX
        for (subview, width) in zip(subviews, [left, right]) {
            subview.place(at: CGPoint(x: x, y: bounds.minY), proposal: ProposedViewSize(width: width, height: nil))
            x += width + gap
        }
    }

    private func widths(_ total: CGFloat) -> (CGFloat, CGFloat) {
        let left = max(total - gap, 0) * 1.4 / 2.4
        return (left, max(total - gap - left, 0))
    }
}
