import { render } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import type { Mock } from "vitest";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { PersonalizationPayload, RunStatus } from "../api/types";
import GlobalJobActivity from "../components/GlobalJobActivity";
import RunBoardPage from "./RunBoardPage";

// T62b exit criterion and design note §6 "At most one request per change":
// EventsProvider + the rail (GlobalJobActivity) + RunBoardPage(t), with the
// client mocked and openEventStream yielding a controllable stream.
//
// - A *change* is one delivered `change` frame.
// - A *mounted resource* is one mounted usePolling instance: the board's
//   /v1/runs/t and /v1/jobs?topic=t, the rail's /v1/jobs and /v1/topics
//   (and, on a guide run, the board's personalization).
// - A *request* is a call to any api client function.

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  // Every client function is a mock that never settles unless a test says
  // otherwise, so any request a test did not plan for is still counted.
  const mocked: Record<string, unknown> = { ApiRequestError: actual.ApiRequestError };
  for (const [name, value] of Object.entries(actual)) {
    if (typeof value === "function" && name !== "ApiRequestError") {
      mocked[name] = vi.fn(() => new Promise(() => {}));
    }
  }
  mocked.openEventStream = vi.fn();
  return mocked;
});

import * as client from "../api/client";
import { getJobs, getPersonalization, getRunStatus, getTopics, openEventStream } from "../api/client";
import { EventsProvider } from "../hooks/useEvents";
import {
  createFakeEventServer,
  flush,
  idleWithKeepalives,
  pendingUntilAborted,
  useFakeClock,
} from "../test/eventStream";

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

const interactiveStatus: RunStatus = {
  ...status,
  content_contract: { kind: "interactive_guide", schema_version: "1.1" },
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

let server: ReturnType<typeof createFakeEventServer>;
const random = () => 0.5;

function renderBoardWithRail() {
  return render(
    <EventsProvider random={random}>
      <MemoryRouter initialEntries={["/topics/t"]}>
        <GlobalJobActivity />
        <Routes>
          <Route path="/topics/:topicId" element={<RunBoardPage />} />
        </Routes>
      </MemoryRouter>
    </EventsProvider>,
  );
}

// Per mounted resource, by the arguments usePolling's fetcher passes.
const boardStatus = () => vi.mocked(getRunStatus).mock.calls.filter(([t]) => t === "t").length;
const boardJobs = () => vi.mocked(getJobs).mock.calls.filter(([t]) => t === "t").length;
const railJobs = () => vi.mocked(getJobs).mock.calls.filter(([t]) => t === undefined).length;
const railTopics = () => vi.mocked(getTopics).mock.calls.length;
const boardPersonalization = () => vi.mocked(getPersonalization).mock.calls.length;

/** Every api client call so far, whatever the route. */
function totalRequests(): number {
  let total = 0;
  for (const [name, value] of Object.entries(client)) {
    if (name === "openEventStream" || !vi.isMockFunction(value)) continue;
    total += (value as Mock).mock.calls.length;
  }
  return total;
}

function snapshot() {
  return {
    boardStatus: boardStatus(),
    boardJobs: boardJobs(),
    railJobs: railJobs(),
    railTopics: railTopics(),
    total: totalRequests(),
  };
}

function delta(before: ReturnType<typeof snapshot>) {
  const now = snapshot();
  return {
    boardStatus: now.boardStatus - before.boardStatus,
    boardJobs: now.boardJobs - before.boardJobs,
    railJobs: now.railJobs - before.railJobs,
    railTopics: now.railTopics - before.railTopics,
    total: now.total - before.total,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  useFakeClock();
  server = createFakeEventServer();
  // clearAllMocks keeps queued mockImplementationOnce answers; start clean.
  vi.mocked(openEventStream).mockReset();
  vi.mocked(openEventStream).mockImplementation(server.open);
  vi.mocked(getRunStatus).mockResolvedValue(status);
  vi.mocked(getJobs).mockResolvedValue({ jobs: [] });
  vi.mocked(getTopics).mockResolvedValue({ topics: [] });
  vi.mocked(getPersonalization).mockResolvedValue(personalization);
});

afterEach(() => {
  vi.useRealTimers();
  delete document.documentElement.dataset.events;
});

/** Mount, let the mount ticks land, then bring the stream up. */
async function mountUp() {
  renderBoardWithRail();
  await flush(0);
  expect(openEventStream).toHaveBeenCalledTimes(1);
  // Mount ticks: the stream is not up yet, so each poller starts as today.
  expect(snapshot()).toMatchObject({ boardStatus: 1, boardJobs: 1, railJobs: 1, railTopics: 1 });
  const beforeHello = snapshot();
  server.current.hello();
  await flush(0);
  return beforeHello;
}

describe("RunBoardPage + rail under the events stream: at most one request per change", () => {
  it("1. after hello, each mounted resource has fetched exactly once (the resync)", async () => {
    const beforeHello = await mountUp();
    expect(delta(beforeHello)).toEqual({
      boardStatus: 1,
      boardJobs: 1,
      railJobs: 1,
      railTopics: 1,
      total: 4,
    });
  });

  it("2. 120 s connected and idle, with a keepalive every 15 s, costs zero requests", async () => {
    await mountUp();
    const before = snapshot();
    await idleWithKeepalives(server.current, 120_000);
    expect(delta(before).total).toBe(0);
  });

  it("3. one change for run t costs one request per {run: t} resource and the rail's /v1/topics, none for the rail's /v1/jobs", async () => {
    await mountUp();
    const before = snapshot();
    server.current.change({ kind: "run", topic: "t" });
    await flush(0);
    expect(delta(before)).toEqual({
      boardStatus: 1,
      boardJobs: 1,
      railJobs: 0,
      railTopics: 1,
      total: 3,
    });
  });

  it("4. a change for another run costs the board nothing (the rail's run-* topics list refetches)", async () => {
    await mountUp();
    const before = snapshot();
    server.current.change({ kind: "run", topic: "other" });
    await flush(0);
    expect(delta(before)).toEqual({
      boardStatus: 0,
      boardJobs: 0,
      railJobs: 0,
      railTopics: 1,
      total: 1,
    });
  });

  it("jobs and topics notices reach only the rail resources that name them", async () => {
    await mountUp();
    let before = snapshot();
    server.current.change({ kind: "jobs" });
    await flush(0);
    expect(delta(before)).toEqual({ boardStatus: 0, boardJobs: 0, railJobs: 1, railTopics: 0, total: 1 });

    before = snapshot();
    server.current.change({ kind: "topics" });
    await flush(0);
    expect(delta(before)).toEqual({ boardStatus: 0, boardJobs: 0, railJobs: 0, railTopics: 1, total: 1 });
  });

  it("5. three more frames during an unresolved fetch cost exactly one follow-up per resource", async () => {
    await mountUp();
    // From here every polled request stays in flight until released.
    const release: Array<() => void> = [];
    const held = <T,>(value: T) =>
      new Promise<T>((resolve) => {
        release.push(() => resolve(value));
      });
    vi.mocked(getRunStatus).mockImplementation(() => held(status));
    vi.mocked(getJobs).mockImplementation(() => held({ jobs: [] }));
    vi.mocked(getTopics).mockImplementation(() => held({ topics: [] }));
    const settle = async () => {
      for (const resolve of release.splice(0)) resolve();
      await flush(0);
    };

    const before = snapshot();
    server.current.change({ kind: "run", topic: "t" });
    await flush(0);
    expect(delta(before)).toMatchObject({ boardStatus: 1, boardJobs: 1, railTopics: 1, total: 3 });
    for (let i = 0; i < 3; i++) {
      server.current.change({ kind: "run", topic: "t" });
      await flush(0);
    }
    expect(delta(before).total).toBe(3); // all three still in flight

    await settle();
    expect(delta(before)).toEqual({
      boardStatus: 2,
      boardJobs: 2,
      railJobs: 0,
      railTopics: 2,
      total: 6,
    });
    await settle();
    await idleWithKeepalives(server.current, 60_000);
    expect(delta(before).total).toBe(6);
  });

  it("6. ending the stream resumes every interval with an immediate tick", async () => {
    await mountUp();
    await idleWithKeepalives(server.current, 30_000);
    // Keep the stream down after it ends: the reconnect never answers.
    vi.mocked(openEventStream).mockImplementation(pendingUntilAborted);
    const before = snapshot();
    server.current.end();
    await flush(0);
    expect(delta(before)).toMatchObject({ boardStatus: 1, boardJobs: 1, railJobs: 1, railTopics: 1 });
    await flush(5_000);
    // Today's cadence: status 5 s, board jobs 2 s, rail jobs 5 s, topics 10 s.
    expect(delta(before)).toMatchObject({ boardStatus: 2, boardJobs: 3, railJobs: 2, railTopics: 1 });
  });

  it("7. a stream-driven fetch that fails is retried on that resource's interval until it succeeds, then costs nothing", async () => {
    await mountUp();
    vi.mocked(getTopics)
      .mockRejectedValueOnce(new Error("half-written TOML"))
      .mockRejectedValueOnce(new Error("half-written TOML"))
      .mockResolvedValue({ topics: [] });
    const before = snapshot();
    server.current.change({ kind: "run", topic: "t" });
    await flush(0);
    expect(delta(before)).toMatchObject({ boardStatus: 1, boardJobs: 1, railTopics: 1, total: 3 });

    // The rail's topics interval is 10 s; only that resource retries.
    await flush(9_999);
    expect(delta(before).total).toBe(3);
    await flush(1);
    expect(delta(before)).toMatchObject({ railTopics: 2, total: 4 }); // fails again
    await flush(10_000);
    expect(delta(before)).toMatchObject({ railTopics: 3, total: 5 }); // succeeds

    await idleWithKeepalives(server.current, 120_000);
    expect(delta(before)).toEqual({
      boardStatus: 1,
      boardJobs: 1,
      railJobs: 0,
      railTopics: 3,
      total: 5,
    });
  });

  it("on a guide run, the board's personalization is one more {run: t} resource", async () => {
    vi.mocked(getRunStatus).mockResolvedValue(interactiveStatus);
    await mountUp();
    await flush(0);
    const personalizationBefore = boardPersonalization();
    expect(personalizationBefore).toBeGreaterThanOrEqual(1);
    const before = snapshot();

    await idleWithKeepalives(server.current, 120_000);
    expect(delta(before).total).toBe(0);

    server.current.change({ kind: "run", topic: "t" });
    await flush(0);
    expect(boardPersonalization() - personalizationBefore).toBe(1);
    expect(delta(before)).toMatchObject({ boardStatus: 1, boardJobs: 1, railJobs: 0, railTopics: 1, total: 4 });

    const beforeOther = boardPersonalization();
    server.current.change({ kind: "run", topic: "other" });
    server.current.change({ kind: "jobs" });
    await flush(0);
    expect(boardPersonalization()).toBe(beforeOther);
  });
});
