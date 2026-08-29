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
import CopyPromptButton from "./CopyPromptButton";
import ExportControls from "./ExportControls";
import ResponseForm from "./ResponseForm";

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

  if (activeJob) {
    const verb = activeJob.status === "queued" ? "queued" : "running";
    return (
      <div className="primary-action">
        <p className="active-job-status" role="status">
          <span className="state state-running">
            {activeJob.status === "queued" ? "Queued" : "Running"}
          </span>
          <span>
            The {activeJob.stage} stage is {verb} with {activeJob.provider}
            {activeJob.model ? ` / ${activeJob.model}` : ""}. The board updates
            automatically; the live log is in Jobs below.
          </span>
        </p>
      </div>
    );
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
          <button
            disabled={busy}
            onClick={() =>
              run(() => postApprove(topicId, stage), {
                retryWithOverwrite: () => postApprove(topicId, stage, true),
                successMessage: `Approved ${stage}.`,
              })
            }
          >
            {reapproving ? `Approve changes to ${stage}` : `Approve ${stage}`}
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
