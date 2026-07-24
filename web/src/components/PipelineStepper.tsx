import { Link } from "react-router-dom";
import type { Job, RunStatus, StageProvenance } from "../api/types";
import { stageStateLabel } from "../lib/labels";

// The latest provenance entry per stage — a stage can be re-run, so multiple
// entries may share a stage name; the most recently recorded one wins.
export function latestProvenanceByStage(
  entries: StageProvenance[],
): Map<string, StageProvenance> {
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

/**
 * The run board's at-a-glance pipeline: one step per model stage, in order,
 * with the stage's state, live job status, findings badge, and provenance.
 * Each stage name links to the stage viewer; the next-action stage carries
 * aria-current="step".
 */
export default function PipelineStepper({
  status,
  activeJob,
  findingsByStage,
}: {
  status: RunStatus;
  activeJob: Job | null;
  findingsByStage: Record<string, number>;
}) {
  const provenanceByStage = latestProvenanceByStage(status.stage_provenance);
  return (
    <ol className="pipeline-stepper" aria-label="Run pipeline">
      {status.stages.map((s) => {
        const provenance = provenanceByStage.get(s.stage);
        const findingsCount = findingsByStage[s.stage] ?? 0;
        const stageJob = activeJob?.stage === s.stage ? activeJob : null;
        return (
          <li
            key={s.stage}
            className={`stepper-step stepper-${stageJob ? "running" : s.state}`}
            aria-label={`${s.stage} stage`}
            aria-current={s.stage === status.next_action.stage ? "step" : undefined}
          >
            <span className="stepper-marker" aria-hidden="true" />
            <div className="stepper-body">
              <span className="stepper-heading">
                <Link
                  className="stepper-stage"
                  to={`/topics/${status.topic_id}/stages/${s.stage}`}
                >
                  {s.stage}
                </Link>
                {findingsCount > 0 && (
                  <span
                    className="findings-badge"
                    aria-label={`${findingsCount} ${findingsCount === 1 ? "finding" : "findings"}`}
                  >
                    {findingsCount}
                  </span>
                )}
              </span>
              {stageJob ? (
                <span className="state state-running">
                  {stageJob.status === "queued"
                    ? `Queued with ${stageJob.provider}`
                    : `Running with ${stageJob.provider}…`}
                </span>
              ) : (
                <span className={`state state-${s.state}`}>{stageStateLabel(s.state)}</span>
              )}
              {provenance && (
                <p className="stage-provenance">{formatProvenance(provenance)}</p>
              )}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
