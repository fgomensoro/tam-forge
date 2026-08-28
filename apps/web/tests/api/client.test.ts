import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import {
  ApiProblemError,
  apiRequest,
  registerUnauthorizedHandler,
  setCsrfToken,
} from "../../src/api/client";
import { server } from "../support/server";

describe("API client", () => {
  it("includes browser credentials and the in-memory CSRF token on mutations", async () => {
    let credentials: string | undefined;
    let csrf: string | null = null;
    server.use(
      http.post("http://localhost:3000/api/v1/example", ({ request }) => {
        credentials = request.credentials;
        csrf = request.headers.get("X-CSRF-Token");
        return HttpResponse.json({ saved: true });
      }),
    );
    setCsrfToken("csrf-only-in-memory");

    await expect(
      apiRequest<{ saved: boolean }>("/api/v1/example", {
        method: "POST",
        body: JSON.stringify({ answer: 42 }),
      }),
    ).resolves.toEqual({ saved: true });

    expect(credentials).toBe("include");
    expect(csrf).toBe("csrf-only-in-memory");
    expect(localStorage).toHaveLength(0);
    expect(sessionStorage).toHaveLength(0);
  });

  it("turns RFC problem documents into safe typed errors", async () => {
    server.use(
      http.get("http://localhost:3000/api/v1/broken", () =>
        HttpResponse.json(
          {
            type: "https://tamforge.local/problems/auth_unavailable",
            title: "Authentication unavailable",
            status: 503,
            detail: "Authentication is temporarily unavailable.",
            code: "auth_unavailable",
          },
          { status: 503, headers: { "Content-Type": "application/problem+json" } },
        ),
      ),
    );

    const error = await apiRequest("/api/v1/broken").catch((caught) => caught);

    expect(error).toBeInstanceOf(ApiProblemError);
    expect(error).toMatchObject({
      status: 503,
      code: "auth_unavailable",
      message: "Authentication is temporarily unavailable.",
    });
  });

  it("notifies the auth boundary when a session expires", async () => {
    const onUnauthorized = vi.fn();
    const unregister = registerUnauthorizedHandler(onUnauthorized);
    server.use(
      http.get("http://localhost:3000/api/v1/protected", () =>
        HttpResponse.json(
          {
            type: "https://tamforge.local/problems/unauthenticated",
            title: "Authentication required",
            status: 401,
            detail: "Authentication is required.",
            code: "unauthenticated",
          },
          { status: 401 },
        ),
      ),
    );

    await expect(apiRequest("/api/v1/protected")).rejects.toMatchObject({ status: 401 });
    expect(onUnauthorized).toHaveBeenCalledOnce();
    unregister();
  });

  it("never sends session credentials or CSRF to a different origin", async () => {
    setCsrfToken("private-csrf");

    await expect(
      apiRequest("https://unexpected.example/api", { method: "POST", body: "{}" }),
    ).rejects.toThrow("same-origin");
  });
});
