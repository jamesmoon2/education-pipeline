import { defineConfig } from "@playwright/test";

// Sandboxed CI images sometimes pre-install a Chromium build that does not
// match this package's pinned Playwright version; point at it explicitly
// with PLAYWRIGHT_CHROMIUM_EXECUTABLE instead of re-downloading browsers.
const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE;

export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  use: { headless: true, launchOptions: executablePath ? { executablePath } : {} },
});
