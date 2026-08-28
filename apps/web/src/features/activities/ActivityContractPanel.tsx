import type { ActivityDetail } from "./api";

function Items({ title, values }: { title: string; values: string[] }) {
  return (
    <div>
      <dt>{title}</dt>
      <dd>{values.length ? <ul>{values.map((value) => <li key={value}>{value}</li>)}</ul> : "None"}</dd>
    </div>
  );
}

export function ActivityContractPanel({ activity }: { activity: ActivityDetail }) {
  const contract = activity.task_contract;
  return (
    <aside className="activity-contract" aria-labelledby="activity-contract-title">
      <p className="section-label">Roadmap contract</p>
      <h2 id="activity-contract-title">What good looks like</h2>
      <dl>
        <Items title="Required output" values={contract.required_output} />
        <Items title="Pass criteria" values={contract.pass_criteria} />
        <Items title="Evidence required" values={contract.evidence_requirements} />
        <Items title="Constraints" values={contract.constraints} />
      </dl>
      {contract.procedure.length ? (
        <ol className="procedure-list" aria-label="Assigned procedure">
          {contract.procedure.map((step) => (
            <li key={`${step.phase}-${step.minutes ?? "unbounded"}`}>
              <strong>{step.phase}{step.minutes == null ? "" : ` · ${step.minutes} min`}</strong>
              <span>{step.requirement}</span>
            </li>
          ))}
        </ol>
      ) : null}
    </aside>
  );
}
