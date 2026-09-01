import SwiftUI

struct EvidenceLedgerView: View {
    @ObservedObject var model: EvidenceLedgerModel
    let onOpenActivity: (Int) -> Void
    let onShowAll: () -> Void

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                header
                skillSection
                portfolioSection
                if let activityID = model.inspectedActivityID {
                    activitySection(activityID: activityID)
                }
            }
            .frame(maxWidth: 980, alignment: .leading)
            .padding(24)
        }
        .accessibilityIdentifier("evidenceLedger")
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .top, spacing: 16) {
                VStack(alignment: .leading, spacing: 4) {
                    Text("Measured performance")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                    Text("Evidence")
                        .font(.largeTitle)
                        .bold()
                        .accessibilityAddTraits(.isHeader)
                        .accessibilityIdentifier("evidenceTitle")
                }
                Spacer()
                Button("Refresh", systemImage: "arrow.clockwise") {
                    Task { await model.refresh() }
                }
                .keyboardShortcut("r", modifiers: .command)
                .accessibilityIdentifier("evidenceRefresh")
            }
            Text("See what you demonstrated, how each estimate was calculated, and the evidence behind it.")
                .accessibilityIdentifier("evidenceIntro")
            Text("Skill estimates use a 4-point scale. Portfolio judgment uses a separate 20-point scale. Self-scores remain separate. Missing evidence is not zero.")
                .font(.subheadline)
                .foregroundStyle(.secondary)
            if model.isStale {
                Label("Showing saved evidence. Refresh to check for updates.", systemImage: "clock.arrow.circlepath")
                    .foregroundStyle(.orange)
                    .accessibilityIdentifier("evidenceStaleNotice")
            }
            if let activityID = model.activeActivityID {
                HStack(spacing: 12) {
                    Text("Activity \(activityID) context").font(.headline)
                    Button("Open activity") { onOpenActivity(activityID) }
                        .accessibilityIdentifier("evidenceOpenActivity")
                    Button("All evidence") {
                        model.showAllEvidence()
                        onShowAll()
                    }
                    .accessibilityIdentifier("evidenceAllActivities")
                }
                .padding(12)
                .background(.quaternary, in: RoundedRectangle(cornerRadius: 10))
                .accessibilityElement(children: .contain)
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilitySortPriority(3)
    }

    private var skillSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            sectionHeader("Demonstrated skills", title: "Skill estimates")
            if model.skillState == .loading {
                ProgressView("Loading skill evidence…")
            }
            if model.skillState == .failed {
                sectionError(
                    model.skillError ?? "Skill evidence could not be loaded.",
                    retryID: "evidenceRetrySkills",
                    retryLabel: "Retry skill estimates"
                ) {
                    await model.retrySkills()
                }
            }
            if model.skillState == .empty {
                Text("No skills are configured yet.").foregroundStyle(.secondary)
            }
            ForEach(model.skills) { skill in
                skillCard(skill)
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilitySortPriority(2)
    }

    private func skillCard(_ skill: EvidenceSkill) -> some View {
        GroupBox {
            VStack(alignment: .leading, spacing: 12) {
                HStack(alignment: .firstTextBaseline, spacing: 16) {
                    VStack(alignment: .leading, spacing: 3) {
                        Text(skill.name)
                            .font(.title3)
                            .bold()
                            .accessibilityIdentifier("evidenceSkillName_\(skill.slug)")
                        Text("Baseline \(skill.baseline) · Month 1 \(skill.monthOneTarget) · Final \(skill.finalTarget)")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    Spacer()
                    Text(skill.snapshot.map { "\($0.estimatedLevel) / 4" } ?? "Not assessed")
                        .font(.title3)
                        .bold()
                        .monospacedDigit()
                }
                if let snapshot = skill.snapshot {
                    Text("\(readable(snapshot.confidence)) confidence · \(readable(snapshot.trend)) trend · \(readable(snapshot.recency)) evidence")
                        .font(.subheadline)
                    Text("Baseline gap \(snapshot.baselineTargetGap) · Month 1 gap \(snapshot.monthOneTargetGap) · Final target gap \(snapshot.finalTargetGap)")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                    Text("Last strong evidence \(snapshot.lastStrongEvidenceDate ?? "not yet demonstrated")")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                    Button(model.selectedSkillSlug == skill.slug ? "Hide evidence" : "Inspect evidence") {
                        if model.selectedSkillSlug == skill.slug {
                            model.dismissSkillInspector()
                        } else {
                            Task { await model.inspectSkill(slug: skill.slug) }
                        }
                    }
                    .accessibilityLabel(model.selectedSkillSlug == skill.slug ? "Hide \(skill.name) evidence" : "Inspect \(skill.name) evidence")
                    .accessibilityValue(model.selectedSkillSlug == skill.slug ? "Expanded" : "Collapsed")
                    .accessibilityIdentifier("evidenceInspectSkill_\(skill.slug)")
                    if model.selectedSkillSlug == skill.slug {
                        skillInspector(snapshot: snapshot)
                    }
                } else {
                    Text("No qualifying independent evidence yet. Missing evidence is never scored as zero.")
                        .foregroundStyle(.secondary)
                }
            }
            .padding(.vertical, 4)
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("evidenceSkill_\(skill.slug)")
    }

    private func skillInspector(snapshot: EvidenceSnapshot) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Divider()
            Text("Estimate lineage").font(.headline).accessibilityAddTraits(.isHeader)
            Grid(alignment: .leading, horizontalSpacing: 24, verticalSpacing: 6) {
                metricRow("Formula", snapshot.formulaVersion)
                metricRow("Snapshot date", snapshot.snapshotDate)
                metricRow("Effective weight", snapshot.totalEffectiveWeight)
                metricRow("Qualifying events", String(snapshot.qualifyingEventCount))
                metricRow("Exercise types", String(snapshot.exerciseTypeCount))
                metricRow("Baseline gap", snapshot.baselineTargetGap)
                metricRow("Month 1 gap", snapshot.monthOneTargetGap)
                metricRow("Final target gap", snapshot.finalTargetGap)
            }
            DisclosureGroup("Confidence basis") { lineageText(snapshot.confidenceBasis) }
                .accessibilityIdentifier("evidenceConfidenceBasis")
            DisclosureGroup("Trend basis") { lineageText(snapshot.trendBasis) }
                .accessibilityIdentifier("evidenceTrendBasis")
            inspectorContent(
                state: model.skillInspectorState,
                error: model.skillInspectorError,
                empty: "No evidence events are available for this skill.",
                retryID: "evidenceRetrySkillInspector",
                retryLabel: "Retry selected skill evidence",
                retry: { await model.retrySkillEvidence() }
            ) {
                if let page = model.skillPage {
                    manifest(snapshot.manifest, events: page.items)
                    ForEach(page.items) { event in eventCard(event) }
                    pageControls(
                        newest: model.isNewestSkillPage,
                        hasOlder: page.nextCursor != nil,
                        olderID: "evidenceSkillOlder",
                        newestID: "evidenceSkillNewest",
                        olderLabel: "Older skill evidence",
                        newestLabel: "Newest skill evidence",
                        older: { await model.loadOlderSkillEvidence() },
                        newestAction: { await model.loadNewestSkillEvidence() }
                    )
                }
            }
        }
        .padding(12)
        .background(.quinary, in: RoundedRectangle(cornerRadius: 8))
    }

    private var portfolioSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            sectionHeader("Cross-customer decisions", title: "Portfolio history")
            if model.portfolioState == .loading {
                ProgressView("Loading portfolio history…")
            }
            if model.portfolioState == .failed {
                sectionError(
                    model.portfolioError ?? "Portfolio history could not be loaded.",
                    retryID: "evidenceRetryPortfolio",
                    retryLabel: "Retry portfolio history"
                ) {
                    await model.retryPortfolio()
                }
            }
            if model.portfolioState == .empty {
                Text("No portfolio judgment has been assessed yet.").foregroundStyle(.secondary)
            }
            if let page = model.portfolioPage {
                ForEach(page.items) { score in portfolioCard(score) }
                pageControls(
                    newest: model.isNewestPortfolioPage,
                    hasOlder: page.nextCursor != nil,
                    olderID: "evidencePortfolioOlder",
                    newestID: "evidencePortfolioNewest",
                    olderLabel: "Older portfolio history",
                    newestLabel: "Newest portfolio history",
                    older: { await model.loadOlderPortfolio() },
                    newestAction: { await model.loadNewestPortfolio() }
                )
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilitySortPriority(1)
    }

    private func portfolioCard(_ score: EvidencePortfolioScore) -> some View {
        GroupBox {
            VStack(alignment: .leading, spacing: 10) {
                HStack(alignment: .firstTextBaseline) {
                    VStack(alignment: .leading, spacing: 3) {
                        Text("Portfolio judgment").font(.title3).bold()
                        Text("Activity \(score.activityID) · Attempt \(score.attemptID)")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    Spacer()
                    Text("\(score.totalScore) / 20")
                        .font(.title3)
                        .bold()
                        .monospacedDigit()
                }
                Grid(alignment: .leading, horizontalSpacing: 24, verticalSpacing: 5) {
                    ForEach(score.components) { component in
                        metricRow(readable(component.slug), component.score)
                    }
                }
                Text("\(score.formulaVersion) · \(score.rubricVersion)")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Text("Scored \(score.scoredAt.formatted(date: .abbreviated, time: .shortened))")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                DisclosureGroup("Trend basis") { lineageText(score.trendBasis) }
                    .accessibilityIdentifier("evidencePortfolioTrend_\(score.id)")
                Button(model.inspectedActivityID == score.activityID ? "Reload related evidence" : "Inspect related evidence") {
                    Task { await model.inspectActivity(activityID: score.activityID) }
                }
                .accessibilityLabel("Inspect portfolio evidence from activity \(score.activityID)")
                .accessibilityIdentifier("evidenceInspectPortfolio_\(score.id)")
            }
            .padding(.vertical, 4)
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("evidencePortfolio_\(score.id)")
    }

    private func activitySection(activityID: Int) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(alignment: .bottom) {
                sectionHeader("Related lineage", title: "Activity \(activityID) evidence")
                    .accessibilityIdentifier("evidenceActivityHistory")
                Spacer()
                Button("All evidence") {
                    model.showAllEvidence()
                    onShowAll()
                }
                .accessibilityIdentifier("evidenceAllActivitiesFromInspector")
            }
            inspectorContent(
                state: model.activityState,
                error: model.activityInspectorError,
                empty: "No qualifying evidence is recorded for this activity.",
                retryID: "evidenceRetryActivityInspector",
                retryLabel: "Retry activity evidence",
                retry: { await model.retryActivityEvidence() }
            ) {
                if let page = model.activityPage {
                    ForEach(page.items) { event in eventCard(event) }
                    pageControls(
                        newest: model.isNewestActivityPage,
                        hasOlder: page.nextCursor != nil,
                        olderID: "evidenceActivityOlder",
                        newestID: "evidenceActivityNewest",
                        olderLabel: "Older activity evidence",
                        newestLabel: "Newest activity evidence",
                        older: { await model.loadOlderActivityEvidence() },
                        newestAction: { await model.loadNewestActivityEvidence() }
                    )
                }
            }
        }
        .accessibilityElement(children: .contain)
    }

    private func manifest(_ entries: [EvidenceManifestEntry], events: [EvidenceEvent]) -> some View {
        DisclosureGroup("Snapshot manifest · \(entries.count) events") {
            VStack(alignment: .leading, spacing: 8) {
                ForEach(entries) { entry in
                    let event = events.first { $0.id == entry.eventID }
                    VStack(alignment: .leading, spacing: 2) {
                        Text("Event \(entry.eventID) · \(readable(entry.inclusionCode))").bold()
                        if let event {
                            Text("Used weight \(entry.usedWeight) · Event weight \(event.effectiveWeight)")
                        } else {
                            Text("Used weight \(entry.usedWeight) · Outside this page; browse older evidence")
                                .foregroundStyle(.secondary)
                        }
                    }
                    .accessibilityElement(children: .combine)
                }
            }
            .padding(.top, 6)
        }
        .accessibilityIdentifier("evidenceManifest")
    }

    private func eventCard(_ event: EvidenceEvent) -> some View {
        DisclosureGroup {
            VStack(alignment: .leading, spacing: 8) {
                Text("Activity \(event.activityID) · Attempt \(event.attemptID.map { String($0) } ?? "not linked")")
                Text("Performance \(event.performanceScore) / 4 · Skill impact \(event.skillImpact) · Effective weight \(event.effectiveWeight)")
                Text(event.qualifyingForLevel ? "Qualifies for level · \(readable(event.qualificationReason))" : "Excluded from level · \(readable(event.qualificationReason))")
                Grid(alignment: .leading, horizontalSpacing: 20, verticalSpacing: 4) {
                    metricRow("Exercise", readable(event.exerciseType))
                    metricRow("Mapping", event.mappingVersion)
                    metricRow("Formula", event.formulaVersion)
                    metricRow("Rubric", "\(event.rubricSlug) · \(event.rubricVersion)")
                    metricRow("Evaluator", readable(event.evaluator))
                    metricRow("Practice", readable(event.practiceMode))
                    metricRow("Assistance", readable(event.assistance))
                    metricRow("Difficulty", readable(event.difficulty))
                }
                DisclosureGroup("Raw dimension scores") {
                    lineageText(event.rawDimensionScores)
                }
                .accessibilityIdentifier("evidenceRawDimensions_\(event.id)")
            }
            .padding(.top, 6)
        } label: {
            VStack(alignment: .leading, spacing: 2) {
                Text("Evidence event \(event.id)").bold()
                Text("\(model.skillName(for: event.skillSlug) ?? readable(event.skillSlug)) · \(event.occurredAt.formatted(date: .abbreviated, time: .shortened))")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            .accessibilityIdentifier("evidenceEvent_\(event.id)")
        }
    }

    @ViewBuilder
    private func inspectorContent<Content: View>(
        state: EvidenceLoadState,
        error: String?,
        empty: String,
        retryID: String,
        retryLabel: String,
        retry: @escaping @MainActor () async -> Void,
        @ViewBuilder content: () -> Content
    ) -> some View {
        if state == .loading { ProgressView("Loading evidence…") }
        if state == .failed {
            sectionError(
                error ?? "Evidence could not be loaded.",
                retryID: retryID,
                retryLabel: retryLabel,
                retry: retry
            )
        }
        if state == .empty { Text(empty).foregroundStyle(.secondary) }
        if state == .content || state == .failed || state == .loading { content() }
    }

    private func sectionError(
        _ message: String,
        retryID: String,
        retryLabel: String,
        retry: @escaping @MainActor () async -> Void
    ) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 10) {
            Label(message, systemImage: "exclamationmark.triangle")
                .foregroundStyle(.orange)
            Button("Retry") { Task { await retry() } }
                .accessibilityLabel(retryLabel)
                .accessibilityIdentifier(retryID)
        }
    }

    private func pageControls(
        newest: Bool,
        hasOlder: Bool,
        olderID: String,
        newestID: String,
        olderLabel: String,
        newestLabel: String,
        older: @escaping @MainActor () async -> Void,
        newestAction: @escaping @MainActor () async -> Void
    ) -> some View {
        HStack(spacing: 10) {
            if hasOlder {
                Button("Older") { Task { await older() } }
                    .accessibilityLabel(olderLabel)
                    .accessibilityIdentifier(olderID)
            }
            if !newest {
                Button("Newest") { Task { await newestAction() } }
                    .accessibilityLabel(newestLabel)
                    .accessibilityIdentifier(newestID)
            }
        }
    }

    private func sectionHeader(_ eyebrow: String, title: String) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(eyebrow).font(.caption).foregroundStyle(.secondary)
            Text(title).font(.title2).bold().accessibilityAddTraits(.isHeader)
        }
    }

    private func metricRow(_ label: String, _ value: String) -> some View {
        GridRow {
            Text(label).foregroundStyle(.secondary)
            Text(value).monospacedDigit()
        }
    }

    private func lineageText(_ value: [String: ActivityJSONValue]) -> some View {
        Text(EvidenceLineageText.render(.object(value)))
            .font(.system(.caption, design: .monospaced))
            .textSelection(.enabled)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.top, 6)
    }

    private func readable(_ value: String) -> String {
        value.replacingOccurrences(of: "_", with: " ")
    }
}

enum EvidenceLineageText {
    private static let labels = [
        "basis_code": "Basis",
        "availability": "Availability",
        "context": "Context",
        "dimension_score_id": "Dimension score",
        "dimension_slug": "Dimension",
        "event_ids": "Evidence events",
        "observations": "Observations",
        "qualifying_events": "Qualifying events",
        "score": "Score",
        "scores": "Scores",
        "schema_version": "Schema version",
        "weight": "Weight",
    ]

    static func render(_ value: ActivityJSONValue) -> String {
        render(value, root: true)
    }

    private static func render(_ value: ActivityJSONValue, root: Bool) -> String {
        switch value {
        case let .string(value): return String(reflecting: value)
        case let .integer(value): return String(value)
        case let .decimal(value): return String(value)
        case let .boolean(value): return value ? "true" : "false"
        case .null: return "null"
        case let .array(values):
            return "[" + values.map { render($0, root: false) }.joined(separator: ", ") + "]"
        case let .object(values):
            let contents = values.keys.sorted().map { key in
                "\(labels[key] ?? String(reflecting: key)): \(render(values[key]!, root: false))"
            }.joined(separator: root ? "\n" : ", ")
            return root ? contents : "{\(contents)}"
        }
    }
}
