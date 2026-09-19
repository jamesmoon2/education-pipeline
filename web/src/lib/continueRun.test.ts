import { describe, expect, it, vi } from "vitest";
import type { NextAction, RunStatus } from "../api/types";
import type { ContinuePayload } from "../api/types";
import {
  chainFailed,
  chainFeedback,
  continueFailed,
  continueFeedback,
  continueOnlyFeedback,
  continueRun,
  type ContinueApi,
  type Continuation,
  type ContinueResult,
  type ContinueStep,
  type ContinueStop,
} from "./continueRun";

/**
 * T32: continueRun is now a thin client over a single daemon call
 * (POST /v1/runs/{id}/continue, education_pipeline.orchestrate.run_until_judgment
 * behind it) instead of driving the chain step by step itself. These tests
 * replace the old step-by-step-chain suite entirely.
 */

function makeStatus(action: NextAction["action"], stage: string | null): RunStatus {
  return {
    topic_id: "t",
    finalized: action === "done",
    content_contract: { kind: "legacy_markdown" },
    stage_provenance: [],
    validations: {
      draft: { state: "missing", blocking: 0, errors: 0, warnings: 0 },
      final: { state: "missing", blocking: 0, errors: 0, warnings: 0 },
    },
    stages: [],
    next_action: { topic_id: "t", stage, action, detail: `detail for ${action}` },
  };
}

function makePayload(
  stop: ContinueStop,
  steps: ContinueStep[] = [],
  status: RunStatus | null = null,
): ContinuePayload {
  return { topic_id: "t", steps, stop, status };
}

function makeApi(postContinue: ReturnType<typeof vi.fn>): ContinueApi {
  return { postContinue };
}

describe("continueRun (thin client)", () => {
  // One entry per STOP_KINDS value (education_pipeline/orchestrate.py), plus
  // a batch-count variant of "started" -- the whole surface the daemon can
  // report back, per decision 2 of the phase-3 plan ("stop kinds are the
  // cockpit's, unchanged").
  const table: { name: string; payload: ContinuePayload }[] = [
    {
      name: "started",
      payload: makePayload(
        { kind: "started", stage: "qa", provider: "claude-code" },
        [
          { kind: "advance", stage: "qa" },
          { kind: "job", stage: "qa", provider: "claude-code" },
        ],
      ),
    },
    {
      name: "started with a module-batch count",
      payload: makePayload(
        { kind: "started", stage: "draft", provider: "claude-code", count: 3 },
        [{ kind: "job", stage: "draft", provider: "claude-code", count: 3 }],
      ),
    },
    {
      name: "manual",
      payload: makePayload(
        { kind: "manual", stage: "qa" },
        [{ kind: "advance", stage: "qa" }],
      ),
    },
    {
      name: "plan_unreadable",
      payload: makePayload(
        { kind: "plan_unreadable", stage: "qa" },
        [{ kind: "advance", stage: "qa" }],
      ),
    },
    {
      name: "approve",
      payload: makePayload({ kind: "approve", stage: "qa" }, []),
    },
    {
      name: "resolve_findings",
      payload: makePayload(
        { kind: "resolve_findings" },
        [{ kind: "validate", stage: "draft", phase: "draft" }],
      ),
    },
    {
      name: "finalize",
      payload: makePayload(
        { kind: "finalize" },
        [{ kind: "validate", stage: "repair", phase: "final" }],
      ),
    },
    {
      name: "done",
      payload: makePayload({ kind: "done" }, []),
    },
    {
      name: "unfinished",
      payload: makePayload(
        { kind: "unfinished" },
        [{ kind: "advance", stage: "spec" }],
      ),
    },
    {
      name: "failed",
      payload: makePayload(
        {
          kind: "failed",
          action: "starting qa with claude-code",
          message: "provider unavailable",
        },
        [],
      ),
    },
  ];

  it.each(table)("returns the $name payload verbatim", async ({ payload }) => {
    const postContinue = vi.fn().mockResolvedValue(payload);
    const api = makeApi(postContinue);

    const result = await continueRun("t", api);

    expect(postContinue).toHaveBeenCalledTimes(1);
    expect(postContinue).toHaveBeenCalledWith("t");
    expect(result).toEqual({
      steps: payload.steps,
      stop: payload.stop,
      status: payload.status,
    });
  });

  it("reports the freshest status the daemon sent, unmodified", async () => {
    const status = makeStatus("save_response", "qa");
    const payload = makePayload({ kind: "started", stage: "qa", provider: "claude-code" }, [], status);
    const api = makeApi(vi.fn().mockResolvedValue(payload));

    const result = await continueRun("t", api);

    expect(result.status).toBe(status);
  });

  it("calls postContinue with the given topic id, nothing else", async () => {
    const payload = makePayload({ kind: "done" }, []);
    const postContinue = vi.fn().mockResolvedValue(payload);
    const api = makeApi(postContinue);

    await continueRun("other-topic", api);

    expect(postContinue).toHaveBeenCalledWith("other-topic");
  });

  it("uses the production api by default (no api argument required)", () => {
    // Type-level check only: continueRun's second parameter must default to
    // PRODUCTION_API, so a caller can omit it entirely, exactly as before.
    expect(continueRun.length).toBeLessThanOrEqual(2);
  });
});

describe("continueRun failures", () => {
  it("wraps a transport error from postContinue as a failed stop", async () => {
    const api = makeApi(vi.fn().mockRejectedValue(new Error("daemon gone")));

    const result = await continueRun("t", api);

    expect(result).toEqual({
      steps: [],
      stop: { kind: "failed", action: "continuing the run", message: "daemon gone" },
      status: null,
    });
  });

  it("reports a non-Error rejection as text", async () => {
    const api = makeApi(vi.fn().mockRejectedValue("offline"));

    const result = await continueRun("t", api);

    expect(result.steps).toEqual([]);
    expect(result.status).toBeNull();
    expect(result.stop).toMatchObject({
      kind: "failed",
      action: "continuing the run",
      message: "offline",
    });
  });
});

describe("continueFailed", () => {
  it("is true only when the stop kind is failed", () => {
    const failed: ContinueResult = {
      steps: [],
      stop: { kind: "failed", action: "starting qa with claude-code", message: "provider unavailable" },
      status: null,
    };
    const notFailed: ContinueResult = {
      steps: [],
      stop: { kind: "approve", stage: "qa" },
      status: null,
    };
    expect(continueFailed(failed)).toBe(true);
    expect(continueFailed(notFailed)).toBe(false);
  });
});

// Every phrase below is byte-identical to the pre-T32 step-by-step-chain
// suite; only the step literals changed (`enqueue` -> `job`, and `validate`
// steps now carry `stage` alongside `phase`, per the daemon's wire shape).
describe("continueFeedback", () => {
  it("names the provider the next stage started with", () => {
    const result: ContinueResult = {
      steps: [
        { kind: "advance", stage: "qa" },
        { kind: "job", stage: "qa", provider: "claude-code" },
      ],
      stop: { kind: "started", stage: "qa", provider: "claude-code" },
      status: null,
    };
    expect(continueFeedback("draft", result)).toBe(
      "Approved draft — started qa with claude-code.",
    );
  });

  it("joins the steps it took with where the run now stands", () => {
    const result: ContinueResult = {
      steps: [{ kind: "validate", stage: "draft", phase: "draft" }],
      stop: { kind: "resolve_findings" },
      status: null,
    };
    expect(continueFeedback("qa", result)).toBe(
      "Approved qa — ran draft validation; findings need review.",
    );
  });

  it("hands the manual loop back to the user", () => {
    const result: ContinueResult = {
      steps: [{ kind: "advance", stage: "qa" }],
      stop: { kind: "manual", stage: "qa" },
      status: null,
    };
    expect(continueFeedback("draft", result)).toBe(
      "Approved draft — the qa prompt is ready for you to run.",
    );
  });

  it("says the prompt is ready when the model plan could not be read", () => {
    const result: ContinueResult = {
      steps: [{ kind: "advance", stage: "qa" }],
      stop: { kind: "plan_unreadable", stage: "qa" },
      status: null,
    };
    expect(continueFeedback("draft", result)).toBe(
      "Approved draft — the qa prompt is ready, but the model plan could not be read, so start the stage yourself.",
    );
  });

  it("points at the next approval, finalize, and export gates", () => {
    expect(
      continueFeedback("outline", {
        steps: [],
        stop: { kind: "approve", stage: "draft" },
        status: null,
      }),
    ).toBe("Approved outline — draft needs your approval.");
    expect(
      continueFeedback("repair", {
        steps: [{ kind: "validate", stage: "repair", phase: "final" }],
        stop: { kind: "finalize" },
        status: null,
      }),
    ).toBe("Approved repair — ran final validation; the run is ready to finalize.");
    expect(
      continueFeedback("repair", { steps: [], stop: { kind: "done" }, status: null }),
    ).toBe("Approved repair — the run is ready to export.");
  });

  it("reports the approval as done when a follow-up failed", () => {
    const result: ContinueResult = {
      steps: [{ kind: "advance", stage: "qa" }],
      stop: {
        kind: "failed",
        action: "starting qa with claude-code",
        message: "provider unavailable",
      },
      status: null,
    };
    expect(continueFeedback("draft", result)).toBe(
      "Approved draft, but starting qa with claude-code failed: provider unavailable",
    );
  });

  it("says more steps are waiting when the chain hit its bound", () => {
    expect(
      continueFeedback("spec", {
        steps: [{ kind: "advance", stage: "outline" }],
        stop: { kind: "unfinished" },
        status: null,
      }),
    ).toBe("Approved spec — wrote the outline prompt; more steps are waiting.");
  });

  it("does not describe a job step on its own -- the started stop already names it", () => {
    const result: ContinueResult = {
      steps: [{ kind: "job", stage: "qa", provider: "claude-code" }],
      stop: { kind: "started", stage: "qa", provider: "claude-code" },
      status: null,
    };
    expect(continueFeedback("draft", result)).toBe(
      "Approved draft — started qa with claude-code.",
    );
  });
});

/**
 * T34: the daemon now carries the chain across job completions (decision 9
 * addendum). `RunStatus.continuation` reports the latest chained job's
 * outcome; these two functions turn it into the same kind of feedback line
 * `continueFeedback` produces for an approval, but headed by what the job
 * itself did rather than by an approval.
 */
function makeContinuation(
  stop: ContinueStop,
  steps: ContinueStep[] = [],
  overrides: Partial<Omit<Continuation, "stop" | "steps">> = {},
): Continuation {
  return {
    job_id: "j1",
    stage: "draft",
    provider: "claude-code",
    after: "job",
    steps,
    stop,
    at: "2026-09-19T00:00:00.000Z",
    ...overrides,
  };
}

describe("chainFeedback", () => {
  // One entry per STOP_KINDS value, mirroring the continueFeedback table
  // above -- the daemon can report any of the nine back on `continuation`.
  it.each([
    {
      name: "started (no describable steps)",
      continuation: makeContinuation(
        { kind: "started", stage: "outline", provider: "claude-code" },
        [{ kind: "job", stage: "outline", provider: "claude-code" }],
        { stage: "spec" },
      ),
      expected: "After the spec job ran: started outline with claude-code.",
    },
    {
      name: "manual",
      continuation: makeContinuation(
        { kind: "manual", stage: "outline" },
        [{ kind: "advance", stage: "outline" }],
        { stage: "spec" },
      ),
      expected: "After the spec job ran: wrote the outline prompt; the outline prompt is ready for you to run.",
    },
    {
      name: "plan_unreadable",
      continuation: makeContinuation(
        { kind: "plan_unreadable", stage: "outline" },
        [{ kind: "advance", stage: "outline" }],
        { stage: "spec" },
      ),
      expected:
        "After the spec job ran: wrote the outline prompt; the outline prompt is ready, but the model plan could not be read, so start the stage yourself.",
    },
    {
      name: "approve",
      continuation: makeContinuation(
        { kind: "approve", stage: "draft" },
        [{ kind: "validate", stage: "draft", phase: "draft" }],
        { stage: "draft" },
      ),
      expected: "After the draft job ran: ran draft validation; draft needs your approval.",
    },
    {
      name: "resolve_findings",
      continuation: makeContinuation(
        { kind: "resolve_findings" },
        [{ kind: "validate", stage: "draft", phase: "draft" }],
        { stage: "draft" },
      ),
      expected: "After the draft job ran: ran draft validation; findings need review.",
    },
    {
      name: "finalize",
      continuation: makeContinuation(
        { kind: "finalize" },
        [{ kind: "validate", stage: "repair", phase: "final" }],
        { stage: "repair" },
      ),
      expected: "After the repair job ran: ran final validation; the run is ready to finalize.",
    },
    {
      name: "done (no describable steps)",
      continuation: makeContinuation({ kind: "done" }, [], { stage: "repair" }),
      expected: "After the repair job ran: the run is ready to export.",
    },
    {
      name: "unfinished",
      continuation: makeContinuation(
        { kind: "unfinished" },
        [{ kind: "advance", stage: "outline" }],
        { stage: "spec" },
      ),
      expected: "After the spec job ran: wrote the outline prompt; more steps are waiting.",
    },
    {
      name: "failed",
      continuation: makeContinuation(
        {
          kind: "failed",
          action: "starting qa with claude-code",
          message: "provider unavailable",
        },
        [{ kind: "advance", stage: "qa" }],
        { stage: "draft" },
      ),
      expected:
        "After the draft job ran: wrote the qa prompt; starting qa with claude-code failed: provider unavailable.",
    },
  ])("$name", ({ continuation, expected }) => {
    expect(chainFeedback(continuation)).toBe(expected);
  });

  it("uses the module-jobs prefix for a batch continuation", () => {
    const continuation = makeContinuation(
      { kind: "started", stage: "qa", provider: "claude-code", count: 3 },
      [],
      { stage: "draft", after: "batch" },
    );
    expect(chainFeedback(continuation)).toBe(
      "After the draft module jobs ran: 3 module jobs started for qa with claude-code.",
    );
  });
});

describe("chainFailed", () => {
  it("is true only when the continuation's stop kind is failed", () => {
    const failed = makeContinuation({
      kind: "failed",
      action: "starting qa with claude-code",
      message: "provider unavailable",
    });
    const notFailed = makeContinuation({ kind: "approve", stage: "qa" });
    expect(chainFailed(failed)).toBe(true);
    expect(chainFailed(notFailed)).toBe(false);
  });
});

describe("continueOnlyFeedback", () => {
  it("names the provider the run started with, headed by 'Continued'", () => {
    const result: ContinueResult = {
      steps: [
        { kind: "advance", stage: "qa" },
        { kind: "job", stage: "qa", provider: "claude-code" },
      ],
      stop: { kind: "started", stage: "qa", provider: "claude-code" },
      status: null,
    };
    expect(continueOnlyFeedback(result)).toBe("Continued — started qa with claude-code.");
  });

  it("joins the steps it took with where the run now stands", () => {
    const result: ContinueResult = {
      steps: [{ kind: "validate", stage: "draft", phase: "draft" }],
      stop: { kind: "resolve_findings" },
      status: null,
    };
    expect(continueOnlyFeedback(result)).toBe(
      "Continued — ran draft validation; findings need review.",
    );
  });

  it("hands the manual loop back to the user without double-naming the stage", () => {
    const result: ContinueResult = {
      steps: [{ kind: "advance", stage: "qa" }],
      stop: { kind: "manual", stage: "qa" },
      status: null,
    };
    expect(continueOnlyFeedback(result)).toBe(
      "Continued — the qa prompt is ready for you to run.",
    );
  });

  it("reports a failure in the same shape continueFeedback uses, headed by 'Continuing failed'", () => {
    const result: ContinueResult = {
      steps: [{ kind: "advance", stage: "qa" }],
      stop: {
        kind: "failed",
        action: "starting qa with claude-code",
        message: "provider unavailable",
      },
      status: null,
    };
    expect(continueOnlyFeedback(result)).toBe(
      "Continuing failed: starting qa with claude-code failed: provider unavailable",
    );
  });
});
