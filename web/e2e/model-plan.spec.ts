import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { execFileSync, spawn, type ChildProcess } from "node:child_process";
import {
  chmodSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { delimiter, join, resolve } from "node:path";

// This spec exercises a mixed-provider run configured entirely through the
// cockpit UI: two "executable" stub providers (claude-code, codex) plus the
// manual paste flow, driven from the run board's per-run plan editor
// (RunPlanPanel). No TOML is hand-edited as part of the UI-driven flow — the
// catalog/plan TOML written below is fixture setup, equivalent to a real
// deployment shipping its own config/model-catalog.toml.

let daemon: ChildProcess;
let baseURL: string;
let ws: string;

const CLAUDE_STUB = `#!/usr/bin/env python3
import sys
sys.stdin.buffer.read()
sys.stdout.write('{"result": "claude stub response body"}')
`;

const CODEX_STUB = `#!/usr/bin/env python3
import sys
sys.stdin.buffer.read()
sys.stdout.write("codex stub response body")
`;

const MODEL_CATALOG_TOML = `
[[providers]]
id = "claude-code"
label = "Claude Code"
description = "Stub Claude Code provider for e2e tests."

[[providers.models]]
id = "balanced"
label = "Balanced"
description = "Default stub model."
quality = "strong"
default_effort = "medium"

[[providers.models]]
id = "quick"
label = "Quick"
description = "Weak/fast stub model, used to trigger the reasoning-stage warning."
quality = "fast"
default_effort = "low"

[[providers]]
id = "codex"
label = "Codex"
description = "Stub Codex provider for e2e tests."

[[providers.models]]
id = "balanced"
label = "Balanced"
description = "Default stub model."
quality = "strong"
default_effort = "medium"

[[providers]]
id = "manual"
label = "Manual prompt workflow"
description = "Copy prompts into any model UI, then paste or import responses."

[[providers.models]]
id = "prompt-only"
label = "Prompt-only handoff"
description = "No automated execution."
quality = "manual"

[[presets]]
id = "balanced"
label = "Balanced"
description = "Fixture preset."

[presets.stages.claude-code]
profile = { model = "balanced" }
spec = { model = "balanced", effort = "high" }
outline = { model = "balanced" }
draft = { model = "balanced" }
qa = { model = "quick", effort = "low" }
repair = { model = "balanced" }
audit = { model = "balanced" }

[presets.stages.codex]
profile = { model = "balanced" }
spec = { model = "balanced", effort = "high" }
outline = { model = "balanced" }
draft = { model = "balanced" }
qa = { model = "balanced", effort = "low" }
repair = { model = "balanced" }
audit = { model = "balanced" }
`;

const MODEL_PLAN_TOML = `provider = "claude-code"\n`;

test.beforeAll(async () => {
  ws = mkdtempSync(join(tmpdir(), "ep-e2e-model-plan-"));
  mkdirSync(join(ws, "topics"), { recursive: true });
  mkdirSync(join(ws, "config"), { recursive: true });
  writeFileSync(join(ws, "config", "model-catalog.toml"), MODEL_CATALOG_TOML);
  writeFileSync(join(ws, "config", "model-plan.toml"), MODEL_PLAN_TOML);

  const stubDir = mkdtempSync(join(tmpdir(), "ep-e2e-stub-bin-"));
  const claudePath = join(stubDir, "claude");
  const codexPath = join(stubDir, "codex");
  writeFileSync(claudePath, CLAUDE_STUB);
  writeFileSync(codexPath, CODEX_STUB);
  chmodSync(claudePath, 0o755);
  chmodSync(codexPath, 0o755);

  daemon = spawn("python3", ["-m", "education_pipeline.daemon", ws], {
    cwd: resolve(import.meta.dirname, "../.."),
    env: {
      ...process.env,
      EP_WEB_DIST: resolve(import.meta.dirname, "../dist"),
      PATH: `${stubDir}${delimiter}${process.env.PATH ?? ""}`,
    },
    stdio: "inherit",
  });

  const discovery = join(ws, ".education-pipeline", "daemon.json");
  let record: { port?: number } | undefined;
  for (let i = 0; i < 100 && !record?.port; i++) {
    await new Promise((r) => setTimeout(r, 100));
    if (!existsSync(discovery)) continue;
    try {
      record = JSON.parse(readFileSync(discovery, "utf-8")) as { port?: number };
    } catch {
      // partially written record; keep polling
    }
  }
  if (!record?.port) throw new Error("daemon never wrote a ready discovery record");
  baseURL = `http://127.0.0.1:${record.port}`;
});

test.afterAll(() => {
  daemon?.kill();
});

test("mixed-provider run configured entirely in the cockpit", async ({ page }) => {
  // Step 1: Settings shows both stub providers as available.
  await page.goto(`${baseURL}/settings`);
  await expect(page.getByText(/Claude Code \(claude-code\): available/)).toBeVisible();
  await expect(page.getByText(/Codex \(codex\): available/)).toBeVisible();

  // Set up a topic and start its run (first Advance writes the spec prompt
  // and is the only way to bring RunPlanPanel — the per-run plan editor —
  // onto the page).
  await page.goto(`${baseURL}/`);
  await page.getByRole("button", { name: "Import topic…" }).click();
  await page
    .getByLabel("topic TOML")
    .fill('schema_version = 1\nid = "mp"\ntitle = "Mixed Provider Topic"\n');
  await page.getByRole("button", { name: "Import", exact: true }).click();
  execFileSync(
    "python3",
    ["-m", "education_pipeline", "-C", ws, "create", "mp", "--legacy-markdown"],
    { cwd: resolve(import.meta.dirname, "../..") },
  );
  await page.getByRole("link", { name: "mp", exact: true }).click();
  await page.getByRole("button", { name: "Advance" }).click();
  await expect(page.getByText("Model plan for this run")).toBeVisible();

  const outlineRow = page.locator('[data-stage="outline"]');
  const draftRow = page.locator('[data-stage="draft"]');
  const qaRow = page.locator('[data-stage="qa"]');

  // Step 2: set a weak (quality "fast") model on outline → the warning renders.
  await outlineRow.getByLabel("Model for outline").selectOption({ label: "Quick — fast" });
  await expect(outlineRow.getByRole("alert")).toContainText(/reasoning-heavy/);
  await expect(outlineRow.getByRole("alert")).toContainText(/fast/);

  // Step 3: configure recommended defaults + one per-stage override
  // (draft → the second provider) + qa set to manual — all without ever
  // editing TOML through the UI-driven path.
  await outlineRow.getByRole("button", { name: "Reset to default" }).click();
  await expect(outlineRow.getByRole("alert")).not.toBeVisible();

  // Role-based locators for the provider selects: the row's InfoTip trigger
  // ("About provider for draft") would also substring-match getByLabel.
  await draftRow
    .getByRole("combobox", { name: "Provider for draft" })
    .selectOption({ label: "Codex" });
  // Catalog defines its own "manual" provider (label "Manual prompt
  // workflow") -- select by value, since the row no longer renders a
  // duplicate generic-labeled "manual" option alongside it.
  await qaRow.getByRole("combobox", { name: "Provider for qa" }).selectOption({ value: "manual" });

  // Step 4: drive the run — provider stages via the run button, manual stage
  // via the existing response paste flow.
  // spec's prompt was already written by the initial Advance above.
  for (const stage of ["spec", "outline", "draft"]) {
    if (stage !== "spec") {
      await page.getByRole("button", { name: "Advance" }).click();
    }
    await page.getByRole("button", { name: "Run with provider" }).click();
    await expect(page.getByRole("button", { name: `Approve ${stage}` })).toBeVisible({
      timeout: 20_000,
    });
    await page.getByRole("button", { name: `Approve ${stage}` }).click();
  }

  await page.getByRole("button", { name: "Advance" }).click();
  await page.getByRole("button", { name: "Paste response…" }).click();
  await page.getByLabel("Response for qa").fill("qa response body");
  await page.getByRole("button", { name: "Save response" }).click();
  await page.getByRole("button", { name: "Approve qa" }).click();

  // Step 5: each completed stage shows the expected provenance line,
  // including "(override)" on draft and "manual" on qa.
  const stageRow = (stage: string) =>
    page.getByRole("listitem", { name: `${stage} stage` });
  await expect(stageRow("spec").locator(".stage-provenance")).toHaveText(
    "ran on claude-code (default)",
  );
  await expect(stageRow("outline").locator(".stage-provenance")).toHaveText(
    "ran on claude-code (default)",
  );
  await expect(stageRow("draft").locator(".stage-provenance")).toHaveText(
    "ran on codex (override)",
  );
  await expect(stageRow("qa").locator(".stage-provenance")).toHaveText("ran on manual (manual)");
});

test("preset fills every stage row, saves, and survives reload", async ({ page }) => {
  await page.goto(`${baseURL}/settings`);
  await page.getByRole("button", { name: /Balanced/ }).click();
  const specRow = page.locator('[data-stage="spec"]');
  await expect(specRow.getByLabel("Model for spec")).toHaveValue("balanced");
  // Role-based locator: the row's InfoTip trigger ("About effort for spec")
  // would also substring-match getByLabel("Effort for spec").
  await expect(specRow.getByRole("combobox", { name: "Effort for spec" })).toHaveValue("high");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await page.reload();
  await expect(
    page.locator('[data-stage="qa"]').getByLabel("Model for qa"),
  ).toHaveValue("quick");
});

test("settings page with a tooltip open passes axe", async ({ page }) => {
  await page.goto(`${baseURL}/settings`);
  await page.getByRole("button", { name: "About spec stage" }).click();
  await expect(page.getByRole("tooltip")).toBeVisible();
  const results = await new AxeBuilder({ page }).analyze();
  // Same gate as the suite's other axe checks: serious/critical must be clean.
  const serious = results.violations.filter(
    (v) => v.impact === "serious" || v.impact === "critical",
  );
  expect(serious).toEqual([]);
});
