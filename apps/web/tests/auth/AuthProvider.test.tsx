import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { apiRequest } from "../../src/api/client";
import { AuthProvider, useAuth } from "../../src/auth/AuthProvider";
import { server } from "../support/server";

function AuthProbe() {
  const auth = useAuth();
  return (
    <div>
      <p>{auth.status}</p>
      <p>{auth.session?.github_login ?? "no owner"}</p>
      <button type="button" onClick={() => void auth.logout()}>
        Log out
      </button>
      <button type="button" onClick={() => void apiRequest("/api/v1/protected").catch(() => undefined)}>
        Protected action
      </button>
    </div>
  );
}

function renderProvider() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <AuthProbe />
      </AuthProvider>
    </QueryClientProvider>,
  );
}

it("loads the owner, logs out with CSRF, and never persists browser secrets", async () => {
  const csrfToken = "c".repeat(43);
  let logoutCsrf: string | null = null;
  server.use(
    http.get("http://localhost:3000/api/v1/auth/session", () =>
      HttpResponse.json({ github_login: "fgomensoro", csrf_token: csrfToken }),
    ),
    http.post("http://localhost:3000/api/v1/auth/logout", ({ request }) => {
      logoutCsrf = request.headers.get("X-CSRF-Token");
      return new HttpResponse(null, { status: 204 });
    }),
  );
  const user = userEvent.setup();
  renderProvider();

  expect(await screen.findByText("fgomensoro")).toBeVisible();
  await user.click(screen.getByRole("button", { name: "Log out" }));

  await waitFor(() => expect(screen.getByText("unauthenticated")).toBeVisible());
  expect(logoutCsrf).toBe(csrfToken);
  expect(localStorage).toHaveLength(0);
  expect(sessionStorage).toHaveLength(0);
});

it("returns to the signed-out state when any request reports an expired session", async () => {
  server.use(
    http.get("http://localhost:3000/api/v1/auth/session", () =>
      HttpResponse.json({ github_login: "fgomensoro", csrf_token: "c".repeat(43) }),
    ),
    http.get("http://localhost:3000/api/v1/protected", () =>
      HttpResponse.json({ title: "Authentication required", status: 401 }, { status: 401 }),
    ),
  );
  const user = userEvent.setup();
  renderProvider();

  expect(await screen.findByText("fgomensoro")).toBeVisible();
  await user.click(screen.getByRole("button", { name: "Protected action" }));

  expect(await screen.findByText("unauthenticated")).toBeVisible();
  expect(screen.getByText("no owner")).toBeVisible();
});
