import { useCallback, useEffect, useRef, useState } from "react";
import { noticeMatches, useEvents, type NoticeFilter } from "./useEvents";

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

export interface PollingOptions {
  /**
   * The change notices this poller refetches on. While the events stream is
   * up the interval chain stops, and the poller fetches once per resync
   * (`hello`) and once per matching notice, with at most one follow-up queued
   * behind a fetch in flight. Without a filter, or while the stream is down,
   * it polls exactly as before. Held in a ref, so a fresh literal on every
   * render restarts nothing.
   */
  events?: NoticeFilter;
}

interface PollControl {
  /** Fetch now, or once more after the fetch in flight. */
  request(): void;
  /** Restart the interval chain with an immediate tick. */
  resume(): void;
  /** Stop the interval chain. */
  stop(): void;
}

export function usePolling<T>(fetcher: () => Promise<T>, intervalMs: number, options?: PollingOptions) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [nonce, setNonce] = useState(0);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;
  const lastKey = useRef<string | undefined>(undefined);

  const { up, epoch, subscribe } = useEvents();
  const filterRef = useRef(options?.events);
  filterRef.current = options?.events;
  const streaming = up && options?.events !== undefined;
  const streamingRef = useRef(streaming);
  const control = useRef<PollControl | null>(null);

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
    // Stream requests that arrived during a fetch: one follow-up, however many.
    let dirty = false;
    // A fresh mount (or refresh()/interval change) always publishes its first
    // payload, so an explicit refresh still hands consumers a new reference.
    lastKey.current = undefined;

    const tick = async () => {
      let failed = false;
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
          failed = true;
          if (!cancelled) setError(err instanceof Error ? err : new Error(String(err)));
        } finally {
          inFlight = false;
        }
      }
      if (cancelled) return;
      if (dirty) {
        dirty = false;
        void tick();
      } else if (!streamingRef.current || failed) {
        // Polling; or, while the stream is up, a failed fetch retries on the
        // interval until one succeeds, since no notice may come to heal it.
        timer = window.setTimeout(tick, intervalMs);
      }
    };

    const resume = () => {
      if (cancelled || inFlight) return;
      window.clearTimeout(timer);
      void tick();
    };
    control.current = {
      request: () => {
        if (cancelled) return;
        if (inFlight) dirty = true;
        else resume();
      },
      resume,
      stop: () => window.clearTimeout(timer),
    };

    void tick();

    const onVisibility = () => {
      if (document.visibilityState === "visible" && !streamingRef.current) resume();
    };
    document.addEventListener("visibilitychange", onVisibility);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [intervalMs, nonce]);

  // Stream up: stop the chain. Stream down: restart it with an immediate tick.
  useEffect(() => {
    if (streamingRef.current === streaming) return;
    streamingRef.current = streaming;
    if (streaming) control.current?.stop();
    else control.current?.resume();
  }, [streaming]);

  // Every hello after mount is one resync.
  const seenEpoch = useRef(epoch);
  useEffect(() => {
    if (seenEpoch.current === epoch) return;
    seenEpoch.current = epoch;
    if (streamingRef.current) control.current?.request();
  }, [epoch]);

  useEffect(
    () =>
      subscribe((notice) => {
        const filter = filterRef.current;
        if (streamingRef.current && filter && noticeMatches(filter, notice)) control.current?.request();
      }),
    [subscribe],
  );

  const refresh = useCallback(() => setNonce((n) => n + 1), []);
  return { data, error, refresh };
}
