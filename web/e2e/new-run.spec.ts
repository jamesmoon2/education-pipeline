import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { spawn, type ChildProcess } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

let daemon: ChildProcess;
let baseURL: string;

test.beforeAll(async () => {
  // An empty workspace: no topic files, no runs. The daemon falls back to
  // the packaged example catalog/plan, so RunPlanPanel still has data to
  // render for a freshly created topic.
  const ws = mkdtempSync(join(tmpdir(), "ep-e2e-new-run-"));
  mkdirSync(join(ws, "topics"), { recursive: true });

  daemon = spawn("python3", ["-m", "education_pipeline.daemon", ws], {
    cwd: resolve(import.meta.dirname, "../.."),
    env: { ...process.env, EP_WEB_DIST: resolve(import.meta.dirname, "../dist") },
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

test("new-run wizard: learner, topic, plan review, confirm, land on the run board", async ({
  page,
}) => {
  await page.goto(`${baseURL}/`);
  await expect(page.getByText(/No topics yet/)).toBeVisible();

  // First-run welcome panel: three facts + provider detection + primary CTA.
  const welcome = page.getByRole("region", { name: /welcome/i });
  await expect(welcome).toBeVisible();
  await expect(welcome.getByText(/stored locally/i)).toBeVisible();
  await expect(welcome.getByText(/Manual copy\/paste — always available/i)).toBeVisible();

  await page.getByRole("link", { name: "Create your first course →" }).first().click();
  await expect(page).toHaveURL(`${baseURL}/new`);

  // Step 1: learner — the empty workspace offers a link out to Profiles.
  await expect(page.getByText(/No profiles yet/)).toBeVisible();
  await page.getByRole("button", { name: "Continue" }).click();

  // Step 2: topic + brief.
  await page.getByLabel("Topic id").fill("wizard-topic");
  await page.getByLabel("Title").fill("Wizard Topic");
  await page.getByRole("button", { name: "Continue" }).click();

  // Step 3: read-only model-plan review with a Settings link.
  await expect(page.getByRole("heading", { name: "Model plan" })).toBeVisible();
  await expect(page.getByRole("link", { name: /Adjust in Settings/i })).toBeVisible();
  await page.getByRole("button", { name: "Continue" }).click();

  // Step 4: confirm preview (learner/topic pairing + estimated stages).
  await expect(page.getByRole("heading", { name: "Confirm" })).toBeVisible();
  await expect(page.getByText("No profile (generic course)")).toBeVisible();
  await expect(page.getByText(/wizard-topic — Wizard Topic/)).toBeVisible();
  await expect(page.getByText(/spec → outline → draft/)).toBeVisible();
  await page.getByRole("button", { name: "Create course" }).click();

  // Creation lands on the run board with the next action highlighted.
  await expect(page).toHaveURL(`${baseURL}/topics/wizard-topic`);
  await expect(page.getByRole("heading", { name: "wizard-topic" })).toBeVisible();
});

test("has no serious or critical automated accessibility violations on /new", async ({ page }) => {
  await page.goto(`${baseURL}/new`);
  const results = await new AxeBuilder({ page }).analyze();
  const serious = results.violations.filter(
    (v) => v.impact === "serious" || v.impact === "critical",
  );
  expect(serious, JSON.stringify(serious, null, 2)).toEqual([]);
});
