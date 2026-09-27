import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { existsSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { bootDaemon, type DaemonHandle } from "./helpers/daemon";

// T61 keyboard shortcuts (plan decisions 4-8): a keyboard-only walk from the
// library to a course waiting for review and on to its stage, proving that
// typing in a field triggers nothing, that `a` only moves focus (approval
// still takes Enter), and that the `?` overlay passes axe and hands focus
// back on Escape.

const REPO_ROOT = resolve(import.meta.dirname, "../..");

let handle: DaemonHandle;

function cli(...args: string[]): string {
  return execFileSync("python3", ["-m", "education_pipeline", "-C", handle.ws, ...args], {
    cwd: REPO_ROOT,
    encoding: "utf-8",
  });
}

test.beforeAll(async () => {
  handle = await bootDaemon("ep-e2e-keyboard-", {
    setup: (ws) => {
      for (const topic of ["kb-busy", "kb-review"]) {
        writeFileSync(
          join(ws, "topics", `${topic}.toml`),
          `schema_version = 1\nid = "${topic}"\ntitle = "Keyboard ${topic}"\n`,
          "utf-8",
        );
      }
    },
  });
  // kb-busy waits on its spec response; kb-review waits on approval of it.
  for (const topic of ["kb-busy", "kb-review"]) {
    cli("create", topic, "--legacy-markdown");
    cli("advance", topic);
  }
  writeFileSync(
    join(handle.ws, "runs", "kb-review", "responses", "spec.response.md"),
    "# Spec\n\nA spec response waiting for review.\n",
    "utf-8",
  );
  expect(cli("status", "kb-review")).toContain("Next: approve (spec)");
});

test.afterAll(() => {
  handle?.daemon.kill();
});

test("keyboard walk: library → filter → next review → stage → a focuses approve → ? overlay", async ({
  page,
}) => {
  await page.goto(`${handle.baseURL}/`);
  const filter = page.getByRole("searchbox", { name: "Filter courses" });
  await expect(filter).toBeVisible();
  await expect(page.getByRole("link", { name: "kb-review", exact: true })).toBeVisible();

  // `/` focuses the library filter and types nothing into it.
  await page.keyboard.press("/");
  await expect(filter).toBeFocused();
  await expect(filter).toHaveValue("");

  // Typing the shortcut letters inside the field only types.
  await page.keyboard.type("nar/?");
  await expect(filter).toHaveValue("nar/?");
  await expect(page).toHaveURL(`${handle.baseURL}/`);
  await expect(page.getByRole("dialog")).toHaveCount(0);

  // Clear the field and leave it, by keyboard.
  await page.keyboard.press("ControlOrMeta+a");
  await page.keyboard.press("Backspace");
  await expect(filter).toHaveValue("");
  await page.keyboard.press("Shift+Tab");
  await expect(filter).not.toBeFocused();
  await expect(page.getByRole("button", { name: "Import profile…", exact: true })).toBeFocused();

  // `r` opens the next course needing review on its approve deep link.
  await page.keyboard.press("r");
  await expect(page).toHaveURL(`${handle.baseURL}/topics/kb-review/stages/spec?tab=response`);
  await expect(page.getByRole("tab", { name: /^response/ })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  const approve = page.getByRole("button", { name: "Approve spec", exact: true });
  await expect(approve).toBeVisible();
  // The run status (which names the next stage) has loaded once this shows.
  await expect(
    page.getByRole("button", { name: "Rerun with provider…", exact: true }),
  ).toBeVisible();

  // `n` opens the stage the run's next action names.
  await page.keyboard.press("n");
  await expect(page).toHaveURL(`${handle.baseURL}/topics/kb-review/stages/spec`);

  // `a` moves focus to the approve button and never presses it.
  await page.keyboard.press("a");
  await expect(approve).toBeFocused();

  // `?` opens the overlay; axe runs with it open.
  await page.keyboard.press("?");
  const overlay = page.getByRole("dialog", { name: "Keyboard shortcuts" });
  await expect(overlay).toBeVisible();
  await expect(overlay).toHaveAttribute("aria-modal", "true");
  await expect(
    overlay.getByRole("checkbox", { name: "Single-key shortcuts", exact: true }),
  ).toBeChecked();
  const results = await new AxeBuilder({ page }).analyze();
  const serious = results.violations.filter(
    (v) => v.impact === "serious" || v.impact === "critical",
  );
  expect(serious, JSON.stringify(serious, null, 2)).toEqual([]);

  // Escape closes it and restores focus to where it was.
  await page.keyboard.press("Escape");
  await expect(overlay).toHaveCount(0);
  await expect(approve).toBeFocused();

  // Nothing was approved along the way: the gate is still waiting.
  await expect(page.getByText("Approved spec.")).toHaveCount(0);
  await expect(approve).toBeVisible();
  expect(cli("status", "kb-review")).toContain("Next: approve (spec)");
  expect(existsSync(join(handle.ws, "runs", "kb-review", "approved", "spec.md"))).toBe(
    false,
  );
});

test("`n` on the run board opens the run's next stage", async ({ page }) => {
  await page.goto(`${handle.baseURL}/topics/kb-busy`);
  await expect(page.getByRole("heading", { name: "kb-busy", exact: true })).toBeVisible();
  await expect(page.getByText(/Run the spec prompt/)).toBeVisible();

  await page.keyboard.press("n");

  await expect(page).toHaveURL(`${handle.baseURL}/topics/kb-busy/stages/spec`);
  await expect(page.getByRole("heading", { name: "kb-busy / spec" })).toBeVisible();
});
