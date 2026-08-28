import { useState } from "react";
import type { RoadmapImport, RoadmapVersion } from "./api";

export function ActivationGate({
  roadmapImport,
  version,
  busy,
  onApprove,
  onRetryMirror,
  onActivate,
}: {
  roadmapImport: RoadmapImport;
  version: RoadmapVersion | null;
  busy: boolean;
  onApprove: () => void;
  onRetryMirror: () => void;
  onActivate: () => void;
}) {
  const [confirmed, setConfirmed] = useState(false);
  const hash = roadmapImport.validation_report.normalized_hash;
  const mirrorReady = version
    ? ["synced", "not_required"].includes(version.mirror_status)
    : false;

  return (
    <section className="governance-card activation-card" aria-labelledby="approval-title">
      <div className="step-heading">
        <span>04</span>
        <div>
          <p className="section-label">Human gate</p>
          <h2 id="approval-title">Approve, mirror, then activate</h2>
        </div>
      </div>
      {!version ? (
        <>
          <label className="confirmation-row">
            <input
              type="checkbox"
              checked={confirmed}
              onChange={(event) => setConfirmed(event.target.checked)}
            />
            <span>I reviewed the validation and semantic changes. Create an immutable roadmap version.</span>
          </label>
          <p className="approval-note">
            Approval record · import #{roadmapImport.id}{typeof hash === "string" ? ` · ${hash.slice(0, 12)}` : ""}
          </p>
          <button className="primary-button" type="button" disabled={!confirmed || busy} onClick={onApprove}>
            {busy ? "Approving…" : "Approve roadmap"}
          </button>
        </>
      ) : (
        <div className="version-gate">
          <p className="success-line">Version {version.version_key} {version.state}</p>
          <dl className="version-metadata">
            <div><dt>Version ID</dt><dd>#{version.id}</dd></div>
            <div><dt>Month</dt><dd>{version.month_number}</dd></div>
            <div><dt>State</dt><dd>{version.state}</dd></div>
          </dl>
          {version.mirror_status === "failed" ? (
            <div className="mirror-status is-failed">
              <p>Private mirror failed: {version.mirror_error_code}</p>
              <button className="secondary-button" type="button" disabled={busy} onClick={onRetryMirror}>Retry private mirror</button>
            </div>
          ) : version.mirror_status === "synced" ? (
            <p className="mirror-status">Private mirror synced · {version.mirror_ref}</p>
          ) : (
            <p className="mirror-status">Private mirror · {version.mirror_status.replaceAll("_", " ")}</p>
          )}
          {version.month_number > 1 ? (
            <p className="gate-note">Month 1 exit review must be complete and marked eligible before Month 2 can activate.</p>
          ) : null}
          {version.state === "active" ? (
            <p className="active-state">Month {version.month_number} is active</p>
          ) : (
            <button className="primary-button" type="button" disabled={busy || !mirrorReady} onClick={onActivate}>
              Activate Month {version.month_number}
            </button>
          )}
        </div>
      )}
    </section>
  );
}
