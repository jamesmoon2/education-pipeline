import { expect, test, type Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { rmSync } from "node:fs";
import { resolve } from "node:path";
import { bootDaemon, type DaemonHandle } from "./helpers/daemon";

// T63 (plan decisions 15-17), in the real cockpit iframe: a board mutation
// that leaves the guide HTML unchanged only refetches -- the preview document
// is not reloaded and the reviewer stays on their section -- and when the
// rendered guide does change, the reloaded preview is sent back to the last
// section the reviewer moved to.

const REPO_ROOT = resolve(import.meta.dirname, "../..");
const KEEP = "pb-keep";
const RESTORE = "pb-restore";
const PREVIEW_IFRAME = 'iframe[title="Interactive guide preview"]';

// Drives an interactive-guide run to an approved repair out of process, as
// the CLI would. argv: workspace, topic, "validate" to also run final
// validation (the board then offers Finalize) or "" to stop before it (the
// board offers "Run final validation").
const DRIVE_RUN = `
import json, sys
from pathlib import Path
from education_pipeline import ContentContract, RunStore, TopicStore
ws, topic, validate = Path(sys.argv[1]), sys.argv[2], sys.argv[3] == "validate"
guide = Path("tests/fixtures/guides/feedback-loops.guide.json").read_text(encoding="utf-8")
spec = {"contract_version": 1, "guide_schema_version": "1.0", "blueprint": "conceptual-foundations",
  "estimated_minutes": 30, "outcomes": [{"id": "identify-loop", "text": "Identify reinforcing and balancing feedback."}],
  "required_interactions": ["knowledge_check", "worked_reveal", "scenario", "reflection"],
  "personalization_requirements": ["Use gardening examples where they clarify the concept."],
  "source_policy": "Sources required for factual claims that are not common knowledge."}
outline = {"contract_version": 1, "modules": {"feedback-loops": {"outcome_ids": ["identify-loop"],
  "estimated_minutes": 30, "interaction_types": ["knowledge_check", "worked_reveal"]}}}
TopicStore(ws).save_topic_toml(topic, f'schema_version = 1\\nid = "{topic}"\\ntitle = "Preview bridge"\\n')
runs = RunStore(ws)
runs.create_run(topic, content_contract=ContentContract.interactive_guide_v1())
def respond(prompt, text, stage):
    prompt.response_path.write_text(text, encoding="utf-8")
    runs.approve_stage(topic, stage)
respond(runs.write_topic_spec_prompt(topic),
  "# Spec\\n\\n\`\`\`education-pipeline-contract+json\\n" + json.dumps(spec) + "\\n\`\`\`\\n", "spec")
respond(runs.write_outline_prompt(topic),
  "# Outline\\n\\n\`\`\`education-pipeline-outline+json\\n" + json.dumps(outline) + "\\n\`\`\`\\n", "outline")
respond(runs.write_draft_prompt(topic), guide, "draft")
runs.validate_run(topic, "draft")
respond(runs.write_qa_prompt(topic), "# QA\\n\\nNo major issues.\\n", "qa")
respond(runs.write_factcheck_prompt(topic),
  "# Fact-Check Report\\n\\n## Verdict\\npass — no material factual errors.\\n\\n## Findings\\n(none)\\n", "factcheck")
respond(runs.write_repair_prompt(topic), guide, "repair")
if validate:
    runs.validate_run(topic, "final")
`;

// Approves a revised repair out of process: the section the reviewer is on
// gets a new title, so the rendered guide HTML changes while every section
// id stays the same.
const REVISE_REPAIR = `
import json, sys
from pathlib import Path
from education_pipeline import RunStore
ws, topic = Path(sys.argv[1]), sys.argv[2]
path = ws / "runs" / topic / "responses" / "repair.response.json"
guide = json.loads(path.read_text(encoding="utf-8"))
section = guide["modules"][1]["sections"][0]
assert section["id"] == "delays-and-leverage"
section["title"] += " (revised)"
path.write_text(json.dumps(guide), encoding="utf-8")
RunStore(ws).approve_stage(topic, "repair", overwrite=True)
`;

let handle: DaemonHandle;

function python(script: string, ...args: string[]) {
  execFileSync("python3", ["-c", script, ...args], { cwd: REPO_ROOT, encoding: "utf-8" });
}

test.beforeAll(async () => {
  handle = await bootDaemon("ep-e2e-preview-bridge-");
  python(DRIVE_RUN, handle.ws, KEEP, "");
  python(DRIVE_RUN, handle.ws, RESTORE, "validate");
});

test.afterAll(async () => {
  const daemon = handle?.daemon;
  if (daemon && daemon.exitCode === null && daemon.signalCode === null) {
    const exited = new Promise<void>((resolveExit) => daemon.once("exit", () => resolveExit()));
    daemon.kill();
    await exited;
  }
  if (handle?.ws) rmSync(handle.ws, { recursive: true, force: true });
});

test.beforeEach(async ({ page }) => {
  // Every load of a preview iframe, counted from the cockpit document: a new
  // srcDoc document is a new load, a kept one is not.
  await page.addInitScript(() => {
    const w = window as unknown as { __previewLoads: number };
    w.__previewLoads = 0;
    document.addEventListener(
      "load",
      (event) => {
        const target = event.target;
        if (
          target instanceof HTMLIFrameElement &&
          target.title === "Interactive guide preview"
        ) {
          w.__previewLoads += 1;
        }
      },
      true,
    );
  });
});

const previewLoads = (page: Page) =>
  page.evaluate(() => (window as unknown as { __previewLoads: number }).__previewLoads);

/** Marks the preview's current document, so a reload is visible as its loss. */
async function markPreviewDocument(page: Page) {
  const element = await page.locator(PREVIEW_IFRAME).elementHandle();
  const frame = await element?.contentFrame();
  if (!frame) throw new Error("the guide preview iframe has no frame");
  await frame.evaluate(() => {
    document.documentElement.dataset.bridgeMarker = "kept";
  });
}

/** Opens the board and moves the preview two sections on, inside the frame. */
async function openBoardOnLaterSection(page: Page, topic: string) {
  await page.goto(`${handle.baseURL}/topics/${topic}`);
  const preview = page.frameLocator(PREVIEW_IFRAME);
  await expect(preview.locator("#feedback-foundations")).toHaveClass(/is-current/);
  await preview.locator('#feedback-foundations [data-role="next-section"]').click();
  await expect(preview.locator("#recognize-loop-types")).toHaveClass(/is-current/);
  await preview.locator('#recognize-loop-types [data-role="next-section"]').click();
  await expect(preview.locator("#delays-and-leverage")).toHaveClass(/is-current/);
  await markPreviewDocument(page);
  expect(await previewLoads(page)).toBe(1);
  return preview;
}

function repairRefetch(page: Page, topic: string) {
  return page.waitForResponse(
    (response) => new URL(response.url()).pathname === `/v1/runs/${topic}/stages/repair`,
  );
}

test("a board mutation that leaves the guide HTML unchanged keeps the preview document and its section", async ({
  page,
}) => {
  const preview = await openBoardOnLaterSection(page, KEEP);

  // Final validation, then Finalize: two board mutations, neither of which
  // changes the approved repair the preview renders.
  for (const [button, next] of [
    ["Run final validation", "Finalize"],
    ["Finalize", "Export"],
  ] as const) {
    const refetched = repairRefetch(page, KEEP);
    await page.getByRole("button", { name: button, exact: true }).click();
    await refetched;
    await expect(page.getByRole("button", { name: next, exact: true })).toBeVisible();
    // Long enough for a remount's fetch, render and srcDoc load to land.
    await page.waitForTimeout(1_000);

    expect(await previewLoads(page), `${button} reloaded the preview`).toBe(1);
    await expect(preview.locator("html")).toHaveAttribute("data-bridge-marker", "kept");
    await expect(preview.locator("#delays-and-leverage")).toHaveClass(/is-current/);
    await expect(preview.locator("#feedback-foundations")).not.toHaveClass(/is-current/);
  }
});

test("when the guide HTML changes, the reloaded preview returns to the reviewer's section", async ({
  page,
}) => {
  const preview = await openBoardOnLaterSection(page, RESTORE);
  await expect(page.getByRole("button", { name: "Finalize", exact: true })).toBeVisible();

  // A revised repair is approved out of process; the board learns of it (the
  // events stream, or its poll) and asks for final validation.
  python(REVISE_REPAIR, handle.ws, RESTORE);
  const runFinal = page.getByRole("button", { name: "Run final validation", exact: true });
  await expect(runFinal).toBeVisible({ timeout: 15_000 });

  // The reviewer's mutation refetches the preview, which now renders the
  // revised guide: a new document, restored to where the reviewer was.
  await runFinal.click();
  await expect.poll(() => previewLoads(page)).toBe(2);
  await expect(preview.locator("html")).not.toHaveAttribute("data-bridge-marker", "kept");
  await expect(preview.locator("#delays-and-leverage h2")).toContainText("(revised)");
  await expect(preview.locator("#delays-and-leverage")).toHaveClass(/is-current/);
  await expect(preview.locator("#feedback-foundations")).not.toHaveClass(/is-current/);
});
