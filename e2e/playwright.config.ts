import { defineConfig } from "@playwright/test";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const MOCK_PORT = process.env.E2E_MOCK_PORT || "4173";
const baseURL = `http://127.0.0.1:${MOCK_PORT}`;

export default defineConfig({
  testDir: "./tests",
  // Shared in-memory mock server: parallel tests would race on /__e2e/reset and status overrides.
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL,
    trace: "on-first-retry",
  },
  webServer: {
    command: "node server/mock-backend.mjs",
    cwd: __dirname,
    url: `${baseURL}/__e2e/health`,
    reuseExistingServer: !process.env.CI,
    env: {
      ...process.env,
      E2E_MOCK_PORT: MOCK_PORT,
    },
  },
  projects: [
    {
      name: "chromium",
      use: { browserName: "chromium" },
    },
  ],
});
