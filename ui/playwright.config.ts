import { defineConfig, devices } from "@playwright/test";

const UI_PORT = 3100;
const API_PORT = 8000;
const UI_URL = `http://localhost:${UI_PORT}`;
const API_URL = `http://localhost:${API_PORT}`;
const REAL_BACKEND = process.env.E2E_REAL_BACKEND === "1";

export default defineConfig({
  testDir: "./tests/e2e",
  forbidOnly: true,
  fullyParallel: true,
  retries: 0,
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: UI_URL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "mocked",
      testMatch: /registration\.spec\.ts/,
      use: { ...devices["Desktop Chrome"] },
    },
    {
      // Runs against the API on the in-memory store: `E2E_REAL_BACKEND=1 npm run e2e`.
      name: "real-backend",
      testMatch: /real-backend\.spec\.ts/,
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: [
    {
      command: "node .next/standalone/server.js",
      url: UI_URL,
      reuseExistingServer: !process.env.CI,
      env: {
        PORT: String(UI_PORT),
        HOSTNAME: "localhost",
        API_BASE_URL: API_URL,
        ASSISTANT_ENABLED: "true",
        BOT_CHECK_STUB_TOKEN: "local",
      },
    },
    ...(REAL_BACKEND
      ? [
          {
            command: `uv run --frozen uvicorn app.main:create_app --factory --port ${API_PORT}`,
            cwd: "..",
            url: `${API_URL}/healthz/live`,
            reuseExistingServer: !process.env.CI,
            env: {
              CUSTOMER_STORE: "memory",
              ALLOW_LOCAL_ADAPTERS: "true",
              EMAIL_ALLOW_RESERVED_DOMAINS: "true",
              ADVISOR_ENABLED: "false",
              ASSISTANT_ENABLED: "false",
              CORS_ALLOW_ORIGINS: UI_URL,
              PII_HASH_KEY: "e2e-local-key-not-for-deployment",
            },
          },
        ]
      : []),
  ],
});
