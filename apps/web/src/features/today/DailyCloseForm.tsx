import { useState } from "react";
import { closeToday, type DailyCloseCommand, type Today } from "./api";

const evidenceStates = new Set(["output_committed", "self_review_complete", "ai_processing", "feedback_ready", "correction_due", "demonstrated", "needs_work", "incomplete", "superseded"]);

export function DailyCloseForm({ today, onClosed }: { today: Today; onClosed: () => void }) {
  const [strongest, setStrongest] = useState("");
  const [mistake, setMistake] = useState("");
  const [classification, setClassification] = useState<DailyCloseCommand["unfinished_classification"]>("none");
  const [unfinished, setUnfinished] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const activityIds = today.tasks.filter((task) => task.block !== "daily_close" && evidenceStates.has(task.state)).map((task) => task.activity_id);
  const complete = confirmed && strongest.trim() && mistake.trim() && activityIds.length > 0 && (classification === "none" || unfinished.trim());

  const submit = async () => {
    setBusy(true); setError(null);
    try {
      await closeToday(today.local_date, {
        evidence_confirmed: true,
        evidence_manifest: { schema_version: 1, activity_ids: activityIds, attempt_ids: [], artifact_ids: [], self_review_ids: [] },
        strongest_output: strongest.trim(),
        repeated_mistake: mistake.trim(),
        unfinished_classification: classification,
        unfinished_requirement: classification === "none" ? null : unfinished.trim(),
        correction_ids: [],
      });
      onClosed();
    } catch { setError("The day could not be closed. Your saved activities are unchanged."); }
    finally { setBusy(false); }
  };

  return (
    <section className="daily-close-form" id="daily-close" aria-labelledby="daily-close-title">
      <p className="section-label">15-minute close</p>
      <h2 id="daily-close-title">Close the study day</h2>
      <p>Confirm evidence, name the strongest output and repeated mistake, then stop. Unused time does not create extra work.</p>
      <label className="editor-field"><span>Strongest output</span><textarea rows={3} value={strongest} onChange={(event) => setStrongest(event.target.value)} /></label>
      <label className="editor-field"><span>Repeated mistake</span><textarea rows={3} value={mistake} onChange={(event) => setMistake(event.target.value)} /></label>
      <label className="editor-field compact"><span>Unfinished work</span><select value={classification} onChange={(event) => setClassification(event.target.value as DailyCloseCommand["unfinished_classification"])}><option value="none">None</option><option value="required">Required — replace adaptive work</option><option value="useful">Useful — retrieval queue</option><option value="optional">Optional — drop</option><option value="superseded">Superseded by stronger evidence</option></select></label>
      {classification !== "none" ? <label className="editor-field"><span>Unfinished requirement</span><textarea rows={3} value={unfinished} onChange={(event) => setUnfinished(event.target.value)} /></label> : null}
      <p className="close-evidence">Saved activity evidence · {activityIds.length} items<br />Corrections selected for tomorrow · 0 of 2</p>
      <label className="confirmation-row"><input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} /><span>I confirmed today’s saved evidence and will not add catch-up work.</span></label>
      {error ? <p className="workflow-error" role="alert">{error}</p> : null}
      <button className="primary-button" type="button" disabled={busy || !complete} onClick={() => void submit()}>{busy ? "Closing…" : "Close day"}</button>
    </section>
  );
}
