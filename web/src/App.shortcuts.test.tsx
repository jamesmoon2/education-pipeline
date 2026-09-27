import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { NextAction, RunStatus, StageContent, TopicSummary } from "./api/types";
import App from "./App";

// T61 keyboard shortcuts, end to end inside the cockpit shell: the key map
// (decision 4), the conflict rules (5), two-key approve (6), the WCAG 2.1.4
// off switch and the overlay dialog (7), all wired through the App-level
// provider (8).

// Every client function is a mock that never settles unless a test says
// otherwise, so panels this suite does not care about simply stay loading.
vi.mock("./api/client", async () => {
  const actual = await vi.importActual<typeof import("./api/client")>("./api/client");
  const mocked: Record<string, unknown> = { ...actual };
  for (const [name, value] of Object.entries(actual)) {
    if (typeof value === "function" && name !== "ApiRequestError") {
      mocked[name] = vi.fn(() => new Promise(() => {}));
    }
  }
  return mocked;
});

import {
  getConfigProviders,
  getJobs,
  getProfiles,
  getRunStatus,
  getStageContent,
  getTopics,
  getWorkspace,
  postApprove,
  postContinue,
} from "./api/client";

const STAGES = ["spec", "outline", "draft", "qa", "factcheck", "repair"];

function makeRun(topicId: string, action: NextAction["action"], stage: string | null): RunStatus {
  return {
    topic_id: topicId,
    finalized: false,
    content_contract: { kind: "legacy_markdown" },
    stage_provenance: [],
    validations: {
      draft: { state: "missing", blocking: 0, errors: 0, warnings: 0 },
      final: { state: "missing", blocking: 0, errors: 0, warnings: 0 },
    },
    stages: STAGES.map((name) => ({
      stage: name,
      state: name === "spec" ? "approved" : "pending",
      prompt_written: name === "spec",
      response_ingested: name === "spec",
      approved: name === "spec",
    })),
    next_action: { topic_id: topicId, stage, action, detail: `Next for ${topicId}.` },
  };
}

function makeTopic(
  id: string,
  next: { action: NextAction["action"]; stage: string | null } | null,
  lastActivity: string | null,
  overrides: Partial<TopicSummary> = {},
): TopicSummary {
  return {
    id,
    title: `Title ${id}`,
    error: null,
    run: next ? makeRun(id, next.action, next.stage) : null,
    archived: false,
    last_activity: lastActivity,
    profile_id: null,
    completion: null,
    ...overrides,
  };
}

function content(topicId: string, stage: string): StageContent {
  return {
    topic_id: topicId,
    stage,
    prompt: `# ${stage} prompt`,
    response: `${stage} response body`,
    approved: null,
    response_sha256: `sha-${topicId}-${stage}`,
    content_type: "text/markdown",
  };
}

// Library order (newest activity first) matches list order here: a, b, c.
const LIBRARY: TopicSummary[] = [
  makeTopic("a", { action: "approve", stage: "spec" }, "2026-09-27T10:00:00Z"),
  makeTopic("b", { action: "approve", stage: "draft" }, "2026-09-27T09:00:00Z"),
  makeTopic("c", { action: "save_response", stage: "outline" }, "2026-09-27T08:00:00Z"),
];

/** Each topic's run, keyed by id; tests override entries they need. */
let runs: Record<string, RunStatus>;

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location">{location.pathname + location.search}</div>;
}

const currentLocation = () => screen.getByTestId("location").textContent;

function renderApp(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
      <LocationProbe />
    </MemoryRouter>,
  );
}

function blur() {
  (document.activeElement as HTMLElement | null)?.blur();
}

const filterBox = () => screen.findByRole("searchbox", { name: "Filter courses" });

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  runs = {
    a: makeRun("a", "approve", "spec"),
    b: makeRun("b", "approve", "draft"),
    c: makeRun("c", "save_response", "outline"),
    t: makeRun("t", "approve", "outline"),
  };
  vi.mocked(getTopics).mockResolvedValue({ topics: LIBRARY });
  vi.mocked(getProfiles).mockResolvedValue({ profiles: [] });
  vi.mocked(getWorkspace).mockResolvedValue({
    path: "/ws",
    counts: { topics: 3, runs: 3, profiles: 0 },
    first_run: false,
  });
  vi.mocked(getConfigProviders).mockResolvedValue({ providers: [] });
  vi.mocked(getJobs).mockResolvedValue({ jobs: [] });
  vi.mocked(getRunStatus).mockImplementation(async (topicId: string) => runs[topicId]);
  vi.mocked(getStageContent).mockImplementation(async (topicId: string, stage: string) =>
    content(topicId, stage),
  );
});

afterEach(() => {
  blur();
});

describe("the shortcuts overlay", () => {
  it("? opens a modal dialog listing every key; Escape closes it and restores focus", async () => {
    const user = userEvent.setup();
    renderApp("/");
    const importTopic = await screen.findByRole("button", { name: "Import topic…" });
    importTopic.focus();

    await user.keyboard("?");

    const dialog = await screen.findByRole("dialog", { name: "Keyboard shortcuts" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    const keys = Array.from(dialog.querySelectorAll("kbd")).map((kbd) => kbd.textContent?.trim());
    for (const key of ["?", "/", "n", "r", "a", "Escape"]) {
      expect(keys).toContain(key);
    }
    // Focus moves into the dialog on open.
    expect(dialog).toContainElement(document.activeElement as HTMLElement);

    await user.keyboard("{Escape}");

    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "Keyboard shortcuts" })).not.toBeInTheDocument(),
    );
    expect(importTopic).toHaveFocus();
  });

  it("the Single-key shortcuts switch turns every key off and is stored as ep.shortcuts=off", async () => {
    const user = userEvent.setup();
    renderApp("/");
    const filter = await filterBox();
    blur();

    await user.keyboard("?");
    const dialog = await screen.findByRole("dialog", { name: "Keyboard shortcuts" });
    const toggle = within(dialog).getByRole("checkbox", { name: "Single-key shortcuts" });
    expect(toggle).toBeChecked();

    await user.click(toggle);

    expect(toggle).not.toBeChecked();
    expect(localStorage.getItem("ep.shortcuts")).toBe("off");

    // Escape still closes the dialog, even with the keys switched off.
    await user.keyboard("{Escape}");
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "Keyboard shortcuts" })).not.toBeInTheDocument(),
    );

    blur();
    await user.keyboard("?");
    expect(screen.queryByRole("dialog", { name: "Keyboard shortcuts" })).not.toBeInTheDocument();
    await user.keyboard("/");
    expect(filter).not.toHaveFocus();
    await user.keyboard("r");
    expect(currentLocation()).toBe("/");
  });

  it("the rail's Keyboard shortcuts button opens the overlay even when keys are off", async () => {
    localStorage.setItem("ep.shortcuts", "off");
    const user = userEvent.setup();
    renderApp("/");
    const filter = await filterBox();
    blur();

    await user.keyboard("?");
    expect(screen.queryByRole("dialog", { name: "Keyboard shortcuts" })).not.toBeInTheDocument();
    await user.keyboard("/");
    expect(filter).not.toHaveFocus();

    const railButton = within(screen.getByRole("banner")).getByRole("button", {
      name: "Keyboard shortcuts",
    });
    await user.click(railButton);

    const dialog = await screen.findByRole("dialog", { name: "Keyboard shortcuts" });
    const toggle = within(dialog).getByRole("checkbox", { name: "Single-key shortcuts" });
    expect(toggle).not.toBeChecked();

    await user.click(toggle);

    expect(toggle).toBeChecked();
    expect(localStorage.getItem("ep.shortcuts")).not.toBe("off");

    await user.keyboard("{Escape}");
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "Keyboard shortcuts" })).not.toBeInTheDocument(),
    );
    expect(railButton).toHaveFocus();

    // Back on: ? works again.
    await user.keyboard("?");
    expect(await screen.findByRole("dialog", { name: "Keyboard shortcuts" })).toBeInTheDocument();
  });

  it("does nothing while another modal dialog is open", async () => {
    const user = userEvent.setup();
    renderApp("/");
    const filter = await filterBox();
    const other = document.createElement("div");
    other.setAttribute("role", "dialog");
    other.setAttribute("aria-modal", "true");
    other.setAttribute("aria-label", "Some other dialog");
    document.body.appendChild(other);
    try {
      blur();
      await user.keyboard("?");
      expect(screen.queryByRole("dialog", { name: "Keyboard shortcuts" })).not.toBeInTheDocument();
      await user.keyboard("/");
      expect(filter).not.toHaveFocus();
    } finally {
      other.remove();
    }

    // Control: with the other dialog gone, the same key works.
    blur();
    await user.keyboard("?");
    expect(await screen.findByRole("dialog", { name: "Keyboard shortcuts" })).toBeInTheDocument();
  });
});

describe("/ — focus the library filter", () => {
  it("focuses Filter courses on the library and claims the key", async () => {
    renderApp("/");
    const filter = await filterBox();
    blur();

    const notPrevented = fireEvent.keyDown(document.body, { key: "/" });

    expect(notPrevented).toBe(false); // also stops Firefox quick-find
    expect(filter).toHaveFocus();
  });

  it("types nothing into the filter it just focused", async () => {
    const user = userEvent.setup();
    renderApp("/");
    const filter = await filterBox();
    blur();

    await user.keyboard("/");

    expect(filter).toHaveFocus();
    expect(filter).toHaveValue("");
  });

  it("navigates to the library first from any other page, then focuses the filter", async () => {
    const user = userEvent.setup();
    renderApp("/topics/c");
    await screen.findByRole("heading", { name: "c" });
    blur();

    await user.keyboard("/");

    await waitFor(() => expect(currentLocation()).toBe("/"));
    await waitFor(async () => expect(await filterBox()).toHaveFocus());
  });
});

describe("typing never triggers shortcuts", () => {
  it("n, a, r, / and ? typed into the filter only type", async () => {
    const user = userEvent.setup();
    renderApp("/");
    const filter = await filterBox();

    await user.click(filter);
    await user.keyboard("nar/?");

    expect(filter).toHaveValue("nar/?");
    expect(currentLocation()).toBe("/");
    expect(screen.queryByRole("dialog", { name: "Keyboard shortcuts" })).not.toBeInTheDocument();
    expect(screen.queryByText("No course needs review")).not.toBeInTheDocument();

    // Control: outside the field the very same key acts.
    blur();
    await user.keyboard("?");
    expect(await screen.findByRole("dialog", { name: "Keyboard shortcuts" })).toBeInTheDocument();
  });

  it("n, a, r, / and ? typed into a textarea only type", async () => {
    const user = userEvent.setup();
    runs.c = makeRun("c", "save_response", "outline");
    renderApp("/topics/c");
    await user.click(await screen.findByRole("button", { name: "Paste response…" }));
    const textarea = screen.getByLabelText("Response for outline");

    await user.click(textarea);
    await user.keyboard("nar/?");

    expect(textarea).toHaveValue("nar/?");
    expect(currentLocation()).toBe("/topics/c");
    expect(screen.queryByRole("dialog", { name: "Keyboard shortcuts" })).not.toBeInTheDocument();

    // Control: outside the field, `n` does open the next stage.
    blur();
    await user.keyboard("n");
    await waitFor(() => expect(currentLocation()).toBe("/topics/c/stages/outline"));
  });
});

describe("a — focus approve, never approve (decision 6)", () => {
  it("on the run board, moves focus to the primary approve button without approving", async () => {
    const user = userEvent.setup();
    renderApp("/topics/t");
    const approve = await screen.findByRole("button", { name: "Approve outline & continue" });
    blur();

    await user.keyboard("a");

    expect(approve).toHaveFocus();
    expect(postApprove).not.toHaveBeenCalled();
    expect(postContinue).not.toHaveBeenCalled();
  });

  it("on the stage viewer, moves focus to Approve {stage}; Enter then approves", async () => {
    const user = userEvent.setup();
    vi.mocked(postApprove).mockResolvedValue({
      topic_id: "t",
      stage: "outline",
      approved_path: "/ws/runs/t/approved/outline.approved.md",
      status: makeRun("t", "write_prompt", "draft"),
    });
    renderApp("/topics/t/stages/outline?tab=response");
    const approve = await screen.findByRole("button", { name: "Approve outline" });
    blur();

    await user.keyboard("a");

    expect(approve).toHaveFocus();
    expect(postApprove).not.toHaveBeenCalled();

    // The second key of the two-key gate is the button's own Enter.
    await user.keyboard("{Enter}");

    await waitFor(() => expect(postApprove).toHaveBeenCalledTimes(1));
    expect(postApprove).toHaveBeenCalledWith("t", "outline");
    expect(postContinue).not.toHaveBeenCalled();
  });

  it("leaves focus alone on a page with nothing to approve", async () => {
    const user = userEvent.setup();
    renderApp("/topics/c");
    const runWithProvider = await screen.findByRole("button", { name: "Run with provider" });
    runWithProvider.focus();

    await user.keyboard("a");

    expect(runWithProvider).toHaveFocus();
    expect(postApprove).not.toHaveBeenCalled();

    // Control: the page's shortcuts are live; there is just nothing to approve.
    await user.keyboard("n");
    await waitFor(() => expect(currentLocation()).toBe("/topics/c/stages/outline"));
  });
});

describe("n — open the run's next stage", () => {
  it("from the run board", async () => {
    const user = userEvent.setup();
    renderApp("/topics/c");
    await screen.findByRole("heading", { name: "c" });
    blur();

    await user.keyboard("n");

    await waitFor(() => expect(currentLocation()).toBe("/topics/c/stages/outline"));
  });

  it("from the stage viewer", async () => {
    const user = userEvent.setup();
    renderApp("/topics/c/stages/spec");
    await screen.findByRole("heading", { name: "c / spec" });
    // "Rerun with provider…" renders only once the run status (which names
    // the next stage) has loaded.
    await screen.findByRole("button", { name: "Rerun with provider…" });
    blur();

    await user.keyboard("n");

    await waitFor(() => expect(currentLocation()).toBe("/topics/c/stages/outline"));
  });

  it("does nothing on the library", async () => {
    const user = userEvent.setup();
    renderApp("/");
    await filterBox();
    blur();

    await user.keyboard("n");

    expect(currentLocation()).toBe("/");
    // Control: the library's own key, `/`, does act here.
    const filter = await filterBox();
    expect(filter).not.toHaveFocus();
    await user.keyboard("/");
    expect(filter).toHaveFocus();
  });
});

describe("r — the next course needing review", () => {
  it("from the library, opens the first course needing review on its approve deep link", async () => {
    const user = userEvent.setup();
    renderApp("/");
    await filterBox();
    blur();

    await user.keyboard("r");

    await waitFor(() => expect(currentLocation()).toBe("/topics/a/stages/spec?tab=response"));
  });

  it("starts after the current course and wraps", async () => {
    const user = userEvent.setup();
    renderApp("/topics/b/stages/draft?tab=response");
    await screen.findByRole("heading", { name: "b / draft" });
    blur();

    await user.keyboard("r");

    // b is current; c needs nothing; the search wraps to a.
    await waitFor(() => expect(currentLocation()).toBe("/topics/a/stages/spec?tab=response"));
  });

  it("follows the library's default order (newest activity first), not the API's", async () => {
    const user = userEvent.setup();
    vi.mocked(getTopics).mockResolvedValue({
      topics: [
        makeTopic("older", { action: "approve", stage: "spec" }, "2026-09-01T00:00:00Z"),
        makeTopic("newer", { action: "approve", stage: "qa" }, "2026-09-20T00:00:00Z"),
      ],
    });
    renderApp("/");
    await filterBox();
    blur();

    await user.keyboard("r");

    await waitFor(() => expect(currentLocation()).toBe("/topics/newer/stages/qa?tab=response"));
  });

  it("announces politely when no course needs review", async () => {
    const user = userEvent.setup();
    vi.mocked(getTopics).mockResolvedValue({
      topics: [makeTopic("c", { action: "save_response", stage: "outline" }, null)],
    });
    renderApp("/");
    await filterBox();
    blur();

    await user.keyboard("r");

    const message = await screen.findByText("No course needs review");
    expect(message.closest('[aria-live="polite"], [role="status"]')).not.toBeNull();
    expect(currentLocation()).toBe("/");
  });
});
