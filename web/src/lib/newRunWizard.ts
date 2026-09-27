/**
 * The New-course wizard's form and lifecycle state as one pure reducer
 * (Phase 6 decision 3). The page keeps only its remote data (blueprints,
 * the model plan and their errors, the blueprint-restore flag) in useState.
 * `wizardDraft(state)` is exactly the NewRunDraft that saveNewRunDraft
 * persists, so the draft format does not change.
 */

import type { NewRunDraft, NewRunStep, NewRunTopicMode } from "./newRunDraft";

// Step order is deliberately structural (spec §6); the blueprint-selection
// step slots in between "topic" and "plan" exactly as anticipated.
export const WIZARD_STEPS = [
  "learner",
  "topic",
  "blueprint",
  "plan",
  "confirm",
] as const satisfies readonly NewRunStep[];

export interface WizardState extends NewRunDraft {
  /** The draft restored at mount (null for a fresh wizard); never changes after. */
  initialDraft: NewRunDraft | null;
  restoredNoteVisible: boolean;
  creating: boolean;
  createError: unknown;
}

/** The free-text draft fields a form control edits directly. */
export type WizardTextField =
  | "profileId"
  | "id"
  | "title"
  | "brief"
  | "audience"
  | "goals"
  | "toml"
  | "selectedBlueprint"
  | "timeBudget";

export type WizardAction =
  | { type: "setField"; field: WizardTextField; value: string }
  | { type: "setMode"; mode: NewRunTopicMode }
  | { type: "next" }
  | { type: "back" }
  | { type: "goToStep"; step: NewRunStep }
  | { type: "dismissRestoreNote" }
  | { type: "startOver" }
  | { type: "createStart" }
  | { type: "topicCreated"; id: string }
  | { type: "profileAttached" }
  | { type: "createSuccess" }
  | { type: "createFailure"; error: unknown };

const EMPTY_DRAFT: NewRunDraft = {
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

// Key order matches what the page always persisted.
function pickDraft(source: NewRunDraft): NewRunDraft {
  return {
    step: source.step,
    profileId: source.profileId,
    mode: source.mode,
    id: source.id,
    title: source.title,
    brief: source.brief,
    audience: source.audience,
    goals: source.goals,
    toml: source.toml,
    selectedBlueprint: source.selectedBlueprint,
    timeBudget: source.timeBudget,
    createdId: source.createdId,
    attached: source.attached,
  };
}

/** The wizard at mount: a restored draft (with the restore note) or today's defaults. */
export function initWizardState(draft: NewRunDraft | null): WizardState {
  return {
    initialDraft: draft,
    restoredNoteVisible: draft !== null,
    ...pickDraft(draft ?? EMPTY_DRAFT),
    creating: false,
    createError: null,
  };
}

/** The persisted part of the wizard: the 13 draft fields and nothing else. */
export function wizardDraft(state: WizardState): NewRunDraft {
  return pickDraft(state);
}

function withStep(state: WizardState, step: NewRunStep): WizardState {
  return state.step === step ? state : { ...state, step };
}

function stepBy(step: NewRunStep, offset: 1 | -1): NewRunStep {
  const index = WIZARD_STEPS.indexOf(step) + offset;
  return index >= 0 && index < WIZARD_STEPS.length ? WIZARD_STEPS[index] : step;
}

export function wizardReducer(state: WizardState, action: WizardAction): WizardState {
  switch (action.type) {
    case "setField":
      return state[action.field] === action.value
        ? state
        : { ...state, [action.field]: action.value };
    case "setMode":
      return state.mode === action.mode ? state : { ...state, mode: action.mode };
    case "next":
      return withStep(state, stepBy(state.step, 1));
    case "back":
      return withStep(state, stepBy(state.step, -1));
    case "goToStep":
      return withStep(state, action.step);
    case "dismissRestoreNote":
      return { ...state, restoredNoteVisible: false };
    case "startOver":
      // `creating` is untouched: Start over is disabled while creating.
      return { ...state, ...EMPTY_DRAFT, restoredNoteVisible: false, createError: null };
    case "createStart":
      return { ...state, creating: true, createError: null };
    case "topicCreated":
      return { ...state, createdId: action.id };
    case "profileAttached":
      return { ...state, attached: true };
    case "createSuccess":
      return { ...state, creating: false };
    case "createFailure":
      return { ...state, creating: false, createError: action.error };
  }
}
