import { expect, test } from "@playwright/test";
import { fileURLToPath } from "node:url";
import { authenticate, seedTestSession } from "./support/auth";

const roadmapPackage = fileURLToPath(
  new URL("../../backend/tests/fixtures/roadmaps/month-v1.zip", import.meta.url),
);

test("imports Month 1 and preserves the independent learning workflow", async ({ page }) => {
  const session = seedTestSession();
  expect(session.owner_github_id).toBe(102269369);
  await authenticate(page.context(), session);
  await page.addInitScript(() => {
    const RealDate = Date;
    const fixed = new RealDate("2026-08-24T12:00:00-07:00").valueOf();
    class FixedDate extends RealDate {
      constructor(...args: ConstructorParameters<typeof Date>) {
        super(...(args.length ? args : [fixed]));
      }
      static now() { return fixed; }
    }
    Object.defineProperty(globalThis, "Date", { value: FixedDate });
  });

  await page.goto("/roadmaps");
  await expect(page.getByRole("heading", { level: 1, name: "Roadmaps" })).toBeVisible();
  await page.getByLabel("Roadmap ZIP").setInputFiles(roadmapPackage);
  await page.getByRole("button", { name: "Review package" }).click();
  await expect(page.getByRole("heading", { name: "Validation passed" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "What this roadmap changes" })).toBeVisible();
  await page.getByLabel(/I reviewed the validation and semantic changes/).check();
  await page.getByRole("button", { name: "Approve roadmap" }).click();
  await expect(page.getByText(/Private mirror · not required/)).toBeVisible();
  await page.getByRole("button", { name: "Activate Month 1" }).click();
  await expect(page.getByText("Month 1 is active")).toBeVisible();

  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1, name: "Today" })).toBeVisible();
  await expect(page.getByText("240 planned minutes")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Required work" })).toBeVisible();
  const todayResponse = await page.request.get("/api/v1/today?date=2026-08-24");
  expect(todayResponse.ok()).toBeTruthy();
  const today = await todayResponse.json() as {
    tasks: Array<{ activity_id: number; block: string; timebox_minutes: number }>;
  };
  const reading = today.tasks.find((task) => task.block === "technical_learning");
  expect(reading).toMatchObject({ timebox_minutes: 45 });
  expect(reading).toBeDefined();

  await page.goto(`/activities/${reading!.activity_id}`);
  await expect(page.getByRole("heading", { level: 2, name: "Working output" })).toBeVisible();
  await page.getByRole("button", { name: "Start activity" }).click();
  await expect(page.getByText("Timer running")).toBeVisible();
  await page.getByRole("button", { name: "Pause" }).click();
  await page.reload();
  await page.getByRole("button", { name: "Resume" }).click();
  await page.getByRole("button", { name: "Hide source" }).click();
  await expect(page.getByRole("heading", { name: "Source hidden" })).toBeVisible();

  await page.getByLabel("Audience").fill("Technical hiring manager");
  await page.getByLabel("Key idea 1").fill("HTTP requests carry explicit methods and resource paths.");
  await page.getByLabel("Key idea 2").fill("Status codes separate client and server failure classes.");
  await page.getByLabel("Key idea 3").fill("A TAM connects protocol evidence to customer impact.");
  await page.getByLabel("Boundary or failure mode").fill("A successful transport does not prove the business operation completed.");
  await page.getByLabel("TAM or customer example").fill("Confirm whether an order was committed before advising a retry.");
  await page.getByLabel("Unresolved question").fill("Which application errors use a successful HTTP status?");
  await page.getByLabel(/I understand this independent output becomes immutable evidence/).check();
  await page.getByRole("button", { name: "Commit Attempt A" }).click();
  await expect(page.getByRole("heading", { name: "Mandatory self-review" })).toBeVisible();

  const reflections = [
    ["Main answer or decision", "I separated transport status from business outcome."],
    ["What I did well", "I connected the protocol to customer impact."],
    ["Where structure was weak", "The boundary came later than it should."],
    ["Where I became vague", "I did not name the exact business error shape."],
    ["Where I hesitated", "I paused while choosing the retry example."],
    ["What I will change", "Lead with the business outcome before retry guidance."],
  ] as const;
  for (const [label, value] of reflections) await page.getByLabel(label).fill(value);
  await page.getByLabel("My self-score").selectOption("3");
  await page.getByRole("button", { name: "Submit self-review" }).click();
  await expect(page.getByRole("heading", { name: "Self-review complete" })).toBeVisible();
  await expect(page.getByText(/Attempt A is committed and read-only/)).toBeVisible();
  await expect(page.getByText("Attempt C")).toHaveCount(0);

  await page.getByRole("link", { name: "Evidence" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Evidence" })).toBeVisible();
  await expect(page.getByText("Missing evidence is not zero.")).toBeVisible();
  await expect(page.getByText("Not assessed").first()).toBeVisible();
  await expect(page.getByText(/streak|recording count|transcript word count/i)).toHaveCount(0);

  await page.getByRole("button", { name: /Notifications/ }).click();
  const markRead = page.getByRole("button", { name: "Mark Feedback ready as read" });
  await expect(markRead).toBeVisible();
  await markRead.press("Enter");
  await expect(markRead).toHaveCount(0);
  await expect(page.getByText(/Sunday study reminder/i)).toHaveCount(0);
});
