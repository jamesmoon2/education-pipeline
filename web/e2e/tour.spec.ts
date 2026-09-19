import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { bootDaemon, type DaemonHandle } from "./helpers/daemon";

// Guided tour acceptance: the tour is reachable from the dock and from a
// ?tour=1 deep link, hops routes to anchor each step, is fully keyboard
// operable, records completion so it never re-launches on its own, and its
// dialog passes the accessibility gate over a live anchored step.

let handle: DaemonHandle;

test.beforeAll(async () => {
  handle = await bootDaemon("ep-e2e-tour-", {
    setup: (ws) => {
      writeFileSync(
        join(ws, "topics", "tour-topic.toml"),
        'schema_version = 1\nid = "tour-topic"\ntitle = "Tour Topic"\n',
        "utf-8",
      );
      mkdirSync(join(ws, "config"), { recursive: true });
      writeFileSync(join(ws, "config", "model-plan.toml"), 'provider = "manual"\n', "utf-8");
    },
  });
  execFileSync(
    "python3",
    ["-m", "education_pipeline", "-C", handle.ws, "create", "tour-topic", "--legacy-markdown"],
    { cwd: resolve(import.meta.dirname, "../..") },
  );
});

test.afterAll(() => {
  handle?.daemon.kill();
});

test("the workbench tour walks the shell, hops routes, and remembers completion", async ({
  page,
}) => {
  await page.goto(`${handle.baseURL}/`);
  // Never auto-launches: the learner opts in.
  await expect(page.getByRole("dialog")).toHaveCount(0);

  await page.getByRole("button", { name: "Take the tour" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toHaveAttribute("aria-modal", "true");
  await expect(dialog).toContainText("Your course workbench");
  await expect(page.getByText("Step 1 of 8")).toBeVisible();

  // Step 2 anchors to the dock's primary navigation.
  await page.getByRole("button", { name: "Next" }).click();
  await expect(dialog).toContainText("Four places to be");
  await expect(dialog).toHaveAttribute("data-anchored", "true");
  await expect(page.getByTestId("tour-spotlight")).toBeVisible();

  const axe = await new AxeBuilder({ page }).analyze();
  const serious = axe.violations.filter(
    (v) => v.impact === "serious" || v.impact === "critical",
  );
  expect(serious, JSON.stringify(serious, null, 2)).toEqual([]);

  // Step 3 stays on the library and spotlights the course table.
  await page.keyboard.press("ArrowRight");
  await expect(dialog).toContainText("The course library");
  await expect(dialog).toHaveAttribute("data-anchored", "true");

  // Step 4 hops to the new-course wizard.
  await page.keyboard.press("ArrowRight");
  await expect(dialog).toContainText("Five steps to a course");
  await expect(page).toHaveURL(/\/new$/);
  await expect(dialog).toHaveAttribute("data-anchored", "true");

  // Back returns to the library step (and the library route).
  await page.getByRole("button", { name: "Back" }).click();
  await expect(dialog).toContainText("The course library");
  await expect(page).toHaveURL(new RegExp(`${handle.baseURL}/$`));

  // Run to the end: settings hop, then the closing card.
  for (let i = 0; i < 4; i++) await page.keyboard.press("ArrowRight");
  await expect(dialog).toContainText("Light, dark, or follow the system");
  await expect(page).toHaveURL(/\/settings$/);
  await page.keyboard.press("ArrowRight");
  await expect(dialog).toContainText("Everything stays on this device");
  await expect(page.getByRole("button", { name: "Finish" })).toBeVisible();
  await page.getByRole("button", { name: "Finish" }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);

  const remembered = await page.evaluate(() => localStorage.getItem("ep.tour.completed"));
  expect(remembered).toBe("done");
});

test("a ?tour=1 deep link starts the tour once and cleans the address bar", async ({ page }) => {
  await page.goto(`${handle.baseURL}/settings?tour=1`);
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("Your course workbench");
  await expect(page).toHaveURL(new RegExp(`${handle.baseURL}/settings$`));
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await page.reload();
  await expect(page.getByRole("dialog")).toHaveCount(0);
});

test("the run board offers its own tour over the learning thread", async ({ page }) => {
  await page.goto(`${handle.baseURL}/topics/tour-topic`);
  await page.getByRole("button", { name: "Explain this board" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("What to do next");
  await expect(dialog).toHaveAttribute("data-anchored", "true");
  await page.getByRole("button", { name: "Next" }).click();
  await expect(dialog).toContainText("The learning thread");
  await expect(dialog).toHaveAttribute("data-anchored", "true");
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
});

test("the theme control pins dark, survives reload, and returns to system", async ({ page }) => {
  await page.goto(`${handle.baseURL}/`);
  await page.getByRole("radio", { name: "Dark" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.getByRole("radio", { name: "System" }).click();
  await expect(page.locator("html")).not.toHaveAttribute("data-theme", /.+/);
});
