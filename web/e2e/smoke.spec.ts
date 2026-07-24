import { expect, test } from "@playwright/test";
import { spawn, type ChildProcess } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

let daemon: ChildProcess;
let baseURL: string;

test.beforeAll(async () => {
  const ws = mkdtempSync(join(tmpdir(), "ep-e2e-"));
  mkdirSync(join(ws, "topics"), { recursive: true });
  writeFileSync(
    join(ws, "topics", "t.toml"),
    'schema_version = 1\nid = "t"\ntitle = "E2E Topic"\n',
  );
  const run = join(ws, "runs", "t");
  for (const d of ["inputs", "prompts", "responses", "approved", "reports", "final"]) {
    mkdirSync(join(run, d), { recursive: true });
  }
  writeFileSync(
    join(run, "manifest.json"),
    JSON.stringify({ schema_version: 1, topic_id: "t", events: [] }),
  );
  writeFileSync(join(run, "prompts", "spec.prompt.md"), "# spec prompt\n");

  daemon = spawn("python3", ["-m", "education_pipeline.daemon", ws], {
    cwd: resolve(import.meta.dirname, "../.."),
    env: { ...process.env, EP_WEB_DIST: resolve(import.meta.dirname, "../dist") },
    stdio: "inherit",
  });

  // Poll for a ready record containing a port: the daemon writes a pid-only
  // placeholder first, and reading that races to an undefined port.
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

test("read flow: topic list → run board → stage viewer", async ({ page }) => {
  await page.goto(`${baseURL}/`);
  await expect(page.getByRole("link", { name: "t", exact: true })).toBeVisible();
  await page.getByRole("link", { name: "t", exact: true }).click();
  // spec prompt written, no response → next action is save_response
  await expect(page.getByText(/Run the spec prompt/)).toBeVisible();
  await page.getByRole("listitem", { name: "spec stage" }).getByRole("link", { name: "spec" }).click();
  // The prompt renders as prose by default; the Raw toggle shows the bytes.
  await expect(page.getByRole("heading", { name: "spec prompt" })).toBeVisible();
  await page.getByRole("button", { name: "Raw" }).click();
  await expect(page.getByText("# spec prompt")).toBeVisible();
});
