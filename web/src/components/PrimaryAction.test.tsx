import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { NextAction, RunStatus } from "../api/types";
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
    // Read by the "Approve & continue" chain (lib/continueRun.ts).
    getRunStatus: vi.fn(),
    getConfigPlan: vi.fn(),
    downloadFinal: vi.fn(),
    downloadExport: vi.fn(),
    // Read by JobLogView's tail, mounted for a running activeJob.
    getJobLog: vi.fn(),
  };
});

import {
  ApiRequestError,
  enqueueJob,
  getConfigPlan,
  getJobLog,
  getRunStatus,
  getStageContent,
  postAdvance,
  postApprove,
  postFinalize,
  postValidate,
  postResponse,
} from "../api/client";
import type { Job, PlanPayload, StageContent } from "../api/types";

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
): RunStatus {
  return {
    topic_id: "t",
    finalized: action === "done",
    content_contract: { kind: "legacy_markdown" },
    stage_provenance: [],
    validations: {
      draft: { state: "missing", blocking: 0, errors: 0, warnings: 0 },
      final: { state: "missing", blocking: 0, errors: 0, warnings: 0 },
    },
    stages,
    next_action: { topic_id: "t", stage, action, detail: `detail for ${action}` },
  };
}

function makePlan(provider: string): PlanPayload {
  return { provider, plan_sha256: "sha-plan", stages: [] };
}

function renderAction(status: RunStatus, onChanged = vi.fn(), activeJob: Job | null = null) {
  render(
    <MemoryRouter>
      <PrimaryAction status={status} activeJob={activeJob} onChanged={onChanged} />
    </MemoryRouter>,
  );
  return onChanged;
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
    vi.mocked(getRunStatus).mockResolvedValue(makeStatus("finalize", null));
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
    expect(getRunStatus).not.toHaveBeenCalled();
    expect(postAdvance).not.toHaveBeenCalled();
    expect(enqueueJob).not.toHaveBeenCalled();
    expect(await screen.findByText("Approved qa.")).toBeInTheDocument();
  });

  it("Approve & continue writes the next prompt and starts the configured provider", async () => {
    vi.mocked(postApprove).mockResolvedValue({} as never);
    vi.mocked(getRunStatus).mockResolvedValue(makeStatus("write_prompt", "qa"));
    vi.mocked(postAdvance).mockResolvedValue({
      performed: "write_prompt",
      status: makeStatus("save_response", "qa"),
    });
    vi.mocked(getConfigPlan).mockResolvedValue(makePlan("claude-code"));
    vi.mocked(enqueueJob).mockResolvedValue({} as never);
    const onChanged = renderAction(makeStatus("approve", "draft"));

    await userEvent.click(screen.getByRole("button", { name: "Approve draft & continue" }));
    expect(postApprove).toHaveBeenCalledWith("t", "draft");
    expect(postAdvance).toHaveBeenCalledWith("t");
    expect(enqueueJob).toHaveBeenCalledWith("t");
    expect(await screen.findByText("Approved draft — started qa with claude-code.")).toHaveClass(
      "success",
    );
    expect(onChanged).toHaveBeenCalled();
  });

  it("Approve & continue hands a manual stage back to the copy/paste loop", async () => {
    vi.mocked(postApprove).mockResolvedValue({} as never);
    vi.mocked(getRunStatus).mockResolvedValue(makeStatus("save_response", "qa"));
    vi.mocked(getConfigPlan).mockResolvedValue(makePlan("manual"));
    renderAction(makeStatus("approve", "draft"));

    await userEvent.click(screen.getByRole("button", { name: "Approve draft & continue" }));
    expect(enqueueJob).not.toHaveBeenCalled();
    expect(
      await screen.findByText("Approved draft — the qa prompt is ready for you to run."),
    ).toBeInTheDocument();
  });

  it("Approve & continue stops at the next gate that needs judgment", async () => {
    vi.mocked(postApprove).mockResolvedValue({} as never);
    vi.mocked(getRunStatus)
      .mockResolvedValueOnce(makeStatus("validate", "draft"))
      .mockResolvedValueOnce(makeStatus("resolve_findings", "draft"));
    vi.mocked(postValidate).mockResolvedValue({} as never);
    renderAction(makeStatus("approve", "qa"));

    await userEvent.click(screen.getByRole("button", { name: "Approve qa & continue" }));
    expect(postValidate).toHaveBeenCalledWith("t", "draft");
    expect(
      await screen.findByText("Approved qa — ran draft validation; findings need review."),
    ).toBeInTheDocument();
  });

  it("Approve & continue still reports the approval when a follow-up fails", async () => {
    vi.mocked(postApprove).mockResolvedValue({} as never);
    vi.mocked(getRunStatus).mockResolvedValue(makeStatus("write_prompt", "qa"));
    vi.mocked(postAdvance).mockRejectedValue(
      new ApiRequestError(409, "job_active", "job j1 is running for topic 't'"),
    );
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
    vi.mocked(getRunStatus).mockResolvedValue(makeStatus("save_response", "qa"));
    vi.mocked(getConfigPlan).mockRejectedValue(new Error("plan unreadable"));
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
    vi.mocked(getRunStatus).mockResolvedValue(makeStatus("finalize", null));
    renderAction(makeStatus("approve", "qa"));

    await userEvent.click(screen.getByRole("button", { name: "Approve qa & continue" }));
    expect(postApprove).toHaveBeenNthCalledWith(1, "t", "qa");
    expect(postApprove).toHaveBeenNthCalledWith(2, "t", "qa", true);
    // The chain runs once, after the retried approval succeeded.
    expect(getRunStatus).toHaveBeenCalledTimes(1);
    expect(
      await screen.findByText("Approved qa — the run is ready to finalize."),
    ).toBeInTheDocument();
  });

  it("never finalizes from the continue chain", async () => {
    vi.mocked(postApprove).mockResolvedValue({} as never);
    vi.mocked(getRunStatus).mockResolvedValue(makeStatus("finalize", null));
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
    expect(screen.getByText("Queued for 42s")).toBeInTheDocument();
    expect(getJobLog).not.toHaveBeenCalled();
  });
});
