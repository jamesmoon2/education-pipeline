import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import type { TourStep } from "./steps";

/** Breathing room around the spotlit element, in CSS pixels. */
const SPOTLIGHT_PAD = 10;
/** How long to wait for a route-hopped anchor to mount before floating. */
const ANCHOR_TIMEOUT_MS = 1_500;
/** Popover size before the first measurement; the card is re-placed from
 *  its rendered size right after it mounts. */
const CARD_WIDTH = 360;
const CARD_HEIGHT = 240;
const CARD_GAP = 16;
const VIEWPORT_MARGIN = 16;

interface Rect {
  top: number;
  left: number;
  width: number;
  height: number;
}

function measure(element: Element): Rect {
  const box = element.getBoundingClientRect();
  return { top: box.top, left: box.left, width: box.width, height: box.height };
}

/**
 * Resolve a step's anchor. Polls for up to ANCHOR_TIMEOUT_MS because a step
 * may have just navigated and its page is still loading; once found, the
 * element is tracked through scroll and resize. `null` means "float".
 */
function useAnchor(selector: string | undefined): {
  rect: Rect | null;
  settled: boolean;
} {
  const [rect, setRect] = useState<Rect | null>(null);
  const [settled, setSettled] = useState(!selector);

  useLayoutEffect(() => {
    if (!selector) {
      setRect(null);
      setSettled(true);
      return;
    }
    let element: Element | null = null;
    let frame = 0;
    let cancelled = false;
    let observer: ResizeObserver | null = null;
    const started = performance.now();

    const update = () => {
      if (!element || cancelled) return;
      setRect(measure(element));
    };

    const attach = (found: Element) => {
      element = found;
      if (typeof found.scrollIntoView === "function") {
        found.scrollIntoView({ block: "center", inline: "nearest" });
      }
      update();
      setSettled(true);
      if (typeof ResizeObserver !== "undefined") {
        observer = new ResizeObserver(update);
        observer.observe(found);
      }
      window.addEventListener("scroll", update, true);
      window.addEventListener("resize", update);
    };

    const search = () => {
      if (cancelled) return;
      const found = document.querySelector(selector);
      if (found) {
        attach(found);
        return;
      }
      if (performance.now() - started > ANCHOR_TIMEOUT_MS) {
        setRect(null);
        setSettled(true);
        return;
      }
      frame = window.requestAnimationFrame(search);
    };

    setSettled(false);
    search();

    return () => {
      cancelled = true;
      window.cancelAnimationFrame(frame);
      observer?.disconnect();
      window.removeEventListener("scroll", update, true);
      window.removeEventListener("resize", update);
    };
  }, [selector]);

  return { rect, settled };
}

type Placement = "top" | "bottom" | "left" | "right" | "center" | "overlay";

interface Size {
  width: number;
  height: number;
}

/**
 * Place the card beside the spotlight: below, else above, else to the right,
 * else to the left, always clamped to the viewport. When the anchor is tall
 * enough that no side fits, the card overlays the anchor's lower edge rather
 * than covering its middle.
 */
export function placeCard(
  rect: Rect | null,
  card: Size,
  viewport: Size,
): { placement: Placement; style: React.CSSProperties } {
  if (!rect) return { placement: "center", style: {} };
  const vw = viewport.width;
  const vh = viewport.height;
  const clampX = (x: number) =>
    Math.min(Math.max(x, VIEWPORT_MARGIN), Math.max(VIEWPORT_MARGIN, vw - card.width - VIEWPORT_MARGIN));
  const clampY = (y: number) =>
    Math.min(Math.max(y, VIEWPORT_MARGIN), Math.max(VIEWPORT_MARGIN, vh - card.height - VIEWPORT_MARGIN));
  const below = rect.top + rect.height + SPOTLIGHT_PAD + CARD_GAP;
  const above = rect.top - SPOTLIGHT_PAD - CARD_GAP - card.height;
  const right = rect.left + rect.width + SPOTLIGHT_PAD + CARD_GAP;
  const left = rect.left - SPOTLIGHT_PAD - CARD_GAP - card.width;
  const centerX = rect.left + rect.width / 2 - card.width / 2;
  const centerY = rect.top + rect.height / 2 - card.height / 2;

  if (below + card.height <= vh - VIEWPORT_MARGIN) {
    return { placement: "bottom", style: { top: below, left: clampX(centerX) } };
  }
  if (above >= VIEWPORT_MARGIN) {
    return { placement: "top", style: { top: above, left: clampX(centerX) } };
  }
  if (right + card.width <= vw - VIEWPORT_MARGIN) {
    return { placement: "right", style: { top: clampY(centerY), left: right } };
  }
  if (left >= VIEWPORT_MARGIN) {
    return { placement: "left", style: { top: clampY(centerY), left } };
  }
  // Nothing fits: the anchor fills the viewport. Tuck the card into the
  // lower-right corner so the anchor's leading columns stay readable.
  return {
    placement: "overlay",
    style: { top: clampY(below), left: clampX(vw - card.width - VIEWPORT_MARGIN) },
  };
}

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * One tour step: a dimmed backdrop with a glowing cutout over the anchor,
 * and a dialog card placed beside it (or centered when floating). Modal:
 * the backdrop swallows pointer events, Tab cycles inside the card, and the
 * arrow keys / Escape drive the tour so it can be completed hands-on-keys.
 */
export default function TourOverlay({
  step,
  index,
  count,
  onNext,
  onBack,
  onSkip,
}: {
  step: TourStep;
  index: number;
  count: number;
  onNext: () => void;
  onBack: () => void;
  onSkip: () => void;
}) {
  const { rect, settled } = useAnchor(step.target);
  const cardRef = useRef<HTMLElement>(null);
  const titleId = useId();
  const bodyId = useId();
  const anchored = rect !== null;
  const last = index === count - 1;
  const [cardSize, setCardSize] = useState<Size>({ width: CARD_WIDTH, height: CARD_HEIGHT });

  // Measure the rendered card so placement uses its true height: a long
  // step body must never sit on top of the thing it is explaining.
  useLayoutEffect(() => {
    const card = cardRef.current;
    if (!card) return;
    const { offsetWidth, offsetHeight } = card;
    if (offsetWidth > 0 && offsetHeight > 0) {
      setCardSize((current) =>
        current.width === offsetWidth && current.height === offsetHeight
          ? current
          : { width: offsetWidth, height: offsetHeight },
      );
    }
  }, [step.id, rect]);

  // Focus the card on every step so screen readers announce the new title.
  useEffect(() => {
    cardRef.current?.focus({ preventScroll: true });
  }, [step.id]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.defaultPrevented) return;
      switch (event.key) {
        case "Escape":
          event.preventDefault();
          onSkip();
          break;
        case "ArrowRight":
          event.preventDefault();
          onNext();
          break;
        case "ArrowLeft":
          event.preventDefault();
          if (index > 0) onBack();
          break;
        case "Tab": {
          const card = cardRef.current;
          if (!card) return;
          const focusable = Array.from(card.querySelectorAll<HTMLElement>(FOCUSABLE));
          if (focusable.length === 0) return;
          const first = focusable[0];
          const lastEl = focusable[focusable.length - 1];
          const current = document.activeElement;
          if (event.shiftKey && (current === first || current === card)) {
            event.preventDefault();
            lastEl.focus();
          } else if (!event.shiftKey && current === lastEl) {
            event.preventDefault();
            first.focus();
          } else if (!card.contains(current)) {
            event.preventDefault();
            first.focus();
          }
          break;
        }
        default:
          break;
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [index, onBack, onNext, onSkip]);

  const { placement, style } = placeCard(rect, cardSize, {
    width: window.innerWidth,
    height: window.innerHeight,
  });

  return (
    <div
      className="tour-root"
      data-settled={settled ? "true" : "false"}
      data-anchored={anchored ? "true" : "false"}
    >
      <div className="tour-backdrop" aria-hidden="true" />
      {rect && (
        <div
          className="tour-spotlight"
          data-testid="tour-spotlight"
          aria-hidden="true"
          style={{
            top: rect.top - SPOTLIGHT_PAD,
            left: rect.left - SPOTLIGHT_PAD,
            width: rect.width + SPOTLIGHT_PAD * 2,
            height: rect.height + SPOTLIGHT_PAD * 2,
          }}
        />
      )}
      <section
        ref={cardRef}
        className="tour-card"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={bodyId}
        data-anchored={anchored ? "true" : "false"}
        data-placement={placement}
        data-step={step.id}
        tabIndex={-1}
        style={style}
      >
        <p className="tour-eyebrow">
          <span className="tour-eyebrow-mark" aria-hidden="true" />
          Step {index + 1} of {count}
        </p>
        <h2 id={titleId} className="tour-title">
          {step.title}
        </h2>
        <p id={bodyId} className="tour-body">
          {step.body}
        </p>
        <ol className="tour-progress" aria-hidden="true">
          {Array.from({ length: count }, (_, i) => (
            <li key={i} data-state={i < index ? "done" : i === index ? "current" : "todo"} />
          ))}
        </ol>
        <div className="tour-actions">
          <button type="button" className="tour-skip" onClick={onSkip}>
            Skip tour
          </button>
          <span className="tour-actions-spacer" />
          <button type="button" onClick={onBack} disabled={index === 0}>
            Back
          </button>
          <button type="button" className="tour-next" onClick={onNext}>
            {last ? "Finish" : "Next"}
          </button>
        </div>
        <p className="tour-hint" aria-hidden="true">
          <kbd>←</kbd> <kbd>→</kbd> to move · <kbd>Esc</kbd> to leave
        </p>
      </section>
    </div>
  );
}
