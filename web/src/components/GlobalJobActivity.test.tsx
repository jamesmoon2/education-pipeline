import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Job, RunStatus, TopicSummary } from "../api/types";
import GlobalJobActivity from "./GlobalJobActivity";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return {
    ApiRequestError: actual.ApiRequestError,
    getJobs: vi.fn(),
    getTopics: vi.fn(),
  };
});

import { getJobs, getTopics } from "../api/client";

beforeEach(() => {
  vi.clearAllMocks();
  // Most tests here are about job activity, not the topics poll; give it an
  // inert default so it never needs its own mock in those tests.
  vi.mocked(getTopics).mockResolvedValue({ topics: [] });
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

function makeNextAction(overrides: Partial<RunStatus["next_action"]> = {}): RunStatus["next_action"] {
  return { topic_id: "t", stage: "qa", action: "approve", detail: "", ...overrides };
}

function makeTopic(id: string, overrides: Partial<TopicSummary> = {}): TopicSummary {
  return {
    id,
    title: null,
    error: null,
    archived: false,
    last_activity: null,
    profile_id: null,
    completion: null,
    run: {
      topic_id: id,
      finalized: false,
      content_contract: { kind: "legacy_markdown" },
      stage_provenance: [],
      validations: {
        draft: { state: "missing", blocking: 0, errors: 0, warnings: 0 },
        final: { state: "missing", blocking: 0, errors: 0, warnings: 0 },
      },
      stages: [],
      next_action: makeNextAction({ topic_id: id }),
    },
    ...overrides,
  };
}

function renderActivity(topicsIntervalMs = 30) {
  return render(
    <MemoryRouter>
      <GlobalJobActivity intervalMs={30} successToastMs={120} topicsIntervalMs={topicsIntervalMs} />
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

  it("suppresses the active-jobs rail while polling fails, restores on recovery", async () => {
    vi.mocked(getJobs)
      .mockResolvedValueOnce({ jobs: [makeJob("j1", "running")] })
      .mockRejectedValueOnce(new Error("daemon unreachable"))
      .mockResolvedValue({ jobs: [makeJob("j1", "running")] });
    renderActivity();
    await screen.findByLabelText("Active jobs");
    // The failed poll must not keep presenting the stale "running" snapshot.
    await waitFor(() =>
      expect(screen.queryByLabelText("Active jobs")).not.toBeInTheDocument(),
    );
    await screen.findByLabelText("Active jobs");
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

  it("ticks each active job's elapsed time", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.setSystemTime(new Date("2026-07-10T00:05:00Z"));
    vi.mocked(getJobs).mockResolvedValue({
      jobs: [makeJob("j1", "running", { started_at: "2026-07-10T00:01:00Z" })],
    });
    render(
      <MemoryRouter>
        <GlobalJobActivity intervalMs={30} successToastMs={120} topicsIntervalMs={30} />
      </MemoryRouter>,
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    const rail = screen.getByLabelText("Active jobs");
    expect(within(rail).getByText("4m 00s")).toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });
    expect(within(rail).getByText("5m 00s")).toBeInTheDocument();
    vi.useRealTimers();
  });
});

describe("GlobalJobActivity ready to review", () => {
  it("renders nothing when no topic is ready for approval", async () => {
    vi.mocked(getJobs).mockResolvedValue({ jobs: [] });
    vi.mocked(getTopics).mockResolvedValue({
      topics: [makeTopic("t1", { run: { ...makeTopic("t1").run!, next_action: makeNextAction({ action: "validate", stage: "draft" }) } })],
    });
    renderActivity();
    await waitFor(() => expect(getTopics).toHaveBeenCalled());
    expect(screen.queryByLabelText("Ready to review")).not.toBeInTheDocument();
  });

  it("lists non-archived topics awaiting approval, linking to the pending response", async () => {
    vi.mocked(getJobs).mockResolvedValue({ jobs: [] });
    vi.mocked(getTopics).mockResolvedValue({
      topics: [
        makeTopic("intro-to-sql", { title: "Intro to SQL" }),
        makeTopic("archived-one", { archived: true }),
        makeTopic("not-ready", {
          run: { ...makeTopic("not-ready").run!, next_action: makeNextAction({ action: "finalize", stage: null }) },
        }),
      ],
    });
    renderActivity();
    const rail = await screen.findByLabelText("Ready to review");
    expect(within(rail).getByRole("link", { name: "Intro to SQL" })).toHaveAttribute(
      "href",
      "/topics/intro-to-sql/stages/qa?tab=response",
    );
    expect(within(rail).queryByText(/archived-one/)).not.toBeInTheDocument();
    expect(within(rail).queryByText(/not-ready/)).not.toBeInTheDocument();
  });

  it("falls back to the topic id when it has no title", async () => {
    vi.mocked(getJobs).mockResolvedValue({ jobs: [] });
    vi.mocked(getTopics).mockResolvedValue({ topics: [makeTopic("intro-to-sql")] });
    renderActivity();
    const rail = await screen.findByLabelText("Ready to review");
    expect(within(rail).getByRole("link", { name: "intro-to-sql" })).toBeInTheDocument();
  });

  it("caps the list at 5 rows with a '+N more' link to the topic list", async () => {
    vi.mocked(getJobs).mockResolvedValue({ jobs: [] });
    vi.mocked(getTopics).mockResolvedValue({
      topics: Array.from({ length: 7 }, (_, i) => makeTopic(`topic-${i}`)),
    });
    renderActivity();
    const rail = await screen.findByLabelText("Ready to review");
    expect(within(rail).getAllByRole("listitem")).toHaveLength(6); // 5 topics + overflow line
    const more = within(rail).getByRole("link", { name: "+2 more" });
    expect(more).toHaveAttribute("href", "/");
  });

  it("suppresses the section while the topics poll fails, restores on recovery", async () => {
    vi.mocked(getJobs).mockResolvedValue({ jobs: [] });
    vi.mocked(getTopics)
      .mockResolvedValueOnce({ topics: [makeTopic("intro-to-sql")] })
      .mockRejectedValueOnce(new Error("daemon unreachable"))
      .mockResolvedValue({ topics: [makeTopic("intro-to-sql")] });
    renderActivity();
    await screen.findByLabelText("Ready to review");
    // A failed poll must not keep presenting the stale "ready" snapshot --
    // a reviewer may have approved it during the outage.
    await waitFor(() =>
      expect(screen.queryByLabelText("Ready to review")).not.toBeInTheDocument(),
    );
    await screen.findByLabelText("Ready to review");
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

  it("toasts a job that terminates in the same tick another job leaves the payload", async () => {
    vi.mocked(getJobs)
      .mockResolvedValueOnce({
        jobs: [
          makeJob("j1", "running"),
          makeJob("j2", "running", { topic_id: "feedback-loops", stage: "draft" }),
        ],
      })
      .mockResolvedValue({
        jobs: [
          makeJob("j2", "failed", {
            topic_id: "feedback-loops",
            stage: "draft",
            error: "provider exited 1",
          }),
        ],
      });
    renderActivity();

    const toast = await screen.findByRole("alert");
    expect(toast).toHaveTextContent("The draft stage failed on feedback-loops — provider exited 1");
    // j1 left without a terminal status of its own; there is nothing to announce.
    expect(screen.getAllByRole("alert")).toHaveLength(1);
  });

  it("forgets a job the payload drops, so its reappearance is history, not news", async () => {
    vi.mocked(getJobs)
      .mockResolvedValueOnce({ jobs: [makeJob("j1", "running")] })
      .mockResolvedValueOnce({ jobs: [] })
      .mockResolvedValue({ jobs: [makeJob("j1", "succeeded")] });
    renderActivity();

    await waitFor(() => expect(getJobs).toHaveBeenCalledTimes(4));
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Job notifications")).not.toBeInTheDocument();
  });

  it("never toasts a job first seen in a terminal state", async () => {
    vi.mocked(getJobs).mockResolvedValue({ jobs: [makeJob("j1", "succeeded")] });
    renderActivity();
    await waitFor(() => expect(getJobs).toHaveBeenCalledTimes(2));
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Job notifications")).not.toBeInTheDocument();
  });
});
