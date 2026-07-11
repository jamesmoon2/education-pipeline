import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { execFileSync } from "node:child_process";
import { createServer } from "node:http";
import type { Server } from "node:http";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

const ROOT = path.resolve(process.cwd(), "..");

function assembleFixtureDocument(): string {
  const script = [
    "from pathlib import Path",
    "from education_pipeline.guides import parse_guide, normalize_guide",
    "from education_pipeline.guides.document import assemble_guide_document",
    "p=Path('tests/fixtures/guides/feedback-loops.guide.json')",
    "print(assemble_guide_document(normalize_guide(parse_guide(p.read_bytes()))), end='')",
  ].join(";");
  return execFileSync("python3", ["-c", script], { cwd: ROOT, encoding: "utf8" });
}

let documentHtml: string;
let httpServer: Server;
let httpBaseUrl: string;
let tempDir: string;
let fileUrl: string;

test.beforeAll(async () => {
  documentHtml = assembleFixtureDocument();

  tempDir = mkdtempSync(path.join(tmpdir(), "guide-runtime-e2e-"));
  const filePath = path.join(tempDir, "guide.html");
  writeFileSync(filePath, documentHtml, "utf8");
  fileUrl = `file://${filePath}`;

  httpServer = createServer((_req, res) => {
    res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
    res.end(documentHtml);
  });
  await new Promise<void>((resolve) => httpServer.listen(0, "127.0.0.1", () => resolve()));
  const address = httpServer.address();
  const port = typeof address === "object" && address ? address.port : 0;
  httpBaseUrl = `http://127.0.0.1:${port}/`;
});

test.afterAll(async () => {
  await new Promise<void>((resolve) => httpServer.close(() => resolve()));
  rmSync(tempDir, { recursive: true, force: true });
});

const TRANSPORTS = ["http", "file"] as const;

// The runtime shows one section at a time, so tests must open the section
// that owns the block they exercise. Uses the fragment router (a tested
// navigation path in itself).
async function gotoSection(page: import("@playwright/test").Page, sectionId: string) {
  await page.evaluate((id) => {
    location.hash = `#${id}`;
  }, sectionId);
  await expect(page.locator(`#${sectionId}`)).toHaveClass(/is-current/);
}

for (const transport of TRANSPORTS) {
  test.describe(`guide runtime via ${transport}`, () => {
    test.beforeEach(async ({ page }) => {
      const url = transport === "http" ? httpBaseUrl : fileUrl;
      await page.goto(url, { waitUntil: "load" });
    });

    test("renders the deterministic fixture shell and hides the loading status", async ({ page }) => {
      await expect(page.getByRole("heading", { name: "Thinking in Feedback Loops" })).toBeVisible();
      await expect(page.getByRole("navigation", { name: "Course sections" })).toBeVisible();
      await expect(page.locator("[data-guide-status]")).toBeHidden();
      await expect(page.locator("html")).toHaveClass(/js-enhanced/);
    });

    test("knowledge check: select an answer, submit, see the explanation; retry keeps completion", async ({
      page,
    }) => {
      await gotoSection(page, "recognize-loop-types");
      const kc = page.locator("article.knowledge_check").first();
      const submit = kc.locator('[data-role="kc-submit"]');
      const explanation = kc.locator('[data-role="kc-explanation"]');
      const result = kc.locator('[data-role="kc-result"]');

      await expect(explanation).toBeHidden();
      await expect(submit).toBeDisabled();

      await kc.locator('[data-role="kc-choice"][data-correct="true"]').first().check();
      await expect(submit).toBeEnabled();
      await submit.click();

      await expect(explanation).toBeVisible();
      await expect(explanation).toContainText("Success increases learning");
      await expect(result).toContainText("Correct");

      const progress = page.locator('[data-role="progress-summary"]');
      await expect(progress).toContainText("1 of");

      const retry = kc.locator('[data-role="kc-retry"]');
      await expect(retry).toBeVisible();
      await retry.click();

      // Selection is cleared and controls reset, but the interaction remains
      // recorded as complete in the progress summary (attempt history kept).
      await expect(explanation).toBeHidden();
      await expect(submit).toBeVisible();
      await expect(submit).toBeDisabled();
      await expect(kc.locator('[data-role="kc-choice"]').first()).not.toBeChecked();
      await expect(progress).toContainText("1 of");
    });

    test("knowledge check: keyboard-only selection and submission", async ({ page }) => {
      await gotoSection(page, "recognize-loop-types");
      const kc = page.locator("article.knowledge_check").first();
      const firstChoice = kc.locator('[data-role="kc-choice"]').first();
      await firstChoice.focus();
      await page.keyboard.press("Space");
      const submit = kc.locator('[data-role="kc-submit"]');
      await submit.focus();
      await page.keyboard.press("Enter");
      await expect(kc.locator('[data-role="kc-explanation"]')).toBeVisible();
    });

    test("worked reveal: reveals steps one at a time, show all, and reset", async ({ page }) => {
      await gotoSection(page, "recognize-loop-types");
      const wr = page.locator("article.worked_reveal").first();
      const steps = wr.locator('[data-role="reveal-step"]');
      const reveal = wr.locator('[data-role="wr-reveal-next"]');
      const showAll = wr.locator('[data-role="wr-show-all"]');
      const reset = wr.locator('[data-role="wr-reset"]');
      const conclusion = wr.locator('[data-role="wr-conclusion"]');

      await expect(steps.nth(0)).toBeHidden();
      await expect(conclusion).toBeHidden();

      await reveal.click();
      await expect(steps.nth(0)).toBeVisible();
      await expect(steps.nth(0)).toContainText("Choose the quantity");
      await expect(steps.nth(1)).toBeHidden();

      await showAll.click();
      await expect(steps.last()).toBeVisible();
      await expect(conclusion).toBeVisible();
      await expect(conclusion).toContainText("The loop reinforces growth");

      await reset.click();
      await expect(steps.nth(0)).toBeHidden();
      await expect(conclusion).toBeHidden();
    });

    test("scenario: choosing a decision reveals its feedback and the debrief", async ({ page }) => {
      await gotoSection(page, "garden-decision");
      const sc = page.locator("article.scenario").first();
      const debrief = sc.locator('[data-role="sc-debrief"]');
      const submit = sc.locator('[data-role="sc-submit"]');

      await expect(debrief).toBeHidden();
      await sc.locator('[data-role="sc-choice"][data-quality="best"]').check();
      await expect(submit).toBeEnabled();
      await submit.click();

      await expect(debrief).toBeVisible();
      await expect(debrief).toContainText("A thoughtful intervention begins");
      await expect(sc.locator('[data-role="sc-result"]')).toContainText("best");

      const retry = sc.locator('[data-role="sc-retry"]');
      await expect(retry).toBeVisible();
      await retry.click();
      await expect(debrief).toBeHidden();
    });

    test("reflection: type a note, skip control, and reset with confirmation", async ({ page }) => {
      await gotoSection(page, "garden-decision");
      const rf = page.locator("article.reflection").first();
      const textarea = rf.locator('[data-role="reflection-input"]');
      const status = rf.locator('[data-role="rf-status"]');

      await textarea.fill("A note about a project I know.");
      await textarea.blur();
      await expect(status).toHaveText("Saved locally.");

      page.once("dialog", (dialog) => dialog.accept());
      await rf.locator('[data-role="rf-reset"]').click();
      await expect(textarea).toHaveValue("");
      await expect(status).toHaveText("Cleared.");

      await rf.locator('[data-role="rf-skip"]').click();
      await expect(status).toHaveText("Skipped.");
    });

    test("navigation: next/prev controls move between sections and update the URL fragment", async ({
      page,
    }) => {
      const currentSection = page.locator('section[data-role="guide-section"].is-current');
      const firstSection = page.locator('section[data-role="guide-section"]').first();
      await expect(firstSection).toHaveClass(/is-current/);

      await currentSection.locator('[data-role="next-section"]').click();
      await expect(firstSection).not.toHaveClass(/is-current/);
      await expect(page).toHaveURL(/#recognize-loop-types$/);

      await currentSection.locator('[data-role="prev-section"]').click();
      await expect(firstSection).toHaveClass(/is-current/);
      await expect(page).toHaveURL(/#feedback-foundations$/);
    });

    test("navigation: a fragment link to content inside another section opens the owning section", async ({
      page,
    }) => {
      // "choose-biomass" is a worked-reveal step id that lives inside the
      // "recognize-loop-types" section, not a section id itself.
      await page.evaluate(() => {
        location.hash = "#choose-biomass";
      });
      await expect(page.locator("#recognize-loop-types")).toHaveClass(/is-current/);
    });

    test("navigation: an unknown fragment falls back to the first section with a non-disruptive announcement", async ({
      page,
    }) => {
      await page.evaluate(() => {
        location.hash = "#not-a-real-section";
      });
      const firstSection = page.locator('section[data-role="guide-section"]').first();
      await expect(firstSection).toHaveClass(/is-current/);
      await expect(page.locator('[data-role="nav-announcement"]')).toContainText(
        "does not match a section"
      );
    });

    test("progress updates and persists across reload via localStorage", async ({ page }) => {
      await gotoSection(page, "recognize-loop-types");
      const kc = page.locator("article.knowledge_check").first();
      await kc.locator('[data-role="kc-choice"][data-correct="true"]').first().check();
      await kc.locator('[data-role="kc-submit"]').click();

      const progress = page.locator('[data-role="progress-summary"]');
      await expect(progress).toContainText("1 of");

      await page.reload({ waitUntil: "load" });
      await expect(page.locator('[data-role="progress-summary"]')).toContainText("1 of");
      const kcAfterReload = page.locator("article.knowledge_check").first();
      await expect(kcAfterReload).toHaveClass(/is-submitted/);
    });

    test("corrupted localStorage degrades gracefully instead of crashing the runtime", async ({ page }) => {
      await page.evaluate(() => {
        for (let i = 0; i < window.localStorage.length; i++) {
          const key = window.localStorage.key(i);
          if (key && key.startsWith("education-pipeline:guide:")) {
            window.localStorage.setItem(key, "{not valid json");
          }
        }
      });
      await page.reload({ waitUntil: "load" });
      await expect(page.getByRole("heading", { name: "Thinking in Feedback Loops" })).toBeVisible();
      await expect(page.locator("[data-guide-status]")).toBeHidden();
      await expect(page.locator('[data-role="progress-summary"]')).toContainText("of");
    });

    test("theme toggle switches light/dark and course controls explain local storage", async ({ page }) => {
      const select = page.locator('[data-role="theme-select"]');
      await select.selectOption("dark");
      await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
      await select.selectOption("light");
      await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
      await expect(page.locator(".local-data-note").first()).toContainText("stored only in this browser");
    });

    test("print media expands all educational content", async ({ page }) => {
      const kc = page.locator("article.knowledge_check").first();
      const wr = page.locator("article.worked_reveal").first();

      await expect(kc.locator('[data-role="kc-explanation"]')).toBeHidden();
      await expect(wr.locator('[data-role="reveal-step"]').first()).toBeHidden();

      await page.emulateMedia({ media: "print" });

      await expect(kc.locator('[data-role="kc-explanation"]')).toBeVisible();
      await expect(wr.locator('[data-role="reveal-step"]').first()).toBeVisible();
      await expect(page.locator("article.scenario").first().locator('[data-role="sc-debrief"]')).toBeVisible();
      await expect(page.locator(".guide-nav")).toBeHidden();
      await expect(page.locator(".reflection-input").first()).toBeHidden();
    });

    test("has no serious or critical automated accessibility violations", async ({ page }) => {
      const results = await new AxeBuilder({ page }).analyze();
      const serious = results.violations.filter(
        (v) => v.impact === "serious" || v.impact === "critical"
      );
      expect(serious, JSON.stringify(serious, null, 2)).toEqual([]);
    });
  });
}
