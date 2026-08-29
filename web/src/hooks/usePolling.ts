import { useCallback, useEffect, useRef, useState } from "react";

/**
 * A value key for change detection. Two ticks that parsed the same response
 * bytes produce the same key (JSON.parse preserves key order), so an unchanged
 * payload is recognisable even though every tick builds a fresh object graph.
 * Returns undefined for anything JSON cannot represent — those payloads are
 * always republished rather than gated on a key that cannot be compared.
 */
function payloadKey(value: unknown): string | undefined {
  try {
    return JSON.stringify(value);
  } catch {
    return undefined; // cyclic or otherwise unserializable
  }
}

export function usePolling<T>(fetcher: () => Promise<T>, intervalMs: number) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [nonce, setNonce] = useState(0);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;
  const lastKey = useRef<string | undefined>(undefined);

  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;
    // True from the moment a tick starts its fetch until that tick has
    // rescheduled. `timer` is the id of the timeout that started the in-flight
    // tick — already fired, so clearing it would be a no-op — and restarting
    // the chain from here would leave two chains running for the rest of the
    // mount. A resume mid-fetch needs nothing anyway: the fetch in flight is
    // the fresh data it would have asked for.
    let inFlight = false;
    // A fresh mount (or refresh()/interval change) always publishes its first
    // payload, so an explicit refresh still hands consumers a new reference.
    lastKey.current = undefined;

    const tick = async () => {
      if (document.visibilityState === "visible") {
        inFlight = true;
        try {
          const result = await fetcherRef.current();
          if (!cancelled) {
            const key = payloadKey(result);
            // Bail out of the state update when nothing changed: React can
            // then skip the whole consumer subtree instead of re-rendering it
            // every interval against an identical payload. `setError(null)`
            // stays unconditional — React already bails on an identical
            // primitive, and the error path must clear on every good tick.
            if (key === undefined || key !== lastKey.current) {
              lastKey.current = key;
              setData(result);
            }
            setError(null);
          }
        } catch (err) {
          if (!cancelled) setError(err instanceof Error ? err : new Error(String(err)));
        } finally {
          inFlight = false;
        }
      }
      if (!cancelled) timer = window.setTimeout(tick, intervalMs);
    };

    void tick();

    const onVisibility = () => {
      if (document.visibilityState === "visible" && !cancelled && !inFlight) {
        window.clearTimeout(timer);
        void tick();
      }
    };
    document.addEventListener("visibilitychange", onVisibility);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [intervalMs, nonce]);

  const refresh = useCallback(() => setNonce((n) => n + 1), []);
  return { data, error, refresh };
}
