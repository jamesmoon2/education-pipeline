import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { DraftProgress, NextAction, RunStatus } from "../api/types";
import type { Continuation, ContinueStep, ContinueStop } from "../lib/continueRun";
import PrimaryAction from "./PrimaryAction";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return {
    ApiRequestError: actual.ApiRequestError,
    postAdvance: vi.fn(),
    postApprove: vi.fn(),
    postFinalize: vi.fn(),
    postValidate: vi.fn(),
    postResponse: vi.fn(),
    postExport: vi.fn(),
    enqueueJob: vi.fn(),
    getStageContent: vi.fn(),
    // Called by the "Approve & continue" client (lib/continueRun.ts).
    postContinue: vi.fn(),
    downloadFinal: vi.fn(),
    downloadExport: vi.fn(),
    // Read by JobLogView's tail, mounted for a running activeJob.
    getJobLog: vi.fn(),
  };
});

import {
  ApiRequestError,
  enqueueJob,
  getJobLog,
  getStageContent,
  postAdvance,
  postApprove,
  postContinue,
  postFinalize,
  postValidate,
  postResponse,
} from "../api/client";
import type { Job, StageContent } from "../api/types";

beforeEach(() => {
  vi.clearAllMocks();
  vi.restoreAllMocks();
  delete (navigator as { clipboard?: unknown }).clipboard;
});

function makeStageContent(prompt: string | null): StageContent {
  return {
    topic_id: "t",
    stage: "draft",
    prompt,
    response: null,
    approved: null,
    response_sha256: null,
    content_type: "text/markdown",
  };
}

function makeStatus(
  action: NextAction["action"],
  stage: string | null,
  stages: RunStatus["stages"] = [],
  draftProgress?: DraftProgress,
): RunStatus {
  return {
    topic_id: "t",
    finalized: action === "done",
    content_contract: draftProgress ? { kind: "interactive_guide" } : { kind: "legacy_markdown" },
    stage_provenance: [],
    validations: {
      draft: { state: "missing", blocking: 0, errors: 0, warnings: 0 },
      final: { state: "missing", blocking: 0, errors: 0, warnings: 0 },
    },
    stages,
    next_action: { topic_id: "t", stage, action, detail: `detail for ${action}` },
    ...(draftProgress ? { draft_progress: draftProgress } : {}),
  };
}

function makeDraftProgress(overrides: Partial<DraftProgress> = {}): DraftProgress {
  return {
    skeleton: { state: "response_ingested", error: null, job_id: null },
    modules: [
      {
        id: "loop-basics",
        title: "How loops behave",
        state: "prompt_written",
        response_sha256: null,
        error: null,
        job_id: null,
      },
    ],
    assembled: null,
    superseded: false,
    parallelism: 2,
    counts: { total: 1, saved: 0, stale: 0 },
    ...overrides,
  };
}

function renderAction(status: RunStatus, onChanged = vi.fn(), activeJob: Job | null = null) {
  render(
    <MemoryRouter>
      <PrimaryAction status={status} activeJob={activeJob} onChanged={onChanged} />
    </MemoryRouter>,
  );
  return onChanged;
}

// T34: RunStatus.continuation (decision 9 addendum) -- the daemon's report
// of the latest chained job it carried on its own, after the endpoint that
// started it returned. Self-contained fixture, mirroring continueRun.test.ts.
function makeContinuation(
  stop: ContinueStop,
  steps: ContinueStep[] = [],
  overrides: Partial<Omit<Continuation, "stop" | "steps">> = {},
): Continuation {
  return {
    job_id: "j1",
    stage: "draft",
    provider: "claude-code",
    after: "job",
    steps,
    stop,
    at: "2026-09-19T00:00:00.000Z",
    ...overrides,
  };
}

function withContinuation(status: RunStatus, continuation: Continuation | null): RunStatus {
  return { ...status, continuation };
}

function makeJob(status: Job["status"], overrides: Partial<Job> = {}): Job {
  return {
    id: "j1",
    topic_id: "t",
    stage: "draft",
    provider: "claude-code",
    model: "sonnet",
    effort: null,
    status,
    created_at: "2026-07-10T00:00:00.000Z",
    started_at: "2026-07-10T00:01:00.000Z",
    ended_at: null,
    exit_code: null,
    error: null,
    ...overrides,
  };
}

describe("PrimaryAction", () => {
  it("write_prompt renders Advance and posts it", async () => {
    vi.mocked(postAdvance).mockResolvedValue({
      performed: "write_prompt",
      status: makeStatus("save_response", "spec"),
    });
    const onChanged = renderAction(makeStatus("write_prompt", "spec"));
    await userEvent.click(screen.getByRole("button", { name: "Advance" }));
    expect(postAdvance).toHaveBeenCalledWith("t");
    expect(onChanged).toHaveBeenCalled();
    expect(await screen.findByText("Prompt written.")).toBeInTheDocument();
  });

  it("save_response renders provider run and paste form", async () => {
    vi.mocked(enqueueJob).mockResolvedValue({} as never);
    vi.mocked(postResponse).mockResolvedValue({} as never);
    const onChanged = renderAction(makeStatus("save_response", "draft"));

    await userEvent.click(screen.getByRole("button", { name: "Run with provider" }));
    expect(enqueueJob).toHaveBeenCalledWith("t");

    await userEvent.click(screen.getByRole("button", { name: "Paste response…" }));
    await userEvent.type(screen.getByLabelText("Response for draft"), "draft body");
    await userEvent.click(screen.getByRole("button", { name: "Save response" }));
    expect(postResponse).toHaveBeenCalledWith("t", "draft", "draft body");
    expect(onChanged).toHaveBeenCalled();
  });

  it("save_response on a guide draft with drafted modules labels the button 'Run modules with provider' and delegates paste to the panel", async () => {
    renderAction(makeStatus("save_response", "draft", [], makeDraftProgress()));
    expect(
      screen.getByRole("button", { name: "Run modules with provider" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Run with provider" })).not.toBeInTheDocument();
    // The unit-level paste loop lives in DraftProgressPanel now; the
    // stage-level "paste a whole response" loop must not also appear.
    expect(screen.queryByRole("button", { name: "Paste response…" })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Response for draft")).not.toBeInTheDocument();
  });

  it("save_response before the skeleton has module rows still uses the plain manual loop", async () => {
    vi.mocked(enqueueJob).mockResolvedValue({} as never);
    renderAction(
      makeStatus(
        "save_response",
        "draft",
        [],
        makeDraftProgress({
          skeleton: { state: "prompt_written", error: null, job_id: null },
          modules: [],
          counts: { total: 0, saved: 0, stale: 0 },
        }),
      ),
    );
    expect(screen.getByRole("button", { name: "Run with provider" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Paste response…" }));
    expect(screen.getByLabelText("Response for draft")).toBeInTheDocument();
  });

  it("save_response for a legacy run (no draft_progress) keeps the plain manual loop", async () => {
    renderAction(makeStatus("save_response", "draft"));
    expect(screen.getByRole("button", { name: "Run with provider" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Paste response…" }));
    expect(screen.getByLabelText("Response for draft")).toBeInTheDocument();
  });

  it("save_response groups the manual loop and copies the stage prompt", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    vi.mocked(getStageContent).mockResolvedValue(
      makeStageContent("# raw prompt bytes\n"),
    );
    renderAction(makeStatus("save_response", "draft"));

    const loop = screen.getByRole("list", { name: "Manual copy/paste loop" });
    expect(loop).toContainElement(
      screen.getByRole("button", { name: "Copy prompt" }),
    );
    expect(loop).toContainElement(
      screen.getByRole("button", { name: "Paste response…" }),
    );
    expect(loop).not.toContainElement(
      screen.getByRole("button", { name: "Run with provider" }),
    );

    await userEvent.click(screen.getByRole("button", { name: "Copy prompt" }));
    expect(getStageContent).toHaveBeenCalledWith("t", "draft");
    expect(writeText).toHaveBeenCalledWith("# raw prompt bytes\n");
    expect(await screen.findByRole("status")).toHaveTextContent("Copied ✓");
  });

  it("copy prompt fails visibly when no prompt is on disk", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    vi.mocked(getStageContent).mockResolvedValue(makeStageContent(null));
    renderAction(makeStatus("save_response", "draft"));
    await userEvent.click(screen.getByRole("button", { name: "Copy prompt" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Copy failed — select the prompt text and copy it manually.",
    );
    expect(writeText).not.toHaveBeenCalled();
  });

  it("approve renders both approval buttons with a review link to the pending response", async () => {
    vi.mocked(postApprove).mockResolvedValue({} as never);
    vi.mocked(postContinue).mockResolvedValue({
      topic_id: "t",
      steps: [],
      stop: { kind: "finalize" },
      status: null,
    });
    renderAction(makeStatus("approve", "qa"));
    expect(screen.getByRole("link", { name: "review first" })).toHaveAttribute(
      "href",
      "/topics/t/stages/qa?tab=response",
    );
    await userEvent.click(screen.getByRole("button", { name: "Approve qa & continue" }));
    expect(postApprove).toHaveBeenCalledWith("t", "qa");
  });

  it("approve only approves and stops there", async () => {
    vi.mocked(postApprove).mockResolvedValue({} as never);
    renderAction(makeStatus("approve", "qa"));
    await userEvent.click(screen.getByRole("button", { name: "Approve qa only" }));
    expect(postApprove).toHaveBeenCalledWith("t", "qa");
    expect(postContinue).not.toHaveBeenCalled();
    expect(postAdvance).not.toHaveBeenCalled();
    expect(enqueueJob).not.toHaveBeenCalled();
    expect(await screen.findByText("Approved qa.")).toBeInTheDocument();
  });

  it("Approve & continue writes the next prompt and starts the configured provider", async () => {
    vi.mocked(postApprove).mockResolvedValue({} as never);
    vi.mocked(postContinue).mockResolvedValue({
      topic_id: "t",
      steps: [
        { kind: "advance", stage: "qa" },
        { kind: "job", stage: "qa", provider: "claude-code" },
      ],
      stop: { kind: "started", stage: "qa", provider: "claude-code" },
      status: null,
    });
    const onChanged = renderAction(makeStatus("approve", "draft"));

    await userEvent.click(screen.getByRole("button", { name: "Approve draft & continue" }));
    expect(postApprove).toHaveBeenCalledWith("t", "draft");
    expect(postContinue).toHaveBeenCalledWith("t");
    expect(await screen.findByText("Approved draft — started qa with claude-code.")).toHaveClass(
      "success",
    );
    expect(onChanged).toHaveBeenCalled();
  });

  it("Approve & continue hands a manual stage back to the copy/paste loop", async () => {
    vi.mocked(postApprove).mockResolvedValue({} as never);
    vi.mocked(postContinue).mockResolvedValue({
      topic_id: "t",
      steps: [{ kind: "advance", stage: "qa" }],
      stop: { kind: "manual", stage: "qa" },
      status: null,
    });
    renderAction(makeStatus("approve", "draft"));

    await userEvent.click(screen.getByRole("button", { name: "Approve draft & continue" }));
    expect(enqueueJob).not.toHaveBeenCalled();
    expect(
      await screen.findByText("Approved draft — the qa prompt is ready for you to run."),
    ).toBeInTheDocument();
  });

  it("Approve & continue stops at the next gate that needs judgment", async () => {
    vi.mocked(postApprove).mockResolvedValue({} as never);
    vi.mocked(postContinue).mockResolvedValue({
      topic_id: "t",
      steps: [{ kind: "validate", stage: "draft", phase: "draft" }],
      stop: { kind: "resolve_findings" },
      status: null,
    });
    renderAction(makeStatus("approve", "qa"));

    await userEvent.click(screen.getByRole("button", { name: "Approve qa & continue" }));
    expect(postContinue).toHaveBeenCalledWith("t");
    expect(
      await screen.findByText("Approved qa — ran draft validation; findings need review."),
    ).toBeInTheDocument();
  });

  it("Approve & continue still reports the approval when a follow-up fails", async () => {
    vi.mocked(postApprove).mockResolvedValue({} as never);
    vi.mocked(postContinue).mockResolvedValue({
      topic_id: "t",
      steps: [{ kind: "advance", stage: "qa" }],
      stop: {
        kind: "failed",
        action: "writing the qa prompt",
        message: "job j1 is running for topic 't'",
      },
      status: null,
    });
    renderAction(makeStatus("approve", "draft"));

    await userEvent.click(screen.getByRole("button", { name: "Approve draft & continue" }));
    // The approval landed, but a failed follow-up must not read as a plain
    // success: the line carries the error tone.
    expect(
      await screen.findByText(
        "Approved draft, but writing the qa prompt failed: job j1 is running for topic 't'",
      ),
    ).toHaveClass("error");
  });

  it("keeps the success tone for a stage left to the manual loop", async () => {
    vi.mocked(postApprove).mockResolvedValue({} as never);
    vi.mocked(postContinue).mockResolvedValue({
      topic_id: "t",
      steps: [{ kind: "advance", stage: "qa" }],
      stop: { kind: "plan_unreadable", stage: "qa" },
      status: null,
    });
    renderAction(makeStatus("approve", "draft"));

    await userEvent.click(screen.getByRole("button", { name: "Approve draft & continue" }));
    expect(
      await screen.findByText(
        "Approved draft — the qa prompt is ready, but the model plan could not be read, so start the stage yourself.",
      ),
    ).toHaveClass("success");
  });

  it("labels a re-approval when the stage already has an approved copy", async () => {
    vi.mocked(postApprove).mockResolvedValue({} as never);
    renderAction(
      makeStatus("approve", "qa", [
        {
          stage: "qa",
          state: "stale",
          prompt_written: true,
          response_ingested: true,
          approved: true,
        },
      ]),
    );
    const button = screen.getByRole("button", { name: "Approve changes to qa only" });
    // e2e and screen-reader affordances rely on names starting with "Approve".
    expect(button).toHaveAccessibleName(/^Approve/);
    expect(
      screen.getByRole("button", { name: "Approve changes to qa & continue" }),
    ).toBeInTheDocument();
    await userEvent.click(button);
    expect(postApprove).toHaveBeenCalledWith("t", "qa");
  });

  it("keeps the plain approve label when no approved copy exists for the stage", () => {
    renderAction(
      makeStatus("approve", "qa", [
        {
          stage: "qa",
          state: "response_ingested",
          prompt_written: true,
          response_ingested: true,
          approved: false,
        },
      ]),
    );
    expect(screen.getByRole("button", { name: "Approve qa only" })).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Approve changes to qa/ }),
    ).not.toBeInTheDocument();
  });

  it("retries approve with overwrite after a confirmed 409", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    vi.mocked(postApprove)
      .mockRejectedValueOnce(new ApiRequestError(409, "already_exists", "already approved"))
      .mockResolvedValueOnce({} as never);
    renderAction(makeStatus("approve", "qa"));
    await userEvent.click(screen.getByRole("button", { name: "Approve qa only" }));
    expect(postApprove).toHaveBeenNthCalledWith(1, "t", "qa");
    expect(postApprove).toHaveBeenNthCalledWith(2, "t", "qa", true);
  });

  it("retries the & continue approval with overwrite, then runs the chain", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    vi.mocked(postApprove)
      .mockRejectedValueOnce(new ApiRequestError(409, "already_exists", "already approved"))
      .mockResolvedValueOnce({} as never);
    vi.mocked(postContinue).mockResolvedValue({
      topic_id: "t",
      steps: [],
      stop: { kind: "finalize" },
      status: null,
    });
    renderAction(makeStatus("approve", "qa"));

    await userEvent.click(screen.getByRole("button", { name: "Approve qa & continue" }));
    expect(postApprove).toHaveBeenNthCalledWith(1, "t", "qa");
    expect(postApprove).toHaveBeenNthCalledWith(2, "t", "qa", true);
    // The chain runs once, after the retried approval succeeded.
    expect(postContinue).toHaveBeenCalledTimes(1);
    expect(
      await screen.findByText("Approved qa — the run is ready to finalize."),
    ).toBeInTheDocument();
  });

  it("never finalizes from the continue chain", async () => {
    vi.mocked(postApprove).mockResolvedValue({} as never);
    vi.mocked(postContinue).mockResolvedValue({
      topic_id: "t",
      steps: [],
      stop: { kind: "finalize" },
      status: null,
    });
    renderAction(makeStatus("approve", "repair"));

    await userEvent.click(screen.getByRole("button", { name: "Approve repair & continue" }));
    await screen.findByText("Approved repair — the run is ready to finalize.");
    expect(postFinalize).not.toHaveBeenCalled();
  });

  it("finalize renders Finalize", async () => {
    vi.mocked(postFinalize).mockResolvedValue({} as never);
    renderAction(makeStatus("finalize", null));
    await userEvent.click(screen.getByRole("button", { name: "Finalize" }));
    expect(postFinalize).toHaveBeenCalledWith("t");
  });

  it("assemble renders Assemble draft and posts advance", async () => {
    vi.mocked(postAdvance).mockResolvedValue({
      performed: "write_prompt",
      status: makeStatus("approve", "draft"),
    });
    renderAction(makeStatus("assemble", "draft"));
    await userEvent.click(screen.getByRole("button", { name: "Assemble draft" }));
    expect(postAdvance).toHaveBeenCalledWith("t");
  });

  it("runs the phase-specific validation machine action", async () => {
    vi.mocked(postValidate).mockResolvedValue({} as never);
    renderAction(makeStatus("validate", "repair"));
    await userEvent.click(screen.getByRole("button", { name: "Run final validation" }));
    expect(postValidate).toHaveBeenCalledWith("t", "final");
  });

  it("explains and links resolve_findings without offering finalize", () => {
    renderAction(makeStatus("resolve_findings", "repair"));
    expect(screen.getByRole("link", { name: "Review findings" })).toHaveAttribute(
      "href", "/topics/t/stages/repair",
    );
    expect(screen.getByText(/Finalization blocked/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Finalize" })).toBeNull();
  });

  it("shows the envelope message on job_active", async () => {
    vi.mocked(postAdvance).mockRejectedValue(
      new ApiRequestError(409, "job_active", "job j1 is running for topic 't'"),
    );
    renderAction(makeStatus("write_prompt", "spec"));
    await userEvent.click(screen.getByRole("button", { name: "Advance" }));
    expect(
      await screen.findByText(/job j1 is running for topic 't'/),
    ).toBeInTheDocument();
  });
});

describe("PrimaryAction active job", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.setSystemTime(new Date("2026-07-10T00:05:00.000Z"));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("shows a ticking elapsed readout and a log tail for a running job", async () => {
    vi.mocked(getJobLog).mockResolvedValue({
      data: "line one\nline two\nline three\nline four",
      offset: 40,
    });
    renderAction(
      makeStatus("save_response", "draft"),
      vi.fn(),
      makeJob("running", { started_at: "2026-07-10T00:01:00.000Z" }),
    );

    expect(
      screen.getByText(/draft stage is running with claude-code \/ sonnet/),
    ).toBeInTheDocument();
    expect(screen.getByText("Running for 4m 00s")).toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });
    expect(screen.getByText("Running for 5m 00s")).toBeInTheDocument();

    // Only the tail (last 3 non-empty lines) is shown, not the full log.
    expect(await screen.findByText(/line four/)).toBeInTheDocument();
    expect(screen.queryByText(/line one\b/)).not.toBeInTheDocument();
  });

  it("shows a Queued elapsed readout without a log tail (no process running yet)", () => {
    renderAction(
      makeStatus("save_response", "draft"),
      vi.fn(),
      makeJob("queued", { started_at: null, created_at: "2026-07-10T00:04:18.000Z" }),
    );
    const status = screen.getByRole("status");
    const elapsed = screen.getByText("Queued for 42s");
    expect(elapsed).toBeInTheDocument();
    // A screen reader must not be able to re-announce the ticking readout
    // via the live region: it has to live outside it.
    expect(status).not.toContainElement(elapsed);
    expect(getJobLog).not.toHaveBeenCalled();
  });

  it("keeps the ticking elapsed readout out of the live region", async () => {
    vi.mocked(getJobLog).mockResolvedValue({ data: "", offset: 0 });
    renderAction(
      makeStatus("save_response", "draft"),
      vi.fn(),
      makeJob("running", { started_at: "2026-07-10T00:01:00.000Z" }),
    );

    const status = screen.getByRole("status");
    const elapsed = screen.getByText("Running for 4m 00s");
    // The elapsed readout is a sibling of the live region, not nested
    // inside it -- assistive tech reads it on demand, but the region
    // itself never re-announces it.
    expect(status).not.toContainElement(elapsed);
    // Still reachable/readable: not hidden from the accessibility tree.
    expect(elapsed).toBeVisible();
    expect(elapsed).not.toHaveAttribute("aria-hidden");

    const initialStatusText = status.textContent;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });

    // The tick changed the elapsed readout...
    expect(screen.getByText("Running for 5m 00s")).toBeInTheDocument();
    // ...but the live region's own announced text did not change, so a
    // screen reader has nothing to re-announce every second.
    expect(status.textContent).toBe(initialStatusText);
  });
});

describe("PrimaryAction continuation feedback (T34, decision 9 addendum)", () => {
  it("renders chainFeedback text with the success tone when status carries a continuation", () => {
    const continuation = makeContinuation(
      { kind: "approve", stage: "draft" },
      [{ kind: "validate", stage: "draft", phase: "draft" }],
      { stage: "draft" },
    );
    renderAction(withContinuation(makeStatus("write_prompt", "spec"), continuation));
    expect(
      screen.getByText(
        "After the draft job ran: ran draft validation; draft needs your approval.",
      ),
    ).toHaveClass("success");
  });

  it("renders the error tone when the continuation's chain failed", () => {
    const continuation = makeContinuation(
      {
        kind: "failed",
        action: "starting qa with claude-code",
        message: "provider unavailable",
      },
      [{ kind: "advance", stage: "qa" }],
      { stage: "draft" },
    );
    renderAction(withContinuation(makeStatus("write_prompt", "spec"), continuation));
    expect(
      screen.getByText(
        "After the draft job ran: wrote the qa prompt; starting qa with claude-code failed: provider unavailable.",
      ),
    ).toHaveClass("error");
  });

  it("uses the module-jobs phrasing for an after: batch continuation", () => {
    const continuation = makeContinuation(
      { kind: "started", stage: "qa", provider: "claude-code", count: 3 },
      [],
      { stage: "draft", after: "batch" },
    );
    renderAction(withContinuation(makeStatus("write_prompt", "spec"), continuation));
    expect(
      screen.getByText(
        "After the draft module jobs ran: 3 module jobs started for qa with claude-code.",
      ),
    ).toBeInTheDocument();
  });

  it("renders nothing when status carries no continuation", () => {
    renderAction(makeStatus("write_prompt", "spec"));
    expect(screen.queryByText(/After the .* job ran/)).not.toBeInTheDocument();
    expect(screen.queryByText(/After the .* module jobs ran/)).not.toBeInTheDocument();
  });

  it("renders nothing when continuation is explicitly null", () => {
    renderAction(withContinuation(makeStatus("write_prompt", "spec"), null));
    expect(screen.queryByText(/After the .* job ran/)).not.toBeInTheDocument();
  });
});

describe("PrimaryAction 'Continue to next approval' (T34, decision 9 addendum)", () => {
  it("renders for next action write_prompt", () => {
    renderAction(makeStatus("write_prompt", "spec"));
    expect(
      screen.getByRole("button", { name: "Continue to next approval" }),
    ).toBeInTheDocument();
  });

  it("renders for next action assemble", () => {
    renderAction(makeStatus("assemble", "draft"));
    expect(
      screen.getByRole("button", { name: "Continue to next approval" }),
    ).toBeInTheDocument();
  });

  it("renders for next action validate", () => {
    renderAction(makeStatus("validate", "repair"));
    expect(
      screen.getByRole("button", { name: "Continue to next approval" }),
    ).toBeInTheDocument();
  });

  it("renders for next action save_response, alongside the unchanged 'Run with provider' button", () => {
    renderAction(makeStatus("save_response", "draft"));
    expect(screen.getByRole("button", { name: "Run with provider" })).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Continue to next approval" }),
    ).toBeInTheDocument();
  });

  it("renders for a guide draft fan-out, alongside the unchanged 'Run modules with provider' button", () => {
    renderAction(makeStatus("save_response", "draft", [], makeDraftProgress()));
    expect(
      screen.getByRole("button", { name: "Run modules with provider" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Continue to next approval" }),
    ).toBeInTheDocument();
  });

  it("does not render for next action approve", () => {
    renderAction(makeStatus("approve", "qa"));
    expect(
      screen.queryByRole("button", { name: "Continue to next approval" }),
    ).not.toBeInTheDocument();
  });

  it("does not render for next action resolve_findings", () => {
    renderAction(makeStatus("resolve_findings", "repair"));
    expect(
      screen.queryByRole("button", { name: "Continue to next approval" }),
    ).not.toBeInTheDocument();
  });

  it("does not render for next action finalize", () => {
    renderAction(makeStatus("finalize", null));
    expect(
      screen.queryByRole("button", { name: "Continue to next approval" }),
    ).not.toBeInTheDocument();
  });

  it("does not render for next action done", () => {
    renderAction(makeStatus("done", null));
    expect(
      screen.queryByRole("button", { name: "Continue to next approval" }),
    ).not.toBeInTheDocument();
  });

  it("calls continueRun (postContinue) and shows continueOnlyFeedback, then refreshes status", async () => {
    vi.mocked(postContinue).mockResolvedValue({
      topic_id: "t",
      steps: [{ kind: "validate", stage: "draft", phase: "draft" }],
      stop: { kind: "resolve_findings" },
      status: null,
    });
    const onChanged = renderAction(makeStatus("assemble", "draft"));

    await userEvent.click(screen.getByRole("button", { name: "Continue to next approval" }));

    expect(postContinue).toHaveBeenCalledWith("t");
    expect(postAdvance).not.toHaveBeenCalled();
    expect(
      await screen.findByText("Continued — ran draft validation; findings need review."),
    ).toHaveClass("success");
    expect(onChanged).toHaveBeenCalled();
  });

  it("shows the error tone when the continue-to-next-approval chain fails", async () => {
    vi.mocked(postContinue).mockResolvedValue({
      topic_id: "t",
      steps: [],
      stop: {
        kind: "failed",
        action: "starting qa with claude-code",
        message: "provider unavailable",
      },
      status: null,
    });
    renderAction(makeStatus("validate", "repair"));

    await userEvent.click(screen.getByRole("button", { name: "Continue to next approval" }));

    expect(
      await screen.findByText(
        "Continuing failed: starting qa with claude-code failed: provider unavailable",
      ),
    ).toHaveClass("error");
  });

  it("disables the button while the call is in flight", async () => {
    let resolvePromise!: (value: Awaited<ReturnType<typeof postContinue>>) => void;
    vi.mocked(postContinue).mockImplementation(
      () =>
        new Promise((resolve) => {
          resolvePromise = resolve;
        }),
    );
    renderAction(makeStatus("write_prompt", "spec"));

    const button = screen.getByRole("button", { name: "Continue to next approval" });
    void userEvent.click(button);

    await waitFor(() => expect(button).toBeDisabled());

    resolvePromise({
      topic_id: "t",
      steps: [],
      stop: { kind: "done" },
      status: null,
    });
  });
});
