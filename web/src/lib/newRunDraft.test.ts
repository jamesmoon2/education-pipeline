import { afterEach, describe, expect, it, vi } from "vitest";
import {
  NEW_RUN_DRAFT_KEY,
  clearNewRunDraft,
  loadNewRunDraft,
  saveNewRunDraft,
} from "./newRunDraft";
import type { NewRunDraft } from "./newRunDraft";

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

afterEach(() => {
  vi.restoreAllMocks();
  sessionStorage.clear();
});

describe("newRunDraft", () => {
  it("round-trips a saved draft", () => {
    const draft = makeDraft();
    saveNewRunDraft(draft);
    expect(loadNewRunDraft()).toEqual(draft);
  });

  it("round-trips the create-retry markers", () => {
    const draft = makeDraft({ step: "confirm", createdId: "intro-to-sql", attached: true });
    saveNewRunDraft(draft);
    expect(loadNewRunDraft()).toEqual(draft);
  });

  it("returns null when nothing is stored", () => {
    expect(loadNewRunDraft()).toBeNull();
  });

  it("clear removes the stored draft", () => {
    saveNewRunDraft(makeDraft());
    clearNewRunDraft();
    expect(sessionStorage.getItem(NEW_RUN_DRAFT_KEY)).toBeNull();
    expect(loadNewRunDraft()).toBeNull();
  });

  it("returns null for corrupt JSON", () => {
    sessionStorage.setItem(NEW_RUN_DRAFT_KEY, "{not json");
    expect(loadNewRunDraft()).toBeNull();
  });

  it("returns null for a wrong version", () => {
    saveNewRunDraft(makeDraft());
    const stored = JSON.parse(sessionStorage.getItem(NEW_RUN_DRAFT_KEY)!) as Record<string, unknown>;
    sessionStorage.setItem(NEW_RUN_DRAFT_KEY, JSON.stringify({ ...stored, version: 999 }));
    expect(loadNewRunDraft()).toBeNull();
  });

  it.each([
    ["null", "null"],
    ["a number", "42"],
    ["a string", '"draft"'],
    ["an array", "[]"],
    ["an empty object", "{}"],
  ])("returns null for %s", (_label, raw) => {
    sessionStorage.setItem(NEW_RUN_DRAFT_KEY, raw);
    expect(loadNewRunDraft()).toBeNull();
  });

  it.each([
    ["an unknown step", { step: "checkout" }],
    ["an unknown mode", { mode: "yaml" }],
    ["a non-string title", { title: 7 }],
    ["a missing field", { toml: undefined }],
    ["a non-string non-null createdId", { createdId: 12 }],
    ["a non-boolean attached", { attached: "yes" }],
  ])("returns null when the payload has %s", (_label, patch) => {
    saveNewRunDraft(makeDraft());
    const stored = JSON.parse(sessionStorage.getItem(NEW_RUN_DRAFT_KEY)!) as Record<string, unknown>;
    sessionStorage.setItem(NEW_RUN_DRAFT_KEY, JSON.stringify({ ...stored, ...patch }));
    expect(loadNewRunDraft()).toBeNull();
  });

  it("load returns null when sessionStorage.getItem throws", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("storage denied");
    });
    expect(loadNewRunDraft()).toBeNull();
  });

  it("save swallows a throwing sessionStorage.setItem", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("storage denied");
    });
    expect(() => saveNewRunDraft(makeDraft())).not.toThrow();
  });

  it("clear swallows a throwing sessionStorage.removeItem", () => {
    vi.spyOn(Storage.prototype, "removeItem").mockImplementation(() => {
      throw new Error("storage denied");
    });
    expect(() => clearNewRunDraft()).not.toThrow();
  });
});
