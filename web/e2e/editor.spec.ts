import { expect, test } from "@playwright/test";
import { execFileSync, spawn, type ChildProcess } from "node:child_process";
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

let daemon: ChildProcess;
let baseURL: string;
let ws: string;

test.beforeAll(async () => {
  ws = mkdtempSync(join(tmpdir(), "ep-e2e-editor-"));
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

async function importTopicAndRunAllStages(page, topicId: string, title: string) {
  await page.goto(`${baseURL}/`);
  await page.getByRole("button", { name: "Import topic…" }).click();
  await page
    .getByLabel("topic TOML")
    .fill(`schema_version = 1\nid = "${topicId}"\ntitle = "${title}"\n`);
  await page.getByRole("button", { name: "Import", exact: true }).click();
  execFileSync(
    "python3",
    ["-m", "education_pipeline", "-C", ws, "create", topicId, "--legacy-markdown"],
    { cwd: resolve(import.meta.dirname, "../..") },
  );
  await page.getByRole("link", { name: topicId, exact: true }).click();

  for (const stage of ["spec", "outline", "draft", "qa", "repair"]) {
    await page.getByRole("button", { name: "Advance" }).click();
    await page.getByRole("button", { name: "Paste response…" }).click();
    await page.getByLabel(`Response for ${stage}`).fill(`${stage} response body`);
    await page.getByRole("button", { name: "Save response" }).click();
    await page.getByRole("button", { name: `Approve ${stage} only`, exact: true }).click();
  }
}

test("edit → save → re-approve → finalize entirely in the browser", async ({
  page,
}) => {
  page.on("dialog", (dialog) => dialog.accept());
  await importTopicAndRunAllStages(page, "w", "Editable Topic");

  // open the repair stage viewer (stepper node link) and edit its response
  await page
    .getByRole("listitem", { name: "repair stage" })
    .getByRole("link", { name: "repair" })
    .click();
  await page.getByRole("tab", { name: /^response/ }).click();
  await page.getByRole("button", { name: "Edit" }).click();
  await page
    .getByLabel("Edit response for repair")
    .fill("repair response body, edited in the browser");
  await page.getByRole("button", { name: "Save" }).click();

  // the edit resurfaces Approve (already approved -> overwrite confirm auto-accepted)
  await page.getByRole("button", { name: "Approve repair" }).click();
  await expect(page.getByText("Approved repair.")).toBeVisible();

  // back to the run board: finalize the edited run
  await page.getByRole("link", { name: /back to w/ }).click();
  // exact: the run board's "About Finalized" InfoTip trigger would otherwise
  // also substring-match this locator.
  await page.getByRole("button", { name: "Finalize", exact: true }).click();
  await expect(page.getByText("Finalized: yes")).toBeVisible();

  // the edited content is what got finalized
  const finalGuide = readFileSync(join(ws, "runs", "w", "final", "guide.md"), "utf-8");
  expect(finalGuide).toBe("repair response body, edited in the browser");
});

test("a concurrent external edit is detected and rejected, never overwritten", async ({
  page,
}) => {
  await page.goto(`${baseURL}/`);
  await page.getByRole("button", { name: "Import topic…" }).click();
  await page
    .getByLabel("topic TOML")
    .fill('schema_version = 1\nid = "c"\ntitle = "Conflict Topic"\n');
  await page.getByRole("button", { name: "Import", exact: true }).click();
  execFileSync(
    "python3",
    ["-m", "education_pipeline", "-C", ws, "create", "c", "--legacy-markdown"],
    { cwd: resolve(import.meta.dirname, "../..") },
  );
  await page.getByRole("link", { name: "c", exact: true }).click();
  await page.getByRole("button", { name: "Advance" }).click();
  await page.getByRole("button", { name: "Paste response…" }).click();
  await page.getByLabel("Response for spec").fill("spec response body");
  await page.getByRole("button", { name: "Save response" }).click();

  // open the editor with the loaded content/hash
  await page
    .getByRole("listitem", { name: "spec stage" })
    .getByRole("link", { name: "spec" })
    .click();
  await page.getByRole("tab", { name: /^response/ }).click();
  await page.getByRole("button", { name: "Edit" }).click();

  // simulate a concurrent external edit directly on disk
  const responseFile = join(ws, "runs", "c", "responses", "spec.response.md");
  writeFileSync(responseFile, "EXTERNAL EDIT", "utf-8");

  await page.getByLabel("Edit response for spec").fill("my browser edit");
  await page.getByRole("button", { name: "Save" }).click();

  // rejected with the stale-content message; reload is offered
  await expect(page.getByText(/changed on disk/)).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Reload current content" }),
  ).toBeVisible();
  // the buffer is intact and the external edit was never overwritten
  await expect(page.getByLabel("Edit response for spec")).toHaveValue(
    "my browser edit",
  );
  expect(readFileSync(responseFile, "utf-8")).toBe("EXTERNAL EDIT");
});
