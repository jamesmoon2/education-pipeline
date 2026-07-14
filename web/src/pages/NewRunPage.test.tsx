import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import type { CatalogProvider, PlanPayload, ProviderAvailability, RunStatus } from "../api/types";
import NewRunPage from "./NewRunPage";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return {
    ApiRequestError: actual.ApiRequestError,
    createTopic: vi.fn(),
    importTopic: vi.fn(),
    getProfiles: vi.fn(),
    attachProfile: vi.fn(),
    postAdvance: vi.fn(),
    getRunStatus: vi.fn(),
    getConfigProviders: vi.fn(),
    getConfigCatalog: vi.fn(),
    getRunPlan: vi.fn(),
    putRunPlan: vi.fn(),
  };
});

import {
  attachProfile,
  createTopic,
  getConfigCatalog,
  getConfigProviders,
  getProfiles,
  getRunPlan,
  getRunStatus,
  importTopic,
  postAdvance,
} from "../api/client";

const providers: ProviderAvailability[] = [
  { id: "claude-code", label: "Claude Code", description: "", executable: true, available: true, reason: null },
];

const catalog: CatalogProvider[] = [
  {
    id: "claude-code",
    label: "Claude Code",
    description: "",
    models: [{ id: "sonnet", label: "Sonnet", description: "", quality: "strong", default_effort: null }],
  },
];

function makePlan(): PlanPayload {
  return {
    provider: "claude-code",
    plan_sha256: "sha-1",
    stages: ["spec", "outline"].map((stage) => ({
      stage,
      provider: "claude-code",
      model: "sonnet",
      effort: null,
      recommendation: "x",
      warning: null,
      source: "default" as const,
    })),
  };
}

function makeRunStatus(topicId: string): RunStatus {
  return {
    topic_id: topicId,
    finalized: false,
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
      action: "write_prompt",
      detail: "Write the spec prompt.",
    },
  };
}

function setupPlanMocks() {
  vi.mocked(getConfigProviders).mockResolvedValue({ providers });
  vi.mocked(getConfigCatalog).mockResolvedValue({ providers: catalog });
  vi.mocked(getRunPlan).mockResolvedValue(makePlan());
}

describe("NewRunPage", () => {
  it("submits the Describe-it form with parsed fields including goals as an array", async () => {
    vi.mocked(getProfiles).mockResolvedValue({ profiles: [] });
    vi.mocked(createTopic).mockResolvedValue({ id: "sys-thinking", title: "Systems Thinking" });
    vi.mocked(postAdvance).mockResolvedValue({ performed: "write_prompt", status: makeRunStatus("sys-thinking") });
    vi.mocked(getRunStatus).mockResolvedValue(makeRunStatus("sys-thinking"));
    setupPlanMocks();

    render(
      <MemoryRouter>
        <NewRunPage />
      </MemoryRouter>,
    );

    await userEvent.type(screen.getByLabelText("Topic id"), "sys-thinking");
    await userEvent.type(screen.getByLabelText("Title"), "Systems Thinking");
    await userEvent.type(
      screen.getByLabelText("Goals (one per line)"),
      "Understand feedback loops\nSee the system, not the event",
    );
    await userEvent.click(screen.getByRole("button", { name: "Create topic" }));

    expect(createTopic).toHaveBeenCalledWith({
      id: "sys-thinking",
      title: "Systems Thinking",
      goals: ["Understand feedback loops", "See the system, not the event"],
    });
  });

  it("submits Paste TOML mode via importTopic", async () => {
    vi.mocked(getProfiles).mockResolvedValue({ profiles: [] });
    vi.mocked(importTopic).mockResolvedValue({ id: "n1", title: "New One" });
    vi.mocked(postAdvance).mockResolvedValue({ performed: "write_prompt", status: makeRunStatus("n1") });
    vi.mocked(getRunStatus).mockResolvedValue(makeRunStatus("n1"));
    setupPlanMocks();

    render(
      <MemoryRouter>
        <NewRunPage />
      </MemoryRouter>,
    );

    await userEvent.click(screen.getByRole("radio", { name: "Paste TOML" }));
    await userEvent.type(screen.getByLabelText("Topic TOML"), 'id = "n1"');
    await userEvent.click(screen.getByRole("button", { name: "Import topic" }));

    expect(importTopic).toHaveBeenCalledWith('id = "n1"');
  });

  it("renders the profile step after topic creation and allows skipping", async () => {
    vi.mocked(getProfiles).mockResolvedValue({ profiles: [{ id: "p1", attached_topic_count: 2 }] });
    vi.mocked(createTopic).mockResolvedValue({ id: "t1", title: "T1" });
    vi.mocked(postAdvance).mockResolvedValue({ performed: "write_prompt", status: makeRunStatus("t1") });
    vi.mocked(getRunStatus).mockResolvedValue(makeRunStatus("t1"));
    setupPlanMocks();

    render(
      <MemoryRouter>
        <NewRunPage />
      </MemoryRouter>,
    );

    await userEvent.type(screen.getByLabelText("Topic id"), "t1");
    await userEvent.type(screen.getByLabelText("Title"), "T1");
    await userEvent.click(screen.getByRole("button", { name: "Create topic" }));

    expect(await screen.findByRole("button", { name: "Skip" })).toBeInTheDocument();
    expect(screen.getByLabelText("Profile")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Skip" }));

    expect(attachProfile).not.toHaveBeenCalled();
    expect(await screen.findByText("Model plan for this run")).toBeInTheDocument();
  });

  it("stays on the profile step and shows the error when run initialization fails", async () => {
    vi.mocked(getProfiles).mockResolvedValue({ profiles: [] });
    vi.mocked(createTopic).mockResolvedValue({ id: "t3", title: "T3" });
    vi.mocked(postAdvance).mockRejectedValue(new Error("run init failed: boom"));
    setupPlanMocks();

    render(
      <MemoryRouter>
        <NewRunPage />
      </MemoryRouter>,
    );

    await userEvent.type(screen.getByLabelText("Topic id"), "t3");
    await userEvent.type(screen.getByLabelText("Title"), "T3");
    await userEvent.click(screen.getByRole("button", { name: "Create topic" }));

    expect(await screen.findByText(/run init failed: boom/)).toBeInTheDocument();
    // The wizard must NOT have advanced to the plan step.
    expect(screen.queryByText("Model plan for this run")).toBeNull();
  });

  it("initializes the run and renders the plan review with a Go to run board link", async () => {
    vi.mocked(getProfiles).mockResolvedValue({ profiles: [] });
    vi.mocked(createTopic).mockResolvedValue({ id: "t2", title: "T2" });
    vi.mocked(postAdvance).mockResolvedValue({ performed: "write_prompt", status: makeRunStatus("t2") });
    vi.mocked(getRunStatus).mockResolvedValue(makeRunStatus("t2"));
    setupPlanMocks();

    render(
      <MemoryRouter>
        <NewRunPage />
      </MemoryRouter>,
    );

    await userEvent.type(screen.getByLabelText("Topic id"), "t2");
    await userEvent.type(screen.getByLabelText("Title"), "T2");
    await userEvent.click(screen.getByRole("button", { name: "Create topic" }));

    // no profiles -> straight through to the plan step
    expect(postAdvance).toHaveBeenCalledWith("t2");
    expect(await screen.findByText("Model plan for this run")).toBeInTheDocument();
    const link = screen.getByRole("link", { name: "Go to run board" });
    expect(link).toHaveAttribute("href", "/topics/t2");
  });
});
