/**
 * Session-scoped persistence for the New-course wizard so navigating away
 * mid-flow (e.g. to Profiles or Settings) does not destroy typed input.
 * Storage access never throws: an unavailable sessionStorage degrades to a
 * wizard without persistence, and anything invalid in storage loads as null.
 */

export const NEW_RUN_DRAFT_KEY = "ep.newrun.draft";

const DRAFT_VERSION = 1;

const STEPS = ["learner", "topic", "blueprint", "plan", "confirm"] as const;
export type NewRunStep = (typeof STEPS)[number];

const MODES = ["describe", "toml"] as const;
export type NewRunTopicMode = (typeof MODES)[number];

export interface NewRunDraft {
  step: NewRunStep;
  profileId: string;
  mode: NewRunTopicMode;
  id: string;
  title: string;
  brief: string;
  audience: string;
  goals: string;
  toml: string;
  selectedBlueprint: string;
  timeBudget: string;
  createdId: string | null;
  attached: boolean;
}

const STRING_FIELDS = [
  "profileId",
  "id",
  "title",
  "brief",
  "audience",
  "goals",
  "toml",
  "selectedBlueprint",
  "timeBudget",
] as const;

function parseDraft(value: unknown): NewRunDraft | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return null;
  const record = value as Record<string, unknown>;
  if (record.version !== DRAFT_VERSION) return null;
  const step = record.step;
  if (typeof step !== "string" || !(STEPS as readonly string[]).includes(step)) return null;
  const mode = record.mode;
  if (typeof mode !== "string" || !(MODES as readonly string[]).includes(mode)) return null;
  for (const field of STRING_FIELDS) {
    if (typeof record[field] !== "string") return null;
  }
  const createdId = record.createdId;
  if (createdId !== null && typeof createdId !== "string") return null;
  const attached = record.attached;
  if (typeof attached !== "boolean") return null;
  return {
    step: step as NewRunStep,
    profileId: record.profileId as string,
    mode: mode as NewRunTopicMode,
    id: record.id as string,
    title: record.title as string,
    brief: record.brief as string,
    audience: record.audience as string,
    goals: record.goals as string,
    toml: record.toml as string,
    selectedBlueprint: record.selectedBlueprint as string,
    timeBudget: record.timeBudget as string,
    createdId,
    attached,
  };
}

export function saveNewRunDraft(draft: NewRunDraft): void {
  try {
    sessionStorage.setItem(
      NEW_RUN_DRAFT_KEY,
      JSON.stringify({ version: DRAFT_VERSION, ...draft }),
    );
  } catch {
    // sessionStorage unavailable: the wizard still works, just without persistence.
  }
}

export function loadNewRunDraft(): NewRunDraft | null {
  let raw: string | null;
  try {
    raw = sessionStorage.getItem(NEW_RUN_DRAFT_KEY);
  } catch {
    return null;
  }
  if (raw === null) return null;
  try {
    return parseDraft(JSON.parse(raw));
  } catch {
    return null;
  }
}

export function clearNewRunDraft(): void {
  try {
    sessionStorage.removeItem(NEW_RUN_DRAFT_KEY);
  } catch {
    // Nothing to clean up when storage is unavailable.
  }
}
