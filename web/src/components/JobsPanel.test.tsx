import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
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

function makeJob(id: string, status: Job["status"], overrides: Partial<Job> = {}): Job {
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
    ...overrides,
  };
}

function jobRow(id: string) {
  return screen.getByText(id).closest("tr") as HTMLTableRowElement;
}

describe("JobsPanel help", () => {
  it("explains jobs with an InfoTip near the heading", async () => {
    vi.mocked(getJobs).mockResolvedValue({ jobs: [] });
    render(<JobsPanel topicId="t" />);
    expect(await screen.findByRole("button", { name: "About Jobs" })).toBeInTheDocument();
  });
});

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

describe("JobsPanel timing column", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.setSystemTime(new Date("2026-07-10T00:05:00Z"));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("labels the column in plain language", async () => {
    vi.mocked(getJobs).mockResolvedValue({ jobs: [makeJob("j1", "running")] });
    render(<JobsPanel topicId="t" />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(screen.getByRole("columnheader", { name: "Time" })).toBeInTheDocument();
  });

  it("shows a final duration for a terminal job", async () => {
    vi.mocked(getJobs).mockResolvedValue({
      jobs: [
        makeJob("j3", "succeeded", {
          created_at: "2026-07-10T00:00:00Z",
          started_at: "2026-07-10T00:01:00Z",
          ended_at: "2026-07-10T00:03:30Z",
        }),
      ],
    });
    render(<JobsPanel topicId="t" />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(within(jobRow("j3")).getByText("2m 30s")).toBeInTheDocument();
  });

  it("shows a dash when a terminal job is missing the stamps it needs", async () => {
    vi.mocked(getJobs).mockResolvedValue({
      jobs: [makeJob("j4", "failed", { started_at: "2026-07-10T00:01:00Z", ended_at: null })],
    });
    render(<JobsPanel topicId="t" />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(within(jobRow("j4")).getByText("—")).toBeInTheDocument();
  });

  it("ticks a running job's elapsed time live", async () => {
    vi.mocked(getJobs).mockResolvedValue({
      jobs: [makeJob("j5", "running", { started_at: "2026-07-10T00:01:00Z" })],
    });
    render(<JobsPanel topicId="t" />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(within(jobRow("j5")).getByText("4m 00s")).toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });
    expect(within(jobRow("j5")).getByText("5m 00s")).toBeInTheDocument();
  });

  it("ticks a queued job's elapsed time from created_at", async () => {
    vi.mocked(getJobs).mockResolvedValue({
      jobs: [makeJob("j6", "queued", { created_at: "2026-07-10T00:04:42Z", started_at: null })],
    });
    render(<JobsPanel topicId="t" />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(within(jobRow("j6")).getByText("18s")).toBeInTheDocument();
  });
});
