import { afterEach, describe, expect, it } from "vitest";
import { loadNewRunDraft, saveNewRunDraft } from "./newRunDraft";
import type { NewRunDraft, NewRunStep } from "./newRunDraft";
import { initWizardState, wizardDraft, wizardReducer } from "./newRunWizard";
import type { WizardAction, WizardState, WizardTextField } from "./newRunWizard";

// Phase 6 decision 3: the New-course wizard's 17 form + lifecycle states
// live in one pure reducer. The remote-data states (blueprints,
// blueprintsError, restoringBlueprints, plan, planError) stay useState in the
// page. The draft format does not change: wizardDraft(state) is exactly the
// NewRunDraft that saveNewRunDraft persists.

function makeDraft(overrides: Partial<NewRunDraft> = {}): NewRunDraft {
  return {
    step: "topic",
    profileId: "p1",
    mode: "describe",
    id: "intro-to-sql",
    title: "Intro to SQL",
    brief: "A hands-on introduction.",
    audience: "analysts",
    goals: "Join tables\nAggregate rows",
    toml: "",
    selectedBlueprint: "exam-preparation",
    timeBudget: "90",
    createdId: null,
    attached: false,
    ...overrides,
  };
}

const DEFAULT_DRAFT: NewRunDraft = {
  step: "learner",
  profileId: "",
  mode: "describe",
  id: "",
  title: "",
  brief: "",
  audience: "",
  goals: "",
  toml: "",
  selectedBlueprint: "",
  timeBudget: "",
  createdId: null,
  attached: false,
};

function stateAt(step: NewRunStep, overrides: Partial<WizardState> = {}): WizardState {
  return { ...initWizardState(null), step, ...overrides };
}

function run(state: WizardState, ...actions: WizardAction[]): WizardState {
  return actions.reduce(wizardReducer, state);
}

function deepFreeze<T>(value: T): T {
  if (value && typeof value === "object" && !Object.isFrozen(value)) {
    Object.freeze(value);
    for (const inner of Object.values(value as Record<string, unknown>)) deepFreeze(inner);
  }
  return value;
}

afterEach(() => {
  sessionStorage.clear();
});

describe("initWizardState", () => {
  it("starts a fresh wizard with today's defaults and no restore note", () => {
    expect(initWizardState(null)).toEqual({
      initialDraft: null,
      restoredNoteVisible: false,
      step: "learner",
      profileId: "",
      mode: "describe",
      id: "",
      title: "",
      brief: "",
      audience: "",
      goals: "",
      toml: "",
      selectedBlueprint: "",
      timeBudget: "",
      createdId: null,
      attached: false,
      creating: false,
      createError: null,
    });
  });

  it("restores every draft field, keeps the draft, and shows the restore note", () => {
    const draft = makeDraft({ step: "confirm", createdId: "intro-to-sql", attached: true });
    expect(initWizardState(draft)).toEqual({
      initialDraft: draft,
      restoredNoteVisible: true,
      ...draft,
      creating: false,
      createError: null,
    });
  });

  it("is pure: it never reads storage itself", () => {
    saveNewRunDraft(makeDraft());
    expect(initWizardState(null)).toEqual(initWizardState(null));
    expect(initWizardState(null).step).toBe("learner");
    expect(initWizardState(null).restoredNoteVisible).toBe(false);
  });
});

describe("wizardDraft", () => {
  it.each([
    ["a describe-mode draft at topic", makeDraft()],
    ["a toml-mode draft at plan", makeDraft({ step: "plan", mode: "toml", toml: 'id = "x"' })],
    [
      "a confirm draft with create-retry markers",
      makeDraft({ step: "confirm", createdId: "intro-to-sql", attached: true }),
    ],
    ["the pristine draft", DEFAULT_DRAFT],
  ])("round-trips %s through initWizardState", (_label, draft) => {
    expect(wizardDraft(initWizardState(draft))).toEqual(draft);
  });

  it("is the default draft for a fresh wizard", () => {
    expect(wizardDraft(initWizardState(null))).toEqual(DEFAULT_DRAFT);
  });

  it("carries only the 13 draft fields, never lifecycle or note state", () => {
    const state = stateAt("confirm", {
      creating: true,
      createError: new Error("boom"),
      restoredNoteVisible: true,
      initialDraft: makeDraft(),
    });
    expect(Object.keys(wizardDraft(state)).sort()).toEqual(Object.keys(DEFAULT_DRAFT).sort());
  });

  it("is exactly what saveNewRunDraft persists and loadNewRunDraft restores", () => {
    const state = run(
      initWizardState(null),
      { type: "next" },
      { type: "setField", field: "id", value: "wizard-topic" },
      { type: "setField", field: "title", value: "Wizard Topic" },
    );
    saveNewRunDraft(wizardDraft(state));
    expect(loadNewRunDraft()).toEqual(wizardDraft(state));
    expect(wizardDraft(initWizardState(loadNewRunDraft()))).toEqual(wizardDraft(state));
  });
});

describe("wizardReducer: field edits", () => {
  const fields: WizardTextField[] = [
    "profileId",
    "id",
    "title",
    "brief",
    "audience",
    "goals",
    "toml",
    "selectedBlueprint",
    "timeBudget",
  ];

  it.each(fields)("setField %s changes only that field", (field) => {
    const before = initWizardState(makeDraft());
    const after = wizardReducer(before, { type: "setField", field, value: "edited" });
    expect(after).toEqual({ ...before, [field]: "edited" });
  });

  it("setField can clear a field (blueprint selection falls back to none)", () => {
    const before = initWizardState(makeDraft({ selectedBlueprint: "exam-preparation" }));
    const after = wizardReducer(before, {
      type: "setField",
      field: "selectedBlueprint",
      value: "",
    });
    expect(after).toEqual({ ...before, selectedBlueprint: "" });
  });

  it("setMode switches the topic entry mode and keeps both modes' input", () => {
    const before = initWizardState(makeDraft({ toml: 'id = "x"' }));
    const toToml = wizardReducer(before, { type: "setMode", mode: "toml" });
    expect(toToml).toEqual({ ...before, mode: "toml" });
    const back = wizardReducer(toToml, { type: "setMode", mode: "describe" });
    expect(back).toEqual(before);
  });
});

describe("wizardReducer: step moves", () => {
  it("next walks learner → topic → blueprint → plan → confirm and stops there", () => {
    const steps: NewRunStep[] = [];
    let state = initWizardState(null);
    for (let i = 0; i < 6; i++) {
      state = wizardReducer(state, { type: "next" });
      steps.push(state.step);
    }
    expect(steps).toEqual(["topic", "blueprint", "plan", "confirm", "confirm", "confirm"]);
  });

  it("back walks confirm → plan → blueprint → topic → learner and stops there", () => {
    const steps: NewRunStep[] = [];
    let state = stateAt("confirm");
    for (let i = 0; i < 6; i++) {
      state = wizardReducer(state, { type: "back" });
      steps.push(state.step);
    }
    expect(steps).toEqual(["plan", "blueprint", "topic", "learner", "learner", "learner"]);
  });

  it("step moves change nothing but the step (input survives Back)", () => {
    const before = initWizardState(makeDraft({ step: "plan" }));
    expect(wizardReducer(before, { type: "back" })).toEqual({ ...before, step: "blueprint" });
    expect(wizardReducer(before, { type: "next" })).toEqual({ ...before, step: "confirm" });
  });

  it("goToStep moves to an absolute step and is idempotent", () => {
    const before = initWizardState(makeDraft({ step: "topic" }));
    const once = wizardReducer(before, { type: "goToStep", step: "blueprint" });
    expect(once).toEqual({ ...before, step: "blueprint" });
    expect(wizardReducer(once, { type: "goToStep", step: "blueprint" })).toEqual(once);
  });
});

describe("wizardReducer: restore note and Start over", () => {
  it("dismissRestoreNote hides the note and keeps the restored input", () => {
    const before = initWizardState(makeDraft());
    expect(wizardReducer(before, { type: "dismissRestoreNote" })).toEqual({
      ...before,
      restoredNoteVisible: false,
    });
  });

  it("startOver resets every draft field, the markers, the note and the create error", () => {
    const before = stateAt("confirm", {
      ...makeDraft({ step: "confirm", createdId: "intro-to-sql", attached: true }),
      initialDraft: makeDraft(),
      restoredNoteVisible: true,
      createError: new Error("advance failed"),
    });
    const after = wizardReducer(before, { type: "startOver" });
    expect(wizardDraft(after)).toEqual(DEFAULT_DRAFT);
    expect(after.restoredNoteVisible).toBe(false);
    expect(after.createError).toBeNull();
    expect(after.creating).toBe(false);
  });

  it("startOver returns a Paste-TOML draft to Describe it with no pasted TOML", () => {
    // The fixture above is already in describe mode with empty TOML, so it
    // cannot tell a reset mode/toml from a kept one; this draft can.
    const before = initWizardState(
      makeDraft({ step: "plan", mode: "toml", toml: 'id = "pasted"\ntitle = "Pasted"' }),
    );
    const after = wizardReducer(before, { type: "startOver" });
    expect(after.mode).toBe("describe");
    expect(after.toml).toBe("");
    expect(wizardDraft(after)).toEqual(DEFAULT_DRAFT);
  });
});

describe("wizardReducer: course creation lifecycle", () => {
  it("createStart marks creating and clears a previous error", () => {
    const before = stateAt("confirm", { createError: new Error("earlier") });
    expect(wizardReducer(before, { type: "createStart" })).toEqual({
      ...before,
      creating: true,
      createError: null,
    });
  });

  it("topicCreated records the created id; profileAttached records the attach", () => {
    const creating = run(stateAt("confirm"), { type: "createStart" });
    const created = wizardReducer(creating, { type: "topicCreated", id: "wizard-topic" });
    expect(created).toEqual({ ...creating, createdId: "wizard-topic" });
    const attached = wizardReducer(created, { type: "profileAttached" });
    expect(attached).toEqual({ ...created, attached: true });
  });

  it("createSuccess ends creating", () => {
    const before = run(
      stateAt("confirm"),
      { type: "createStart" },
      { type: "topicCreated", id: "wizard-topic" },
    );
    expect(wizardReducer(before, { type: "createSuccess" })).toEqual({
      ...before,
      creating: false,
    });
  });

  it("createFailure ends creating, records the error and keeps the retry markers", () => {
    const error = new Error("run initialization failed");
    const failed = run(
      stateAt("confirm", { profileId: "p1" }),
      { type: "createStart" },
      { type: "topicCreated", id: "wizard-topic" },
      { type: "profileAttached" },
      { type: "createFailure", error },
    );
    expect(failed.creating).toBe(false);
    expect(failed.createError).toBe(error);
    expect(failed.createdId).toBe("wizard-topic");
    expect(failed.attached).toBe(true);
    expect(failed.step).toBe("confirm");

    const retry = wizardReducer(failed, { type: "createStart" });
    expect(retry).toEqual({ ...failed, creating: true, createError: null });
  });
});

describe("wizardReducer: purity", () => {
  const actions: WizardAction[] = [
    { type: "setField", field: "title", value: "t" },
    { type: "setMode", mode: "toml" },
    { type: "next" },
    { type: "back" },
    { type: "goToStep", step: "plan" },
    { type: "dismissRestoreNote" },
    { type: "startOver" },
    { type: "createStart" },
    { type: "topicCreated", id: "x" },
    { type: "profileAttached" },
    { type: "createSuccess" },
    { type: "createFailure", error: new Error("e") },
  ];

  it.each(actions.map((action) => [action.type, action] as const))(
    "%s never mutates the previous state",
    (_type, action) => {
      const before = deepFreeze(initWizardState(makeDraft({ step: "blueprint" })));
      const snapshot = structuredClone(before);
      expect(() => wizardReducer(before, action)).not.toThrow();
      expect(before).toEqual(snapshot);
    },
  );
});
