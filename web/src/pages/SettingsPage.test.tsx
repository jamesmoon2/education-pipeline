import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { CatalogPreset, CatalogProvider, PlanPayload, ProviderAvailability } from "../api/types";
import SettingsPage from "./SettingsPage";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return {
    ApiRequestError: actual.ApiRequestError,
    getConfigProviders: vi.fn(),
    getConfigCatalog: vi.fn(),
    getConfigPlan: vi.fn(),
    putConfigPlan: vi.fn(),
  };
});

import {
  ApiRequestError,
  getConfigCatalog,
  getConfigPlan,
  getConfigProviders,
  putConfigPlan,
} from "../api/client";

const providers: ProviderAvailability[] = [
  { id: "claude-code", label: "Claude Code", description: "", executable: true, available: true, reason: null },
  {
    id: "codex",
    label: "Codex",
    description: "",
    executable: true,
    available: false,
    reason: "codex CLI not found on PATH",
  },
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
    models: [{ id: "gpt", label: "GPT", description: "", quality: "premium", default_effort: null }],
  },
];

const presets: CatalogPreset[] = [
  {
    id: "balanced",
    label: "Balanced",
    description: "Deep design where it counts.",
    stages: {
      "claude-code": {
        profile: { model: "sonnet", effort: "medium" },
        spec: { model: "sonnet", effort: "high" },
        outline: { model: "sonnet", effort: "high" },
        draft: { model: "sonnet", effort: "medium" },
        qa: { model: "sonnet", effort: "medium" },
        repair: { model: "sonnet", effort: "medium" },
        audit: { model: "sonnet", effort: "medium" },
      },
      codex: {
        profile: { model: "gpt", effort: "medium" },
        spec: { model: "gpt", effort: "high" },
        outline: { model: "gpt", effort: "high" },
        draft: { model: "gpt", effort: "medium" },
        qa: { model: "gpt", effort: "medium" },
        repair: { model: "gpt", effort: "medium" },
        audit: { model: "gpt", effort: "medium" },
      },
    },
  },
];

const STAGES = ["profile", "spec", "outline", "draft", "qa", "repair", "audit", "finalize", "export"];

function makePlan(overrides: Partial<Record<string, unknown>> = {}): PlanPayload {
  return {
    provider: "claude-code",
    plan_sha256: "sha-1",
    stages: STAGES.map((stage) => ({
      stage,
      provider: "claude-code",
      model: stage === "finalize" || stage === "export" ? null : "sonnet",
      effort: null,
      recommendation: "x",
      warning: stage === "qa" ? "claude-code sonnet is a weak choice for qa" : null,
      source: "default" as const,
    })),
    ...overrides,
  };
}

function setup(plan: PlanPayload = makePlan()) {
  vi.mocked(getConfigProviders).mockResolvedValue({ providers });
  vi.mocked(getConfigCatalog).mockResolvedValue({ providers: catalog, presets });
  vi.mocked(getConfigPlan).mockResolvedValue(plan);
  return render(<SettingsPage />);
}

describe("SettingsPage", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("renders a row per model-powered stage and static rows for finalize/export", async () => {
    setup();
    expect(await screen.findByLabelText("Provider for outline")).toBeInTheDocument();
    expect(screen.getByLabelText("Provider for spec")).toBeInTheDocument();
    expect(screen.getByLabelText("Provider for audit")).toBeInTheDocument();
    expect(screen.getByText("finalize")).toBeInTheDocument();
    expect(screen.getByText("export")).toBeInTheDocument();
    expect(screen.queryByLabelText("Provider for finalize")).toBeNull();
    expect(screen.queryByLabelText("Provider for export")).toBeNull();
  });

  it("shows the unavailable provider's reason in the availability list", async () => {
    setup();
    await screen.findByLabelText("Provider for outline");
    expect(screen.getByText(/codex CLI not found on PATH/)).toBeInTheDocument();
  });

  it("renders the weak-configuration warning for a stage whose payload carries one", async () => {
    setup();
    await screen.findByLabelText("Provider for outline");
    expect(screen.getByRole("alert")).toHaveTextContent("weak choice for qa");
  });

  it("Save sends the complete plan (every non-local stage), not just the edit", async () => {
    // PUT /v1/config/plan is a full replace, so Save must transmit the whole
    // intended plan or the daemon resets omitted stages to defaults.
    setup();
    await screen.findByLabelText("Effort for outline");
    vi.mocked(putConfigPlan).mockResolvedValue(makePlan());

    await userEvent.selectOptions(screen.getByLabelText("Effort for outline"), "high");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    const [baseSha, provider, stages] = vi.mocked(putConfigPlan).mock.calls[0];
    expect(baseSha).toBe("sha-1");
    expect(provider).toBe("claude-code");
    expect(Object.keys(stages).sort()).toEqual([
      "audit",
      "draft",
      "outline",
      "profile",
      "qa",
      "repair",
      "spec",
    ]);
    expect(stages.outline).toEqual({
      provider: "claude-code",
      model: "sonnet",
      effort: "high",
    });
    // an untouched stage is still present with its persisted values
    expect(stages.draft).toEqual({
      provider: "claude-code",
      model: "sonnet",
      effort: undefined,
    });
  });

  it("preserves a persisted override on an untouched stage across Save (no data loss)", async () => {
    // Regression: the global plan payload has no `source` field, so seeding
    // only "overridden" stages left this map empty and Save wiped outline.
    const plan = makePlan();
    const outline = plan.stages.find((s) => s.stage === "outline")!;
    outline.provider = "codex";
    outline.model = "gpt";
    setup(plan);
    await screen.findByLabelText("Effort for draft");
    vi.mocked(putConfigPlan).mockResolvedValue(makePlan());

    // edit a DIFFERENT stage
    await userEvent.selectOptions(screen.getByLabelText("Effort for draft"), "high");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    const [, , stages] = vi.mocked(putConfigPlan).mock.calls[0];
    expect(stages.outline).toEqual({
      provider: "codex",
      model: "gpt",
      effort: undefined,
    });
    expect(stages.draft).toEqual({
      provider: "claude-code",
      model: "sonnet",
      effort: "high",
    });
  });

  it("shows the recommended default (top-level provider, no model/effort) after a row's Use recommended", async () => {
    const plan = makePlan();
    const outline = plan.stages.find((s) => s.stage === "outline")!;
    outline.provider = "codex";
    outline.model = "gpt";
    setup(plan);
    await screen.findByLabelText("Provider for outline");

    // starts showing the persisted override
    expect(screen.getByLabelText("Provider for outline")).toHaveValue("codex");
    expect(screen.getByLabelText("Model for outline")).toHaveValue("gpt");

    const row = screen.getByLabelText("Provider for outline").closest(".plan-stage-row")!;
    await userEvent.click(within(row as HTMLElement).getByRole("button", { name: "Use recommended" }));

    // now shows the recommended default, not the stale loaded value
    expect(screen.getByLabelText("Provider for outline")).toHaveValue("claude-code");
    expect(screen.getByLabelText("Model for outline")).toHaveValue("");
    expect(screen.getByLabelText("Effort for outline")).toHaveValue("default");
  });

  it("applies a preset to every stage row for the selected provider", async () => {
    const user = userEvent.setup();
    setup();
    await screen.findByText("Default model plan");
    await user.click(screen.getByRole("button", { name: /Balanced/ }));
    const specRow = document.querySelector('[data-stage="spec"]')!;
    expect(
      within(specRow as HTMLElement).getByLabelText("Model for spec"),
    ).toHaveValue("sonnet");
    expect(
      within(specRow as HTMLElement).getByLabelText("Effort for spec"),
    ).toHaveValue("high");
  });

  it("applies the codex mapping when the preset provider toggle is switched", async () => {
    const user = userEvent.setup();
    setup();
    await screen.findByText("Default model plan");
    await user.click(screen.getByRole("radio", { name: "Codex" }));
    await user.click(screen.getByRole("button", { name: /Balanced/ }));
    const qaRow = document.querySelector('[data-stage="qa"]')!;
    expect(
      within(qaRow as HTMLElement).getByLabelText("Provider for qa"),
    ).toHaveValue("codex");
    expect(
      within(qaRow as HTMLElement).getByLabelText("Model for qa"),
    ).toHaveValue("gpt");
  });

  it("falls back to a provider that has presets when the plan provider has none", async () => {
    const user = userEvent.setup();
    const codexOnly = [{ ...presets[0], stages: { codex: presets[0].stages.codex } }];
    vi.mocked(getConfigProviders).mockResolvedValue({ providers });
    vi.mocked(getConfigCatalog).mockResolvedValue({ providers: catalog, presets: codexOnly });
    vi.mocked(getConfigPlan).mockResolvedValue(makePlan()); // plan provider: claude-code
    render(<SettingsPage />);
    await screen.findByText("Default model plan");
    await user.click(screen.getByRole("button", { name: /Balanced/ }));
    const specRow = document.querySelector('[data-stage="spec"]')!;
    expect(
      within(specRow as HTMLElement).getByLabelText("Provider for spec"),
    ).toHaveValue("codex");
  });

  it("saves preset-applied overrides through putConfigPlan", async () => {
    const user = userEvent.setup();
    vi.mocked(putConfigPlan).mockResolvedValue(makePlan());
    setup();
    await screen.findByText("Default model plan");
    await user.click(screen.getByRole("button", { name: /Balanced/ }));
    await user.click(screen.getByRole("button", { name: "Save" }));
    const [, , stages] = vi.mocked(putConfigPlan).mock.calls[0];
    expect(stages.spec).toEqual({ provider: "claude-code", model: "sonnet", effort: "high" });
  });

  it("surfaces the reload affordance on a 409 stale_content from save", async () => {
    setup();
    await screen.findByLabelText("Effort for outline");
    vi.mocked(putConfigPlan).mockRejectedValue(
      new ApiRequestError(409, "stale_content", "the model plan changed on disk"),
    );

    await userEvent.selectOptions(screen.getByLabelText("Effort for outline"), "high");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByText(/Plan changed on disk/)).toBeInTheDocument();
    const reloadButton = screen.getByRole("button", { name: "Reload" });

    vi.mocked(getConfigPlan).mockResolvedValue(makePlan({ plan_sha256: "sha-2" }));
    await userEvent.click(reloadButton);

    expect(getConfigProviders).toHaveBeenCalledTimes(2);
    expect(getConfigPlan).toHaveBeenCalledTimes(2);
  });
});

describe("SettingsPage welcome control", () => {
  it("re-opens the welcome panel by clearing the dismissal flag", async () => {
    const { WELCOME_DISMISSED_KEY } = await import("../components/WelcomePanel");
    localStorage.setItem(WELCOME_DISMISSED_KEY, "1");
    setup();
    await userEvent.click(await screen.findByRole("button", { name: /show welcome/i }));
    expect(localStorage.getItem(WELCOME_DISMISSED_KEY)).toBeNull();
    expect(screen.getByText(/welcome panel will show/i)).toBeInTheDocument();
    localStorage.clear();
  });
});
