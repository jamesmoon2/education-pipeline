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
    await page.getByRole("button", { name: `Approve ${stage}` }).click();
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
    await page.getByRole("button", { name: `Approve ${stage}` }).click();
  }
  await page.getByRole("button", { name: "Run draft validation" }).click();
  await page.getByRole("button", { name: "Advance" }).click();
  await page.getByRole("button", { name: "Paste response…" }).click();
  await page.getByLabel("Response for qa").fill("# QA\n\nNo blocking issues.");
  await page.getByRole("button", { name: "Save response" }).click();
  await page.getByRole("button", { name: "Approve qa" }).click();
  await page.getByRole("button", { name: "Advance" }).click();
  await page.getByRole("button", { name: "Paste response…" }).click();
  await page
    .getByLabel("Response for factcheck")
    .fill("# Fact-Check Report\n\n## Verdict\npass — no material factual errors.\n\n## Findings\n(none)\n");
  await page.getByRole("button", { name: "Save response" }).click();
  await page.getByRole("button", { name: "Approve factcheck" }).click();
  await page.getByRole("button", { name: "Advance" }).click();
  await page.getByRole("button", { name: "Paste response…" }).click();
  await page.getByLabel("Response for repair").fill(fixture);
  await page.getByRole("button", { name: "Save response" }).click();
  await page.getByRole("button", { name: "Approve repair" }).click();
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
});
