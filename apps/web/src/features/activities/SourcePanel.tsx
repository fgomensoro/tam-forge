import type { ActivityDetail } from "./api";

export function SourcePanel({ activity, busy, onVisibility }: { activity: ActivityDetail; busy: boolean; onVisibility: (hidden: boolean) => void }) {
  const reading = activity.task_contract.block === "technical_learning";
  return (
    <section className={`source-panel ${activity.source_hidden ? "is-hidden" : ""}`} aria-labelledby="source-title">
      <header>
        <div><p className="section-label">Assigned source</p><h2 id="source-title">{activity.source_hidden ? "Source hidden" : "Source available"}</h2></div>
        <button className="secondary-button" type="button" disabled={busy || !["ready", "active", "paused"].includes(activity.state)} onClick={() => onVisibility(!activity.source_hidden)}>
          {activity.source_hidden ? "Reveal source" : "Hide source"}
        </button>
      </header>
      {activity.source_hidden ? <p className="closed-source-note">Closed-source mode is active. Recall from memory before reopening the assigned material.</p> : (
        <ul>{activity.task_contract.source_references.map((source) => <li key={`${source.path}:${source.anchor ?? ""}`}>{source.path}{source.anchor ? ` · ${source.anchor}` : ""}</li>)}</ul>
      )}
      {reading && !activity.source_hidden ? <p className="source-requirement">Hide the assigned source before committing recall.</p> : null}
    </section>
  );
}
