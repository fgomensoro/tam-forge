import { screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { renderApp } from "./support/renderApp";
import { server } from "./support/server";

it("renders the private TAM Forge shell in English", async () => {
  server.use(
    http.get("http://localhost:3000/api/v1/auth/session", () =>
      HttpResponse.json({ github_login: "fgomensoro", csrf_token: "c".repeat(43) }),
    ),
  );

  renderApp();

  expect(await screen.findByRole("heading", { name: "Today" })).toBeVisible();
  expect(screen.getByText("AI role · None")).toBeVisible();
});
