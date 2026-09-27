import { describe, expect, it } from "vitest";
import type { NextAction, RunStatus, TopicSummary } from "../api/types";
import {
  SHORTCUTS_STORAGE_KEY,
  nextActionHref,
  nextCourseNeedingReview,
  resolveShortcut,
  type ShortcutAction,
  type ShortcutContext,
  type ShortcutKeyEvent,
} from "./shortcuts";

// T61 decisions 4-8 (docs/superpowers/plans/2026-09-27-phase-6-cockpit.md).
// The resolver answers "which action does this key event mean here" without a
// DOM: the event is a plain object, and its target only needs the shape a
// DOM element has (tagName, isContentEditable).

type Target = ShortcutKeyEvent["target"];

const target = (shape: { tagName: string; isContentEditable?: boolean }): Target =>
  ({ isContentEditable: false, ...shape }) as unknown as Target;

const BODY = target({ tagName: "BODY" });
const BUTTON = target({ tagName: "BUTTON" });
const INPUT = target({ tagName: "INPUT" });
const TEXTAREA = target({ tagName: "TEXTAREA" });
const SELECT = target({ tagName: "SELECT" });
const EDITABLE_DIV = target({ tagName: "DIV", isContentEditable: true });

function press(key: string, overrides: Partial<ShortcutKeyEvent> = {}): ShortcutKeyEvent {
  return {
    key,
    ctrlKey: false,
    metaKey: false,
    altKey: false,
    shiftKey: false,
    isComposing: false,
    defaultPrevented: false,
    target: BODY,
    ...overrides,
  };
}

const ON: ShortcutContext = { enabled: true, overlayOpen: false, otherModalOpen: false };
const OVERLAY: ShortcutContext = { ...ON, overlayOpen: true };

// Every bound key, with the action it means while the overlay is closed.
const KEY_MAP: ReadonlyArray<readonly [string, ShortcutAction]> = [
  ["?", "toggle-overlay"],
  ["/", "focus-search"],
  ["n", "open-next-stage"],
  ["r", "open-next-review"],
  ["a", "focus-approve"],
];
const SINGLE_KEYS = KEY_MAP.map(([key]) => key);

describe("resolveShortcut — key map (decision 4)", () => {
  it.each(KEY_MAP)("%s means %s", (key, action) => {
    expect(resolveShortcut(press(key), ON)).toBe(action);
  });

  it("accepts ? typed with Shift, as it is on most layouts", () => {
    expect(resolveShortcut(press("?", { shiftKey: true }), ON)).toBe("toggle-overlay");
  });

  it("? closes the overlay it opened (the same toggle action)", () => {
    expect(resolveShortcut(press("?"), OVERLAY)).toBe("toggle-overlay");
    expect(resolveShortcut(press("?", { shiftKey: true }), OVERLAY)).toBe("toggle-overlay");
  });

  it("Escape closes the overlay while it is open", () => {
    expect(resolveShortcut(press("Escape"), OVERLAY)).toBe("close-overlay");
  });

  it("Escape means nothing while the overlay is closed, so it stays with the page", () => {
    expect(resolveShortcut(press("Escape"), ON)).toBeNull();
  });

  it("leaves unbound keys alone", () => {
    for (const key of ["b", "j", "k", "x", "1", "Enter", " ", "Tab", "Backspace", "F1"]) {
      expect(resolveShortcut(press(key), ON), key).toBeNull();
    }
  });

  it("never binds ←/→: they belong to the exported guide", () => {
    const contexts: ShortcutContext[] = [
      ON,
      OVERLAY,
      { ...ON, enabled: false },
      { ...ON, otherModalOpen: true },
    ];
    for (const context of contexts) {
      for (const key of ["ArrowLeft", "ArrowRight"]) {
        for (const shiftKey of [false, true]) {
          expect(resolveShortcut(press(key, { shiftKey }), context)).toBeNull();
        }
      }
    }
  });
});

describe("resolveShortcut — conflict rules (decision 5)", () => {
  it.each(["ctrlKey", "metaKey", "altKey"] as const)(
    "ignores every key while %s is held, so browser and OS shortcuts win",
    (modifier) => {
      for (const key of SINGLE_KEYS) {
        expect(resolveShortcut(press(key, { [modifier]: true }), ON), key).toBeNull();
      }
      expect(resolveShortcut(press("Escape", { [modifier]: true }), OVERLAY)).toBeNull();
    },
  );

  it("allows Shift for ? only", () => {
    expect(resolveShortcut(press("/", { shiftKey: true }), ON)).toBeNull();
    for (const key of ["n", "r", "a"]) {
      expect(resolveShortcut(press(key, { shiftKey: true }), ON), key).toBeNull();
      expect(
        resolveShortcut(press(key.toUpperCase(), { shiftKey: true }), ON),
        key.toUpperCase(),
      ).toBeNull();
    }
  });

  it.each([
    ["input", INPUT],
    ["textarea", TEXTAREA],
    ["select", SELECT],
    ["contentEditable", EDITABLE_DIV],
  ] as const)("ignores every single key when the target is editable (%s)", (_name, editable) => {
    for (const key of SINGLE_KEYS) {
      expect(resolveShortcut(press(key, { target: editable }), ON), key).toBeNull();
    }
  });

  it("recognises real DOM form controls as editable targets", () => {
    for (const tag of ["input", "textarea", "select"]) {
      const element = document.createElement(tag) as unknown as Target;
      for (const key of SINGLE_KEYS) {
        expect(resolveShortcut(press(key, { target: element }), ON), `${tag} ${key}`).toBeNull();
      }
    }
    const button = document.createElement("button") as unknown as Target;
    expect(resolveShortcut(press("a", { target: button }), ON)).toBe("focus-approve");
  });

  it("acts on non-editable targets and on a missing target", () => {
    expect(resolveShortcut(press("a", { target: BUTTON }), ON)).toBe("focus-approve");
    expect(resolveShortcut(press("/", { target: null as unknown as Target }), ON)).toBe(
      "focus-search",
    );
  });

  it("lets Escape close the overlay from its own controls (an editable target)", () => {
    // The overlay's "Single-key shortcuts" switch is a checkbox <input>;
    // Escape from it must still close the dialog.
    expect(resolveShortcut(press("Escape", { target: INPUT }), OVERLAY)).toBe("close-overlay");
  });

  it("ignores keys during IME composition", () => {
    for (const key of SINGLE_KEYS) {
      expect(resolveShortcut(press(key, { isComposing: true }), ON), key).toBeNull();
    }
    expect(resolveShortcut(press("Escape", { isComposing: true }), OVERLAY)).toBeNull();
  });

  it("ignores an event something else already handled (defaultPrevented)", () => {
    for (const key of SINGLE_KEYS) {
      expect(resolveShortcut(press(key, { defaultPrevented: true }), ON), key).toBeNull();
    }
    expect(resolveShortcut(press("Escape", { defaultPrevented: true }), OVERLAY)).toBeNull();
  });

  it("while the overlay is open, only ? and Escape act", () => {
    for (const key of ["/", "n", "r", "a"]) {
      expect(resolveShortcut(press(key), OVERLAY), key).toBeNull();
    }
    expect(resolveShortcut(press("?"), OVERLAY)).toBe("toggle-overlay");
    expect(resolveShortcut(press("Escape"), OVERLAY)).toBe("close-overlay");
  });

  it("while any other modal dialog is open, every key is ignored", () => {
    const otherModal: ShortcutContext = { ...ON, otherModalOpen: true };
    for (const key of [...SINGLE_KEYS, "Escape"]) {
      expect(resolveShortcut(press(key), otherModal), key).toBeNull();
      expect(
        resolveShortcut(press(key), { ...otherModal, overlayOpen: true }),
        `${key} with overlay`,
      ).toBeNull();
    }
  });
});

describe("resolveShortcut — the off switch (decision 7, WCAG 2.1.4)", () => {
  const OFF: ShortcutContext = { ...ON, enabled: false };

  it("turns every single-key shortcut off, including ?", () => {
    for (const key of SINGLE_KEYS) {
      expect(resolveShortcut(press(key), OFF), key).toBeNull();
      expect(resolveShortcut(press(key), { ...OFF, overlayOpen: true }), `${key} open`).toBeNull();
    }
    expect(resolveShortcut(press("?", { shiftKey: true }), OFF)).toBeNull();
  });

  it("still lets Escape close the overlay the rail button opened", () => {
    // Escape is not a single-character shortcut, and a modal dialog must
    // always close on it.
    expect(resolveShortcut(press("Escape"), { ...OFF, overlayOpen: true })).toBe(
      "close-overlay",
    );
    expect(resolveShortcut(press("Escape"), OFF)).toBeNull();
  });

  it("stores the switch under ep.shortcuts", () => {
    expect(SHORTCUTS_STORAGE_KEY).toBe("ep.shortcuts");
  });
});

function makeRun(
  topicId: string,
  action: NextAction["action"],
  stage: string | null,
): RunStatus {
  return {
    topic_id: topicId,
    finalized: false,
    content_contract: { kind: "interactive_guide", schema_version: "1.2" },
    stage_provenance: [],
    validations: {
      draft: { state: "missing", blocking: 0, errors: 0, warnings: 0 },
      final: { state: "missing", blocking: 0, errors: 0, warnings: 0 },
    },
    stages: [],
    next_action: { topic_id: topicId, stage, action, detail: "" },
  };
}

function makeTopic(
  id: string,
  next: { action: NextAction["action"]; stage: string | null } | null,
  overrides: Partial<TopicSummary> = {},
): TopicSummary {
  return {
    id,
    title: `Title ${id}`,
    error: null,
    run: next ? makeRun(id, next.action, next.stage) : null,
    archived: false,
    last_activity: null,
    profile_id: null,
    completion: null,
    ...overrides,
  };
}

const review = (id: string, stage = "draft", overrides: Partial<TopicSummary> = {}) =>
  makeTopic(id, { action: "approve", stage }, overrides);
const busy = (id: string) => makeTopic(id, { action: "save_response", stage: "outline" });

describe("nextCourseNeedingReview", () => {
  it("returns the first course needing review when there is no current course", () => {
    const topics = [busy("a"), review("b"), review("c")];
    expect(nextCourseNeedingReview(topics, null)).toBe(topics[1]);
  });

  it("keeps the given (library) order rather than sorting", () => {
    const topics = [review("zeta"), review("alpha")];
    expect(nextCourseNeedingReview(topics, null)).toBe(topics[0]);
  });

  it("starts after the current course", () => {
    const topics = [review("a"), review("b"), review("c")];
    expect(nextCourseNeedingReview(topics, "a")).toBe(topics[1]);
    expect(nextCourseNeedingReview(topics, "b")).toBe(topics[2]);
  });

  it("wraps past the end of the list", () => {
    const topics = [review("a"), busy("b"), review("c")];
    expect(nextCourseNeedingReview(topics, "c")).toBe(topics[0]);
    expect(nextCourseNeedingReview(topics, "b")).toBe(topics[2]);
  });

  it("skips the current course even when it needs review", () => {
    expect(nextCourseNeedingReview([busy("a"), review("b")], "b")).toBeNull();
  });

  it("searches from the start when the current course is not in the list", () => {
    const topics = [busy("a"), review("b")];
    expect(nextCourseNeedingReview(topics, "gone")).toBe(topics[1]);
  });

  it("returns null when no course needs review", () => {
    expect(nextCourseNeedingReview([], null)).toBeNull();
    expect(nextCourseNeedingReview([busy("a"), makeTopic("b", null)], "a")).toBeNull();
  });

  it("only counts runs whose next action is approve", () => {
    const actions: NextAction["action"][] = [
      "write_prompt",
      "save_response",
      "validate",
      "resolve_findings",
      "finalize",
      "done",
      "assemble",
    ];
    const topics = [
      makeTopic("no-run", null),
      ...actions.map((action) => makeTopic(action, { action, stage: "draft" })),
    ];
    expect(nextCourseNeedingReview(topics, null)).toBeNull();
    const withReview = [...topics, review("last")];
    expect(nextCourseNeedingReview(withReview, null)).toBe(withReview[withReview.length - 1]);
  });

  it("skips archived courses and approvals with no stage to link to", () => {
    // An archived run refuses writes, and the library hides it by default.
    const topics = [
      review("archived", "draft", { archived: true }),
      makeTopic("stageless", { action: "approve", stage: null }),
      review("open"),
    ];
    expect(nextCourseNeedingReview(topics, null)).toBe(topics[2]);
    expect(nextCourseNeedingReview(topics.slice(0, 2), null)).toBeNull();
  });
});

describe("nextActionHref (the library's next-action link)", () => {
  it("lands a pending approval on the response tab", () => {
    expect(nextActionHref(review("t", "outline"))).toBe("/topics/t/stages/outline?tab=response");
  });

  it("sends every other action, and a stageless approval, to the board", () => {
    expect(nextActionHref(busy("t"))).toBe("/topics/t");
    expect(nextActionHref(makeTopic("t", { action: "approve", stage: null }))).toBe("/topics/t");
    expect(nextActionHref(makeTopic("t", { action: "done", stage: null }))).toBe("/topics/t");
  });

  it("sends a topic with no run to the board", () => {
    expect(nextActionHref(makeTopic("t", null))).toBe("/topics/t");
  });
});
