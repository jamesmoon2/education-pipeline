import { useState } from "react";
import { Link } from "react-router-dom";
import { enqueueJob, postAdvance, postApprove, postFinalize } from "../api/client";
import type { RunStatus } from "../api/types";
import { useAction } from "../hooks/useAction";
import ExportControls from "./ExportControls";
import ResponseForm from "./ResponseForm";

export default function PrimaryAction({
  status,
  onChanged,
}: {
  status: RunStatus;
  onChanged: () => void;
}) {
  const { busy, feedback, isError, run } = useAction(onChanged);
  const [pasteOpen, setPasteOpen] = useState(false);
  const { topic_id: topicId, next_action: next } = status;
  const stage = next.stage;

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
          <button disabled={busy} onClick={() => setPasteOpen((open) => !open)}>
            Paste response…
          </button>
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
            Approve {stage}
          </button>{" "}
          <Link to={`/topics/${topicId}/stages/${stage}`}>review first</Link>
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
      {next.action === "done" && <ExportControls topicId={topicId} />}
      {feedback && <p className={isError ? "error" : "success"}>{feedback}</p>}
    </div>
  );
}
