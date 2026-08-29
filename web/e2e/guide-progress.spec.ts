import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { execFileSync } from "node:child_process";
import { createServer } from "node:http";
import type { Server } from "node:http";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

// Progress portability for the exported guide runtime: the carry-over offer
// made when a re-export moved the storage key, and the download/restore
// progress-file controls. Assembles the same fixture document as
// guide-runtime.spec.ts and serves it over a throwaway HTTP server plus a
// file:// URL; no daemon is involved.

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

  tempDir = mkdtempSync(path.join(tmpdir(), "guide-progress-e2e-"));
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

// The live key is `education-pipeline:guide:<course>:<content hash>:v<major>`.
// The hash is an FNV-1a digest of the exact embedded JSON, so any string that
// is not the current document's digest stands in for "a previous export" --
// the scan must find it by shape alone.
const COURSE_KEY_PREFIX = "education-pipeline:guide:feedback-loops:";
const OLD_KEY = `${COURSE_KEY_PREFIX}deadbeef:v1`;
const OLDER_KEY = `${COURSE_KEY_PREFIX}0badf00d:v1`;
const OTHER_COURSE_KEY = "education-pipeline:guide:other-course:deadbeef:v1";
const OTHER_MAJOR_KEY = `${COURSE_KEY_PREFIX}deadbeef:v9`;

const NEWEST_STATE = {
  completedSections: ["feedback-foundations", "recognize-loop-types", "section-that-was-cut"],
  interactions: {
    "check-loop-type": {
      type: "knowledge_check",
      completed: true,
      submittedCount: 1,
      selectedIds: ["release-reinforcing"],
    },
    "block-that-was-cut": { type: "reflection", completed: true, text: "gone", skipped: false },
  },
  lastSection: "recognize-loop-types",
  theme: "system",
  updatedAt: 1_700_000_002_000,
};

const OLDER_STATE = {
  completedSections: ["feedback-foundations"],
  interactions: {},
  lastSection: "feedback-foundations",
  theme: "system",
  updatedAt: 1_700_000_001_000,
};

const DECOY_STATE = {
  completedSections: ["delays-and-leverage", "garden-decision"],
  interactions: {},
  lastSection: "garden-decision",
  theme: "system",
  updatedAt: 1_900_000_000_000,
};

// Valid, but every id in it was cut from the course: nothing survives the
// filter, so there is nothing to offer.
const GHOST_ONLY_STATE = {
  completedSections: ["section-that-was-cut"],
  interactions: {
    "block-that-was-cut": { type: "reflection", completed: true, text: "gone", skipped: false },
  },
  lastSection: "section-that-was-cut",
  theme: "system",
  updatedAt: 1_700_000_003_000,
};

async function seed(page: import("@playwright/test").Page, entries: Record<string, unknown>) {
  await page.addInitScript((seeded) => {
    try {
      for (const [key, value] of Object.entries(seeded as Record<string, unknown>)) {
        window.localStorage.setItem(key, JSON.stringify(value));
      }
    } catch (_error) {
      /* the test asserts on the outcome, not on the seeding */
    }
  }, entries);
}

/** Every stored record except the seeded ones, keyed by storage key. */
async function currentRecords(page: import("@playwright/test").Page, seededKeys: string[]) {
  return page.evaluate((skip) => {
    const out: Record<string, unknown> = {};
    for (let i = 0; i < window.localStorage.length; i++) {
      const key = window.localStorage.key(i);
      if (!key || skip.includes(key)) continue;
      out[key] = JSON.parse(window.localStorage.getItem(key) || "null");
    }
    return out;
  }, seededKeys);
}

const banner = '[data-role="progress-migration"]';

test.describe("progress carried over from a previous export", () => {
  test("offers the newest matching record and resumes only what still exists", async ({ page }) => {
    await seed(page, {
      [OLD_KEY]: NEWEST_STATE,
      [OLDER_KEY]: OLDER_STATE,
      [OTHER_COURSE_KEY]: DECOY_STATE,
      [OTHER_MAJOR_KEY]: DECOY_STATE,
    });
    await page.goto(httpBaseUrl, { waitUntil: "load" });

    const offer = page.locator(banner);
    await expect(offer).toBeVisible();
    await expect(offer).toContainText("You have progress from a previous version of this course.");
    // Two of the three completed sections and one of the two interactions
    // survive the filter against this document.
    await expect(offer).toContainText("2 completed sections and 1 saved interaction");
    await expect(page.locator('[data-role="progress-summary"]')).toContainText(
      "0 of 4 sections complete",
    );

    await page.getByRole("button", { name: "Resume that progress" }).click();

    await expect(page.locator('[data-role="progress-summary"]')).toContainText(
      "2 of 4 sections complete",
    );
    await expect(page.locator('[data-role="progress-summary"]')).toContainText(
      "1 of 5 interactions complete",
    );
    await expect(offer).toBeHidden();

    // The knowledge check the old record answered is restored as submitted.
    await page.evaluate(() => {
      location.hash = "#recognize-loop-types";
    });
    const kc = page.locator("article.knowledge_check").first();
    await expect(kc).toHaveClass(/is-submitted/);
    await expect(kc.locator('[data-role="kc-choice"][data-correct="true"]')).toBeChecked();

    // Adopted under this export's own key; ids that no longer exist are
    // dropped, and the previous key is left untouched for older files.
    const records = await currentRecords(page, [
      OLD_KEY,
      OLDER_KEY,
      OTHER_COURSE_KEY,
      OTHER_MAJOR_KEY,
    ]);
    const keys = Object.keys(records);
    expect(keys).toHaveLength(1);
    expect(keys[0]).toMatch(/^education-pipeline:guide:feedback-loops:[0-9a-f]{8}:v1$/);
    expect(keys[0]).not.toBe(OLD_KEY);
    const adopted = records[keys[0]] as Record<string, unknown>;
    expect(adopted.completedSections).toEqual(["feedback-foundations", "recognize-loop-types"]);
    expect(Object.keys(adopted.interactions as object)).toEqual(["check-loop-type"]);
    expect(typeof adopted.updatedAt).toBe("number");
    const previous = await page.evaluate((key) => window.localStorage.getItem(key), OLD_KEY);
    expect(JSON.parse(previous || "null")).toEqual(NEWEST_STATE);
    expect(adopted.migrationDecided).toBe(true);

    // Answered, so it never returns -- not even though the seeded previous
    // record is still there on the next load.
    await page.reload({ waitUntil: "load" });
    await expect(page.locator(banner)).toBeHidden();
    await expect(page.locator('[data-role="progress-summary"]')).toContainText(
      "2 of 4 sections complete",
    );
  });

  test("the offer stands across reloads until the learner answers it", async ({ page }) => {
    // Opening the guide records a last section and a theme under this
    // export's own key. That must not count as "already decided": a learner
    // who opens the replacement file and closes it still gets the offer.
    await seed(page, { [OLD_KEY]: NEWEST_STATE });
    await page.goto(httpBaseUrl, { waitUntil: "load" });
    await expect(page.locator(banner)).toBeVisible();

    await page.reload({ waitUntil: "load" });
    await expect(page.locator(banner)).toBeVisible();
    await page.reload({ waitUntil: "load" });
    await expect(page.locator(banner)).toContainText(
      "You have progress from a previous version of this course.",
    );

    // A record exists under the current key by now; it simply carries no
    // progress and no decision.
    const records = await currentRecords(page, [OLD_KEY]);
    const current = Object.values(records)[0] as Record<string, unknown>;
    expect(current.completedSections).toEqual([]);
    expect(current.migrationDecided).toBeUndefined();
  });

  test("start fresh dismisses the offer and it stays dismissed on reload", async ({ page }) => {
    await seed(page, { [OLD_KEY]: NEWEST_STATE });
    await page.goto(httpBaseUrl, { waitUntil: "load" });

    const offer = page.locator(banner);
    await expect(offer).toBeVisible();
    await page.getByRole("button", { name: "Start fresh" }).click();
    await expect(offer).toBeHidden();
    await expect(page.locator('[data-role="progress-summary"]')).toContainText(
      "0 of 4 sections complete",
    );

    const records = await currentRecords(page, [OLD_KEY]);
    expect((Object.values(records)[0] as Record<string, unknown>).migrationDecided).toBe(true);

    await page.reload({ waitUntil: "load" });
    await expect(page.locator("[data-guide-status]")).toBeHidden();
    await expect(page.locator(banner)).toBeHidden();
    await expect(page.locator('[data-role="progress-summary"]')).toContainText(
      "0 of 4 sections complete",
    );
  });

  test("real progress on this export retires the offer without an answer", async ({ page }) => {
    await seed(page, { [OLD_KEY]: NEWEST_STATE });
    await page.goto(httpBaseUrl, { waitUntil: "load" });
    await expect(page.locator(banner)).toBeVisible();

    // The learner ignored the banner and just started working: they have
    // moved on, so the offer stops asking.
    await page.locator("section.is-current").locator('[data-role="mark-complete"]').click();
    await expect(page.locator('[data-role="progress-summary"]')).toContainText(
      "1 of 4 sections complete",
    );

    await page.reload({ waitUntil: "load" });
    await expect(page.locator(banner)).toBeHidden();
    await expect(page.locator('[data-role="progress-summary"]')).toContainText(
      "1 of 4 sections complete",
    );
  });

  test("a previous record whose ids were all cut is not offered", async ({ page }) => {
    await seed(page, { [OLD_KEY]: GHOST_ONLY_STATE });
    await page.goto(httpBaseUrl, { waitUntil: "load" });

    await expect(page.getByRole("heading", { name: "Thinking in Feedback Loops" })).toBeVisible();
    await expect(page.locator(banner)).toBeHidden();
  });

  test("no previous record means no offer at all", async ({ page }) => {
    await seed(page, { [OTHER_COURSE_KEY]: DECOY_STATE, [OTHER_MAJOR_KEY]: DECOY_STATE });
    await page.goto(httpBaseUrl, { waitUntil: "load" });

    await expect(page.getByRole("heading", { name: "Thinking in Feedback Loops" })).toBeVisible();
    await expect(page.locator(banner)).toBeHidden();
    await expect(page.locator('[data-role="progress-summary"]')).toContainText(
      "0 of 4 sections complete",
    );
  });

  test("an unreadable previous record is ignored rather than offered", async ({ page }) => {
    await page.addInitScript((key) => {
      try {
        window.localStorage.setItem(key as string, "{not valid json");
      } catch (_error) {
        /* asserted through the page, not the seeding */
      }
    }, OLD_KEY);
    await page.goto(httpBaseUrl, { waitUntil: "load" });

    await expect(page.getByRole("heading", { name: "Thinking in Feedback Loops" })).toBeVisible();
    await expect(page.locator(banner)).toBeHidden();
  });

  test("the visible offer has no serious or critical accessibility violations", async ({ page }) => {
    await seed(page, { [OLD_KEY]: NEWEST_STATE });
    await page.goto(httpBaseUrl, { waitUntil: "load" });
    await expect(page.locator(banner)).toBeVisible();

    const results = await new AxeBuilder({ page }).analyze();
    const serious = results.violations.filter(
      (v) => v.impact === "serious" || v.impact === "critical",
    );
    expect(serious, JSON.stringify(serious, null, 2)).toEqual([]);
  });

  test("the offer works the same way from a file:// URL", async ({ page }) => {
    await seed(page, { [OLD_KEY]: NEWEST_STATE });
    await page.goto(fileUrl, { waitUntil: "load" });

    await expect(page.locator(banner)).toBeVisible();
    await page.getByRole("button", { name: "Resume that progress" }).click();
    await expect(page.locator('[data-role="progress-summary"]')).toContainText(
      "2 of 4 sections complete",
    );
  });
});

test.describe("progress files", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto(httpBaseUrl, { waitUntil: "load" });
  });

  test("downloads the current progress as a portable JSON envelope", async ({ page }) => {
    const current = page.locator("section.is-current");
    await current.locator('[data-role="mark-complete"]').click();
    await expect(page.locator('[data-role="progress-summary"]')).toContainText(
      "1 of 4 sections complete",
    );

    const [download] = await Promise.all([
      page.waitForEvent("download"),
      page.getByRole("button", { name: "Download progress" }).click(),
    ]);
    expect(download.suggestedFilename()).toBe("feedback-loops-progress.json");

    const saved = await download.path();
    expect(saved).toBeTruthy();
    const payload = JSON.parse(readFileSync(saved as string, "utf8"));
    expect(payload.format).toBe("education-pipeline.guide-progress");
    expect(payload.version).toBe(1);
    expect(payload.course_id).toBe("feedback-loops");
    expect(payload.schema_version).toBe("1.0");
    expect(Number.isNaN(Date.parse(payload.saved_at))).toBe(false);
    expect(payload.state.completedSections).toEqual(["feedback-foundations"]);
    expect(payload.state.lastSection).toBe("feedback-foundations");
    expect(typeof payload.state.updatedAt).toBe("number");
    await expect(page.locator('[data-role="progress-file-status"]')).toContainText("downloaded");

    // Round trip: wipe the browser-held progress, then restore it from the
    // file that was just written.
    page.once("dialog", (dialog) => dialog.accept());
    await page.locator('[data-role="reset-progress"]').click();
    await expect(page.locator('[data-role="progress-summary"]')).toContainText(
      "0 of 4 sections complete",
    );
    await page.locator('[data-role="progress-file-input"]').setInputFiles(saved as string);
    await expect(page.locator('[data-role="progress-summary"]')).toContainText(
      "1 of 4 sections complete",
    );
  });

  test("restores a hand-made progress file and filters it to this guide", async ({ page }) => {
    const filePath = path.join(tempDir, "restore.json");
    writeFileSync(
      filePath,
      JSON.stringify({
        format: "education-pipeline.guide-progress",
        version: 1,
        course_id: "feedback-loops",
        schema_version: "1.0",
        saved_at: "2026-01-01T00:00:00.000Z",
        state: NEWEST_STATE,
      }),
      "utf8",
    );

    await page.locator('[data-role="progress-file-input"]').setInputFiles(filePath);

    await expect(page.locator('[data-role="progress-summary"]')).toContainText(
      "2 of 4 sections complete",
    );
    await expect(page.locator('[data-role="progress-summary"]')).toContainText(
      "1 of 5 interactions complete",
    );
  });

  test("a file from another course is applied only after confirmation", async ({ page }) => {
    const filePath = path.join(tempDir, "other-course.json");
    writeFileSync(
      filePath,
      JSON.stringify({
        format: "education-pipeline.guide-progress",
        version: 1,
        course_id: "some-other-course",
        schema_version: "1.0",
        saved_at: "2026-01-01T00:00:00.000Z",
        state: OLDER_STATE,
      }),
      "utf8",
    );

    const messages: string[] = [];
    page.on("dialog", (dialog) => {
      messages.push(dialog.message());
      dialog.dismiss();
    });
    await page.locator('[data-role="progress-file-input"]').setInputFiles(filePath);

    await expect(page.locator('[data-role="progress-file-status"]')).toContainText(
      "Restore cancelled",
    );
    await expect(page.locator('[data-role="progress-summary"]')).toContainText(
      "0 of 4 sections complete",
    );
    expect(messages.join(" ")).toContain("some-other-course");
  });

  test("a file that is not a progress file reports an error and leaves the guide working", async ({
    page,
  }) => {
    const garbagePath = path.join(tempDir, "garbage.json");
    writeFileSync(garbagePath, "this is not json at all", "utf8");
    const wrongShapePath = path.join(tempDir, "wrong-shape.json");
    writeFileSync(wrongShapePath, JSON.stringify({ format: "something-else" }), "utf8");
    const noStatePath = path.join(tempDir, "no-state.json");
    writeFileSync(
      noStatePath,
      JSON.stringify({ format: "education-pipeline.guide-progress", version: 1, state: 7 }),
      "utf8",
    );

    const status = page.locator('[data-role="progress-file-status"]');
    const input = page.locator('[data-role="progress-file-input"]');

    await input.setInputFiles(garbagePath);
    await expect(status).toContainText("not an Education Pipeline progress file");
    await input.setInputFiles(wrongShapePath);
    await expect(status).toContainText("not an Education Pipeline progress file");
    await input.setInputFiles(noStatePath);
    await expect(status).toContainText("no readable progress");

    // Nothing was adopted and the guide is still fully operable.
    await expect(page.locator('[data-role="progress-summary"]')).toContainText(
      "0 of 4 sections complete",
    );
    const current = page.locator("section.is-current");
    await current.locator('[data-role="next-section"]').click();
    await expect(page.locator("#recognize-loop-types")).toHaveClass(/is-current/);
    const kc = page.locator("article.knowledge_check").first();
    await kc.locator('[data-role="kc-choice"][data-correct="true"]').first().check();
    await kc.locator('[data-role="kc-submit"]').click();
    await expect(kc.locator('[data-role="kc-result"]')).toContainText("Correct");
  });
});

test.describe("progress files without local storage", () => {
  // Some browsers refuse localStorage for a file: URL entirely. Progress is
  // then session-only, and downloading it is the reader's only way out.
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      Object.defineProperty(window, "localStorage", {
        configurable: true,
        get() {
          throw new Error("storage denied");
        },
      });
    });
    await page.goto(httpBaseUrl, { waitUntil: "load" });
    await expect(page.locator('[data-role="storage-notice"]')).toBeVisible();
  });

  test("downloads the in-memory progress record anyway", async ({ page }) => {
    await page.locator("section.is-current").locator('[data-role="mark-complete"]').click();
    await expect(page.locator('[data-role="progress-summary"]')).toContainText(
      "1 of 4 sections complete",
    );

    const [download] = await Promise.all([
      page.waitForEvent("download"),
      page.getByRole("button", { name: "Download progress" }).click(),
    ]);
    const saved = await download.path();
    const payload = JSON.parse(readFileSync(saved as string, "utf8"));
    expect(payload.format).toBe("education-pipeline.guide-progress");
    expect(payload.state.completedSections).toEqual(["feedback-foundations"]);
  });

  test("restoring a file still updates the progress shown for this viewing", async ({ page }) => {
    const filePath = path.join(tempDir, "session-only.json");
    writeFileSync(
      filePath,
      JSON.stringify({
        format: "education-pipeline.guide-progress",
        version: 1,
        course_id: "feedback-loops",
        schema_version: "1.0",
        saved_at: "2026-01-01T00:00:00.000Z",
        state: NEWEST_STATE,
      }),
      "utf8",
    );

    await page.locator('[data-role="progress-file-input"]').setInputFiles(filePath);

    // Nothing can be stored, so the guide must not reload itself: it keeps
    // the restored record in memory and refreshes the summary in place.
    await expect(page.locator('[data-role="progress-summary"]')).toContainText(
      "2 of 4 sections complete",
    );
    await expect(page.locator('[data-role="progress-file-status"]')).toContainText(
      "Progress restored",
    );
  });
});
