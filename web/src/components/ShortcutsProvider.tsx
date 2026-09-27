import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactNode,
  type RefObject,
} from "react";
import { matchPath, useLocation, useNavigate } from "react-router-dom";
import { getTopics } from "../api/client";
import {
  SHORTCUTS_STORAGE_KEY,
  compareLibraryOrder,
  nextActionHref,
  nextCourseNeedingReview,
  resolveShortcut,
  type PageShortcutAction,
  type ShortcutAction,
} from "../lib/shortcuts";

// Phase 6 decision 8: one document-level keydown listener for the whole
// cockpit. The key map and its conflict rules live in lib/shortcuts.ts; this
// provider carries the resolved action out. Pages register the two
// page-scoped actions (`n`, `a`) through usePageShortcut.

type Handler = () => void;

interface ShortcutsRegistry {
  register: (action: PageShortcutAction, handler: Handler) => () => void;
  openOverlay: (returnFocusTo?: HTMLElement | null) => void;
}

const ShortcutsContext = createContext<ShortcutsRegistry | null>(null);

// The library's filter box (TopicListPage), which `/` focuses.
const FILTER_SELECTOR = 'input[type="search"][aria-label="Filter courses"]';
// How long `/` waits for the library to render its filter after navigating.
const FILTER_WAIT_MS = 10_000;
const NOTICE_MS = 5_000;

// Storage access never throws: blocked storage leaves the default (on) and
// the choice holds for the session.
function readEnabled(): boolean {
  try {
    return window.localStorage.getItem(SHORTCUTS_STORAGE_KEY) !== "off";
  } catch {
    return true;
  }
}

function storeEnabled(enabled: boolean): void {
  try {
    if (enabled) window.localStorage.removeItem(SHORTCUTS_STORAGE_KEY);
    else window.localStorage.setItem(SHORTCUTS_STORAGE_KEY, "off");
  } catch {
    // Storage blocked: keep the in-memory choice.
  }
}

function otherModalOpen(overlay: Element | null): boolean {
  return Array.from(document.querySelectorAll('[aria-modal="true"], dialog[open]')).some(
    (element) => element !== overlay,
  );
}

/**
 * Register this page's handler for `n` ("open-next-stage") or `a`
 * ("focus-approve"). Pass null while the page has nothing for the key, so it
 * stays unclaimed. The latest handler passed is the one called.
 */
export function usePageShortcut(action: PageShortcutAction, handler: Handler | null): void {
  const registry = useContext(ShortcutsContext);
  const latest = useRef(handler);
  useLayoutEffect(() => {
    latest.current = handler;
  });
  const active = handler !== null;
  // A layout effect, so the key works from the first paint that shows it.
  useLayoutEffect(() => {
    if (!registry || !active) return undefined;
    return registry.register(action, () => latest.current?.());
  }, [registry, action, active]);
}

/** The rail's "Keyboard shortcuts" button: opens the overlay even when the keys are off. */
export function ShortcutsButton() {
  const registry = useContext(ShortcutsContext);
  if (!registry) return null;
  return (
    <button
      type="button"
      className="rail-shortcuts"
      onClick={(event) => registry.openOverlay(event.currentTarget)}
    >
      Keyboard shortcuts
    </button>
  );
}

const KEY_ROWS: ReadonlyArray<{ key: string; description: ReactNode }> = [
  { key: "?", description: "Show or hide this list." },
  { key: "/", description: "Filter the course library. From any other page, opens the library first." },
  { key: "n", description: "Open the stage the run needs next (course board and stage pages)." },
  { key: "r", description: "Open the next course waiting for review." },
  {
    key: "a",
    description: (
      <>
        Move focus to the approve button. It never approves: press <kbd>Enter</kbd> to approve.
      </>
    ),
  },
  { key: "Escape", description: "Close this list." },
];

function ShortcutsOverlay({
  dialogRef,
  enabled,
  onEnabledChange,
  onClose,
  returnFocusTo,
}: {
  dialogRef: RefObject<HTMLDivElement>;
  enabled: boolean;
  onEnabledChange: (enabled: boolean) => void;
  onClose: () => void;
  returnFocusTo: HTMLElement | null;
}) {
  const titleId = useId();
  const helpId = useId();

  // Focus moves into the dialog on open and back to where it was on close.
  useEffect(() => {
    dialogRef.current?.focus();
    return () => {
      if (returnFocusTo?.isConnected) returnFocusTo.focus();
    };
  }, [dialogRef, returnFocusTo]);

  // Keep Tab inside the modal dialog.
  const trapTab = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (event.key !== "Tab" || !dialogRef.current) return;
    const focusable = Array.from(
      dialogRef.current.querySelectorAll<HTMLElement>("button, input, [href], [tabindex='0']"),
    ).filter((element) => !element.hasAttribute("disabled"));
    if (focusable.length === 0) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    const active = document.activeElement;
    if (event.shiftKey && (active === first || active === dialogRef.current)) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && active === last) {
      event.preventDefault();
      first.focus();
    }
  };

  return (
    <div
      className="shortcuts-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        ref={dialogRef}
        className="shortcuts-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        onKeyDown={trapTab}
      >
        <h2 id={titleId}>Keyboard shortcuts</h2>
        <dl className="shortcuts-list">
          {KEY_ROWS.map((row) => (
            <div key={row.key}>
              <dt>
                <kbd>{row.key}</kbd>
              </dt>
              <dd>{row.description}</dd>
            </div>
          ))}
        </dl>
        <label className="shortcuts-switch">
          <input
            type="checkbox"
            checked={enabled}
            aria-describedby={helpId}
            onChange={(event) => onEnabledChange(event.target.checked)}
          />
          Single-key shortcuts
        </label>
        <p id={helpId} className="field-help">
          Keys never act while you type in a field. Turn them off if single keys get in the way,
          for example with speech input; the Keyboard shortcuts button in the sidebar always
          opens this list.
        </p>
        <p className="shortcuts-actions">
          <button type="button" onClick={onClose}>
            Close
          </button>
        </p>
      </div>
    </div>
  );
}

export default function ShortcutsProvider({ children }: { children: ReactNode }) {
  const location = useLocation();
  const navigate = useNavigate();
  const [enabled, setEnabled] = useState(readEnabled);
  const [overlay, setOverlay] = useState<{ returnFocusTo: HTMLElement | null } | null>(null);
  const [notice, setNotice] = useState<{ id: number; text: string } | null>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const handlers = useRef(new Map<PageShortcutAction, Handler[]>());

  // The one listener reads the latest render's values through this ref.
  const live = useRef({ enabled, overlayOpen: overlay !== null, location, navigate });
  useLayoutEffect(() => {
    live.current = { enabled, overlayOpen: overlay !== null, location, navigate };
  });

  const register = useCallback((action: PageShortcutAction, handler: Handler) => {
    const stack = handlers.current.get(action) ?? [];
    handlers.current.set(action, [...stack, handler]);
    return () => {
      const current = handlers.current.get(action) ?? [];
      handlers.current.set(action, current.filter((entry) => entry !== handler));
    };
  }, []);

  const openOverlay = useCallback((returnFocusTo?: HTMLElement | null) => {
    const fallback = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    setOverlay((current) => current ?? { returnFocusTo: returnFocusTo ?? fallback });
  }, []);
  const closeOverlay = useCallback(() => setOverlay(null), []);

  const changeEnabled = useCallback((next: boolean) => {
    setEnabled(next);
    storeEnabled(next);
  }, []);

  const announce = useCallback((text: string) => {
    setNotice((current) => ({ id: (current?.id ?? 0) + 1, text }));
  }, []);
  useEffect(() => {
    if (!notice) return undefined;
    const timer = window.setTimeout(() => setNotice(null), NOTICE_MS);
    return () => window.clearTimeout(timer);
  }, [notice]);

  // `/` from another page navigates first, then focuses the filter once the
  // library renders it -- unless focus has meanwhile gone somewhere else.
  const cancelFilterWait = useRef<(() => void) | null>(null);
  const focusFilter = useCallback(() => {
    cancelFilterWait.current?.();
    const { location: current, navigate: go } = live.current;
    const present = document.querySelector<HTMLInputElement>(FILTER_SELECTOR);
    if (current.pathname === "/" && present) {
      present.focus();
      return;
    }
    if (current.pathname !== "/") go("/");
    const focusedAtPress = document.activeElement;
    const tryFocus = () => {
      const filter = document.querySelector<HTMLInputElement>(FILTER_SELECTOR);
      if (!filter) return false;
      const active = document.activeElement;
      if (!active || active === document.body || active === focusedAtPress) filter.focus();
      return true;
    };
    const observer = new MutationObserver(() => {
      if (tryFocus()) stop();
    });
    const timer = window.setTimeout(() => stop(), FILTER_WAIT_MS);
    function stop() {
      observer.disconnect();
      window.clearTimeout(timer);
      cancelFilterWait.current = null;
    }
    cancelFilterWait.current = stop;
    observer.observe(document.body, { childList: true, subtree: true });
  }, []);
  // Leaving the library before its filter shows up drops the pending focus.
  useEffect(() => {
    if (location.pathname !== "/") cancelFilterWait.current?.();
  }, [location.pathname]);
  useEffect(() => () => cancelFilterWait.current?.(), []);

  // `r`: the next course waiting for review, after the current one, in the
  // library's default order. A result that arrives after the reviewer has
  // moved on is dropped rather than yanking them elsewhere.
  const reviewPending = useRef(false);
  const openNextReview = useCallback(async () => {
    if (reviewPending.current) return;
    reviewPending.current = true;
    const pressedAt = live.current.location.key;
    const currentId =
      matchPath({ path: "/topics/:topicId", end: false }, live.current.location.pathname)?.params
        .topicId ?? null;
    try {
      const { topics } = await getTopics();
      if (live.current.location.key !== pressedAt) return;
      const next = nextCourseNeedingReview([...topics].sort(compareLibraryOrder), currentId);
      if (next) live.current.navigate(nextActionHref(next));
      else announce("No course needs review");
    } catch {
      if (live.current.location.key === pressedAt) announce("Could not load the course list");
    } finally {
      reviewPending.current = false;
    }
  }, [announce]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const { enabled: on, overlayOpen } = live.current;
      const action: ShortcutAction | null = resolveShortcut(event, {
        enabled: on,
        overlayOpen,
        otherModalOpen: otherModalOpen(dialogRef.current),
      });
      if (!action) return;
      if (action === "open-next-stage" || action === "focus-approve") {
        const stack = handlers.current.get(action) ?? [];
        const handler = stack[stack.length - 1];
        if (!handler) return; // Nothing on this page for the key: leave it alone.
        event.preventDefault();
        if (!event.repeat) handler();
        return;
      }
      // A handled key claims its default, which also stops Firefox quick-find on `/`.
      event.preventDefault();
      if (event.repeat) return;
      switch (action) {
        case "toggle-overlay":
          if (overlayOpen) closeOverlay();
          else openOverlay();
          break;
        case "close-overlay":
          closeOverlay();
          break;
        case "focus-search":
          focusFilter();
          break;
        case "open-next-review":
          void openNextReview();
          break;
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [closeOverlay, focusFilter, openNextReview, openOverlay]);

  const registry = useMemo(() => ({ register, openOverlay }), [register, openOverlay]);

  return (
    <ShortcutsContext.Provider value={registry}>
      {children}
      {overlay && (
        <ShortcutsOverlay
          dialogRef={dialogRef}
          enabled={enabled}
          onEnabledChange={changeEnabled}
          onClose={closeOverlay}
          returnFocusTo={overlay.returnFocusTo}
        />
      )}
      <div className="shortcuts-announcer" aria-live="polite" aria-atomic="true">
        {notice && (
          <p key={notice.id} className="shortcuts-notice">
            {notice.text}
          </p>
        )}
      </div>
    </ShortcutsContext.Provider>
  );
}
