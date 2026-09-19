import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type {
  CatalogPreset,
  CatalogProvider,
  PlanPayload,
  ProviderAvailability,
  TopicsPayload,
} from "../api/types";
import SettingsPage from "./SettingsPage";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return {
    ApiRequestError: actual.ApiRequestError,
    getConfigProviders: vi.fn(),
    getConfigCatalog: vi.fn(),
    getConfigPlan: vi.fn(),
    getTopics: vi.fn(),
    putConfigPlan: vi.fn(),
  };
});

import {
  ApiRequestError,
  getConfigCatalog,
  getConfigPlan,
  getConfigProviders,
  getTopics,
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

const STAGES = [
  "profile",
  "spec",
  "outline",
  "draft",
  "qa",
  "factcheck",
  "repair",
  "audit",
  "finalize",
  "export",
];

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

function setup(plan: PlanPayload = makePlan(), topics: TopicsPayload = { topics: [] }) {
  vi.mocked(getConfigProviders).mockResolvedValue({ providers });
  vi.mocked(getConfigCatalog).mockResolvedValue({ providers: catalog, presets });
  vi.mocked(getConfigPlan).mockResolvedValue(plan);
  // The plan editor reads per-stage cost observations off the library
  // payload; a workspace that has never run a costed job carries none.
  vi.mocked(getTopics).mockResolvedValue(topics);
  return render(<SettingsPage />);
}

describe("SettingsPage", () => {
  it("offers an Appearance section with the theme control and a tour replay", async () => {
    setup();
    const section = await screen.findByRole("region", { name: "Appearance" });
    expect(within(section).getByRole("radiogroup", { name: "Theme" })).toBeInTheDocument();
    // Outside the app shell there is no tour to start, but the control stays
    // discoverable so the page never depends on the shell to render.
    expect(within(section).getByRole("button", { name: "Replay the tour" })).toBeEnabled();
    expect(screen.getByRole("region", { name: "Default model plan" })).toHaveAttribute(
      "data-tour",
      "model-plan",
    );
  });

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

  it("explains what provider availability means in learner language", async () => {
    setup();
    await screen.findByLabelText("Provider for outline");
    expect(
      screen.getByText(/Available means the provider's CLI was found on this machine/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/switch that stage to Manual copy\/paste to run it by hand instead/),
    ).toBeInTheDocument();
  });

  it("renders the weak-configuration warning for a stage whose payload carries one", async () => {
    setup();
    await screen.findByLabelText("Provider for outline");
    expect(screen.getByRole("alert")).toHaveTextContent("weak choice for qa");
  });

  it("shows a Parallelism input bound to plan.parallelism and includes it on Save", async () => {
    const plan = makePlan({ parallelism: 2 });
    setup(plan);
    const input = await screen.findByLabelText("Parallelism");
    expect(input).toHaveValue(2);
    vi.mocked(putConfigPlan).mockResolvedValue(makePlan({ parallelism: 3 }));

    await userEvent.clear(input);
    await userEvent.type(input, "3");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    const call = vi.mocked(putConfigPlan).mock.calls[0];
    expect(call[3]).toBe(3);
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
      "factcheck",
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

  it("applies the balanced default for the row's provider after Reset to default", async () => {
    const plan = makePlan();
    const outline = plan.stages.find((s) => s.stage === "outline")!;
    outline.provider = "codex";
    outline.model = "gpt";
    setup(plan);
    await screen.findByLabelText("Provider for outline");

    // starts showing the persisted override (no effort recorded)
    expect(screen.getByLabelText("Provider for outline")).toHaveValue("codex");
    expect(screen.getByLabelText("Model for outline")).toHaveValue("gpt");
    expect(screen.getByLabelText("Effort for outline")).toHaveValue("default");

    const row = screen.getByLabelText("Provider for outline").closest(".plan-stage-row")!;
    await userEvent.click(within(row as HTMLElement).getByRole("button", { name: "Reset to default" }));

    // now shows the balanced-preset default for codex, not the stale loaded value
    expect(screen.getByLabelText("Provider for outline")).toHaveValue("codex");
    expect(screen.getByLabelText("Model for outline")).toHaveValue("gpt");
    expect(screen.getByLabelText("Effort for outline")).toHaveValue("high");
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

  it("shows an explicit 'no mapping' state instead of silently no-opping when a preset lacks the selected provider (issue #18)", async () => {
    const user = userEvent.setup();
    // "quick" only defines a claude-code mapping; codex is a real, selectable
    // preset-provider (balanced supports it) but this preset has nothing for it.
    const presetsWithGap: CatalogPreset[] = [
      presets[0],
      {
        id: "quick",
        label: "Quick",
        description: "Fast placeholder-quality pass.",
        stages: {
          "claude-code": {
            spec: { model: "sonnet", effort: "low" },
          },
        },
      },
    ];
    vi.mocked(getConfigProviders).mockResolvedValue({ providers });
    vi.mocked(getConfigCatalog).mockResolvedValue({ providers: catalog, presets: presetsWithGap });
    vi.mocked(getConfigPlan).mockResolvedValue(makePlan());
    render(<SettingsPage />);
    await screen.findByText("Default model plan");

    await user.click(screen.getByRole("radio", { name: "Codex" }));
    const specRow = document.querySelector('[data-stage="spec"]')!;
    const modelBefore = within(specRow as HTMLElement).getByLabelText("Model for spec");
    expect(modelBefore).toHaveValue("sonnet"); // loaded default, unaffected so far

    const quickButton = screen.getByRole("button", { name: /Quick/ });
    await user.click(quickButton);

    // Regression guard for the silent no-op: the row must NOT have been
    // touched by a preset that has nothing to apply.
    expect(
      within(specRow as HTMLElement).getByLabelText("Model for spec"),
    ).toHaveValue("sonnet");

    // The control must surface WHY nothing happened. Either approach is
    // acceptable per issue #18: an explicit "no mapping" message somewhere in
    // the picker, OR the button itself disabled with an accessible reason
    // (aria-describedby pointing at "no mapping" text). We accept both so the
    // implementer can pick either.
    const explicitMessage = screen.queryByText(/no mapping for/i);
    const describedBy = quickButton.getAttribute("aria-describedby");
    const describedText = describedBy
      ? (document.getElementById(describedBy)?.textContent ?? "")
      : "";
    const disabledWithReason =
      quickButton.hasAttribute("disabled") && /no mapping/i.test(describedText);
    expect(Boolean(explicitMessage) || disabledWithReason).toBe(true);
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

  it("keeps a hand-set timeout_seconds on Save (the cockpit has no editor for it)", async () => {
    // model-plan.toml may set [stages.spec] timeout_seconds by hand, and the
    // daemon honors it. PUT /v1/config/plan is a full replace, so Save must
    // transmit the value back untouched or editing any other row silently
    // deletes it.
    const plan = makePlan();
    const spec = plan.stages.find((s) => s.stage === "spec")!;
    spec.timeout_seconds = 900;
    setup(plan);
    await screen.findByLabelText("Effort for draft");
    vi.mocked(putConfigPlan).mockResolvedValue(plan);

    // edit a DIFFERENT row
    await userEvent.selectOptions(screen.getByLabelText("Effort for draft"), "high");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    const [, , stages] = vi.mocked(putConfigPlan).mock.calls[0];
    expect(stages.spec).toEqual({
      provider: "claude-code",
      model: "sonnet",
      effort: undefined,
      timeout_seconds: 900,
    });
  });

  it("keeps a hand-set timeout_seconds when its own row is edited", async () => {
    const plan = makePlan();
    const spec = plan.stages.find((s) => s.stage === "spec")!;
    spec.timeout_seconds = 900;
    setup(plan);
    await screen.findByLabelText("Effort for spec");
    vi.mocked(putConfigPlan).mockResolvedValue(plan);

    await userEvent.selectOptions(screen.getByLabelText("Effort for spec"), "high");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    const [, , stages] = vi.mocked(putConfigPlan).mock.calls[0];
    expect(stages.spec).toEqual({
      provider: "claude-code",
      model: "sonnet",
      effort: "high",
      timeout_seconds: 900,
    });
  });

  it("keeps a hand-set timeout_seconds when the row is reset to default", async () => {
    // "Reset to default" resets the MODEL CHOICE. timeout_seconds has no
    // editor here, so losing it must not be a side effect of that reset.
    const plan = makePlan();
    const spec = plan.stages.find((s) => s.stage === "spec")!;
    spec.timeout_seconds = 900;
    setup(plan);
    await screen.findByLabelText("Effort for spec");
    vi.mocked(putConfigPlan).mockResolvedValue(plan);

    const specRow = document.querySelector('[data-stage="spec"]') as HTMLElement;
    await userEvent.click(
      within(specRow).getByRole("button", { name: "Reset to default" }),
    );
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    const [, , saved] = vi.mocked(putConfigPlan).mock.calls[0];
    expect(saved.spec).toEqual({
      provider: "claude-code",
      model: "sonnet",
      effort: "high",
      timeout_seconds: 900,
    });
  });

  it("keeps a hand-set timeout_seconds when a preset is applied", async () => {
    // Applying a preset rewrites provider/model/effort for every stage. There
    // is no editor for timeout_seconds, so the preset-generated entry must
    // carry the loaded value forward -- otherwise the full-replace PUT drops a
    // hand-set timeout the moment a preset is applied and saved.
    const plan = makePlan();
    const spec = plan.stages.find((s) => s.stage === "spec")!;
    spec.timeout_seconds = 900;
    setup(plan);
    await screen.findByText("Default model plan");
    vi.mocked(putConfigPlan).mockResolvedValue(plan);

    await userEvent.click(screen.getByRole("button", { name: /Balanced/ }));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    const [, , saved] = vi.mocked(putConfigPlan).mock.calls[0];
    expect(saved.spec).toEqual({
      provider: "claude-code",
      model: "sonnet",
      effort: "high",
      timeout_seconds: 900,
    });
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
  // Thread T07: GET /v1/topics' top-level cost block carries, per stage, the
  // newest job in the workspace with a known cost. The plan editor shows it
  // beside that stage's model choice, so the choice is made against what the
  // stage actually cost rather than against a placeholder price table.
  describe("last observed cost per stage", () => {
    it("shows a stage's last observed cost when the topics payload carries one", async () => {
      setup(makePlan(), {
        topics: [],
        cost: {
          workspace_usd: 0.42,
          stages: {
            outline: {
              usd: 0.42,
              source: "provider",
              observed_at: "2026-07-02T00:00:00+00:00",
            },
          },
        },
      });
      await screen.findByLabelText("Provider for outline");
      expect(
        await screen.findByText(/last observed: \$0\.42 \(provider-reported\)/),
      ).toBeInTheDocument();
    });

    it("shows nothing about a last observed cost when the payload carries none", async () => {
      setup();
      await screen.findByLabelText("Provider for outline");
      expect(screen.queryByText(/last observed/i)).not.toBeInTheDocument();
    });
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
