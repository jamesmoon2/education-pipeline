import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { TOURS, type TourId, type TourStep } from "./steps";
import TourOverlay from "./TourOverlay";

export const TOUR_COMPLETED_KEY = "ep.tour.completed";

export function hasCompletedTour(): boolean {
  try {
    return localStorage.getItem(TOUR_COMPLETED_KEY) !== null;
  } catch {
    return false;
  }
}

/** Forget that the tour ran; wired to Settings → Appearance. */
export function resetTourCompletion(): void {
  try {
    localStorage.removeItem(TOUR_COMPLETED_KEY);
  } catch {
    // Storage unavailable: nothing was remembered in the first place.
  }
}

function rememberOutcome(outcome: "done" | "skipped"): void {
  try {
    localStorage.setItem(TOUR_COMPLETED_KEY, outcome);
  } catch {
    // Session-only memory when storage is blocked.
  }
}

export interface TourContextValue {
  active: boolean;
  tourId: TourId | null;
  index: number;
  steps: TourStep[];
  start(tourId?: TourId, startAt?: number): void;
  next(): void;
  back(): void;
  stop(outcome: "done" | "skipped"): void;
}

const TourContext = createContext<TourContextValue | null>(null);

/** The tour context when a provider is mounted, else null (page tests
 *  render pages bare; a page must not require the shell to function). */
export function useOptionalTour(): TourContextValue | null {
  return useContext(TourContext);
}

export function useTour(): TourContextValue {
  const value = useContext(TourContext);
  if (!value) throw new Error("useTour must be used inside <TourProvider>");
  return value;
}

/**
 * Owns tour state for the whole cockpit. Lives inside the router so a step
 * can hop routes; renders the overlay itself so pages never have to.
 * `?tour=1` on any URL starts the workbench tour once and is then removed
 * from the address bar (a reload should not restart it).
 */
export function TourProvider({
  tours = TOURS,
  children,
}: {
  tours?: Record<TourId, TourStep[]>;
  children: ReactNode;
}) {
  const [tourId, setTourId] = useState<TourId | null>(null);
  const [index, setIndex] = useState(0);
  const navigate = useNavigate();
  const location = useLocation();
  const [searchParams, setSearchParams] = useSearchParams();
  const returnFocusTo = useRef<HTMLElement | null>(null);

  const steps = tourId ? tours[tourId] : [];
  const active = tourId !== null;

  const start = useCallback(
    (id: TourId = "workbench", startAt = 0) => {
      const list = tours[id] ?? [];
      if (list.length === 0) return;
      returnFocusTo.current =
        document.activeElement instanceof HTMLElement ? document.activeElement : null;
      setTourId(id);
      setIndex(Math.min(Math.max(startAt, 0), list.length - 1));
    },
    [tours],
  );

  const stop = useCallback((outcome: "done" | "skipped") => {
    rememberOutcome(outcome);
    setTourId(null);
    setIndex(0);
    const target = returnFocusTo.current;
    returnFocusTo.current = null;
    if (target && document.contains(target)) {
      // Let the overlay unmount first so its own focus bookkeeping cannot
      // steal the restore.
      window.setTimeout(() => target.focus(), 0);
    }
  }, []);

  const next = useCallback(() => {
    if (!tourId) return;
    if (index >= steps.length - 1) {
      stop("done");
      return;
    }
    setIndex(index + 1);
  }, [index, steps.length, stop, tourId]);

  const back = useCallback(() => {
    setIndex((current) => Math.max(current - 1, 0));
  }, []);

  // Deep link: /any/path?tour=1 → run the workbench tour once.
  const tourRequested = searchParams.get("tour") === "1";
  useEffect(() => {
    if (!tourRequested) return;
    const nextParams = new URLSearchParams(searchParams);
    nextParams.delete("tour");
    setSearchParams(nextParams, { replace: true });
    start("workbench");
  }, [tourRequested, searchParams, setSearchParams, start]);

  // Route hop: steps carry the pathname they belong to.
  const step = active ? steps[index] : undefined;
  const stepRoute = step?.route;
  useEffect(() => {
    if (!stepRoute || location.pathname === stepRoute) return;
    navigate(stepRoute);
  }, [stepRoute, location.pathname, navigate]);

  const value = useMemo<TourContextValue>(
    () => ({ active, tourId, index, steps, start, next, back, stop }),
    [active, tourId, index, steps, start, next, back, stop],
  );

  return (
    <TourContext.Provider value={value}>
      {children}
      {active && step && (
        <TourOverlay
          key={`${tourId}:${index}`}
          step={step}
          index={index}
          count={steps.length}
          onNext={next}
          onBack={back}
          onSkip={() => stop("skipped")}
        />
      )}
    </TourContext.Provider>
  );
}
