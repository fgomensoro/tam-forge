import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getActivityEvidence, type PortfolioScore, type SkillSummary } from "./api";

function readable(value: string) {
  return value.replaceAll("_", " ");
}

export function PortfolioJudgmentCard({ score, skills }: { score: PortfolioScore; skills: SkillSummary[] }) {
  const [expanded, setExpanded] = useState(false);
  const evidence = useQuery({
    queryKey: ["activities", score.activity_id, "evidence"],
    queryFn: () => getActivityEvidence(score.activity_id),
    enabled: expanded,
  });
  const skillNames = new Map(skills.map((skill) => [skill.slug, skill.name]));

  return (
    <article className="portfolio-card">
      <header>
        <div><p className="section-label">Separate judgment metric</p><h2>Portfolio judgment</h2></div>
        <strong>{score.total_score} / 20</strong>
      </header>
      <dl className="portfolio-components">
        {score.components.map((component) => <div key={component.slug}><dt>{readable(component.slug)}</dt><dd>{component.score}</dd></div>)}
      </dl>
      <p className="lineage-versions"><span>{score.formula_version}</span><span>{score.rubric_version}</span></p>
      <p className="portfolio-trend"><strong>Trend basis</strong><code>{JSON.stringify(score.trend_basis)}</code></p>
      <button
        className="secondary-button"
        type="button"
        aria-expanded={expanded}
        aria-label={`Inspect portfolio evidence from activity ${score.activity_id}`}
        onClick={() => setExpanded((value) => !value)}
      >
        {expanded ? "Hide related evidence" : "Inspect related evidence"}
      </button>
      {expanded ? <div className="portfolio-evidence">
        {evidence.isPending ? <p role="status">Loading related evidence…</p> : null}
        {evidence.isError ? <p className="workflow-error" role="alert">Related evidence could not be loaded.</p> : null}
        {evidence.data?.items.map((event) => (
          <article key={event.id}>
            <strong>Related skill evidence · {skillNames.get(event.skill_slug) ?? readable(event.skill_slug)}</strong>
            <span>Performance {event.performance_score} / 4 · effective weight {event.effective_weight}</span>
          </article>
        ))}
      </div> : null}
    </article>
  );
}
