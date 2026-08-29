import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Dialog, type Page } from "@playwright/test";
import {
  chmodSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { delimiter, join, resolve } from "node:path";
import { bootDaemon, type DaemonHandle } from "./helpers/daemon";

let handle: DaemonHandle | undefined;
let baseURL = "";
let ws = "";
let stubDir: string | undefined;
let workspaceDir: string | undefined;

const TOPIC = "personalization-milestone";
const NO_PROFILE_TOPIC = "personalization-no-profile";
const PROFILE_ID = "milestone-profile";
const PRIVATE_PROFILE_VALUE = "PLANTED_PRIVATE_ALDERBRIDGE_LEARNER";
const PRIVATE_GOAL_TEXT = "PLANTED_PRIVATE_GOAL_ALPHA";
const PRIVATE_EXCLUSION_REASON = "Synthetic deferred objective.";
const PRIVATE_ANNOTATION_KEYS = ["serves_goals", "goal_exclusions"] as const;
const HOSTILE_AUDIT_RATIONALE = "HOSTILE_AUDIT_RATIONALE_7F4C_DO_NOT_PUBLISH";
const HOSTILE_AUDIT_SUMMARY = "HOSTILE_AUDIT_SUMMARY_9B2E_DO_NOT_PUBLISH";

const SPEC = `# Course Specification\n\n\`\`\`education-pipeline-contract+json\n${JSON.stringify({
  contract_version: 1,
  guide_schema_version: "1.1",
  blueprint: "conceptual-foundations",
  estimated_minutes: 30,
  outcomes: [{ id: "identify-loop", text: "Identify reinforcing and balancing feedback." }],
  required_interactions: ["knowledge_check", "worked_reveal", "scenario", "reflection"],
  personalization_requirements: ["Use the attached learner profile locally."],
  source_policy: "Sources required for factual claims that are not common knowledge.",
})}\n\`\`\``;

const OUTLINE = `# Course Outline\n\n\`\`\`education-pipeline-outline+json\n${JSON.stringify({
  contract_version: 1,
  modules: {
    "feedback-loops": {
      outcome_ids: ["identify-loop"],
      estimated_minutes: 30,
      interaction_types: ["knowledge_check", "worked_reveal"],
    },
  },
})}\n\`\`\``;

const SAFE_GUIDE = readFileSync(
  resolve(import.meta.dirname, "../../tests/fixtures/guides/feedback-loops.personalized.guide.json"),
  "utf-8",
);
const leakedGuide = JSON.parse(SAFE_GUIDE);
leakedGuide.modules[0].sections[0].blocks[0].markdown += ` ${PRIVATE_PROFILE_VALUE}`;
const LEAKED_GUIDE = JSON.stringify(leakedGuide);

const AUDIT_RESPONSE = JSON.stringify({
  schema_version: 1,
  goals: [
    {
      goal_id: "goal-001",
      verdict: "weak",
      evidence: [{ kind: "module", id: "loop-basics" }],
      rationale: HOSTILE_AUDIT_RATIONALE,
    },
    {
      goal_id: "goal-002",
      verdict: "served",
      evidence: [{ kind: "module", id: "intervention-practice" }],
      rationale: "Synthetic local audit rationale beta.",
    },
    {
      goal_id: "goal-003",
      verdict: "missing",
      evidence: [],
      rationale: "Synthetic local audit rationale gamma.",
    },
  ],
  facets: [
    {
      facet_id: "pacing",
      verdict: "served",
      evidence: [{ kind: "module", id: "loop-basics" }],
      rationale: "Synthetic local facet rationale.",
    },
  ],
  generic_sections: [
    {
      location: { kind: "block", id: "loop-introduction" },
      reason_code: "generic_explanation",
      rationale: "Synthetic local generic-section rationale.",
    },
  ],
  suspected_private_details: [],
  overall_summary: HOSTILE_AUDIT_SUMMARY,
});

const MODEL_CATALOG = `
[[providers]]
id = "claude-code"
label = "Claude Code"
description = "Deterministic audit stub for milestone acceptance."

[[providers.models]]
id = "balanced"
label = "Balanced"
description = "Deterministic acceptance model."
quality = "strong"
default_effort = "medium"
`;

const MODEL_PLAN = `provider = "claude-code"

[stages.audit]
model = "balanced"
`;

function auditStub(): string {
  return `#!/usr/bin/env python3
import json
import sys
sys.stdin.buffer.read()
sys.stdout.write(json.dumps({"result": ${JSON.stringify(AUDIT_RESPONSE)}}))
`;
}

async function expectNoSeriousAxeViolations(page: Page, state: string) {
  const axe = await new AxeBuilder({ page }).analyze();
  const serious = axe.violations.filter(
    (violation) => violation.impact === "serious" || violation.impact === "critical",
  );
  expect(serious, `${state}: ${JSON.stringify(serious, null, 2)}`).toEqual([]);
}

function stageStep(page: Page, stage: string) {
  return page.getByRole("listitem", { name: `${stage} stage` });
}

function validationPanel(page: Page, phase: "draft" | "final") {
  return page.locator(`section[aria-label="${phase} validation findings"]`);
}

async function pasteAndApprove(page: Page, stage: string, response: string) {
  await page.getByRole("button", { name: "Advance", exact: true }).click();
  await page.getByRole("button", { name: "Paste response…", exact: true }).click();
  await page.getByLabel(`Response for ${stage}`, { exact: true }).fill(response);
  await page.getByRole("button", { name: "Save response", exact: true }).click();
  await page.getByRole("button", { name: `Approve ${stage} only`, exact: true }).click();
}

async function importTopic(page: Page, id: string, title: string) {
  await page.getByRole("button", { name: "Import topic…", exact: true }).click();
  await page
    .getByLabel("topic TOML", { exact: true })
    .fill(`schema_version = 1\nid = "${id}"\ntitle = "${title}"\n`);
  await page.getByRole("button", { name: "Import", exact: true }).click();
}

async function acceptExpectedConfirm(
  page: Page,
  expectedMessage: string,
  trigger: () => Promise<unknown>,
) {
  const handled = new Promise<void>((resolveDialog, rejectDialog) => {
    page.once("dialog", async (dialog: Dialog) => {
      try {
        expect(dialog.type()).toBe("confirm");
        expect(dialog.message()).toBe(expectedMessage);
        await dialog.accept();
        resolveDialog();
      } catch (error) {
        await dialog.dismiss().catch(() => undefined);
        rejectDialog(error);
      }
    });
  });
  await trigger();
  await handled;
}

test.beforeAll(async () => {
  stubDir = mkdtempSync(join(tmpdir(), "ep-e2e-personalization-stub-"));
  try {
    const claudePath = join(stubDir, "claude");
    writeFileSync(claudePath, auditStub());
    chmodSync(claudePath, 0o755);

    handle = await bootDaemon("ep-e2e-personalization-", {
      env: { PATH: `${stubDir}${delimiter}${process.env.PATH ?? ""}` },
      setup(workspace) {
        const config = join(workspace, "config");
        mkdirSync(config, { recursive: true });
        writeFileSync(join(config, "model-catalog.toml"), MODEL_CATALOG);
        writeFileSync(join(config, "model-plan.toml"), MODEL_PLAN);
      },
    });
    baseURL = handle.baseURL;
    ws = handle.ws;
    workspaceDir = handle.ws;
  } catch (error) {
    rmSync(stubDir, { recursive: true, force: true });
    stubDir = undefined;
    throw error;
  }
});

test.afterAll(async () => {
  const daemon = handle?.daemon;
  try {
    if (daemon && daemon.exitCode === null && daemon.signalCode === null) {
      const exited = new Promise<void>((resolveExit) => {
        daemon.once("exit", () => resolveExit());
      });
      daemon.kill();
      await exited;
    }
  } finally {
    if (workspaceDir) rmSync(workspaceDir, { recursive: true, force: true });
    if (stubDir) rmSync(stubDir, { recursive: true, force: true });
  }
  if (workspaceDir) expect(existsSync(workspaceDir)).toBe(false);
  if (stubDir) expect(existsSync(stubDir)).toBe(false);
});

test("personalization milestone: private profile through safe audited export", async ({ page }) => {
  test.setTimeout(240_000);

  // Profiles: empty state, structured create form, and both privacy previews.
  await page.goto(`${baseURL}/profiles`);
  await expect(page.getByRole("heading", { name: "Learner profiles", exact: true })).toBeVisible();
  await expectNoSeriousAxeViolations(page, "Profiles");
  await page.getByRole("link", { name: "New profile", exact: true }).click();
  await page.getByLabel("Profile id", { exact: true }).fill(PROFILE_ID);
  await page.getByLabel("Target learner", { exact: true }).fill(PRIVATE_PROFILE_VALUE);
  await page
    .getByLabel("Learning goals", { exact: true })
    .fill(`${PRIVATE_GOAL_TEXT}\nPLANTED_PRIVATE_GOAL_BETA\nPLANTED_PRIVATE_GOAL_GAMMA`);
  await page.getByLabel("Preferred visual aids", { exact: true }).fill("flowcharts");

  const privacyPreview = page.getByRole("complementary", {
    name: "Privacy preview",
    exact: true,
  });
  await expect(
    privacyPreview.getByRole("heading", { name: "Private prompt context", exact: true }),
  ).toBeVisible();
  await expect(privacyPreview.locator(".profile-prompt-preview")).toContainText(
    PRIVATE_PROFILE_VALUE,
  );
  await expect(
    privacyPreview.getByRole("heading", { name: "Published output", exact: true }),
  ).toBeVisible();
  await expect(privacyPreview).toContainText("Not included in published output.");
  await page.getByRole("button", { name: "Create profile", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/profiles/${PROFILE_ID}$`));

  // Attach the structured profile to the topic through the cockpit.
  await page.getByRole("link", { name: "Education Pipeline", exact: true }).click();
  await importTopic(page, TOPIC, "Personalization milestone");
  const topicRow = page.getByRole("row").filter({ hasText: TOPIC });
  await topicRow.getByLabel(`Attach profile to ${TOPIC}`, { exact: true }).selectOption(PROFILE_ID);
  await topicRow.getByRole("button", { name: "Attach", exact: true }).click();
  await expect(topicRow.getByText(`Attached ${PROFILE_ID}.`, { exact: true })).toBeVisible();
  await topicRow.getByRole("link", { name: TOPIC, exact: true }).click();

  // Full schema-1.1 guide run with a planted private-value leak.
  await page.getByRole("button", { name: "Advance", exact: true }).click();
  await page.getByRole("button", { name: "Paste response…", exact: true }).click();
  await page.getByLabel("Response for spec", { exact: true }).fill(SPEC);
  await page.getByRole("button", { name: "Save response", exact: true }).click();
  await page.getByRole("button", { name: "Approve spec only", exact: true }).click();
  await pasteAndApprove(page, "outline", OUTLINE);
  await pasteAndApprove(page, "draft", SAFE_GUIDE);
  await page.getByRole("button", { name: "Run draft validation", exact: true }).click();

  await pasteAndApprove(page, "qa", "# QA\n\nNo blocking issues.");
  await pasteAndApprove(
    page,
    "factcheck",
    "# Fact-Check Report\n\n## Verdict\npass — no material factual errors.\n\n## Findings\n(none)\n",
  );
  await pasteAndApprove(page, "repair", LEAKED_GUIDE);
  await page.getByRole("button", { name: "Run final validation", exact: true }).click();

  const finalFindings = validationPanel(page, "final");
  await expect(finalFindings.getByText(/privacy\.exact_private_value/)).toBeVisible();
  await expect(page.getByText(/Finalization blocked:/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Finalize", exact: true })).toHaveCount(0);

  // Repair the leaking final source, reapprove it, and revalidate before release.
  await stageStep(page, "repair").getByRole("link", { name: "repair" }).click();
  await expect(page).toHaveURL(new RegExp(`/topics/${TOPIC}/stages/repair$`));
  await page.getByRole("tab", { name: /^response/ }).click();
  await page.getByRole("button", { name: "Edit", exact: true }).click();
  const repairEditor = page.getByLabel("Edit response for repair");
  await expect(repairEditor).toBeVisible();
  await repairEditor.fill(SAFE_GUIDE);
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await acceptExpectedConfirm(
    page,
    "stage 'repair' is already approved; retry with overwrite to replace it\n\nOverwrite?",
    () => page.getByRole("button", { name: "Approve repair", exact: true }).click(),
  );
  await page.getByRole("link", { name: new RegExp(`back to ${TOPIC}`) }).click();
  await validationPanel(page, "final")
    .getByRole("button", { name: "Re-run validation", exact: true })
    .click();
  await expect(finalFindings.getByText(/privacy\.exact_private_value/)).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Finalize", exact: true })).toBeVisible();

  // Trace-only fit state and the opaque preview evidence bridge.
  await expect(page.getByText("Personalization trace is current.", { exact: true })).toBeVisible();
  await expect(page.getByText("Optional audit has not been run.", { exact: true })).toBeVisible();
  await expectNoSeriousAxeViolations(page, "trace-only");

  const preview = page.frameLocator('iframe[title="Interactive guide preview"]');
  const firstSection = preview.locator('section[data-role="guide-section"]').first();
  const evidenceTarget = preview
    .locator('section[data-module-id="intervention-practice"]')
    .first();
  await expect(firstSection).toHaveClass(/is-current/);
  await page
    .getByRole("button", { name: "Open module intervention-practice", exact: true })
    .click();
  await expect(firstSection).not.toHaveClass(/is-current/);
  await expect(evidenceTarget).toHaveClass(/is-current/);
  await expect(evidenceTarget).toBeFocused();

  // First public export is trace-only and must strip every private/source-only value.
  await page.getByRole("button", { name: "Finalize", exact: true }).click();
  await page.getByRole("button", { name: "Export", exact: true }).click();
  await expect(page.getByText("Exported html.", { exact: true })).toBeVisible();

  const htmlPath = join(ws, "runs", TOPIC, "final", "guide.html");
  const sidecarPath = join(ws, "runs", TOPIC, "final", "guide.report.json");
  await expect.poll(() => existsSync(htmlPath)).toBe(true);
  await expect.poll(() => existsSync(sidecarPath)).toBe(true);
  for (const publicArtifact of [
    readFileSync(htmlPath, "utf-8"),
    readFileSync(sidecarPath, "utf-8"),
  ]) {
    expect(publicArtifact).not.toContain(PRIVATE_PROFILE_VALUE);
    expect(publicArtifact).not.toContain(PRIVATE_GOAL_TEXT);
    expect(publicArtifact).not.toContain(PRIVATE_EXCLUSION_REASON);
    for (const key of PRIVATE_ANNOTATION_KEYS) expect(publicArtifact).not.toContain(key);
  }

  // Run the optional audit with a deterministic real provider job, approve its
  // hostile/private-safe projection, and re-export the now-stale public sidecar.
  await page.getByRole("button", { name: "Prepare audit", exact: true }).click();
  await expect(page.getByText("Audit prompt prepared.", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Run audit with provider", exact: true }).click();
  await expect(page.getByRole("button", { name: "Approve audit", exact: true })).toBeVisible({
    timeout: 30_000,
  });
  await page.getByRole("button", { name: "Approve audit", exact: true }).click();
  await expect(page.getByText("Optional audit is current.", { exact: true })).toBeVisible();
  const rawAuditResponse = readFileSync(
    join(ws, "runs", TOPIC, "responses", "audit.response.json"),
    "utf-8",
  );
  expect(rawAuditResponse).toContain(HOSTILE_AUDIT_RATIONALE);
  expect(rawAuditResponse).toContain(HOSTILE_AUDIT_SUMMARY);
  await expect(page.locator("main")).not.toContainText(HOSTILE_AUDIT_RATIONALE);
  await expect(page.locator("main")).not.toContainText(HOSTILE_AUDIT_SUMMARY);
  await expect(page.getByText(/audit\.goal_weak/)).toBeVisible();
  await expect(page.getByText(/audit\.goal_missing/)).toBeVisible();
  await expect(page.getByText(/audit\.generic_section/)).toBeVisible();
  await expect(page.getByText("Re-export to publish the current personalization evidence.")).toBeVisible();
  await expectNoSeriousAxeViolations(page, "current-audit");

  // Corrupt only the private safe-projection hash input to exercise the real
  // stale-audit aggregate state, then restore the approved bytes before the
  // required re-export. This mirrors an interrupted/local artifact edit while
  // keeping the UI flow and public export contract real.
  const auditProjectionPath = join(
    ws,
    "runs",
    TOPIC,
    "reports",
    "personalization-audit-projection.json",
  );
  const approvedProjection = readFileSync(auditProjectionPath);
  const safeAuditProjection = approvedProjection.toString("utf-8");
  expect(safeAuditProjection).not.toContain(HOSTILE_AUDIT_RATIONALE);
  expect(safeAuditProjection).not.toContain(HOSTILE_AUDIT_SUMMARY);
  writeFileSync(
    auditProjectionPath,
    Buffer.concat([approvedProjection, Buffer.from("\n")]),
  );
  await page.reload();
  await expect(page.getByText("Optional audit is stale.", { exact: true })).toBeVisible();
  await expectNoSeriousAxeViolations(page, "stale-audit");
  writeFileSync(auditProjectionPath, approvedProjection);
  await page.reload();
  await expect(page.getByText("Optional audit is current.", { exact: true })).toBeVisible();

  await acceptExpectedConfirm(
    page,
    "html export already exists; retry with overwrite to replace it\n\nOverwrite?",
    () => page.getByRole("button", { name: "Export", exact: true }).click(),
  );
  await expect(page.getByText("Exported html.", { exact: true })).toBeVisible();

  const auditedHtml = readFileSync(htmlPath, "utf-8");
  const auditedSidecar = readFileSync(sidecarPath, "utf-8");
  expect(JSON.parse(auditedSidecar).audit.state).toBe("current");
  for (const privateValue of [
    PRIVATE_PROFILE_VALUE,
    PRIVATE_GOAL_TEXT,
    PRIVATE_EXCLUSION_REASON,
    ...PRIVATE_ANNOTATION_KEYS,
  ]) {
    expect(auditedSidecar).not.toContain(privateValue);
  }
  for (const publicAuditArtifact of [
    safeAuditProjection,
    auditedHtml,
    auditedSidecar,
  ]) {
    expect(publicAuditArtifact).not.toContain(HOSTILE_AUDIT_RATIONALE);
    expect(publicAuditArtifact).not.toContain(HOSTILE_AUDIT_SUMMARY);
  }

  // A second interactive-guide run without an attachment exercises the no-profile state.
  await page.getByRole("link", { name: "Education Pipeline", exact: true }).click();
  await importTopic(page, NO_PROFILE_TOPIC, "No profile acceptance");
  await page.getByRole("link", { name: NO_PROFILE_TOPIC, exact: true }).click();
  await page.getByRole("button", { name: "Advance", exact: true }).click();
  await expect(page.getByText("No learner profile is attached.", { exact: true })).toBeVisible();
  await expect(page.getByText("Audit unavailable: No learner profile is attached.", { exact: true })).toBeVisible();
  await expectNoSeriousAxeViolations(page, "no-profile");
});
