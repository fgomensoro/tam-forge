import type { RoadmapImport } from "./api";

interface ValidationIssue {
  code?: string;
  path?: string | null;
  severity?: string;
  message?: string;
}

function numberValue(report: Record<string, unknown>, key: string) {
  return typeof report[key] === "number" ? report[key] : 0;
}

export function ValidationReport({ roadmapImport }: { roadmapImport: RoadmapImport }) {
  const report = roadmapImport.validation_report;
  const accepted = report.accepted === true && roadmapImport.status === "validated";
  const issues = Array.isArray(report.issues) ? report.issues as ValidationIssue[] : [];
  const hash = typeof report.normalized_hash === "string" ? report.normalized_hash : null;

  return (
    <section className={`governance-card validation-card ${accepted ? "is-valid" : "is-invalid"}`} aria-labelledby="validation-title">
      <div className="step-heading">
        <span>02</span>
        <div>
          <p className="section-label">Validation</p>
          <h2 id="validation-title">{accepted ? "Validation passed" : "Validation needs attention"}</h2>
        </div>
      </div>
      {accepted ? (
        <>
          <div className="metric-row" aria-label="Roadmap contents">
            <span>{numberValue(report, "task_count")} tasks</span>
            <span>{numberValue(report, "resource_count")} resources</span>
            <span>{numberValue(report, "exit_criterion_count")} exit criteria</span>
          </div>
          {hash ? (
            <div className="hash-field">
              <span>Normalized content hash</span>
              <code>{hash}</code>
            </div>
          ) : null}
          <p className="field-help">The uploaded snapshot is stored immutably. Approval will create a new version; it never overwrites an earlier roadmap.</p>
        </>
      ) : (
        <ul className="issue-list">
          {issues.map((issue, index) => (
            <li key={`${issue.code ?? "issue"}-${index}`}>
              <strong>{issue.message ?? "The package could not be validated."}</strong>
              {issue.path ? <span>{issue.path}</span> : null}
              {issue.code ? <code>{issue.code}</code> : null}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
