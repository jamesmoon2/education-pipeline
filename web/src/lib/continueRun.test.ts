import { describe, expect, it, vi } from "vitest";
import type { AdvanceResult, NextAction, PlanPayload, PlanStage, RunStatus } from "../api/types";
import {
  MAX_CONTINUE_STEPS,
  continueFeedback,
  continueRun,
  type ContinueApi,
} from "./continueRun";

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

function makeAdvance(status: RunStatus): AdvanceResult {
  return { performed: "write_prompt", status };
}

function makePlanStage(stage: string, provider: string | null): PlanStage {
  return { stage, provider, model: null, effort: null, recommendation: "", warning: null };
}

function makePlan(provider: string, stages: PlanStage[] = []): PlanPayload {
  return { provider, plan_sha256: "sha-plan", stages };
}

type MockedApi = {
  [K in keyof ContinueApi]: ReturnType<typeof vi.fn>;
} & ContinueApi;

/**
 * Every api function is mocked and every test states the responses it needs;
 * an unstubbed call rejects loudly rather than silently resolving undefined.
 */
function makeApi(overrides: Partial<ContinueApi> = {}): MockedApi {
  const unstubbed = (name: string) => () =>
    Promise.reject(new Error(`unexpected ${name} call`));
  return {
    getRunStatus: vi.fn(unstubbed("getRunStatus")),
    postAdvance: vi.fn(unstubbed("postAdvance")),
    postValidate: vi.fn(unstubbed("postValidate")),
    enqueueJob: vi.fn(unstubbed("enqueueJob")),
    getConfigPlan: vi.fn(unstubbed("getConfigPlan")),
    ...overrides,
  } as MockedApi;
}

describe("continueRun stopping actions", () => {
  it("stops on approve without touching anything", async () => {
    const api = makeApi({
      getRunStatus: vi.fn().mockResolvedValue(makeStatus("approve", "qa")),
    });
    const result = await continueRun("t", api);
    expect(result.stop).toEqual({ kind: "approve", stage: "qa" });
    expect(result.steps).toEqual([]);
    expect(api.postAdvance).not.toHaveBeenCalled();
    expect(api.enqueueJob).not.toHaveBeenCalled();
  });

  it("stops on resolve_findings", async () => {
    const api = makeApi({
      getRunStatus: vi.fn().mockResolvedValue(makeStatus("resolve_findings", "repair")),
    });
    const result = await continueRun("t", api);
    expect(result.stop).toEqual({ kind: "resolve_findings" });
    expect(result.steps).toEqual([]);
  });

  it("never finalizes or exports on its own", async () => {
    const finalize = makeApi({
      getRunStatus: vi.fn().mockResolvedValue(makeStatus("finalize", null)),
    });
    expect((await continueRun("t", finalize)).stop).toEqual({ kind: "finalize" });

    const done = makeApi({
      getRunStatus: vi.fn().mockResolvedValue(makeStatus("done", null)),
    });
    const result = await continueRun("t", done);
    expect(result.stop).toEqual({ kind: "done" });
    expect(result.steps).toEqual([]);
    // The chain only ever calls these four; finalize/export have no adapter.
    expect(Object.keys(done).sort()).toEqual([
      "enqueueJob",
      "getConfigPlan",
      "getRunStatus",
      "postAdvance",
      "postValidate",
    ]);
  });

  it("stops on an action it does not know", async () => {
    const api = makeApi({
      getRunStatus: vi
        .fn()
        .mockResolvedValue(makeStatus("teleport" as NextAction["action"], null)),
    });
    expect((await continueRun("t", api)).stop).toEqual({ kind: "unfinished" });
  });

  it("reports the freshest status it read", async () => {
    const status = makeStatus("approve", "qa");
    const api = makeApi({ getRunStatus: vi.fn().mockResolvedValue(status) });
    expect((await continueRun("t", api)).status).toBe(status);
  });
});

describe("continueRun mechanical steps", () => {
  it("advances a write_prompt and reuses the status advance returned", async () => {
    const api = makeApi({
      getRunStatus: vi.fn().mockResolvedValue(makeStatus("write_prompt", "qa")),
      postAdvance: vi.fn().mockResolvedValue(makeAdvance(makeStatus("approve", "qa"))),
    });
    const result = await continueRun("t", api);
    expect(api.postAdvance).toHaveBeenCalledWith("t");
    expect(api.getRunStatus).toHaveBeenCalledTimes(1);
    expect(result.steps).toEqual([{ kind: "advance", stage: "qa" }]);
    expect(result.stop).toEqual({ kind: "approve", stage: "qa" });
  });

  it("validates the draft phase on the draft stage and the final phase elsewhere", async () => {
    const draft = makeApi({
      getRunStatus: vi
        .fn()
        .mockResolvedValueOnce(makeStatus("validate", "draft"))
        .mockResolvedValueOnce(makeStatus("approve", "qa")),
      postValidate: vi.fn().mockResolvedValue({}),
    });
    const draftResult = await continueRun("t", draft);
    expect(draft.postValidate).toHaveBeenCalledWith("t", "draft");
    expect(draftResult.steps).toEqual([{ kind: "validate", phase: "draft" }]);
    // The validate payload is a report, so the loop re-reads the status.
    expect(draft.getRunStatus).toHaveBeenCalledTimes(2);

    const final = makeApi({
      getRunStatus: vi
        .fn()
        .mockResolvedValueOnce(makeStatus("validate", "repair"))
        .mockResolvedValueOnce(makeStatus("finalize", null)),
      postValidate: vi.fn().mockResolvedValue({}),
    });
    const finalResult = await continueRun("t", final);
    expect(final.postValidate).toHaveBeenCalledWith("t", "final");
    expect(finalResult.steps).toEqual([{ kind: "validate", phase: "final" }]);
    expect(finalResult.stop).toEqual({ kind: "finalize" });
  });

  it("chains a prompt write into a provider job", async () => {
    const api = makeApi({
      getRunStatus: vi.fn().mockResolvedValue(makeStatus("write_prompt", "qa")),
      postAdvance: vi
        .fn()
        .mockResolvedValue(makeAdvance(makeStatus("save_response", "qa"))),
      getConfigPlan: vi.fn().mockResolvedValue(makePlan("claude-code")),
      enqueueJob: vi.fn().mockResolvedValue({}),
    });
    const result = await continueRun("t", api);
    expect(api.enqueueJob).toHaveBeenCalledWith("t");
    expect(result.steps).toEqual([
      { kind: "advance", stage: "qa" },
      { kind: "enqueue", stage: "qa", provider: "claude-code" },
    ]);
    expect(result.stop).toEqual({ kind: "started", stage: "qa", provider: "claude-code" });
  });

  it("validates and then stops where the findings need review", async () => {
    const api = makeApi({
      getRunStatus: vi
        .fn()
        .mockResolvedValueOnce(makeStatus("validate", "draft"))
        .mockResolvedValueOnce(makeStatus("resolve_findings", "draft")),
      postValidate: vi.fn().mockResolvedValue({}),
    });
    const result = await continueRun("t", api);
    expect(result.steps).toEqual([{ kind: "validate", phase: "draft" }]);
    expect(result.stop).toEqual({ kind: "resolve_findings" });
  });

  it("stops after a bounded number of steps", async () => {
    const api = makeApi({
      getRunStatus: vi.fn().mockResolvedValue(makeStatus("write_prompt", "spec")),
      postAdvance: vi
        .fn()
        .mockResolvedValue(makeAdvance(makeStatus("write_prompt", "spec"))),
    });
    const result = await continueRun("t", api);
    expect(api.postAdvance).toHaveBeenCalledTimes(MAX_CONTINUE_STEPS);
    expect(result.steps).toHaveLength(MAX_CONTINUE_STEPS);
    expect(result.stop).toEqual({ kind: "unfinished" });
  });
});

describe("continueRun provider decision", () => {
  it("starts the stage with the plan's default provider", async () => {
    const api = makeApi({
      getRunStatus: vi.fn().mockResolvedValue(makeStatus("save_response", "draft")),
      getConfigPlan: vi.fn().mockResolvedValue(makePlan("codex")),
      enqueueJob: vi.fn().mockResolvedValue({}),
    });
    const result = await continueRun("t", api);
    expect(result.stop).toEqual({ kind: "started", stage: "draft", provider: "codex" });
  });

  it("prefers the stage's own provider over the plan default", async () => {
    const api = makeApi({
      getRunStatus: vi.fn().mockResolvedValue(makeStatus("save_response", "draft")),
      getConfigPlan: vi.fn().mockResolvedValue(
        makePlan("codex", [
          makePlanStage("qa", "claude-code"),
          makePlanStage("draft", "claude-code"),
        ]),
      ),
      enqueueJob: vi.fn().mockResolvedValue({}),
    });
    const result = await continueRun("t", api);
    expect(result.stop).toEqual({
      kind: "started",
      stage: "draft",
      provider: "claude-code",
    });
  });

  it("falls back to the plan default when the stage has no provider of its own", async () => {
    const api = makeApi({
      getRunStatus: vi.fn().mockResolvedValue(makeStatus("save_response", "draft")),
      getConfigPlan: vi
        .fn()
        .mockResolvedValue(makePlan("codex", [makePlanStage("draft", null)])),
      enqueueJob: vi.fn().mockResolvedValue({}),
    });
    const result = await continueRun("t", api);
    expect(result.stop).toEqual({ kind: "started", stage: "draft", provider: "codex" });
  });

  it("stops for the manual loop when the plan default is manual", async () => {
    const api = makeApi({
      getRunStatus: vi.fn().mockResolvedValue(makeStatus("save_response", "draft")),
      getConfigPlan: vi.fn().mockResolvedValue(makePlan("manual")),
    });
    const result = await continueRun("t", api);
    expect(result.stop).toEqual({ kind: "manual", stage: "draft" });
    expect(api.enqueueJob).not.toHaveBeenCalled();
  });

  it("stops for the manual loop when only this stage is manual", async () => {
    const api = makeApi({
      getRunStatus: vi.fn().mockResolvedValue(makeStatus("save_response", "draft")),
      getConfigPlan: vi
        .fn()
        .mockResolvedValue(makePlan("claude-code", [makePlanStage("draft", "manual")])),
    });
    const result = await continueRun("t", api);
    expect(result.stop).toEqual({ kind: "manual", stage: "draft" });
    expect(api.enqueueJob).not.toHaveBeenCalled();
  });

  it("stops gracefully when the plan cannot be read", async () => {
    const api = makeApi({
      getRunStatus: vi.fn().mockResolvedValue(makeStatus("save_response", "draft")),
      getConfigPlan: vi.fn().mockRejectedValue(new Error("plan unreadable")),
    });
    const result = await continueRun("t", api);
    expect(result.stop).toEqual({ kind: "plan_unreadable", stage: "draft" });
    expect(api.enqueueJob).not.toHaveBeenCalled();
  });

  it("stops without guessing when save_response names no stage", async () => {
    const api = makeApi({
      getRunStatus: vi.fn().mockResolvedValue(makeStatus("save_response", null)),
    });
    expect((await continueRun("t", api)).stop).toEqual({ kind: "unfinished" });
    expect(api.getConfigPlan).not.toHaveBeenCalled();
  });
});

describe("continueRun failures", () => {
  it("reports a failed status read", async () => {
    const api = makeApi({
      getRunStatus: vi.fn().mockRejectedValue(new Error("daemon gone")),
    });
    const result = await continueRun("t", api);
    expect(result.stop).toEqual({
      kind: "failed",
      action: "reading the run status",
      message: "daemon gone",
    });
    expect(result.status).toBeNull();
  });

  it("reports a failed advance and keeps the steps taken before it", async () => {
    const api = makeApi({
      getRunStatus: vi
        .fn()
        .mockResolvedValueOnce(makeStatus("validate", "draft"))
        .mockResolvedValueOnce(makeStatus("write_prompt", "qa")),
      postValidate: vi.fn().mockResolvedValue({}),
      postAdvance: vi.fn().mockRejectedValue(new Error("job j1 is running")),
    });
    const result = await continueRun("t", api);
    expect(result.steps).toEqual([{ kind: "validate", phase: "draft" }]);
    expect(result.stop).toEqual({
      kind: "failed",
      action: "writing the qa prompt",
      message: "job j1 is running",
    });
  });

  it("reports a failed validation", async () => {
    const api = makeApi({
      getRunStatus: vi.fn().mockResolvedValue(makeStatus("validate", "repair")),
      postValidate: vi.fn().mockRejectedValue(new Error("validator crashed")),
    });
    expect((await continueRun("t", api)).stop).toEqual({
      kind: "failed",
      action: "final validation",
      message: "validator crashed",
    });
  });

  it("reports a failed job start and records no enqueue step", async () => {
    const api = makeApi({
      getRunStatus: vi.fn().mockResolvedValue(makeStatus("save_response", "qa")),
      getConfigPlan: vi.fn().mockResolvedValue(makePlan("claude-code")),
      enqueueJob: vi.fn().mockRejectedValue(new Error("provider unavailable")),
    });
    const result = await continueRun("t", api);
    expect(result.steps).toEqual([]);
    expect(result.stop).toEqual({
      kind: "failed",
      action: "starting qa with claude-code",
      message: "provider unavailable",
    });
  });

  it("reports a non-Error rejection as text", async () => {
    const api = makeApi({ getRunStatus: vi.fn().mockRejectedValue("offline") });
    expect((await continueRun("t", api)).stop).toMatchObject({ message: "offline" });
  });
});

describe("continueFeedback", () => {
  it("names the provider the next stage started with", () => {
    const result = {
      steps: [
        { kind: "advance", stage: "qa" },
        { kind: "enqueue", stage: "qa", provider: "claude-code" },
      ],
      stop: { kind: "started", stage: "qa", provider: "claude-code" },
      status: null,
    } as const;
    expect(continueFeedback("draft", result)).toBe(
      "Approved draft — started qa with claude-code.",
    );
  });

  it("joins the steps it took with where the run now stands", () => {
    const result = {
      steps: [{ kind: "validate", phase: "draft" }],
      stop: { kind: "resolve_findings" },
      status: null,
    } as const;
    expect(continueFeedback("qa", result)).toBe(
      "Approved qa — ran draft validation; findings need review.",
    );
  });

  it("hands the manual loop back to the user", () => {
    const result = {
      steps: [{ kind: "advance", stage: "qa" }],
      stop: { kind: "manual", stage: "qa" },
      status: null,
    } as const;
    expect(continueFeedback("draft", result)).toBe(
      "Approved draft — the qa prompt is ready for you to run.",
    );
  });

  it("says the prompt is ready when the model plan could not be read", () => {
    const result = {
      steps: [{ kind: "advance", stage: "qa" }],
      stop: { kind: "plan_unreadable", stage: "qa" },
      status: null,
    } as const;
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
        steps: [{ kind: "validate", phase: "final" }],
        stop: { kind: "finalize" },
        status: null,
      }),
    ).toBe("Approved repair — ran final validation; the run is ready to finalize.");
    expect(
      continueFeedback("repair", { steps: [], stop: { kind: "done" }, status: null }),
    ).toBe("Approved repair — the run is ready to export.");
  });

  it("reports the approval as done when a follow-up failed", () => {
    const result = {
      steps: [{ kind: "advance", stage: "qa" }],
      stop: {
        kind: "failed",
        action: "starting qa with claude-code",
        message: "provider unavailable",
      },
      status: null,
    } as const;
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
});
