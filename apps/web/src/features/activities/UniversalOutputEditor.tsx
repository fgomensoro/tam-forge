import type { ActivityDetail, OutputKind } from "./api";

export type OutputDraft = Record<string, string> & { kind: OutputKind };

const kindsByBlock: Record<string, OutputKind[]> = {
  technical_learning: ["reading"],
  sql: ["sql"],
  tam_case: ["case"],
  communication_spoken: ["case", "writing"],
  career_pipeline: ["pipeline"],
  correction_warmup: ["sql", "case", "writing"],
  daily_close: ["writing"],
  saturday_assessment: ["sql", "case", "writing"],
};

function preferredKind(activity: ActivityDetail): OutputKind {
  const allowed = kindsByBlock[activity.task_contract.block] ?? ["writing"];
  const hint = (activity.task_contract.exercise_type ?? "").toLowerCase();
  return allowed.find((kind) => hint.includes(kind)) ?? allowed[0];
}

export function emptyDraft(activity: ActivityDetail, forcedKind?: OutputKind): OutputDraft {
  const kind = forcedKind ?? preferredKind(activity);
  return {
    kind,
    prompt: activity.task_contract.objective,
    audience: "",
    key_idea_1: "", key_idea_2: "", key_idea_3: "", boundary_or_failure: "", tam_customer_example: "", unresolved_question: "",
    query: "", result: "", validation: "", explanation: "", business_meaning: "", assistance_used: "none",
    canonical_prompt: activity.task_contract.objective, canonical_facts: "", discovery_questions: "", assumptions: "", working_notes: "", final_artifact: "", decisions: "", risks: "", unresolved_questions: "",
    requested_action: "", facts: "", unknowns: "", tone: "", word_or_character_limit: "", draft_markdown: "", self_edit_notes: "",
    company: "", role: "", stage: "", completed_action: "", artifact_summary: "", next_action: "",
  };
}

const lines = (value: string) => value.split("\n").map((item) => item.trim()).filter(Boolean);

export function outputPayload(draft: OutputDraft, activity: ActivityDetail): Record<string, unknown> {
  const base = { contract_version: 1, kind: draft.kind, prompt: draft.prompt.trim(), audience: draft.audience.trim(), time_limit_minutes: activity.task_contract.timebox_minutes };
  if (draft.kind === "reading") return { ...base, key_ideas: [draft.key_idea_1.trim(), draft.key_idea_2.trim(), draft.key_idea_3.trim()], boundary_or_failure: draft.boundary_or_failure.trim(), tam_customer_example: draft.tam_customer_example.trim(), unresolved_question: draft.unresolved_question.trim() };
  if (draft.kind === "sql") return { ...base, query: draft.query.trim(), result: draft.result.trim(), validation: draft.validation.trim(), explanation: draft.explanation.trim(), business_meaning: draft.business_meaning.trim(), solving_seconds: Math.min(activity.activity_focused_seconds, activity.task_contract.timebox_minutes * 60), assistance_used: draft.assistance_used };
  if (draft.kind === "case") return { ...base, canonical_prompt: draft.canonical_prompt.trim(), canonical_facts: lines(draft.canonical_facts), discovery_questions: lines(draft.discovery_questions), assumptions: lines(draft.assumptions), working_notes: draft.working_notes.trim(), final_artifact: draft.final_artifact.trim(), decisions: lines(draft.decisions), risks: lines(draft.risks), unresolved_questions: lines(draft.unresolved_questions) };
  if (draft.kind === "pipeline") return { ...base, company: draft.company.trim(), role: draft.role.trim(), stage: draft.stage.trim(), completed_action: draft.completed_action.trim(), artifact_summary: draft.artifact_summary.trim(), next_action: draft.next_action.trim() };
  return { ...base, requested_action: draft.requested_action.trim(), facts: lines(draft.facts), unknowns: lines(draft.unknowns), tone: draft.tone.trim(), word_or_character_limit: draft.word_or_character_limit.trim(), draft_markdown: draft.draft_markdown.trim(), self_edit_notes: draft.self_edit_notes.trim() };
}

export function isComplete(draft: OutputDraft) {
  const payload = outputPayload(draft, { activity_focused_seconds: 0, task_contract: { timebox_minutes: 1 } } as ActivityDetail);
  return Object.entries(payload).every(([key, value]) => {
    if (["solving_seconds"].includes(key)) return true;
    if (Array.isArray(value)) return value.length > 0 && value.every((item) => typeof item === "string" && item.length > 0);
    return typeof value !== "string" || value.trim().length > 0;
  });
}

function Field({ label, name, value, onChange, rows = 3 }: { label: string; name: string; value: string; onChange: (name: string, value: string) => void; rows?: number }) {
  return <label className="editor-field"><span>{label}</span><textarea name={name} rows={rows} value={value} onChange={(event) => onChange(name, event.target.value)} /></label>;
}

function FieldsForKind({ draft, onChange }: { draft: OutputDraft; onChange: (name: string, value: string) => void }) {
  if (draft.kind === "reading") return <><Field label="Key idea 1" name="key_idea_1" value={draft.key_idea_1} onChange={onChange} /><Field label="Key idea 2" name="key_idea_2" value={draft.key_idea_2} onChange={onChange} /><Field label="Key idea 3" name="key_idea_3" value={draft.key_idea_3} onChange={onChange} /><Field label="Boundary or failure mode" name="boundary_or_failure" value={draft.boundary_or_failure} onChange={onChange} /><Field label="TAM or customer example" name="tam_customer_example" value={draft.tam_customer_example} onChange={onChange} /><Field label="Unresolved question" name="unresolved_question" value={draft.unresolved_question} onChange={onChange} /></>;
  if (draft.kind === "sql") return <><Field label="SQL query" name="query" value={draft.query} onChange={onChange} rows={8} /><Field label="Result" name="result" value={draft.result} onChange={onChange} /><Field label="Validation" name="validation" value={draft.validation} onChange={onChange} /><Field label="Query explanation" name="explanation" value={draft.explanation} onChange={onChange} /><Field label="Business meaning" name="business_meaning" value={draft.business_meaning} onChange={onChange} /><label className="editor-field"><span>Assistance used</span><select value={draft.assistance_used} onChange={(event) => onChange("assistance_used", event.target.value)}><option value="none">None</option><option value="coach_preparation">Coach preparation</option><option value="hint_ladder">Hint ladder</option><option value="time_expired">Time expired</option><option value="reference_only">Reference only</option></select></label></>;
  if (draft.kind === "case") return <><Field label="Canonical prompt" name="canonical_prompt" value={draft.canonical_prompt} onChange={onChange} /><Field label="Canonical facts" name="canonical_facts" value={draft.canonical_facts} onChange={onChange} /><Field label="Discovery questions" name="discovery_questions" value={draft.discovery_questions} onChange={onChange} /><Field label="Assumptions" name="assumptions" value={draft.assumptions} onChange={onChange} /><Field label="Working notes" name="working_notes" value={draft.working_notes} onChange={onChange} rows={6} /><Field label="Final artifact" name="final_artifact" value={draft.final_artifact} onChange={onChange} rows={8} /><Field label="Decisions" name="decisions" value={draft.decisions} onChange={onChange} /><Field label="Risks" name="risks" value={draft.risks} onChange={onChange} /><Field label="Unresolved questions" name="unresolved_questions" value={draft.unresolved_questions} onChange={onChange} /></>;
  if (draft.kind === "pipeline") return <><Field label="Company" name="company" value={draft.company} onChange={onChange} /><Field label="Role" name="role" value={draft.role} onChange={onChange} /><Field label="Stage" name="stage" value={draft.stage} onChange={onChange} /><Field label="Completed action" name="completed_action" value={draft.completed_action} onChange={onChange} /><Field label="Saved artifact" name="artifact_summary" value={draft.artifact_summary} onChange={onChange} /><Field label="Next action" name="next_action" value={draft.next_action} onChange={onChange} /></>;
  return <><Field label="Requested action" name="requested_action" value={draft.requested_action} onChange={onChange} /><Field label="Facts" name="facts" value={draft.facts} onChange={onChange} /><Field label="Unknowns" name="unknowns" value={draft.unknowns} onChange={onChange} /><Field label="Tone" name="tone" value={draft.tone} onChange={onChange} /><Field label="Word or character limit" name="word_or_character_limit" value={draft.word_or_character_limit} onChange={onChange} /><Field label="Independent draft" name="draft_markdown" value={draft.draft_markdown} onChange={onChange} rows={10} /><Field label="Self-edit notes" name="self_edit_notes" value={draft.self_edit_notes} onChange={onChange} /></>;
}

export function UniversalOutputEditor({ activity, draft, onChange }: { activity: ActivityDetail; draft: OutputDraft; onChange: (draft: OutputDraft) => void }) {
  const allowed = kindsByBlock[activity.task_contract.block] ?? [draft.kind];
  const change = (name: string, value: string) => onChange({ ...draft, [name]: value });
  return (
    <section className="output-editor" aria-labelledby="output-title">
      <header><p className="section-label">Independent evidence</p><h2 id="output-title">Working output</h2></header>
      {allowed.length > 1 ? <label className="editor-field compact"><span>Output type</span><select value={draft.kind} onChange={(event) => onChange(emptyDraft(activity, event.target.value as OutputKind))}>{allowed.map((kind) => <option key={kind}>{kind}</option>)}</select></label> : null}
      <div className="editor-base-fields">
        <Field label="Prompt" name="prompt" value={draft.prompt} onChange={change} />
        <Field label="Audience" name="audience" value={draft.audience} onChange={change} />
        <p><span>Time limit</span><strong>{activity.task_contract.timebox_minutes} minutes</strong></p>
      </div>
      <p className="line-help">For list fields, put one item on each line.</p>
      <div className="editor-grid"><FieldsForKind draft={draft} onChange={change} /></div>
    </section>
  );
}
