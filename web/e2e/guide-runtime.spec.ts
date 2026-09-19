import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { execFileSync } from "node:child_process";
import { createServer } from "node:http";
import type { Server } from "node:http";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

const ROOT = path.resolve(process.cwd(), "..");

function assembleFixtureDocument(
  fixture = "tests/fixtures/guides/feedback-loops.guide.json",
): string {
  const script = [
    "from pathlib import Path",
    "from education_pipeline.guides import parse_guide, normalize_guide",
    "from education_pipeline.guides.document import assemble_guide_document",
    `p=Path('${fixture}')`,
    "print(assemble_guide_document(normalize_guide(parse_guide(p.read_bytes()))), end='')",
  ].join(";");
  return execFileSync("python3", ["-c", script], { cwd: ROOT, encoding: "utf8" });
}

let documentHtml: string;
let personalizedDocumentHtml: string;
let previewDocumentHtml: string;
let httpServer: Server;
let httpBaseUrl: string;
let tempDir: string;
let fileUrl: string;

test.beforeAll(async () => {
  documentHtml = assembleFixtureDocument();
  personalizedDocumentHtml = assembleFixtureDocument(
    "tests/fixtures/guides/feedback-loops.personalized.guide.json",
  );
  previewDocumentHtml = documentHtml.replace(
    'data-guide-mode="export"',
    'data-guide-mode="preview"',
  );

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

test.describe("guide schema compatibility", () => {
  test("loads a stripped schema 1.1 guide", async ({ page }) => {
    await page.setContent(personalizedDocumentHtml, { waitUntil: "load" });

    await expect(
      page.getByRole("heading", { name: "Thinking in Feedback Loops" }),
    ).toBeVisible();
    await expect(page.locator("[data-guide-status]")).toBeHidden();
    const embedded = await page.locator("#guide-data").textContent();
    expect(embedded).not.toContain("serves_goals");
    expect(embedded).not.toContain("goal_exclusions");
    expect(embedded).not.toContain("Synthetic deferred objective.");
  });

  test("rejects an unknown schema version", async ({ page }) => {
    const unknown = documentHtml
      .replace('data-guide-schema="1.0"', 'data-guide-schema="2.0"')
      .replace('"schema_version":"1.0"', '"schema_version":"2.0"');
    await page.setContent(unknown, { waitUntil: "load" });

    await expect(page.locator("[data-guide-shell]")).toBeHidden();
    await expect(page.locator("[data-guide-status]")).toContainText(
      "schema 2.0, runtime 1.0",
    );
  });
});

test.describe("preview evidence message bridge", () => {
  test.beforeEach(async ({ page }) => {
    await page.setContent(previewDocumentHtml, { waitUntil: "load" });
  });

  test("reveals, scrolls, and focuses the first section for module evidence", async ({ page }) => {
    await page.evaluate(() => {
      const original = Element.prototype.scrollIntoView;
      Element.prototype.scrollIntoView = function scrollIntoView(options) {
        document.documentElement.dataset.evidenceScrolledTo = this.id;
        if (original) original.call(this, options);
      };
      window.dispatchEvent(new MessageEvent("message", {
        source: window,
        data: {
          type: "education-pipeline:preview-evidence",
          kind: "module",
          id: "intervention-practice",
        },
      }));
    });

    const target = page.locator('section[data-module-id="intervention-practice"]').first();
    await expect(target).toHaveClass(/is-current/);
    await expect(target).toBeFocused();
    await expect(target).toHaveAttribute("tabindex", "-1");
    await expect(page.locator("html")).toHaveAttribute(
      "data-evidence-scrolled-to",
      "delays-and-leverage",
    );
  });

  test("resolves outcome evidence by DOM id and focuses the target", async ({ page }) => {
    await page.evaluate(() => {
      window.dispatchEvent(new MessageEvent("message", {
        source: window,
        data: {
          type: "education-pipeline:preview-evidence",
          kind: "outcome",
          id: "identify-loop",
        },
      }));
    });

    await expect(page.locator("#identify-loop")).toBeFocused();
    await expect(page.locator("#identify-loop")).toHaveAttribute("tabindex", "-1");
  });

  test("rejects malformed, unknown, and non-parent messages", async ({ page }) => {
    await expect(page.locator('section[data-role="guide-section"]').first()).toHaveClass(/is-current/);
    await page.evaluate(() => {
      const dispatch = (data: unknown, source: MessageEventSource | null = window) =>
        window.dispatchEvent(new MessageEvent("message", { source, data }));
      dispatch({ type: "education-pipeline:preview-evidence", kind: "module", id: "missing" });
      dispatch({ type: "education-pipeline:preview-evidence", kind: "module", id: "intervention-practice", extra: true });
      dispatch({ type: "education-pipeline:preview-evidence", kind: "block", id: "intervention-practice" });
      dispatch({ type: "education-pipeline:preview-evidence", kind: "module", id: "Not A Guide ID" });
      dispatch({ type: "education-pipeline:preview-evidence", kind: "module", id: "intervention-practice" }, null);
    });

    await expect(page.locator('section[data-role="guide-section"]').first()).toHaveClass(/is-current/);
    await expect(page.locator('section[data-module-id="intervention-practice"]').first()).not.toBeFocused();
  });

  test("rejects a DOM id that is not a declared outcome", async ({ page }) => {
    await page.evaluate(() => {
      window.dispatchEvent(new MessageEvent("message", {
        source: window,
        data: {
          type: "education-pipeline:preview-evidence",
          kind: "outcome",
          id: "guide-main",
        },
      }));
    });

    await expect(page.locator("#guide-main")).not.toBeFocused();
    await expect(page.locator("#guide-main")).not.toHaveAttribute("tabindex", "-1");
  });

  test("export-mode documents ignore otherwise valid evidence messages", async ({ page }) => {
    await page.setContent(documentHtml, { waitUntil: "load" });
    await page.evaluate(() => {
      window.dispatchEvent(new MessageEvent("message", {
        source: window,
        data: {
          type: "education-pipeline:preview-evidence",
          kind: "module",
          id: "intervention-practice",
        },
      }));
    });

    await expect(page.locator('section[data-role="guide-section"]').first()).toHaveClass(/is-current/);
    await expect(page.locator('section[data-module-id="intervention-practice"]').first()).not.toBeFocused();
  });

  test("receives parent evidence messages in an opaque sandboxed srcDoc", async ({ page }) => {
    await page.setContent(
      '<iframe title="Sandboxed guide preview" sandbox="allow-scripts"></iframe>',
    );
    const iframe = page.locator('iframe[title="Sandboxed guide preview"]');
    await iframe.evaluate((element, html) => {
      (element as HTMLIFrameElement).srcdoc = html;
    }, previewDocumentHtml);

    const preview = page.frameLocator('iframe[title="Sandboxed guide preview"]');
    const firstSection = preview.locator('section[data-role="guide-section"]').first();
    const target = preview
      .locator('section[data-module-id="intervention-practice"]')
      .first();
    await expect(preview.locator("[data-guide-shell]")).toBeVisible();
    await expect(firstSection).toHaveClass(/is-current/);

    await iframe.evaluate((element) => {
      (element as HTMLIFrameElement).contentWindow?.postMessage(
        {
          type: "education-pipeline:preview-evidence",
          kind: "module",
          id: "intervention-practice",
        },
        "*",
      );
    });

    await expect(firstSection).not.toHaveClass(/is-current/);
    await expect(target).toHaveClass(/is-current/);
    await expect(target).toBeFocused();
    await expect(iframe).toHaveAttribute("sandbox", "allow-scripts");
    await expect(iframe).not.toHaveAttribute("sandbox", /allow-same-origin/);
  });
});

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

    test("print controls: a Print fieldset defaults to answer key and toggling updates the dataset and persists across reload", async ({
      page,
    }) => {
      const fieldset = page.locator('.course-controls fieldset[data-role="print-mode"]');
      await expect(fieldset).toBeVisible();
      await expect(fieldset.locator("legend")).toHaveText("Print");

      const answerKeyRadio = fieldset.locator('input[name="print-mode"][value="answer-key"]');
      const learnerCopyRadio = fieldset.locator('input[name="print-mode"][value="learner-copy"]');
      await expect(answerKeyRadio).toBeChecked();
      await expect(learnerCopyRadio).not.toBeChecked();

      // Default state: no explicit opt-in has happened yet, so the dataset
      // attribute is either unset or already "answer-key" (both mean the
      // same thing to the print stylesheet); assert the dataset, not the
      // store, per the contract.
      const defaultPrintMode = await page.evaluate(
        () => document.documentElement.dataset.printMode,
      );
      expect(defaultPrintMode === undefined || defaultPrintMode === "answer-key").toBe(true);

      await learnerCopyRadio.check();
      await expect(page.locator("html")).toHaveAttribute("data-print-mode", "learner-copy");

      await page.reload({ waitUntil: "load" });
      const reloadedFieldset = page.locator('.course-controls fieldset[data-role="print-mode"]');
      await expect(
        reloadedFieldset.locator('input[name="print-mode"][value="learner-copy"]'),
      ).toBeChecked();
      await expect(page.locator("html")).toHaveAttribute("data-print-mode", "learner-copy");
    });

    test("print media in learner-copy mode hides answers but keeps prompts, choices, and reflection prompts", async ({
      page,
    }) => {
      await page
        .locator('.course-controls fieldset[data-role="print-mode"] input[value="learner-copy"]')
        .check();
      await page.emulateMedia({ media: "print" });

      const kc = page.locator("article.knowledge_check").first();
      const wr = page.locator("article.worked_reveal").first();
      const sc = page.locator("article.scenario").first();
      const rf = page.locator("article.reflection").first();

      await expect(kc.locator('[data-role="kc-explanation"]').first()).toBeHidden();
      await expect(page.locator('[data-role="answer-marker"]').first()).toBeHidden();
      await expect(kc.locator('[data-role="kc-result"]').first()).toBeHidden();
      await expect(wr.locator('[data-role="reveal-step"]').first()).toBeHidden();
      await expect(page.locator('[data-role="sc-feedback"]').first()).toBeHidden();
      await expect(sc.locator('[data-role="sc-debrief"]').first()).toBeHidden();

      await expect(kc.locator("h3").first()).toBeVisible();
      await expect(kc.locator(".choice-label").first()).toBeVisible();
      await expect(sc.locator("h3").first()).toBeVisible();
      await expect(sc.locator(".choice-label").first()).toBeVisible();
      await expect(rf.locator("h3").first()).toBeVisible();

      const resultsPage = page.locator('[data-role="results-page"]');
      if ((await resultsPage.count()) > 0) {
        await expect(resultsPage).toBeHidden();
      } else {
        expect(await resultsPage.count()).toBe(0);
      }

      await expect(page.locator('.course-controls fieldset[data-role="print-mode"]')).toBeHidden();
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

// ---------------------------------------------------------------------------
// Keyboard-only interaction paths (real key presses; no click/check/fill).
// The mouse paths above already run on both transports, so one transport
// (HTTP) keeps runtime cost sane. The knowledge-check keyboard path is
// covered per-transport above.
// ---------------------------------------------------------------------------

test.describe("guide runtime keyboard-only operation (http)", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto(httpBaseUrl, { waitUntil: "load" });
  });

  test("worked reveal: reveal steps, show all, and reset by keyboard", async ({ page }) => {
    await gotoSection(page, "recognize-loop-types");
    const wr = page.locator("article.worked_reveal").first();
    const steps = wr.locator('[data-role="reveal-step"]');
    const conclusion = wr.locator('[data-role="wr-conclusion"]');

    await wr.locator('[data-role="wr-reveal-next"]').focus();
    await page.keyboard.press("Enter");
    await expect(steps.nth(0)).toBeVisible();
    await expect(steps.nth(1)).toBeHidden();

    await page.keyboard.press("Enter");
    await expect(steps.nth(1)).toBeVisible();

    await wr.locator('[data-role="wr-show-all"]').focus();
    await page.keyboard.press("Space");
    await expect(steps.last()).toBeVisible();
    await expect(conclusion).toBeVisible();

    await wr.locator('[data-role="wr-reset"]').focus();
    await page.keyboard.press("Enter");
    await expect(steps.nth(0)).toBeHidden();
    await expect(conclusion).toBeHidden();
  });

  test("scenario: choose with arrow keys, submit with Enter, feedback and debrief appear", async ({
    page,
  }) => {
    await gotoSection(page, "garden-decision");
    const sc = page.locator("article.scenario").first();
    const debrief = sc.locator('[data-role="sc-debrief"]');

    // Enter the radio group and move to the second choice ("best") with the
    // arrow key, which checks it natively.
    await sc.locator('[data-role="sc-choice"]').first().focus();
    await page.keyboard.press("Space");
    await page.keyboard.press("ArrowDown");
    await expect(sc.locator('[data-role="sc-choice"][data-quality="best"]')).toBeChecked();

    // Tab out of the radio group onto the enabled submit button and activate it.
    await page.keyboard.press("Tab");
    await expect(sc.locator('[data-role="sc-submit"]')).toBeFocused();
    await page.keyboard.press("Enter");

    await expect(sc.locator('[data-role="sc-result"]')).toContainText("best");
    await expect(debrief).toBeVisible();
    await expect(debrief).toContainText("A thoughtful intervention begins");
  });

  test("reflection: type a note by keyboard, blur saves, and skip is keyboard-operable", async ({
    page,
  }) => {
    await gotoSection(page, "garden-decision");
    const rf = page.locator("article.reflection").first();
    const textarea = rf.locator('[data-role="reflection-input"]');
    const status = rf.locator('[data-role="rf-status"]');

    await textarea.focus();
    await page.keyboard.type("A keyboard-typed reflection note.");
    // Tab away: blur triggers the save.
    await page.keyboard.press("Tab");
    await expect(status).toHaveText("Saved locally.");
    await expect(textarea).toHaveValue("A keyboard-typed reflection note.");

    await rf.locator('[data-role="rf-skip"]').focus();
    await page.keyboard.press("Enter");
    await expect(status).toHaveText("Skipped.");
  });

  test("skip link: Enter moves focus to the main content without changing section", async ({
    page,
  }) => {
    const firstSection = page.locator('section[data-role="guide-section"]').first();
    await expect(firstSection).toHaveClass(/is-current/);

    await page.locator(".skip-link").focus();
    await page.keyboard.press("Enter");

    // Focus lands on the main region so the next Tab enters course content,
    // the visible section is unchanged, and no unknown-fragment message is
    // announced.
    await expect(page.locator("#guide-main")).toBeFocused();
    await expect(firstSection).toHaveClass(/is-current/);
    await expect(page.locator('[data-role="nav-announcement"]')).not.toContainText(
      "does not match",
    );
  });

  test("navigation: next and previous section controls work by keyboard", async ({ page }) => {
    const currentSection = page.locator('section[data-role="guide-section"].is-current');
    const firstSection = page.locator('section[data-role="guide-section"]').first();
    await expect(firstSection).toHaveClass(/is-current/);

    await currentSection.locator('[data-role="next-section"]').focus();
    await page.keyboard.press("Enter");
    await expect(firstSection).not.toHaveClass(/is-current/);
    await expect(page).toHaveURL(/#recognize-loop-types$/);

    await currentSection.locator('[data-role="prev-section"]').focus();
    await page.keyboard.press("Enter");
    await expect(firstSection).toHaveClass(/is-current/);
    await expect(page).toHaveURL(/#feedback-foundations$/);
  });
});

// ---------------------------------------------------------------------------
// Print modes and document-level keyboard paging (http only; these exercise
// a document-wide keydown listener and a course-controls fieldset, neither
// of which vary by transport in a way the existing per-transport loop above
// doesn't already cover for print).
// ---------------------------------------------------------------------------

test.describe("guide runtime print modes and keyboard paging (http)", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto(httpBaseUrl, { waitUntil: "load" });
  });

  test("ArrowRight/ArrowLeft page sections when focus is on the body", async ({ page }) => {
    const position = page.locator('section[data-role="guide-section"].is-current [data-role="section-position"]');
    await expect(page.locator("#feedback-foundations")).toHaveClass(/is-current/);
    await expect(position).toHaveText("Section 1 of 4");

    await page.locator("body").click({ position: { x: 2, y: 2 } });
    await page.keyboard.press("ArrowRight");
    await expect(page.locator("#recognize-loop-types")).toHaveClass(/is-current/);
    await expect(
      page.locator('section[data-role="guide-section"].is-current [data-role="section-position"]'),
    ).toHaveText("Section 2 of 4");

    await page.keyboard.press("ArrowLeft");
    await expect(page.locator("#feedback-foundations")).toHaveClass(/is-current/);
    await expect(
      page.locator('section[data-role="guide-section"].is-current [data-role="section-position"]'),
    ).toHaveText("Section 1 of 4");
  });

  test("ArrowRight at the last section is a no-op on section position", async ({ page }) => {
    await gotoSection(page, "garden-decision");
    await page.locator("body").click({ position: { x: 2, y: 2 } });
    await page.keyboard.press("ArrowRight");

    await expect(page.locator("#garden-decision")).toHaveClass(/is-current/);
    await expect(
      page.locator('section[data-role="guide-section"].is-current [data-role="section-position"]'),
    ).toHaveText("Section 4 of 4");
  });

  test("arrow keys are inert inside the reflection textarea and \"/\" types a literal slash", async ({
    page,
  }) => {
    await gotoSection(page, "garden-decision");
    const textarea = page.locator("article.reflection").first().locator('[data-role="reflection-input"]');
    await textarea.focus();

    await page.keyboard.press("ArrowLeft");
    await page.keyboard.press("ArrowRight");
    await expect(page.locator("#garden-decision")).toHaveClass(/is-current/);

    await page.keyboard.press("/");
    await expect(textarea).toHaveValue("/");
    await expect(textarea).toBeFocused();
  });

  test("\"/\" focuses the first section link in the course navigation", async ({ page }) => {
    await page.locator("body").click({ position: { x: 2, y: 2 } });
    await page.keyboard.press("/");
    await expect(page.locator('nav.guide-nav a[data-role="nav-link"]').first()).toBeFocused();
  });

  test("modifier combinations such as Control+ArrowRight do not page sections", async ({ page }) => {
    await page.locator("body").click({ position: { x: 2, y: 2 } });
    await page.keyboard.press("Control+ArrowRight");

    await expect(page.locator("#feedback-foundations")).toHaveClass(/is-current/);
    await expect(
      page.locator('section[data-role="guide-section"].is-current [data-role="section-position"]'),
    ).toHaveText("Section 1 of 4");
  });

  test("course controls name the keyboard shortcuts", async ({ page }) => {
    const help = page.locator('.course-controls [data-role="keyboard-help"]');
    await expect(help).toContainText("←");
    await expect(help).toContainText("→");
    await expect(help).toContainText("/");
  });

  test("every focusable control is a native interactive element (Enter/Space parity guard)", async ({
    page,
  }) => {
    const result = await page.evaluate(() => {
      const allowed = new Set(["BUTTON", "A", "INPUT", "TEXTAREA", "SELECT"]);
      const focusable = Array.from(
        document.querySelectorAll('button, a[href], input, textarea, select, [tabindex]:not([tabindex="-1"])'),
      );
      const nonNativeFocusable = focusable
        .map((el) => el.tagName)
        .filter((tag) => !allowed.has(tag));
      const fakeButtons = Array.from(document.querySelectorAll('[role="button"]')).filter(
        (el) => el.tagName !== "BUTTON",
      ).length;
      return { count: focusable.length, nonNativeFocusable, fakeButtons };
    });
    expect(result.count).toBeGreaterThan(0);
    expect(result.nonNativeFocusable).toEqual([]);
    expect(result.fakeButtons).toBe(0);
  });

  test("has no serious or critical accessibility violations with learner-copy print mode selected", async ({
    page,
  }) => {
    await page
      .locator('.course-controls fieldset[data-role="print-mode"] input[value="learner-copy"]')
      .check();
    const results = await new AxeBuilder({ page }).analyze();
    const serious = results.violations.filter(
      (v) => v.impact === "serious" || v.impact === "critical",
    );
    expect(serious, JSON.stringify(serious, null, 2)).toEqual([]);
  });
});
