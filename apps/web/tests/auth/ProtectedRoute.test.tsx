import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { renderApp } from "../support/renderApp";
import { server } from "../support/server";

describe("protected application shell", () => {
  it("redirects a logged-out visitor to the GitHub sign-in screen", async () => {
    server.use(
      http.get("http://localhost:3000/api/v1/auth/session", () =>
        HttpResponse.json({ title: "Authentication required", status: 401 }, { status: 401 }),
      ),
    );

    renderApp();

    const link = await screen.findByRole("link", { name: "Continue with GitHub" });
    expect(link).toHaveAttribute("href", "/api/v1/auth/login");
    expect(screen.queryByRole("heading", { name: "Today" })).not.toBeInTheDocument();
  });

  it("shows a safe callback error without exposing provider details", async () => {
    server.use(
      http.get("http://localhost:3000/api/v1/auth/session", () =>
        HttpResponse.json({ title: "Authentication required", status: 401 }, { status: 401 }),
      ),
    );

    renderApp("/login?auth_error=identity_provider_error");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "GitHub sign-in is temporarily unavailable. Please try again.",
    );
  });

  it("shows the authenticated owner, explicit inactive AI role, and logout", async () => {
    server.use(
      http.get("http://localhost:3000/api/v1/auth/session", () =>
        HttpResponse.json({ github_login: "fgomensoro", csrf_token: "c".repeat(43) }),
      ),
      http.post("http://localhost:3000/api/v1/auth/logout", () =>
        new HttpResponse(null, { status: 204 }),
      ),
    );
    const user = userEvent.setup();

    renderApp();

    expect(await screen.findByText("@fgomensoro")).toBeVisible();
    expect(screen.getByText("AI role · None")).toBeVisible();
    expect(screen.getByRole("navigation", { name: "Primary" })).toBeVisible();

    await user.click(screen.getByRole("button", { name: "Log out" }));
    expect(await screen.findByRole("link", { name: "Continue with GitHub" })).toBeVisible();
  });
});
