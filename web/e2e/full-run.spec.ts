import { expect, test } from "@playwright/test";
import { spawn, type ChildProcess } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

let daemon: ChildProcess;
let baseURL: string;

test.beforeAll(async () => {
  const ws = mkdtempSync(join(tmpdir(), "ep-e2e-write-"));
  mkdirSync(join(ws, "topics"), { recursive: true });

  daemon = spawn("python3", ["-m", "education_pipeline.daemon", ws], {
    cwd: resolve(import.meta.dirname, "../.."),
    env: { ...process.env, EP_WEB_DIST: resolve(import.meta.dirname, "../dist") },
    stdio: "inherit",
  });

  const discovery = join(ws, ".education-pipeline", "daemon.json");
  for (let i = 0; i < 100 && !existsSync(discovery); i++) {
    await new Promise((r) => setTimeout(r, 100));
  }
  if (!existsSync(discovery)) throw new Error("daemon never wrote its discovery file");
  const record = JSON.parse(readFileSync(discovery, "utf-8")) as { port: number };
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
  await page.getByRole("link", { name: "w", exact: true }).click();

  for (const stage of ["spec", "outline", "draft", "qa", "repair"]) {
    await page.getByRole("button", { name: "Advance" }).click();
    await page.getByRole("button", { name: "Paste response…" }).click();
    await page.getByLabel(`Response for ${stage}`).fill(`${stage} response body`);
    await page.getByRole("button", { name: "Save response" }).click();
    await page.getByRole("button", { name: `Approve ${stage}` }).click();
  }

  await page.getByRole("button", { name: "Finalize" }).click();
  await page.getByRole("button", { name: "Export", exact: true }).click();
  await expect(page.getByText("Exported html.")).toBeVisible();

  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download final guide" }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe("w-guide.md");
});
