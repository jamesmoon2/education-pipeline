import { expect, test, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { bootDaemon, type DaemonHandle } from "./helpers/daemon";

let handle: DaemonHandle;
let baseURL: string;
let ws: string;

const TOPIC_ID = "synthetic-profile-topic";
const SOURCE_ID = "synthetic-profile-alpha";
const COPY_ID = "synthetic-profile-copy";
const PRIVATE_ALPHA = "PLANTED_SYNTHETIC_LEARNER_ALPHA";
const PRIVATE_CONCURRENT = "PLANTED_SYNTHETIC_LEARNER_CONCURRENT";
const PRIVATE_UNSAVED = "PLANTED_SYNTHETIC_LEARNER_UNSAVED";
const PUBLISHABLE_SUMMARY = `Synthetic published summary for ${PRIVATE_ALPHA}`;

async function expectNoSeriousAxeViolations(page: Page) {
  const axe = await new AxeBuilder({ page }).analyze();
  const serious = axe.violations.filter(
    (violation) => violation.impact === "serious" || violation.impact === "critical",
  );
  expect(serious, JSON.stringify(serious, null, 2)).toEqual([]);
}

test.beforeAll(async () => {
  handle = await bootDaemon("ep-e2e-profiles-", {
    setup(workspace) {
      writeFileSync(
        join(workspace, "topics", `${TOPIC_ID}.toml`),
        `schema_version = 1\nid = "${TOPIC_ID}"\ntitle = "Synthetic profile acceptance topic"\n`,
      );
    },
  });
  baseURL = handle.baseURL;
  ws = handle.ws;
});

test.afterAll(() => {
  handle?.daemon?.kill();
});

test("profiles cockpit: create, edit, duplicate, attach, immutable snapshot, and conflict recovery", async ({ page }) => {
  test.setTimeout(120_000);

  // Empty list state.
  await page.goto(`${baseURL}/profiles`);
  await expect(page.getByRole("heading", { name: "Learner profiles", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "No learner profiles yet", exact: true })).toBeVisible();
  await expectNoSeriousAxeViolations(page);

  // New-profile state and the server-rendered private/export preview.
  await page.getByRole("link", { name: "New profile", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Create learner profile", exact: true })).toBeVisible();
  await expectNoSeriousAxeViolations(page);

  await page.getByLabel("Profile id", { exact: true }).fill(SOURCE_ID);
  await page.getByLabel("Target learner", { exact: true }).fill(PRIVATE_ALPHA);
  await page.getByLabel("Prior experience", { exact: true }).fill("PLANTED_SYNTHETIC_EXPERIENCE_INITIAL");
  await page.getByLabel("Learning goals", { exact: true }).fill("Trace a planted synthetic workflow");
  await page.getByLabel("Preferred visual aids", { exact: true }).fill("Synthetic diagrams");
  await page.getByLabel("Include summary in published output", { exact: true }).check();
  await page.getByLabel("Publishable summary", { exact: true }).fill(PUBLISHABLE_SUMMARY);

  const preview = page.getByRole("complementary", { name: "Privacy preview", exact: true });
  await expect(preview.getByRole("heading", { name: "Private prompt context", exact: true })).toBeVisible();
  await expect(preview.locator(".profile-prompt-preview")).toContainText("# Learner Profile Context");
  await expect(preview.locator(".profile-prompt-preview")).toContainText(PRIVATE_ALPHA);
  await expect(preview.getByRole("heading", { name: "Published output", exact: true })).toBeVisible();
  await expect(preview.locator(".publishable-summary")).toHaveText(PUBLISHABLE_SUMMARY);

  // Warning UI renders the value-free policy fields, never the planted value.
  const warningList = preview.locator(".profile-warning-list");
  await expect(warningList.getByRole("heading", { name: "Privacy warnings", exact: true })).toBeVisible();
  const targetWarning = warningList.getByRole("listitem").filter({ hasText: "target_learner" });
  await expect(targetWarning).toHaveText(
    /privacy\.summary_contains_private_value at target_learner · fingerprint [0-9a-f]{12}/,
  );
  await expect(targetWarning).not.toContainText(PRIVATE_ALPHA);
  await expect(targetWarning.locator("code")).toHaveCount(3);
  await expectNoSeriousAxeViolations(page);

  await page.getByRole("button", { name: "Create profile", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/profiles/${SOURCE_ID}$`));
  await expect(page.getByRole("heading", { name: SOURCE_ID, exact: true })).toBeVisible();
  await expect(page.getByLabel("Profile id", { exact: true })).toBeDisabled();
  await expectNoSeriousAxeViolations(page);

  // Edit the canonical source, then duplicate it with a new embedded id.
  await page.getByLabel("Prior experience", { exact: true }).fill("PLANTED_SYNTHETIC_EXPERIENCE_EDITED");
  await page.getByRole("button", { name: "Save changes", exact: true }).click();
  await expect(page.locator("#profile-action-feedback")).toHaveText("Changes saved.");
  await page.getByLabel("Duplicate as", { exact: true }).fill(COPY_ID);
  await page.getByRole("button", { name: "Duplicate profile", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/profiles/${COPY_ID}$`));
  await expect(page.getByLabel("Profile id", { exact: true })).toHaveValue(COPY_ID);
  await expect(page.getByLabel("Prior experience", { exact: true })).toHaveValue(
    "PLANTED_SYNTHETIC_EXPERIENCE_EDITED",
  );

  // Attach from the topic list and inspect the fixture workspace bytes directly.
  await page.getByRole("link", { name: "Education Pipeline", exact: true }).click();
  const topicRow = page.getByRole("row").filter({ hasText: TOPIC_ID });
  await topicRow.getByLabel(`Attach profile to ${TOPIC_ID}`, { exact: true }).selectOption(COPY_ID);
  await topicRow.getByRole("button", { name: "Attach", exact: true }).click();
  await expect(topicRow.getByText(`Attached ${COPY_ID}.`, { exact: true })).toBeVisible();

  const profilePath = join(ws, "profiles", `${COPY_ID}.toml`);
  const snapshotPath = join(ws, "runs", TOPIC_ID, "inputs", "profile.toml");
  const attachedProfileBytes = readFileSync(profilePath);
  const attachedSnapshotBytes = readFileSync(snapshotPath);
  expect(attachedSnapshotBytes.equals(attachedProfileBytes)).toBe(true);
  expect(attachedSnapshotBytes.toString("utf-8")).toContain(`id = "${COPY_ID}"`);
  expect(attachedSnapshotBytes.toString("utf-8")).toContain(PRIVATE_ALPHA);

  // A later profile edit changes saved profile bytes but not the attached run snapshot.
  await page.goto(`${baseURL}/profiles/${COPY_ID}`);
  await page.getByLabel("Preferred examples", { exact: true }).fill("PLANTED_SYNTHETIC_EXAMPLE_AFTER_ATTACH");
  await page.getByRole("button", { name: "Save changes", exact: true }).click();
  await expect(page.locator("#profile-action-feedback")).toHaveText("Changes saved.");
  const editedProfileBytes = readFileSync(profilePath);
  expect(editedProfileBytes.equals(attachedProfileBytes)).toBe(false);
  expect(editedProfileBytes.toString("utf-8")).toContain(
    "PLANTED_SYNTHETIC_EXAMPLE_AFTER_ATTACH",
  );
  expect(readFileSync(snapshotPath).equals(attachedSnapshotBytes)).toBe(true);
  expect(readFileSync(snapshotPath).toString("utf-8")).not.toContain(
    "PLANTED_SYNTHETIC_EXAMPLE_AFTER_ATTACH",
  );

  // Mutate the profile through the real daemon API while the editor retains its old SHA.
  const concurrent = await page.evaluate(
    async ({ copyId, targetLearner }) => {
      const sessionResponse = await fetch("/v1/session");
      const session = (await sessionResponse.json()) as { token: string };
      const headers = { "Content-Type": "application/json", "X-EP-Token": session.token };
      const detailResponse = await fetch(`/v1/profiles/${encodeURIComponent(copyId)}`, { headers });
      const detail = (await detailResponse.json()) as {
        parsed: Record<string, unknown>;
        content_sha256: string;
      };
      const response = await fetch(`/v1/profiles/${encodeURIComponent(copyId)}`, {
        method: "PUT",
        headers,
        body: JSON.stringify({
          profile: { ...detail.parsed, target_learner: targetLearner },
          base_sha256: detail.content_sha256,
        }),
      });
      return { status: response.status, body: await response.json() };
    },
    { copyId: COPY_ID, targetLearner: PRIVATE_CONCURRENT },
  );
  expect(concurrent.status).toBe(200);

  await page.getByLabel("Target learner", { exact: true }).fill(PRIVATE_UNSAVED);
  await page.getByRole("button", { name: "Save changes", exact: true }).click();
  const conflict = page.getByRole("alert");
  await expect(conflict).toHaveText(
    "This profile changed on disk. Your unsaved input is still here; reload the current profile only when you are ready to replace it.",
  );
  await expect(conflict).not.toContainText(PRIVATE_ALPHA);
  await expect(conflict).not.toContainText(PRIVATE_CONCURRENT);
  await expect(conflict).not.toContainText(PRIVATE_UNSAVED);
  await expect(page.getByLabel("Target learner", { exact: true })).toHaveValue(PRIVATE_UNSAVED);
  await expectNoSeriousAxeViolations(page);

  await page.getByRole("button", { name: "Reload current profile", exact: true }).click();
  await expect(page.getByLabel("Target learner", { exact: true })).toHaveValue(PRIVATE_CONCURRENT);
  await expect(page.getByText("Unsaved changes", { exact: true })).toHaveCount(0);
  expect(readFileSync(snapshotPath).equals(attachedSnapshotBytes)).toBe(true);
});
