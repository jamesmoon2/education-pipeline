import { useEffect, useState } from "react";
import {
  ApiRequestError,
  getConfigCatalog,
  getConfigPlan,
  getConfigProviders,
  getTopics,
  putConfigPlan,
} from "../api/client";
import PlanStageRow from "../components/PlanStageRow";
import type {
  CatalogPreset,
  CatalogProvider,
  ObservedStageCost,
  PlanPayload,
  PlanStage,
  ProviderAvailability,
  StageOverride,
} from "../api/types";
import { useAction } from "../hooks/useAction";
import { resetWelcomeDismissal } from "../components/WelcomePanel";

// Mirrors PlanStageRow's LOCAL_ONLY_STAGES: these stages never carry a
// model-plan override (the run engine drives them deterministically).
const LOCAL_ONLY_STAGES = new Set(["finalize", "export"]);

// Seed the editable overrides map from EVERY non-local stage in the loaded
// plan — provider/model/effort exactly as persisted. This is mandatory
// because PUT /v1/config/plan is a FULL REPLACE (see spec §2): the daemon
// rebuilds the plan from exactly the stages in the request body, defaulting
// any omitted stage. Seeding only "changed" stages would silently reset every
// untouched persisted override on Save. (The global plan payload has no
// `source` field — that exists only on the per-run payload — so there is no
// override/default distinction to gate on here.)
function seedOverrides(stages: PlanStage[]): Record<string, StageOverride> {
  const overrides: Record<string, StageOverride> = {};
  for (const stage of stages) {
    if (LOCAL_ONLY_STAGES.has(stage.stage)) continue;
    overrides[stage.stage] = {
      provider: stage.provider ?? undefined,
      model: stage.model ?? undefined,
      effort: stage.effort ?? undefined,
      // Hand-set in model-plan.toml and honored by the daemon; there is no
      // editor for it, so Save must carry it back or the full-replace PUT
      // would delete it.
      timeout_seconds: stage.timeout_seconds ?? undefined,
    };
  }
  return overrides;
}

// The row's displayed state. A stage WITH an entry renders that entry's
// values; a stage WITHOUT an entry (cleared via per-row "Use recommended")
// renders the recommended default — top-level provider, no model, no effort —
// NOT the stale loaded value.
function displayStage(
  stage: PlanStage,
  override: StageOverride | undefined,
  defaultProvider: string,
): PlanStage {
  if (!override) {
    return {
      ...stage,
      provider: defaultProvider,
      model: null,
      effort: null,
      timeout_seconds: null,
    };
  }
  return {
    ...stage,
    provider: override.provider ?? defaultProvider,
    model: override.model ?? null,
    effort: override.effort ?? null,
    timeout_seconds: override.timeout_seconds ?? null,
  };
}

export default function SettingsPage() {
  const [providers, setProviders] = useState<ProviderAvailability[] | null>(null);
  const [catalog, setCatalog] = useState<CatalogProvider[] | null>(null);
  const [plan, setPlan] = useState<PlanPayload | null>(null);
  const [presets, setPresets] = useState<CatalogPreset[]>([]);
  const [presetProvider, setPresetProvider] = useState<string>("claude-code");
  const [loadError, setLoadError] = useState<Error | null>(null);
  const [overrides, setOverrides] = useState<Record<string, StageOverride>>({});
  const [stale, setStale] = useState(false);
  const [welcomeReset, setWelcomeReset] = useState(false);
  // What each stage last actually cost, so a model choice is made next to a
  // real observation instead of a price table. Workspace-wide, and read off
  // the library payload rather than a new endpoint.
  const [observed, setObserved] = useState<Record<string, ObservedStageCost>>({});
  // Decision 10: bounds concurrently running module jobs of one draft
  // batch. Workspace-wide only (no per-stage editor); defaults to 2 to
  // match the daemon's own default for a payload predating the field.
  const [parallelism, setParallelism] = useState<number>(2);
  const save = useAction();

  const load = async () => {
    setLoadError(null);
    try {
      const [providersResp, catalogResp, planResp] = await Promise.all([
        getConfigProviders(),
        getConfigCatalog(),
        getConfigPlan(),
      ]);
      setProviders(providersResp.providers);
      setCatalog(catalogResp.providers);
      setPresets(catalogResp.presets ?? []);
      const presetProviders = new Set(
        (catalogResp.presets ?? []).flatMap((p) => Object.keys(p.stages)),
      );
      // Fall back to the first provider that actually has presets — a workspace
      // catalog may define presets for providers other than claude-code.
      setPresetProvider(
        presetProviders.has(planResp.provider)
          ? planResp.provider
          : ([...presetProviders][0] ?? "claude-code"),
      );
      setPlan(planResp);
      setOverrides(seedOverrides(planResp.stages));
      setParallelism(planResp.parallelism ?? 2);
      setStale(false);
    } catch (err) {
      setLoadError(err instanceof Error ? err : new Error(String(err)));
    }
  };

  useEffect(() => {
    void load();
  }, []);

  // Deliberately outside `load`: a cost observation is a nicety, so neither
  // its latency nor its failure may hold up or break the plan editor.
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const payload = await getTopics();
        if (!cancelled) setObserved(payload?.cost?.stages ?? {});
      } catch {
        /* no observations to show */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const handleRowChange = (stageName: string, override: StageOverride | null) => {
    setOverrides((prev) => {
      const next = { ...prev };
      if (override === null) {
        delete next[stageName];
      } else {
        next[stageName] = override;
      }
      return next;
    });
  };

  const applyPreset = (preset: CatalogPreset) => {
    const mapping = preset.stages[presetProvider];
    // Defensive no-op: the button for a preset lacking this mapping is
    // disabled (see the preset-buttons render below), so this should be
    // unreachable in practice — kept as a guard against stale clicks.
    if (!mapping) return;
    setOverrides((prev) => {
      const next: Record<string, StageOverride> = {};
      for (const [stageName, choice] of Object.entries(mapping)) {
        next[stageName] = {
          provider: presetProvider,
          model: choice.model,
          effort: choice.effort ?? undefined,
          // A preset chooses provider/model/effort only. timeout_seconds is
          // hand-set in model-plan.toml with no editor here, so it must ride
          // along or the full-replace PUT deletes it on the next Save.
          timeout_seconds: prev[stageName]?.timeout_seconds,
        };
      }
      return next;
    });
  };

  const presetProviderIds = Array.from(
    new Set(presets.flatMap((p) => Object.keys(p.stages))),
  );

  const balanced = presets.find((p) => p.id === "balanced") ?? presets[0] ?? null;

  const resetValueFor = (stageName: string, providerId: string): StageOverride | null => {
    const choice = balanced?.stages[providerId]?.[stageName];
    if (!choice) return null;
    return {
      provider: providerId,
      model: choice.model,
      effort: choice.effort ?? undefined,
      // The reset is of the model choice. timeout_seconds is hand-set in
      // model-plan.toml with no editor here, so dropping it must not be a
      // side effect of resetting the row.
      timeout_seconds: overrides[stageName]?.timeout_seconds,
    };
  };

  const doSave = () =>
    save.run(async () => {
      if (!plan) return;
      try {
        const updated = await putConfigPlan(plan.plan_sha256, plan.provider, overrides, parallelism);
        setPlan(updated);
        setOverrides(seedOverrides(updated.stages));
        setParallelism(updated.parallelism ?? parallelism);
        setStale(false);
      } catch (err) {
        if (
          err instanceof ApiRequestError &&
          err.status === 409 &&
          err.code === "stale_content"
        ) {
          setStale(true);
        }
        throw err;
      }
    });

  if (loadError) {
    return <p className="error">Failed to load settings: {loadError.message}</p>;
  }
  if (!providers || !catalog || !plan) return <p>Loading…</p>;

  return (
    <div className="settings-page">
      <h2>Settings</h2>
      <section aria-labelledby="providers-heading">
        <h3 id="providers-heading">Provider availability</h3>
        <p className="field-help">
          Available means the provider's CLI was found on this machine. You can still save a
          plan that uses an unavailable provider, but running one of its stages will fail
          until the CLI is installed — switch that stage to Manual copy/paste to run it by
          hand instead.
        </p>
        <ul>
          {providers.map((p) => (
            <li key={p.id}>
              {p.label} ({p.id}):{" "}
              {p.available ? "available" : `unavailable — ${p.reason ?? "unknown reason"}`}
            </li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="welcome-control-heading">
        <h3 id="welcome-control-heading">First-run welcome</h3>
        <p>
          <button
            type="button"
            onClick={() => {
              resetWelcomeDismissal();
              setWelcomeReset(true);
            }}
          >
            Show welcome
          </button>{" "}
          {welcomeReset && (
            <span role="status">
              The welcome panel will show on the course library while the workspace has no
              runs yet.
            </span>
          )}
        </p>
      </section>

      <section aria-labelledby="plan-heading">
        <h3 id="plan-heading">Default model plan</h3>
        {stale && (
          <p role="alert">
            Plan changed on disk — reload.{" "}
            <button type="button" onClick={() => void load()}>
              Reload
            </button>
          </p>
        )}
        {presets.length > 0 && (
          <div className="preset-picker">
            <fieldset className="preset-provider-toggle">
              <legend>Recommended presets for</legend>
              {presetProviderIds.map((providerId) => (
                <label key={providerId}>
                  <input
                    type="radio"
                    name="preset-provider"
                    value={providerId}
                    checked={presetProvider === providerId}
                    onChange={() => setPresetProvider(providerId)}
                  />
                  {catalog.find((p) => p.id === providerId)?.label ?? providerId}
                </label>
              ))}
            </fieldset>
            <div className="preset-buttons" role="group" aria-label="Recommended presets">
              {presets.map((preset) => {
                const hasMapping = Boolean(preset.stages[presetProvider]);
                const providerLabel =
                  catalog.find((p) => p.id === presetProvider)?.label ?? presetProvider;
                const hintId = `preset-unavailable-${preset.id}`;
                return (
                  <button
                    key={preset.id}
                    type="button"
                    onClick={() => applyPreset(preset)}
                    disabled={!hasMapping}
                    aria-describedby={hasMapping ? undefined : hintId}
                  >
                    <span className="preset-label">{preset.label}</span>
                    <span className="preset-description">{preset.description}</span>
                    {!hasMapping && (
                      <span id={hintId} className="preset-unavailable-hint">
                        No mapping for {providerLabel}
                      </span>
                    )}
                  </button>
                );
              })}
            </div>
            <p className="field-help">
              A preset fills every stage below; adjust any row before saving.
            </p>
          </div>
        )}
        <p className="field-help">
          <label>
            Parallelism
            <input
              type="number"
              min={1}
              max={4}
              value={parallelism}
              onChange={(e) => setParallelism(Number(e.target.value))}
            />
          </label>{" "}
          Concurrently running module jobs of one draft batch (1–4).
        </p>
        <div className="toolbar" role="toolbar" aria-label="Plan actions">
          <button type="button" disabled={save.busy} onClick={doSave}>
            Save
          </button>
        </div>
        {plan.stages.map((stage) => {
          const display = displayStage(stage, overrides[stage.stage], plan.provider);
          return (
            <PlanStageRow
              key={stage.stage}
              stage={display}
              catalog={catalog}
              providers={providers}
              resetValue={resetValueFor(stage.stage, display.provider ?? plan.provider)}
              lastObservedCost={observed[stage.stage]}
              onChange={handleRowChange}
            />
          );
        })}
        {save.feedback && (
          <p className={save.isError ? "error" : "success"}>{save.feedback}</p>
        )}
      </section>
    </div>
  );
}
