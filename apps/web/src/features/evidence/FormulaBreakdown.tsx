import type { EvidenceEvent, SnapshotManifestItem } from "./api";

type FormulaEvent = Pick<
  EvidenceEvent,
  | "id"
  | "performance_score"
  | "effective_weight"
  | "skill_impact"
  | "raw_dimension_scores"
  | "mapping_version"
  | "formula_version"
  | "rubric_version"
  | "qualification_reason"
  | "evaluator"
  | "occurred_at"
>;

function readable(value: string) {
  return value.replaceAll("_", " ");
}

function dimensionEntries(scores: Record<string, unknown>) {
  return Object.entries(scores).map(([name, score]) => `${readable(name)} · ${String(score)}`);
}

export function FormulaBreakdown({ manifest, events }: { manifest: SnapshotManifestItem[]; events: FormulaEvent[] }) {
  const eventsById = new Map(events.map((event) => [event.id, event]));

  return (
    <div className="formula-breakdown">
      <header>
        <p className="section-label">Calculation ledger</p>
        <h3>What shaped this estimate</h3>
      </header>
      <ol>
        {manifest.map((item) => {
          const event = eventsById.get(item.event_id);
          return (
            <li key={item.event_id} className={`formula-event ${item.inclusion_code.startsWith("excluded") ? "is-excluded" : ""}`}>
              <div className="formula-event-heading">
                <strong>Evidence #{item.event_id}</strong>
                <span>{readable(item.inclusion_code)}</span>
              </div>
              <div className="formula-values">
                {event ? <>
                  <span>Performance · {event.performance_score} / 4</span>
                  <span>Skill impact · {event.skill_impact}</span>
                  <span>Effective weight · {item.effective_weight}</span>
                  <span>Evaluator · {readable(event.evaluator)}</span>
                </> : <span>Effective weight · {item.effective_weight}</span>}
              </div>
              {event ? <>
                <p className="dimension-title">Raw dimension scores</p>
                <p className="dimension-values">{dimensionEntries(event.raw_dimension_scores).join(" · ") || "None recorded"}</p>
                <p className="lineage-versions">
                  <span>{event.mapping_version}</span><span>{event.formula_version}</span><span>{event.rubric_version}</span>
                </p>
                <p className="qualification-reason">{event.qualification_reason}</p>
              </> : <p className="qualification-reason">This event is outside the current evidence page.</p>}
            </li>
          );
        })}
      </ol>
    </div>
  );
}
