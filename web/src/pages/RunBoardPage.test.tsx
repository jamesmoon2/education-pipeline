import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { PersonalizationPayload, RunStatus } from "../api/types";
import RunBoardPage from "./RunBoardPage";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return {
    ApiRequestError: actual.ApiRequestError,
    getRunStatus: vi.fn(),
    getPersonalization: vi.fn(),
    getStageContent: vi.fn(),
    postGuidePreview: vi.fn(),
    prepareAudit: vi.fn(),
    getJobs: vi.fn(),
    getJobLog: vi.fn(),
    postAdvance: vi.fn(),
    postApprove: vi.fn(),
    postFinalize: vi.fn(),
    postResponse: vi.fn(),
    postExport: vi.fn(),
    enqueueJob: vi.fn(),
    downloadFinal: vi.fn(),
    downloadExport: vi.fn(),
    cancelJob: vi.fn(),
    getConfigProviders: vi.fn(),
    getConfigCatalog: vi.fn(),
    getRunPlan: vi.fn(),
    putRunPlan: vi.fn(),
  };
});

import {
  ApiRequestError,
  enqueueJob,
  getConfigCatalog,
  getConfigProviders,
  getJobs,
  getPersonalization,
  getRunPlan,
  getRunStatus,
  getStageContent,
  postGuidePreview,
  prepareAudit,
  postAdvance,
} from "../api/client";

const planProviders = [
  { id: "claude-code", label: "Claude Code", description: "", executable: true, available: true, reason: null },
];
const planCatalog = [
  {
    id: "claude-code",
    label: "Claude Code",
    description: "",
    models: [{ id: "sonnet", label: "Sonnet", description: "", quality: "strong", default_effort: null }],
  },
];
const PLAN_STAGES = [
  "profile",
  "spec",
  "outline",
  "draft",
  "qa",
  "factcheck",
  "repair",
  "finalize",
  "export",
];
function makePlan() {
  return {
    provider: "claude-code",
    plan_sha256: "sha-1",
    stages: PLAN_STAGES.map((stage) => ({
      stage,
      provider: "claude-code",
      model: stage === "finalize" || stage === "export" ? null : "sonnet",
      effort: null,
      recommendation: "x",
      warning: null,
      source: "default" as const,
      command: null,
    })),
  };
}

const status: RunStatus = {
  topic_id: "t",
  finalized: false,
  content_contract: { kind: "legacy_markdown" },
  stage_provenance: [],
  validations: {
    draft: { state: "missing", blocking: 0, errors: 0, warnings: 0 },
    final: { state: "missing", blocking: 0, errors: 0, warnings: 0 },
  },
  stages: [
    { stage: "spec", state: "approved", prompt_written: true, response_ingested: true, approved: true },
    { stage: "outline", state: "prompt_written", prompt_written: true, response_ingested: false, approved: false },
    { stage: "draft", state: "pending", prompt_written: false, response_ingested: false, approved: false },
    { stage: "qa", state: "pending", prompt_written: false, response_ingested: false, approved: false },
    { stage: "factcheck", state: "pending", prompt_written: false, response_ingested: false, approved: false },
    { stage: "repair", state: "pending", prompt_written: false, response_ingested: false, approved: false },
  ],
  next_action: {
    topic_id: "t",
    stage: "outline",
    action: "save_response",
    detail: "Run the outline prompt and save the response.",
  },
};

const personalization: PersonalizationPayload = {
  topic_id: "t",
  profile: { state: "attached", id: "learner-a" },
  trace: {
    state: "current",
    facets: ["pacing"],
    goals: [{
      goal_id: "goal-001",
      goal_text: "Recognize feedback loops",
      status: "served",
      evidence: [{ kind: "module", id: "loop-basics" }],
      exclusions: [],
    }],
  },
  audit: {
    state: "not_run",
    stage_state: "not_run",
    available: true,
    unavailable_reason: null,
    findings: [],
  },
  findings: [],
  export: { state: "missing" },
};

const interactiveStatus: RunStatus = {
  ...status,
  content_contract: { kind: "interactive_guide", schema_version: "1.1" },
};

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/topics/:topicId" element={<RunBoardPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("RunBoardPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getConfigProviders).mockResolvedValue({ providers: planProviders });
    vi.mocked(getConfigCatalog).mockResolvedValue({ providers: planCatalog, presets: [] });
    vi.mocked(getRunPlan).mockResolvedValue(makePlan());
    vi.mocked(getPersonalization).mockResolvedValue(personalization);
    vi.mocked(getStageContent).mockResolvedValue({
      topic_id: "t",
      stage: "repair",
      prompt: null,
      response: null,
      approved: null,
      response_sha256: null,
      content_type: "application/vnd.education-pipeline.guide+json;version=1.0",
    });
    vi.mocked(postGuidePreview).mockResolvedValue({
      html: "<!doctype html><p>Guide preview</p>",
      content_sha256: "a".repeat(64),
      validation: { blocking: 0, errors: 0, warnings: 0 },
    });
  });

  it("integrates trace-only personalization beside the durable preview", async () => {
    vi.mocked(getRunStatus).mockResolvedValue(interactiveStatus);
    vi.mocked(getJobs).mockResolvedValue({ jobs: [] });
    renderAt("/topics/t");

    expect(await screen.findByRole("region", { name: "Personalization fit" })).toBeInTheDocument();
    expect(screen.getByText("Recognize feedback loops")).toBeInTheDocument();
    expect(screen.getByText("Optional audit has not been run.")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Optional personalization audit" })).toBeInTheDocument();
    expect(screen.getByText("Approved repair / final source")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "About Validation" })).toBeInTheDocument();
  });

  it("keeps the durable preview available while personalization is loading or unavailable", async () => {
    vi.mocked(getRunStatus).mockResolvedValue(interactiveStatus);
    vi.mocked(getJobs).mockResolvedValue({ jobs: [] });
    vi.mocked(getPersonalization).mockReturnValue(new Promise(() => undefined));
    const loading = renderAt("/topics/t");

    expect(await screen.findByText("Approved repair / final source")).toBeInTheDocument();
    expect(screen.getByRole("status", { name: /Loading personalization/i })).toBeInTheDocument();
    loading.unmount();

    vi.mocked(getPersonalization).mockRejectedValue(new Error("aggregate unavailable"));
    renderAt("/topics/t");
    expect(await screen.findByText("Approved repair / final source")).toBeInTheDocument();
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/Failed to load personalization/);
    await userEvent.click(screen.getByRole("button", { name: /show details/i }));
    expect(alert).toHaveTextContent("aggregate unavailable");
    expect(screen.queryByRole("region", { name: "Optional personalization audit" })).not.toBeInTheDocument();
  });

  it("refreshes the durable preview after a run mutation", async () => {
    vi.mocked(getRunStatus).mockResolvedValue(interactiveStatus);
    vi.mocked(getJobs).mockResolvedValue({ jobs: [] });
    vi.mocked(enqueueJob).mockResolvedValue({
      id: "job-refresh",
      topic_id: "t",
      stage: "outline",
      provider: "claude-code",
      model: "sonnet",
      effort: null,
      status: "queued",
      created_at: "2026-07-15T00:00:00Z",
      started_at: null,
      ended_at: null,
      exit_code: null,
      error: null,
    });
    renderAt("/topics/t");

    await screen.findByText("No approved repair guide is available yet.");
    expect(getStageContent).toHaveBeenCalledTimes(1);
    await userEvent.click(screen.getByRole("button", { name: "Run with provider" }));
    await waitFor(() => expect(getStageContent).toHaveBeenCalledTimes(2));
  });

  it("preserves audit success feedback while refreshing personalization and preview", async () => {
    vi.mocked(getRunStatus).mockResolvedValue(interactiveStatus);
    vi.mocked(getJobs).mockResolvedValue({ jobs: [] });
    vi.mocked(prepareAudit).mockResolvedValue({} as never);
    renderAt("/topics/t");

    await userEvent.click(await screen.findByRole("button", { name: "Prepare audit" }));
    expect(await screen.findByText("Audit prompt prepared.")).toHaveAttribute("role", "status");
    await waitFor(() => expect(getPersonalization).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(getStageContent).toHaveBeenCalledTimes(2));
  });

  it("never renders personalization state from another topic", async () => {
    vi.mocked(getRunStatus).mockResolvedValue(interactiveStatus);
    vi.mocked(getJobs).mockResolvedValue({ jobs: [] });
    vi.mocked(getPersonalization).mockResolvedValue({
      ...personalization,
      topic_id: "other-topic",
    });
    renderAt("/topics/t");

    expect(await screen.findByText("Approved repair / final source")).toBeInTheDocument();
    expect(await screen.findByRole("alert")).toHaveTextContent(/does not match/i);
    expect(screen.queryByRole("region", { name: "Personalization fit" })).not.toBeInTheDocument();
  });

  it("renders current and stale audit states plus the re-export prompt", async () => {
    vi.mocked(getRunStatus).mockResolvedValue(interactiveStatus);
    vi.mocked(getJobs).mockResolvedValue({ jobs: [] });
    vi.mocked(getPersonalization).mockResolvedValue({
      ...personalization,
      audit: {
        ...personalization.audit,
        state: "current",
        stage_state: "approved",
      },
      export: { state: "current" },
    });
    const view = renderAt("/topics/t");

    expect(await screen.findByText("Optional audit is current.")).toBeInTheDocument();
    expect(screen.getByText("Export is current.")).toBeInTheDocument();

    vi.mocked(getPersonalization).mockResolvedValue({
      ...personalization,
      audit: {
        ...personalization.audit,
        state: "stale",
        stage_state: "stale",
      },
      export: { state: "stale" },
    });
    view.unmount();
    renderAt("/topics/t");

    expect(await screen.findByText("Optional audit is stale.")).toBeInTheDocument();
    expect(screen.getByText("Re-export to publish the current personalization evidence.")).toBeInTheDocument();
    expect(screen.getByText("Re-export the guide to publish the current audit projection.")).toBeInTheDocument();
  });

  it("renders the no-profile state without evidence controls", async () => {
    vi.mocked(getRunStatus).mockResolvedValue(interactiveStatus);
    vi.mocked(getJobs).mockResolvedValue({ jobs: [] });
    vi.mocked(getPersonalization).mockResolvedValue({
      ...personalization,
      profile: { state: "not_attached", id: null },
      trace: { state: "missing", goals: [], facets: [] },
      audit: {
        state: "not_run",
        stage_state: "not_run",
        available: false,
        unavailable_reason: "No learner profile is attached.",
        findings: [],
      },
    });
    renderAt("/topics/t");

    expect(await screen.findByText("No learner profile is attached.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Open module/ })).not.toBeInTheDocument();
  });

  it("shows the effective blueprint with its source and rationale", async () => {
    vi.mocked(getRunStatus).mockResolvedValue({
      ...status,
      blueprint: {
        id: "exam-preparation",
        source: "recommended",
        rationale: "Recommended Exam preparation because the topic mentions 'exam'.",
      },
    });
    vi.mocked(getJobs).mockResolvedValue({ jobs: [] });
    renderAt("/topics/t");

    expect(await screen.findByText("exam-preparation")).toBeInTheDocument();
    expect(screen.getByText(/\(recommended\)/)).toBeInTheDocument();
    expect(
      screen.getByText(/because the topic mentions 'exam'/),
    ).toBeInTheDocument();
  });

  it("omits the blueprint line for runs without one", async () => {
    vi.mocked(getRunStatus).mockResolvedValue({ ...status, blueprint: null });
    vi.mocked(getJobs).mockResolvedValue({ jobs: [] });
    renderAt("/topics/t");

    await screen.findByText(/Run the outline prompt/);
    expect(screen.queryByText(/Blueprint:/)).toBeNull();
  });

  it("renders stages, next action, and jobs", async () => {
    vi.mocked(getRunStatus).mockResolvedValue(status);
    vi.mocked(getJobs).mockResolvedValue({
      jobs: [
        {
          id: "20260710T000000Z-abcd",
          topic_id: "t",
          stage: "outline",
          provider: "claude-code",
          model: "m",
          effort: null,
          status: "running",
          created_at: "2026-07-10T00:00:00Z",
          started_at: "2026-07-10T00:00:01Z",
          ended_at: null,
          exit_code: null,
          error: null,
        },
      ],
    });
    renderAt("/topics/t");

    expect(await screen.findByText(/Run the outline prompt/)).toBeInTheDocument();
    expect(screen.getByText("Complete")).toBeInTheDocument();
    const stageLink = screen.getByRole("link", { name: "spec" });
    expect(stageLink).toHaveAttribute("href", "/topics/t/stages/spec");
    expect(await screen.findByText("20260710T000000Z-abcd")).toBeInTheDocument();
    expect(screen.getByText("running")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "About Finalized" })).toBeInTheDocument();
    expect(getPersonalization).not.toHaveBeenCalled();
  });

  it("surfaces a running job at the top of the board instead of 'ready to run'", async () => {
    vi.mocked(getRunStatus).mockResolvedValue(status);
    vi.mocked(getJobs).mockResolvedValue({
      jobs: [
        {
          id: "20260710T000000Z-abcd",
          topic_id: "t",
          stage: "outline",
          provider: "claude-code",
          model: "sonnet",
          effort: null,
          status: "running",
          created_at: "2026-07-10T00:00:00Z",
          started_at: "2026-07-10T00:00:01Z",
          ended_at: null,
          exit_code: null,
          error: null,
        },
      ],
    });
    renderAt("/topics/t");

    // Action area: live progress replaces the enqueue button (any mutation
    // would 409 while the job runs anyway).
    expect(
      await screen.findByText(/outline stage is running with claude-code/),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Run with provider" })).not.toBeInTheDocument();
    // Pipeline stepper: the outline step reports the run, not "Ready to run".
    const outlineStep = screen.getByRole("listitem", { name: "outline stage" });
    expect(within(outlineStep).getByText(/Running with claude-code/)).toBeInTheDocument();
    expect(screen.queryByText("Ready to run")).not.toBeInTheDocument();
  });

  it("stops presenting a running job as live when the jobs poll starts failing", async () => {
    vi.mocked(getRunStatus).mockResolvedValue(status);
    vi.mocked(getJobs)
      .mockResolvedValueOnce({
        jobs: [
          {
            id: "20260710T000000Z-abcd",
            topic_id: "t",
            stage: "outline",
            provider: "claude-code",
            model: "sonnet",
            effort: null,
            status: "running",
            created_at: "2026-07-10T00:00:00Z",
            started_at: "2026-07-10T00:00:01Z",
            ended_at: null,
            exit_code: null,
            error: null,
          },
        ],
      })
      .mockRejectedValue(new Error("daemon unreachable"));
    renderAt("/topics/t");

    expect(
      await screen.findByText(/outline stage is running with claude-code/),
    ).toBeInTheDocument();
    // The failed poll must not leave the stale "running" snapshot on screen.
    await waitFor(
      () => expect(screen.queryByText(/is running with/)).not.toBeInTheDocument(),
      { timeout: 4_000 },
    );
    expect(screen.getByRole("button", { name: "Run with provider" })).toBeInTheDocument();
  });

  it("keeps the action buttons when no job is active", async () => {
    vi.mocked(getRunStatus).mockResolvedValue(status);
    vi.mocked(getJobs).mockResolvedValue({ jobs: [] });
    renderAt("/topics/t");

    expect(await screen.findByRole("button", { name: "Run with provider" })).toBeInTheDocument();
    expect(screen.queryByText(/is running with/)).not.toBeInTheDocument();
  });

  it("shows a friendly message when no run exists", async () => {
    vi.mocked(getRunStatus).mockRejectedValue(
      new ApiRequestError(404, "not_found", "no run started for topic: t"),
    );
    vi.mocked(getJobs).mockResolvedValue({ jobs: [] });
    renderAt("/topics/t");
    expect(await screen.findByText(/No run started/)).toBeInTheDocument();
    expect(getPersonalization).not.toHaveBeenCalled();
  });

  it("renders the primary action for the current next_action", async () => {
    vi.mocked(getRunStatus).mockResolvedValue(status); // fixture action: save_response
    vi.mocked(getJobs).mockResolvedValue({ jobs: [] });
    renderAt("/topics/t");
    expect(
      await screen.findByRole("button", { name: "Run with provider" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Paste response…" })).toBeInTheDocument();
  });

  it("offers Advance to start a run on the 404 branch", async () => {
    vi.mocked(getRunStatus).mockRejectedValue(
      new ApiRequestError(404, "not_found", "no run started for topic: t"),
    );
    vi.mocked(getJobs).mockResolvedValue({ jobs: [] });
    vi.mocked(postAdvance).mockResolvedValue({ performed: "write_prompt", status });
    renderAt("/topics/t");
    const advance = await screen.findByRole("button", { name: "Advance" });
    expect(screen.getByRole("button", { name: "About Start a run" })).toBeInTheDocument();
    await userEvent.click(advance);
    expect(postAdvance).toHaveBeenCalledWith("t");
  });

  it("shows per-stage findings-count badges combining current draft and final reports", async () => {
    vi.mocked(getRunStatus).mockResolvedValue({
      ...status,
      validations: {
        draft: {
          state: "current",
          blocking: 2,
          errors: 0,
          warnings: 0,
          findings_by_stage: { outline: 2 },
        },
        final: {
          state: "current",
          blocking: 1,
          errors: 0,
          warnings: 0,
          findings_by_stage: { outline: 1, repair: 3 },
        },
      },
    });
    vi.mocked(getJobs).mockResolvedValue({ jobs: [] });
    renderAt("/topics/t");

    // outline: 2 (draft) + 1 (final) summed; repair: 3 from the final report only.
    const repairStep = await screen.findByRole("listitem", { name: "repair stage" });
    expect(within(repairStep).getByLabelText("3 findings")).toBeInTheDocument();
    const outlineStep = screen.getByRole("listitem", { name: "outline stage" });
    expect(within(outlineStep).getByLabelText("3 findings")).toBeInTheDocument();
  });

  it("ignores findings_by_stage from a phase whose report is not current", async () => {
    vi.mocked(getRunStatus).mockResolvedValue({
      ...status,
      validations: {
        // Stale draft counts describe superseded content and must not badge.
        draft: {
          state: "stale",
          blocking: 5,
          errors: 0,
          warnings: 0,
          findings_by_stage: { outline: 5 },
        },
        final: {
          state: "current",
          blocking: 1,
          errors: 0,
          warnings: 0,
          findings_by_stage: { repair: 1 },
        },
      },
    });
    vi.mocked(getJobs).mockResolvedValue({ jobs: [] });
    renderAt("/topics/t");

    const repairStep = await screen.findByRole("listitem", { name: "repair stage" });
    expect(within(repairStep).getByLabelText("1 finding")).toBeInTheDocument();
    expect(screen.queryByLabelText("5 findings")).not.toBeInTheDocument();
  });

  it("shows no badge for a phase whose every blocker is waived (server-netted findings_by_stage)", async () => {
    vi.mocked(getRunStatus).mockResolvedValue({
      ...status,
      validations: {
        // Every blocker in draft carries an accepted waiver: the server
        // (_validation_summary, read_api.py) nets waived findings out of
        // findings_by_stage itself, so a fully-waived stage arrives here as
        // {} -- not as a raw pre-waiver count paired with effective_blocking
        // 0. (findings_by_stage: { outline: 1 } alongside effective_blocking:
        // 0 is a payload the server can never emit: findings_by_stage counts
        // blocking OR severity === "error", while effective_blocking counts
        // blocking only, and the server nets both from the same waived-id
        // set, so a fully-waived blocking finding always empties out of
        // both.)
        draft: {
          state: "current",
          blocking: 1,
          errors: 0,
          warnings: 0,
          findings_by_stage: {},
          effective_blocking: 0,
        },
        // final still has a real, unwaived blocker: its badge must survive.
        final: {
          state: "current",
          blocking: 1,
          errors: 0,
          warnings: 0,
          findings_by_stage: { repair: 1 },
          effective_blocking: 1,
        },
      },
    });
    vi.mocked(getJobs).mockResolvedValue({ jobs: [] });
    renderAt("/topics/t");

    const repairStep = await screen.findByRole("listitem", { name: "repair stage" });
    expect(within(repairStep).getByLabelText("1 finding")).toBeInTheDocument();
    const outlineStep = screen.getByRole("listitem", { name: "outline stage" });
    expect(within(outlineStep).queryByLabelText(/finding/)).not.toBeInTheDocument();
  });

  it("does not announce the findings badge as a live region", async () => {
    vi.mocked(getRunStatus).mockResolvedValue({
      ...status,
      validations: {
        draft: {
          state: "current",
          blocking: 2,
          errors: 0,
          warnings: 0,
          findings_by_stage: { outline: 2 },
        },
        final: { state: "missing", blocking: 0, errors: 0, warnings: 0 },
      },
    });
    vi.mocked(getJobs).mockResolvedValue({ jobs: [] });
    renderAt("/topics/t");

    const badge = await screen.findByLabelText(/2 findings/i);
    expect(badge).not.toHaveAttribute("role", "status");
    expect(badge).toHaveAttribute("aria-label", "2 findings");
  });

  it("shows a provenance line for a stage present in stage_provenance", async () => {
    vi.mocked(getRunStatus).mockResolvedValue({
      ...status,
      stage_provenance: [
        {
          stage: "spec",
          provider: "codex",
          model: "gpt-5.4",
          effort: "high",
          source: "override",
          job_id: "job-1",
          recorded_at: "2026-07-10T00:00:00Z",
        },
      ],
    });
    vi.mocked(getJobs).mockResolvedValue({ jobs: [] });
    renderAt("/topics/t");

    expect(
      await screen.findByText("ran on codex / gpt-5.4 / high (override)"),
    ).toBeInTheDocument();
  });
});
