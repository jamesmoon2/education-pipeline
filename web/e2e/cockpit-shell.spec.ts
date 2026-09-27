import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
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
