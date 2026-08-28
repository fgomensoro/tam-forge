type JsonValue = unknown;

interface FieldChange {
  name: string;
  before: JsonValue;
  after: JsonValue;
}

interface EntityChange {
  key: string;
  status: "added" | "removed" | "changed" | "unchanged";
  fields: FieldChange[];
}

interface DiffSection {
  entries: EntityChange[];
}

export interface SemanticRoadmapDiff {
  summary?: Record<string, number>;
  tasks?: DiffSection;
  pass_contracts?: DiffSection;
  resources?: DiffSection;
  exit_criteria?: DiffSection;
}

const fieldLabels: Record<string, string> = {
  objective: "Assignment",
  timebox_minutes: "Timebox",
  required: "Required coverage",
  required_output: "Required output",
  pass_criteria: "Pass criteria",
  evidence_requirements: "Evidence requirements",
  allowed_ai_role: "Allowed AI role",
};

function displayValue(value: unknown) {
  if (value === null || value === undefined) return "None";
  if (Array.isArray(value)) return value.join(" · ");
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function ChangeSection({ title, section }: { title: string; section?: DiffSection }) {
  const entries = (section?.entries ?? []).filter((entry) => entry.status !== "unchanged");
  if (!entries.length) return null;
  return (
    <section className="diff-section">
      <h3>{title}</h3>
      <div className="diff-entries">
        {entries.map((entry) => (
          <article className="diff-entry" key={`${title}-${entry.key}`}>
            <div className="diff-entry-title">
              <code>{entry.key}</code>
              <span className={`status-chip status-${entry.status}`}>{entry.status}</span>
            </div>
            {entry.fields.map((field) => (
              <div className="field-change" data-testid={`change-${field.name}`} key={field.name}>
                <strong>{fieldLabels[field.name] ?? field.name.replaceAll("_", " ")}</strong>
                <span className="before-value">{displayValue(field.before)}</span>
                <span className="change-arrow" aria-hidden="true">→</span>
                <span className="after-value">{displayValue(field.after)}</span>
              </div>
            ))}
          </article>
        ))}
      </div>
    </section>
  );
}

export function SemanticDiff({ diff }: { diff: SemanticRoadmapDiff }) {
  const summary = diff.summary ?? {};
  const counts = ["added", "removed", "changed", "unchanged"] as const;

  return (
    <section className="governance-card" aria-labelledby="diff-title">
      <div className="step-heading">
        <span>03</span>
        <div>
          <p className="section-label">Semantic comparison</p>
          <h2 id="diff-title">What this roadmap changes</h2>
        </div>
      </div>
      <div className="diff-summary">
        {counts.map((status) => <span key={status}>{summary[status] ?? 0} {status}</span>)}
      </div>
      <ChangeSection title="Assignments and time" section={diff.tasks} />
      <ChangeSection title="Pass criteria" section={diff.pass_contracts} />
      <ChangeSection title="Assigned resources" section={diff.resources} />
      <ChangeSection title="Month exit criteria" section={diff.exit_criteria} />
      {(summary.added ?? 0) + (summary.removed ?? 0) + (summary.changed ?? 0) === 0 ? (
        <p className="field-help">No learning requirement changes were detected.</p>
      ) : null}
    </section>
  );
}
