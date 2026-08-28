import { useQuery } from "@tanstack/react-query";
import { getPortfolioHistory, getSkills } from "./api";
import { PortfolioJudgmentCard } from "./PortfolioJudgmentCard";
import { SkillEstimateCard } from "./SkillEstimateCard";

export function EvidenceLedgerPage() {
  const skills = useQuery({ queryKey: ["skills"], queryFn: getSkills });
  const portfolio = useQuery({ queryKey: ["portfolio-judgment"], queryFn: getPortfolioHistory });

  return (
    <section className="evidence-page" aria-labelledby="evidence-title">
      <header className="page-intro evidence-intro">
        <p className="eyebrow">Measured performance</p>
        <h1 id="evidence-title">Evidence</h1>
        <p>See what you demonstrated, how each estimate was calculated, and what remains to reach the next target.</p>
        <p className="scoring-boundary">Self-scores remain separate from AI and assessment scores. Missing evidence is not zero.</p>
      </header>

      {skills.isPending ? <p role="status">Loading skill evidence…</p> : null}
      {skills.isError ? <p className="workflow-error" role="alert">Skill evidence could not be loaded. Historical evidence is unchanged.</p> : null}
      {skills.data ? <section className="skill-ledger" aria-label="Skill estimates">
        {skills.data.items.map((skill) => <SkillEstimateCard key={skill.slug} skill={skill} />)}
      </section> : null}

      <section className="portfolio-section" aria-labelledby="portfolio-title">
        <header><p className="section-label">Cross-customer decisions</p><h2 id="portfolio-title">Portfolio history</h2></header>
        {portfolio.isPending ? <p role="status">Loading portfolio evidence…</p> : null}
        {portfolio.isError ? <p className="workflow-error" role="alert">Portfolio evidence could not be loaded.</p> : null}
        {portfolio.data && skills.data ? portfolio.data.items.map((score) => <PortfolioJudgmentCard key={score.id} score={score} skills={skills.data.items} />) : null}
        {portfolio.data?.items.length === 0 ? <p>No portfolio judgment has been assessed yet.</p> : null}
      </section>
    </section>
  );
}
