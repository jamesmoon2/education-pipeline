import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { CatalogProvider, PlanStage, ProviderAvailability } from "../api/types";
import PlanStageRow, { type PlanStageRowProps } from "./PlanStageRow";

const catalog: CatalogProvider[] = [
  {
    id: "claude-code",
    label: "Claude Code",
    description: "",
    models: [
      { id: "sonnet", label: "Sonnet", description: "", quality: "strong", default_effort: null },
      { id: "haiku", label: "Haiku", description: "", quality: null, default_effort: null },
    ],
  },
  {
    id: "codex",
    label: "Codex",
    description: "",
    models: [{ id: "gpt", label: "GPT", description: "", quality: "premium", default_effort: null }],
  },
];

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

const outlineStage: PlanStage = {
  stage: "outline",
  provider: "claude-code",
  model: "sonnet",
  effort: null,
  recommendation: "premium_reasoning",
  warning: null,
};

const specStage: PlanStage = {
  stage: "spec",
  provider: "claude-code",
  model: "sonnet",
  effort: null,
  recommendation: "premium_reasoning",
  warning: null,
};

function renderRow(props: Partial<PlanStageRowProps> = {}) {
  return render(
    <PlanStageRow
      stage={specStage}
      catalog={catalog}
      providers={providers}
      resetValue={null}
      onChange={vi.fn()}
      {...props}
    />,
  );
}

describe("PlanStageRow", () => {
  it("renders provider/model/effort selectors for a model-powered stage", () => {
    const onChange = vi.fn();
    render(
      <PlanStageRow stage={outlineStage} catalog={catalog} providers={providers} resetValue={null} onChange={onChange} />,
    );
    expect(screen.getByLabelText("Provider for outline")).toBeInTheDocument();
    expect(screen.getByLabelText("Model for outline")).toBeInTheDocument();
    expect(screen.getByLabelText("Effort for outline")).toBeInTheDocument();
    expect(screen.getByLabelText("Model for outline")).toHaveTextContent("Sonnet — strong");
  });

  it("renders finalize/export as static text with no selectors", () => {
    const onChange = vi.fn();
    const stage: PlanStage = {
      stage: "finalize",
      provider: "claude-code",
      model: null,
      effort: null,
      recommendation: "local_only",
      warning: null,
    };
    render(<PlanStageRow stage={stage} catalog={catalog} providers={providers} resetValue={null} onChange={onChange} />);
    expect(screen.getByText("finalize")).toBeInTheDocument();
    expect(screen.getByText(/Local only/)).toBeInTheDocument();
    expect(screen.queryByRole("combobox")).toBeNull();
  });

  it("labels an unavailable provider option with its reason", () => {
    const onChange = vi.fn();
    render(
      <PlanStageRow stage={outlineStage} catalog={catalog} providers={providers} resetValue={null} onChange={onChange} />,
    );
    const providerSelect = screen.getByLabelText("Provider for outline");
    const codexOption = within(providerSelect).getByText("Codex (unavailable)");
    expect(codexOption).toHaveAttribute("title", "codex CLI not found on PATH");
  });

  it("renders stage.warning in a role=alert element", () => {
    const onChange = vi.fn();
    const warned: PlanStage = { ...outlineStage, warning: "claude-code haiku is a weak choice for outline" };
    render(<PlanStageRow stage={warned} catalog={catalog} providers={providers} resetValue={null} onChange={onChange} />);
    expect(screen.getByRole("alert")).toHaveTextContent("weak choice for outline");
  });

  it("renders stage.override_error in a role=alert element", () => {
    const onChange = vi.fn();
    const broken: PlanStage = {
      ...outlineStage,
      source: "override",
      override_error: "stored override is invalid: unknown model 'x' -- reset this stage to clear it.",
    };
    render(<PlanStageRow stage={broken} catalog={catalog} providers={providers} resetValue={null} onChange={onChange} />);
    expect(screen.getByRole("alert")).toHaveTextContent("reset this stage");
  });

  it("does not render an override_error element when stage.override_error is absent", () => {
    const onChange = vi.fn();
    render(
      <PlanStageRow stage={outlineStage} catalog={catalog} providers={providers} resetValue={null} onChange={onChange} />,
    );
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("does not render a warning element when stage.warning is null", () => {
    const onChange = vi.fn();
    render(
      <PlanStageRow stage={outlineStage} catalog={catalog} providers={providers} resetValue={null} onChange={onChange} />,
    );
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("calls onChange(stage, null) when Reset to default is clicked", async () => {
    const onChange = vi.fn();
    render(
      <PlanStageRow
        stage={outlineStage}
        catalog={catalog}
        providers={providers}
        resetValue={null}
        onChange={onChange}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Reset to default" }));
    expect(onChange).toHaveBeenCalledWith("outline", null);
  });

  it("reset button applies the provided default override", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    renderRow({
      resetValue: { provider: "claude-code", model: "sonnet", effort: "high" },
      onChange,
    });
    await user.click(screen.getByRole("button", { name: "Reset to default" }));
    expect(onChange).toHaveBeenCalledWith("spec", {
      provider: "claude-code",
      model: "sonnet",
      effort: "high",
    });
  });

  it("reset button clears the override when no default is provided", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    renderRow({ resetValue: null, onChange });
    await user.click(screen.getByRole("button", { name: "Reset to default" }));
    expect(onChange).toHaveBeenCalledWith("spec", null);
  });

  it("shows a stage explanation tooltip", async () => {
    const user = userEvent.setup();
    renderRow({});
    await user.click(screen.getByRole("button", { name: "About spec stage" }));
    expect(screen.getByRole("tooltip")).toHaveTextContent(/course contract/);
  });

  it("emits a merged override with the pinned provider when the model changes", async () => {
    const onChange = vi.fn();
    render(
      <PlanStageRow stage={outlineStage} catalog={catalog} providers={providers} resetValue={null} onChange={onChange} />,
    );
    await userEvent.selectOptions(screen.getByLabelText("Model for outline"), "haiku");
    expect(onChange).toHaveBeenCalledWith("outline", {
      provider: "claude-code",
      model: "haiku",
      effort: undefined,
    });
  });

  it("does not duplicate the manual option when the catalog already defines one", () => {
    const onChange = vi.fn();
    const catalogWithManual: CatalogProvider[] = [
      ...catalog,
      { id: "manual", label: "manual", description: "", models: [] },
    ];
    render(
      <PlanStageRow
        stage={outlineStage}
        catalog={catalogWithManual}
        providers={providers}
        resetValue={null}
        onChange={onChange}
      />,
    );
    const providerSelect = screen.getByLabelText("Provider for outline");
    const manualOptions = within(providerSelect).getAllByRole("option", { name: "manual" });
    expect(manualOptions).toHaveLength(1);
  });

  it("emits an override when the effort changes, using default to mean unset", async () => {
    const onChange = vi.fn();
    render(
      <PlanStageRow stage={outlineStage} catalog={catalog} providers={providers} resetValue={null} onChange={onChange} />,
    );
    await userEvent.selectOptions(screen.getByLabelText("Effort for outline"), "high");
    expect(onChange).toHaveBeenCalledWith("outline", {
      provider: "claude-code",
      model: "sonnet",
      effort: "high",
    });
  });
});
