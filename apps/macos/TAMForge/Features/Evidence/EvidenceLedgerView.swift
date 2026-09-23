import SwiftUI

struct EvidenceLedgerView: View {
    @ObservedObject var model: EvidenceLedgerModel
    let onOpenActivity: (Int) -> Void
    let onShowAll: () -> Void

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Organic.Space.p24) {
                header
                skillSection
                portfolioSection
                if let activityID = model.inspectedActivityID {
                    activitySection(activityID: activityID)
                }
            }
            .frame(maxWidth: 1008, alignment: .leading)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .accessibilityIdentifier("evidenceLedger")
    }

    // MARK: Header

    private var header: some View {
        VStack(alignment: .leading, spacing: Organic.Space.p14) {
            HStack(alignment: .bottom, spacing: Organic.Space.p20) {
                VStack(alignment: .leading, spacing: 6) {
                    Text("Evidence")
                        .organic(.h1)
                        .accessibilityAddTraits(.isHeader)
                        .accessibilityIdentifier("evidenceTitle")
                    Text("See what you demonstrated, how each estimate was calculated, and the evidence behind it.")
                        .organic(.body, color: Organic.Color.muted)
                        .fixedSize(horizontal: false, vertical: true)
                        .accessibilityIdentifier("evidenceIntro")
                }
                Spacer(minLength: 0)
                HStack(spacing: Organic.Space.p12) {
                    ViewThatFits(in: .horizontal) {
                        filterChips
                        ScrollView(.horizontal, showsIndicators: false) { filterChips }
                    }
                    Button("Refresh", systemImage: "arrow.clockwise") {
                        Task { await model.refresh() }
                    }
                    .keyboardShortcut("r", modifiers: .command)
                    .accessibilityIdentifier("evidenceRefresh")
                }
            }
            Text("Skill estimates use a 4-point scale. Portfolio judgment uses a separate 20-point scale. Self-scores remain separate. Missing evidence is not zero.")
                .organic(.small)
                .fixedSize(horizontal: false, vertical: true)
            if model.isStale {
                OrganicNotice(systemImage: "clock.arrow.circlepath", message: "Showing saved evidence. Refresh to check for updates.")
                    .accessibilityElement(children: .combine)
                    .accessibilityIdentifier("evidenceStaleNotice")
            }
            if let activityID = model.activeActivityID {
                HStack(spacing: Organic.Space.p12) {
                    Text("Activity \(activityID) context").organic(.title)
                    Spacer(minLength: 0)
                    Button("Open activity") { onOpenActivity(activityID) }
                        .accessibilityIdentifier("evidenceOpenActivity")
                    Button("All evidence") {
                        model.showAllEvidence()
                        onShowAll()
                    }
                    .accessibilityIdentifier("evidenceAllActivities")
                }
                .padding(.horizontal, Organic.Space.p16)
                .padding(.vertical, Organic.Space.p12)
                .background(Organic.Color.fill04, in: RoundedRectangle(cornerRadius: Organic.Radius.r20, style: .continuous))
                .accessibilityElement(children: .contain)
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilitySortPriority(3)
    }

    /// "All skills" plus one chip per skill. A chip opens that skill's ledger through
    /// the same model calls as "Inspect evidence"; a skill without a snapshot has no
    /// ledger to open, so its chip is disabled.
    private var filterChips: some View {
        HStack(spacing: 6) {
            chip("All skills", selected: model.selectedSkillSlug == nil) {
                model.dismissSkillInspector()
            }
            ForEach(model.skills) { skill in
                chip(skill.name, selected: model.selectedSkillSlug == skill.slug) {
                    guard model.selectedSkillSlug != skill.slug else { return }
                    Task { await model.inspectSkill(slug: skill.slug) }
                }
                .disabled(skill.snapshot == nil)
            }
        }
    }

    private func chip(_ title: String, selected: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(title)
                .font(Organic.Font.figtree(.semibold, size: 11))
                .tracking(0.22)
                .lineLimit(1)
                .fixedSize()
                .foregroundStyle(selected ? Organic.Color.neutral900 : Organic.Color.neutral300)
                .padding(.horizontal, Organic.Space.p14)
                .padding(.vertical, 6)
                .background(selected ? Organic.Color.accent400 : .clear, in: Capsule(style: .continuous))
                .overlay(Capsule(style: .continuous).strokeBorder(selected ? .clear : Organic.Color.divider, lineWidth: 1))
                .contentShape(Capsule(style: .continuous))
                .modifier(OrganicDisabledDimming())
        }
        .buttonStyle(.plain)
        .accessibilityAddTraits(selected ? .isSelected : [])
    }

    // MARK: Skills

    private var skillSection: some View {
        VStack(alignment: .leading, spacing: Organic.Space.p14) {
            sectionHeader("Demonstrated skills", title: "Skill estimates")
            if model.skillState == .loading {
                ProgressView("Loading skill evidence…").controlSize(.small)
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
                Text("No skills are configured yet.").organic(.small)
            }
            Grid(alignment: .topLeading, horizontalSpacing: Organic.Space.p14, verticalSpacing: Organic.Space.p14) {
                ForEach(skillRows, id: \.first?.slug) { row in
                    GridRow {
                        ForEach(row) { skill in skillCard(skill) }
                        ForEach(row.count..<3, id: \.self) { _ in
                            Color.clear.frame(maxWidth: .infinity).gridCellUnsizedAxes(.vertical)
                        }
                    }
                }
            }
            if let skill = model.selectedSkill, let snapshot = skill.snapshot {
                skillInspector(skill: skill, snapshot: snapshot)
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilitySortPriority(2)
    }

    /// Summary cards sit three to a row, as in the handoff.
    private var skillRows: [[EvidenceSkill]] {
        stride(from: 0, to: model.skills.count, by: 3).map {
            Array(model.skills[$0..<min($0 + 3, model.skills.count)])
        }
    }

    private func skillCard(_ skill: EvidenceSkill) -> some View {
        VStack(alignment: .leading, spacing: Organic.Space.p4) {
            Text(skill.name)
                .organic(.kicker)
                .accessibilityLabel(skill.name)
                .accessibilityIdentifier("evidenceSkillName_\(skill.slug)")
            if let snapshot = skill.snapshot {
                summaryValue("\(snapshot.estimatedLevel) / 4")
                Text("\(readable(snapshot.confidence)) confidence · \(readable(snapshot.trend)) trend · \(readable(snapshot.recency)) evidence")
                    .organic(.caption)
                Text("Baseline gap \(snapshot.baselineTargetGap) · Month 1 gap \(snapshot.monthOneTargetGap) · Final target gap \(snapshot.finalTargetGap)")
                    .organic(.caption)
                Text("Last strong evidence \(snapshot.lastStrongEvidenceDate ?? "not yet demonstrated")")
                    .organic(.caption)
                targets(skill)
                Spacer(minLength: Organic.Space.p8)
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
            } else {
                summaryValue("—", color: Organic.Color.faint)
                    .accessibilityHidden(true)
                Text("Not assessed").organic(.caption)
                targets(skill)
                Text("No qualifying independent evidence yet. Missing evidence is never scored as zero.")
                    .organic(.caption, color: Organic.Color.faint)
            }
        }
        .padding(.vertical, Organic.Space.p20)
        .padding(.horizontal, 22)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(
            RoundedRectangle(cornerRadius: Organic.Radius.r26, style: .continuous)
                .fill(skill.snapshot == nil ? Organic.Color.fill04 : Organic.Color.surface)
        )
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("evidenceSkill_\(skill.slug)")
    }

    private func summaryValue(_ value: String, color: Color = Organic.Color.text) -> some View {
        Text(value)
            .font(Organic.Font.tabular(.semibold, size: 24))
            .tracking(-0.24)
            .foregroundStyle(color)
    }

    private func targets(_ skill: EvidenceSkill) -> some View {
        Text("Baseline \(skill.baseline) · Month 1 \(skill.monthOneTarget) · Final \(skill.finalTarget)")
            .organic(.caption, color: Organic.Color.faint)
    }

    private func skillInspector(skill: EvidenceSkill, snapshot: EvidenceSnapshot) -> some View {
        VStack(alignment: .leading, spacing: Organic.Space.p14) {
            GroupBox {
                VStack(alignment: .leading, spacing: Organic.Space.p12) {
                    HStack(alignment: .firstTextBaseline, spacing: Organic.Space.p12) {
                        Text("Estimate lineage").organic(.title).accessibilityAddTraits(.isHeader)
                        Text(skill.name).organic(.small)
                    }
                    HStack(alignment: .top, spacing: Organic.Space.p40) {
                        Grid(alignment: .leading, horizontalSpacing: Organic.Space.p24, verticalSpacing: 6) {
                            metricRow("Formula", snapshot.formulaVersion)
                            metricRow("Snapshot date", snapshot.snapshotDate)
                            metricRow("Effective weight", snapshot.totalEffectiveWeight)
                            metricRow("Qualifying events", String(snapshot.qualifyingEventCount))
                        }
                        Grid(alignment: .leading, horizontalSpacing: Organic.Space.p24, verticalSpacing: 6) {
                            metricRow("Exercise types", String(snapshot.exerciseTypeCount))
                            metricRow("Baseline gap", snapshot.baselineTargetGap)
                            metricRow("Month 1 gap", snapshot.monthOneTargetGap)
                            metricRow("Final target gap", snapshot.finalTargetGap)
                        }
                    }
                    DisclosureGroup("Confidence basis") { lineageText(snapshot.confidenceBasis) }
                        .accessibilityIdentifier("evidenceConfidenceBasis")
                    DisclosureGroup("Trend basis") { lineageText(snapshot.trendBasis) }
                        .accessibilityIdentifier("evidenceTrendBasis")
                }
            }
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
                    ledger(page.items, manifest: snapshot.manifest)
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
    }

    // MARK: Portfolio

    private var portfolioSection: some View {
        VStack(alignment: .leading, spacing: Organic.Space.p14) {
            sectionHeader("Cross-customer decisions", title: "Portfolio history")
            if model.portfolioState == .loading {
                ProgressView("Loading portfolio history…").controlSize(.small)
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
                Text("No portfolio judgment has been assessed yet.").organic(.small)
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
            VStack(alignment: .leading, spacing: Organic.Space.p12) {
                HStack(alignment: .firstTextBaseline) {
                    VStack(alignment: .leading, spacing: 3) {
                        Text("Portfolio judgment").organic(.title)
                        Text("Activity \(score.activityID) · Attempt \(score.attemptID)").organic(.caption)
                    }
                    Spacer()
                    summaryValue("\(score.totalScore) / 20")
                }
                Grid(alignment: .leading, horizontalSpacing: Organic.Space.p24, verticalSpacing: 5) {
                    ForEach(score.components) { component in
                        metricRow(readable(component.slug), component.score)
                    }
                }
                Text("\(score.formulaVersion) · \(score.rubricVersion)").organic(.caption)
                Text("Scored \(score.scoredAt.formatted(date: .abbreviated, time: .shortened))").organic(.caption)
                DisclosureGroup("Trend basis") { lineageText(score.trendBasis) }
                    .accessibilityIdentifier("evidencePortfolioTrend_\(score.id)")
                Button(model.inspectedActivityID == score.activityID ? "Reload related evidence" : "Inspect related evidence") {
                    Task { await model.inspectActivity(activityID: score.activityID) }
                }
                .accessibilityLabel("Inspect portfolio evidence from activity \(score.activityID)")
                .accessibilityIdentifier("evidenceInspectPortfolio_\(score.id)")
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("evidencePortfolio_\(score.id)")
    }

    // MARK: Activity

    private func activitySection(activityID: Int) -> some View {
        VStack(alignment: .leading, spacing: Organic.Space.p14) {
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
                    ledger(page.items, manifest: [])
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

    // MARK: Ledger

    private func manifest(_ entries: [EvidenceManifestEntry], events: [EvidenceEvent]) -> some View {
        DisclosureGroup("Snapshot manifest · \(entries.count) events") {
            VStack(alignment: .leading, spacing: Organic.Space.p8) {
                ForEach(entries) { entry in
                    let event = events.first { $0.id == entry.eventID }
                    VStack(alignment: .leading, spacing: 2) {
                        Text("Event \(entry.eventID) · \(readable(entry.inclusionCode))").organic(.strong)
                        if let event {
                            Text("Used weight \(entry.usedWeight) · Event weight \(event.effectiveWeight)")
                                .organic(.small, color: Organic.Color.neutral300)
                        } else {
                            Text("Used weight \(entry.usedWeight) · Outside this page; browse older evidence")
                                .organic(.small)
                        }
                    }
                    .accessibilityElement(children: .combine)
                }
            }
            .padding(.top, 6)
        }
        .accessibilityIdentifier("evidenceManifest")
    }

    /// The handoff's ledger table: a column header, then one disclosure row per event.
    /// The Activity column leads because the disclosure's accessibility label is
    /// built from the row text, and the UI tests match it by its "Evidence event N,"
    /// prefix.
    private func ledger(_ events: [EvidenceEvent], manifest: [EvidenceManifestEntry]) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: LedgerColumn.spacing) {
                Text("Activity").frame(maxWidth: .infinity, alignment: .leading)
                Text("When").frame(width: LedgerColumn.when, alignment: .leading)
                Text("Evaluator").frame(width: LedgerColumn.evaluator, alignment: .leading)
                Text("Score").frame(width: LedgerColumn.score, alignment: .leading)
                Text("Weight").frame(width: LedgerColumn.weight, alignment: .leading)
                Text("Counts").frame(width: LedgerColumn.counts, alignment: .leading)
            }
            .organic(.kicker)
            .padding(.leading, LedgerColumn.disclosureInset)
            .padding(.horizontal, Organic.Space.p8)
            .padding(.vertical, Organic.Space.p8)
            .overlay(alignment: .bottom) { Rectangle().fill(Organic.Color.divider).frame(height: 1) }
            .accessibilityHidden(true)
            ForEach(events) { event in
                eventRow(event, manifestEntry: manifest.first { $0.eventID == event.id })
            }
        }
    }

    private func eventRow(_ event: EvidenceEvent, manifestEntry: EvidenceManifestEntry?) -> some View {
        DisclosureGroup {
            VStack(alignment: .leading, spacing: Organic.Space.p8) {
                Text("Activity \(event.activityID) · Attempt \(event.attemptID.map { String($0) } ?? "not linked")")
                Text("Performance \(event.performanceScore) / 4 · Skill impact \(event.skillImpact) · Effective weight \(event.effectiveWeight)")
                Text(event.qualifyingForLevel ? "Qualifies for level · \(readable(event.qualificationReason))" : "Excluded from level · \(readable(event.qualificationReason))")
                Grid(alignment: .leading, horizontalSpacing: Organic.Space.p20, verticalSpacing: 4) {
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
            .organic(.small, color: Organic.Color.neutral300)
            .padding(.top, 6)
            .padding(.bottom, Organic.Space.p12)
        } label: {
            HStack(alignment: .firstTextBaseline, spacing: LedgerColumn.spacing) {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Evidence event \(event.id)")
                        .font(Organic.Font.figtree(.semibold, size: 13))
                        .foregroundStyle(Organic.Color.text)
                    Text("\(model.skillName(for: event.skillSlug) ?? readable(event.skillSlug)) · \(readable(event.exerciseType))")
                        .font(Organic.Font.figtree(.regular, size: 11))
                        .foregroundStyle(Organic.Color.muted)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                Text(event.occurredAt.formatted(date: .abbreviated, time: .shortened))
                    .foregroundStyle(Organic.Color.muted)
                    .frame(width: LedgerColumn.when, alignment: .leading)
                Text(readable(event.evaluator))
                    .frame(width: LedgerColumn.evaluator, alignment: .leading)
                Text(event.performanceScore)
                    .font(Organic.Font.tabular(.regular, size: 13))
                    .frame(width: LedgerColumn.score, alignment: .leading)
                Text(event.effectiveWeight)
                    .font(Organic.Font.tabular(.regular, size: 13))
                    .frame(width: LedgerColumn.weight, alignment: .leading)
                countsTag(event, manifestEntry: manifestEntry)
                    .frame(width: LedgerColumn.counts, alignment: .leading)
            }
            .font(Organic.Font.figtree(.regular, size: 13))
            .foregroundStyle(Organic.Color.body)
            .lineLimit(1)
            .padding(.vertical, Organic.Space.p8)
            .accessibilityIdentifier("evidenceEvent_\(event.id)")
        }
        .padding(.horizontal, Organic.Space.p8)
        .modifier(EvidenceRowHover())
        .overlay(alignment: .bottom) { Rectangle().fill(Organic.Color.fill08).frame(height: 1) }
    }

    /// Qualifies: sage. Discounted by the snapshot manifest: accent. Anything else
    /// (excluded, pending): neutral.
    private func countsTag(_ event: EvidenceEvent, manifestEntry: EvidenceManifestEntry?) -> OrganicTag {
        if let code = manifestEntry?.inclusionCode, code.hasPrefix("discounted") {
            return OrganicTag(text: readable(code), background: Organic.Color.accentOn, foreground: Organic.Color.accent300)
        }
        if event.qualifyingForLevel {
            return OrganicTag(text: "qualifies", background: Organic.Color.accent2.opacity(0.28), foreground: Organic.Color.accent2_200)
        }
        return OrganicTag(text: readable(event.qualificationReason))
    }

    // MARK: Shared parts

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
        if state == .loading { ProgressView("Loading evidence…").controlSize(.small) }
        if state == .failed {
            sectionError(
                error ?? "Evidence could not be loaded.",
                retryID: retryID,
                retryLabel: retryLabel,
                retry: retry
            )
        }
        if state == .empty { Text(empty).organic(.small) }
        if state == .content || state == .failed || state == .loading { content() }
    }

    private func sectionError(
        _ message: String,
        retryID: String,
        retryLabel: String,
        retry: @escaping @MainActor () async -> Void
    ) -> some View {
        OrganicNotice(systemImage: "exclamationmark.triangle", message: message) {
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
        HStack(spacing: Organic.Space.p8) {
            if hasOlder {
                Button("Load older") { Task { await older() } }
                    .buttonStyle(.organicSecondary)
                    .accessibilityLabel(olderLabel)
                    .accessibilityIdentifier(olderID)
            }
            if !newest {
                Button("Newest") { Task { await newestAction() } }
                    .buttonStyle(.organicSecondary)
                    .accessibilityLabel(newestLabel)
                    .accessibilityIdentifier(newestID)
            }
        }
    }

    private func sectionHeader(_ eyebrow: String, title: String) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(eyebrow).organic(.kicker)
            Text(title).organic(.h2).accessibilityAddTraits(.isHeader)
        }
    }

    private func metricRow(_ label: String, _ value: String) -> some View {
        GridRow {
            Text(label).organic(.small)
            Text(value)
                .font(Organic.Font.tabular(.regular, size: 13))
                .foregroundStyle(Organic.Color.body)
        }
    }

    private func lineageText(_ value: [String: ActivityJSONValue]) -> some View {
        Text(EvidenceLineageText.render(.object(value)))
            .organic(.mono)
            .textSelection(.enabled)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.top, 6)
    }

    private func readable(_ value: String) -> String {
        value.replacingOccurrences(of: "_", with: " ")
    }
}

/// Ledger column widths, from the handoff's table at the 1008 pt content width.
private enum LedgerColumn {
    static let spacing: CGFloat = 12
    static let when: CGFloat = 132
    static let evaluator: CGFloat = 104
    static let score: CGFloat = 44
    static let weight: CGFloat = 72
    static let counts: CGFloat = 150
    /// Width of the system disclosure triangle, so the header lines up with the rows.
    static let disclosureInset: CGFloat = 20
}

/// Table row hover: neutral-100 at 4 %.
private struct EvidenceRowHover: ViewModifier {
    @State private var hovering = false

    func body(content: Content) -> some View {
        content
            .background(hovering ? Organic.Color.fill04 : .clear, in: Rectangle())
            .onHover { hovering = $0 }
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
