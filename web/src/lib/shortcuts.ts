import type { TopicSummary } from "../api/types";

// Cockpit keyboard shortcuts (Phase 6, decisions 4-8). This module answers
// "which action does this key event mean here" without a DOM, so the key map
// and its conflict rules are unit-testable; ShortcutsProvider owns the one
// document listener and carries the actions out.

/** Where the "Single-key shortcuts" switch is stored; `off` when disabled. */
export const SHORTCUTS_STORAGE_KEY = "ep.shortcuts";

export type ShortcutAction =
  | "toggle-overlay"
  | "close-overlay"
  | "focus-search"
  | "open-next-stage"
  | "open-next-review"
  | "focus-approve";

/** The actions a page supplies the handler for, through usePageShortcut. */
export type PageShortcutAction = Extract<ShortcutAction, "open-next-stage" | "focus-approve">;

/** The parts of a KeyboardEvent the resolver reads; a real one satisfies it. */
export interface ShortcutKeyEvent {
  key: string;
  ctrlKey: boolean;
  metaKey: boolean;
  altKey: boolean;
  shiftKey: boolean;
  isComposing: boolean;
  defaultPrevented: boolean;
  target: EventTarget | null;
}

export interface ShortcutContext {
  /** The "Single-key shortcuts" switch. */
  enabled: boolean;
  /** The shortcuts overlay itself is open. */
  overlayOpen: boolean;
  /** Some other modal dialog is open. */
  otherModalOpen: boolean;
}

/** Form fields and contentEditable keep every key they are typed. */
function isEditableTarget(target: EventTarget | null): boolean {
  if (!target || typeof target !== "object") return false;
  const element = target as { tagName?: unknown; isContentEditable?: unknown };
  if (element.isContentEditable === true) return true;
  const tag = typeof element.tagName === "string" ? element.tagName.toUpperCase() : "";
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";
}

/** The unshifted single keys (decision 4). ←/→ are deliberately absent. */
function singleKeyAction(key: string): ShortcutAction | null {
  switch (key) {
    case "/":
      return "focus-search";
    case "n":
      return "open-next-stage";
    case "r":
      return "open-next-review";
    case "a":
      return "focus-approve";
    default:
      return null;
  }
}

export function resolveShortcut(
  event: ShortcutKeyEvent,
  context: ShortcutContext,
): ShortcutAction | null {
  // Browser and OS shortcuts win; so do IME composition and any handler
  // that already claimed the key (decision 5).
  if (event.ctrlKey || event.metaKey || event.altKey) return null;
  if (event.isComposing || event.defaultPrevented) return null;
  if (context.otherModalOpen) return null;
  // Escape is not a single-character shortcut: it closes the overlay even
  // with the switch off, and from the overlay's own checkbox.
  if (context.overlayOpen && event.key === "Escape") return "close-overlay";
  if (!context.enabled || isEditableTarget(event.target)) return null;
  // `?` is typed with Shift on most layouts, so Shift is allowed for it only.
  if (event.key === "?") return "toggle-overlay";
  if (event.shiftKey || context.overlayOpen) return null;
  return singleKeyAction(event.key);
}

/**
 * The library's default order: newest activity first, courses with no
 * activity last, ties by id. TopicListPage sorts by it, and `r` walks it.
 */
export function compareLibraryOrder(a: TopicSummary, b: TopicSummary): number {
  const left = a.last_activity ?? "";
  const right = b.last_activity ?? "";
  if (left === right) return a.id.localeCompare(b.id);
  if (!left) return 1;
  if (!right) return -1;
  return right.localeCompare(left);
}

function needsReview(topic: TopicSummary): boolean {
  // An archived run refuses writes, and a stageless approval has no deep
  // link to land on.
  const next = topic.run?.next_action;
  return !topic.archived && next?.action === "approve" && !!next.stage;
}

/**
 * The next course waiting for review, searching `topics` in the order given
 * from just after `currentId` and wrapping. The current course never counts.
 */
export function nextCourseNeedingReview(
  topics: readonly TopicSummary[],
  currentId: string | null,
): TopicSummary | null {
  const start = currentId === null ? -1 : topics.findIndex((topic) => topic.id === currentId);
  for (let offset = 1; offset <= topics.length; offset += 1) {
    const topic = topics[(start + offset) % topics.length];
    if (topic.id !== currentId && needsReview(topic)) return topic;
  }
  return null;
}

// Where a course's next action takes you. An approval is the one action that
// needs the pending response in front of the reviewer; every other action —
// and a topic with no run yet — starts from the board's action area.
export function nextActionHref(topic: TopicSummary): string {
  const next = topic.run?.next_action;
  if (next?.action === "approve" && next.stage) {
    return `/topics/${topic.id}/stages/${next.stage}?tab=response`;
  }
  return `/topics/${topic.id}`;
}
