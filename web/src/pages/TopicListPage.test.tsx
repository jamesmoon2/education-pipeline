import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi, beforeEach } from "vitest";
import type { RunStatus, TopicSummary } from "../api/types";
import TopicListPage from "./TopicListPage";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return {
    ApiRequestError: actual.ApiRequestError,
    getTopics: vi.fn(),
    getProfiles: vi.fn(),
    getWorkspace: vi.fn(),
    getConfigProviders: vi.fn(),
    importTopic: vi.fn(),
    importProfile: vi.fn(),
    attachProfile: vi.fn(),
    archiveRun: vi.fn(),
    unarchiveRun: vi.fn(),
    duplicateTopic: vi.fn(),
    revealTarget: vi.fn(),
  };
});

import {
  ApiRequestError,
  archiveRun,
  getConfigProviders,
  getWorkspace,
  attachProfile,
  duplicateTopic,
  getProfiles,
  getTopics,
  importProfile,
  importTopic,
  revealTarget,
  unarchiveRun,
} from "../api/client";

beforeEach(() => {
  vi.clearAllMocks();
  // The library page hosts WelcomePanel; a non-first-run workspace keeps it
  // out of these tests (WelcomePanel has its own suite).
  vi.mocked(getWorkspace).mockResolvedValue({
    path: "/ws",
    counts: { topics: 1, runs: 1, profiles: 0 },
    first_run: false,
  });
  vi.mocked(getConfigProviders).mockResolvedValue({ providers: [] });
});

function makeRun(
  topicId: string,
  action: RunStatus["next_action"]["action"] = "write_prompt",
  finalized = false,
): RunStatus {
  return {
    topic_id: topicId,
    finalized,
    content_contract: { kind: "legacy_markdown" },
    stage_provenance: [],
    validations: {
      draft: { state: "missing", blocking: 0, errors: 0, warnings: 0 },
      final: { state: "missing", blocking: 0, errors: 0, warnings: 0 },
    },
    stages: [],
    next_action: {
      topic_id: topicId,
      stage: "spec",
      action,
      detail: "Next step.",
    },
  };
}

function makeTopic(id: string, overrides: Partial<TopicSummary> = {}): TopicSummary {
  return {
    id,
    title: `Title ${id}`,
    error: null,
    run: makeRun(id),
    archived: false,
    last_activity: "2026-07-15T12:00:00+00:00",
    profile_id: null,
    completion: { stages_approved: 1, stages_total: 5, exported: false },
    ...overrides,
  };
}

function renderPage() {
  return render(
    <MemoryRouter>
      <TopicListPage />
    </MemoryRouter>,
  );
}

const summary = makeTopic("systems-thinking", { title: "Systems Thinking" });

describe("TopicListPage", () => {
  it("renders topics with title, next action, and a run-board link", async () => {
    vi.mocked(getTopics).mockResolvedValue({ topics: [summary] });
    vi.mocked(getProfiles).mockResolvedValue({ profiles: [] });
    renderPage();
    const link = await screen.findByRole("link", { name: "systems-thinking" });
    expect(link).toHaveAttribute("href", "/topics/systems-thinking");
    expect(screen.getByText("Systems Thinking")).toBeInTheDocument();
    expect(screen.getByText("Write the next prompt")).toBeInTheDocument();
  });

  it("explains the row actions with an InfoTip in the Actions header", async () => {
    vi.mocked(getTopics).mockResolvedValue({ topics: [summary] });
    vi.mocked(getProfiles).mockResolvedValue({ profiles: [] });
    renderPage();
    await screen.findByRole("link", { name: "systems-thinking" });
    expect(screen.getByRole("button", { name: "About Actions" })).toBeInTheDocument();
  });

  it("shows completion progress and export state", async () => {
    vi.mocked(getTopics).mockResolvedValue({
      topics: [
        makeTopic("done-course", {
          completion: { stages_approved: 5, stages_total: 5, exported: true },
        }),
      ],
    });
    vi.mocked(getProfiles).mockResolvedValue({ profiles: [] });
    renderPage();
    expect(await screen.findByText(/5\/5/)).toBeInTheDocument();
    expect(screen.getByText(/exported/)).toBeInTheDocument();
  });

  it("shows the empty state", async () => {
    vi.mocked(getTopics).mockResolvedValue({ topics: [] });
    vi.mocked(getProfiles).mockResolvedValue({ profiles: [] });
    renderPage();
    expect(await screen.findByText(/No topics yet/)).toBeInTheDocument();
    const link = screen.getByRole("link", { name: "Create your first course →" });
    expect(link).toHaveAttribute("href", "/new");
  });

  it("imports a topic from pasted TOML", async () => {
    vi.mocked(getTopics).mockResolvedValue({ topics: [] });
    vi.mocked(getProfiles).mockResolvedValue({ profiles: [] });
    vi.mocked(importTopic).mockResolvedValue({ id: "n1", title: "New One" });
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Import topic…" }));
    await userEvent.type(screen.getByLabelText("topic TOML"), 'id = "n1"');
    await userEvent.click(screen.getByRole("button", { name: "Import" }));
    expect(importTopic).toHaveBeenCalledWith('id = "n1"');
  });

  it("imports a profile from pasted TOML", async () => {
    vi.mocked(getTopics).mockResolvedValue({ topics: [summary] });
    vi.mocked(getProfiles).mockResolvedValue({ profiles: [] });
    vi.mocked(importProfile).mockResolvedValue({ id: "p1" });
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Import profile…" }));
    await userEvent.type(screen.getByLabelText("profile TOML"), 'id = "p1"');
    await userEvent.click(screen.getByRole("button", { name: "Import" }));
    expect(importProfile).toHaveBeenCalledWith('id = "p1"');
  });

  it("attaches a profile to a topic", async () => {
    vi.mocked(getTopics).mockResolvedValue({
      topics: [makeTopic("t", { title: "Topic", run: null, last_activity: null, completion: null })],
    });
    vi.mocked(getProfiles).mockResolvedValue({ profiles: [
      { id: "p1", attached_topic_count: 1 },
      { id: "p2", attached_topic_count: 0 },
    ] });
    vi.mocked(attachProfile).mockResolvedValue({
      profile_id: "p1",
      topic_id: "t",
      snapshot_path: "inputs/profile.toml",
    });
    renderPage();
    await userEvent.selectOptions(await screen.findByLabelText("Attach profile to t"), "p1");
    await userEvent.click(screen.getByRole("button", { name: "Attach" }));
    expect(attachProfile).toHaveBeenCalledWith("t", "p1");
  });
});

describe("TopicListPage filtering and sorting", () => {
  const topics = [
    makeTopic("alpha", {
      title: "Alpha Course",
      last_activity: "2026-07-10T00:00:00+00:00",
      profile_id: "learner-a",
    }),
    makeTopic("beta", {
      title: "Beta Course",
      last_activity: "2026-07-14T00:00:00+00:00",
      run: makeRun("beta", "done", true),
      completion: { stages_approved: 5, stages_total: 5, exported: true },
    }),
    makeTopic("gamma", {
      title: "Gamma Course",
      archived: true,
      last_activity: "2026-07-16T00:00:00+00:00",
    }),
    makeTopic("delta", { title: "Delta Course", run: null, last_activity: null, completion: null }),
  ];

  function rowIds(): string[] {
    return screen.getAllByRole("row").slice(1).map((row) => {
      const link = within(row).queryAllByRole("link")[0];
      return link ? link.textContent ?? "" : "";
    });
  }

  beforeEach(() => {
    vi.mocked(getTopics).mockResolvedValue({ topics });
    vi.mocked(getProfiles).mockResolvedValue({ profiles: [] });
  });

  it("hides archived courses by default and shows them on toggle", async () => {
    renderPage();
    await screen.findByRole("link", { name: "alpha" });
    expect(screen.queryByRole("link", { name: "gamma" })).toBeNull();
    await userEvent.click(screen.getByLabelText("Show archived"));
    expect(screen.getByRole("link", { name: "gamma" })).toBeInTheDocument();
    expect(screen.getAllByText(/archived/i).length).toBeGreaterThan(0);
  });

  it("sorts by last activity (newest first) by default, nulls last", async () => {
    renderPage();
    await screen.findByRole("link", { name: "alpha" });
    expect(rowIds()).toEqual(["beta", "alpha", "delta"]);
  });

  it("sorts by title when selected", async () => {
    renderPage();
    await screen.findByRole("link", { name: "alpha" });
    await userEvent.selectOptions(screen.getByLabelText("Sort by"), "title");
    expect(rowIds()).toEqual(["alpha", "beta", "delta"]);
  });

  it("sorts by completion when selected", async () => {
    renderPage();
    await screen.findByRole("link", { name: "alpha" });
    await userEvent.selectOptions(screen.getByLabelText("Sort by"), "completion");
    expect(rowIds()[0]).toBe("beta");
  });

  it("filters by free text over id and title", async () => {
    renderPage();
    await screen.findByRole("link", { name: "alpha" });
    await userEvent.type(screen.getByLabelText("Filter courses"), "beta");
    expect(rowIds()).toEqual(["beta"]);
  });

  it("filters by status", async () => {
    renderPage();
    await screen.findByRole("link", { name: "alpha" });
    await userEvent.selectOptions(screen.getByLabelText("Status"), "finalized");
    expect(rowIds()).toEqual(["beta"]);
    await userEvent.selectOptions(screen.getByLabelText("Status"), "no_run");
    expect(rowIds()).toEqual(["delta"]);
  });

  it("filters by learner", async () => {
    renderPage();
    await screen.findByRole("link", { name: "alpha" });
    await userEvent.selectOptions(screen.getByLabelText("Learner"), "learner-a");
    expect(rowIds()).toEqual(["alpha"]);
  });
});

describe("TopicListPage actions", () => {
  beforeEach(() => {
    vi.mocked(getProfiles).mockResolvedValue({ profiles: [] });
  });

  it("archives a course", async () => {
    vi.mocked(getTopics).mockResolvedValue({ topics: [makeTopic("alpha")] });
    vi.mocked(archiveRun).mockResolvedValue({ topic_id: "alpha", archived: true });
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Archive alpha" }));
    expect(archiveRun).toHaveBeenCalledWith("alpha");
  });

  it("unarchives a visible archived course", async () => {
    vi.mocked(getTopics).mockResolvedValue({
      topics: [makeTopic("gamma", { archived: true })],
    });
    vi.mocked(unarchiveRun).mockResolvedValue({ topic_id: "gamma", archived: false });
    renderPage();
    await userEvent.click(await screen.findByLabelText("Show archived"));
    await userEvent.click(screen.getByRole("button", { name: "Unarchive gamma" }));
    expect(unarchiveRun).toHaveBeenCalledWith("gamma");
  });

  it("offers no archive action for a topic without a run", async () => {
    vi.mocked(getTopics).mockResolvedValue({
      topics: [makeTopic("delta", { run: null, last_activity: null, completion: null })],
    });
    renderPage();
    await screen.findByRole("link", { name: "delta" });
    expect(screen.queryByRole("button", { name: /Archive delta/ })).toBeNull();
  });

  it("duplicates a course from its brief", async () => {
    vi.mocked(getTopics).mockResolvedValue({ topics: [makeTopic("alpha")] });
    vi.mocked(duplicateTopic).mockResolvedValue({ id: "alpha-copy", title: "Alpha" });
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Duplicate alpha" }));
    expect(duplicateTopic).toHaveBeenCalledWith("alpha");
  });

  it("reveals the run directory in the file manager", async () => {
    vi.mocked(getTopics).mockResolvedValue({ topics: [makeTopic("alpha")] });
    vi.mocked(revealTarget).mockResolvedValue({ path: "/ws/runs/alpha" });
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Reveal alpha" }));
    expect(revealTarget).toHaveBeenCalledWith("run", "alpha");
  });

  it("reveals the topic file when there is no run", async () => {
    vi.mocked(getTopics).mockResolvedValue({
      topics: [makeTopic("delta", { run: null, last_activity: null, completion: null })],
    });
    vi.mocked(revealTarget).mockResolvedValue({ path: "/ws/topics/delta.toml" });
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Reveal delta" }));
    expect(revealTarget).toHaveBeenCalledWith("topic", "delta");
  });

  it("falls back to a copyable path when reveal is unsupported", async () => {
    vi.mocked(getTopics).mockResolvedValue({ topics: [makeTopic("alpha")] });
    vi.mocked(revealTarget).mockRejectedValue(
      new ApiRequestError(422, "reveal_unsupported", "opener failed", {
        path: "/ws/runs/alpha",
      }),
    );
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText } });
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Reveal alpha" }));
    expect(await screen.findByText("/ws/runs/alpha")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /copy path/i }));
    expect(writeText).toHaveBeenCalledWith("/ws/runs/alpha");
    vi.unstubAllGlobals();
  });

  it("shows the archived_course recovery with an Unarchive action", async () => {
    vi.mocked(getTopics).mockResolvedValue({
      topics: [makeTopic("gamma", { archived: true })],
    });
    vi.mocked(duplicateTopic).mockRejectedValue(
      new ApiRequestError(409, "archived_course", "course is archived"),
    );
    vi.mocked(unarchiveRun).mockResolvedValue({ topic_id: "gamma", archived: false });
    renderPage();
    await userEvent.click(await screen.findByLabelText("Show archived"));
    await userEvent.click(screen.getByRole("button", { name: "Duplicate gamma" }));
    await userEvent.click(await screen.findByRole("button", { name: "Unarchive" }));
    expect(unarchiveRun).toHaveBeenCalledWith("gamma");
  });
});
