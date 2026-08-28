import type { TodayTask } from "./api";

const blockNames: Record<string, string> = {
  sql: "SQL",
  technical_learning: "Technical learning",
  career_pipeline: "Career pipeline",
  correction_warmup: "Correction warm-up",
  tam_case: "TAM case",
  communication_spoken: "Communication & spoken work",
  daily_close: "Daily close",
  saturday_assessment: "Saturday assessment",
};

function ContractList({ title, items }: { title: string; items: string[] }) {
  return (
    <div>
      <dt>{title}</dt>
      <dd><ul>{items.map((item) => <li key={item}>{item}</li>)}</ul></dd>
    </div>
  );
}

export function TaskCard({ task }: { task: TodayTask }) {
  return (
    <article className="today-task-card">
      <header>
        <span className="task-order">{String(task.roadmap_order).padStart(2, "0")}</span>
        <div>
          <p className="section-label">{blockNames[task.block] ?? task.block.replaceAll("_", " ")}</p>
          <h3>{task.objective}</h3>
        </div>
        <span className={`task-state state-${task.state}`}>{task.state.replaceAll("_", " ")}</span>
      </header>
      <div className="task-meta">
        <span>{task.timebox_minutes} minutes</span>
        <span>Allowed AI role · {task.allowed_ai_role === "none" ? "None" : task.allowed_ai_role}</span>
        <span>{task.required ? "Required" : "Adaptive"}</span>
      </div>
      <dl className="task-contract-grid">
        <ContractList title="Required output" items={task.required_output} />
        <ContractList title="Pass criteria" items={task.pass_criteria} />
        <ContractList title="Evidence" items={task.evidence_requirements} />
        <div>
          <dt>Assigned source</dt>
          <dd>{task.source_references.length ? task.source_references.map((source) => (
            <span key={`${source.path}:${source.anchor ?? ""}`}>{source.path}{source.anchor ? ` · ${source.anchor}` : ""}</span>
          )) : "No source assigned"}</dd>
        </div>
      </dl>
    </article>
  );
}
