import type { BrowserContext } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { e2eEnvironment } from "../../playwright.config";

const root = fileURLToPath(new URL("../../../..", import.meta.url));

interface SeededSession {
  base_url: string;
  session_cookie: string;
  session_token: string;
  csrf_cookie: string;
  csrf_token: string;
  owner_github_id: number;
}

export function seedTestSession(): SeededSession {
  if (e2eEnvironment.TAMFORGE_ENV !== "test") {
    throw new Error("The browser session fixture is available only in TAMFORGE_ENV=test.");
  }
  const output = execFileSync(
    "uv",
    ["run", "python", "scripts/dev/seed_foundation_demo.py"],
    {
      cwd: root,
      encoding: "utf8",
      env: { ...process.env, ...e2eEnvironment },
    },
  );
  return JSON.parse(output.trim().split("\n").at(-1) ?? "") as SeededSession;
}

export async function authenticate(context: BrowserContext, session: SeededSession) {
  await context.addCookies([
    {
      name: session.session_cookie,
      value: session.session_token,
      domain: "127.0.0.1",
      path: "/api/v1",
      httpOnly: true,
      sameSite: "Lax",
    },
    {
      name: session.csrf_cookie,
      value: session.csrf_token,
      domain: "127.0.0.1",
      path: "/api/v1/auth/session",
      httpOnly: true,
      sameSite: "Lax",
    },
  ]);
}
