import { render, screen, within } from "@testing-library/react";
import { SemanticDiff } from "../../src/features/roadmaps/SemanticDiff";

it("separates time, assignment, pass-criteria, and resource changes", () => {
  render(
    <SemanticDiff
      diff={{
        summary: { added: 2, removed: 0, changed: 2, unchanged: 10 },
        tasks: {
          entries: [
            {
              key: "m2-w1-d1-sql",
              status: "changed",
              fields: [
                { name: "timebox_minutes", before: 45, after: 50 },
                { name: "objective", before: "Practice joins", after: "Reconcile payments" },
              ],
            },
          ],
        },
        pass_contracts: {
          entries: [
            {
              key: "m2-w1-d1-sql",
              status: "changed",
              fields: [{ name: "pass_criteria", before: ["Valid query"], after: ["Valid reconciliation"] }],
            },
          ],
        },
        resources: {
          entries: [{ key: "payments-docs", status: "added", fields: [] }],
        },
        exit_criteria: { entries: [] },
      }}
    />,
  );

  expect(screen.getByText("2 added")).toBeVisible();
  const time = screen.getByTestId("change-timebox_minutes");
  expect(within(time).getByText("45")).toBeVisible();
  expect(within(time).getByText("50")).toBeVisible();
  expect(screen.getByText("Assignment")).toBeVisible();
  expect(screen.getByRole("heading", { name: "Pass criteria" })).toBeVisible();
  expect(screen.getByText("payments-docs")).toBeVisible();
});
