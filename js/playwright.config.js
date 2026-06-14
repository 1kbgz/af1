import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "tests",
  testIgnore: process.env.CI ? ["**/visual*"] : [],
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: [
    ["line"],
    ["html", { outputFile: "playwright-report/index.html", open: "never" }],
    ["junit", { outputFile: "junit.xml" }],
  ],
  use: {
    baseURL: "http://127.0.0.1:8510",
    trace: "on-first-retry",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: {
<<<<<<< before updating
    command: "python -m af1.testing.test_server",
    url: "http://127.0.0.1:8510/api/health",
=======
    command: "pnpm run start:tests",
    url: "http://127.0.0.1:3000",
>>>>>>> after updating
    reuseExistingServer: !process.env.CI,
    timeout: 30 * 1000,
  },
});
