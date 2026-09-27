import { render } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import type { Mock } from "vitest";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { RunStatus, StageContent } from "./api/types";
import GlobalJobActivity from "./components/GlobalJobActivity";
import ModuleRepairControl from "./components/ModuleRepairControl";
import NewRunPage from "./pages/NewRunPage";
import ProfilesPage from "./pages/ProfilesPage";
import RunBoardPage from "./pages/RunBoardPage";
import StageViewerPage from "./pages/StageViewerPage";
import TopicListPage from "./pages/TopicListPage";

// T62b, design note §6 call-site table: every usePolling call site passes
// the filter the table gives it, so under a live stream it stops polling
// and refetches exactly on the notices that name its endpoint.
//
// | Call site                                        | Filter                   |
// | RunBoardPage status, jobs?topic=t, personalization; |                       |
// |   StageViewerPage stage, run; ModuleRepairControl | { run: t }              |
// | GlobalJobActivity /v1/jobs                        | { jobs: true }          |
// | GlobalJobActivity, TopicListPage /v1/topics       | { run: "*", topics }    |
// | TopicListPage, NewRunPage, ProfilesPage /v1/profiles | { topics: true }     |
//
// NewRunPage and ProfilesPage are the design note's pre-agreed T62c cut if
// T62b would otherwise touch a 12th non-test file; their rows are the last
// two entries of SITES.

vi.mock("./api/client", async () => {
  const actual = await vi.importActual<typeof import("./api/client")>("./api/client");
  // Every client function never settles unless a site sets it up, so every
  // request a page makes is counted, planned or not.
  const mocked: Record<string, unknown> = { ApiRequestError: actual.ApiRequestError };
  for (const [name, value] of Object.entries(actual)) {
    if (typeof value === "function" && name !== "ApiRequestError") {
      mocked[name] = vi.fn(() => new Promise(() => {}));
    }
  }
  mocked.openEventStream = vi.fn();
  return mocked;
});

import * as client from "./api/client";
import {
  getJobs,
  getPersonalization,
  getProfiles,
  getRepairModules,
  getRunStatus,
  getStageContent,
  getTopics,
  openEventStream,
} from "./api/client";
import { EventsProvider } from "./hooks/useEvents";
import {
  createFakeEventServer,
  flush,
  idleWithKeepalives,
  type Notice,
  useFakeClock,
} from "./test/eventStream";

type Kind = "run t" | "run other" | "jobs" | "topics";
const KINDS: Kind[] = ["run t", "run other", "jobs", "topics"];
const NOTICES: Record<Kind, Notice> = {
  "run t": { kind: "run", topic: "t" },
  "run other": { kind: "run", topic: "other" },
  jobs: { kind: "jobs" },
  topics: { kind: "topics" },
};

// Expected requests per notice for each filter in the table.
const RUN_T: Record<Kind, number> = { "run t": 1, "run other": 0, jobs: 0, topics: 0 };
const JOBS: Record<Kind, number> = { "run t": 0, "run other": 0, jobs: 1, topics: 0 };
const RUN_ANY_OR_TOPICS: Record<Kind, number> = { "run t": 1, "run other": 1, jobs: 0, topics: 1 };
const TOPICS: Record<Kind, number> = { "run t": 0, "run other": 0, jobs: 0, topics: 1 };

const legacyStatus: RunStatus = {
  topic_id: "t",
  finalized: false,
  content_contract: { kind: "legacy_markdown" },
  stage_provenance: [],
  validations: {
    draft: { state: "missing", blocking: 0, errors: 0, warnings: 0 },
    final: { state: "missing", blocking: 0, errors: 0, warnings: 0 },
  },
  stages: [],
  next_action: { topic_id: "t", stage: "draft", action: "save_response", detail: "Save the draft." },
};

const draftContent: StageContent = {
  topic_id: "t",
  stage: "draft",
  prompt: "Write the draft.",
  response: null,
  approved: null,
  response_sha256: null,
  content_type: "text/markdown",
};

interface Resource {
  label: string;
  calls: () => number;
  perNotice: Record<Kind, number>;
}

interface Site {
  name: string;
  setup: () => void;
  ui: ReactNode;
  path?: string;
  resources: Resource[];
}

const callsWith = (fn: unknown, match: (args: unknown[]) => boolean) => () =>
  (fn as Mock).mock.calls.filter(match).length;

const runStatusOfT = callsWith(getRunStatus, ([t]) => t === "t");
const jobsOfT = callsWith(getJobs, ([t]) => t === "t");
const allJobs = callsWith(getJobs, ([t]) => t === undefined);
const topicsList = callsWith(getTopics, () => true);
const profilesList = callsWith(getProfiles, () => true);

const SITES: Site[] = [
  {
    name: "RunBoardPage",
    path: "/topics/t",
    setup: () => {
      vi.mocked(getRunStatus).mockResolvedValue(legacyStatus);
      vi.mocked(getJobs).mockResolvedValue({ jobs: [] });
    },
    ui: (
      <Routes>
        <Route path="/topics/:topicId" element={<RunBoardPage />} />
      </Routes>
    ),
    resources: [
      { label: "/v1/runs/t", calls: runStatusOfT, perNotice: RUN_T },
      { label: "/v1/jobs?topic=t", calls: jobsOfT, perNotice: RUN_T },
    ],
  },
  {
    name: "RunBoardPage on a guide run",
    path: "/topics/t",
    setup: () => {
      vi.mocked(getRunStatus).mockResolvedValue({
        ...legacyStatus,
        content_contract: { kind: "interactive_guide", schema_version: "1.1" },
      });
      vi.mocked(getJobs).mockResolvedValue({ jobs: [] });
      vi.mocked(getPersonalization).mockResolvedValue({
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
      });
    },
    ui: (
      <Routes>
        <Route path="/topics/:topicId" element={<RunBoardPage />} />
      </Routes>
    ),
    resources: [
      { label: "/v1/runs/t", calls: runStatusOfT, perNotice: RUN_T },
      { label: "/v1/jobs?topic=t", calls: jobsOfT, perNotice: RUN_T },
      {
        label: "/v1/runs/t/personalization",
        calls: callsWith(getPersonalization, ([t]) => t === "t"),
        perNotice: RUN_T,
      },
    ],
  },
  {
    name: "StageViewerPage",
    path: "/topics/t/stages/draft",
    setup: () => {
      vi.mocked(getStageContent).mockResolvedValue(draftContent);
      vi.mocked(getRunStatus).mockResolvedValue(legacyStatus);
    },
    ui: (
      <Routes>
        <Route path="/topics/:topicId/stages/:stage" element={<StageViewerPage />} />
      </Routes>
    ),
    resources: [
      {
        label: "/v1/runs/t/stages/draft",
        calls: callsWith(getStageContent, ([t, s]) => t === "t" && s === "draft"),
        perNotice: RUN_T,
      },
      { label: "/v1/runs/t", calls: runStatusOfT, perNotice: RUN_T },
    ],
  },
  {
    name: "ModuleRepairControl",
    setup: () => {
      vi.mocked(getRepairModules).mockResolvedValue({
        topic_id: "t",
        modules: [
          { id: "m1", title: "Module one", open_findings: 1, module_level_findings: 0, sections: [] },
        ],
        repair_scope: null,
      });
    },
    ui: <ModuleRepairControl topicId="t" onPrepared={() => {}} />,
    resources: [
      {
        label: "/v1/runs/t/repair/modules",
        calls: callsWith(getRepairModules, ([t]) => t === "t"),
        perNotice: RUN_T,
      },
    ],
  },
  {
    name: "GlobalJobActivity",
    setup: () => {
      vi.mocked(getJobs).mockResolvedValue({ jobs: [] });
      vi.mocked(getTopics).mockResolvedValue({ topics: [] });
    },
    ui: <GlobalJobActivity />,
    resources: [
      { label: "/v1/jobs", calls: allJobs, perNotice: JOBS },
      { label: "/v1/topics", calls: topicsList, perNotice: RUN_ANY_OR_TOPICS },
    ],
  },
  {
    name: "TopicListPage",
    setup: () => {
      vi.mocked(getTopics).mockResolvedValue({ topics: [] });
      vi.mocked(getProfiles).mockResolvedValue({ profiles: [] });
    },
    ui: <TopicListPage />,
    resources: [
      { label: "/v1/topics", calls: topicsList, perNotice: RUN_ANY_OR_TOPICS },
      { label: "/v1/profiles", calls: profilesList, perNotice: TOPICS },
    ],
  },
  {
    name: "NewRunPage",
    path: "/new",
    setup: () => {
      vi.mocked(getProfiles).mockResolvedValue({ profiles: [] });
    },
    ui: <NewRunPage />,
    resources: [{ label: "/v1/profiles", calls: profilesList, perNotice: TOPICS }],
  },
  {
    name: "ProfilesPage",
    path: "/profiles",
    setup: () => {
      vi.mocked(getProfiles).mockResolvedValue({ profiles: [] });
    },
    ui: <ProfilesPage />,
    resources: [{ label: "/v1/profiles", calls: profilesList, perNotice: TOPICS }],
  },
];

let server: ReturnType<typeof createFakeEventServer>;
const random = () => 0.5;

function totalRequests(): number {
  let total = 0;
  for (const [name, value] of Object.entries(client)) {
    if (name === "openEventStream" || !vi.isMockFunction(value)) continue;
    total += (value as Mock).mock.calls.length;
  }
  return total;
}

beforeEach(() => {
  vi.clearAllMocks();
  sessionStorage.clear();
  useFakeClock();
  server = createFakeEventServer();
  // clearAllMocks keeps queued mockImplementationOnce answers; start clean.
  vi.mocked(openEventStream).mockReset();
  vi.mocked(openEventStream).mockImplementation(server.open);
});

afterEach(() => {
  vi.useRealTimers();
  sessionStorage.clear();
  delete document.documentElement.dataset.events;
});

describe.each(SITES.map((site) => [site.name, site] as const))("%s under the events stream", (_name, site) => {
  async function mountUp() {
    site.setup();
    render(
      <EventsProvider random={random}>
        <MemoryRouter initialEntries={[site.path ?? "/"]}>{site.ui}</MemoryRouter>
      </EventsProvider>,
    );
    await flush(0);
    server.current.hello();
    await flush(0);
    for (const resource of site.resources) {
      expect(resource.calls(), `${resource.label} is mounted`).toBeGreaterThanOrEqual(1);
    }
  }

  it("makes no request while connected and idle (65 s, keepalive every 15 s)", async () => {
    await mountUp();
    const before = totalRequests();
    await idleWithKeepalives(server.current, 65_000);
    expect(totalRequests() - before).toBe(0);
  });

  it.each(KINDS)("refetches exactly the resources a %s notice names", async (kind) => {
    await mountUp();
    const before = site.resources.map((resource) => resource.calls());
    const totalBefore = totalRequests();
    server.current.change(NOTICES[kind]);
    await flush(0);
    const deltas = Object.fromEntries(
      site.resources.map((resource, i) => [resource.label, resource.calls() - before[i]]),
    );
    const expected = Object.fromEntries(
      site.resources.map((resource) => [resource.label, resource.perNotice[kind]]),
    );
    expect(deltas).toEqual(expected);
    const expectedTotal = site.resources.reduce((sum, r) => sum + r.perNotice[kind], 0);
    expect(totalRequests() - totalBefore).toBe(expectedTotal);
  });
});
