import { useEffect, useState } from "react";
import { ApiProblemError } from "../../api/client";
import { ActivationGate } from "./ActivationGate";
import {
  activateRoadmapVersion,
  approveRoadmapImport,
  listRoadmapVersions,
  retryRoadmapMirror,
  stageRoadmapPackage,
  type RoadmapImport,
  type RoadmapPackage,
  type RoadmapVersion,
} from "./api";
import { PackagePicker } from "./PackagePicker";
import { SemanticDiff, type SemanticRoadmapDiff } from "./SemanticDiff";
import { ValidationReport } from "./ValidationReport";

function messageFor(error: unknown, month?: number) {
  if (error instanceof ApiProblemError && error.status === 409 && month && month > 1) {
    return `Month ${month} remains locked until the previous month exit review is complete and eligible.`;
  }
  if (error instanceof ApiProblemError) return error.message;
  return "The roadmap operation could not be completed. Please try again.";
}

export function RoadmapImportPage() {
  const [selection, setSelection] = useState<RoadmapPackage | null>(null);
  const [roadmapImport, setRoadmapImport] = useState<RoadmapImport | null>(null);
  const [version, setVersion] = useState<RoadmapVersion | null>(null);
  const [versions, setVersions] = useState<RoadmapVersion[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void listRoadmapVersions().then(setVersions).catch(() => setVersions([]));
  }, []);

  const selectPackage = (next: RoadmapPackage) => {
    setSelection(next);
    setRoadmapImport(null);
    setVersion(null);
    setError(null);
  };

  const review = async () => {
    if (!selection) return;
    setBusy(true);
    setError(null);
    try {
      setRoadmapImport(await stageRoadmapPackage(selection));
    } catch (caught) {
      setError(messageFor(caught));
    } finally {
      setBusy(false);
    }
  };

  const approve = async () => {
    if (!roadmapImport) return;
    setBusy(true);
    setError(null);
    try {
      const approved = await approveRoadmapImport(roadmapImport.id);
      setVersion(approved);
      setVersions((current) => [approved, ...current.filter((item) => item.id !== approved.id)]);
    } catch (caught) {
      setError(messageFor(caught));
    } finally {
      setBusy(false);
    }
  };

  const recordVersion = (next: RoadmapVersion) => {
    setVersion((current) => current?.id === next.id ? next : current);
    setVersions((current) => [next, ...current.filter((item) => item.id !== next.id)]);
  };

  const retryMirror = async (target: RoadmapVersion | null) => {
    if (!target) return;
    setBusy(true);
    setError(null);
    try {
      recordVersion(await retryRoadmapMirror(target.id));
    } catch (caught) {
      setError(messageFor(caught));
    } finally {
      setBusy(false);
    }
  };

  const activate = async (target: RoadmapVersion | null) => {
    if (!target) return;
    setBusy(true);
    setError(null);
    try {
      recordVersion(await activateRoadmapVersion(target.id));
    } catch (caught) {
      setError(messageFor(caught, target.month_number));
    } finally {
      setBusy(false);
    }
  };

  const cancel = () => {
    setSelection(null);
    setRoadmapImport(null);
    setVersion(null);
    setError(null);
  };

  const validated = roadmapImport?.status === "validated"
    && roadmapImport.validation_report.accepted === true;

  return (
    <section className="roadmap-page" aria-labelledby="roadmaps-title">
      <header className="page-intro">
        <p className="eyebrow">Governed curriculum</p>
        <h1 id="roadmaps-title">Roadmaps</h1>
        <p>Obsidian remains your authored source. TAM Forge imports a versioned snapshot only after you inspect and approve the changes.</p>
      </header>

      <section className="governance-card" aria-labelledby="package-title">
        <div className="step-heading">
          <span>01</span>
          <div>
            <p className="section-label">Source package</p>
            <h2 id="package-title">Stage a roadmap export</h2>
          </div>
        </div>
        <PackagePicker selection={selection} disabled={busy} onSelect={selectPackage} />
        <div className="button-row">
          <button className="primary-button" type="button" disabled={!selection || busy} onClick={() => void review()}>
            {busy && !roadmapImport ? "Uploading package…" : "Review package"}
          </button>
          {roadmapImport ? <button className="secondary-button" type="button" disabled={busy} onClick={cancel}>Cancel review</button> : null}
        </div>
      </section>

      {busy && !roadmapImport ? <p className="upload-status" role="status">Uploading package…</p> : null}
      {error ? <p className="workflow-error" role="alert">{error}</p> : null}
      {roadmapImport ? <ValidationReport roadmapImport={roadmapImport} /> : null}
      {validated && roadmapImport ? (
        <>
          <SemanticDiff diff={roadmapImport.semantic_diff as SemanticRoadmapDiff} />
          <ActivationGate
            roadmapImport={roadmapImport}
            version={version}
            busy={busy}
            onApprove={() => void approve()}
            onRetryMirror={() => void retryMirror(version)}
            onActivate={() => void activate(version)}
          />
        </>
      ) : null}

      {versions.length ? (
        <section className="version-history" aria-labelledby="version-history-title">
          <p className="section-label">Preserved history</p>
          <h2 id="version-history-title">Roadmap versions</h2>
          <ul>
            {versions.map((item) => (
              <li key={item.id}>
                <strong>{item.version_key}</strong>
                <span>Month {item.month_number}</span>
                <span>{item.state}</span>
                <span>mirror: {item.mirror_status.replaceAll("_", " ")}</span>
                {item.id !== version?.id && item.mirror_status === "failed" ? (
                  <button className="table-action" type="button" disabled={busy} onClick={() => void retryMirror(item)}>Retry mirror for {item.version_key}</button>
                ) : null}
                {item.id !== version?.id
                  && item.state === "approved"
                  && ["synced", "not_required"].includes(item.mirror_status) ? (
                    <button className="table-action" type="button" disabled={busy} onClick={() => void activate(item)}>Activate {item.version_key}</button>
                  ) : null}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </section>
  );
}
