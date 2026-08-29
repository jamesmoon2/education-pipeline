import {
  enqueueJob,
  getRunPlan,
  getRunStatus,
  postAdvance,
  postValidate,
} from "../api/client";
import type { AdvanceResult, NextAction, PlanPayload, RunStatus } from "../api/types";

/**
 * "Approve & continue": after a human approval succeeds, run the mechanical
 * follow-ups that need no judgment — writing the next stage prompt, running
 * validation, and starting the configured provider — and stop at the first
 * step that does need judgment.
 *
 * The product rule this file exists to keep: nothing here approves,
 * finalizes, or exports. Those actions have no adapter in ContinueApi at
 * all, so the chain cannot perform them even by mistake; it stops and says
 * where the run stands instead.
 */

const MANUAL_PROVIDER = "manual";

/** Loop bound: guarantees termination even if the daemon keeps reporting an
 *  action the chain's own step never clears. Six is twice the longest real
 *  chain (validate → advance → start). */
export const MAX_CONTINUE_STEPS = 6;

/** Mechanical follow-ups the chain performed, in the order it took them. */
export type ContinueStep =
  | { kind: "advance"; stage: string | null }
  | { kind: "validate"; phase: "draft" | "final" }
  | { kind: "enqueue"; stage: string; provider: string };

/** Where the chain stopped, and why. */
export type ContinueStop =
  | { kind: "started"; stage: string; provider: string }
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
  /** Freshest status the chain read; null when the first read failed. */
  readonly status: RunStatus | null;
}

/** The api surface the chain is allowed to touch. Injected so tests drive
 *  every branch without a module mock — and so the absent approve/finalize/
 *  export adapters are visible in one place. */
export interface ContinueApi {
  getRunStatus: (topicId: string) => Promise<RunStatus>;
  postAdvance: (topicId: string) => Promise<AdvanceResult>;
  postValidate: (topicId: string, phase: "draft" | "final") => Promise<unknown>;
  /** The queued job payload is not used; the board's job poll picks it up. */
  enqueueJob: (topicId: string) => Promise<unknown>;
  /** This run's effective plan (GET /v1/runs/{id}/plan) — the workspace plan
   *  with this run's stage overrides already applied. The workspace-wide
   *  plan (GET /v1/config/plan) is the wrong source: it misses overrides. */
  getRunPlan: (topicId: string) => Promise<PlanPayload>;
}

// Wrapped rather than passed by reference so each call resolves through the
// live client module (module mocks in component tests still apply).
const PRODUCTION_API: ContinueApi = {
  getRunStatus: (topicId) => getRunStatus(topicId),
  postAdvance: (topicId) => postAdvance(topicId),
  postValidate: (topicId, phase) => postValidate(topicId, phase),
  enqueueJob: (topicId) => enqueueJob(topicId),
  getRunPlan: (topicId) => getRunPlan(topicId),
};

/** Carries the plain-language name of the step that threw, so the caller can
 *  say which follow-up failed while still reporting the approval as done. */
class StepError extends Error {
  constructor(readonly action: string, cause: unknown) {
    super(cause instanceof Error ? cause.message : String(cause));
    this.name = "StepError";
  }
}

async function step<T>(action: string, call: () => Promise<T>): Promise<T> {
  try {
    return await call();
  } catch (err) {
    throw new StepError(action, err);
  }
}

export async function continueRun(
  topicId: string,
  api: ContinueApi = PRODUCTION_API,
  maxSteps: number = MAX_CONTINUE_STEPS,
): Promise<ContinueResult> {
  const steps: ContinueStep[] = [];
  let status: RunStatus | null = null;
  const stopAt = (stop: ContinueStop): ContinueResult => ({ steps, stop, status });

  try {
    for (let taken = 0; taken < maxSteps; taken += 1) {
      if (status === null) {
        status = await step("reading the run status", () => api.getRunStatus(topicId));
      }
      // Annotated: the step labels below name the stage, so inferring these
      // from `status` would circle back through the calls that reassign it.
      const next: NextAction = status.next_action;
      const stage: string | null = next.stage;
      switch (next.action) {
        case "write_prompt": {
          // Only ever from a freshly read write_prompt: advance performs
          // whatever step the run is on, and that includes finalize.
          const advanced = await step(
            `writing the ${stage ?? "next"} prompt`,
            () => api.postAdvance(topicId),
          );
          steps.push({ kind: "advance", stage });
          // advance hands back a fresh status; no need to re-read it.
          status = advanced.status;
          break;
        }
        case "validate": {
          // Same phase mapping the run board uses: only the draft stage
          // gates on the draft report; every later stage gates on final.
          const phase = stage === "draft" ? "draft" : "final";
          await step(`${phase} validation`, () => api.postValidate(topicId, phase));
          steps.push({ kind: "validate", phase });
          // The validate payload is a report, not a status: re-read.
          status = null;
          break;
        }
        case "save_response": {
          // The daemon always names a stage for save_response; without one
          // there is no plan row to consult, so stop rather than guess.
          if (stage === null) return stopAt({ kind: "unfinished" });
          let plan: PlanPayload;
          try {
            plan = await api.getRunPlan(topicId);
          } catch {
            // A plan we cannot read is not a failed approval: the prompt is
            // on disk either way, so hand the stage back to the user.
            return stopAt({ kind: "plan_unreadable", stage });
          }
          // INVARIANT: this must resolve the provider exactly as the enqueue
          // endpoint does, or the chain starts a job the daemon runs with a
          // different provider than reported — or refuses to start one it
          // would have run. DaemonContext.enqueue_stage (daemon/server.py)
          // applies this run's overrides to the workspace plan and then takes
          // `stage_plan.provider or plan.provider`; GET /v1/runs/{id}/plan
          // serializes that same overridden plan, so the rule here is the
          // matching row's provider, falling back to the plan default. A row
          // with no provider of its own is NOT manual — the run-plan panel
          // shows null as "manual", but that is a display fallback only.
          const provider =
            plan.stages.find((entry) => entry.stage === stage)?.provider ?? plan.provider;
          if (provider === MANUAL_PROVIDER) return stopAt({ kind: "manual", stage });
          await step(`starting ${stage} with ${provider}`, () => api.enqueueJob(topicId));
          steps.push({ kind: "enqueue", stage, provider });
          return stopAt({ kind: "started", stage, provider });
        }
        case "approve":
          return stopAt({ kind: "approve", stage });
        case "resolve_findings":
          return stopAt({ kind: "resolve_findings" });
        case "finalize":
          return stopAt({ kind: "finalize" });
        case "done":
          return stopAt({ kind: "done" });
        default:
          // An action from a newer daemon than this build knows about.
          return stopAt({ kind: "unfinished" });
      }
    }
  } catch (err) {
    if (!(err instanceof StepError)) throw err;
    return stopAt({ kind: "failed", action: err.action, message: err.message });
  }
  return stopAt({ kind: "unfinished" });
}

function describeStep(step: ContinueStep): string | null {
  switch (step.kind) {
    case "advance":
      return `wrote the ${step.stage ?? "next"} prompt`;
    case "validate":
      return `ran ${step.phase} validation`;
    case "enqueue":
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
      return `started ${stop.stage} with ${stop.provider}`;
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
