import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { emptyDraft, UniversalOutputEditor } from "../../src/features/activities/UniversalOutputEditor";
import type { ActivityDetail } from "../../src/features/activities/api";

function activity(block: ActivityDetail["task_contract"]["block"], exerciseType: string): ActivityDetail {
  return {
    id: 1, study_day_id: 1, state: "active", optimistic_version: 1,
    classification: "required", stronger_evidence_id: null, activity_focused_seconds: 10,
    day_focused_minutes: 1, hard_stop_recommended: false, open_timer: null, source_hidden: true,
    committed_output: null, self_review: null,
    task_contract: {
      stable_id: `task-${block}`, block, objective: "Produce independent evidence.",
      timebox_minutes: 45, required: true, source_references: [], required_output: [],
      pass_criteria: [], evidence_requirements: [], allowed_ai_role: "none", procedure: [], constraints: [],
      exercise_type: exerciseType, mapping_version: "month-1-v1",
    },
  };
}

it.each([
  ["technical_learning", "reading", "Key idea 1"],
  ["sql", "sql", "SQL query"],
  ["tam_case", "case", "Discovery questions"],
  ["communication_spoken", "writing", "Independent draft"],
  ["career_pipeline", "pipeline", "Completed action"],
] as const)("renders the %s evidence contract", (block, exerciseType, expectedField) => {
  const current = activity(block, exerciseType);
  const view = render(<UniversalOutputEditor activity={current} draft={emptyDraft(current)} onChange={vi.fn()} />);
  expect(screen.getByLabelText(expectedField)).toBeVisible();
  expect(screen.getByLabelText("Audience")).toBeVisible();
  view.unmount();
});
