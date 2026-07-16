import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { CatalogProvider, PlanPayload, ProviderAvailability } from "../api/types";
import RunPlanPanel from "./RunPlanPanel";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return {
    ApiRequestError: actual.ApiRequestError,
    getConfigProviders: vi.fn(),
    getConfigCatalog: vi.fn(),
    getRunPlan: vi.fn(),
    putRunPlan: vi.fn(),
  };
});

import { getConfigCatalog, getConfigProviders, getRunPlan, putRunPlan } from "../api/client";

const providers: ProviderAvailability[] = [
  { id: "claude-code", label: "Claude Code", description: "", executable: true, available: true, reason: null },
  { id: "codex", label: "Codex", description: "", executable: true, available: true, reason: null },
];

const catalog: CatalogProvider[] = [
  {
    id: "claude-code",
    label: "Claude Code",
    description: "",
    models: [{ id: "sonnet", label: "Sonnet", description: "", quality: "strong", default_effort: null }],
  },
  {
    id: "codex",
    label: "Codex",
    description: "",
    models: [{ id: "gpt-5.4", label: "GPT-5.4", description: "", quality: "premium", default_effort: null }],
  },
];

const STAGES = ["profile", "spec", "outline", "draft", "qa", "repair", "finalize", "export"];

function makePlan(overrides: Partial<Record<string, unknown>> = {}): PlanPayload {
  return {
    provider: "claude-code",
    plan_sha256: "sha-1",
    stages: STAGES.map((stage) => ({
      stage,
      provider: stage === "draft" ? "codex" : "claude-code",
      model: stage === "finalize" || stage === "export" ? null : stage === "draft" ? "gpt-5.4" : "sonnet",
      effort: stage === "draft" ? "high" : null,
      recommendation: "x",
      warning: null,
      source: stage === "draft" ? ("override" as const) : ("default" as const),
      command: stage === "draft" ? ["codex", "exec", "--model", "gpt-5.4"] : null,
    })),
    ...overrides,
  };
}

function setup(plan: PlanPayload = makePlan(), nextStage: string | null = "draft") {
  vi.mocked(getConfigProviders).mockResolvedValue({ providers });
  vi.mocked(getConfigCatalog).mockResolvedValue({ providers: catalog });
  vi.mocked(getRunPlan).mockResolvedValue(plan);
  return render(<RunPlanPanel topicId="t" nextStage={nextStage} />);
}

describe("RunPlanPanel", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("renders rows from getRunPlan and tags overridden rows", async () => {
    setup();
    expect(await screen.findByLabelText("Provider for outline")).toBeInTheDocument();
    const draftRow = screen.getByLabelText("Provider for draft").closest(".run-plan-row")!;
    expect(draftRow).toHaveTextContent(/overridden/i);
    const outlineRow = screen.getByLabelText("Provider for outline").closest(".run-plan-row")!;
    expect(outlineRow).not.toHaveTextContent(/overridden/i);
  });

  it("fires putRunPlan with the stage override when a row's model changes", async () => {
    setup();
    await screen.findByLabelText("Model for outline");
    vi.mocked(putRunPlan).mockResolvedValue(makePlan());

    await userEvent.selectOptions(screen.getByLabelText("Model for outline"), "sonnet");

    expect(putRunPlan).toHaveBeenCalledWith("t", {
      outline: { provider: "claude-code", model: "sonnet", effort: undefined },
    });
  });

  it("fires putRunPlan with a null override when Use recommended is clicked", async () => {
    setup();
    await screen.findByLabelText("Provider for draft");
    vi.mocked(putRunPlan).mockResolvedValue(makePlan());

    const draftRow = screen.getByLabelText("Provider for draft").closest(".plan-stage-row")!;
    await userEvent.click(within(draftRow as HTMLElement).getByRole("button", { name: "Use recommended" }));

    expect(putRunPlan).toHaveBeenCalledWith("t", { draft: null });
  });

  it("renders the next stage's command preview as argv", async () => {
    setup();
    expect(await screen.findByText(/Next: draft/)).toBeInTheDocument();
    expect(screen.getByText(/codex \/ gpt-5\.4 \/ high/)).toBeInTheDocument();
    const code = screen.getByText("codex exec --model gpt-5.4");
    expect(code.tagName.toLowerCase()).toBe("code");
  });

  it("shows the manual message when the next stage's provider is manual", async () => {
    const plan = makePlan();
    const draft = plan.stages.find((s) => s.stage === "draft")!;
    draft.provider = "manual";
    draft.command = null;
    setup(plan);
    const heading = await screen.findByText(/Next: draft/);
    const nextLine = heading.closest("p")!;
    expect(nextLine).toHaveTextContent("you run the prompt yourself");
    // "manual" must appear exactly once in the next-stage line, not doubled
    // (describeEffective already renders the provider name "manual").
    const occurrences = nextLine.textContent!.match(/manual/g) ?? [];
    expect(occurrences).toHaveLength(1);
  });

  it("renders a local-stage line (not provider/model text) when the next stage is finalize", async () => {
    const plan = makePlan();
    setup(plan, "finalize");
    const heading = await screen.findByText(/Next: finalize/);
    const nextLine = heading.closest("p")!;
    expect(nextLine).toHaveTextContent("Next: finalize — runs locally, no model");
    expect(nextLine).not.toHaveTextContent("claude-code");
  });
});
