import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Job } from "../api/types";
import JobsPanel from "./JobsPanel";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return {
    ApiRequestError: actual.ApiRequestError,
    getJobLog: vi.fn(),
    cancelJob: vi.fn(),
  };
});

import { cancelJob } from "../api/client";

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

describe("JobsPanel loading/error/empty states", () => {
  it("shows a loading placeholder while data is null and there is no error", () => {
    render(<JobsPanel data={null} error={null} />);
    expect(screen.getByText("Loading jobs…")).toBeInTheDocument();
  });

  it("shows an error notice from the error prop, even once data was previously loaded", () => {
    render(<JobsPanel data={{ jobs: [makeJob("j1", "running")] }} error={new Error("daemon unreachable")} />);
    expect(screen.getByText(/Failed to load jobs/)).toBeInTheDocument();
    expect(screen.queryByText("j1")).not.toBeInTheDocument();
  });

  it("shows the empty-state message when the payload has no jobs", () => {
    render(<JobsPanel data={{ jobs: [] }} error={null} />);
    expect(screen.getByText(/No jobs yet/)).toBeInTheDocument();
  });
});

describe("JobsPanel help", () => {
  it("explains jobs with an InfoTip near the heading", () => {
    render(<JobsPanel data={{ jobs: [] }} error={null} />);
    expect(screen.getByRole("button", { name: "About Jobs" })).toBeInTheDocument();
  });
});

describe("JobsPanel cancel", () => {
  it("cancels an active job and reports it through onChanged", async () => {
    vi.mocked(cancelJob).mockResolvedValue(makeJob("j1", "canceled"));
    const onChanged = vi.fn();
    render(<JobsPanel data={{ jobs: [makeJob("j1", "running")] }} error={null} onChanged={onChanged} />);
    await userEvent.click(screen.getByRole("button", { name: "cancel" }));
    expect(cancelJob).toHaveBeenCalledWith("j1");
    expect(onChanged).toHaveBeenCalled();
  });

  it("offers no cancel for terminal jobs", () => {
    render(<JobsPanel data={{ jobs: [makeJob("j2", "succeeded")] }} error={null} />);
    expect(screen.getByText("j2")).toBeInTheDocument();
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
    render(<JobsPanel data={{ jobs: [makeJob("j1", "running")] }} error={null} />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(screen.getByRole("columnheader", { name: "Time" })).toBeInTheDocument();
  });

  it("shows a final duration for a terminal job", async () => {
    render(
      <JobsPanel
        data={{
          jobs: [
            makeJob("j3", "succeeded", {
              created_at: "2026-07-10T00:00:00Z",
              started_at: "2026-07-10T00:01:00Z",
              ended_at: "2026-07-10T00:03:30Z",
            }),
          ],
        }}
        error={null}
      />,
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(within(jobRow("j3")).getByText("2m 30s")).toBeInTheDocument();
  });

  it("shows a dash when a terminal job is missing the stamps it needs", async () => {
    render(
      <JobsPanel
        data={{ jobs: [makeJob("j4", "failed", { started_at: "2026-07-10T00:01:00Z", ended_at: null })] }}
        error={null}
      />,
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(within(jobRow("j4")).getByText("—")).toBeInTheDocument();
  });

  it("ticks a running job's elapsed time live", async () => {
    render(
      <JobsPanel
        data={{ jobs: [makeJob("j5", "running", { started_at: "2026-07-10T00:01:00Z" })] }}
        error={null}
      />,
    );
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
    render(
      <JobsPanel
        data={{ jobs: [makeJob("j6", "queued", { created_at: "2026-07-10T00:04:42Z", started_at: null })] }}
        error={null}
      />,
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(within(jobRow("j6")).getByText("18s")).toBeInTheDocument();
  });
});
