import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import type { RunStatus } from "../api/types";
import RunBoardPage from "./RunBoardPage";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return {
    ApiRequestError: actual.ApiRequestError,
    getRunStatus: vi.fn(),
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
  };
});

import { ApiRequestError, getJobs, getRunStatus, postAdvance } from "../api/client";

const status: RunStatus = {
  topic_id: "t",
  finalized: false,
  content_contract: { kind: "legacy_markdown" },
  validations: {
    draft: { state: "missing", blocking: 0, errors: 0, warnings: 0 },
    final: { state: "missing", blocking: 0, errors: 0, warnings: 0 },
  },
  stages: [
    { stage: "spec", state: "approved", prompt_written: true, response_ingested: true, approved: true },
    { stage: "outline", state: "prompt_written", prompt_written: true, response_ingested: false, approved: false },
    { stage: "draft", state: "pending", prompt_written: false, response_ingested: false, approved: false },
    { stage: "qa", state: "pending", prompt_written: false, response_ingested: false, approved: false },
    { stage: "repair", state: "pending", prompt_written: false, response_ingested: false, approved: false },
  ],
  next_action: {
    topic_id: "t",
    stage: "outline",
    action: "save_response",
    detail: "Run the outline prompt and save the response.",
  },
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
    expect(screen.getByText("approved")).toBeInTheDocument();
    const stageLink = screen.getAllByRole("link", { name: "view" })[0];
    expect(stageLink).toHaveAttribute("href", "/topics/t/stages/spec");
    expect(await screen.findByText("20260710T000000Z-abcd")).toBeInTheDocument();
    expect(screen.getByText("running")).toBeInTheDocument();
  });

  it("shows a friendly message when no run exists", async () => {
    vi.mocked(getRunStatus).mockRejectedValue(
      new ApiRequestError(404, "not_found", "no run started for topic: t"),
    );
    vi.mocked(getJobs).mockResolvedValue({ jobs: [] });
    renderAt("/topics/t");
    expect(await screen.findByText(/No run started/)).toBeInTheDocument();
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
    await userEvent.click(advance);
    expect(postAdvance).toHaveBeenCalledWith("t");
  });
});
