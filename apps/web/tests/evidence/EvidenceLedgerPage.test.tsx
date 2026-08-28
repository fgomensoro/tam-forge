import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { expect, it } from "vitest";
import { renderApp } from "../support/renderApp";
import { server } from "../support/server";

const event = {
  id: 91, activity_id: 41, attempt_id: 51, skill_slug: "sql_reconciliation",
  exercise_type: "sql", mapping_version: "mapping-v1", formula_version: "formula-v1",
  rubric_slug: "sql", rubric_version: "rubric-v2", evaluator: "ai_rubric_reviewer",
  practice_mode: "timed_assessment", assistance: "no_ai", difficulty: "standard",
  performance_score: "3.2", skill_impact: "0.6", effective_weight: "0.8",
  qualifying_for_level: true, qualification_reason: "independent evidence",
  raw_dimension_scores: { correctness: "3.4", business_meaning: "3.0" },
  occurred_at: "2026-08-27T12:00:00Z",
};

it("shows evidence-first skill and portfolio history with every formula input inspectable", async () => {
  server.use(
    http.get("http://localhost:3000/api/v1/auth/session", () => HttpResponse.json({ github_login: "fgomensoro", csrf_token: "c".repeat(43) })),
    http.get("http://localhost:3000/api/v1/skills", () => HttpResponse.json({ items: [{
      slug: "sql_reconciliation", name: "SQL & reconciliation", baseline: "1.5", month_one_target: "3.0", final_target: "4.0",
      latest_snapshot: {
        id: 7, formula_version: "formula-v1", snapshot_date: "2026-08-27", estimated_level: "2.8",
        confidence: "medium", trend: "improving", recency: "current", baseline_target_gap: "-1.3",
        month_one_target_gap: "0.2", final_target_gap: "1.2", total_effective_weight: "2.4",
        qualifying_event_count: 3, exercise_type_count: 2, last_strong_evidence_date: "2026-08-26",
        manifest: [
          { event_id: 91, effective_weight: "0.8", inclusion_code: "included" },
          { event_id: 92, effective_weight: "0.4", inclusion_code: "discounted_same_day" },
          { event_id: 93, effective_weight: "0", inclusion_code: "excluded_nonqualifying" },
        ],
        confidence_basis: { event_count: 3 }, trend_basis: { slope: "0.2" },
      },
    }] })),
    http.get("http://localhost:3000/api/v1/skills/sql_reconciliation/evidence", () => HttpResponse.json({ items: [
      event,
      { ...event, id: 92, effective_weight: "0.4", qualifying_for_level: true, evaluator: "self" },
      { ...event, id: 93, effective_weight: "0", qualifying_for_level: false, qualification_reason: "assisted evidence" },
    ], next_cursor: null })),
    http.get("http://localhost:3000/api/v1/portfolio-judgment", () => HttpResponse.json({ items: [{
      id: 15, activity_id: 41, attempt_id: 51, formula_version: "portfolio-v1", rubric_version: "portfolio-r1",
      total_score: "14.5", components: [
        ["customer_impact", "2.5"], ["risk", "2.0"], ["severity", "2.0"], ["urgency", "2.0"],
        ["workaround", "2.0"], ["strategic_context", "2.0"], ["capacity", "2.0"],
      ].map(([slug, score]) => ({ slug, score })), trend_basis: { prior_total: "13.0" }, scored_at: "2026-08-27T12:00:00Z",
    }], next_cursor: null })),
    http.get("http://localhost:3000/api/v1/activities/41/evidence", () => HttpResponse.json({ items: [event], next_cursor: null })),
  );
  const user = userEvent.setup();
  renderApp("/evidence");

  expect(await screen.findByRole("heading", { name: "Evidence" })).toBeVisible();
  expect(await screen.findByText("SQL & reconciliation")).toBeVisible();
  expect(screen.getByText("2.8 / 4")).toBeVisible();
  expect(screen.getByText("0.2 to Month 1 target")).toBeVisible();
  expect(screen.getByText("medium confidence")).toBeVisible();
  expect(screen.getByText("improving trend")).toBeVisible();
  expect(screen.getByText("current evidence")).toBeVisible();
  expect(screen.getByText("Last strong evidence · 2026-08-26")).toBeVisible();
  expect(screen.getByText(/Self-scores remain separate/i)).toBeVisible();

  await user.click(screen.getByRole("button", { name: "Inspect SQL & reconciliation evidence" }));
  expect((await screen.findAllByText("mapping-v1")).length).toBeGreaterThan(0);
  expect(screen.getAllByText("formula-v1").length).toBeGreaterThan(0);
  expect(screen.getAllByText("rubric-v2").length).toBeGreaterThan(0);
  expect(screen.getByText("included")).toBeVisible();
  expect(screen.getByText("discounted same day")).toBeVisible();
  expect(screen.getByText("excluded nonqualifying")).toBeVisible();
  expect(screen.getAllByText("Raw dimension scores").length).toBeGreaterThan(0);

  expect(screen.getByText("14.5 / 20")).toBeVisible();
  expect(screen.getByText("customer impact")).toBeVisible();
  await user.click(screen.getByRole("button", { name: "Inspect portfolio evidence from activity 41" }));
  expect(await screen.findByText("Related skill evidence · SQL & reconciliation")).toBeVisible();
  expect(screen.queryByText(/streak|recording count|word count|app time/i)).not.toBeInTheDocument();
});
