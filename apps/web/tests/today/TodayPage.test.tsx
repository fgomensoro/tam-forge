import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { renderApp } from "../support/renderApp";
import { server } from "../support/server";

const task = {
  activity_id: 41,
  roadmap_order: 1,
  stable_id: "m1-w1-d1-sql",
  block: "sql",
  state: "ready",
  objective: "Reconcile customer payments with the correct result grain.",
  timebox_minutes: 45,
  source_references: [{ path: "sql/tasks.md", anchor: "Task 1" }],
  required_output: ["Query", "Validated result", "Business explanation"],
  pass_criteria: ["Correct result grain"],
  allowed_ai_role: "none",
  evidence_requirements: ["Independent query and result"],
  required: true,
  optimistic_version: 1,
};

function today(overrides: Record<string, unknown> = {}) {
  return {
    local_date: "2026-08-27",
    timezone: "America/Los_Angeles",
    day_id: 8,
    day_type: "weekday",
    day_status: "planned",
    roadmap: { version_id: 2, version_key: "month-1-v1", version_number: 1, month: 1, week: 1, day: 1 },
    total_planned_minutes: 240,
    time_policy: { target_minutes: 240, acceptable_minimum: 225, hard_stop_minutes: 255, focused_minutes: 0, hard_stop_recommended: false },
    required_blocks: [{ name: "Knowledge and career pipeline", planned_minutes: 120, activity_ids: [41] }],
    tasks: [task],
    corrections: [
      { id: 1, priority: 1, due_date: "2026-08-27", instruction: "Lead with the recommendation.", status: "scheduled", attempt_b_activity_id: 51 },
      { id: 2, priority: 2, due_date: "2026-08-27", instruction: "State customer impact precisely.", status: "pending", attempt_b_activity_id: null },
    ],
    interviews: [{ id: 3, company: "ExampleCo", role: "TAM", stage: "Hiring manager", starts_at: "2026-08-27T18:00:00Z", expected_duration_minutes: 45, privacy_permission_code: "permission_not_requested" }],
    awaiting_self_reviews: [{ activity_id: 31, objective: "Incident update", output_committed_at: "2026-08-27T12:00:00Z" }],
    analyses: [
      { activity_id: 21, state: "ready", progress_label: "ready", updated_at: "2026-08-27T12:00:00Z" },
      { activity_id: 22, state: "needs_attention", progress_label: "action_required", updated_at: "2026-08-27T12:00:00Z" },
    ],
    primary_continue: { kind: "start_activity", target_id: 41, label: "Start SQL", allowed_ai_role: "none" },
    source_updated_at: "2026-08-27T12:00:00Z",
    read_model_version: "today-v1",
    etag: "abc",
    ...overrides,
  };
}

function authenticate() {
  server.use(
    http.get("http://localhost:3000/api/v1/auth/session", () =>
      HttpResponse.json({ github_login: "fgomensoro", csrf_token: "c".repeat(43) }),
    ),
  );
}

describe("Today", () => {
  it("shows the governed day, full task contract, and exactly one primary Continue action", async () => {
    authenticate();
    server.use(http.get("http://localhost:3000/api/v1/today", () => HttpResponse.json(today())));
    renderApp();

    expect(await screen.findByRole("heading", { name: "Today" })).toBeVisible();
    expect(screen.getByText("Month 1 · Week 1 · Day 1")).toBeVisible();
    expect(screen.getByText("240 planned minutes")).toBeVisible();
    expect(screen.getByText(task.objective)).toBeVisible();
    expect(screen.getByText("45 minutes")).toBeVisible();
    expect(screen.getByText("sql/tasks.md · Task 1")).toBeVisible();
    expect(screen.getByText("Correct result grain")).toBeVisible();
    expect(screen.getByText("Independent query and result")).toBeVisible();
    expect(screen.getAllByRole("link", { name: /Continue: Start SQL/i })).toHaveLength(1);
    expect(screen.getByText("Lead with the recommendation.")).toBeVisible();
    expect(screen.getByText("State customer impact precisely.")).toBeVisible();
    expect(screen.getByText(/ExampleCo · TAM · Hiring manager/i)).toBeVisible();
    expect(screen.getByText("Self-review due")).toBeVisible();
    expect(screen.getByText("Feedback ready")).toBeVisible();
    expect(screen.getByText("Processing needs attention")).toBeVisible();
    expect(screen.queryByText(/streak/i)).not.toBeInTheDocument();
  });

  it("keeps Sunday completely off and applies the Saturday 120-minute cap", async () => {
    authenticate();
    let payload = today({
      day_type: "sunday",
      day_status: "off",
      day_id: null,
      total_planned_minutes: 0,
      tasks: [],
      corrections: [],
      primary_continue: null,
      required_blocks: [],
      time_policy: { target_minutes: 0, acceptable_minimum: 0, hard_stop_minutes: 0, focused_minutes: 0, hard_stop_recommended: false },
    });
    server.use(http.get("http://localhost:3000/api/v1/today", () => HttpResponse.json(payload)));
    const view = renderApp();
    expect(await screen.findByText("Sunday is off.")).toBeVisible();
    expect(screen.queryByRole("link", { name: /Continue:/i })).not.toBeInTheDocument();

    payload = today({
      day_type: "saturday",
      total_planned_minutes: 120,
      time_policy: { target_minutes: 120, acceptable_minimum: 0, hard_stop_minutes: 120, focused_minutes: 35, hard_stop_recommended: false },
    });
    window.dispatchEvent(new CustomEvent("tamforge:status", { detail: { query: "today" } }));
    await waitFor(() => expect(screen.getByText("Saturday · 120-minute maximum")).toBeVisible());
    view.unmount();
  });

  it("refreshes only the Today query after a status event", async () => {
    authenticate();
    let reads = 0;
    server.use(http.get("http://localhost:3000/api/v1/today", () => {
      reads += 1;
      return HttpResponse.json(today());
    }));
    renderApp();
    await screen.findByText(task.objective);
    window.dispatchEvent(new CustomEvent("tamforge:status", { detail: { query: "today" } }));
    await waitFor(() => expect(reads).toBe(2));
  });

  it("closes the day from saved evidence without inventing extra work", async () => {
    authenticate();
    let requestBody: Record<string, unknown> | null = null;
    const payload = today({
      day_status: "in_progress",
      tasks: [
        { ...task, state: "self_review_complete" },
        { ...task, activity_id: 70, roadmap_order: 7, stable_id: "daily-close", block: "daily_close", objective: "Close the study day.", timebox_minutes: 15 },
      ],
      primary_continue: { kind: "close_day", target_id: 70, label: "Close study day", allowed_ai_role: "none" },
      corrections: [],
      analyses: [],
      awaiting_self_reviews: [],
    });
    let closed = false;
    server.use(
      http.get("http://localhost:3000/api/v1/today", () => HttpResponse.json(closed ? { ...payload, day_status: "closed", primary_continue: null } : payload)),
      http.post("http://localhost:3000/api/v1/today/2026-08-27/close", async ({ request }) => {
        requestBody = await request.json() as Record<string, unknown>;
        closed = true;
        return HttpResponse.json({ daily_close_id: 9, study_day_id: 8, day_status: "closed", closed_at: "2026-08-27T23:00:00Z", consequence: "none", replayed: false });
      }),
    );
    const user = userEvent.setup();
    renderApp("/?close=70#daily-close");
    expect(await screen.findByRole("heading", { name: "Close the study day" })).toBeVisible();
    await user.type(screen.getByLabelText("Strongest output"), "A clear rollback recommendation.");
    await user.type(screen.getByLabelText("Repeated mistake"), "The customer impact came too late.");
    await user.click(screen.getByRole("checkbox", { name: /confirmed today’s saved evidence/i }));
    await user.click(screen.getByRole("button", { name: "Close day" }));

    await waitFor(() => expect(requestBody).not.toBeNull());
    expect(requestBody).toMatchObject({
      evidence_confirmed: true,
      evidence_manifest: { activity_ids: [41] },
      unfinished_classification: "none",
      unfinished_requirement: null,
      correction_ids: [],
    });
    await waitFor(() => expect(screen.queryByRole("heading", { name: "Close the study day" })).not.toBeInTheDocument());
  });
});
