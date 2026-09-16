import SwiftUI

/// Progress: the 14 skills over time against their targets, real versus planned minutes per
/// week, and the last assessments and interviews.
struct ProgressScreen: View {
    @ObservedObject var model: ProgressModel

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                HStack {
                    Text("Progress").font(.title2.weight(.semibold))
                    Spacer()
                    if model.isLoading { SwiftUI.ProgressView().controlSize(.small) }
                    Button("Refresh") { Task { await model.load() } }
                        .disabled(model.isLoading)
                        .accessibilityIdentifier("progressRefresh")
                }
                if let message = model.errorMessage {
                    Label(message, systemImage: "exclamationmark.triangle").foregroundStyle(Color.orange)
                        .accessibilityIdentifier("progressError")
                }
                skills
                weeks
                assessmentDays
                assessments
                interviews
            }
            .padding()
        }
        .task { await model.load() }
        .accessibilityIdentifier("progressScreen")
    }

    private var skills: some View {
        GroupBox("Skills against targets") {
            VStack(alignment: .leading, spacing: 8) {
                Text("\(model.skillsOnTarget) of \(model.report.skills.count) at or past the month-one target.")
                    .font(.caption).foregroundStyle(.secondary)
                    .accessibilityIdentifier("progressSkillsSummary")
                if model.report.skills.isEmpty, model.hasLoaded {
                    Text("No skills yet. Seed the configuration and complete a block.").foregroundStyle(.secondary)
                }
                ForEach(model.report.skills) { skill in
                    VStack(alignment: .leading, spacing: 4) {
                        HStack {
                            Text(skill.name).font(.body.weight(.medium))
                            Spacer()
                            Text(levelLabel(skill)).font(.caption.monospacedDigit()).foregroundStyle(.secondary)
                        }
                        GeometryReader { geometry in
                            ZStack(alignment: .leading) {
                                RoundedRectangle(cornerRadius: 3).fill(.quaternary)
                                RoundedRectangle(cornerRadius: 3)
                                    .fill(skill.latestLevel == nil ? Color.gray : Color.accentColor)
                                    .frame(width: geometry.size.width * skill.progressFraction)
                            }
                        }
                        .frame(height: 6)
                        if !skill.points.isEmpty {
                            Text(skill.points.map { "\($0.snapshotDate): \($0.estimatedLevel)" }.joined(separator: "  ·  "))
                                .font(.caption2).foregroundStyle(.secondary).lineLimit(2)
                        }
                    }
                    .accessibilityIdentifier("progressSkill-\(skill.slug)")
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private var weeks: some View {
        GroupBox("Minutes per week, focused against planned") {
            VStack(alignment: .leading, spacing: 8) {
                if model.recentWeeks.isEmpty, model.hasLoaded {
                    Text("No study days yet.").foregroundStyle(.secondary)
                }
                ForEach(model.recentWeeks) { week in
                    HStack(spacing: 8) {
                        Text("Week of \(week.weekStart)").font(.caption.monospacedDigit()).frame(width: 130, alignment: .leading)
                        GeometryReader { geometry in
                            ZStack(alignment: .leading) {
                                RoundedRectangle(cornerRadius: 3).fill(.quaternary)
                                RoundedRectangle(cornerRadius: 3).fill(Color.accentColor)
                                    .frame(width: geometry.size.width * week.completion)
                            }
                        }
                        .frame(height: 10)
                        Text("\(week.focusedMinutes) / \(week.plannedMinutes) min · \(week.closedDays)/\(week.studyDays) days closed")
                            .font(.caption.monospacedDigit()).foregroundStyle(.secondary)
                            .frame(width: 220, alignment: .leading)
                    }
                    .accessibilityIdentifier("progressWeek-\(week.weekStart)")
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private var assessmentDays: some View {
        GroupBox("Saturday assessments") {
            VStack(alignment: .leading, spacing: 8) {
                if model.report.assessmentDays.isEmpty, model.hasLoaded {
                    Text("No assessment days yet.").foregroundStyle(.secondary)
                }
                ForEach(model.report.assessmentDays) { day in
                    VStack(alignment: .leading, spacing: 4) {
                        HStack {
                            Text(day.localDate).font(.body.weight(.medium))
                            Text(day.dayStatus).font(.caption).foregroundStyle(.secondary)
                            Spacer()
                            Text(day.averageScore.map { "\($0) avg · \(day.scoredContracts)/\(day.contracts.count) scored" } ?? "not scored yet")
                                .font(.caption.monospacedDigit())
                        }
                        ForEach(day.contracts) { contract in
                            HStack {
                                Text(contract.contractType.replacingOccurrences(of: "_", with: " ")).font(.caption)
                                Text(contract.result.replacingOccurrences(of: "_", with: " ")).font(.caption).foregroundStyle(.secondary)
                                Spacer()
                                Text(contract.averageScore.map { "\($0)" } ?? "–").font(.caption.monospacedDigit())
                            }
                        }
                    }
                    .accessibilityIdentifier("progressAssessmentDay-\(day.studyDayID)")
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private var assessments: some View {
        GroupBox("Last assessments") {
            VStack(alignment: .leading, spacing: 8) {
                if model.report.assessments.isEmpty, model.hasLoaded {
                    Text("No reviewer assessments yet.").foregroundStyle(.secondary)
                }
                ForEach(model.report.assessments) { assessment in
                    VStack(alignment: .leading, spacing: 2) {
                        HStack {
                            Text(assessment.taskStableID).font(.body.weight(.medium))
                            Text(assessment.localDate).font(.caption).foregroundStyle(.secondary)
                            Spacer()
                            Text("\(assessment.averageScore) avg over \(assessment.dimensionCount)")
                                .font(.caption.monospacedDigit())
                        }
                        Text(assessment.verdict).font(.caption).foregroundStyle(.secondary).lineLimit(2)
                    }
                    .accessibilityIdentifier("progressAssessment-\(assessment.reviewID)")
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private var interviews: some View {
        GroupBox("Last interviews") {
            VStack(alignment: .leading, spacing: 8) {
                if model.report.interviews.isEmpty, model.hasLoaded {
                    Text("No interviews recorded yet.").foregroundStyle(.secondary)
                }
                ForEach(model.report.interviews) { interview in
                    HStack {
                        Text("\(interview.company) · \(interview.role)").font(.body.weight(.medium))
                        Text(interview.stage).font(.caption).foregroundStyle(.secondary)
                        Spacer()
                        Text(interview.startsAt, style: .date).font(.caption)
                        Text("\(interview.status) · \(interview.recordingCount) rec").font(.caption).foregroundStyle(.secondary)
                    }
                    .accessibilityIdentifier("progressInterview-\(interview.interviewID)")
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private func levelLabel(_ skill: ProgressSkill) -> String {
        let latest = skill.latestLevel.map { "\($0)" } ?? "no estimate"
        return "\(latest) · baseline \(skill.baseline) · targets \(skill.monthOneTarget) / \(skill.finalTarget)"
    }
}
