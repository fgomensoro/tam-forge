import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { ActivityContractPanel } from "./ActivityContractPanel";
import { ArtifactUploader } from "./ArtifactUploader";
import {
  commitOutput,
  getActivity,
  setSourceVisibility,
  submitSelfReview,
  type ActivityDetail,
  type ActivityResponse,
  type ArtifactReference,
  type SelfReviewInput,
} from "./api";
import { SelfReviewForm } from "./SelfReviewForm";
import { SourcePanel } from "./SourcePanel";
import { emptyDraft, isComplete, outputPayload, UniversalOutputEditor, type OutputDraft } from "./UniversalOutputEditor";
import { useResumableTimer } from "./useResumableTimer";

const activityKey = (id: number) => ["activity", id] as const;
const editableStates = new Set(["ready", "active", "paused"]);

interface WorkingState {
  draft: OutputDraft;
  artifactRefs: ArtifactReference[];
  artifactNames: string[];
}

function readWorkingState(activity: ActivityDetail): WorkingState {
  try {
    const saved = localStorage.getItem(`tamforge:activity:${activity.id}:draft`);
    if (saved) {
      const parsed = JSON.parse(saved) as Partial<WorkingState> & Partial<OutputDraft>;
      if (parsed.draft) {
        return {
          draft: { ...emptyDraft(activity), ...parsed.draft },
          artifactRefs: parsed.artifactRefs ?? [],
          artifactNames: parsed.artifactNames ?? [],
        };
      }
      return { draft: { ...emptyDraft(activity), ...parsed as OutputDraft }, artifactRefs: [], artifactNames: [] };
    }
  } catch {
    // Invalid browser-local draft data is ignored without touching server evidence.
  }
  return { draft: emptyDraft(activity), artifactRefs: [], artifactNames: [] };
}

function mergedDetail(current: ActivityDetail, response: ActivityResponse): ActivityDetail {
  return { ...current, ...response, task_contract: current.task_contract };
}

function ReadOnlyAttempt({ activity }: { activity: ActivityDetail }) {
  const output = activity.committed_output?.contract_payload.output as Record<string, unknown> | undefined;
  return (
    <section className="committed-attempt" aria-labelledby="committed-title">
      <p className="section-label">Immutable evidence</p>
      <h2 id="committed-title">Attempt A is committed and read-only.</h2>
      <p>Any future correction is stored as a distinct Attempt B linked to this evidence.</p>
      <dl>{output ? Object.entries(output).map(([name, value]) => <div key={name}><dt>{name.replaceAll("_", " ")}</dt><dd>{Array.isArray(value) ? value.join(" · ") : String(value)}</dd></div>) : null}</dl>
      <code>{activity.committed_output?.commitment_sha256}</code>
    </section>
  );
}

function LoadedActivity({ initial }: { initial: ActivityDetail }) {
  const queryClient = useQueryClient();
  const [restored] = useState<WorkingState>(() => readWorkingState(initial));
  const [draft, setDraft] = useState<OutputDraft>(restored.draft);
  const [savedAt, setSavedAt] = useState<Date | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [artifactRefs, setArtifactRefs] = useState<ArtifactReference[]>(restored.artifactRefs);
  const [artifactNames, setArtifactNames] = useState<string[]>(restored.artifactNames);
  const activity = initial;

  const update = (response: ActivityResponse) => {
    queryClient.setQueryData<ActivityDetail>(activityKey(activity.id), (current) => current ? mergedDetail(current, response) : initial);
  };
  const timer = useResumableTimer({ activity, onChange: update });

  useEffect(() => {
    if (!editableStates.has(activity.state)) return;
    const timeout = window.setTimeout(() => {
      localStorage.setItem(`tamforge:activity:${activity.id}:draft`, JSON.stringify({
        schemaVersion: 1,
        draft,
        artifactRefs,
        artifactNames,
      }));
      setSavedAt(new Date());
    }, 450);
    return () => window.clearTimeout(timeout);
  }, [activity.id, activity.state, artifactNames, artifactRefs, draft]);

  const run = async (action: () => Promise<void>) => {
    setBusy(true); setError(null);
    try { await action(); }
    catch { setError("That action could not be saved. Your existing evidence and local draft are unchanged."); }
    finally { setBusy(false); }
  };

  const refresh = async () => { await queryClient.invalidateQueries({ queryKey: activityKey(activity.id) }); };
  const commit = () => run(async () => {
    await commitOutput(activity.id, activity.optimistic_version, timer.nextSequence(), outputPayload(draft, activity), artifactRefs);
    localStorage.removeItem(`tamforge:activity:${activity.id}:draft`);
    await refresh();
  });
  const review = (value: SelfReviewInput) => run(async () => {
    await submitSelfReview(activity.id, activity.optimistic_version, value);
    await refresh();
  });

  const completed = !editableStates.has(activity.state);
  const canCommit = activity.state === "active" && isComplete(draft) && confirmed && (activity.task_contract.block !== "technical_learning" || activity.source_hidden);

  return (
    <section className="activity-page" aria-labelledby="activity-title">
      <Link className="back-link" to="/">← Today</Link>
      <header className="activity-hero">
        <div>
          <p className="eyebrow">{activity.task_contract.block.replaceAll("_", " ")}</p>
          <h1 id="activity-title">{activity.task_contract.objective}</h1>
        </div>
        <div className="activity-clock">
          <strong>{Math.floor(activity.activity_focused_seconds / 60)}:{String(activity.activity_focused_seconds % 60).padStart(2, "0")}</strong>
          <span>{activity.task_contract.timebox_minutes} minutes</span>
        </div>
      </header>
      <div className="activity-status-row">
        <span>{activity.state.replaceAll("_", " ")}</span>
        <span>Allowed AI role · {activity.task_contract.allowed_ai_role === "none" ? "None" : activity.task_contract.allowed_ai_role}</span>
        <span>{activity.task_contract.required ? "Required" : "Adaptive"}</span>
      </div>
      {activity.hard_stop_recommended ? <p className="hard-stop-notice">255-minute hard stop reached. Save safely and stop; no extra work will be added.</p> : null}
      {timer.syncIssue ? <p className="sync-warning" role="status">Timer connection interrupted. The same heartbeat will retry without double-counting.</p> : null}
      {error ? <p className="workflow-error" role="alert">{error}</p> : null}

      <div className="activity-layout">
        <div className="activity-work">
          {!completed ? (
            <>
              <section className="timer-controls" aria-label="Focused timer">
                {activity.state === "ready" ? <button className="primary-button" type="button" disabled={busy} onClick={() => void run(timer.start)}>Start activity</button> : null}
                {activity.state === "active" ? <><span className="timer-live">Timer running</span><button className="secondary-button" type="button" disabled={busy} onClick={() => void run(timer.pause)}>Pause</button></> : null}
                {activity.state === "paused" ? <button className="primary-button" type="button" disabled={busy} onClick={() => void run(timer.resume)}>Resume</button> : null}
              </section>
              <SourcePanel activity={activity} busy={busy} onVisibility={(hidden) => void run(async () => update(await setSourceVisibility(activity.id, activity.optimistic_version, hidden)))} />
              <UniversalOutputEditor activity={activity} draft={draft} onChange={setDraft} />
              <p className="autosave-state" role="status">{savedAt ? `Saved on this Mac at ${savedAt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}` : "Draft autosave is preparing…"}</p>
              <ArtifactUploader activityId={activity.id} expectedVersion={activity.optimistic_version} disabled={busy} onUploaded={(reference, name) => { setArtifactRefs((current) => [...current, reference]); setArtifactNames((current) => [...current, name]); }} />
              {artifactNames.length ? <p className="attached-files">Attached · {artifactNames.join(", ")}</p> : null}
              <section className="commit-panel">
                <label className="confirmation-row"><input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} /><span>I understand this independent output becomes immutable evidence.</span></label>
                {activity.task_contract.block === "technical_learning" && !activity.source_hidden ? <p>Closed-source recall is required before commitment.</p> : null}
                <button className="primary-button" type="button" disabled={busy || !canCommit} onClick={() => void commit()}>Commit Attempt A</button>
              </section>
            </>
          ) : <ReadOnlyAttempt activity={activity} />}

          {activity.state === "output_committed" ? <SelfReviewForm busy={busy} onSubmit={review} /> : null}
          {activity.self_review ? (
            <section className="review-complete" id="self-review"><p className="section-label">Reflection preserved</p><h2>Self-review complete</h2><strong>Your score · {activity.self_review.self_score} / 4</strong><p>AI analysis has not been requested yet. Your independent evidence is safe and available to the asynchronous processing workflow.</p></section>
          ) : null}
          <button className="secondary-button ai-review-button" type="button" disabled>Ask AI for review</button>
          <p className="ai-boundary">The analysis trigger is not enabled in this foundation slice. AI feedback remains separate and cannot alter your original attempt or self-score.</p>
        </div>
        <ActivityContractPanel activity={activity} />
      </div>
    </section>
  );
}

export function ActivityWorkspacePage() {
  const rawId = useParams().activityId;
  const activityId = Number(rawId);
  const query = useQuery({ queryKey: activityKey(activityId), queryFn: () => getActivity(activityId), enabled: Number.isSafeInteger(activityId) && activityId > 0 });
  if (!Number.isSafeInteger(activityId) || activityId <= 0) return <p className="workflow-error" role="alert">This activity link is invalid.</p>;
  if (query.isPending) return <p role="status">Opening activity…</p>;
  if (query.isError || !query.data) return <p className="workflow-error" role="alert">This activity could not be opened. No evidence was changed.</p>;
  return <LoadedActivity initial={query.data} />;
}
