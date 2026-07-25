import { expect, test, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { bootDaemon, type DaemonHandle } from "./helpers/daemon";

// Acceptance e2e for blueprint-driven pedagogy: the recommendation flows
// into visibly different stage prompts, an override changes them again, one
// weak module regenerates in place without touching its siblings, and a
// time-budget overrun warns at the responsible stage.

let handle: DaemonHandle;
let baseURL: string;
let ws: string;

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

const FIXTURE = JSON.parse(
  readFileSync(
    resolve(import.meta.dirname, "../../tests/fixtures/guides/feedback-loops.guide.json"),
    "utf-8",
  ),
);
const DRAFT = JSON.stringify(FIXTURE);

function revisedModuleFragment(): string {
  const module = JSON.parse(JSON.stringify(FIXTURE.modules[0]));
  module.title = "How loops behave, regenerated";
  return JSON.stringify(module);
}

async function importTopic(page: Page, toml: string, id: string) {
  await page.goto(`${baseURL}/`);
  await page.getByRole("button", { name: "Import topic…" }).click();
  await page.getByLabel("topic TOML").fill(toml);
  await page.getByRole("button", { name: "Import", exact: true }).click();
  await page.getByRole("link", { name: id, exact: true }).click();
}

async function pasteAndApprove(page: Page, stage: string, response: string) {
  await page.getByRole("button", { name: "Advance" }).click();
  await page.getByRole("button", { name: "Paste response…" }).click();
  await page.getByLabel(`Response for ${stage}`).fill(response);
  await page.getByRole("button", { name: "Save response" }).click();
  await page.getByRole("button", { name: `Approve ${stage}` }).click();
}

function stageStep(page: Page, stage: string) {
  return page.getByRole("listitem", { name: `${stage} stage` });
}

test.beforeAll(async () => {
  handle = await bootDaemon("ep-e2e-blueprints-");
  baseURL = handle.baseURL;
  ws = handle.ws;
});

test.afterAll(() => {
  handle?.daemon?.kill();
});

async function walkWizardToBlueprint(page: Page, id: string, title: string) {
  await page.goto(`${baseURL}/new`);
  // Learner step (empty workspace) -> topic step.
  await page.getByRole("button", { name: "Continue" }).click();
  // exact: the "About Topic id" InfoTip trigger would otherwise also match
  // Playwright's substring-based getByLabel.
  await page.getByLabel("Topic id", { exact: true }).fill(id);
  await page.getByLabel("Title").fill(title);
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByRole("heading", { name: "Choose a blueprint" })).toBeVisible();
}

async function finishWizard(page: Page) {
  await page.getByRole("button", { name: "Continue" }).click(); // blueprint -> plan
  await page.getByRole("button", { name: "Continue" }).click(); // plan -> confirm
  await page.getByRole("button", { name: "Create course" }).click();
}

test("accepting the recommendation puts the blueprint contract in the spec prompt", async ({
  page,
}) => {
  await walkWizardToBlueprint(page, "bp-accept", "Feedback Systems");
  await expect(
    page.getByRole("radio", { name: /Conceptual foundations/ }),
  ).toBeChecked();
  await expect(page.getByText(/general conceptual topic/)).toBeVisible();
  await finishWizard(page);

  // The run header records the recommendation, and the spec prompt carries
  // the blueprint contract.
  await expect(page).toHaveURL(`${baseURL}/topics/bp-accept`);
  await expect(page.getByText(/Blueprint:/)).toBeVisible();
  await expect(page.getByText("conceptual-foundations")).toBeVisible();
  await page.goto(`${baseURL}/topics/bp-accept/stages/spec`);
  // Raw mode shows the exact prompt bytes (rendered prose is the default).
  await page.getByRole("button", { name: "Raw" }).click();
  await expect(page.locator("pre.content")).toContainText("## Blueprint Contract");
  await expect(page.locator("pre.content")).toContainText("Conceptual foundations");
});

test("overriding to a second blueprint produces a visibly different prompt", async ({
  page,
}) => {
  await walkWizardToBlueprint(page, "bp-override", "Feedback Systems Again");
  await page.getByRole("radio", { name: /Exam preparation/ }).click();
  await finishWizard(page);

  await expect(page).toHaveURL(`${baseURL}/topics/bp-override`);
  await expect(page.getByText("exam-preparation")).toBeVisible();
  await expect(page.getByText(/\(user\)/)).toBeVisible();
  await page.goto(`${baseURL}/topics/bp-override/stages/spec`);
  await page.getByRole("button", { name: "Raw" }).click();
  await expect(page.locator("pre.content")).toContainText("## Blueprint Contract");
  await expect(page.locator("pre.content")).toContainText("Exam preparation");
  await expect(page.locator("pre.content")).toContainText(
    "Practice items must match the assessment format",
  );
});

test("one weak module regenerates in place without touching its siblings", async ({
  page,
}) => {
  test.setTimeout(120_000);
  page.on("dialog", (dialog) => dialog.accept());

  await importTopic(
    page,
    'schema_version = 1\nid = "bp-splice"\ntitle = "Splice Topic"\n',
    "bp-splice",
  );
  await pasteAndApprove(page, "spec", SPEC);
  await pasteAndApprove(page, "outline", OUTLINE);
  await pasteAndApprove(page, "draft", DRAFT);
  await page.getByRole("button", { name: "Run draft validation" }).click();
  await pasteAndApprove(page, "qa", "# QA\n\n## Findings\n1. minor - loop-basics: tighten the opener.");
  await pasteAndApprove(
    page,
    "factcheck",
    "# Fact-Check Report\n\n## Verdict\npass — no material factual errors.\n\n## Findings\n(none)\n",
  );

  // Prepare a scoped repair for one module from the repair stage view.
  await stageStep(page, "repair").getByRole("link", { name: "repair" }).click();
  await expect(
    page.getByRole("heading", { name: "Regenerate one module" }),
  ).toBeVisible();
  await page
    .locator(".module-repair")
    .getByRole("combobox")
    .selectOption("loop-basics");
  await page.getByRole("button", { name: "Regenerate this module" }).click();
  await expect(
    page.getByText(/Scoped repair prompt prepared for loop-basics/),
  ).toBeVisible();
  await expect(
    page.getByText(/The pending repair is scoped to module/),
  ).toBeVisible();

  // The scoped response is one module object; approval splices it.
  await page.getByRole("button", { name: "Paste response…" }).click();
  await page.getByLabel("Response for repair").fill(revisedModuleFragment());
  await page.getByRole("button", { name: "Save response" }).click();
  await page.getByRole("button", { name: "Approve repair" }).click();
  await expect(page.getByRole("tab", { name: /approved/ })).toBeVisible();

  // The approved repair is the merged whole guide: the target changed, the
  // sibling module is untouched, and the run proceeds through the final gate.
  const approvedPath = join(ws, "runs", "bp-splice", "approved", "repair.json");
  await expect
    .poll(() => {
      try {
        return JSON.parse(readFileSync(approvedPath, "utf-8")).modules[0].title;
      } catch {
        return null;
      }
    })
    .toBe("How loops behave, regenerated");
  const merged = JSON.parse(readFileSync(approvedPath, "utf-8"));
  expect(merged.modules).toHaveLength(FIXTURE.modules.length);
  // The merged guide is canonical JSON, which materializes default empty
  // outcome_ids/source_ids arrays the hand-written fixture omits; content is
  // otherwise untouched.
  const expectedSibling = JSON.parse(JSON.stringify(FIXTURE.modules[1]));
  for (const section of expectedSibling.sections) {
    for (const block of section.blocks) {
      block.outcome_ids = block.outcome_ids ?? [];
      block.source_ids = block.source_ids ?? [];
    }
  }
  expect(merged.modules[1]).toEqual(expectedSibling);

  await page.goto(`${baseURL}/topics/bp-splice`);
  await page.getByRole("button", { name: "Run final validation" }).click();
  await expect(page.getByRole("button", { name: "Finalize", exact: true })).toBeVisible();
});

test("a blown time budget warns at the responsible stage", async ({ page }) => {
  test.setTimeout(120_000);
  await importTopic(
    page,
    'schema_version = 1\nid = "bp-budget"\ntitle = "Budget Topic"\ntime_budget_minutes = 10\n',
    "bp-budget",
  );
  await pasteAndApprove(page, "spec", SPEC);
  await pasteAndApprove(page, "outline", OUTLINE);
  await pasteAndApprove(page, "draft", DRAFT);
  await page.getByRole("button", { name: "Run draft validation" }).click();

  // The 30-minute course against a 10-minute budget warns, attributed to the
  // outline stage, without blocking.
  const draftPanel = page.locator('section[aria-label="draft validation findings"]');
  await expect(draftPanel.getByText(/time\.budget_exceeded/)).toBeVisible();
  await expect(
    draftPanel.getByText(/exceeds the stated time budget of 10 minutes/),
  ).toBeVisible();
});
