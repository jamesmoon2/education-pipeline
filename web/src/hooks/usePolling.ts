import { useCallback, useEffect, useRef, useState } from "react";

export function usePolling<T>(fetcher: () => Promise<T>, intervalMs: number) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [nonce, setNonce] = useState(0);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;

    const tick = async () => {
      if (document.visibilityState === "visible") {
        try {
          const result = await fetcherRef.current();
          if (!cancelled) {
            setData(result);
            setError(null);
          }
        } catch (err) {
          if (!cancelled) setError(err instanceof Error ? err : new Error(String(err)));
        }
      }
      if (!cancelled) timer = window.setTimeout(tick, intervalMs);
    };

    void tick();

    const onVisibility = () => {
      if (document.visibilityState === "visible" && !cancelled) {
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
