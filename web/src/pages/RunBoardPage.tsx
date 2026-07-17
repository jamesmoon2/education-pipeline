import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiRequestError, getPersonalization, getRunStatus, postAdvance } from "../api/client";
import type { RunStatus, StageProvenance } from "../api/types";
import AuditControls from "../components/AuditControls";
import CanonicalGuidePreview, {
  type CanonicalGuidePreviewHandle,
} from "../components/CanonicalGuidePreview";
import ErrorNotice from "../components/ErrorNotice";
import JobsPanel from "../components/JobsPanel";
import PersonalizationPanel from "../components/PersonalizationPanel";
import PrimaryAction from "../components/PrimaryAction";
import RunPlanPanel from "../components/RunPlanPanel";
import ValidationFindingsPanel from "../components/ValidationFindingsPanel";
import { useAction } from "../hooks/useAction";
import { usePolling } from "../hooks/usePolling";
import { stageStateLabel } from "../lib/labels";

// The latest provenance entry per stage — a stage can be re-run, so multiple
// entries may share a stage name; the most recently recorded one wins.
function latestProvenanceByStage(entries: StageProvenance[]): Map<string, StageProvenance> {
  const latest = new Map<string, StageProvenance>();
  for (const entry of entries) {
    const existing = latest.get(entry.stage);
    if (!existing || entry.recorded_at > existing.recorded_at) {
      latest.set(entry.stage, entry);
    }
  }
  return latest;
}

function formatProvenance(entry: StageProvenance): string {
  const model = entry.model ? ` / ${entry.model}` : "";
  const effort = entry.effort ? ` / ${entry.effort}` : "";
  return `ran on ${entry.provider}${model}${effort} (${entry.source})`;
}

// Blocking-or-error findings by stage, combined across the draft and final
// validation reports, so a stage badges up if either phase flagged it.
// Only "current" reports contribute: stale or missing reports describe
// superseded content and would misrepresent actionable work.
//
// No client-side effective_blocking check here: the server
// (_validation_summary, read_api.py) already nets waived findings out of
// findings_by_stage itself, so a fully-waived stage arrives as {} and needs
// no extra suppression. An earlier version additionally skipped a phase
// whenever effective_blocking === 0, reasoning that would guard against the
// server "under-netting" a stray non-blocking severity: "error" finding --
// but findings_by_stage counts blocking OR severity === "error" while
// effective_blocking counts blocking only, so that skip would have done the
// opposite: dropped a real, un-waived error-severity badge whenever it
// wasn't also blocking. It was inert only because every error-severity rule
// today also sets blocking=True (guides/validation.py). Trust the server's
// netting instead of re-deriving (and getting backwards) a second copy of
// it here.
function combinedFindingsByStage(status: RunStatus): Record<string, number> {
  const merged: Record<string, number> = {};
  for (const phase of ["draft", "final"] as const) {
    const validation = status.validations[phase];
    if (validation.state !== "current") continue;
    const byStage: Record<string, number> = validation.findings_by_stage ?? {};
    for (const [stage, count] of Object.entries(byStage)) {
      merged[stage] = (merged[stage] ?? 0) + count;
    }
  }
  return merged;
}

function InteractiveGuidePanels({
  status,
  mutationGeneration,
  onStatusChanged,
}: {
  status: RunStatus;
  mutationGeneration: number;
  onStatusChanged: () => void;
}) {
  const fetchPersonalization = useCallback(
    () => getPersonalization(status.topic_id),
    [status.topic_id],
  );
  const {
    data: personalization,
    error,
    refresh: refreshPersonalization,
  } = usePolling(fetchPersonalization, 5_000);
  const previewRef = useRef<CanonicalGuidePreviewHandle>(null);
  const observedMutationGeneration = useRef(mutationGeneration);
  const [previewGeneration, setPreviewGeneration] = useState(0);
  const refreshWorkspace = useCallback(() => {
    onStatusChanged();
    refreshPersonalization();
    setPreviewGeneration((generation) => generation + 1);
  }, [onStatusChanged, refreshPersonalization]);

  useEffect(() => {
    if (observedMutationGeneration.current === mutationGeneration) return;
    observedMutationGeneration.current = mutationGeneration;
    refreshPersonalization();
    setPreviewGeneration((generation) => generation + 1);
  }, [mutationGeneration, refreshPersonalization]);

  const mismatchedTopic = personalization && personalization.topic_id !== status.topic_id;
  const currentPersonalization = !error && !mismatchedTopic ? personalization : null;

  return (
    <>
      <section className="run-personalization-workspace" aria-label="Personalization workspace">
        <div className="run-personalization-sidebar">
          {error ? (
            <ErrorNotice prefix="Failed to load personalization" error={error} />
          ) : mismatchedTopic ? (
            <p className="error" role="alert">
              Personalization response does not match this run.
            </p>
          ) : currentPersonalization ? (
            <>
              <PersonalizationPanel
                personalization={currentPersonalization}
                onEvidence={(evidence) => previewRef.current?.revealEvidence(evidence)}
              />
              <AuditControls
                topicId={status.topic_id}
                audit={currentPersonalization.audit}
                exportState={currentPersonalization.export.state}
                onChanged={refreshWorkspace}
              />
            </>
          ) : (
            <p role="status" aria-label="Loading personalization">
              Loading personalization…
            </p>
          )}
        </div>
        <CanonicalGuidePreview
          key={previewGeneration}
          ref={previewRef}
          topicId={status.topic_id}
        />
      </section>
      <section aria-labelledby="validation-heading">
        <h3 id="validation-heading">Validation milestones</h3>
        <table>
          <thead><tr><th>Phase</th><th>State</th><th>Blocking</th><th>Errors</th><th>Warnings</th></tr></thead>
          <tbody>
            {(["draft", "final"] as const).map((phase) => {
              const validation = status.validations[phase];
              return <tr key={phase}>
                <td>{phase}</td><td>{validation.state}</td><td>{validation.blocking}</td>
                <td>{validation.errors}</td><td>{validation.warnings}</td>
              </tr>;
            })}
          </tbody>
        </table>
        {(["draft", "final"] as const).map((phase) => (
          <ValidationFindingsPanel
            key={phase}
            topicId={status.topic_id}
            phase={phase}
            state={status.validations[phase].state}
            effectiveBlocking={status.validations[phase].effective_blocking}
            supplementalFindings={
              phase === "final" ? currentPersonalization?.audit.findings : []
            }
            onChanged={refreshWorkspace}
          />
        ))}
      </section>
    </>
  );
}

function RunBoardForTopic({ topicId }: { topicId: string }) {
  const fetchStatus = useCallback(() => getRunStatus(topicId), [topicId]);
  const { data: status, error, refresh: refreshStatus } = usePolling(fetchStatus, 5_000);
  const [contentGeneration, setContentGeneration] = useState(0);
  const refresh = useCallback(() => {
    refreshStatus();
    setContentGeneration((generation) => generation + 1);
  }, [refreshStatus]);
  const start = useAction(refresh);

  if (error instanceof ApiRequestError && error.status === 404) {
    return (
      <div>
        <p>
          No run started for <strong>{topicId}</strong> yet.
        </p>
        <button
          disabled={start.busy}
          onClick={() =>
            start.run(() => postAdvance(topicId), { successMessage: "Run started." })
          }
        >
          Advance
        </button>
        {start.feedback && (
          <p className={start.isError ? "error" : "success"}>{start.feedback}</p>
        )}
      </div>
    );
  }
  if (error) return <ErrorNotice prefix="Failed to load run" error={error} onRetry={refresh} />;
  if (!status) return <p>Loading…</p>;
  if (status.topic_id !== topicId) {
    return <p className="error" role="alert">Run response does not match this topic.</p>;
  }

  const provenanceByStage = latestProvenanceByStage(status.stage_provenance);
  const findingsByStage = combinedFindingsByStage(status);

  return (
    <div>
      <h2>{status.topic_id}</h2>
      {status.blueprint && (
        <p className="blueprint-line">
          Blueprint: <strong>{status.blueprint.id}</strong> ({status.blueprint.source})
          {status.blueprint.rationale ? <> — {status.blueprint.rationale}</> : null}
        </p>
      )}
      <p className="next-action">
        <strong>Next:</strong> {status.next_action.detail}
      </p>
      <PrimaryAction status={status} onChanged={refresh} />
      <table>
        <thead>
          <tr>
            <th>Stage</th>
            <th>State</th>
            <th>Findings</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {status.stages.map((s) => {
            const provenance = provenanceByStage.get(s.stage);
            const findingsCount = findingsByStage[s.stage] ?? 0;
            return (
              <tr key={s.stage}>
                <td>{s.stage}</td>
                <td>
                  <span className={`state state-${s.state}`}>{stageStateLabel(s.state)}</span>
                  {provenance && <p className="stage-provenance">{formatProvenance(provenance)}</p>}
                </td>
                <td>
                  {findingsCount > 0 && (
                    <span
                      className="findings-badge"
                      aria-label={`${findingsCount} ${findingsCount === 1 ? "finding" : "findings"}`}
                    >
                      {findingsCount}
                    </span>
                  )}
                </td>
                <td>
                  <Link to={`/topics/${status.topic_id}/stages/${s.stage}`}>view</Link>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p>Finalized: {status.finalized ? "yes" : "no"}</p>
      {status.content_contract.kind === "interactive_guide" && (
        <InteractiveGuidePanels
          status={status}
          mutationGeneration={contentGeneration}
          onStatusChanged={refreshStatus}
        />
      )}
      <RunPlanPanel topicId={status.topic_id} nextStage={status.next_action.stage} />
      <JobsPanel topicId={status.topic_id} />
    </div>
  );
}

export default function RunBoardPage() {
  const { topicId } = useParams<{ topicId: string }>();
  if (!topicId) return <p className="error">Topic id is required.</p>;
  return <RunBoardForTopic key={topicId} topicId={topicId} />;
}
