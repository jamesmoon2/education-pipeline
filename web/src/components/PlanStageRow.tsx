import type {
  CatalogProvider,
  PlanStage,
  ProviderAvailability,
  StageOverride,
} from "../api/types";

export interface PlanStageRowProps {
  stage: PlanStage;
  catalog: CatalogProvider[];
  providers: ProviderAvailability[];
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
  onChange,
}: PlanStageRowProps) {
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
  const useRecommended = () => onChange(stage.stage, null);

  return (
    <div className="plan-stage-row" data-stage={stage.stage}>
      <span className="plan-stage-name">{stage.stage}</span>
      <label>
        {`Provider for ${stage.stage}`}
        <select
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
          <option value={MANUAL_PROVIDER}>manual</option>
        </select>
      </label>
      <label>
        {`Model for ${stage.stage}`}
        <select value={stage.model ?? ""} onChange={(e) => handleModelChange(e.target.value)}>
          <option value="">(provider default)</option>
          {models.map((model) => (
            <option key={model.id} value={model.id}>
              {model.quality ? `${model.label} — ${model.quality}` : model.label}
            </option>
          ))}
        </select>
      </label>
      <label>
        {`Effort for ${stage.stage}`}
        <select value={stage.effort ?? "default"} onChange={(e) => handleEffortChange(e.target.value)}>
          <option value="default">default</option>
          {EFFORT_OPTIONS.map((effort) => (
            <option key={effort} value={effort}>
              {effort}
            </option>
          ))}
        </select>
      </label>
      <button type="button" onClick={useRecommended}>
        Use recommended
      </button>
      {stage.warning && (
        <p role="alert" className="plan-stage-warning">
          {stage.warning}
        </p>
      )}
    </div>
  );
}
