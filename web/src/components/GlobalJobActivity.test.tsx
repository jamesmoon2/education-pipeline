import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Job } from "../api/types";
import GlobalJobActivity from "./GlobalJobActivity";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return {
    ApiRequestError: actual.ApiRequestError,
    getJobs: vi.fn(),
  };
});

import { getJobs } from "../api/client";

beforeEach(() => {
  vi.clearAllMocks();
});

function makeJob(id: string, status: Job["status"], overrides: Partial<Job> = {}): Job {
  return {
    id,
    topic_id: "intro-to-sql",
    stage: "qa",
    provider: "claude-code",
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

function renderActivity() {
  return render(
    <MemoryRouter>
      <GlobalJobActivity intervalMs={30} successToastMs={120} />
    </MemoryRouter>,
  );
}

describe("GlobalJobActivity rail indicator", () => {
  it("renders nothing when no job is active", async () => {
    vi.mocked(getJobs).mockResolvedValue({ jobs: [makeJob("j0", "succeeded")] });
    renderActivity();
    await waitFor(() => expect(getJobs).toHaveBeenCalled());
    expect(screen.queryByLabelText("Active jobs")).not.toBeInTheDocument();
  });

  it("lists active jobs across topics with links to their boards", async () => {
    vi.mocked(getJobs).mockResolvedValue({
      jobs: [
        makeJob("j1", "running"),
        makeJob("j2", "queued", { topic_id: "feedback-loops", stage: "draft" }),
      ],
    });
    renderActivity();
    const rail = await screen.findByLabelText("Active jobs");
    expect(within(rail).getByText("2 jobs running")).toBeInTheDocument();
    expect(within(rail).getByRole("link", { name: "qa · intro-to-sql" })).toHaveAttribute(
      "href",
      "/topics/intro-to-sql",
    );
    expect(
      within(rail).getByRole("link", { name: "draft · feedback-loops" }),
    ).toHaveAttribute("href", "/topics/feedback-loops");
  });
});

describe("GlobalJobActivity toasts", () => {
  it("toasts when a job observed active succeeds, linking to the response", async () => {
    vi.mocked(getJobs)
      .mockResolvedValueOnce({ jobs: [makeJob("j1", "running")] })
      .mockResolvedValue({ jobs: [makeJob("j1", "succeeded")] });
    renderActivity();
    const toast = await screen.findByRole("status");
    expect(toast).toHaveTextContent("The qa stage finished on intro-to-sql — ready to review.");
    expect(within(toast).getByRole("link", { name: "intro-to-sql" })).toHaveAttribute(
      "href",
      "/topics/intro-to-sql/stages/qa?tab=response",
    );
  });

  it("auto-dismisses a success toast", async () => {
    vi.mocked(getJobs)
      .mockResolvedValueOnce({ jobs: [makeJob("j1", "running")] })
      .mockResolvedValue({ jobs: [makeJob("j1", "succeeded")] });
    renderActivity();
    await screen.findByRole("status");
    await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());
  });

  it("keeps a failure toast (with the error) until dismissed", async () => {
    vi.mocked(getJobs)
      .mockResolvedValueOnce({ jobs: [makeJob("j1", "running")] })
      .mockResolvedValue({
        jobs: [makeJob("j1", "failed", { error: "provider exited 1" })],
      });
    renderActivity();
    const toast = await screen.findByRole("alert");
    expect(toast).toHaveTextContent("The qa stage failed on intro-to-sql — provider exited 1");
    // Outlives the success auto-dismiss window.
    await new Promise((resolve) => setTimeout(resolve, 200));
    expect(screen.getByRole("alert")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Dismiss notification" }));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("never toasts a job first seen in a terminal state", async () => {
    vi.mocked(getJobs).mockResolvedValue({ jobs: [makeJob("j1", "succeeded")] });
    renderActivity();
    await waitFor(() => expect(getJobs).toHaveBeenCalledTimes(2));
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Job notifications")).not.toBeInTheDocument();
  });
});
