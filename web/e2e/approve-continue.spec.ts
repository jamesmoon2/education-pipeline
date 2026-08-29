import { expect, test, type Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { bootDaemon, type DaemonHandle } from "./helpers/daemon";

// "Approve & continue" acceptance: one click approves the stage the run is
// waiting on and then runs the mechanical follow-ups — here, writing the next
// stage's prompt — stopping at the manual copy/paste loop. Nothing is
// auto-approved, auto-finalized, or auto-exported.
//
// The workspace pins the manual plan so the chain stops at the manual loop
// instead of enqueueing a provider job for a CLI this machine does not have.

let handle: DaemonHandle;

const TOPICS = ["ac-chain", "ac-link"] as const;

test.beforeAll(async () => {
  handle = await bootDaemon("ep-e2e-approve-continue-", {
    setup: (ws) => {
      for (const topic of TOPICS) {
        writeFileSync(
          join(ws, "topics", `${topic}.toml`),
          `schema_version = 1\nid = "${topic}"\ntitle = "Continue ${topic}"\n`,
          "utf-8",
        );
      }
      mkdirSync(join(ws, "config"), { recursive: true });
      writeFileSync(join(ws, "config", "model-plan.toml"), 'provider = "manual"\n', "utf-8");
    },
  });
  for (const topic of TOPICS) {
    execFileSync(
      "python3",
      ["-m", "education_pipeline", "-C", handle.ws, "create", topic, "--legacy-markdown"],
      { cwd: resolve(import.meta.dirname, "../..") },
    );
  }
});

test.afterAll(() => {
  handle?.daemon.kill();
});

/** Board flow up to the approval gate: write the prompt, paste a response. */
async function fillStageResponse(page: Page, topic: string, stage: string) {
  await page.goto(`${handle.baseURL}/topics/${topic}`);
  await page.getByRole("button", { name: "Advance", exact: true }).click();
  await page.getByRole("button", { name: "Paste response…", exact: true }).click();
  await page.getByLabel(`Response for ${stage}`, { exact: true }).fill(`${stage} response body`);
  await page.getByRole("button", { name: "Save response", exact: true }).click();
}

test("Approve & continue approves the stage and writes the next stage's prompt", async ({
  page,
}) => {
  await fillStageResponse(page, "ac-chain", "spec");
  await expect(
    page.getByRole("button", { name: "Approve spec & continue", exact: true }),
  ).toBeVisible();

  await page.getByRole("button", { name: "Approve spec & continue", exact: true }).click();

  // The feedback line names what was approved and where the run now stands.
  await expect(
    page.getByText("Approved spec — the outline prompt is ready for you to run."),
  ).toBeVisible();

  // The run really moved on: the outline prompt is on disk and the board
  // offers the outline stage's manual loop.
  await expect(page.getByText(/Run the outline prompt/)).toBeVisible();
  await expect(
    page.getByRole("list", { name: "Manual copy/paste loop" }),
  ).toBeVisible();
  expect(
    existsSync(join(handle.ws, "runs", "ac-chain", "prompts", "outline.prompt.md")),
  ).toBe(true);

  // Approval is still the only gate: the chain stopped before the next one.
  await expect(page.getByRole("button", { name: /^Approve/ })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Finalize", exact: true })).toHaveCount(0);
});

test("the library's next action links a pending approval to the response tab", async ({
  page,
}) => {
  await fillStageResponse(page, "ac-link", "spec");

  await page.goto(`${handle.baseURL}/`);
  const row = page.getByRole("row").filter({ hasText: "ac-link" });
  const nextAction = row.getByRole("link", { name: "Review and approve", exact: true });
  await expect(nextAction).toHaveAttribute(
    "href",
    "/topics/ac-link/stages/spec?tab=response",
  );

  await nextAction.click();
  await expect(page).toHaveURL(/\/topics\/ac-link\/stages\/spec\?tab=response$/);
  await expect(page.getByRole("tab", { name: /^response/ })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  // The stage viewer offers the same one-click continue for this approval.
  await expect(
    page.getByRole("button", { name: "Approve & continue", exact: true }),
  ).toBeVisible();
});
