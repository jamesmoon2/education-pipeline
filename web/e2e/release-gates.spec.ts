import { expect, test, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { existsSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { bootDaemon, type DaemonHandle } from "./helpers/daemon";

// Acceptance e2e for the deterministic release gates: one spec driving the
// full finding -> repair -> re-run -> waive -> export loop through the cockpit.
//
// The guide fixture is deliberately seeded with two blocking, waivable
// findings, both attributed to the DRAFT stage:
//   1. content.placeholder ("TODO" in a rich-text block) -- the blocker we
//      CLEAR by editing the draft content and re-running validation.
//   2. markdown.invalid_heading_level (a level-1 heading in a callout) -- the
//      finding that REMAINS after the repair; we WAIVE it to open the gate.
//
// The draft-phase report is where the badge/link/repair/re-run narrative
// plays out. The final-phase report (over the repair-stage content, byte
// identical to the repaired draft) carries the same heading finding, and its
// waiver gate is what actually blocks finalize/export -- so the waive that
// opens the export gate is load-bearing (see the sabotage evidence in the
// task report).

let handle: DaemonHandle;
let baseURL: string;
let ws: string;

const TOPIC = "rg";
const PLACEHOLDER_PATH = "/modules/0/sections/0/blocks/0/markdown";

// Reused verbatim from full-run.spec's passing guide-v1 baseline: a spec and
// outline that let the run advance through its stages. Draft validation is
// guide-internal, so these do not introduce findings of their own.
const SPEC = `# Course Specification\n\n\`\`\`education-pipeline-contract+json\n${JSON.stringify({
  contract_version: 1,
  guide_schema_version: "1.0",
  blueprint: "conceptual-foundations",
  estimated_minutes: 30,
  outcomes: [{ id: "identify-loop", text: "Identify reinforcing and balancing feedback." }],
  required_interactions: ["knowledge_check", "worked_reveal", "scenario", "reflection"],
  personalization_requirements: ["Use gardening examples where useful."],
  source_policy: "Sources required for factual claims that are not common knowledge.",
})}\n\`\`\``;
const OUTLINE = `# Course Outline\n\n\`\`\`education-pipeline-outline+json\n${JSON.stringify({
  contract_version: 1,
  modules: { "feedback-loops": { outcome_ids: ["identify-loop"], estimated_minutes: 30, interaction_types: ["knowledge_check", "worked_reveal"] } },
})}\n\`\`\``;

function guideFixtures() {
  const base = JSON.parse(
    readFileSync(
      resolve(import.meta.dirname, "../../tests/fixtures/guides/feedback-loops.guide.json"),
      "utf-8",
    ),
  );
  // Repaired guide: keep the level-1 heading (the waivable finding that
  // remains), leave everything else pristine.
  const repaired = JSON.parse(JSON.stringify(base));
  const rBlocks = repaired.modules[0].sections[0].blocks;
  rBlocks[1].markdown = `# Overview\n\n${rBlocks[1].markdown}`;

  // Placeholder draft: the repaired guide plus a TODO placeholder blocker.
  const withPlaceholder = JSON.parse(JSON.stringify(repaired));
  const pBlocks = withPlaceholder.modules[0].sections[0].blocks;
  pBlocks[0].markdown = `${pBlocks[0].markdown} TODO: finish writing this explanation.`;

  return {
    withPlaceholder: JSON.stringify(withPlaceholder),
    repaired: JSON.stringify(repaired),
  };
}

const { withPlaceholder: DRAFT_V1, repaired: DRAFT_V2 } = guideFixtures();

// A stage's node in the run-board pipeline stepper (as opposed to the
// validation-milestones table, which also has "draft"/"final" rows).
function stageStep(page: Page, stage: string) {
  return page.getByRole("listitem", { name: `${stage} stage` });
}

function draftPanel(page: Page) {
  return page.locator('section[aria-label="draft validation findings"]');
}
function finalPanel(page: Page) {
  return page.locator('section[aria-label="final validation findings"]');
}

async function pasteAndApprove(page: Page, stage: string, response: string) {
  await page.getByRole("button", { name: "Advance" }).click();
  await page.getByRole("button", { name: "Paste response…" }).click();
  await page.getByLabel(`Response for ${stage}`).fill(response);
  await page.getByRole("button", { name: "Save response" }).click();
  await page.getByRole("button", { name: `Approve ${stage}` }).click();
}

test.beforeAll(async () => {
  handle = await bootDaemon("ep-e2e-release-gates-");
  baseURL = handle.baseURL;
  ws = handle.ws;
});

test.afterAll(() => {
  handle?.daemon?.kill();
});

test("release gate: finding → repair → re-run → waive → export", async ({ page }) => {
  test.setTimeout(120_000);
  // Re-approving an already-approved stage prompts an overwrite confirm.
  page.on("dialog", (dialog) => dialog.accept());

  // Seed a guide-v1 run and drive it to an approved draft carrying a
  // placeholder blocker.
  await page.goto(`${baseURL}/`);
  await page.getByRole("button", { name: "Import topic…" }).click();
  await page
    .getByLabel("topic TOML")
    .fill(`schema_version = 1\nid = "${TOPIC}"\ntitle = "Release Gates"\n`);
  await page.getByRole("button", { name: "Import", exact: true }).click();
  await page.getByRole("link", { name: TOPIC, exact: true }).click();

  await pasteAndApprove(page, "spec", SPEC);
  await pasteAndApprove(page, "outline", OUTLINE);
  await pasteAndApprove(page, "draft", DRAFT_V1);

  // Run draft validation -> the draft stage badges up with both findings.
  await page.getByRole("button", { name: "Run draft validation" }).click();

  const draftRow = stageStep(page, "draft");
  // The badge is no longer a role="status" live region (that would
  // re-announce on every 5s poll) -- it carries its accessible name via
  // aria-label instead.
  await expect(draftRow.locator(".findings-badge")).toHaveText("2");
  await expect(draftRow.locator(".findings-badge")).toHaveAttribute("aria-label", "2 findings");
  // Badge is on the draft stage specifically, not any other stage.
  await expect(
    stageStep(page, "outline").locator(".findings-badge"),
  ).toHaveCount(0);

  // The blocker is listed in the draft findings panel and its source link
  // points at the draft stage.
  const placeholderLink = draftPanel(page).getByRole("link", {
    name: `Open source at ${PLACEHOLDER_PATH}`,
  });
  await expect(draftPanel(page).getByText(/content\.placeholder/)).toBeVisible();
  await expect(placeholderLink).toHaveAttribute(
    "href",
    new RegExp(`/topics/${TOPIC}/stages/draft\\b`),
  );

  // Accessibility gate over the findings panel + badge states.
  const axe = await new AxeBuilder({ page }).analyze();
  const serious = axe.violations.filter(
    (v) => v.impact === "serious" || v.impact === "critical",
  );
  expect(serious, JSON.stringify(serious, null, 2)).toEqual([]);

  // Repair the content in the editor: replace the draft response with the
  // placeholder-free guide, then re-approve.
  await draftRow.getByRole("link", { name: "draft" }).click();
  await page.getByRole("tab", { name: /^response/ }).click();
  // Accessibility gate over the JSON-tree stage view before editing.
  await expect(page.locator(".json-tree")).toBeVisible();
  const axeViewer = await new AxeBuilder({ page }).analyze();
  const seriousViewer = axeViewer.violations.filter(
    (v) => v.impact === "serious" || v.impact === "critical",
  );
  expect(seriousViewer, JSON.stringify(seriousViewer, null, 2)).toEqual([]);
  await page.getByRole("button", { name: "Edit" }).click();
  await page.getByLabel("Edit response for draft").fill(DRAFT_V2);
  await page.getByRole("button", { name: "Save" }).click();
  await page.getByRole("button", { name: "Approve draft" }).click();
  await page.getByRole("link", { name: new RegExp(`back to ${TOPIC}`) }).click();

  // Re-run validation from the panel: the placeholder blocker clears, and the
  // waivable heading finding remains (badge drops 2 -> 1).
  await draftPanel(page).getByRole("button", { name: "Re-run validation" }).click();
  const draftRowAfter = stageStep(page, "draft");
  await expect(draftRowAfter.locator(".findings-badge")).toHaveText("1");
  await expect(draftPanel(page).getByText(/content\.placeholder/)).toHaveCount(0);
  await expect(draftPanel(page).getByText(/markdown\.invalid_heading_level/)).toBeVisible();

  // Continue the pipeline. Repair-stage content is the repaired guide, so the
  // final-phase report carries the same waivable heading blocker.
  await pasteAndApprove(page, "qa", "# QA\n\nNo blocking issues.");
  await pasteAndApprove(page, "repair", DRAFT_V2);
  await page.getByRole("button", { name: "Run final validation" }).click();

  // The final gate is closed on the un-waived blocker: finalize is not offered.
  await expect(
    finalPanel(page).getByText(/markdown\.invalid_heading_level/),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "Finalize", exact: true })).toHaveCount(0);

  // Waive the remaining finding with a reason through the final panel; this is
  // what opens the export gate.
  await finalPanel(page).getByRole("button", { name: "Waive…" }).click();
  const dialog = finalPanel(page).getByRole("dialog");
  await dialog
    .getByLabel("Reason")
    .fill("Intentional level-1 heading in the intro callout; accepted for this release.");
  await dialog.getByRole("button", { name: "Confirm waiver" }).click();

  // Gate open -> finalize -> export.
  await page.getByRole("button", { name: "Finalize", exact: true }).click();
  await page.getByRole("button", { name: "Export", exact: true }).click();
  await expect(page.getByText("Exported html.")).toBeVisible();

  // The exported HTML and its sidecar report land in the workspace, and the
  // gate the sidecar records is open.
  const htmlPath = join(ws, "runs", TOPIC, "final", "guide.html");
  const reportPath = join(ws, "runs", TOPIC, "final", "guide.report.json");
  await expect.poll(() => existsSync(htmlPath)).toBe(true);
  await expect.poll(() => existsSync(reportPath)).toBe(true);
  const sidecar = JSON.parse(readFileSync(reportPath, "utf-8"));
  expect(sidecar.gate.open).toBe(true);
  expect(sidecar.gate.effective_blocking).toBe(0);
});

test("release gate: a waiver can be removed from the cockpit", async ({ page }) => {
  test.setTimeout(120_000);
  page.on("dialog", (dialog) => dialog.accept());

  // Same topic/spec/outline scaffolding as the primary test, but seeded
  // directly with the repaired (placeholder-free) draft: this test only
  // needs the waivable heading finding to reach an open final gate with one
  // recorded waiver, so the placeholder-blocker/repair narrative is skipped.
  const topic = "rg2";
  await page.goto(`${baseURL}/`);
  await page.getByRole("button", { name: "Import topic…" }).click();
  await page
    .getByLabel("topic TOML")
    .fill(`schema_version = 1\nid = "${topic}"\ntitle = "Release Gates 2"\n`);
  await page.getByRole("button", { name: "Import", exact: true }).click();
  await page.getByRole("link", { name: topic, exact: true }).click();

  await pasteAndApprove(page, "spec", SPEC);
  await pasteAndApprove(page, "outline", OUTLINE);
  await pasteAndApprove(page, "draft", DRAFT_V2);
  // A current draft-phase report is required before the run advances to qa.
  await page.getByRole("button", { name: "Run draft validation" }).click();
  await expect(
    draftPanel(page).getByText(/markdown\.invalid_heading_level/),
  ).toBeVisible();
  await pasteAndApprove(page, "qa", "# QA\n\nNo blocking issues.");
  await pasteAndApprove(page, "repair", DRAFT_V2);
  await page.getByRole("button", { name: "Run final validation" }).click();

  // Waive the remaining finding to reach an open export gate.
  await finalPanel(page).getByRole("button", { name: "Waive…" }).click();
  const dialog = finalPanel(page).getByRole("dialog");
  await dialog
    .getByLabel("Reason")
    .fill("Intentional level-1 heading in the intro callout; accepted for this release.");
  await dialog.getByRole("button", { name: "Confirm waiver" }).click();
  await expect(page.getByRole("button", { name: "Finalize", exact: true })).toBeVisible();

  // Remove the waiver from the cockpit: the gate re-closes.
  await finalPanel(page).getByRole("button", { name: /unwaive/i }).click();
  // Anchored: the "About Waive" InfoTip trigger beside the control would
  // otherwise also match a bare /waive/i.
  await expect(finalPanel(page).getByRole("button", { name: /^waive/i })).toBeVisible();
  await expect(page.getByRole("button", { name: "Finalize", exact: true })).toHaveCount(0);
  await expect(finalPanel(page).getByText(/1 blocking .* 0 waived/)).toBeVisible();
});
