import { useEffect, useState } from "react";
import { getConfigCatalog, getConfigProviders, getRunPlan, putRunPlan } from "../api/client";
import type { CatalogProvider, PlanPayload, PlanStage, ProviderAvailability, StageOverride } from "../api/types";
import PlanStageRow from "./PlanStageRow";

const MANUAL_PROVIDER = "manual";
// Mirrors LOCAL_ONLY_STAGES in PlanStageRow.tsx: stages the run engine
// drives locally, never through a model provider.
const LOCAL_ONLY_STAGES = new Set(["finalize", "export"]);

function describeEffective(stage: PlanStage): string {
  const parts = [stage.provider ?? MANUAL_PROVIDER];
  if (stage.model) parts.push(stage.model);
  if (stage.effort) parts.push(stage.effort);
  return parts.join(" / ");
}

export default function RunPlanPanel({
  topicId,
  nextStage,
}: {
  topicId: string;
  nextStage: string | null;
}) {
  const [providers, setProviders] = useState<ProviderAvailability[] | null>(null);
  const [catalog, setCatalog] = useState<CatalogProvider[] | null>(null);
  const [plan, setPlan] = useState<PlanPayload | null>(null);
  const [loadError, setLoadError] = useState<Error | null>(null);
  const [rowError, setRowError] = useState<string | null>(null);

  const load = async () => {
    setLoadError(null);
    try {
      const [providersResp, catalogResp, planResp] = await Promise.all([
        getConfigProviders(),
        getConfigCatalog(),
        getRunPlan(topicId),
      ]);
      setProviders(providersResp.providers);
      setCatalog(catalogResp.providers);
      setPlan(planResp);
    } catch (err) {
      setLoadError(err instanceof Error ? err : new Error(String(err)));
    }
  };

  useEffect(() => {
    void load();
  }, [topicId]);

  const handleRowChange = async (stageName: string, override: StageOverride | null) => {
    setRowError(null);
    try {
      const updated = await putRunPlan(topicId, { [stageName]: override });
      setPlan(updated);
    } catch (err) {
      setRowError(err instanceof Error ? err.message : String(err));
    }
  };

  if (loadError) {
    return <p className="error">Failed to load run plan: {loadError.message}</p>;
  }
  if (!providers || !catalog || !plan) return <p>Loading plan…</p>;

  const nextStagePlan = nextStage ? plan.stages.find((s) => s.stage === nextStage) : undefined;

  return (
    <section aria-labelledby="run-plan-heading">
      <h3 id="run-plan-heading">Model plan for this run</h3>
      {nextStagePlan && (
        <p className="run-plan-next">
          {LOCAL_ONLY_STAGES.has(nextStagePlan.stage) ? (
            <strong>{`Next: ${nextStagePlan.stage} — runs locally, no model`}</strong>
          ) : (
            <>
              <strong>{`Next: ${nextStagePlan.stage} — ${describeEffective(nextStagePlan)}`}</strong>
              {nextStagePlan.provider === MANUAL_PROVIDER || nextStagePlan.provider === null ? (
                <span> — you run the prompt yourself</span>
              ) : nextStagePlan.command ? (
                <>
                  {" "}
                  runs locally as: <code>{nextStagePlan.command.join(" ")}</code>
                </>
              ) : null}
            </>
          )}
        </p>
      )}
      {rowError && <p className="error">{rowError}</p>}
      {plan.stages.map((stage) => (
        <div key={stage.stage} className="run-plan-row">
          {stage.source === "override" && <span className="plan-stage-badge">overridden</span>}
          <PlanStageRow
            stage={stage}
            catalog={catalog}
            providers={providers}
            resetValue={null}
            onChange={(s, o) => void handleRowChange(s, o)}
          />
        </div>
      ))}
    </section>
  );
}
