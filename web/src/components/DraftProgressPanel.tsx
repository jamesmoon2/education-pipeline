import { useState } from "react";
import {
  cancelBatch,
  enqueueJob,
  postDraftAssemble,
  postDraftUnitResponse,
} from "../api/client";
import type { DraftModuleProgress, DraftProgress, Job } from "../api/types";
import { useAction } from "../hooks/useAction";
import { ACTIVE_JOB_STATUSES } from "./JobsPanel";

// A job's status once it is no longer queued/running -- the states a batch
// job settles into. Used to count "done" for the batch progress line.
const TERMINAL_JOB_STATUSES = new Set<Job["status"]>([
  "succeeded",
  "failed",
  "canceled",
  "interrupted",
]);

const RUNNABLE_STATES = new Set<DraftModuleProgress["state"]>(["prompt_written", "stale"]);

/** The skeleton row's own paste control. A run's stage-level "Paste
 *  response..." loop (PrimaryAction) always writes straight to the
 *  whole-stage response file (the deliberate whole-guide bypass, design
 *  decision 6/9) -- pasting the *skeleton* specifically has to go through
 *  the skeleton unit route instead, so per-module drafting still fans out
 *  on the next Advance. */
// Skeleton states whose unit already has a saved response -- pasting over
// one of these must force-overwrite it (finding 2) rather than let the
// daemon's already_exists conflict swallow the paste.
const SKELETON_HAS_RESPONSE = new Set<DraftModuleProgress["state"]>([
  "response_ingested",
  "stale",
]);

function SkeletonPaste({
  topicId,
  state,
  onChanged,
}: {
  topicId: string;
  state: DraftModuleProgress["state"];
  onChanged: () => void;
}) {
  const [pasteOpen, setPasteOpen] = useState(false);
  const [text, setText] = useState("");
  const hasResponse = SKELETON_HAS_RESPONSE.has(state);
  const save = useAction(() => {
    setPasteOpen(false);
    onChanged();
  });

  return (
    <>
      <button onClick={() => setPasteOpen((open) => !open)}>
        Paste skeleton response
      </button>
      {pasteOpen && (
        <div className="draft-progress-paste">
          <label>
            Response for skeleton
            <textarea value={text} onChange={(e) => setText(e.target.value)} rows={8} />
          </label>
          <button
            disabled={save.busy || !text.trim()}
            onClick={() =>
              save.run(
                () =>
                  hasResponse
                    ? postDraftUnitResponse(topicId, "skeleton", null, text, true)
                    : postDraftUnitResponse(topicId, "skeleton", null, text),
                { successMessage: "Response saved." },
              )
            }
          >
            Save
          </button>
          {save.feedback && <p className={save.isError ? "error" : "success"}>{save.feedback}</p>}
        </div>
      )}
    </>
  );
}

function ModuleRow({
  topicId,
  module,
  batchActive,
  onChanged,
}: {
  topicId: string;
  module: DraftModuleProgress;
  batchActive: boolean;
  onChanged: () => void;
}) {
  const [pasteOpen, setPasteOpen] = useState(false);
  const [text, setText] = useState("");
  const rerun = useAction(onChanged);
  // Closes the editor on a successful save (keeping only one row's "Save"
  // button on screen at a time when pasting several modules in a row).
  const save = useAction(() => {
    setPasteOpen(false);
    onChanged();
  });

  return (
    <li className="draft-progress-row">
      <span className="draft-progress-title">{module.title}</span>{" "}
      <span className="draft-progress-state">{module.state}</span>
      {module.error && <p className="error">{module.error}</p>}
      <div className="draft-progress-row-actions">
        {!batchActive && (
          <button
            disabled={rerun.busy}
            onClick={() =>
              rerun.run(
                () =>
                  enqueueJob(topicId, "draft", Boolean(module.response_sha256), {
                    modules: [module.id],
                  }),
                { successMessage: `Provider run queued for ${module.title}.` },
              )
            }
          >
            Rerun {module.title}
          </button>
        )}{" "}
        <button onClick={() => setPasteOpen((open) => !open)}>
          Paste response for {module.title}
        </button>
      </div>
      {rerun.feedback && <p className={rerun.isError ? "error" : "success"}>{rerun.feedback}</p>}
      {pasteOpen && (
        <div className="draft-progress-paste">
          <label>
            Response for {module.title}
            <textarea value={text} onChange={(e) => setText(e.target.value)} rows={8} />
          </label>
          <button
            disabled={save.busy || !text.trim()}
            onClick={() =>
              save.run(
                () =>
                  module.response_sha256 !== null
                    ? postDraftUnitResponse(topicId, "module", module.id, text, true)
                    : postDraftUnitResponse(topicId, "module", module.id, text),
                { successMessage: "Response saved." },
              )
            }
          >
            Save
          </button>
          {save.feedback && <p className={save.isError ? "error" : "success"}>{save.feedback}</p>}
        </div>
      )}
    </li>
  );
}

/**
 * Per-module draft progress (design 2026-09-18 §8): a skeleton row, one row
 * per module with a batch run/per-module rerun/paste loop, and the
 * deterministic "Assemble draft" step. `activeJobs` is this topic's draft
 * jobs (skeleton + module units, history included); a *queued or running*
 * job carrying a `batch_id` marks a module batch as in flight, which hides
 * the run/rerun controls in favor of batch progress and a cancel button --
 * a batch whose jobs have all settled into a terminal status no longer
 * counts, even though its (now-history) jobs are still present in the list.
 */
export default function DraftProgressPanel({
  topicId,
  progress,
  activeJobs,
  onChanged,
}: {
  topicId: string;
  progress: DraftProgress;
  activeJobs: Job[];
  onChanged: () => void;
}) {
  const batchControls = useAction(onChanged);
  const assemble = useAction(onChanged);

  const batchJob = activeJobs.find(
    (job) => job.batch_id && ACTIVE_JOB_STATUSES.has(job.status),
  );
  const batchId = batchJob?.batch_id ?? null;
  const batchJobs = batchId ? activeJobs.filter((job) => job.batch_id === batchId) : [];
  const batchTotal = batchJobs.length;
  const batchDone = batchJobs.filter((job) => TERMINAL_JOB_STATUSES.has(job.status)).length;
  const batchActive = batchId !== null;

  const canRunModules =
    !batchActive && progress.modules.some((module) => RUNNABLE_STATES.has(module.state));
  const canAssemble =
    progress.modules.length > 0 &&
    progress.modules.every((module) => module.state === "response_ingested") &&
    (progress.assembled === null || !progress.assembled.ok);

  return (
    <section className="draft-progress-panel" aria-labelledby="draft-progress-heading">
      <h3 id="draft-progress-heading">Module drafting</h3>
      {progress.superseded && (
        <p className="warning">
          The draft skeleton was superseded by an edit to the approved outline; regenerate it
          before continuing.
        </p>
      )}
      <p className="draft-progress-counts">
        {progress.counts.saved} of {progress.counts.total} modules saved
      </p>
      {batchActive && (
        <p className="draft-progress-batch">
          <span>
            {batchDone} of {batchTotal} running/done
          </span>{" "}
          <button
            disabled={batchControls.busy}
            onClick={() =>
              batchControls.run(() => cancelBatch(batchId as string), {
                successMessage: "Batch canceled.",
              })
            }
          >
            Cancel batch
          </button>
        </p>
      )}
      <ul className="draft-progress-list">
        <li className="draft-progress-row">
          <span className="draft-progress-title">Skeleton</span>{" "}
          <span className="draft-progress-state">{progress.skeleton.state}</span>
          {progress.skeleton.error && <p className="error">{progress.skeleton.error}</p>}
          <div className="draft-progress-row-actions">
            <SkeletonPaste
              topicId={topicId}
              state={progress.skeleton.state}
              onChanged={onChanged}
            />
          </div>
        </li>
        {progress.modules.map((module) => (
          <ModuleRow
            key={module.id}
            topicId={topicId}
            module={module}
            batchActive={batchActive}
            onChanged={onChanged}
          />
        ))}
      </ul>
      <div className="draft-progress-actions">
        {canRunModules && (
          <button
            disabled={batchControls.busy}
            onClick={() =>
              batchControls.run(() => enqueueJob(topicId, "draft"), {
                successMessage: "Provider run queued.",
              })
            }
          >
            Run modules with provider
          </button>
        )}{" "}
        {canAssemble && (
          <button
            disabled={assemble.busy}
            onClick={() =>
              assemble.run(() => postDraftAssemble(topicId), {
                successMessage: (result) =>
                  result.ok ? "Draft assembled." : (result.error ?? "Assemble failed."),
                errorTone: (result) => !result.ok,
              })
            }
          >
            Assemble draft
          </button>
        )}
      </div>
      {batchControls.feedback && (
        <p className={batchControls.isError ? "error" : "success"}>{batchControls.feedback}</p>
      )}
      {assemble.feedback && (
        <p className={assemble.isError ? "error" : "success"}>{assemble.feedback}</p>
      )}
    </section>
  );
}
