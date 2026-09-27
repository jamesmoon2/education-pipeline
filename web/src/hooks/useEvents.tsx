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
import { openEventStream } from "../api/client";

// The cockpit side of `GET /v1/events` (design note §1 wire format, §6
// client). The stream says *that* something changed, never what: pollers
// that name a notice refetch over their usual route, and poll exactly as
// before whenever the stream is down.

/** One idempotent change notice. */
export type ChangeNotice = { kind: "run"; topic: string } | { kind: "jobs" } | { kind: "topics" };

/** The notices a poller refetches on: one run (or any, `"*"`), the job list, the topic list. */
export interface NoticeFilter {
  run?: string;
  jobs?: true;
  topics?: true;
}

export function noticeMatches(filter: NoticeFilter, notice: ChangeNotice): boolean {
  switch (notice.kind) {
    case "run":
      return filter.run === "*" || (filter.run !== undefined && filter.run === notice.topic);
    case "jobs":
      return filter.jobs === true;
    case "topics":
      return filter.topics === true;
  }
}

export interface SseEvent {
  event: "hello" | "change";
  data: Record<string, unknown>;
}

/**
 * A streaming `text/event-stream` parser: push raw bytes, get `hello` and
 * `change` events whose data is a JSON object. LF, CRLF and CR all end a
 * line, including a CR that ends one chunk with its LF at the start of the
 * next. Comments, `id`, `retry`, other events and bad JSON are ignored;
 * nothing the bytes contain makes it throw.
 */
export function createSseParser(onEvent: (event: SseEvent) => void): { push(chunk: Uint8Array): void } {
  const decoder = new TextDecoder();
  let buffer = "";
  let skipLeadingLF = false;
  let eventType = "";
  let dataLines: string[] = [];

  const dispatch = () => {
    const type = eventType;
    const lines = dataLines;
    eventType = "";
    dataLines = [];
    if (lines.length === 0 || (type !== "hello" && type !== "change")) return;
    let data: unknown;
    try {
      data = JSON.parse(lines.join("\n"));
    } catch {
      return;
    }
    if (data === null || typeof data !== "object" || Array.isArray(data)) return;
    onEvent({ event: type, data: data as Record<string, unknown> });
  };

  const line = (text: string) => {
    if (text === "") return dispatch();
    if (text.startsWith(":")) return; // comment
    const colon = text.indexOf(":");
    const field = colon === -1 ? text : text.slice(0, colon);
    let value = colon === -1 ? "" : text.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "event") eventType = value;
    else if (field === "data") dataLines.push(value);
  };

  return {
    push(chunk) {
      let text = decoder.decode(chunk, { stream: true });
      if (skipLeadingLF && text !== "") {
        skipLeadingLF = false;
        if (text.startsWith("\n")) text = text.slice(1);
      }
      buffer += text;
      const lines: string[] = [];
      let start = 0;
      for (let i = 0; i < buffer.length; i += 1) {
        const char = buffer[i];
        if (char !== "\n" && char !== "\r") continue;
        lines.push(buffer.slice(start, i));
        if (char === "\r") {
          if (i + 1 === buffer.length) skipLeadingLF = true;
          else if (buffer[i + 1] === "\n") i += 1;
        }
        start = i + 1;
      }
      buffer = buffer.slice(start);
      for (const complete of lines) line(complete);
    },
  };
}

type Listener = (notice: ChangeNotice) => void;

export interface EventsState {
  /** True from a stream's `hello` until that stream ends. */
  up: boolean;
  /** Bumped on every `hello`: each (re)connect is one resync. */
  epoch: number;
  /** Receive change notices while up; returns the unsubscribe. */
  subscribe: (listener: Listener) => () => void;
}

// Without a provider the stream is never up, so every poller polls as today.
const EventsContext = createContext<EventsState>({ up: false, epoch: 0, subscribe: () => () => {} });

export function useEvents(): EventsState {
  return useContext(EventsContext);
}

const BACKOFF_MS = [1_000, 2_000, 4_000, 8_000, 16_000, 30_000];
const CAPACITY_RETRY_MS = 30_000;
const HELLO_TIMEOUT_MS = 15_000;
const LIVED_LONG_MS = 10_000;
const DEFAULT_HEARTBEAT_SECONDS = 15;

function toNotice(data: Record<string, unknown>): ChangeNotice | null {
  if (data.kind === "jobs" || data.kind === "topics") return { kind: data.kind };
  if (data.kind === "run" && typeof data.topic === "string" && data.topic !== "") {
    return { kind: "run", topic: data.topic };
  }
  return null;
}

/**
 * Owns the tab's one events stream (App level, around the rail and every
 * route). Reconnects per the design note's table: 250-1000 ms after a stream
 * that lived 10 s past `hello`; 30 s after a 503; 1, 2, 4, 8, 16, then 30 s
 * (±20 % from `random`) after anything else that failed; never again after a
 * 404, a bodyless answer or an unknown protocol. A hidden tab drops its
 * stream and reconnects when shown. `<html data-events>` mirrors the state.
 */
export function EventsProvider({
  children,
  random = Math.random,
}: {
  children: ReactNode;
  random?: () => number;
}) {
  const [state, setState] = useState({ up: false, epoch: 0 });
  const listeners = useRef(new Set<Listener>());
  const randomRef = useRef(random);
  randomRef.current = random;

  const subscribe = useCallback((listener: Listener) => {
    listeners.current.add(listener);
    return () => {
      listeners.current.delete(listener);
    };
  }, []);

  useEffect(() => {
    const root = document.documentElement;
    let disposed = false;
    let controller: AbortController | null = null;
    let retry: number | undefined;
    let failures = 0;
    let unsupported = false;

    const setUp = (up: boolean) => {
      root.dataset.events = up ? "up" : "down";
      setState((s) => (up ? { up, epoch: s.epoch + 1 } : s.up ? { up, epoch: s.epoch } : s));
    };
    const schedule = (ms: number) => {
      window.clearTimeout(retry);
      retry = window.setTimeout(() => void connect(), Math.round(ms));
    };

    const connect = async () => {
      retry = undefined;
      if (disposed || unsupported || controller || document.visibilityState !== "visible") return;
      const attempt = new AbortController();
      controller = attempt;
      const s = {
        outcome: "backoff" as "backoff" | "capacity" | "unsupported",
        helloAt: null as number | null,
        idleMs: 3_000 * DEFAULT_HEARTBEAT_SECONDS,
        tripped: false,
        watchdog: undefined as number | undefined,
      };
      const arm = (ms: number) => {
        window.clearTimeout(s.watchdog);
        s.watchdog = window.setTimeout(() => {
          s.tripped = true;
          attempt.abort();
        }, ms);
      };
      arm(HELLO_TIMEOUT_MS); // until hello, even if the request never answers
      try {
        const resp = await openEventStream(attempt.signal);
        const reader = resp.ok ? resp.body?.getReader() : undefined;
        if (!resp.ok) void resp.body?.cancel().catch(() => {});
        if (resp.status === 404 || (resp.ok && !reader)) s.outcome = "unsupported";
        else if (resp.status === 503) s.outcome = "capacity";
        if (reader) {
          const parser = createSseParser(({ event, data }) => {
            if (event === "hello") {
              if (s.helloAt !== null) return;
              if (data.protocol !== 1) {
                s.outcome = "unsupported";
                attempt.abort();
                return;
              }
              const beat = data.heartbeat_seconds;
              if (typeof beat === "number" && Number.isFinite(beat) && beat > 0) s.idleMs = 3_000 * beat;
              s.helloAt = performance.now();
              setUp(true);
            } else if (s.helloAt !== null) {
              const notice = toNotice(data);
              if (notice) for (const listener of [...listeners.current]) listener(notice);
            }
          });
          for (;;) {
            const { done, value } = await reader.read();
            if (done) break;
            parser.push(value);
            if (s.helloAt !== null) arm(s.idleMs); // any byte after hello re-arms
          }
        }
      } catch {
        // A network failure, an abort (watchdog, hidden tab, unmount) or a broken body.
      }
      window.clearTimeout(s.watchdog);
      if (disposed || controller !== attempt) return; // unmounted, or dropped while hidden
      controller = null;
      setUp(false);
      if (s.outcome === "unsupported") {
        unsupported = true; // poll for the life of the page
      } else if (s.outcome === "capacity") {
        schedule(CAPACITY_RETRY_MS);
      } else if (!s.tripped && s.helloAt !== null && performance.now() - s.helloAt >= LIVED_LONG_MS) {
        failures = 0;
        schedule(250 + 750 * randomRef.current());
      } else {
        const base = BACKOFF_MS[Math.min(failures, BACKOFF_MS.length - 1)];
        failures += 1;
        schedule(base * (0.8 + 0.4 * randomRef.current()));
      }
    };

    const onVisibility = () => {
      if (document.visibilityState === "visible") {
        if (controller || unsupported) return;
        window.clearTimeout(retry);
        void connect();
        return;
      }
      window.clearTimeout(retry);
      retry = undefined;
      const dropped = controller;
      controller = null;
      dropped?.abort();
      setUp(false);
    };

    root.dataset.events = "down";
    document.addEventListener("visibilitychange", onVisibility);
    void connect();
    return () => {
      disposed = true;
      window.clearTimeout(retry);
      controller?.abort();
      controller = null;
      document.removeEventListener("visibilitychange", onVisibility);
      delete root.dataset.events;
    };
  }, []);

  const value = useMemo(
    () => ({ up: state.up, epoch: state.epoch, subscribe }),
    [state.up, state.epoch, subscribe],
  );
  return <EventsContext.Provider value={value}>{children}</EventsContext.Provider>;
}
