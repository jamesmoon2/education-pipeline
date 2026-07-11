import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Job } from "../api/types";
import JobsPanel from "./JobsPanel";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return {
    ApiRequestError: actual.ApiRequestError,
    getJobs: vi.fn(),
    getJobLog: vi.fn(),
    cancelJob: vi.fn(),
  };
});

import { cancelJob, getJobs } from "../api/client";

beforeEach(() => {
  vi.clearAllMocks();
});

function makeJob(id: string, status: Job["status"]): Job {
  return {
    id,
    topic_id: "t",
    stage: "draft",
    provider: "fake",
    model: null,
    effort: null,
    status,
    created_at: "2026-07-10T00:00:00Z",
    started_at: null,
    ended_at: null,
    exit_code: null,
    error: null,
  };
}

describe("JobsPanel cancel", () => {
  it("cancels an active job", async () => {
    vi.mocked(getJobs).mockResolvedValue({ jobs: [makeJob("j1", "running")] });
    vi.mocked(cancelJob).mockResolvedValue(makeJob("j1", "canceled"));
    render(<JobsPanel topicId="t" />);
    await userEvent.click(await screen.findByRole("button", { name: "cancel" }));
    expect(cancelJob).toHaveBeenCalledWith("j1");
  });

  it("offers no cancel for terminal jobs", async () => {
    vi.mocked(getJobs).mockResolvedValue({ jobs: [makeJob("j2", "succeeded")] });
    render(<JobsPanel topicId="t" />);
    expect(await screen.findByText("j2")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "cancel" })).not.toBeInTheDocument();
  });
});
