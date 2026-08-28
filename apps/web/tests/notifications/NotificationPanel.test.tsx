import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { expect, it } from "vitest";
import { renderApp } from "../support/renderApp";
import { server } from "../support/server";

it("shows only the five actionable notification types and marks one read idempotently", async () => {
  let readCalls = 0;
  const base = { subject_kind: "activity", subject_id: 41, created_at: "2026-08-27T12:00:00Z", read_at: null };
  server.use(
    http.get("http://localhost:3000/api/v1/auth/session", () => HttpResponse.json({ github_login: "fgomensoro", csrf_token: "c".repeat(43) })),
    http.get("http://localhost:3000/api/v1/today", () => HttpResponse.json({ title: "Today is not ready", status: 404 }, { status: 404 })),
    http.get("http://localhost:3000/api/v1/notifications", () => HttpResponse.json({ items: [
      { ...base, id: 1, notification_type: "feedback_ready" },
      { ...base, id: 2, notification_type: "correction_due", subject_kind: "correction" },
      { ...base, id: 3, notification_type: "upcoming_real_interview", subject_kind: "interview" },
      { ...base, id: 4, notification_type: "saturday_assessment", subject_kind: "study_day" },
      { ...base, id: 5, notification_type: "processing_failure_requires_action", subject_kind: "processing_status" },
      { ...base, id: 6, notification_type: "engagement_streak" },
    ], next_cursor: null })),
    http.post("http://localhost:3000/api/v1/notifications/1/read", () => {
      readCalls += 1;
      return HttpResponse.json({ ...base, id: 1, notification_type: "feedback_ready", read_at: "2026-08-27T12:05:00Z" });
    }),
  );
  const user = userEvent.setup();
  renderApp();
  await screen.findByRole("heading", { name: "Today" });
  await user.click(screen.getByRole("button", { name: /Notifications/i }));

  expect(await screen.findByText("Feedback ready")).toBeVisible();
  expect(screen.getByText("Correction due")).toBeVisible();
  expect(screen.getByText("Upcoming real interview")).toBeVisible();
  expect(screen.getByText("Saturday assessment")).toBeVisible();
  expect(screen.getByText("Processing needs action")).toBeVisible();
  expect(screen.getByText(/Study can continue independently/i)).toBeVisible();
  expect(screen.queryByText(/engagement|streak|Sunday study reminder/i)).not.toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "Mark Feedback ready as read" }));
  expect(readCalls).toBe(1);
  expect(screen.queryByRole("button", { name: "Mark Feedback ready as read" })).not.toBeInTheDocument();
});
