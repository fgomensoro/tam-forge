import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { delay, http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { renderApp } from "../support/renderApp";
import { server } from "../support/server";
import { relativeFolderFiles } from "../../src/features/roadmaps/PackagePicker";
import { buildRoadmapForm } from "../../src/features/roadmaps/api";

const hash = "a".repeat(64);
const validImport = {
  id: 17,
  status: "validated",
  validation_report: {
    schema_version: 1,
    accepted: true,
    normalized_hash: hash,
    task_count: 158,
    resource_count: 12,
    exit_criterion_count: 5,
    issues: [],
  },
  semantic_diff: {
    summary: { added: 158, removed: 0, changed: 0, unchanged: 0 },
    tasks: { entries: [] },
    pass_contracts: { entries: [] },
    resources: { entries: [] },
    exit_criteria: { entries: [] },
  },
  failure_code: null,
};

function authAndVersions() {
  server.use(
    http.get("http://localhost:3000/api/v1/auth/session", () =>
      HttpResponse.json({ github_login: "fgomensoro", csrf_token: "c".repeat(43) }),
    ),
    http.get("http://localhost:3000/api/v1/roadmap-versions", () => HttpResponse.json([])),
  );
}

describe("roadmap import workspace", () => {
  it("stages a ZIP, shows progress and immutable validation evidence, then explicitly approves and activates", async () => {
    authAndVersions();
    let uploadContentType: string | null = null;
    let uploadCsrf: string | null = null;
    server.use(
      http.post("http://localhost:3000/api/v1/roadmap-imports", async ({ request }) => {
        uploadContentType = request.headers.get("Content-Type");
        uploadCsrf = request.headers.get("X-CSRF-Token");
        await delay(40);
        return HttpResponse.json(validImport, { status: 201 });
      }),
      http.post("http://localhost:3000/api/v1/roadmap-imports/17/approve", () =>
        HttpResponse.json({
          id: 8,
          version_key: "month-1-v1",
          version_number: 1,
          month_number: 1,
          state: "approved",
          mirror_status: "not_required",
          mirror_ref: null,
          mirror_error_code: null,
        }),
      ),
      http.post("http://localhost:3000/api/v1/roadmap-versions/8/activate", () =>
        HttpResponse.json({
          id: 8,
          version_key: "month-1-v1",
          version_number: 1,
          month_number: 1,
          state: "active",
          mirror_status: "not_required",
          mirror_ref: null,
          mirror_error_code: null,
        }),
      ),
    );
    const user = userEvent.setup();
    renderApp("/roadmaps");

    await screen.findByRole("heading", { name: "Roadmaps" });
    const zip = new File(["roadmap"], "month-1.zip");
    expect(buildRoadmapForm({ kind: "zip", file: zip }).get("package_kind")).toBe("zip");
    await user.upload(screen.getByLabelText("Roadmap ZIP"), zip);
    await user.click(screen.getByRole("button", { name: "Review package" }));
    expect(screen.getByRole("status")).toHaveTextContent("Uploading package…");

    expect(await screen.findByText("Validation passed")).toBeVisible();
    expect(uploadContentType).toMatch(/^multipart\/form-data; boundary=/u);
    expect(uploadCsrf).toBe("c".repeat(43));
    expect(screen.getByText(hash)).toBeVisible();
    expect(screen.getByText("158 tasks")).toBeVisible();
    expect(screen.getByText("158 added")).toBeVisible();

    const approve = screen.getByRole("button", { name: "Approve roadmap" });
    expect(approve).toBeDisabled();
    await user.click(screen.getByRole("checkbox", { name: /I reviewed the validation/i }));
    await user.click(approve);
    expect(await screen.findByText("Version month-1-v1 approved")).toBeVisible();

    await user.click(screen.getByRole("button", { name: "Activate Month 1" }));
    expect(await screen.findByText("Month 1 is active")).toBeVisible();
  });

  it("preserves browser-folder relative paths and can cancel a staged review", async () => {
    authAndVersions();
    let uploadCalled = false;
    server.use(
      http.post("http://localhost:3000/api/v1/roadmap-imports", () => {
        uploadCalled = true;
        return HttpResponse.json(validImport, { status: 201 });
      }),
    );
    const user = userEvent.setup();
    renderApp("/roadmaps");
    await screen.findByRole("heading", { name: "Roadmaps" });

    const readme = new File(["# Roadmap"], "README.md", { type: "text/markdown" });
    Object.defineProperty(readme, "webkitRelativePath", { value: "Roadmap/README.md" });
    const week = new File(["# Week"], "Week 1.md", { type: "text/markdown" });
    Object.defineProperty(week, "webkitRelativePath", { value: "Roadmap/Week 1.md" });
    expect(relativeFolderFiles([readme, week]).map((entry) => entry.path)).toEqual([
      "README.md",
      "Week 1.md",
    ]);
    await user.upload(screen.getByLabelText("Roadmap folder"), [readme, week]);
    await user.click(screen.getByRole("button", { name: "Review package" }));

    expect(await screen.findByText("Validation passed")).toBeVisible();
    expect(uploadCalled).toBe(true);
    expect(screen.getByText(hash)).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Cancel review" }));
    expect(screen.queryByText("Validation passed")).not.toBeInTheDocument();
  });

  it("shows exact validation issues and never offers approval or activation for a rejected package", async () => {
    authAndVersions();
    server.use(
      http.post("http://localhost:3000/api/v1/roadmap-imports", () =>
        HttpResponse.json(
          {
            id: 18,
            status: "rejected",
            validation_report: {
              accepted: false,
              issues: [{
                code: "roadmap_validation_failed",
                path: "Week 2.md",
                severity: "error",
                message: "Required Saturday assessment is missing.",
              }],
            },
            semantic_diff: {},
            failure_code: "validation_failed",
          },
          { status: 201 },
        ),
      ),
    );
    const user = userEvent.setup();
    renderApp("/roadmaps");
    await screen.findByRole("heading", { name: "Roadmaps" });
    await user.upload(screen.getByLabelText("Roadmap ZIP"), new File(["bad"], "bad.zip"));
    await user.click(screen.getByRole("button", { name: "Review package" }));

    expect(await screen.findByText("Required Saturday assessment is missing.")).toBeVisible();
    expect(screen.getByText("Week 2.md")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Approve roadmap" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Activate Month/i })).not.toBeInTheDocument();
  });

  it("makes mirror retry visible and explains the enforced Month 1 exit-review gate", async () => {
    authAndVersions();
    server.use(
      http.post("http://localhost:3000/api/v1/roadmap-imports", () =>
        HttpResponse.json(validImport, { status: 201 }),
      ),
      http.post("http://localhost:3000/api/v1/roadmap-imports/17/approve", () =>
        HttpResponse.json({
          id: 9,
          version_key: "month-2-v1",
          version_number: 2,
          month_number: 2,
          state: "approved",
          mirror_status: "failed",
          mirror_ref: null,
          mirror_error_code: "write_failed",
        }),
      ),
      http.post("http://localhost:3000/api/v1/roadmap-imports/9/mirror/retry", () =>
        HttpResponse.json({
          id: 9,
          version_key: "month-2-v1",
          version_number: 2,
          month_number: 2,
          state: "approved",
          mirror_status: "synced",
          mirror_ref: "commit-abc",
          mirror_error_code: null,
        }),
      ),
      http.post("http://localhost:3000/api/v1/roadmap-versions/9/activate", () =>
        HttpResponse.json(
          { title: "Roadmap state conflict", status: 409, detail: "Roadmap state conflict.", code: "roadmap_state_conflict" },
          { status: 409 },
        ),
      ),
    );
    const user = userEvent.setup();
    renderApp("/roadmaps");
    await screen.findByRole("heading", { name: "Roadmaps" });
    await user.upload(screen.getByLabelText("Roadmap ZIP"), new File(["month2"], "month-2.zip"));
    await user.click(screen.getByRole("button", { name: "Review package" }));
    await screen.findByText("Validation passed");
    await user.click(screen.getByRole("checkbox", { name: /I reviewed the validation/i }));
    await user.click(screen.getByRole("button", { name: "Approve roadmap" }));

    expect(await screen.findByText("Private mirror failed: write_failed")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Retry private mirror" }));
    expect(await screen.findByText("Private mirror synced · commit-abc")).toBeVisible();
    expect(screen.getByText(/Month 1 exit review must be complete/i)).toBeVisible();

    await user.click(screen.getByRole("button", { name: "Activate Month 2" }));
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("Month 2 remains locked"),
    );
  });

  it("keeps active and superseded history visible and resumes an approved version after reload", async () => {
    authAndVersions();
    const superseded = {
      id: 5,
      version_key: "month-1-v1",
      version_number: 1,
      month_number: 1,
      state: "superseded",
      mirror_status: "not_required",
      mirror_ref: null,
      mirror_error_code: null,
    };
    const approved = { ...superseded, id: 6, version_key: "month-1-v2", version_number: 2, state: "approved" };
    server.use(
      http.get("http://localhost:3000/api/v1/roadmap-versions", () =>
        HttpResponse.json([approved, superseded]),
      ),
      http.post("http://localhost:3000/api/v1/roadmap-versions/6/activate", () =>
        HttpResponse.json({ ...approved, state: "active" }),
      ),
    );
    const user = userEvent.setup();
    renderApp("/roadmaps");

    expect(await screen.findByText("month-1-v1")).toBeVisible();
    expect(screen.getByText("month-1-v2")).toBeVisible();
    expect(screen.getByText("superseded")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Activate month-1-v2" }));

    expect(await screen.findByText("active")).toBeVisible();
  });
});
