import { useEffect, useState } from "react";
import {
  ApiRequestError,
  getConfigCatalog,
  getConfigPlan,
  getConfigProviders,
  putConfigPlan,
} from "../api/client";
import PlanStageRow from "../components/PlanStageRow";
import type {
  CatalogProvider,
  PlanPayload,
  PlanStage,
  ProviderAvailability,
  StageOverride,
} from "../api/types";
import { useAction } from "../hooks/useAction";

// Mirrors PlanStageRow's LOCAL_ONLY_STAGES: these stages never carry a
// model-plan override (the run engine drives them deterministically).
const LOCAL_ONLY_STAGES = new Set(["finalize", "export"]);

function seedOverrides(stages: PlanStage[]): Record<string, StageOverride> {
  const overrides: Record<string, StageOverride> = {};
  for (const stage of stages) {
    if (LOCAL_ONLY_STAGES.has(stage.stage)) continue;
    if (stage.source === "override") {
      overrides[stage.stage] = {
        provider: stage.provider ?? undefined,
        model: stage.model ?? undefined,
        effort: stage.effort ?? undefined,
      };
    }
  }
  return overrides;
}

function withOverride(stage: PlanStage, override: StageOverride | undefined): PlanStage {
  if (!override) return stage;
  return {
    ...stage,
    provider: override.provider ?? stage.provider,
    model: override.model ?? null,
    effort: override.effort ?? null,
  };
}

export default function SettingsPage() {
  const [providers, setProviders] = useState<ProviderAvailability[] | null>(null);
  const [catalog, setCatalog] = useState<CatalogProvider[] | null>(null);
  const [plan, setPlan] = useState<PlanPayload | null>(null);
  const [loadError, setLoadError] = useState<Error | null>(null);
  const [overrides, setOverrides] = useState<Record<string, StageOverride>>({});
  const [stale, setStale] = useState(false);
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
      setPlan(planResp);
      setOverrides(seedOverrides(planResp.stages));
      setStale(false);
    } catch (err) {
      setLoadError(err instanceof Error ? err : new Error(String(err)));
    }
  };

  useEffect(() => {
    void load();
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

  const useRecommendedAll = () => setOverrides({});

  const doSave = () =>
    save.run(async () => {
      if (!plan) return;
      try {
        const updated = await putConfigPlan(plan.plan_sha256, plan.provider, overrides);
        setPlan(updated);
        setOverrides(seedOverrides(updated.stages));
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
        <ul>
          {providers.map((p) => (
            <li key={p.id}>
              {p.label} ({p.id}):{" "}
              {p.available ? "available" : `unavailable — ${p.reason ?? "unknown reason"}`}
            </li>
          ))}
        </ul>
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
        <div className="toolbar" role="toolbar" aria-label="Plan actions">
          <button type="button" onClick={useRecommendedAll}>
            Use recommended (all stages)
          </button>
          <button type="button" disabled={save.busy} onClick={doSave}>
            Save
          </button>
        </div>
        {plan.stages.map((stage) => (
          <PlanStageRow
            key={stage.stage}
            stage={withOverride(stage, overrides[stage.stage])}
            catalog={catalog}
            providers={providers}
            onChange={handleRowChange}
          />
        ))}
        {save.feedback && (
          <p className={save.isError ? "error" : "success"}>{save.feedback}</p>
        )}
      </section>
    </div>
  );
}
