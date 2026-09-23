import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { execFileSync } from "node:child_process";
import { createServer } from "node:http";
import type { Server } from "node:http";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
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
      "schema 2.0, runtime 1.2",
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

    // T43 (PR #41 review finding): the worked-reveal conclusion is the same
    // kind of "answer" as its steps, but only `.reveal-step` is hidden by the
    // learner-copy print rule (`runtime.css`) -- `.conclusion` is not, so it
    // leaks onto a printed learner copy.
    test("learner-copy print hides the worked-reveal conclusion; answer-key print keeps it visible", async ({
      page,
    }) => {
      await gotoSection(page, "recognize-loop-types");
      const wr = page.locator("article.worked_reveal").first();
      const conclusion = wr.locator('[data-role="wr-conclusion"]');

      // Reveal every step on screen first, so the conclusion is showing
      // before print is ever emulated.
      await wr.locator('[data-role="wr-show-all"]').click();
      await expect(conclusion).toBeVisible();

      // Answer key is the default print mode: the conclusion is part of the
      // worked answer and must stay visible when printed.
      await page.emulateMedia({ media: "print" });
      await expect(conclusion).toBeVisible();
      await page.emulateMedia({ media: "screen" });

      // Learner copy must hide it exactly like the reveal steps it concludes.
      await page
        .locator('.course-controls fieldset[data-role="print-mode"] input[value="learner-copy"]')
        .check();
      await page.emulateMedia({ media: "print" });
      await expect(conclusion).toBeHidden();
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

  test("ArrowRight at the last section opens the results page and is a no-op there", async ({ page }) => {
    await gotoSection(page, "garden-decision");
    await page.locator("body").click({ position: { x: 2, y: 2 } });
    await page.keyboard.press("ArrowRight");

    await expect(page.locator("#results")).toHaveClass(/is-current/);
    await expect(page.locator('#results [data-role="section-position"]')).toHaveText("Results");

    await page.keyboard.press("ArrowRight");
    await expect(page.locator("#results")).toHaveClass(/is-current/);

    await page.keyboard.press("ArrowLeft");
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

// ---------------------------------------------------------------------------
// T40: per-outcome mastery results (header indicator + "Your results" page).
// The fixture has three outcomes: "identify-loop" (scored only by the
// knowledge check "check-loop-type"), "map-loop" (scored only by the
// knowledge check "check-delay-response"), and "choose-intervention" (scored
// by both "check-delay-response" and the scenario "pest-density-scenario").
// http-only: these assertions are about text/DOM contract, not transport.
// ---------------------------------------------------------------------------

test.describe("mastery results (T40, http)", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto(httpBaseUrl, { waitUntil: "load" });
  });

  test("header reports no checks answered yet and drops the old 'not mastery' copy", async ({
    page,
  }) => {
    const progress = page.locator('[data-role="progress-summary"]');
    await expect(progress).toContainText(
      "Progress and results are stored only in this browser. They are not a grade.",
    );
    const progressText = await progress.textContent();
    expect(progressText).not.toContain("not mastery");

    const resultsSummary = page.locator('[data-role="results-summary"]');
    await expect(resultsSummary).toContainText("Results: no checks answered yet");
    await expect(resultsSummary.locator('a[href="#results"]')).toBeVisible();
  });

  test("the results page lists every outcome, in guide order, as not started before any answers", async ({
    page,
  }) => {
    await page.evaluate(() => {
      location.hash = "#results";
    });
    await expect(page.locator("#results")).toHaveClass(/is-current/);

    const items = page.locator('[data-role="results-outcomes"] li');
    await expect(items).toHaveCount(3);
    await expect(items.nth(0)).toHaveAttribute("data-outcome-id", "identify-loop");
    await expect(items.nth(1)).toHaveAttribute("data-outcome-id", "map-loop");
    await expect(items.nth(2)).toHaveAttribute("data-outcome-id", "choose-intervention");
    for (let i = 0; i < 3; i++) {
      await expect(items.nth(i)).toHaveAttribute("data-status", "not_started");
      await expect(items.nth(i).locator('[data-role="results-outcome-count"]')).toHaveText(
        "Not started",
      );
    }
    await expect(items.nth(0)).toContainText(
      "Identify reinforcing and balancing feedback in a familiar system.",
    );
  });

  test("the results page is not a guide section and carries only a previous control", async ({
    page,
  }) => {
    await page.evaluate(() => {
      location.hash = "#results";
    });
    const results = page.locator("#results");
    await expect(results).toHaveAttribute("data-role", "results-page");
    await expect(results.locator("h2").first()).toHaveText("Your results");
    await expect(results.locator('[data-role="section-position"]')).toHaveText("Results");
    await expect(results.locator('[data-role="prev-section"]')).toBeVisible();
    await expect(results.locator('[data-role="next-section"]')).toHaveCount(0);
    // A results page is not itself a counted guide section.
    await expect(page.locator('section[data-role="guide-section"]')).toHaveCount(4);
  });

  test("existing section-position and progress-count text are unchanged by the results page", async ({
    page,
  }) => {
    await expect(page.locator('#feedback-foundations [data-role="section-position"]')).toHaveText(
      "Section 1 of 4",
    );
    await expect(page.locator('[data-role="progress-summary"]')).toContainText(
      "0 of 4 sections complete",
    );
    await expect(page.locator('[data-role="progress-summary"]')).toContainText(
      "0 of 5 interactions complete",
    );
  });

  test("a correct knowledge-check answer puts its outcome on track and updates the header", async ({
    page,
  }) => {
    await gotoSection(page, "recognize-loop-types");
    const kc = page.locator("article.knowledge_check").first();
    await kc.locator('[data-role="kc-choice"][data-correct="true"]').first().check();
    await kc.locator('[data-role="kc-submit"]').click();

    await expect(page.locator('[data-role="results-summary"]')).toContainText(
      "Results: 1 of 3 outcomes on track",
    );

    await page.evaluate(() => {
      location.hash = "#results";
    });
    const item = page.locator('[data-outcome-id="identify-loop"]');
    await expect(item).toHaveAttribute("data-status", "on_track");
    await expect(item.locator('[data-role="results-outcome-count"]')).toHaveText(
      "1 of 1 correct",
    );
  });

  test("a wrong knowledge-check answer puts its outcome up for review and the header appends a review count", async ({
    page,
  }) => {
    await gotoSection(page, "recognize-loop-types");
    const kc = page.locator("article.knowledge_check").first();
    await kc.locator('[data-role="kc-choice"][data-correct="false"]').first().check();
    await kc.locator('[data-role="kc-submit"]').click();

    await expect(page.locator('[data-role="results-summary"]')).toContainText(
      "Results: 0 of 3 outcomes on track, 1 to review",
    );

    await page.evaluate(() => {
      location.hash = "#results";
    });
    const item = page.locator('[data-outcome-id="identify-loop"]');
    await expect(item).toHaveAttribute("data-status", "review");
    await expect(item.locator('[data-role="results-outcome-count"]')).toHaveText(
      "0 of 1 correct",
    );
  });

  test("a retry that lands correct flips an outcome from review back to on track", async ({
    page,
  }) => {
    await gotoSection(page, "recognize-loop-types");
    const kc = page.locator("article.knowledge_check").first();
    await kc.locator('[data-role="kc-choice"][data-correct="false"]').first().check();
    await kc.locator('[data-role="kc-submit"]').click();
    await expect(page.locator('[data-role="results-summary"]')).toContainText("1 to review");

    await kc.locator('[data-role="kc-retry"]').click();
    await kc.locator('[data-role="kc-choice"][data-correct="true"]').first().check();
    await kc.locator('[data-role="kc-submit"]').click();

    const resultsSummary = page.locator('[data-role="results-summary"]');
    await expect(resultsSummary).toContainText("Results: 1 of 3 outcomes on track");
    const summaryText = await resultsSummary.textContent();
    expect(summaryText).not.toContain("to review");
  });

  test("an outcome linked to two scorable blocks aggregates both into its results count", async ({
    page,
  }) => {
    await gotoSection(page, "delays-and-leverage");
    const kc = page.locator("#delays-and-leverage article.knowledge_check");
    const correctChoices = kc.locator('[data-role="kc-choice"][data-correct="true"]');
    const correctCount = await correctChoices.count();
    for (let i = 0; i < correctCount; i++) await correctChoices.nth(i).check();
    await kc.locator('[data-role="kc-submit"]').click();

    await gotoSection(page, "garden-decision");
    const sc = page.locator("article.scenario").first();
    await sc.locator('[data-role="sc-choice"][data-quality="weak"]').check();
    await sc.locator('[data-role="sc-submit"]').click();

    await expect(page.locator('[data-role="results-summary"]')).toContainText(
      "Results: 1 of 3 outcomes on track, 1 to review",
    );

    await page.evaluate(() => {
      location.hash = "#results";
    });
    const mapLoop = page.locator('[data-outcome-id="map-loop"]');
    await expect(mapLoop).toHaveAttribute("data-status", "on_track");
    await expect(mapLoop.locator('[data-role="results-outcome-count"]')).toHaveText(
      "1 of 1 correct",
    );
    const chooseIntervention = page.locator('[data-outcome-id="choose-intervention"]');
    await expect(chooseIntervention).toHaveAttribute("data-status", "review");
    await expect(chooseIntervention.locator('[data-role="results-outcome-count"]')).toHaveText(
      "1 of 2 correct",
    );
  });

  test("an outcome with one of two checks answered counts only the answered one and names the open one", async ({
    page,
  }) => {
    await page.goto(httpBaseUrl);
    await gotoSection(page, "delays-and-leverage");
    const kc = page.locator("#delays-and-leverage article.knowledge_check");
    const correctChoices = kc.locator('[data-role="kc-choice"][data-correct="true"]');
    const correctCount = await correctChoices.count();
    for (let i = 0; i < correctCount; i++) await correctChoices.nth(i).check();
    await kc.locator('[data-role="kc-submit"]').click();

    await page.evaluate(() => {
      location.hash = "#results";
    });
    const chooseIntervention = page.locator('[data-outcome-id="choose-intervention"]');
    await expect(chooseIntervention).toHaveAttribute("data-status", "on_track");
    await expect(chooseIntervention.locator('[data-role="results-outcome-count"]')).toHaveText(
      "1 of 1 correct, 1 not yet answered",
    );
  });

  test("Next from the last guide section and a direct #results fragment both open the results page", async ({
    page,
  }) => {
    await gotoSection(page, "garden-decision");
    const current = page.locator("section[data-role=\"guide-section\"].is-current");
    const next = current.locator('[data-role="next-section"]');
    // On the last guide section, Next must lead on to the results page
    // instead of staying disabled the way it does today.
    await expect(next).toBeEnabled();
    await next.click();
    await expect(page.locator("#results")).toHaveClass(/is-current/);
    await expect(page).toHaveURL(/#results$/);

    await page.reload({ waitUntil: "load" });
    await page.evaluate(() => {
      location.hash = "#results";
    });
    await expect(page.locator("#results")).toHaveClass(/is-current/);
    await expect(page.locator('#results [data-role="section-position"]')).toHaveText("Results");
  });

  test("the results page has no serious or critical accessibility violations after answering everything", async ({
    page,
  }) => {
    await gotoSection(page, "recognize-loop-types");
    const kc1 = page.locator("article.knowledge_check").first();
    await kc1.locator('[data-role="kc-choice"][data-correct="true"]').first().check();
    await kc1.locator('[data-role="kc-submit"]').click();

    await gotoSection(page, "delays-and-leverage");
    const kc2 = page.locator("#delays-and-leverage article.knowledge_check");
    const correctChoices = kc2.locator('[data-role="kc-choice"][data-correct="true"]');
    const correctCount = await correctChoices.count();
    for (let i = 0; i < correctCount; i++) await correctChoices.nth(i).check();
    await kc2.locator('[data-role="kc-submit"]').click();

    await gotoSection(page, "garden-decision");
    const sc = page.locator("article.scenario").first();
    await sc.locator('[data-role="sc-choice"][data-quality="best"]').check();
    await sc.locator('[data-role="sc-submit"]').click();

    await page.evaluate(() => {
      location.hash = "#results";
    });
    await expect(page.locator("#results")).toHaveClass(/is-current/);

    const results = await new AxeBuilder({ page }).analyze();
    const serious = results.violations.filter(
      (v) => v.impact === "serious" || v.impact === "critical",
    );
    expect(serious, JSON.stringify(serious, null, 2)).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// T41: the review queue. "Missed" = a knowledge_check or scenario whose
// stored `correct === false` on the latest attempt. `check-loop-type` (in
// "recognize-loop-types", guide section index 1) sits exactly two sections
// before "garden-decision" (index 3), which is what makes the distance rule
// testable in both directions: no panel one section later
// ("delays-and-leverage", index 2) and a panel two sections later. The
// scenario block `pest-density-scenario` carries no `retry` flag, so it is
// used to pin the non-retryable "See the explanation" link text; everything
// else uses the retryable knowledge check `check-loop-type`.
// ---------------------------------------------------------------------------

test.describe("review queue (T41, http)", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto(httpBaseUrl, { waitUntil: "load" });
  });

  test("entering a section two or more sections after a missed check shows a review panel naming it", async ({
    page,
  }) => {
    await gotoSection(page, "recognize-loop-types");
    const kc = page.locator("article.knowledge_check").first();
    await kc.locator('[data-role="kc-choice"][data-correct="false"]').first().check();
    await kc.locator('[data-role="kc-submit"]').click();

    await gotoSection(page, "garden-decision");

    const panel = page.locator('#garden-decision [data-role="review-panel"]');
    await expect(panel).toBeVisible();
    await expect(panel).toHaveClass(/review-panel/);
    await expect(panel.locator("h3")).toHaveText("Review what you missed");

    const labelledBy = await panel.getAttribute("aria-labelledby");
    expect(labelledBy).toBeTruthy();
    await expect(page.locator(`#${labelledBy}`)).toHaveText("Review what you missed");

    const items = panel.locator('[data-role="review-items"] li');
    await expect(items).toHaveCount(1);
    const item = items.first();
    await expect(item).toHaveAttribute("data-block-id", "check-loop-type");
    await expect(item).toContainText(
      "A project team learns from each successful release, making later releases smoother and creating more opportunities to learn. What kind of loop dominates?",
    );
    const link = item.locator('[data-role="practice-again"]');
    await expect(link).toHaveText("Practice again");
    await expect(link).toHaveAttribute("href", "#check-loop-type");

    const dismissBtn = panel.locator('[data-role="review-dismiss"]');
    await expect(dismissBtn).toHaveText("Dismiss");

    const positionedRightAfterHeading = await page
      .locator("#garden-decision")
      .evaluate((section) => {
        const heading = section.querySelector("h2");
        return Boolean(
          heading &&
            heading.nextElementSibling &&
            heading.nextElementSibling.matches('[data-role="review-panel"]'),
        );
      });
    expect(positionedRightAfterHeading).toBe(true);
  });

  test("no review panel appears in the section holding the missed block, or the one right after it", async ({
    page,
  }) => {
    await gotoSection(page, "recognize-loop-types");
    const kc = page.locator("article.knowledge_check").first();
    await kc.locator('[data-role="kc-choice"][data-correct="false"]').first().check();
    await kc.locator('[data-role="kc-submit"]').click();

    // Same section as the missed block: distance 0.
    await expect(page.locator('#recognize-loop-types [data-role="review-panel"]')).toHaveCount(0);

    // The very next section: distance 1.
    await gotoSection(page, "delays-and-leverage");
    await expect(page.locator('#delays-and-leverage [data-role="review-panel"]')).toHaveCount(0);
  });

  test("no review panel appears anywhere when nothing has been answered wrong", async ({ page }) => {
    await gotoSection(page, "garden-decision");
    await expect(page.locator('[data-role="review-panel"]')).toHaveCount(0);
  });

  test("dismissing the review panel hides it for this visit; leaving and returning shows it again while still missed", async ({
    page,
  }) => {
    await gotoSection(page, "recognize-loop-types");
    const kc = page.locator("article.knowledge_check").first();
    await kc.locator('[data-role="kc-choice"][data-correct="false"]').first().check();
    await kc.locator('[data-role="kc-submit"]').click();

    await gotoSection(page, "garden-decision");
    const panel = page.locator('#garden-decision [data-role="review-panel"]');
    await expect(panel).toBeVisible();
    await panel.locator('[data-role="review-dismiss"]').click();
    await expect(panel).toHaveCount(0);

    await gotoSection(page, "delays-and-leverage");
    await gotoSection(page, "garden-decision");
    await expect(page.locator('#garden-decision [data-role="review-panel"]')).toBeVisible();
  });

  test("practice again on a retryable block opens its section, focuses the block, and returns it to an answerable state", async ({
    page,
  }) => {
    await gotoSection(page, "recognize-loop-types");
    const kc = page.locator("article.knowledge_check").first();
    await kc.locator('[data-role="kc-choice"][data-correct="false"]').first().check();
    await kc.locator('[data-role="kc-submit"]').click();
    await expect(kc).toHaveClass(/is-submitted/);

    await gotoSection(page, "garden-decision");
    const panel = page.locator('#garden-decision [data-role="review-panel"]');
    await panel.locator('[data-role="practice-again"]').click();

    await expect(page.locator("#recognize-loop-types")).toHaveClass(/is-current/);
    await expect(page.locator("article#check-loop-type")).toBeFocused();
    await expect(kc).not.toHaveClass(/is-submitted/);
    await expect(kc.locator('[data-role="kc-submit"]')).toBeVisible();
    await expect(kc.locator('[data-role="kc-choice"]').first()).toBeEnabled();
    await expect(kc.locator('[data-role="kc-result"]')).toHaveText("");
  });

  test("the results page lists missed blocks only under outcomes up for review", async ({ page }) => {
    await gotoSection(page, "recognize-loop-types");
    const kc = page.locator("article.knowledge_check").first();
    await kc.locator('[data-role="kc-choice"][data-correct="false"]').first().check();
    await kc.locator('[data-role="kc-submit"]').click();

    await page.evaluate(() => {
      location.hash = "#results";
    });

    const identifyLoop = page.locator('[data-outcome-id="identify-loop"]');
    await expect(identifyLoop).toHaveAttribute("data-status", "review");
    const missedList = identifyLoop.locator('[data-role="results-missed"]');
    await expect(missedList).toBeVisible();
    const missedItems = missedList.locator("li");
    await expect(missedItems).toHaveCount(1);
    await expect(missedItems.first()).toHaveAttribute("data-block-id", "check-loop-type");
    await expect(missedItems.first().locator('[data-role="practice-again"]')).toHaveText(
      "Practice again",
    );

    const mapLoop = page.locator('[data-outcome-id="map-loop"]');
    await expect(mapLoop).toHaveAttribute("data-status", "not_started");
    await expect(mapLoop.locator('[data-role="results-missed"]')).toHaveCount(0);

    const chooseIntervention = page.locator('[data-outcome-id="choose-intervention"]');
    await expect(chooseIntervention).toHaveAttribute("data-status", "not_started");
    await expect(chooseIntervention.locator('[data-role="results-missed"]')).toHaveCount(0);
  });

  test("practice again for a non-retryable scenario keeps its answered view and reads 'See the explanation'", async ({
    page,
  }) => {
    await gotoSection(page, "garden-decision");
    const sc = page.locator("article.scenario").first();
    await sc.locator('[data-role="sc-choice"][data-quality="weak"]').check();
    await sc.locator('[data-role="sc-submit"]').click();
    await expect(sc).toHaveClass(/is-submitted/);

    await page.evaluate(() => {
      location.hash = "#results";
    });
    const chooseIntervention = page.locator('[data-outcome-id="choose-intervention"]');
    await expect(chooseIntervention).toHaveAttribute("data-status", "review");
    const item = chooseIntervention.locator(
      '[data-role="results-missed"] li[data-block-id="pest-density-scenario"]',
    );
    const link = item.locator('[data-role="practice-again"]');
    await expect(link).toHaveText("See the explanation");
    await expect(link).toHaveAttribute("href", "#pest-density-scenario");

    await link.click();
    await expect(page.locator("#garden-decision")).toHaveClass(/is-current/);
    await expect(page.locator("article#pest-density-scenario")).toBeFocused();
    await expect(sc).toHaveClass(/is-submitted/);
    await expect(sc.locator('[data-role="sc-submit"]')).toBeHidden();
  });

  test("a retry that lands correct removes the block from the results-page missed list", async ({
    page,
  }) => {
    await gotoSection(page, "recognize-loop-types");
    const kc = page.locator("article.knowledge_check").first();
    await kc.locator('[data-role="kc-choice"][data-correct="false"]').first().check();
    await kc.locator('[data-role="kc-submit"]').click();

    await page.evaluate(() => {
      location.hash = "#results";
    });
    const identifyLoopBeforeFix = page.locator('[data-outcome-id="identify-loop"]');
    await expect(identifyLoopBeforeFix).toHaveAttribute("data-status", "review");
    await expect(
      identifyLoopBeforeFix.locator('[data-role="results-missed"] li[data-block-id="check-loop-type"]'),
    ).toHaveCount(1);

    await gotoSection(page, "recognize-loop-types");
    await kc.locator('[data-role="kc-retry"]').click();
    await kc.locator('[data-role="kc-choice"][data-correct="true"]').first().check();
    await kc.locator('[data-role="kc-submit"]').click();

    await page.evaluate(() => {
      location.hash = "#results";
    });
    const identifyLoop = page.locator('[data-outcome-id="identify-loop"]');
    await expect(identifyLoop).toHaveAttribute("data-status", "on_track");
    await expect(identifyLoop.locator('[data-role="results-missed"]')).toHaveCount(0);
  });

  test("keyboard: Tab reaches the practice-again link and the dismiss button; Enter dismisses", async ({
    page,
  }) => {
    await gotoSection(page, "recognize-loop-types");
    const kc = page.locator("article.knowledge_check").first();
    await kc.locator('[data-role="kc-choice"][data-correct="false"]').first().check();
    await kc.locator('[data-role="kc-submit"]').click();

    await gotoSection(page, "garden-decision");
    const panel = page.locator('#garden-decision [data-role="review-panel"]');
    const link = panel.locator('[data-role="practice-again"]');
    const dismissBtn = panel.locator('[data-role="review-dismiss"]');

    await link.focus();
    await expect(link).toBeFocused();
    await page.keyboard.press("Tab");
    await expect(dismissBtn).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(panel).toHaveCount(0);
  });

  test("the review panel has no animation and stays accessible", async ({ page }) => {
    await gotoSection(page, "recognize-loop-types");
    const kc = page.locator("article.knowledge_check").first();
    await kc.locator('[data-role="kc-choice"][data-correct="false"]').first().check();
    await kc.locator('[data-role="kc-submit"]').click();

    await gotoSection(page, "garden-decision");
    const panel = page.locator('#garden-decision [data-role="review-panel"]');
    await expect(panel).toBeVisible();

    const styleAttr = (await panel.getAttribute("style")) || "";
    expect(styleAttr).not.toMatch(/transition|animation/i);

    const results = await new AxeBuilder({ page }).analyze();
    const serious = results.violations.filter(
      (v) => v.impact === "serious" || v.impact === "critical",
    );
    expect(serious, JSON.stringify(serious, null, 2)).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// T43 (PR #41 review finding): the results page is always created with
// `page.id = "results"` and `installPage()` bails out whenever
// `document.getElementById("results")` already exists -- so an authored
// section whose id happens to be "results" both steals `#results` from the
// runtime page *and* silently suppresses the results page outright (the
// early return means it is never appended at all). A fixture where the first
// section is renamed to "results" pins that the runtime must give its own
// page a different, never-authorable id instead.
// ---------------------------------------------------------------------------

test.describe("results page never collides with an authored id (T43)", () => {
  let collisionHtmlPath: string;

  test.beforeAll(() => {
    const guide = JSON.parse(
      readFileSync(
        path.join(ROOT, "tests/fixtures/guides/feedback-loops.guide.json"),
        "utf8",
      ),
    );
    // Section ids are the schema's only place-of-record for a section: no
    // other field (blocks link to outcomes via outcome_ids, not section ids)
    // has to be fixed up for this rename to stay a valid, resolvable guide.
    guide.modules[0].sections[0].id = "results";
    const guideJsonPath = path.join(tempDir, "results-collision.guide.json");
    writeFileSync(guideJsonPath, JSON.stringify(guide), "utf8");
    const html = assembleFixtureDocument(guideJsonPath);
    collisionHtmlPath = path.join(tempDir, "results-collision.html");
    writeFileSync(collisionHtmlPath, html, "utf8");
  });

  test("on the plain fixture the results page keeps the id 'results'", async ({ page }) => {
    // Existing #results-fragment assertions elsewhere in this file rely on
    // this id; pin it explicitly so a future change to the collision fix
    // cannot quietly break their meaning.
    await page.goto(httpBaseUrl, { waitUntil: "load" });
    const id = await page.evaluate(
      () => document.querySelector('[data-role="results-page"]')?.id,
    );
    expect(id).toBe("results");
  });

  test("an authored section named 'results' keeps #results; the runtime's results page still exists under a different id", async ({
    page,
  }) => {
    await page.goto(`file://${collisionHtmlPath}`, { waitUntil: "load" });

    // #results still opens the authored section, not the runtime's page.
    await page.evaluate(() => {
      location.hash = "#results";
    });
    const authored = page.locator("#results");
    await expect(authored).toHaveClass(/is-current/);
    await expect(authored).toHaveAttribute("data-role", "guide-section");

    // The runtime still builds its results page -- just not at #results, and
    // not at any id an authored guide could ever declare (the schema's
    // identifier pattern), so no future course can ever retake it.
    const resultsPage = page.locator('[data-role="results-page"]');
    await expect(resultsPage).toHaveCount(1);
    const pageId = await resultsPage.evaluate((el) => el.id);
    expect(pageId).not.toBe("results");
    expect(pageId).not.toMatch(/^[a-z][a-z0-9-]{0,63}$/);

    const link = page.locator('[data-role="results-summary"] a');
    await expect(link).toHaveAttribute("href", `#${pageId}`);
    await link.click();
    await expect(resultsPage).toHaveClass(/is-current/);
  });
});

test.describe("diagram rendering: flow and timeline (T53)", () => {
  const DIAGRAMS_FIXTURE = "tests/fixtures/guides/feedback-loops.diagrams.guide.json";
  const FLOW = "figure#growth-loop-flow";
  const TIMELINE = "figure#watering-delay-timeline";
  const FLOW_DESC =
    "Flow diagram with 4 steps and 4 connections, 1 of which loops back to an earlier step. " +
    "Steps in order: Plant biomass; Leaf area; Sunlight captured; New growth.";
  const TIMELINE_DESC =
    "Timeline of 4 events, from Day 1, morning (Water the bed) to Day 4 (Leaves recover).";
  let diagramsHtml: string;

  test.beforeAll(() => {
    diagramsHtml = assembleFixtureDocument(DIAGRAMS_FIXTURE);
  });

  async function load(page: import("@playwright/test").Page, html = diagramsHtml) {
    await page.setContent(html, { waitUntil: "load" });
    await expect(page.locator("[data-guide-status]")).toBeHidden();
  }

  async function expectNoSeriousViolations(page: import("@playwright/test").Page) {
    const results = await new AxeBuilder({ page }).analyze();
    const serious = results.violations.filter(
      (v) => v.impact === "serious" || v.impact === "critical",
    );
    expect(serious, JSON.stringify(serious, null, 2)).toEqual([]);
  }

  test("the document declares schema 1.2 and runtime 1.2 and boots without errors", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(String(error)));
    page.on("console", (message) => {
      if (message.type() === "error") errors.push(message.text());
    });
    await load(page);
    await expect(page.locator("html")).toHaveAttribute("data-guide-schema", "1.2");
    await expect(page.locator("html")).toHaveAttribute("data-guide-runtime", "1.2");
    await expect(page.locator("[data-guide-shell]")).toBeVisible();
    expect(errors).toEqual([]);
  });

  test("flow is drawn as one labelled svg[role=img] with the §10.4 viewBox", async ({ page }) => {
    await load(page);
    const figure = page.locator(FLOW);
    await expect(figure).toHaveAttribute("data-diagram-state", "drawn");
    const svg = figure.locator("svg");
    await expect(svg).toHaveCount(1);
    await expect(svg).toHaveAttribute("role", "img");
    await expect(svg).toHaveAttribute("focusable", "false");
    await expect(svg).toHaveClass("diagram-svg diagram-svg--flow");
    await expect(svg).toHaveAttribute("viewBox", "0 0 261 368");
    await expect(svg).toHaveAttribute("width", "261");
    await expect(svg).toHaveAttribute("height", "368");
    await expect(svg).toHaveAttribute("aria-labelledby", "growth-loop-flow__title");
    await expect(svg).toHaveAttribute("aria-describedby", "growth-loop-flow__desc");
    await expect(svg.locator("title#growth-loop-flow__title")).toHaveText(
      "How plant growth reinforces itself",
    );
    await expect(svg.locator("desc#growth-loop-flow__desc")).toHaveText(FLOW_DESC);
    await expect(svg).toBeVisible();
    await expect(page.getByRole("img", { name: "How plant growth reinforces itself" })).toHaveCount(1);
  });

  test("flow draws four nodes, four edges and exactly one back edge with an arrowhead", async ({ page }) => {
    await load(page);
    const svg = page.locator(`${FLOW} svg`);
    await expect(svg.locator("g.diagram-node")).toHaveCount(4);
    await expect(svg.locator("path.diagram-edge")).toHaveCount(4);
    await expect(page.locator(".diagram-edge--back")).toHaveCount(1);
    await expect(svg.locator("path.diagram-edge--back")).toHaveCount(1);
    await expect(svg.locator("g.diagram-edge-label")).toHaveCount(4);
    await expect(svg.locator("marker#growth-loop-flow__arrow")).toHaveCount(1);
    const markerEnds = await svg
      .locator("path.diagram-edge")
      .evaluateAll((paths) => paths.map((p) => p.getAttribute("marker-end")));
    expect(markerEnds).toEqual(Array(4).fill("url(#growth-loop-flow__arrow)"));
    const labels = await svg
      .locator("g.diagram-node text")
      .evaluateAll((nodes) => nodes.map((n) => n.textContent));
    expect(labels).toEqual(["Plant biomass", "Leaf area", "Sunlight captured", "New growth"]);
  });

  test("timeline is drawn as a horizontal then a vertical svg with the §10.4 viewBoxes", async ({ page }) => {
    await load(page);
    const figure = page.locator(TIMELINE);
    await expect(figure).toHaveAttribute("data-diagram-state", "drawn");
    const svgs = figure.locator("svg");
    await expect(svgs).toHaveCount(2);
    const horizontal = svgs.nth(0);
    const vertical = svgs.nth(1);
    await expect(horizontal).toHaveClass("diagram-svg diagram-svg--timeline-h");
    await expect(vertical).toHaveClass("diagram-svg diagram-svg--timeline-v");
    await expect(horizontal).toHaveAttribute("viewBox", "0 0 648 240");
    await expect(vertical).toHaveAttribute("viewBox", "0 0 360 424");
    for (const [svg, sfx] of [[horizontal, "-h"], [vertical, "-v"]] as const) {
      await expect(svg).toHaveAttribute("role", "img");
      await expect(svg).toHaveAttribute("focusable", "false");
      await expect(svg).toHaveAttribute("aria-labelledby", `watering-delay-timeline__title${sfx}`);
      await expect(svg).toHaveAttribute("aria-describedby", `watering-delay-timeline__desc${sfx}`);
      await expect(svg.locator(`title#watering-delay-timeline__title${sfx}`)).toHaveText(
        "Why watering again too soon overcorrects",
      );
      await expect(svg.locator(`desc#watering-delay-timeline__desc${sfx}`)).toHaveText(TIMELINE_DESC);
      await expect(svg.locator("circle.diagram-event-marker")).toHaveCount(4);
      await expect(svg.locator("marker")).toHaveCount(0);
    }
    await expect(horizontal.locator("line.diagram-tick")).toHaveCount(4);
    await expect(vertical.locator("line.diagram-tick")).toHaveCount(0);
  });

  test("the figure reads figcaption, svg(s), then a closed 'Text version' disclosure holding the text", async ({ page }) => {
    await load(page);
    for (const [selector, expected] of [
      [FLOW, ["figcaption", "svg", "details"]],
      [TIMELINE, ["figcaption", "svg", "svg", "details"]],
    ] as const) {
      const figure = page.locator(selector);
      const children = await figure.evaluate((el) =>
        Array.from(el.children).map((c) => c.localName),
      );
      expect(children).toEqual(expected);
      const details = figure.locator(':scope > details[data-role="diagram-text-toggle"]');
      await expect(details).toHaveCount(1);
      await expect(details).toHaveClass("diagram-text-toggle");
      await expect(details).not.toHaveAttribute("open", /.*/);
      await expect(details.locator(":scope > summary")).toHaveText("Text version");
      await expect(details.locator(':scope > div[data-role="diagram-text"]')).toHaveCount(1);
    }
    await expect(page.locator(`${FLOW} .diagram-connections`)).toBeHidden();
    await page.locator(`${FLOW} summary`).click();
    await expect(page.locator(`${FLOW} .diagram-connections`)).toContainText(
      "New growth → Plant biomass — adds to (loops back)",
    );
  });

  test("every id in the document is unique, including marker, title and desc ids", async ({ page }) => {
    await load(page);
    const ids = await page.evaluate(() =>
      Array.from(document.querySelectorAll("[id]")).map((el) => el.id),
    );
    const duplicates = ids.filter((id, i) => ids.indexOf(id) !== i);
    expect(duplicates).toEqual([]);
    const markerIds = await page
      .locator("svg marker")
      .evaluateAll((markers) => markers.map((m) => m.id));
    expect(markerIds).toContain("growth-loop-flow__arrow");
    expect(new Set(markerIds).size).toBe(markerIds.length);
  });

  test("the svgs use no inline style, script, image or foreignObject", async ({ page }) => {
    await load(page);
    await expect(page.locator(`${FLOW} svg, ${TIMELINE} svg`)).toHaveCount(3);
    const offending = await page.evaluate(() =>
      Array.from(
        document.querySelectorAll(
          "figure.diagram svg [style], figure.diagram svg[style], figure.diagram svg style, " +
            "figure.diagram svg script, figure.diagram svg image, figure.diagram svg foreignObject",
        ),
      ).map((el) => el.outerHTML),
    );
    expect(offending).toEqual([]);
  });

  test("two renders of the same guide give identical svg markup", async ({ page }) => {
    const snapshot = () =>
      page
        .locator("figure.diagram svg")
        .evaluateAll((svgs) => svgs.map((svg) => svg.outerHTML));
    await load(page);
    const first = await snapshot();
    await load(page);
    const second = await snapshot();
    expect(first.length).toBeGreaterThanOrEqual(3);
    expect(second).toEqual(first);
  });

  test("the horizontal timeline shows on a wide screen and the vertical one at 375px", async ({ page }) => {
    await load(page);
    await page.evaluate(() => {
      location.hash = "#delays-and-leverage";
    });
    await expect(page.locator("#delays-and-leverage")).toHaveClass(/is-current/);
    await expect(page.locator(`${TIMELINE} svg.diagram-svg--timeline-h`)).toBeVisible();
    await expect(page.locator(`${TIMELINE} svg.diagram-svg--timeline-v`)).toBeHidden();

    await page.setViewportSize({ width: 375, height: 812 });
    await expect(page.locator(`${TIMELINE} svg.diagram-svg--timeline-v`)).toBeVisible();
    await expect(page.locator(`${TIMELINE} svg.diagram-svg--timeline-h`)).toBeHidden();
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);
  });

  test("beforeprint opens closed text versions and afterprint restores them", async ({ page }) => {
    await load(page);
    const flowDetails = page.locator(`${FLOW} details[data-role="diagram-text-toggle"]`);
    const timelineDetails = page.locator(`${TIMELINE} details[data-role="diagram-text-toggle"]`);
    await expect(flowDetails).toHaveCount(1);
    await expect(timelineDetails).toHaveCount(1);
    // A disclosure the learner opened stays open after printing.
    await timelineDetails.evaluate((el) => el.setAttribute("open", ""));

    await page.evaluate(() => window.dispatchEvent(new Event("beforeprint")));
    await expect(flowDetails).toHaveAttribute("open", "");
    await expect(flowDetails).toHaveAttribute("data-print-opened", /.*/);
    await expect(timelineDetails).toHaveAttribute("open", "");
    await expect(timelineDetails).not.toHaveAttribute("data-print-opened", /.*/);

    await page.evaluate(() => window.dispatchEvent(new Event("afterprint")));
    await expect(flowDetails).not.toHaveAttribute("open", /.*/);
    await expect(flowDetails).not.toHaveAttribute("data-print-opened", /.*/);
    await expect(timelineDetails).toHaveAttribute("open", "");
  });

  test("print media hides the disclosure summary", async ({ page }) => {
    await load(page);
    await expect(page.locator(`${FLOW} summary`)).toHaveCount(1);
    await page.emulateMedia({ media: "print" });
    await expect(page.locator(`${FLOW} summary`)).toBeHidden();
  });

  test("tampered guide-data (unknown edge target) leaves the text version and no svg while the guide boots", async ({ page }) => {
    const original = '{"from":"biomass","label":"increases","to":"leaf-area"}';
    expect(diagramsHtml).toContain(original);
    const tampered = diagramsHtml.replace(
      original,
      '{"from":"biomass","label":"increases","to":"missing-node"}',
    );
    const consoleErrors: string[] = [];
    const pageErrors: string[] = [];
    page.on("console", (message) => {
      if (message.type() === "error") consoleErrors.push(message.text());
    });
    page.on("pageerror", (error) => pageErrors.push(String(error)));
    await load(page, tampered);

    await expect(page.getByRole("heading", { name: "Thinking in Feedback Loops" })).toBeVisible();
    await expect(page.locator("[data-guide-shell]")).toBeVisible();
    const figure = page.locator(FLOW);
    await expect(figure).toHaveAttribute("data-diagram-state", "text");
    await expect(figure.locator("svg")).toHaveCount(0);
    await expect(figure.locator("details")).toHaveCount(0);
    await expect(figure.locator(':scope > div[data-role="diagram-text"]')).toBeVisible();
    await expect(figure.locator(".diagram-connections")).toContainText("Plant biomass → Leaf area");
    // The other diagrams and the interactive blocks still work.
    await expect(page.locator(TIMELINE)).toHaveAttribute("data-diagram-state", "drawn");
    await expect(page.locator(`${TIMELINE} svg`)).toHaveCount(2);
    await expect(page.locator("html")).toHaveClass(/js-enhanced/);
    // Boot continued past the diagrams: later install steps still ran.
    await expect(page.locator('[data-role="results-page"]')).toHaveCount(1);
    expect(pageErrors).toEqual([]);
    expect(consoleErrors).toContainEqual(
      expect.stringContaining("guide-runtime: diagram fell back to its text version:"),
    );
    expect(consoleErrors.join("\n")).toContain("growth-loop-flow");
  });

  for (const theme of ["light", "dark"] as const) {
    test(`diagram sections have no serious or critical accessibility violations (${theme})`, async ({ page }) => {
      await load(page);
      await page.locator('[data-role="theme-select"]').selectOption(theme);
      await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
      await expect(page.locator(FLOW)).toHaveAttribute("data-diagram-state", "drawn");
      await expectNoSeriousViolations(page);
      await page.locator(`${FLOW} summary`).click();
      await expectNoSeriousViolations(page);

      await page.evaluate(() => {
        location.hash = "#delays-and-leverage";
      });
      await expect(page.locator("#delays-and-leverage")).toHaveClass(/is-current/);
      await expect(page.locator(`${TIMELINE} svg.diagram-svg--timeline-h`)).toBeVisible();
      await expectNoSeriousViolations(page);
    });
  }
});

test.describe("diagram rendering: concept map and comparison (T54)", () => {
  const DIAGRAMS_FIXTURE = "tests/fixtures/guides/feedback-loops.diagrams.guide.json";
  const MAP = "figure#loop-kinds-map";
  const TABLE = "figure#loop-types-comparison";
  const FLOW = "figure#growth-loop-flow";
  const TIMELINE = "figure#watering-delay-timeline";
  const MAP_DESC =
    "Concept map centered on Feedback loop, connected to 3 ideas: Reinforcing loop; Balancing loop; Delay.";
  // §10.4 for the fixture: k = 3 ring nodes, R = 200, NODE_H = 38, hub centre
  // (304, 243); ring centres at 12 o'clock, then clockwise.
  const R3 = 200 * Math.cos(Math.PI / 6);
  const CENTRES: Record<string, [number, number]> = {
    "Feedback loop": [304, 243],
    "Reinforcing loop": [304, 43],
    "Balancing loop": [304 + R3, 343],
    Delay: [304 - R3, 343],
  };
  // Each edge runs centre to centre, clipped at both box borders.
  const EDGES: { from: string; to: string; label: string[]; start: [number, number]; end: [number, number] }[] = [
    { from: "Feedback loop", to: "Reinforcing loop", label: ["can be"], start: [304, 224], end: [304, 62] },
    {
      from: "Feedback loop",
      to: "Balancing loop",
      label: ["can be"],
      start: [304 + 0.19 * R3, 262],
      end: [304 + 0.81 * R3, 324],
    },
    {
      from: "Balancing loop",
      to: "Delay",
      label: ["overshoots with", "a"],
      start: [304 + R3 - 80, 343],
      end: [304 - R3 + 80, 343],
    },
  ];
  let diagramsHtml: string;

  test.beforeAll(() => {
    diagramsHtml = assembleFixtureDocument(DIAGRAMS_FIXTURE);
  });

  async function load(page: import("@playwright/test").Page, html = diagramsHtml) {
    await page.setContent(html, { waitUntil: "load" });
    await expect(page.locator("[data-guide-status]")).toBeHidden();
  }

  async function showComparison(page: import("@playwright/test").Page) {
    await page.evaluate(() => {
      location.hash = "#recognize-loop-types";
    });
    await expect(page.locator("#recognize-loop-types")).toHaveClass(/is-current/);
    await expect(page.locator(TABLE)).toBeVisible();
  }

  async function expectNoSeriousViolations(page: import("@playwright/test").Page) {
    const results = await new AxeBuilder({ page }).analyze();
    const serious = results.violations.filter(
      (v) => v.impact === "serious" || v.impact === "critical",
    );
    expect(serious, JSON.stringify(serious, null, 2)).toEqual([]);
  }

  const near = (actual: number, expected: number) =>
    expect(Math.abs(actual - expected), `${actual} vs ${expected}`).toBeLessThanOrEqual(0.11);

  test("concept map is drawn as one labelled svg[role=img] with the §10.4 viewBox", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(String(error)));
    page.on("console", (message) => {
      if (message.type() === "error") errors.push(message.text());
    });
    await load(page);
    const figure = page.locator(MAP);
    await expect(figure).toHaveAttribute("data-diagram-state", "drawn");
    const svg = figure.locator("svg");
    await expect(svg).toHaveCount(1);
    await expect(svg).toHaveAttribute("role", "img");
    await expect(svg).toHaveAttribute("focusable", "false");
    await expect(svg).toHaveClass("diagram-svg diagram-svg--concept-map");
    await expect(svg).toHaveAttribute("viewBox", "0 0 608 486");
    await expect(svg).toHaveAttribute("width", "608");
    await expect(svg).toHaveAttribute("height", "486");
    await expect(svg).toHaveAttribute("aria-labelledby", "loop-kinds-map__title");
    await expect(svg).toHaveAttribute("aria-describedby", "loop-kinds-map__desc");
    await expect(svg.locator("title#loop-kinds-map__title")).toHaveText("Kinds of feedback");
    await expect(svg.locator("desc#loop-kinds-map__desc")).toHaveText(MAP_DESC);
    const firstChildren = await svg.evaluate((el) =>
      Array.from(el.children).slice(0, 2).map((c) => c.localName),
    );
    expect(firstChildren).toEqual(["title", "desc"]);
    await expect(svg).toBeVisible();
    await expect(page.getByRole("img", { name: "Kinds of feedback" })).toHaveCount(1);
    expect(errors).toEqual([]);
  });

  test("concept map draws the hub at the centre and the ring clockwise from 12 o'clock", async ({ page }) => {
    await load(page);
    const svg = page.locator(`${MAP} svg`);
    const groups = await svg.evaluate((el) =>
      Array.from(el.querySelectorAll(":scope > g")).map((g) => g.getAttribute("class")),
    );
    expect(groups).toEqual(["diagram-edges", "diagram-edge-labels", "diagram-nodes"]);
    await expect(svg.locator("g.diagram-node")).toHaveCount(4);
    const hub = svg.locator("g.diagram-node.diagram-node--hub");
    await expect(hub).toHaveCount(1);
    await expect(hub).toHaveClass("diagram-node diagram-node--hub");
    await expect(hub.locator("text.diagram-node-label")).toHaveText("Feedback loop");
    await expect(page.locator(".diagram-node--hub")).toHaveCount(1);
    const nodes = await svg.locator("g.diagram-node").evaluateAll((gs) =>
      gs.map((g) => {
        const rect = g.querySelector("rect.diagram-node-box")!;
        const num = (name: string) => Number(rect.getAttribute(name));
        return {
          label: g.querySelector("text.diagram-node-label")!.textContent,
          x: num("x"),
          y: num("y"),
          width: num("width"),
          height: num("height"),
          rx: rect.getAttribute("rx"),
        };
      }),
    );
    expect(nodes.map((n) => n.label)).toEqual([
      "Feedback loop",
      "Reinforcing loop",
      "Balancing loop",
      "Delay",
    ]);
    for (const node of nodes) {
      expect(node.width).toBe(160);
      expect(node.height).toBe(38);
      expect(node.rx).toBe("6");
      const [cx, cy] = CENTRES[node.label!];
      near(node.x + node.width / 2, cx);
      near(node.y + node.height / 2, cy);
    }
  });

  test("concept map edges carry arrowheads and labels at the clipped segment midpoints", async ({ page }) => {
    await load(page);
    const svg = page.locator(`${MAP} svg`);
    await expect(svg.locator("path.diagram-edge")).toHaveCount(3);
    await expect(svg.locator("path.diagram-edge--back")).toHaveCount(0);
    await expect(svg.locator("marker#loop-kinds-map__arrow")).toHaveCount(1);
    const markerEnds = await svg
      .locator("path.diagram-edge")
      .evaluateAll((paths) => paths.map((p) => p.getAttribute("marker-end")));
    expect(markerEnds).toEqual(Array(3).fill("url(#loop-kinds-map__arrow)"));

    const labels = await svg.locator("g.diagram-edge-label").evaluateAll((gs) =>
      gs.map((g) => {
        const bg = g.querySelector("rect.diagram-edge-label-bg")!;
        const num = (name: string) => Number(bg.getAttribute(name));
        return {
          lines: Array.from(g.querySelectorAll("text.diagram-edge-label-text tspan")).map((t) => t.textContent),
          cx: num("x") + num("width") / 2,
          cy: num("y") + num("height") / 2,
          width: num("width"),
          height: num("height"),
        };
      }),
    );
    expect(labels.map((l) => l.lines)).toEqual(EDGES.map((e) => e.label));
    // §10.3 label box: maxLineLen * EDGE_CHAR_W + 8 wide, lines * EDGE_LINE_H + 4 high.
    expect(labels.map((l) => [l.width, l.height])).toEqual([
      [50, 19],
      [50, 19],
      [113, 34],
    ]);
    EDGES.forEach((edge, i) => {
      near(labels[i].cx, (edge.start[0] + edge.end[0]) / 2);
      near(labels[i].cy, (edge.start[1] + edge.end[1]) / 2);
    });
  });

  test("concept map edge endpoints are clipped at the node box borders", async ({ page }) => {
    await load(page);
    const svg = page.locator(`${MAP} svg`);
    const ds = await svg
      .locator("path.diagram-edge")
      .evaluateAll((paths) => paths.map((p) => p.getAttribute("d") ?? ""));
    expect(ds).toHaveLength(3);
    ds.forEach((d, i) => {
      expect(d).toMatch(/^M-?[\d.]+,-?[\d.]+ L-?[\d.]+,-?[\d.]+$/);
      const [sx, sy, tx, ty] = (d.match(/-?\d+(?:\.\d+)?/g) ?? []).map(Number);
      const edge = EDGES[i];
      near(sx, edge.start[0]);
      near(sy, edge.start[1]);
      near(tx, edge.end[0]);
      near(ty, edge.end[1]);
      // Each endpoint sits on its own box border, never inside the box.
      for (const [[px, py], label] of [
        [[sx, sy], edge.from],
        [[tx, ty], edge.to],
      ] as const) {
        const [cx, cy] = CENTRES[label];
        const onVertical = Math.abs(Math.abs(px - cx) - 80) <= 0.11 && Math.abs(py - cy) <= 19.11;
        const onHorizontal = Math.abs(Math.abs(py - cy) - 19) <= 0.11 && Math.abs(px - cx) <= 80.11;
        expect(onVertical || onHorizontal, `${label} endpoint (${px}, ${py})`).toBe(true);
      }
    });
  });

  test("concept map reads figcaption, svg, then a closed 'Text version' disclosure", async ({ page }) => {
    await load(page);
    const figure = page.locator(MAP);
    const children = await figure.evaluate((el) => Array.from(el.children).map((c) => c.localName));
    expect(children).toEqual(["figcaption", "svg", "details"]);
    const details = figure.locator(':scope > details[data-role="diagram-text-toggle"]');
    await expect(details).toHaveCount(1);
    await expect(details).toHaveClass("diagram-text-toggle");
    await expect(details).not.toHaveAttribute("open", /.*/);
    await expect(details.locator(":scope > summary")).toHaveText("Text version");
    await expect(details.locator(':scope > div[data-role="diagram-text"]')).toHaveCount(1);
    await expect(figure.locator(".diagram-map")).toBeHidden();
    await details.locator("summary").click();
    await expect(figure.locator(".diagram-map")).toContainText("overshoots with a → Delay");
  });

  test("every id in the document stays unique with the concept map drawn", async ({ page }) => {
    await load(page);
    await expect(page.locator(MAP)).toHaveAttribute("data-diagram-state", "drawn");
    const ids = await page.evaluate(() =>
      Array.from(document.querySelectorAll("[id]")).map((el) => el.id),
    );
    expect(ids.filter((id, i) => ids.indexOf(id) !== i)).toEqual([]);
    for (const id of ["loop-kinds-map__title", "loop-kinds-map__desc", "loop-kinds-map__arrow"]) {
      expect(ids).toContain(id);
    }
    const markerIds = await page.locator("svg marker").evaluateAll((markers) => markers.map((m) => m.id));
    expect(markerIds).toEqual(expect.arrayContaining(["growth-loop-flow__arrow", "loop-kinds-map__arrow"]));
    expect(new Set(markerIds).size).toBe(markerIds.length);
  });

  test("the concept map svg uses no inline style, script, image or foreignObject", async ({ page }) => {
    await load(page);
    await expect(page.locator(`${MAP} svg`)).toHaveCount(1);
    const offending = await page.evaluate(() =>
      Array.from(
        document.querySelectorAll(
          "figure#loop-kinds-map svg [style], figure#loop-kinds-map svg[style], figure#loop-kinds-map svg style, " +
            "figure#loop-kinds-map svg script, figure#loop-kinds-map svg image, figure#loop-kinds-map svg foreignObject",
        ),
      ).map((el) => el.outerHTML),
    );
    expect(offending).toEqual([]);
  });

  test("two renders give identical concept map svg markup", async ({ page }) => {
    const snapshot = () =>
      page.locator(`${MAP} svg`).evaluateAll((svgs) => svgs.map((svg) => svg.outerHTML));
    await load(page);
    const first = await snapshot();
    await load(page);
    const second = await snapshot();
    expect(first).toHaveLength(1);
    expect(second).toEqual(first);
  });

  test("tampered concept-map guide-data (unknown hub) leaves the text version while the guide boots", async ({ page }) => {
    const original = '"hub":"feedback-loop"';
    expect(diagramsHtml).toContain(original);
    const tampered = diagramsHtml.replace(original, '"hub":"missing-node"');
    const consoleErrors: string[] = [];
    const pageErrors: string[] = [];
    page.on("console", (message) => {
      if (message.type() === "error") consoleErrors.push(message.text());
    });
    page.on("pageerror", (error) => pageErrors.push(String(error)));
    await load(page, tampered);

    await expect(page.locator("[data-guide-shell]")).toBeVisible();
    const figure = page.locator(MAP);
    await expect(figure).toHaveAttribute("data-diagram-state", "text");
    await expect(figure.locator("svg")).toHaveCount(0);
    await expect(figure.locator("details")).toHaveCount(0);
    await expect(figure.locator(':scope > div[data-role="diagram-text"]')).toBeVisible();
    await expect(figure.locator(".diagram-map")).toContainText("Feedback loop (central idea)");
    // The neighbouring flow is still drawn and the comparison is still a table.
    await expect(page.locator(FLOW)).toHaveAttribute("data-diagram-state", "drawn");
    await expect(page.locator(TABLE)).toHaveAttribute("data-diagram-state", "table");
    await expect(page.locator(TIMELINE)).toHaveAttribute("data-diagram-state", "drawn");
    await expect(page.locator("html")).toHaveClass(/js-enhanced/);
    await expect(page.locator('[data-role="results-page"]')).toHaveCount(1);
    expect(pageErrors).toEqual([]);
    expect(consoleErrors).toContainEqual(
      expect.stringContaining("guide-runtime: diagram fell back to its text version:"),
    );
    expect(consoleErrors.join("\n")).toContain("loop-kinds-map");
  });

  test("comparison stays the server table: state table, no svg, scoped headers and no disclosure", async ({ page }) => {
    await load(page);
    await showComparison(page);
    const figure = page.locator(TABLE);
    await expect(figure).toHaveAttribute("data-diagram-state", "table");
    await expect(figure.locator("svg")).toHaveCount(0);
    await expect(figure.locator("details")).toHaveCount(0);
    const children = await figure.evaluate((el) => Array.from(el.children).map((c) => c.localName));
    expect(children).toEqual(["figcaption", "div"]);
    const text = figure.locator(':scope > div[data-role="diagram-text"]');
    await expect(text).toBeVisible();
    const table = text.locator("table.diagram-table");
    await expect(table).toBeVisible();
    const colHeaders = await table
      .locator('thead th[scope="col"]')
      .evaluateAll((ths) => ths.map((th) => th.textContent));
    expect(colHeaders).toEqual(["Criterion", "Reinforcing loop", "Balancing loop"]);
    const rowHeaders = await table
      .locator('tbody th[scope="row"]')
      .evaluateAll((ths) => ths.map((th) => th.textContent));
    expect(rowHeaders).toEqual(["What it does", "Garden example", "Main risk"]);
    await expect(table.locator("th:not([scope])")).toHaveCount(0);
    await expect(table.locator("tbody td")).toHaveCount(6);
    await expect(table.locator("tbody td em")).toHaveText("Overcorrection");
    await expect(page.getByRole("columnheader", { name: "Reinforcing loop" })).toHaveCount(1);
    await expect(page.getByRole("rowheader", { name: "Main risk" })).toHaveCount(1);
  });

  test("comparison table is styled: scrollable wrapper and tinted row headers", async ({ page }) => {
    await load(page);
    await showComparison(page);
    const text = page.locator(`${TABLE} > div[data-role="diagram-text"]`);
    await expect(text).toHaveCSS("overflow-x", "auto");
    const [rowHeaderBg, subtle] = await page.evaluate(() => {
      const th = document.querySelector('figure#loop-types-comparison th[scope="row"]')!;
      const probe = document.createElement("div");
      probe.style.background = "var(--ep-color-surface-subtle)";
      document.body.appendChild(probe);
      const expected = getComputedStyle(probe).backgroundColor;
      probe.remove();
      return [getComputedStyle(th).backgroundColor, expected];
    });
    expect(rowHeaderBg).toBe(subtle);
  });

  for (const theme of ["light", "dark"] as const) {
    test(`concept map and comparison have no serious or critical accessibility violations (${theme})`, async ({ page }) => {
      await load(page);
      await page.locator('[data-role="theme-select"]').selectOption(theme);
      await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
      await expect(page.locator(MAP)).toHaveAttribute("data-diagram-state", "drawn");
      await expect(page.locator(`${MAP} svg`)).toBeVisible();
      await expectNoSeriousViolations(page);
      await page.locator(`${MAP} summary`).click();
      await expect(page.locator(`${MAP} .diagram-map`)).toBeVisible();
      await expectNoSeriousViolations(page);

      await showComparison(page);
      await expect(page.locator(TABLE)).toHaveAttribute("data-diagram-state", "table");
      await expectNoSeriousViolations(page);
    });
  }
});

test.describe("Codex round 1 on PR #42: no-JS text version, trimmed runtime limits (T57)", () => {
  const DIAGRAMS_FIXTURE = "tests/fixtures/guides/feedback-loops.diagrams.guide.json";
  const DIAGRAM_IDS = ["growth-loop-flow", "loop-kinds-map", "loop-types-comparison", "watering-delay-timeline"];
  let scratch: string;

  test.beforeAll(() => {
    scratch = mkdtempSync(path.join(tmpdir(), "ep-t57-"));
  });

  test.afterAll(() => {
    rmSync(scratch, { recursive: true, force: true });
  });

  test("without JavaScript the guide and every diagram's text version are visible, not the loading shell", async ({ browser }) => {
    const file = path.join(scratch, "no-js.html");
    writeFileSync(file, assembleFixtureDocument(DIAGRAMS_FIXTURE), "utf8");
    const context = await browser.newContext({ javaScriptEnabled: false });
    const page = await context.newPage();
    try {
      await page.goto(`file://${file}`);
      await expect(page.locator("html")).not.toHaveClass(/js-enhanced/);
      await expect(page.locator("[data-guide-shell]")).toBeVisible();
      await expect(page.locator("[data-guide-status]")).toBeHidden();
      await expect(page.getByRole("heading", { name: "Thinking in Feedback Loops" })).toBeVisible();
      for (const id of DIAGRAM_IDS) {
        const figure = page.locator(`figure#${id}`);
        await expect(figure).toBeVisible();
        await expect(figure.locator("svg")).toHaveCount(0);
        await expect(figure.locator(':scope > div[data-role="diagram-text"]')).toBeVisible();
      }
      await expect(page.locator("figure#growth-loop-flow .diagram-connections")).toContainText(
        "Plant biomass → Leaf area",
      );
      // Every section is stacked and readable, like the answer-key print.
      const sections = page.locator('main section[data-role="guide-section"]');
      const count = await sections.count();
      expect(count).toBeGreaterThan(1);
      for (let i = 0; i < count; i += 1) await expect(sections.nth(i)).toBeVisible();
      await expect(page.locator('[data-role="kc-explanation"]').first()).toBeVisible();
      await expect(page.locator('[data-role="answer-marker"]').first()).toBeVisible();
      await expect(page.locator('[data-role="nav-link"]').first()).toBeVisible();
      // Controls that only work with JavaScript are not offered.
      for (const selector of [
        ".course-controls",
        ".section-nav-controls",
        ".section-complete-controls",
        ".kc-controls",
        ".wr-controls",
        ".sc-controls",
        ".rf-controls",
        ".reflection-input",
        '[data-role="kc-choice"]',
        '[data-role="sc-choice"]',
        ".nav-toggle",
      ]) {
        const nodes = page.locator(selector);
        const n = await nodes.count();
        for (let i = 0; i < n; i += 1) await expect(nodes.nth(i), selector).toBeHidden();
      }
    } finally {
      await context.close();
    }
  });

  test("padded-but-valid diagram strings are measured and drawn trimmed, not dropped to text", async ({ page }) => {
    const pad = (s: string) => `  ${s}  `;
    const title = "T".repeat(110) + " whole ok"; // 119 code points
    const label = "Plant biomass " + "b".repeat(34); // 48 code points
    const edge = "increases " + "e".repeat(22); // 32 code points
    const when = "Day 1, morning " + "w".repeat(17); // 32 code points
    const guide = JSON.parse(readFileSync(path.join(ROOT, DIAGRAMS_FIXTURE), "utf8"));
    const blocks = guide.modules.flatMap((m: any) => m.sections).flatMap((s: any) => s.blocks);
    const flow = blocks.find((b: any) => b.id === "growth-loop-flow");
    flow.title = pad(title);
    flow.nodes[0].label = pad(label);
    flow.edges[0].label = pad(edge);
    const timeline = blocks.find((b: any) => b.id === "watering-delay-timeline");
    timeline.title = pad(title);
    timeline.events[0].when = pad(when);
    timeline.events[0].label = pad(label);
    const file = path.join(scratch, "padded.guide.json");
    writeFileSync(file, JSON.stringify(guide), "utf8");
    // The Python validator accepts these strings: it measures the trimmed value.
    const findings = execFileSync(
      "python3",
      [
        "-c",
        [
          "from pathlib import Path",
          "from education_pipeline.guides import validate_guide",
          `print(len(validate_guide(Path(${JSON.stringify(file)}).read_bytes()).findings), end='')`,
        ].join(";"),
      ],
      { cwd: ROOT, encoding: "utf8" },
    );
    expect(findings).toBe("0");
    const html = assembleFixtureDocument(file);
    expect(html).toContain(JSON.stringify(pad(label)));

    const consoleErrors: string[] = [];
    page.on("console", (message) => {
      if (message.type() === "error") consoleErrors.push(message.text());
    });
    await page.setContent(html, { waitUntil: "load" });
    await expect(page.locator("[data-guide-status]")).toBeHidden();
    const figure = page.locator("figure#growth-loop-flow");
    await expect(figure).toHaveAttribute("data-diagram-state", "drawn");
    expect(await figure.locator("svg > title").textContent()).toBe(title);
    const desc = await figure.locator("svg > desc").textContent();
    expect(desc).toContain(`Steps in order: ${label}; Leaf area;`);
    const edgeText = await figure.locator("g.diagram-edge-label").first().locator("text").allTextContents();
    expect(edgeText[0]).toBe("increases");
    const timelineFigure = page.locator("figure#watering-delay-timeline");
    await expect(timelineFigure).toHaveAttribute("data-diagram-state", "drawn");
    for (const svg of await timelineFigure.locator("svg").all()) {
      expect(await svg.locator("title").textContent()).toBe(title);
      expect(await svg.locator("desc").textContent()).toBe(
        `Timeline of 4 events, from ${when} (${label}) to Day 4 (Leaves recover).`,
      );
    }
    expect(consoleErrors.join("\n")).not.toContain("fell back to its text version");
  });
});
