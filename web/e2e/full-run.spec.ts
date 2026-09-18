import { expect, test } from "@playwright/test";
import { execFileSync, spawn, type ChildProcess } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

let daemon: ChildProcess;
let baseURL: string;
let ws: string;

test.beforeAll(async () => {
  ws = mkdtempSync(join(tmpdir(), "ep-e2e-write-"));
  mkdirSync(join(ws, "topics"), { recursive: true });

  daemon = spawn("python3", ["-m", "education_pipeline.daemon", ws], {
    cwd: resolve(import.meta.dirname, "../.."),
    env: { ...process.env, EP_WEB_DIST: resolve(import.meta.dirname, "../dist") },
    stdio: "inherit",
  });

  const discovery = join(ws, ".education-pipeline", "daemon.json");
  let record: { port: number } | null = null;
  for (let i = 0; i < 100 && !record?.port; i++) {
    if (existsSync(discovery)) {
      try { record = JSON.parse(readFileSync(discovery, "utf-8")) as { port: number }; } catch { /* retry partial record */ }
    }
    if (!record?.port) await new Promise((r) => setTimeout(r, 100));
  }
  if (!record?.port) throw new Error("daemon never wrote a ready discovery record");
  baseURL = `http://127.0.0.1:${record.port}`;
});

test.afterAll(() => {
  daemon?.kill();
});

test("full write flow: import → advance/paste/approve ×5 → finalize → export → download", async ({
  page,
}) => {
  await page.goto(`${baseURL}/`);

  await page.getByRole("button", { name: "Import topic…" }).click();
  await page
    .getByLabel("topic TOML")
    .fill('schema_version = 1\nid = "w"\ntitle = "Write Topic"\n');
  await page.getByRole("button", { name: "Import", exact: true }).click();
  execFileSync(
    "python3",
    ["-m", "education_pipeline", "-C", ws, "create", "w", "--legacy-markdown"],
    { cwd: resolve(import.meta.dirname, "../..") },
  );
  await page.getByRole("link", { name: "w", exact: true }).click();

  for (const stage of ["spec", "outline", "draft", "qa", "repair"]) {
    await page.getByRole("button", { name: "Advance" }).click();
    await page.getByRole("button", { name: "Paste response…" }).click();
    await page.getByLabel(`Response for ${stage}`).fill(`${stage} response body`);
    await page.getByRole("button", { name: "Save response" }).click();
    await page.getByRole("button", { name: `Approve ${stage} only`, exact: true }).click();
  }

  await page.getByRole("button", { name: "Finalize", exact: true }).click();
  await page.getByRole("button", { name: "Export", exact: true }).click();
  await expect(page.getByText("Exported html.")).toBeVisible();

  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download final guide" }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe("w-guide.md");
});

test("guide-v1 fixture reaches validation, finalize, export, and mixed-workspace resume", async ({ page }) => {
  const fixture = readFileSync(
    resolve(import.meta.dirname, "../../tests/fixtures/guides/feedback-loops.guide.json"),
    "utf-8",
  );
  const spec = `# Course Specification\n\n\`\`\`education-pipeline-contract+json\n${JSON.stringify({
    contract_version: 1,
    guide_schema_version: "1.0",
    blueprint: "conceptual-foundations",
    estimated_minutes: 30,
    outcomes: [{ id: "identify-loop", text: "Identify reinforcing and balancing feedback." }],
    required_interactions: ["knowledge_check", "worked_reveal", "scenario", "reflection"],
    personalization_requirements: ["Use gardening examples where useful."],
    source_policy: "Sources required for factual claims that are not common knowledge.",
  })}\n\`\`\``;
  const outline = `# Course Outline\n\n\`\`\`education-pipeline-outline+json\n${JSON.stringify({
    contract_version: 1,
    modules: { "feedback-loops": { outcome_ids: ["identify-loop"], estimated_minutes: 30, interaction_types: ["knowledge_check", "worked_reveal"] } },
  })}\n\`\`\``;

  await page.goto(`${baseURL}/`);
  await page.getByRole("button", { name: "Import topic…" }).click();
  await page.getByLabel("topic TOML").fill('schema_version = 1\nid = "g"\ntitle = "Guide Topic"\n');
  await page.getByRole("button", { name: "Import", exact: true }).click();
  await page.getByRole("link", { name: "g", exact: true }).click();

  for (const [stage, response] of [["spec", spec], ["outline", outline], ["draft", fixture]] as const) {
    await page.getByRole("button", { name: "Advance" }).click();
    await page.getByRole("button", { name: "Paste response…" }).click();
    await page.getByLabel(`Response for ${stage}`).fill(response);
    await page.getByRole("button", { name: "Save response" }).click();
    await page.getByRole("button", { name: `Approve ${stage} only`, exact: true }).click();
  }
  await page.getByRole("button", { name: "Run draft validation" }).click();
  await page.getByRole("button", { name: "Advance" }).click();
  await page.getByRole("button", { name: "Paste response…" }).click();
  await page.getByLabel("Response for qa").fill("# QA\n\nNo blocking issues.");
  await page.getByRole("button", { name: "Save response" }).click();
  await page.getByRole("button", { name: "Approve qa only", exact: true }).click();
  await page.getByRole("button", { name: "Advance" }).click();
  await page.getByRole("button", { name: "Paste response…" }).click();
  await page
    .getByLabel("Response for factcheck")
    .fill("# Fact-Check Report\n\n## Verdict\npass — no material factual errors.\n\n## Findings\n(none)\n");
  await page.getByRole("button", { name: "Save response" }).click();
  await page.getByRole("button", { name: "Approve factcheck only", exact: true }).click();
  await page.getByRole("button", { name: "Advance" }).click();
  await page.getByRole("button", { name: "Paste response…" }).click();
  await page.getByLabel("Response for repair").fill(fixture);
  await page.getByRole("button", { name: "Save response" }).click();
  await page.getByRole("button", { name: "Approve repair only", exact: true }).click();
  await page.getByRole("button", { name: "Run final validation" }).click();
  await page.getByRole("button", { name: "Finalize", exact: true }).click();
  await page.getByRole("button", { name: "Export", exact: true }).click();
  await expect(page.getByText("Exported html.")).toBeVisible();

  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download final guide" }).click();
  expect((await downloadPromise).suggestedFilename()).toBe("g-guide.json");
  await page.goto(`${baseURL}/`);
  await expect(page.getByRole("link", { name: "w", exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "g", exact: true })).toBeVisible();

  // Thread T07: the library gets a Cost column (GET /v1/topics' per-row
  // cost.run_usd, thread T06). This whole run went through manual paste
  // responses -- no provider job ever ran -- so neither "w" nor "g" has
  // any known cost, and this asserts the null placeholder rather than a
  // dollar figure. (The daemon test helper here has no fake-provider path
  // that reports a cost; see full-run.spec.ts's beforeAll / model-plan.spec.ts
  // for the one stub-provider spec in this suite, which does not drive a
  // full run to a cost-bearing job either.)
  await expect(page.getByRole("columnheader", { name: "Cost" })).toBeVisible();
  const wRow = page.locator("tr").filter({ has: page.getByRole("link", { name: "w", exact: true }) });
  await expect(wRow.getByText("—", { exact: true })).toBeVisible();
});

test("guide run drafts module by module through the paste loop", async ({ page }) => {
  // Per-module drafting (docs/superpowers/specs/
  // 2026-09-18-per-module-drafting-design.md §8): the draft stage fans out
  // into a skeleton unit plus one unit per module instead of one whole-guide
  // response. This drives spec/outline through the ordinary paste loop, then
  // exercises the unit-level flow at draft only -- skeleton paste, the
  // per-module "Paste response for <title>" loop in DraftProgressPanel, the
  // automatic assembly once every module is saved, and a plain approval.
  const fixture: {
    outcomes: { id: string; text: string }[];
    modules: { id: string; title: string; sections: unknown[] }[];
  } = JSON.parse(
    readFileSync(
      resolve(import.meta.dirname, "../../tests/fixtures/guides/feedback-loops.guide.json"),
      "utf-8",
    ),
  );

  const spec = `# Course Specification\n\n\`\`\`education-pipeline-contract+json\n${JSON.stringify({
    contract_version: 1,
    guide_schema_version: "1.0",
    blueprint: "conceptual-foundations",
    estimated_minutes: 30,
    outcomes: fixture.outcomes,
    required_interactions: ["knowledge_check", "worked_reveal", "scenario", "reflection"],
    personalization_requirements: ["Use gardening examples where useful."],
    source_policy: "Sources required for factual claims that are not common knowledge.",
  })}\n\`\`\``;
  // Module order and per-module fields must match the fixture's own modules
  // (runs.py's draft unit layer reads the authored module order off this
  // approved outline contract, not off the guide contract).
  const outline = `# Course Outline\n\n\`\`\`education-pipeline-outline+json\n${JSON.stringify({
    contract_version: 1,
    modules: {
      "loop-basics": {
        outcome_ids: ["identify-loop", "map-loop"],
        estimated_minutes: 14,
        interaction_types: ["knowledge_check", "worked_reveal"],
      },
      "intervention-practice": {
        outcome_ids: ["map-loop", "choose-intervention"],
        estimated_minutes: 16,
        interaction_types: ["knowledge_check", "scenario", "reflection"],
      },
    },
  })}\n\`\`\``;
  // The skeleton: the same guide with every module reduced to a sectionless
  // stub (check_skeleton's contract) -- derived from the fixture rather than
  // hand-authored, so it always matches the module JSON pasted per row below.
  const skeletonText = JSON.stringify({
    ...fixture,
    modules: fixture.modules.map((module) => ({ ...module, sections: [] })),
  });

  await page.goto(`${baseURL}/`);
  await page.getByRole("button", { name: "Import topic…" }).click();
  await page
    .getByLabel("topic TOML")
    .fill('schema_version = 1\nid = "md"\ntitle = "Module Drafting Topic"\n');
  await page.getByRole("button", { name: "Import", exact: true }).click();
  await page.getByRole("link", { name: "md", exact: true }).click();

  for (const [stage, response] of [["spec", spec], ["outline", outline]] as const) {
    await page.getByRole("button", { name: "Advance" }).click();
    await page.getByRole("button", { name: "Paste response…" }).click();
    await page.getByLabel(`Response for ${stage}`).fill(response);
    await page.getByRole("button", { name: "Save response" }).click();
    await page.getByRole("button", { name: `Approve ${stage} only`, exact: true }).click();
  }

  // draft: Advance writes the skeleton prompt (draft/skeleton/prompt.md).
  await page.getByRole("button", { name: "Advance" }).click();

  // The stage-level "Paste response…" loop always writes straight to the
  // whole-stage response file (the deliberate whole-guide bypass the other
  // guide-v1 test in this file exercises), so the skeleton goes through
  // DraftProgressPanel's own skeleton paste instead, landing in
  // draft/skeleton/response.json via the unit route and keeping per-module
  // drafting intact.
  await page.getByRole("button", { name: "Paste skeleton response" }).click();
  await page.getByLabel("Response for skeleton").fill(skeletonText);
  await page.getByRole("button", { name: "Save" }).click();

  // Ingesting the skeleton response auto-writes the per-module prompts
  // (design decision 9); Advance again only if the daemon left that step
  // pending, so this works whichever route actually landed the skeleton.
  const firstModulePaste = page.getByRole("button", {
    name: `Paste response for ${fixture.modules[0].title}`,
  });
  await page.getByRole("button", { name: "Advance" }).or(firstModulePaste).first().waitFor();
  const advanceButton = page.getByRole("button", { name: "Advance" });
  if (await advanceButton.isVisible()) {
    await advanceButton.click();
  }
  await firstModulePaste.waitFor();

  // One module at a time: DraftProgressPanel's "Save" button is not
  // per-row-qualified, so only one row's paste editor is open at once (it
  // closes itself on a successful save).
  for (const module of fixture.modules) {
    await page.getByRole("button", { name: `Paste response for ${module.title}` }).click();
    await page.getByLabel(`Response for ${module.title}`).fill(JSON.stringify(module));
    await page.getByRole("button", { name: "Save" }).click();
  }

  // The last module's ingest assembles the draft automatically; approve the
  // assembled response without continuing into qa.
  await page.getByRole("button", { name: "Approve draft only", exact: true }).click();
  await expect(page.getByText("Approved draft.")).toBeVisible();

  const approvedDraft = JSON.parse(
    readFileSync(join(ws, "runs", "md", "approved", "draft.json"), "utf-8"),
  ) as { modules: { id: string }[] };
  expect(approvedDraft.modules.map((module) => module.id)).toEqual([
    "loop-basics",
    "intervention-practice",
  ]);
});
