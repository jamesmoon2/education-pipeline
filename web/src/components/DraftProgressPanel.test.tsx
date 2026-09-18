import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { DraftProgress, Job } from "../api/types";
import DraftProgressPanel from "./DraftProgressPanel";

// docs/superpowers/specs/2026-09-18-per-module-drafting-design.md §8 (T25
// brief). Semantics pinned by this file (for the green implementer):
//
// - Skeleton row: text "Skeleton" plus its state, e.g. "response_ingested".
// - One row per module: its title, its state, and (when set) its error
//   text.
// - "Run modules with provider" button: enqueueJob(topicId, "draft"). Shown
//   only when >=1 module is prompt_written|stale AND no batch is active.
// - Per-module "Rerun <title>" button: enqueueJob(topicId, "draft", force,
//   {modules: [id]}); force = true iff the module already has a
//   response_sha256.
// - Per-module "Paste response for <title>" toggles a textarea labelled
//   "Response for <title>" + a "Save" button that calls
//   postDraftUnitResponse(topicId, "module", id, text).
// - "Assemble draft" button: postDraftAssemble(topicId); shown only when
//   every module is response_ingested AND (assembled === null ||
//   !assembled.ok).
// - Superseded note: rendered (containing "superseded by an edit") iff
//   progress.superseded.
// - Counts line: "{saved} of {total} modules saved".
// - Batch active (any job in activeJobs carrying a batch_id): renders
//   "{done} of {total} running/done" (done = terminal-status jobs of that
//   batch) and a "Cancel batch" button (cancelBatch(batchId)); hides
//   "Run modules with provider" and every per-module "Rerun" button.

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return {
    ApiRequestError: actual.ApiRequestError,
    enqueueJob: vi.fn(),
    cancelBatch: vi.fn(),
    postDraftUnitResponse: vi.fn(),
    postDraftAssemble: vi.fn(),
  };
});

import {
  cancelBatch,
  enqueueJob,
  postDraftAssemble,
  postDraftUnitResponse,
} from "../api/client";

beforeEach(() => {
  vi.clearAllMocks();
});

function makeProgress(overrides: Partial<DraftProgress> = {}): DraftProgress {
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
      {
        id: "intervention-practice",
        title: "Practice interventions",
        state: "not_run",
        response_sha256: null,
        error: null,
        job_id: null,
      },
    ],
    assembled: null,
    superseded: false,
    parallelism: 2,
    counts: { total: 2, saved: 0, stale: 0 },
    ...overrides,
  };
}

function makeJob(overrides: Partial<Job> = {}): Job {
  return {
    id: "j1",
    topic_id: "t",
    stage: "draft",
    provider: "claude-code",
    model: "sonnet",
    effort: null,
    status: "running",
    created_at: "2026-09-18T00:00:00.000Z",
    started_at: "2026-09-18T00:00:00.000Z",
    ended_at: null,
    exit_code: null,
    error: null,
    unit: "module",
    module_id: "loop-basics",
    batch_id: "batch-1",
    ...overrides,
  };
}

function renderPanel(
  progress: DraftProgress = makeProgress(),
  activeJobs: Job[] = [],
  onChanged = vi.fn(),
) {
  render(
    <DraftProgressPanel
      topicId="t"
      progress={progress}
      activeJobs={activeJobs}
      onChanged={onChanged}
    />,
  );
  return onChanged;
}

describe("DraftProgressPanel rows", () => {
  it("renders the skeleton row with its state", () => {
    renderPanel(makeProgress({ skeleton: { state: "response_ingested", error: null, job_id: null } }));
    expect(screen.getByText("Skeleton")).toBeInTheDocument();
    expect(screen.getByText("response_ingested")).toBeInTheDocument();
  });

  it("renders one row per module with its title and state", () => {
    renderPanel();
    expect(screen.getByText("How loops behave")).toBeInTheDocument();
    expect(screen.getByText("Practice interventions")).toBeInTheDocument();
  });

  it("shows a module's error text when set", () => {
    renderPanel(
      makeProgress({
        modules: [
          {
            id: "loop-basics",
            title: "How loops behave",
            state: "stale",
            response_sha256: null,
            error: "assembly failed: dangling source id",
            job_id: null,
          },
        ],
        counts: { total: 1, saved: 0, stale: 1 },
      }),
    );
    expect(screen.getByText("assembly failed: dangling source id")).toBeInTheDocument();
  });

  it("shows the saved/total counts line", () => {
    renderPanel(makeProgress({ counts: { total: 5, saved: 2, stale: 0 } }));
    expect(screen.getByText("2 of 5 modules saved")).toBeInTheDocument();
  });
});

describe("DraftProgressPanel run/rerun", () => {
  it("shows Run modules with provider when a module is prompt_written and enqueues the draft batch", async () => {
    const onChanged = renderPanel();
    const button = screen.getByRole("button", { name: "Run modules with provider" });
    await userEvent.click(button);
    expect(enqueueJob).toHaveBeenCalledWith("t", "draft");
    expect(onChanged).toHaveBeenCalled();
  });

  it("hides Run modules with provider when no module is prompt_written or stale", () => {
    renderPanel(
      makeProgress({
        modules: [
          {
            id: "loop-basics",
            title: "How loops behave",
            state: "response_ingested",
            response_sha256: "sha-a",
            error: null,
            job_id: null,
          },
        ],
        counts: { total: 1, saved: 1, stale: 0 },
      }),
    );
    expect(
      screen.queryByRole("button", { name: "Run modules with provider" }),
    ).not.toBeInTheDocument();
  });

  it("reruns a module without a response with force=false", async () => {
    renderPanel();
    await userEvent.click(screen.getByRole("button", { name: "Rerun How loops behave" }));
    expect(enqueueJob).toHaveBeenCalledWith("t", "draft", false, { modules: ["loop-basics"] });
  });

  it("reruns a module that already has a response with force=true", async () => {
    renderPanel(
      makeProgress({
        modules: [
          {
            id: "loop-basics",
            title: "How loops behave",
            state: "response_ingested",
            response_sha256: "sha-a",
            error: null,
            job_id: null,
          },
        ],
        counts: { total: 1, saved: 1, stale: 0 },
      }),
    );
    await userEvent.click(screen.getByRole("button", { name: "Rerun How loops behave" }));
    expect(enqueueJob).toHaveBeenCalledWith("t", "draft", true, { modules: ["loop-basics"] });
  });
});

describe("DraftProgressPanel paste", () => {
  it("pastes and saves a module response", async () => {
    vi.mocked(postDraftUnitResponse).mockResolvedValue({
      unit: "module",
      module_id: "loop-basics",
      response_path: "draft/modules/loop-basics/response.json",
      response_sha256: "sha-new",
      status: {} as never,
    });
    const onChanged = renderPanel();
    await userEvent.click(
      screen.getByRole("button", { name: "Paste response for How loops behave" }),
    );
    await userEvent.type(
      screen.getByLabelText("Response for How loops behave"),
      '{"id":"loop-basics"}',
    );
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(postDraftUnitResponse).toHaveBeenCalledWith(
      "t",
      "module",
      "loop-basics",
      '{"id":"loop-basics"}',
    );
    expect(onChanged).toHaveBeenCalled();
  });
});

describe("DraftProgressPanel assemble", () => {
  it("shows Assemble draft once every module is response_ingested and nothing is assembled yet", async () => {
    const progress = makeProgress({
      modules: [
        {
          id: "loop-basics",
          title: "How loops behave",
          state: "response_ingested",
          response_sha256: "sha-a",
          error: null,
          job_id: null,
        },
        {
          id: "intervention-practice",
          title: "Practice interventions",
          state: "response_ingested",
          response_sha256: "sha-b",
          error: null,
          job_id: null,
        },
      ],
      assembled: null,
      counts: { total: 2, saved: 2, stale: 0 },
    });
    const onChanged = renderPanel(progress);
    await userEvent.click(screen.getByRole("button", { name: "Assemble draft" }));
    expect(postDraftAssemble).toHaveBeenCalledWith("t");
    expect(onChanged).toHaveBeenCalled();
  });

  it("hides Assemble draft once assembly already succeeded", () => {
    const progress = makeProgress({
      modules: [
        {
          id: "loop-basics",
          title: "How loops behave",
          state: "response_ingested",
          response_sha256: "sha-a",
          error: null,
          job_id: null,
        },
      ],
      assembled: { ok: true, response_sha256: "sha-assembled", error: null },
      counts: { total: 1, saved: 1, stale: 0 },
    });
    renderPanel(progress);
    expect(screen.queryByRole("button", { name: "Assemble draft" })).not.toBeInTheDocument();
  });

  it("hides Assemble draft while any module is not yet response_ingested", () => {
    renderPanel();
    expect(screen.queryByRole("button", { name: "Assemble draft" })).not.toBeInTheDocument();
  });
});

describe("DraftProgressPanel superseded", () => {
  it("shows a superseded note when the progress flags it", () => {
    renderPanel(makeProgress({ superseded: true }));
    expect(screen.getByText(/superseded by an edit/)).toBeInTheDocument();
  });

  it("shows no superseded note otherwise", () => {
    renderPanel(makeProgress({ superseded: false }));
    expect(screen.queryByText(/superseded by an edit/)).not.toBeInTheDocument();
  });
});

describe("DraftProgressPanel active batch", () => {
  it("shows batch progress and a Cancel batch button, and hides run/rerun", async () => {
    const jobs = [
      makeJob({ id: "j1", module_id: "loop-basics", status: "succeeded", batch_id: "batch-1" }),
      makeJob({ id: "j2", module_id: "intervention-practice", status: "running", batch_id: "batch-1" }),
    ];
    const onChanged = renderPanel(makeProgress(), jobs);

    expect(screen.getByText("1 of 2 running/done")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Run modules with provider" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /^Rerun / }),
    ).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Cancel batch" }));
    expect(cancelBatch).toHaveBeenCalledWith("batch-1");
    expect(onChanged).toHaveBeenCalled();
  });
});
