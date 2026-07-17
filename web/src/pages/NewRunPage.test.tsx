import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi, beforeEach } from "vitest";
import type { PlanPayload, RunStatus } from "../api/types";
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
    getConfigPlan: vi.fn(),
    recommendBlueprints: vi.fn(),
  };
});

import {
  attachProfile,
  createTopic,
  getConfigPlan,
  getProfiles,
  getRunStatus,
  importTopic,
  postAdvance,
  recommendBlueprints,
} from "../api/client";

const blueprintsPayload = {
  blueprints: [
    {
      id: "conceptual-foundations",
      title: "Conceptual foundations",
      summary: "Builds a mental model of core concepts.",
      when_to_use: "Choose for understanding ideas.",
      required_interactions: ["knowledge_check", "reflection"],
      default_difficulty: "introductory",
    },
    {
      id: "exam-preparation",
      title: "Exam preparation",
      summary: "Prepares for a specific assessment.",
      when_to_use: "Choose when success is measured by an exam.",
      required_interactions: ["knowledge_check", "worked_reveal"],
      default_difficulty: "intermediate",
    },
  ],
  recommendation: {
    id: "conceptual-foundations",
    rationale: "Recommended Conceptual foundations for a general conceptual topic.",
  },
  topic_blueprint: null,
};

function makePlan(): PlanPayload {
  return {
    provider: "claude-code",
    plan_sha256: "sha-1",
    stages: ["spec", "outline", "draft", "qa", "repair"].map((stage) => ({
      stage,
      provider: "claude-code",
      model: "sonnet",
      effort: null,
      recommendation: "x",
      warning: null,
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

function renderWizard() {
  return render(
    <MemoryRouter initialEntries={["/new"]}>
      <Routes>
        <Route path="/new" element={<NewRunPage />} />
        <Route path="/topics/:topicId" element={<div>RUN BOARD DESTINATION</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getConfigPlan).mockResolvedValue(makePlan());
  vi.mocked(recommendBlueprints).mockResolvedValue(blueprintsPayload);
});

async function renderAtTopicStep() {
  vi.mocked(getProfiles).mockResolvedValue({ profiles: [] });
  renderWizard();
  await screen.findByRole("heading", { name: "Learner" });
  await userEvent.click(screen.getByRole("button", { name: "Continue" }));
}

async function fillTopicStep(id: string, title: string) {
  await userEvent.type(screen.getByLabelText("Topic id"), id);
  await userEvent.type(screen.getByLabelText("Title"), title);
  await userEvent.click(screen.getByRole("button", { name: "Continue" }));
  // The blueprint step sits between topic and plan; accept the default.
  await screen.findByText("Choose a blueprint");
  await userEvent.click(screen.getByRole("button", { name: "Continue" }));
}

describe("NewRunPage wizard structure", () => {
  it("walks learner → topic → plan → confirm and creates on confirm", async () => {
    vi.mocked(getProfiles).mockResolvedValue({ profiles: [{ id: "p1", attached_topic_count: 2 }] });
    vi.mocked(createTopic).mockResolvedValue({ id: "t1", title: "T1" });
    vi.mocked(attachProfile).mockResolvedValue({
      profile_id: "p1",
      topic_id: "t1",
      snapshot_path: "inputs/profile.toml",
    });
    vi.mocked(postAdvance).mockResolvedValue({ performed: "write_prompt", status: makeRunStatus("t1") });
    vi.mocked(getRunStatus).mockResolvedValue(makeRunStatus("t1"));

    renderWizard();

    // Step 1: learner
    expect(await screen.findByRole("heading", { name: "Learner" })).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Learner profile"), "p1");
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));

    // Step 2: topic + brief
    await fillTopicStep("t1", "T1");

    // Step 3: read-only plan review with a Settings link
    expect(await screen.findByRole("heading", { name: "Model plan" })).toBeInTheDocument();
    expect(screen.getAllByText("claude-code").length).toBeGreaterThan(0);
    expect(screen.getByRole("link", { name: /adjust in Settings/i })).toHaveAttribute(
      "href",
      "/settings",
    );
    expect(createTopic).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));

    // Step 4: confirm preview shows the pairing and estimated stages
    expect(await screen.findByText("Confirm")).toBeInTheDocument();
    expect(screen.getByText(/p1/)).toBeInTheDocument();
    expect(screen.getByText(/t1/)).toBeInTheDocument();
    expect(screen.getByText(/spec/)).toBeInTheDocument();
    expect(screen.getByText(/repair/)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Create course" }));

    expect(createTopic).toHaveBeenCalledWith({ id: "t1", title: "T1" });
    expect(attachProfile).toHaveBeenCalledWith("t1", "p1");
    expect(postAdvance).toHaveBeenCalledWith("t1", undefined);
    expect(await screen.findByText("RUN BOARD DESTINATION")).toBeInTheDocument();
  });

  it("skips profile attachment when no learner is selected", async () => {
    vi.mocked(getProfiles).mockResolvedValue({ profiles: [{ id: "p1", attached_topic_count: 0 }] });
    vi.mocked(createTopic).mockResolvedValue({ id: "t2", title: "T2" });
    vi.mocked(postAdvance).mockResolvedValue({ performed: "write_prompt", status: makeRunStatus("t2") });
    vi.mocked(getRunStatus).mockResolvedValue(makeRunStatus("t2"));

    renderWizard();
    await screen.findByRole("heading", { name: "Learner" });
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));
    await fillTopicStep("t2", "T2");
    await userEvent.click(await screen.findByRole("button", { name: "Continue" }));
    await userEvent.click(await screen.findByRole("button", { name: "Create course" }));

    expect(attachProfile).not.toHaveBeenCalled();
    expect(await screen.findByText("RUN BOARD DESTINATION")).toBeInTheDocument();
  });

  it("offers an import link when no profiles exist", async () => {
    vi.mocked(getProfiles).mockResolvedValue({ profiles: [] });
    renderWizard();
    expect(await screen.findByText(/No profiles yet/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /profiles/i })).toHaveAttribute(
      "href",
      "/profiles",
    );
  });

  it("parses goals into an array in Describe-it mode", async () => {
    vi.mocked(getProfiles).mockResolvedValue({ profiles: [] });
    vi.mocked(createTopic).mockResolvedValue({ id: "sys", title: "Systems" });
    vi.mocked(postAdvance).mockResolvedValue({ performed: "write_prompt", status: makeRunStatus("sys") });
    vi.mocked(getRunStatus).mockResolvedValue(makeRunStatus("sys"));

    renderWizard();
    await screen.findByRole("heading", { name: "Learner" });
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));
    await userEvent.type(screen.getByLabelText("Topic id"), "sys");
    await userEvent.type(screen.getByLabelText("Title"), "Systems");
    await userEvent.type(
      screen.getByLabelText("Goals (one per line)"),
      "Understand feedback loops\nSee the system, not the event",
    );
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));
    await screen.findByText("Choose a blueprint");
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));
    await userEvent.click(await screen.findByRole("button", { name: "Continue" }));
    await userEvent.click(await screen.findByRole("button", { name: "Create course" }));

    expect(createTopic).toHaveBeenCalledWith({
      id: "sys",
      title: "Systems",
      goals: ["Understand feedback loops", "See the system, not the event"],
    });
  });

  it("imports pasted TOML on create", async () => {
    vi.mocked(getProfiles).mockResolvedValue({ profiles: [] });
    vi.mocked(importTopic).mockResolvedValue({ id: "n1", title: "New One" });
    vi.mocked(postAdvance).mockResolvedValue({ performed: "write_prompt", status: makeRunStatus("n1") });
    vi.mocked(getRunStatus).mockResolvedValue(makeRunStatus("n1"));

    renderWizard();
    await screen.findByRole("heading", { name: "Learner" });
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));
    await userEvent.click(screen.getByRole("radio", { name: "Paste TOML" }));
    await userEvent.type(screen.getByLabelText("Topic TOML"), 'id = "n1"');
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));
    await screen.findByText("Choose a blueprint");
    expect(recommendBlueprints).toHaveBeenCalledWith({ toml: 'id = "n1"' });
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));
    await userEvent.click(await screen.findByRole("button", { name: "Continue" }));
    await userEvent.click(await screen.findByRole("button", { name: "Create course" }));

    expect(importTopic).toHaveBeenCalledWith('id = "n1"');
    expect(createTopic).not.toHaveBeenCalled();
    expect(await screen.findByText("RUN BOARD DESTINATION")).toBeInTheDocument();
  });

  it("stays on confirm and surfaces the error when run initialization fails", async () => {
    vi.mocked(getProfiles).mockResolvedValue({ profiles: [] });
    vi.mocked(createTopic).mockResolvedValue({ id: "t3", title: "T3" });
    vi.mocked(postAdvance).mockRejectedValue(new Error("run init failed: boom"));

    renderWizard();
    await screen.findByRole("heading", { name: "Learner" });
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));
    await fillTopicStep("t3", "T3");
    await userEvent.click(await screen.findByRole("button", { name: "Continue" }));
    await userEvent.click(await screen.findByRole("button", { name: "Create course" }));

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.queryByText("RUN BOARD DESTINATION")).toBeNull();
    // Retrying must not re-create the already-created topic.
    vi.mocked(postAdvance).mockResolvedValue({ performed: "write_prompt", status: makeRunStatus("t3") });
    await userEvent.click(screen.getByRole("button", { name: "Create course" }));
    expect(await screen.findByText("RUN BOARD DESTINATION")).toBeInTheDocument();
    expect(createTopic).toHaveBeenCalledTimes(1);
  });

  it("supports going back to earlier steps without losing input", async () => {
    vi.mocked(getProfiles).mockResolvedValue({ profiles: [] });
    renderWizard();
    await screen.findByRole("heading", { name: "Learner" });
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));
    await userEvent.type(screen.getByLabelText("Topic id"), "keep-me");
    await userEvent.click(screen.getByRole("button", { name: "Back" }));
    expect(await screen.findByText(/No profiles yet/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(screen.getByLabelText("Topic id")).toHaveValue("keep-me");
  });

  it("preselects the recommendation with its rationale on the blueprint step", async () => {
    vi.mocked(getProfiles).mockResolvedValue({ profiles: [] });
    renderWizard();
    await screen.findByRole("heading", { name: "Learner" });
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));
    await userEvent.type(screen.getByLabelText("Topic id"), "b1");
    await userEvent.type(screen.getByLabelText("Title"), "B1");
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));

    await screen.findByText("Choose a blueprint");
    expect(recommendBlueprints).toHaveBeenCalledWith({ id: "b1", title: "B1" });
    expect(
      screen.getByRole("radio", { name: /Conceptual foundations/ }),
    ).toBeChecked();
    expect(
      screen.getByText(/general conceptual topic/),
    ).toBeInTheDocument();
  });

  it("passes a blueprint override to the run only when the user changes the selection", async () => {
    vi.mocked(getProfiles).mockResolvedValue({ profiles: [] });
    vi.mocked(createTopic).mockResolvedValue({ id: "b2", title: "B2" });
    vi.mocked(postAdvance).mockResolvedValue({ performed: "write_prompt", status: makeRunStatus("b2") });
    vi.mocked(getRunStatus).mockResolvedValue(makeRunStatus("b2"));

    renderWizard();
    await screen.findByRole("heading", { name: "Learner" });
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));
    await userEvent.type(screen.getByLabelText("Topic id"), "b2");
    await userEvent.type(screen.getByLabelText("Title"), "B2");
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));

    await screen.findByText("Choose a blueprint");
    await userEvent.click(screen.getByRole("radio", { name: /Exam preparation/ }));
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));
    await userEvent.click(await screen.findByRole("button", { name: "Continue" }));

    // The confirm preview names the chosen blueprint.
    expect(await screen.findByText("Confirm")).toBeInTheDocument();
    expect(screen.getByText("exam-preparation")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Create course" }));

    expect(postAdvance).toHaveBeenCalledWith("b2", { blueprint: "exam-preparation" });
  });

  it("sends the optional time budget with the topic", async () => {
    vi.mocked(getProfiles).mockResolvedValue({ profiles: [] });
    vi.mocked(createTopic).mockResolvedValue({ id: "tb", title: "TB" });
    vi.mocked(postAdvance).mockResolvedValue({ performed: "write_prompt", status: makeRunStatus("tb") });
    vi.mocked(getRunStatus).mockResolvedValue(makeRunStatus("tb"));

    renderWizard();
    await screen.findByRole("heading", { name: "Learner" });
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));
    await userEvent.type(screen.getByLabelText("Topic id"), "tb");
    await userEvent.type(screen.getByLabelText("Title"), "TB");
    await userEvent.type(screen.getByLabelText("Time budget (minutes, optional)"), "90");
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));
    await screen.findByText("Choose a blueprint");
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));
    await userEvent.click(await screen.findByRole("button", { name: "Continue" }));
    await userEvent.click(await screen.findByRole("button", { name: "Create course" }));

    expect(createTopic).toHaveBeenCalledWith({
      id: "tb",
      title: "TB",
      time_budget_minutes: 90,
    });
  });

  it("shows help for the brief and topic id", async () => {
    const user = userEvent.setup();
    await renderAtTopicStep();
    await user.click(screen.getByRole("button", { name: "About Topic id" }));
    expect(screen.getByRole("tooltip")).toHaveTextContent(/intro-to-sql/);
    expect(screen.getByLabelText("Topic id")).toHaveAttribute(
      "placeholder",
      "intro-to-sql",
    );
  });

  it("rejects a malformed topic id before continuing", async () => {
    const user = userEvent.setup();
    await renderAtTopicStep();
    await user.type(screen.getByLabelText("Topic id"), "bad id!");
    await user.type(screen.getByLabelText("Title"), "A Title");
    expect(
      screen.getByText(/letters, digits, dots, dashes/i),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Continue" })).toBeDisabled();
    await user.clear(screen.getByLabelText("Topic id"));
    await user.type(screen.getByLabelText("Topic id"), "intro-to-sql");
    expect(screen.getByRole("button", { name: "Continue" })).toBeEnabled();
  });

  it("proceeds past an unavailable blueprint registry without blocking creation", async () => {
    vi.mocked(getProfiles).mockResolvedValue({ profiles: [] });
    vi.mocked(recommendBlueprints).mockRejectedValue(new Error("registry down"));
    vi.mocked(createTopic).mockResolvedValue({ id: "b3", title: "B3" });
    vi.mocked(postAdvance).mockResolvedValue({ performed: "write_prompt", status: makeRunStatus("b3") });
    vi.mocked(getRunStatus).mockResolvedValue(makeRunStatus("b3"));

    renderWizard();
    await screen.findByRole("heading", { name: "Learner" });
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));
    await userEvent.type(screen.getByLabelText("Topic id"), "b3");
    await userEvent.type(screen.getByLabelText("Title"), "B3");
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));

    expect(await screen.findByText("Choose a blueprint")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(/unavailable/i);
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));
    await userEvent.click(await screen.findByRole("button", { name: "Continue" }));
    await userEvent.click(await screen.findByRole("button", { name: "Create course" }));

    expect(postAdvance).toHaveBeenCalledWith("b3", undefined);
  });
});
