import { defineConfig } from "@playwright/test";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../..", import.meta.url));
const databaseUrl = process.env.TEST_DATABASE_URL
  ?? "postgresql+asyncpg://tamforge:tamforge@127.0.0.1:54329/tamforge_test";

export const e2eEnvironment = {
  TAMFORGE_ENV: "test",
  TEST_DATABASE_URL: databaseUrl,
  TAMFORGE_DATABASE_URL: databaseUrl,
  TAMFORGE_GITHUB_USER_ID: "102269369",
  TAMFORGE_GITHUB_CLIENT_ID: "test-client",
  TAMFORGE_GITHUB_CLIENT_SECRET: "test-client-secret",
  TAMFORGE_SESSION_SIGNING_SECRET: "test-session-signing-secret-0123456789abcdef",
  TAMFORGE_CORS_ORIGINS: '["http://127.0.0.1:5173"]',
  TAMFORGE_SECURE_COOKIES: "false",
  TAMFORGE_OBJECT_STORE_ENDPOINT: "http://127.0.0.1:9000",
  TAMFORGE_OBJECT_STORE_BUCKET: "tam-forge-e2e",
  TAMFORGE_OBJECT_STORE_REGION: "us-east-1",
  TAMFORGE_OBJECT_STORE_ADDRESSING_STYLE: "path",
  TAMFORGE_OBJECT_STORE_ACCESS_KEY: "tamforge",
  TAMFORGE_OBJECT_STORE_SECRET_KEY: "tamforge-local",
  TAMFORGE_ROADMAP_CONFIG_DIR: `${root}/config`,
};

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: "http://127.0.0.1:5173",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  webServer: [
    {
      command: "uv run uvicorn tamforge_backend.main:app --host 127.0.0.1 --port 8000",
      cwd: root,
      env: { ...process.env, ...e2eEnvironment },
      url: "http://127.0.0.1:8000/healthz",
      reuseExistingServer: false,
      timeout: 30_000,
    },
    {
      command: "pnpm --filter @tam-forge/web dev --host 127.0.0.1 --port 5173",
      cwd: root,
      env: process.env,
      url: "http://127.0.0.1:5173",
      reuseExistingServer: false,
      timeout: 30_000,
    },
  ],
});
