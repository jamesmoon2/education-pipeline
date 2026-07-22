import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { bootDaemon, type DaemonHandle } from "./helpers/daemon";

// Cockpit build-freshness banner acceptance (spec: cockpit-build-freshness):
// the real e2e daemon always reports `ok` (bootDaemon sets EP_WEB_DIST), so
// the stale state is faked via page.route interception of /v1/health.

let handle: DaemonHandle;

test.beforeAll(async () => {
  handle = await bootDaemon("ep-e2e-build-banner-");
});

test.afterAll(() => {
  handle?.daemon.kill();
});

const staleHealth = {
  version: "test",
  ok: true,
  cockpit_build: { status: "stale", build_id: "e2e-build-1" },
};

test("stale build shows an accessible, dismissible banner", async ({ page }) => {
  await page.route("**/v1/health", (route) => route.fulfill({ json: staleHealth }));
  await page.goto(handle.baseURL);

  const banner = page.getByRole("status").filter({ hasText: /older than its source/i });
  await expect(banner).toBeVisible();

  const results = await new AxeBuilder({ page }).analyze();
  const serious = results.violations.filter(
    (v) => v.impact === "serious" || v.impact === "critical",
  );
  expect(serious, JSON.stringify(serious, null, 2)).toEqual([]);

  await banner.getByRole("button", { name: /dismiss/i }).click();
  await expect(banner).toBeHidden();

  // Dismissal is keyed to the build id and survives reload. The route
  // handler still intercepts /v1/health after reload (Playwright routes
  // persist across reloads on the same page), so this asserts localStorage
  // dismissal — not the route going away — hides the banner.
  await page.reload();
  await expect(
    page.getByRole("status").filter({ hasText: /older than its source/i }),
  ).toBeHidden();
});

test("fresh build shows no banner", async ({ page }) => {
  await page.goto(handle.baseURL);
  await expect(
    page.getByRole("status").filter({ hasText: /older than its source/i }),
  ).toBeHidden();
});
