import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { FormulaBreakdown } from "./FormulaBreakdown";
import { getSkillEvidence, type SkillSummary } from "./api";

export function SkillEstimateCard({ skill }: { skill: SkillSummary }) {
  const [expanded, setExpanded] = useState(false);
  const snapshot = skill.latest_snapshot;
  const evidence = useQuery({
    queryKey: ["skills", skill.slug, "evidence"],
    queryFn: () => getSkillEvidence(skill.slug),
    enabled: expanded,
  });

  return (
    <article className="skill-estimate-card">
      <header>
        <div>
          <p className="section-label">Demonstrated skill</p>
          <h2>{skill.name}</h2>
        </div>
        <strong className="skill-level">{snapshot ? `${snapshot.estimated_level} / 4` : "Not assessed"}</strong>
      </header>
      {snapshot ? <>
        <div className="estimate-status" aria-label="Estimate context">
          <span>{snapshot.month_one_target_gap} to Month 1 target</span>
          <span>{snapshot.confidence} confidence</span>
          <span>{snapshot.trend} trend</span>
          <span>{snapshot.recency} evidence</span>
        </div>
        <p className="last-strong">Last strong evidence · {snapshot.last_strong_evidence_date ?? "Not yet demonstrated"}</p>
        <button
          className="secondary-button"
          type="button"
          aria-expanded={expanded}
          onClick={() => setExpanded((value) => !value)}
          aria-label={`Inspect ${skill.name} evidence`}
        >
          {expanded ? "Hide evidence" : "Inspect evidence"}
        </button>
        {expanded ? <div className="evidence-detail">
          <dl className="estimate-basis">
            <div><dt>Formula</dt><dd>{snapshot.formula_version}</dd></div>
            <div><dt>Effective weight</dt><dd>{snapshot.total_effective_weight}</dd></div>
            <div><dt>Qualifying events</dt><dd>{snapshot.qualifying_event_count}</dd></div>
            <div><dt>Exercise types</dt><dd>{snapshot.exercise_type_count}</dd></div>
            <div><dt>Baseline gap</dt><dd>{snapshot.baseline_target_gap}</dd></div>
            <div><dt>Month 1 gap</dt><dd>{snapshot.month_one_target_gap}</dd></div>
            <div><dt>Final target gap</dt><dd>{snapshot.final_target_gap}</dd></div>
          </dl>
          <div className="estimate-method">
            <div><strong>Confidence basis</strong><code>{JSON.stringify(snapshot.confidence_basis)}</code></div>
            <div><strong>Trend basis</strong><code>{JSON.stringify(snapshot.trend_basis)}</code></div>
          </div>
          {evidence.isPending ? <p role="status">Loading evidence…</p> : null}
          {evidence.isError ? <p className="workflow-error" role="alert">Evidence could not be loaded. The estimate remains unchanged.</p> : null}
          {evidence.data ? <FormulaBreakdown manifest={snapshot.manifest} events={evidence.data.items} /> : null}
        </div> : null}
      </> : <p className="not-assessed-copy">No qualifying independent evidence yet. Missing evidence is never scored as zero.</p>}
    </article>
  );
}
