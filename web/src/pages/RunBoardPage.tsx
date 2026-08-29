import { useCallback, useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { ApiRequestError, getJobs, getPersonalization, getRunStatus, postAdvance } from "../api/client";
import type { Job, RunStatus } from "../api/types";
import AuditControls from "../components/AuditControls";
import CanonicalGuidePreview, {
  type CanonicalGuidePreviewHandle,
} from "../components/CanonicalGuidePreview";
import ErrorNotice from "../components/ErrorNotice";
import InfoTip from "../components/InfoTip";
import JobsPanel, { ACTIVE_JOB_STATUSES } from "../components/JobsPanel";
import PersonalizationPanel from "../components/PersonalizationPanel";
import PipelineStepper from "../components/PipelineStepper";
import PrimaryAction from "../components/PrimaryAction";
import RunPlanPanel from "../components/RunPlanPanel";
import ValidationFindingsPanel, { NO_FINDINGS } from "../components/ValidationFindingsPanel";
import { useAction } from "../hooks/useAction";
import { usePolling } from "../hooks/usePolling";

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
        <InfoTip
          label="Validation"
          text="Automatic checks of the guide's structure and content — no model involved. The draft phase checks the approved draft; the final phase checks the repaired guide. Blocking findings must be fixed or waived before finalize."
        />
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
              phase === "final" ? currentPersonalization?.audit.findings : NO_FINDINGS
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
  // Single poll of the jobs endpoint, held here at the board level. JobsPanel
  // used to run its own identical poll for its table, doubling this request
  // stream; it now takes this payload (and error) as props instead, so there
  // is exactly one 2s poll. A queued/running job still surfaces at the TOP of
  // the board (action area and stage row) on the same cadence the Jobs table
  // below renders from.
  const fetchJobs = useCallback(() => getJobs(topicId), [topicId]);
  const { data: jobsData, error: jobsError, refresh: refreshJobs } = usePolling(fetchJobs, 2_000);
  // While the jobs poll is failing, usePolling keeps its last payload; a job
  // that terminated during the outage would stay presented as "Running…" in
  // the action area and on its stepper node. Treat the snapshot as unusable
  // until a poll succeeds again (error clears on the next good tick).
  const activeJob: Job | null = jobsError
    ? null
    : (jobsData?.jobs.find((job) => ACTIVE_JOB_STATUSES.has(job.status)) ?? null);
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
        <InfoTip
          label="Start a run"
          text="Advance starts the run by writing the first stage's prompt into the course folder. Nothing is sent to a model until that prompt is run, and every stage waits for your approval before the next one begins."
        />
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
      <PrimaryAction status={status} activeJob={activeJob} onChanged={refresh} />
      <PipelineStepper
        status={status}
        activeJob={activeJob}
        findingsByStage={findingsByStage}
      />
      <p>
        Finalized: {status.finalized ? "yes" : "no"}{" "}
        <InfoTip
          label="Finalized"
          text="Finalize locks the approved content into the published guide once every blocking finding is resolved; export then writes the shareable file."
        />
      </p>
      {status.content_contract.kind === "interactive_guide" && (
        <InteractiveGuidePanels
          status={status}
          mutationGeneration={contentGeneration}
          onStatusChanged={refreshStatus}
        />
      )}
      <RunPlanPanel topicId={status.topic_id} nextStage={status.next_action.stage} />
      <JobsPanel data={jobsData} error={jobsError} onChanged={refreshJobs} />
    </div>
  );
}

export default function RunBoardPage() {
  const { topicId } = useParams<{ topicId: string }>();
  if (!topicId) return <p className="error">Topic id is required.</p>;
  return <RunBoardForTopic key={topicId} topicId={topicId} />;
}
