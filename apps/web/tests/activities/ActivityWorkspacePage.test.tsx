import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { renderApp } from "../support/renderApp";
import { server } from "../support/server";

function activity(overrides: Record<string, unknown> = {}) {
  return {
    id: 41,
    study_day_id: 8,
    state: "ready",
    optimistic_version: 1,
    classification: "required",
    stronger_evidence_id: null,
    activity_focused_seconds: 0,
    day_focused_minutes: 0,
    hard_stop_recommended: false,
    open_timer: null,
    source_hidden: false,
    task_contract: {
      stable_id: "m1-w1-d1-writing",
      block: "communication_spoken",
      objective: "Write a concise customer incident update.",
      timebox_minutes: 35,
      required: true,
      source_references: [{ path: "Week 1.md", anchor: "Incident update" }],
      required_output: ["Independent draft", "Self-edit"],
      pass_criteria: ["States impact and next action"],
      evidence_requirements: ["Committed Attempt A"],
      allowed_ai_role: "none",
      procedure: [{ phase: "Draft", minutes: 30, requirement: "Write without AI." }],
      constraints: ["No AI before commitment."],
      exercise_type: "writing",
      mapping_version: "month-1-v1",
    },
    committed_output: null,
    self_review: null,
    ...overrides,
  };
}

function setup(initial = activity()) {
  let current = initial;
  server.use(
    http.get("http://localhost:3000/api/v1/auth/session", () =>
      HttpResponse.json({ github_login: "fgomensoro", csrf_token: "c".repeat(43) }),
    ),
    http.get("http://localhost:3000/api/v1/activities/41", () => HttpResponse.json(current)),
    http.post("http://localhost:3000/api/v1/activities/41/start", () => {
      current = activity({ state: "active", optimistic_version: 2, open_timer: { id: 7, started_at: "2026-08-27T12:00:00Z", last_heartbeat_at: "2026-08-27T12:00:00Z", counted_seconds: 0, last_client_sequence: 0 } });
      return HttpResponse.json(current);
    }),
    http.post("http://localhost:3000/api/v1/activities/41/commit-output", async ({ request }) => {
      const body = await request.json() as { output: Record<string, unknown> };
      current = activity({
        state: "output_committed",
        optimistic_version: 3,
        committed_output: { attempt_id: 91, attempt_kind: "attempt_a", commitment_sha256: "a".repeat(64), contract_payload: { output: body.output }, artifact_ids: [], committed_at: "2026-08-27T12:10:00Z" },
      });
      return HttpResponse.json({ activity_id: 41, state: "output_committed", optimistic_version: 3, attempt_id: 91, commitment_sha256: "a".repeat(64), artifact_ids: [] });
    }),
    http.post("http://localhost:3000/api/v1/activities/41/self-review", async ({ request }) => {
      const body = await request.json() as Record<string, unknown>;
      current = activity({
        state: "self_review_complete",
        optimistic_version: 4,
        committed_output: { attempt_id: 91, attempt_kind: "attempt_a", commitment_sha256: "a".repeat(64), contract_payload: { output: {} }, artifact_ids: [], committed_at: "2026-08-27T12:10:00Z" },
        self_review: { id: 92, attempt_id: 91, ...body, submitted_at: "2026-08-27T12:15:00Z" },
      });
      return HttpResponse.json({ activity_id: 41, state: "self_review_complete", optimistic_version: 4, self_review_id: 92, attempt_id: 91, self_score: body.self_score });
    }),
  );
}

describe("universal activity workspace", () => {
  it("always displays the governed contract and keeps AI locked during independent work", async () => {
    setup();
    renderApp("/activities/41");
    expect(await screen.findByRole("heading", { name: "Write a concise customer incident update." })).toBeVisible();
    expect(screen.getAllByText("35 minutes")).toHaveLength(2);
    expect(screen.getByText("Allowed AI role · None")).toBeVisible();
    expect(screen.getByText("Committed Attempt A")).toBeVisible();
    expect(screen.getByText("States impact and next action")).toBeVisible();
    expect(screen.getByText("Week 1.md · Incident update")).toBeVisible();
    expect(screen.getByRole("button", { name: "Ask AI for review" })).toBeDisabled();
    expect(screen.queryByText("Attempt C")).not.toBeInTheDocument();
  });

  it("autosaves a mutable draft, commits Attempt A irreversibly, then requires self-review", async () => {
    setup();
    const user = userEvent.setup();
    renderApp("/activities/41");
    await screen.findByRole("heading", { name: "Write a concise customer incident update." });
    await user.click(screen.getByRole("button", { name: "Start activity" }));
    await screen.findByText("Timer running");

    await user.type(screen.getByLabelText("Audience"), "Customer technical lead");
    await user.type(screen.getByLabelText("Requested action"), "Confirm rollback.");
    await user.type(screen.getByLabelText("Facts"), "Errors rose after release 42.");
    await user.type(screen.getByLabelText("Unknowns"), "Regional scope.");
    await user.type(screen.getByLabelText("Tone"), "Calm and direct");
    await user.type(screen.getByLabelText("Word or character limit"), "150 words");
    await user.type(screen.getByLabelText("Independent draft"), "We recommend a rollback.");
    await user.type(screen.getByLabelText("Self-edit notes"), "Removed speculation.");
    await waitFor(() => expect(screen.getByText(/Saved on this Mac/i)).toBeVisible());
    await user.click(screen.getByRole("checkbox", { name: /becomes immutable/i }));
    await user.click(screen.getByRole("button", { name: "Commit Attempt A" }));

    expect(await screen.findByText("Attempt A is committed and read-only.")).toBeVisible();
    expect(screen.getByRole("button", { name: "Ask AI for review" })).toBeDisabled();
    const answers = [
      ["Main answer or decision", "Recommend rollback."],
      ["What I did well", "Led with the decision."],
      ["Where structure was weak", "Risk arrived late."],
      ["Where I became vague", "Checkpoint was vague."],
      ["Where I hesitated", "Before the timeout explanation."],
      ["What I will change", "Name the next checkpoint."],
    ] as const;
    for (const [label, value] of answers) await user.type(screen.getByLabelText(label), value);
    await user.selectOptions(screen.getByLabelText("My self-score"), "3");
    await user.click(screen.getByRole("button", { name: "Submit self-review" }));
    expect(await screen.findByText("Self-review complete")).toBeVisible();
    expect(screen.getByText("Your score · 3 / 4")).toBeVisible();
  });

  it("requires closed-source recall and warns at the hard stop without adding work", async () => {
    setup(activity({
      state: "active",
      optimistic_version: 2,
      hard_stop_recommended: true,
      day_focused_minutes: 255,
      open_timer: { id: 7, started_at: "2026-08-27T12:00:00Z", last_heartbeat_at: "2026-08-27T12:00:00Z", counted_seconds: 0, last_client_sequence: 0 },
      task_contract: { ...activity().task_contract, block: "technical_learning", exercise_type: "technical_reading" },
    }));
    renderApp("/activities/41");
    expect(await screen.findByText(/255-minute hard stop reached/i)).toBeVisible();
    expect(screen.getByText(/Hide the assigned source before committing recall/i)).toBeVisible();
    expect(screen.queryByText(/extend/i)).not.toBeInTheDocument();
  });
});
