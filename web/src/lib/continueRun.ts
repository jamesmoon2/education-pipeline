import { postContinue } from "../api/client";
import type { Continuation, ContinuePayload, RunStatus } from "../api/types";

export type { Continuation };

/**
 * "Approve & continue": after a human approval succeeds, run the mechanical
 * follow-ups that need no judgment — writing the next stage prompt, running
 * validation, and starting the configured provider — and stop at the first
 * step that does need judgment.
 *
 * T32: the loop itself now lives in ``education_pipeline/orchestrate.py``
 * (``run_until_judgment``), behind ``POST /v1/runs/{id}/continue``. This
 * file is a thin client over that one call: it sends the request and maps
 * the daemon's payload onto ``ContinueResult``, nothing more.
 *
 * The product rule this file used to enforce by hand — nothing here
 * approves, finalizes, or exports — is now enforced in the engine instead:
 * the daemon's ``Steps`` protocol has no approve/finalize/export member at
 * all, so the loop behind this call cannot perform them even by mistake.
 */

/** Mechanical follow-ups the daemon performed, in the order it took them. */
export type ContinueStep =
  | { kind: "advance"; stage: string | null }
  | { kind: "validate"; stage: string | null; phase: "draft" | "final" }
  | { kind: "job"; stage: string; provider: string; count?: number };

/** Where the run stopped, and why. */
export type ContinueStop =
  | {
      kind: "started";
      stage: string;
      provider: string;
      // Set when the job was a draft module batch; equals the batch size.
      // Absent for a single-job start.
      count?: number;
    }
  | { kind: "manual"; stage: string }
  | { kind: "plan_unreadable"; stage: string }
  | { kind: "approve"; stage: string | null }
  | { kind: "resolve_findings" }
  | { kind: "finalize" }
  | { kind: "done" }
  | { kind: "unfinished" }
  | { kind: "failed"; action: string; message: string };

export interface ContinueResult {
  readonly steps: readonly ContinueStep[];
  readonly stop: ContinueStop;
  /** Freshest status the daemon sent; null when the first read failed. */
  readonly status: RunStatus | null;
}

/** The api surface this client is allowed to touch. Injected so tests drive
 *  every branch without a network mock. */
export interface ContinueApi {
  postContinue: (topicId: string) => Promise<ContinuePayload>;
}

// Wrapped rather than passed by reference so each call resolves through the
// live client module (module mocks in component tests still apply).
const PRODUCTION_API: ContinueApi = {
  postContinue: (topicId) => postContinue(topicId),
};

export async function continueRun(
  topicId: string,
  api: ContinueApi = PRODUCTION_API,
): Promise<ContinueResult> {
  try {
    const payload = await api.postContinue(topicId);
    return { steps: payload.steps, stop: payload.stop, status: payload.status };
  } catch (err) {
    return {
      steps: [],
      stop: {
        kind: "failed",
        action: "continuing the run",
        message: err instanceof Error ? err.message : String(err),
      },
      status: null,
    };
  }
}

function describeStep(step: ContinueStep): string | null {
  switch (step.kind) {
    case "advance":
      return `wrote the ${step.stage ?? "next"} prompt`;
    case "validate":
      return `ran ${step.phase} validation`;
    case "job":
      // The "started …" stop phrase already reports this one.
      return null;
  }
}

/** The stage a stop phrase names, so a prompt-writing step for that same
 *  stage isn't announced twice ("wrote the qa prompt; started qa with …"). */
function stopStage(stop: ContinueStop): string | null {
  switch (stop.kind) {
    case "started":
    case "manual":
    case "plan_unreadable":
    case "approve":
      return stop.stage;
    default:
      return null;
  }
}

function describeStop(stop: ContinueStop): string {
  switch (stop.kind) {
    case "started":
      // A module-batch job carries a job count; name it so the feedback
      // doesn't read as if only one provider call started.
      return stop.count
        ? `${stop.count} module jobs started for ${stop.stage} with ${stop.provider}`
        : `started ${stop.stage} with ${stop.provider}`;
    case "manual":
      return `the ${stop.stage} prompt is ready for you to run`;
    case "plan_unreadable":
      return `the ${stop.stage} prompt is ready, but the model plan could not be read, so start the stage yourself`;
    case "approve":
      return stop.stage ? `${stop.stage} needs your approval` : "the next stage needs your approval";
    case "resolve_findings":
      return "findings need review";
    case "finalize":
      return "the run is ready to finalize";
    case "done":
      return "the run is ready to export";
    case "unfinished":
      return "more steps are waiting";
    case "failed":
      return `${stop.action} failed: ${stop.message}`;
  }
}

/** True when a follow-up failed after the approval landed, so the caller can
 *  show the outcome in its error tone. A stage left for the manual loop —
 *  including one whose plan could not be read — is not a failure: the prompt
 *  is on disk and the user simply runs it. */
export function continueFailed(result: ContinueResult): boolean {
  return result.stop.kind === "failed";
}

/** One plain-language line for an "Approve & continue" click: what was
 *  approved, what ran on its own, and where the run now stands. */
export function continueFeedback(stage: string, result: ContinueResult): string {
  if (result.stop.kind === "failed") {
    return `Approved ${stage}, but ${describeStop(result.stop)}`;
  }
  const named = stopStage(result.stop);
  const taken = result.steps
    .filter((item) => !(item.kind === "advance" && item.stage === named))
    .map(describeStep)
    .filter((phrase): phrase is string => phrase !== null);
  return `Approved ${stage} — ${[...taken, describeStop(result.stop)].join("; ")}.`;
}

/** One plain-language line for the "Continue to next approval" button --
 *  the same run-to-judgment loop as "Approve & continue", but with no
 *  approval headline (nothing was approved by this click). */
export function continueOnlyFeedback(result: ContinueResult): string {
  if (result.stop.kind === "failed") {
    return `Continuing failed: ${describeStop(result.stop)}`;
  }
  const named = stopStage(result.stop);
  const taken = result.steps
    .filter((item) => !(item.kind === "advance" && item.stage === named))
    .map(describeStep)
    .filter((phrase): phrase is string => phrase !== null);
  return `Continued — ${[...taken, describeStop(result.stop)].join("; ")}.`;
}

/** True when the latest chained job (``RunStatus.continuation``) ended in a
 *  failed stop, so the cockpit can show it in the error tone. */
export function chainFailed(continuation: Continuation): boolean {
  return continuation.stop.kind === "failed";
}

/** One plain-language line reporting a chained job's outcome
 *  (``RunStatus.continuation``): headed by the job that ran rather than by
 *  an approval, since nothing here was triggered by this page load. Unlike
 *  ``continueFeedback``/``continueOnlyFeedback``, every step the daemon
 *  reports is named -- there is no approval or "Continue" headline to make
 *  a same-stage prompt-write step redundant here. */
export function chainFeedback(continuation: Continuation): string {
  const ran = continuation.after === "batch" ? "module jobs ran" : "job ran";
  const taken = continuation.steps
    .map((step) => describeStep(step))
    .filter((phrase): phrase is string => phrase !== null);
  return `After the ${continuation.stage} ${ran}: ${[...taken, describeStop(continuation.stop)].join("; ")}.`;
}
