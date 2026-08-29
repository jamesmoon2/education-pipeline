import { useState } from "react";
import { Link } from "react-router-dom";
import {
  enqueueJob,
  getStageContent,
  postAdvance,
  postApprove,
  postFinalize,
  postValidate,
} from "../api/client";
import type { Job, RunStatus } from "../api/types";
import { useAction } from "../hooks/useAction";
import { useNow } from "../hooks/useNow";
import { continueFailed, continueFeedback, continueRun } from "../lib/continueRun";
import { formatDurationMs, jobElapsedMs } from "../lib/time";
import CopyPromptButton from "./CopyPromptButton";
import ExportControls from "./ExportControls";
import JobLogView from "./JobLogView";
import ResponseForm from "./ResponseForm";

/** The active-job block for a queued/running provider job. Split out so
 *  `useNow`'s tick is scoped to exactly this block's lifetime -- it mounts
 *  only from the `if (activeJob)` branch below and unmounts (taking its
 *  interval with it) the moment the job leaves the board's status poll. */
function ActiveJobStatus({ job }: { job: Job }) {
  const now = useNow();
  const queued = job.status === "queued";
  const elapsedMs = jobElapsedMs(job, now);
  const elapsedLabel =
    elapsedMs === null
      ? null
      : `${queued ? "Queued" : "Running"} for ${formatDurationMs(elapsedMs)}`;

  return (
    <div className="primary-action">
      <div className="active-job-status">
        {/* The live region announces the job's state once when it changes;
            the ticking elapsed readout below is a sibling, not a child, so
            a screen reader is never re-prompted to re-announce this whole
            block every second for the life of a run. */}
        <p role="status">
          <span className="state state-running">{queued ? "Queued" : "Running"}</span>
          <span>
            The {job.stage} stage is {queued ? "queued" : "running"} with {job.provider}
            {job.model ? ` / ${job.model}` : ""}. The board updates automatically; the
            full log is in Jobs below.
          </span>
        </p>
        {/* Not aria-hidden: still reachable/readable on demand, just outside
            the live region above. */}
        {elapsedLabel && <span className="active-job-elapsed">{elapsedLabel}</span>}
      </div>
      {/* A queued job has no process running yet, so there is no log to tail. */}
      {job.status === "running" && <JobLogView jobId={job.id} active tail={3} />}
    </div>
  );
}

export default function PrimaryAction({
  status,
  activeJob = null,
  onChanged,
}: {
  status: RunStatus;
  /** A queued/running provider job for this topic, if any. While one is
   *  active every mutating action would 409, so the action area shows live
   *  progress instead of a button that still says "ready to run". */
  activeJob?: Job | null;
  onChanged: () => void;
}) {
  const { busy, feedback, isError, run } = useAction(onChanged);
  const [pasteOpen, setPasteOpen] = useState(false);
  const { topic_id: topicId, next_action: next } = status;
  const stage = next.stage;
  // stages[].approved flags an approved copy on disk, so an approve action
  // for such a stage is a re-approval that overwrites the prior copy.
  const reapproving = status.stages.some((s) => s.stage === stage && s.approved);
  const approveLabel = reapproving ? `Approve changes to ${stage}` : `Approve ${stage}`;

  if (activeJob) {
    return <ActiveJobStatus job={activeJob} />;
  }

  return (
    <div className="primary-action">
      {next.action === "write_prompt" && (
        <button
          disabled={busy}
          onClick={() =>
            run(() => postAdvance(topicId), { successMessage: "Prompt written." })
          }
        >
          Advance
        </button>
      )}
      {next.action === "save_response" && stage && (
        <>
          <button
            disabled={busy}
            onClick={() => run(() => enqueueJob(topicId), { successMessage: "Job enqueued." })}
          >
            Run with provider
          </button>{" "}
          <ol className="manual-loop" aria-label="Manual copy/paste loop">
            <li>
              <CopyPromptButton
                getText={async () => {
                  const content = await getStageContent(topicId, stage);
                  if (content.prompt === null) {
                    throw new Error(`No prompt on disk for ${stage} yet.`);
                  }
                  return content.prompt;
                }}
              />
            </li>
            <li className="manual-loop-hint">
              run it in the model you already use
            </li>
            <li>
              <button
                disabled={busy}
                onClick={() => setPasteOpen((open) => !open)}
              >
                Paste response…
              </button>
            </li>
          </ol>
          {pasteOpen && (
            <ResponseForm
              topicId={topicId}
              stage={stage}
              onDone={() => {
                setPasteOpen(false);
                onChanged();
              }}
            />
          )}
        </>
      )}
      {next.action === "approve" && stage && (
        <>
          {/* Approval is the judgment; the chain runs the mechanical
              follow-ups only after it succeeds — including after an
              overwrite retry, which repeats the approval first. */}
          <button
            disabled={busy}
            onClick={() =>
              run(
                async () => {
                  await postApprove(topicId, stage);
                  return continueRun(topicId);
                },
                {
                  retryWithOverwrite: async () => {
                    await postApprove(topicId, stage, true);
                    return continueRun(topicId);
                  },
                  successMessage: (result) => continueFeedback(stage, result),
                  errorTone: continueFailed,
                },
              )
            }
          >
            {approveLabel} &amp; continue
          </button>{" "}
          <button
            disabled={busy}
            onClick={() =>
              run(() => postApprove(topicId, stage), {
                retryWithOverwrite: () => postApprove(topicId, stage, true),
                successMessage: `Approved ${stage}.`,
              })
            }
          >
            {approveLabel} only
          </button>{" "}
          {/* Land review on the pending content, not the default prompt tab. */}
          <Link to={`/topics/${topicId}/stages/${stage}?tab=response`}>
            review first
          </Link>
        </>
      )}
      {next.action === "validate" && stage && (
        <button
          disabled={busy}
          onClick={() =>
            run(
              () => postValidate(topicId, stage === "draft" ? "draft" : "final"),
              { successMessage: `${stage === "draft" ? "Draft" : "Final"} validation complete.` },
            )
          }
        >
          Run {stage === "draft" ? "draft" : "final"} validation
        </button>
      )}
      {next.action === "resolve_findings" && stage && (
        <>
          <Link to={`/topics/${topicId}/stages/${stage}`}>Review findings</Link>{" "}
          <span className="blocked-reason">Finalization blocked: {next.detail}</span>
        </>
      )}
      {next.action === "finalize" && (
        <button
          disabled={busy}
          onClick={() =>
            run(() => postFinalize(topicId), {
              retryWithOverwrite: () => postFinalize(topicId, true),
              successMessage: "Finalized.",
            })
          }
        >
          Finalize
        </button>
      )}
      {next.action === "done" && (
        <ExportControls
          topicId={topicId}
          guideV1={status.content_contract.kind === "interactive_guide"}
        />
      )}
      {feedback && <p className={isError ? "error" : "success"}>{feedback}</p>}
    </div>
  );
}
