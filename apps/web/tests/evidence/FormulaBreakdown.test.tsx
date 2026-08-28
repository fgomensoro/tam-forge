import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { FormulaBreakdown } from "../../src/features/evidence/FormulaBreakdown";

it("distinguishes included, discounted, and excluded evidence with raw and effective values", () => {
  render(<FormulaBreakdown
    manifest={[
      { event_id: 1, effective_weight: "1.0", inclusion_code: "included" },
      { event_id: 2, effective_weight: "0.5", inclusion_code: "discounted_same_day" },
      { event_id: 3, effective_weight: "0", inclusion_code: "excluded_nonqualifying" },
    ]}
    events={[
      { id: 1, performance_score: "3.5", effective_weight: "1.0", skill_impact: "0.7", raw_dimension_scores: { judgment: "3.5" }, mapping_version: "map-v1", formula_version: "formula-v1", rubric_version: "rubric-v1", qualification_reason: "independent", evaluator: "ai_rubric_reviewer", occurred_at: "2026-08-27T12:00:00Z" },
    ]}
  />);
  expect(screen.getByText("Performance · 3.5 / 4")).toBeVisible();
  expect(screen.getByText("Effective weight · 1.0")).toBeVisible();
  expect(screen.getByText(/judgment.*3.5/i)).toBeVisible();
  expect(screen.getByText("discounted same day")).toBeVisible();
  expect(screen.getByText("excluded nonqualifying")).toBeVisible();
});
