import { useId } from "react";
import type {
  CatalogProvider,
  PlanStage,
  ProviderAvailability,
  StageOverride,
} from "../api/types";
import InfoTip from "./InfoTip";
import { EFFORT_HELP, PROVIDER_HELP, STAGE_HELP } from "../lib/planHelp";

export interface PlanStageRowProps {
  stage: PlanStage;
  catalog: CatalogProvider[];
  providers: ProviderAvailability[];
  /** Show the "overridden" tag on this row (run-level override in effect). */
  overridden?: boolean;
  resetValue: StageOverride | null;
  onChange(stage: string, override: StageOverride | null): void;
}

// The run engine never drives these stages through a model (see
// SUPPORTED_STAGES in runs.py) — they're deterministic and local-only, so
// there's nothing for a provider/model/effort selector to configure.
const LOCAL_ONLY_STAGES = new Set(["finalize", "export"]);
const EFFORT_OPTIONS = ["low", "medium", "high"] as const;
const MANUAL_PROVIDER = "manual";

export default function PlanStageRow({
  stage,
  catalog,
  providers,
  overridden = false,
  resetValue,
  onChange,
}: PlanStageRowProps) {
  // Explicit label/select association. The InfoTip trigger is a labelable
  // <button>, so it lives on the heading line beside the label, never inside
  // it — otherwise the label would associate with the button, not the select.
  const providerSelectId = useId();
  const modelSelectId = useId();
  const effortSelectId = useId();

  if (LOCAL_ONLY_STAGES.has(stage.stage)) {
    return (
      <div className="plan-stage-row plan-stage-row--local" data-stage={stage.stage}>
        <span className="plan-stage-name">{stage.stage}</span>
        <span className="plan-stage-local">Local only — no model configuration.</span>
      </div>
    );
  }

  const availabilityById = new Map(providers.map((p) => [p.id, p]));
  const currentProviderId = stage.provider ?? MANUAL_PROVIDER;
  const selectedCatalogProvider = catalog.find((p) => p.id === currentProviderId);
  const models = selectedCatalogProvider?.models ?? [];

  const handleProviderChange = (value: string) => {
    onChange(stage.stage, { provider: value, model: undefined, effort: stage.effort ?? undefined });
  };
  const handleModelChange = (value: string) => {
    onChange(stage.stage, {
      provider: currentProviderId,
      model: value === "" ? undefined : value,
      effort: stage.effort ?? undefined,
    });
  };
  const handleEffortChange = (value: string) => {
    onChange(stage.stage, {
      provider: currentProviderId,
      model: stage.model ?? undefined,
      effort: value === "default" ? undefined : value,
    });
  };
  const resetToDefault = () =>
    onChange(stage.stage, resetValue ? { ...resetValue } : null);

  return (
    <div className="plan-stage-row" data-stage={stage.stage}>
      {/* The "overridden" tag lives inside the fixed-width name column so
          toggling an override never shifts the select columns sideways. */}
      <span className="plan-stage-name">
        <span className="plan-stage-name-text">
          {stage.stage}
          {STAGE_HELP[stage.stage] && (
            <InfoTip label={`${stage.stage} stage`} text={STAGE_HELP[stage.stage]} />
          )}
        </span>
        {overridden && <span className="plan-stage-badge">overridden</span>}
      </span>
      <div className="plan-stage-field">
        <span className="plan-stage-field-label">
          <label htmlFor={providerSelectId}>{`Provider for ${stage.stage}`}</label>
          <InfoTip label={`provider for ${stage.stage}`} text={PROVIDER_HELP} />
        </span>
        <select
          id={providerSelectId}
          value={currentProviderId}
          onChange={(e) => handleProviderChange(e.target.value)}
        >
          {catalog.map((provider) => {
            const availability = availabilityById.get(provider.id);
            const unavailable = availability !== undefined && !availability.available;
            return (
              <option
                key={provider.id}
                value={provider.id}
                title={unavailable ? (availability?.reason ?? undefined) : undefined}
              >
                {provider.label}
                {unavailable ? " (unavailable)" : ""}
              </option>
            );
          })}
          {!catalog.some((provider) => provider.id === MANUAL_PROVIDER) && (
            <option value={MANUAL_PROVIDER}>manual</option>
          )}
        </select>
      </div>
      <div className="plan-stage-field">
        <span className="plan-stage-field-label">
          <label htmlFor={modelSelectId}>{`Model for ${stage.stage}`}</label>
        </span>
        <select
          id={modelSelectId}
          value={stage.model ?? ""}
          onChange={(e) => handleModelChange(e.target.value)}
        >
          <option value="">(provider default)</option>
          {models.map((model) => (
            <option key={model.id} value={model.id}>
              {model.quality ? `${model.label} — ${model.quality}` : model.label}
            </option>
          ))}
        </select>
      </div>
      <div className="plan-stage-field">
        <span className="plan-stage-field-label">
          <label htmlFor={effortSelectId}>{`Effort for ${stage.stage}`}</label>
          <InfoTip label={`effort for ${stage.stage}`} text={EFFORT_HELP} />
        </span>
        <select
          id={effortSelectId}
          value={stage.effort ?? "default"}
          onChange={(e) => handleEffortChange(e.target.value)}
        >
          <option value="default">default</option>
          {EFFORT_OPTIONS.map((effort) => (
            <option key={effort} value={effort}>
              {effort}
            </option>
          ))}
        </select>
      </div>
      <button type="button" onClick={resetToDefault}>
        Reset to default
      </button>
      {stage.warning && (
        <p role="alert" className="plan-stage-warning">
          {stage.warning}
        </p>
      )}
      {stage.override_error && (
        <p role="alert" className="plan-stage-override-error">
          {stage.override_error}
        </p>
      )}
    </div>
  );
}
