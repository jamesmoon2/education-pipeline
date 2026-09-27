import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { writeFileSync } from "node:fs";
import { join } from "node:path";
import { bootDaemon, type DaemonHandle } from "./helpers/daemon";

// Phase 6 T60 (decision 2): the rail-footer theme select stamps
// <html data-theme>, persists the choice per browser (localStorage
// `ep.theme`), survives a reload, and the library passes axe in forced dark.
// "Match system" removes the attribute and the stored key.

let handle: DaemonHandle;

test.beforeAll(async () => {
  handle = await bootDaemon("ep-e2e-cockpit-shell-", {
    setup: (ws) => {
      writeFileSync(
        join(ws, "topics", "shell-topic.toml"),
        'schema_version = 1\nid = "shell-topic"\ntitle = "Shell Topic"\n',
        "utf-8",
      );
    },
  });
});

test.afterAll(() => {
  handle?.daemon.kill();
});

test("Dark stamps html[data-theme], survives a reload and passes axe; Match system clears it", async ({
  page,
}) => {
  // A light system preference, so any dark rendering below comes from the
  // explicit choice and not from the prefers-color-scheme media query.
  await page.emulateMedia({ colorScheme: "light" });
  await page.goto(`${handle.baseURL}/`);
  await expect(page.getByRole("link", { name: "shell-topic", exact: true })).toBeVisible();

  const html = page.locator("html");
  const theme = page.getByRole("combobox", { name: "Theme" });
  await expect(theme).toHaveValue("system");
  await expect(html).not.toHaveAttribute("data-theme");
  const canvas = () =>
    page.evaluate(() => getComputedStyle(document.body).backgroundColor);
  const lightCanvas = await canvas();

  await theme.selectOption({ label: "Dark" });
  await expect(html).toHaveAttribute("data-theme", "dark");
  expect(await page.evaluate(() => localStorage.getItem("ep.theme"))).toBe("dark");
  await expect.poll(canvas).not.toBe(lightCanvas);

  await page.reload();
  await expect(page.getByRole("link", { name: "shell-topic", exact: true })).toBeVisible();
  await expect(html).toHaveAttribute("data-theme", "dark");
  await expect(page.getByRole("combobox", { name: "Theme" })).toHaveValue("dark");
  await expect.poll(canvas).not.toBe(lightCanvas);

  const axe = await new AxeBuilder({ page }).analyze();
  const serious = axe.violations.filter(
    (v) => v.impact === "serious" || v.impact === "critical",
  );
  expect(serious, JSON.stringify(serious, null, 2)).toEqual([]);

  await page.getByRole("combobox", { name: "Theme" }).selectOption({ label: "Match system" });
  await expect(html).not.toHaveAttribute("data-theme");
  expect(await page.evaluate(() => localStorage.getItem("ep.theme"))).toBeNull();
  await expect.poll(canvas).toBe(lightCanvas);

  await page.reload();
  await expect(page.getByRole("link", { name: "shell-topic", exact: true })).toBeVisible();
  await expect(html).not.toHaveAttribute("data-theme");
  await expect(page.getByRole("combobox", { name: "Theme" })).toHaveValue("system");
});

// T62b fix: a rail toast must be readable in either theme. The toast region
// renders inside the app rail, whose own `color` is the rail's near-white
// text; a toast paints the page surface, so any toast text that inherits the
// rail colour disappears on the light surface. The rail toasts a job it has
// seen active that then turns terminal, and a real job's timing decides
// whether the rail ever sees it active, so the test serves the workspace-wide
// jobs list itself: active until the rail shows it running, terminal after.
// `/v1/events` answers 404, so the client polls for the life of the page and
// no stream notice can interleave with the phases; everything else hits the
// real daemon.

type JobStatus = "running" | "succeeded" | "failed";

function railJob(id: string, stage: string, status: JobStatus) {
  const ended = status !== "running";
  return {
    id,
    topic_id: "shell-topic",
    stage,
    provider: "claude-code",
    model: null,
    effort: null,
    status,
    created_at: "2026-01-01T00:00:00Z",
    started_at: "2026-01-01T00:00:01Z",
    ended_at: ended ? "2026-01-01T00:01:00Z" : null,
    exit_code: ended ? (status === "succeeded" ? 0 : 1) : null,
    error: status === "failed" ? "provider exited with status 1" : null,
  };
}

async function raiseRailToasts(page: Page) {
  let phase: "active" | "terminal" = "active";
  await page.route("**/v1/events", (route) =>
    route.fulfill({ status: 404, json: { error: { code: "not_found", message: "no stream" } } }),
  );
  await page.route(
    (url) => url.pathname === "/v1/jobs" && url.search === "",
    (route) => {
      if (route.request().method() !== "GET") return route.continue();
      const jobs =
        phase === "active"
          ? [railJob("job-ok", "draft", "running"), railJob("job-bad", "factcheck", "running")]
          : [railJob("job-ok", "draft", "succeeded"), railJob("job-bad", "factcheck", "failed")];
      return route.fulfill({ json: { jobs } });
    },
  );

  await page.goto(`${handle.baseURL}/`);
  await expect(page.getByRole("link", { name: "shell-topic", exact: true })).toBeVisible();
  // The rail has now recorded both jobs as active.
  await expect(page.getByRole("navigation", { name: "Active jobs" })).toContainText(
    "2 jobs running",
  );

  phase = "terminal";
  // With the stream down a visible `visibilitychange` resumes every poller at
  // once; if a jobs fetch was already in flight, the next 5 s tick serves the
  // terminal list instead, hence the longer timeouts below.
  await page.evaluate(() => document.dispatchEvent(new Event("visibilitychange")));

  const region = page.locator(".toast-region");
  const success = region.getByRole("status");
  const failure = region.getByRole("alert");
  await expect(success).toBeVisible({ timeout: 10_000 });
  await expect(success).toContainText("The draft stage finished on shell-topic");
  await expect(failure).toBeVisible({ timeout: 10_000 });
  await expect(failure).toContainText("The factcheck stage failed on shell-topic");
}

for (const theme of ["light", "dark"] as const) {
  test(`rail toasts pass axe colour contrast in the ${theme} theme`, async ({ page }) => {
    // A light system preference throughout: the light case is the default
    // (no stored choice) and the dark case is the T60 explicit choice.
    await page.emulateMedia({ colorScheme: "light" });
    // Tall enough that the library's content ends well above the
    // bottom-anchored toast region, so every toast line box has the same
    // page beneath it (see the incomplete check below).
    await page.setViewportSize({ width: 1280, height: 1600 });
    if (theme === "dark") {
      await page.addInitScript(() => localStorage.setItem("ep.theme", "dark"));
    }

    await raiseRailToasts(page);
    if (theme === "dark") await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    else await expect(page.locator("html")).not.toHaveAttribute("data-theme");

    const axe = await new AxeBuilder({ page })
      .include(".toast-region")
      .withRules(["color-contrast"])
      .analyze();
    // A verdict on every toast text node: axe leaves text "incomplete" when
    // its line boxes sit over different page elements, which would let the
    // rule pass without judging the toast at all.
    const undecided = axe.incomplete.flatMap((rule) =>
      rule.nodes.map((node) => ({ target: node.target, summary: node.failureSummary })),
    );
    expect(undecided, JSON.stringify(undecided, null, 2)).toEqual([]);
    const checked = [...axe.passes, ...axe.violations].flatMap((rule) => rule.nodes);
    expect(checked.length, "axe evaluated no toast text").toBeGreaterThan(0);
    const failures = axe.violations.flatMap((rule) =>
      rule.nodes.map((node) => ({ target: node.target, summary: node.failureSummary })),
    );
    expect(failures, JSON.stringify(failures, null, 2)).toEqual([]);
  });
}
