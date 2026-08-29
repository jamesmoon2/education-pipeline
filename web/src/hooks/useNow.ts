import { useEffect, useState } from "react";

/** A `Date.now()` value that refreshes every `intervalMs`, for components
 *  ticking a live elapsed-time readout. There is no visibility/enabled gate
 *  here on purpose: callers gate it structurally instead, by only mounting
 *  the component that calls this hook while there is something active to
 *  tick (an active-job block, a "running"/"queued" row) -- swap it out for
 *  a plain static string once the thing it is timing goes terminal, rather
 *  than calling this hook unconditionally and hoping nothing re-renders. */
export function useNow(intervalMs = 1_000): number {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), intervalMs);
    return () => window.clearInterval(timer);
  }, [intervalMs]);

  return now;
}
