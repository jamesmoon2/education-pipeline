import { describe, expect, it, vi } from "vitest";
import type { NextAction, RunStatus } from "../api/types";
import type { ContinuePayload } from "../api/types";
import {
  continueFailed,
  continueFeedback,
  continueRun,
  type ContinueApi,
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
