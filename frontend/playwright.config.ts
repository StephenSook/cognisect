import { defineConfig, devices } from "@playwright/test";

import { E2E_APP_URL, E2E_BACKEND_URL } from "./e2e-settings";

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: false,
  workers: 1,
  timeout: 60_000,
  reporter: "list",
  use: {
    baseURL: E2E_APP_URL,
    trace: "retain-on-failure",
  },
  projects: [
    {
      name: "desktop",
      use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } },
    },
    {
      name: "mobile",
      use: { ...devices["Pixel 7"], viewport: { width: 390, height: 844 } },
    },
  ],
  webServer: [
    {
      command: "uv run python backend/tests/run_frontend_server.py",
      cwd: "..",
      env: {
        UV_CACHE_DIR:
          process.env.UV_CACHE_DIR ?? "/private/tmp/cognisect-uv-cache",
      },
      url: `${E2E_BACKEND_URL}/health`,
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      command: "npm run start -- --hostname 127.0.0.1 --port 3100",
      env: {
        COGNISECT_APP_URL: E2E_APP_URL,
        COGNISECT_BACKEND_URL: E2E_BACKEND_URL,
        COGNISECT_FRONTEND_ENV: "test",
      },
      url: E2E_APP_URL,
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
});
