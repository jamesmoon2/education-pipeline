import { render, renderHook } from "@testing-library/react";
import { StrictMode, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// T62b (plan decisions 9-13; design note §1 wire format, §6 client, §7 test
// plan): the SSE parser, the notice matcher, and EventsProvider's
// connection state machine — one stream per tab over the client's
// openEventStream (fetch + ReadableStream, never EventSource), the reconnect
// table with injectable jitter, both watchdogs, and hidden tabs dropping
// their stream.

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return {
    ApiRequestError: actual.ApiRequestError,
    openEventStream: vi.fn(),
  };
});

import { openEventStream } from "../api/client";
import {
  EventsProvider,
  createSseParser,
  noticeMatches,
  useEvents,
  type ChangeNotice,
  type NoticeFilter,
} from "./useEvents";
import {
  createFakeEventServer,
  eventsAttribute,
  flush,
  pendingUntilAborted,
  statusResponse,
  useFakeClock,
} from "../test/eventStream";

const encoder = new TextEncoder();

// ---------------------------------------------------------------------------
// createSseParser: bytes in, typed events out. Pure; no provider, no timers.
// ---------------------------------------------------------------------------

function parse(chunks: Array<string | Uint8Array>): unknown[] {
  const events: unknown[] = [];
  const parser = createSseParser((event) => events.push(event));
  for (const chunk of chunks) {
    parser.push(typeof chunk === "string" ? encoder.encode(chunk) : chunk);
  }
  return events;
}

const HELLO_EVENT = {
  event: "hello",
  data: { heartbeat_seconds: 15, lifetime_seconds: 300, protocol: 1 },
};
const JOBS_EVENT = { event: "change", data: { kind: "jobs" } };
const TOPICS_EVENT = { event: "change", data: { kind: "topics" } };

// The §1 sample, byte for byte as the daemon writes it.
const WIRE_SAMPLE = [
  "event: hello",
  'data: {"heartbeat_seconds":15,"lifetime_seconds":300,"protocol":1}',
  "",
  "event: change",
  'data: {"kind":"run","topic":"intro-statistics"}',
  "",
  "event: change",
  'data: {"kind":"jobs"}',
  "",
  "event: change",
  'data: {"kind":"topics"}',
  "",
  ": keepalive",
  "",
  "",
];
const WIRE_EVENTS = [
  HELLO_EVENT,
  { event: "change", data: { kind: "run", topic: "intro-statistics" } },
  JOBS_EVENT,
  TOPICS_EVENT,
];

describe("createSseParser", () => {
  it("dispatches the hello and change frames of the §1 wire sample, in order", () => {
    expect(parse([WIRE_SAMPLE.join("\n")])).toEqual(WIRE_EVENTS);
  });

  it("accepts CRLF and bare CR line endings", () => {
    expect(parse([WIRE_SAMPLE.join("\r\n")])).toEqual(WIRE_EVENTS);
    expect(parse([WIRE_SAMPLE.join("\r")])).toEqual(WIRE_EVENTS);
  });

  it("treats a CR ending one chunk and an LF starting the next as one line end, not two", () => {
    // Read as two line ends, the LF would be a blank line: it would dispatch
    // an event with no data and reset the event type, and the change would
    // then arrive as an ignored default "message".
    expect(parse(["event: change\r", '\ndata: {"kind":"jobs"}\r\n\r\n'])).toEqual([JOBS_EVENT]);
    // The same split on the blank line that ends the frame dispatches once.
    expect(
      parse([
        'event: change\r\ndata: {"kind":"jobs"}\r\n\r',
        '\nevent: change\r\ndata: {"kind":"topics"}\r\n\r\n',
      ]),
    ).toEqual([JOBS_EVENT, TOPICS_EVENT]);
  });

  it("still ends the line at a chunk-final CR when the next chunk starts with anything else", () => {
    expect(parse(["event: change\r", 'data: {"kind":"jobs"}\r', "\r"])).toEqual([JOBS_EVENT]);
  });

  it("reassembles a field split mid-line across chunks", () => {
    expect(
      parse(["eve", "nt: cha", "nge\nda", 'ta: {"kind":', '"topics"}\n', "\n"]),
    ).toEqual([TOPICS_EVENT]);
  });

  it("decodes a multi-byte UTF-8 character split across chunks", () => {
    const bytes = encoder.encode('event: change\ndata: {"kind":"run","topic":"café"}\n\n');
    const lead = bytes.indexOf(0xc3); // first byte of the two-byte "é"
    expect(lead).toBeGreaterThan(0);
    expect(parse([bytes.slice(0, lead + 1), bytes.slice(lead + 1)])).toEqual([
      { event: "change", data: { kind: "run", topic: "café" } },
    ]);
  });

  it("joins multi-line data with newlines before parsing it", () => {
    expect(
      parse(['event: change\ndata: {"kind":\ndata: "run","topic":\ndata: "t"}\n\n']),
    ).toEqual([{ event: "change", data: { kind: "run", topic: "t" } }]);
    // The join is a newline, not nothing: a number split across two data
    // lines is two tokens, so that frame is bad JSON and is ignored.
    expect(parse(['event: change\ndata: {"kind":"jobs","n":1\ndata: 2}\n\n'])).toEqual([]);
  });

  it("ignores comments, id and retry, and a comment inside a frame does not split it", () => {
    expect(parse([": keepalive\n\n"])).toEqual([]);
    expect(
      parse(['event: change\n: a note\nid: 7\nretry: 10\ndata: {"kind":"jobs"}\n\n']),
    ).toEqual([JOBS_EVENT]);
  });

  it("ignores unknown events and frames without an event field, and keeps parsing", () => {
    expect(
      parse([
        "event: ping\ndata: {}\n\n",
        'data: {"kind":"jobs"}\n\n',
        'event: change\ndata: {"kind":"topics"}\n\n',
      ]),
    ).toEqual([TOPICS_EVENT]);
  });

  it("does not carry an event type over into the next frame", () => {
    expect(parse(['event: change\ndata: {"kind":"jobs"}\n\ndata: {"kind":"topics"}\n\n'])).toEqual(
      [JOBS_EVENT],
    );
  });

  it("ignores bad JSON and non-object data, and keeps parsing", () => {
    expect(
      parse([
        "event: change\ndata: {nope\n\n",
        "event: change\ndata: 42\n\n",
        "event: change\ndata: null\n\n",
        'event: change\ndata: "jobs"\n\n',
        "event: change\ndata: [1]\n\n",
        "event: hello\ndata: {oops\n\n",
        'event: change\ndata: {"kind":"jobs"}\n\n',
      ]),
    ).toEqual([JOBS_EVENT]);
  });

  it("dispatches nothing for a frame without data, or before its blank line arrives", () => {
    expect(parse(["event: change\n\n"])).toEqual([]);
    const events: unknown[] = [];
    const parser = createSseParser((event) => events.push(event));
    parser.push(encoder.encode('event: change\ndata: {"kind":"jobs"}\n'));
    expect(events).toEqual([]);
    parser.push(encoder.encode("\n"));
    expect(events).toEqual([JOBS_EVENT]);
  });

  it("strips one space after the colon and accepts none", () => {
    expect(parse(['event:change\ndata:{"kind":"jobs"}\n\n'])).toEqual([JOBS_EVENT]);
  });

  it("never throws, whatever the bytes, and recovers at the next frame", () => {
    const events: unknown[] = [];
    const parser = createSseParser((event) => events.push(event));
    const garbage: Uint8Array[] = [
      new Uint8Array([0xff, 0xfe, 0x00, 0x0a, 0xc3]),
      encoder.encode("no colon at all\nevent\ndata\n\r\r\r\n\n"),
      encoder.encode(`data: ${"x".repeat(10_000)}\n\n`),
      encoder.encode("event: change\ndata: {}\n\n"),
      encoder.encode(":\n::\n: \n\n\n\n"),
    ];
    for (const chunk of garbage) expect(() => parser.push(chunk)).not.toThrow();
    const before = events.length;
    parser.push(encoder.encode('event: change\ndata: {"kind":"jobs"}\n\n'));
    expect(events.slice(before)).toEqual([JOBS_EVENT]);
  });
});

// ---------------------------------------------------------------------------
// noticeMatches: the per-call-site filter table (design note §6).
// ---------------------------------------------------------------------------

describe("noticeMatches", () => {
  const runT: ChangeNotice = { kind: "run", topic: "t" };
  const runU: ChangeNotice = { kind: "run", topic: "u" };
  const jobs: ChangeNotice = { kind: "jobs" };
  const topics: ChangeNotice = { kind: "topics" };
  const notices = [runT, runU, jobs, topics];

  const table: Array<[string, NoticeFilter, boolean[]]> = [
    ["{ run: t }", { run: "t" }, [true, false, false, false]],
    ['{ run: "*" }', { run: "*" }, [true, true, false, false]],
    ["{ jobs }", { jobs: true }, [false, false, true, false]],
    ["{ topics }", { topics: true }, [false, false, false, true]],
    ['{ run: "*", topics }', { run: "*", topics: true }, [true, true, false, true]],
    ["{ run: t, jobs }", { run: "t", jobs: true }, [true, false, true, false]],
    ["{}", {}, [false, false, false, false]],
  ];

  it.each(table)("%s matches run t, run u, jobs, topics as %j", (_label, filter, expected) => {
    expect(notices.map((notice) => noticeMatches(filter, notice))).toEqual(expected);
  });
});

// ---------------------------------------------------------------------------
// useEvents without a provider: today's behaviour.
// ---------------------------------------------------------------------------

describe("useEvents without a provider", () => {
  it("is never up, and subscribe is inert, so pages poll exactly as today", () => {
    const { result } = renderHook(() => useEvents());
    expect(result.current.up).toBe(false);
    const unsubscribe = result.current.subscribe(() => {
      throw new Error("no provider, no notices");
    });
    expect(typeof unsubscribe).toBe("function");
    unsubscribe();
    expect(openEventStream).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// EventsProvider
// ---------------------------------------------------------------------------

const setVisibility = (state: DocumentVisibilityState) =>
  Object.defineProperty(document, "visibilityState", { value: state, configurable: true });

async function showTab(state: DocumentVisibilityState) {
  setVisibility(state);
  document.dispatchEvent(new Event("visibilitychange"));
  await flush(0);
}

let server: ReturnType<typeof createFakeEventServer>;

beforeEach(() => {
  vi.clearAllMocks();
  useFakeClock();
  server = createFakeEventServer();
  // clearAllMocks keeps queued mockImplementationOnce answers; start clean.
  vi.mocked(openEventStream).mockReset();
  vi.mocked(openEventStream).mockImplementation(server.open);
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  setVisibility("visible");
  delete document.documentElement.dataset.events;
});

function mountProvider(random: () => number = () => 0.5) {
  const wrapper = ({ children }: { children: ReactNode }) => (
    <EventsProvider random={random}>{children}</EventsProvider>
  );
  return renderHook(() => useEvents(), { wrapper });
}

const attempts = () => vi.mocked(openEventStream).mock.calls.length;
const signalOf = (attempt: number) => vi.mocked(openEventStream).mock.calls[attempt - 1][0] as AbortSignal;

/** The next attempt starts exactly `ms` after now: not at ms - 1, but at ms. */
async function expectNextAttemptAfter(ms: number) {
  const before = attempts();
  await flush(ms - 1);
  expect(attempts()).toBe(before);
  await flush(1);
  expect(attempts()).toBe(before + 1);
}

describe("EventsProvider: opening the stream", () => {
  it("opens one stream through openEventStream with an AbortSignal — never EventSource, never a bare fetch", async () => {
    const eventSource = vi.fn();
    const fetchSpy = vi.fn(() => new Promise(() => {}));
    vi.stubGlobal("EventSource", eventSource);
    vi.stubGlobal("fetch", fetchSpy);
    mountProvider();
    await flush(0);
    expect(openEventStream).toHaveBeenCalledTimes(1);
    expect(signalOf(1)).toBeInstanceOf(AbortSignal);
    expect(signalOf(1).aborted).toBe(false);
    expect(eventSource).not.toHaveBeenCalled();
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("is up from hello until the reader ends, bumps epoch on every hello, and mirrors data-events", async () => {
    const { result } = mountProvider();
    await flush(0);
    expect(result.current.up).toBe(false);
    expect(result.current.epoch).toBe(0);
    expect(eventsAttribute()).not.toBe("up");

    server.current.hello();
    await flush(0);
    expect(result.current.up).toBe(true);
    expect(result.current.epoch).toBe(1);
    expect(eventsAttribute()).toBe("up");

    await flush(10_000);
    server.current.end();
    await flush(0);
    expect(result.current.up).toBe(false);
    expect(eventsAttribute()).not.toBe("up");

    await flush(1_000); // lived ≥ 10 s: back within 250-1000 ms
    expect(attempts()).toBe(2);
    server.current.hello();
    await flush(0);
    expect(result.current.up).toBe(true);
    expect(result.current.epoch).toBe(2);
  });

  it("delivers change notices to every subscriber until it unsubscribes", async () => {
    const { result } = mountProvider();
    await flush(0);
    server.current.hello();
    await flush(0);
    const a = vi.fn();
    const b = vi.fn();
    const unsubscribeA = result.current.subscribe(a);
    result.current.subscribe(b);

    server.current.change({ kind: "run", topic: "t" });
    await flush(0);
    expect(a.mock.calls).toEqual([[{ kind: "run", topic: "t" }]]);
    expect(b.mock.calls).toEqual([[{ kind: "run", topic: "t" }]]);

    unsubscribeA();
    server.current.change({ kind: "jobs" });
    await flush(0);
    expect(a).toHaveBeenCalledTimes(1);
    expect(b.mock.calls[1]).toEqual([{ kind: "jobs" }]);
  });

  it("keeps exactly one live stream through StrictMode's double effect", async () => {
    render(
      <StrictMode>
        <EventsProvider random={() => 0.5}>
          <p>child</p>
        </EventsProvider>
      </StrictMode>,
    );
    await flush(0);
    const live = vi
      .mocked(openEventStream)
      .mock.calls.filter(([signal]) => !(signal as AbortSignal).aborted);
    expect(attempts()).toBeGreaterThanOrEqual(1);
    expect(live).toHaveLength(1);
  });

  it("aborts its stream on unmount and never reconnects", async () => {
    const { unmount } = mountProvider();
    await flush(0);
    server.current.hello();
    await flush(0);
    unmount();
    await flush(0);
    expect(signalOf(1).aborted).toBe(true);
    expect(eventsAttribute()).not.toBe("up");
    await flush(10 * 60_000);
    expect(attempts()).toBe(1);
  });
});

describe("EventsProvider: reconnect table (random fixed at 0.5 = no jitter)", () => {
  it("backs off 1, 2, 4, 8, 16, then 30 s on network errors, and stays at the cap", async () => {
    vi.mocked(openEventStream).mockRejectedValue(new TypeError("Failed to fetch"));
    mountProvider();
    await flush(0);
    expect(attempts()).toBe(1);
    for (const delay of [1_000, 2_000, 4_000, 8_000, 16_000, 30_000, 30_000]) {
      await expectNextAttemptAfter(delay);
    }
  });

  it("takes ±20 % jitter from the injected random: base × (0.8 + 0.4 × random)", async () => {
    vi.mocked(openEventStream).mockRejectedValue(new TypeError("Failed to fetch"));
    mountProvider(() => 0);
    await flush(0);
    await expectNextAttemptAfter(800);
    await expectNextAttemptAfter(1_600);
    await expectNextAttemptAfter(3_200);
  });

  it("uses the backoff row for EOF before hello", async () => {
    mountProvider();
    await flush(0);
    server.current.end();
    await flush(0);
    await expectNextAttemptAfter(1_000);
    server.current.end();
    await flush(0);
    await expectNextAttemptAfter(2_000);
  });

  it("uses the backoff row for EOF under 10 s after hello, and hello alone does not reset it", async () => {
    const { result } = mountProvider();
    await flush(0);
    server.current.hello();
    await flush(9_999);
    server.current.end();
    await flush(0);
    expect(result.current.up).toBe(false);
    await expectNextAttemptAfter(1_000);
    server.current.hello();
    await flush(0);
    server.current.end();
    await flush(0);
    await expectNextAttemptAfter(2_000);
  });

  it("reconnects in 250 + 750 × random ms after a stream that lived 10 s past hello, and resets the backoff", async () => {
    vi.mocked(openEventStream)
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockImplementationOnce(server.open)
      .mockRejectedValueOnce(new TypeError("Failed to fetch"));
    mountProvider();
    await flush(0);
    await expectNextAttemptAfter(1_000); // backoff step 1 spent
    server.current.hello();
    await flush(10_000);
    server.current.end();
    await flush(0);
    await expectNextAttemptAfter(625); // 250 + 750 × 0.5
    // Reset: the next failure starts over at 1 s, not at the 2 s step.
    await expectNextAttemptAfter(1_000);
  });

  it("maps the lived-long reconnect through random as well", async () => {
    mountProvider(() => 0);
    await flush(0);
    server.current.hello();
    await flush(10_000);
    server.current.end();
    await flush(0);
    await expectNextAttemptAfter(250);
  });

  it("waits 30 s after a 503 events_capacity", async () => {
    vi.mocked(openEventStream).mockImplementationOnce(() => statusResponse(503, "events_capacity"));
    mountProvider();
    await flush(0);
    await expectNextAttemptAfter(30_000);
  });

  it("takes the backoff row for 401, another 4xx and another 5xx", async () => {
    vi.mocked(openEventStream)
      .mockImplementationOnce(() => statusResponse(401, "unauthorized"))
      .mockImplementationOnce(() => statusResponse(400, "bad_host"))
      .mockImplementationOnce(() => statusResponse(500, "internal"))
      .mockImplementation(() => statusResponse(502, "bad_gateway"));
    mountProvider();
    await flush(0);
    await expectNextAttemptAfter(1_000); // after the 401
    await expectNextAttemptAfter(2_000); // after the 400
    await expectNextAttemptAfter(4_000); // after the 500
    await expectNextAttemptAfter(8_000); // after the 502
  });

  it.each([
    ["404 from an older daemon", () => statusResponse(404, "not_found")],
    ["a 200 without a readable body", () => Promise.resolve(new Response(null, { status: 200 }))],
  ])("stops for the life of the page after %s", async (_label, answer) => {
    vi.mocked(openEventStream).mockImplementation(answer);
    const { result } = mountProvider();
    await flush(0);
    await flush(30 * 60_000);
    expect(attempts()).toBe(1);
    expect(result.current.up).toBe(false);
    expect(eventsAttribute()).not.toBe("up");
  });

  it("treats a hello with protocol != 1 as unsupported: closes it and never reconnects", async () => {
    const { result } = mountProvider();
    await flush(0);
    server.current.hello({ protocol: 2 });
    await flush(0);
    expect(result.current.up).toBe(false);
    expect(result.current.epoch).toBe(0);
    expect(signalOf(1).aborted).toBe(true);
    await flush(30 * 60_000);
    expect(attempts()).toBe(1);
  });
});

describe("EventsProvider: watchdogs", () => {
  it("aborts a request still unanswered 15 s after it started, then backs off", async () => {
    vi.mocked(openEventStream).mockImplementationOnce(pendingUntilAborted);
    mountProvider();
    await flush(14_999);
    expect(signalOf(1).aborted).toBe(false);
    await flush(1);
    expect(signalOf(1).aborted).toBe(true);
    await expectNextAttemptAfter(1_000);
  });

  it("aborts a stream that sends no hello within 15 s of the request", async () => {
    mountProvider();
    await flush(14_999);
    expect(signalOf(1).aborted).toBe(false);
    await flush(1);
    expect(signalOf(1).aborted).toBe(true);
    await expectNextAttemptAfter(1_000);
  });

  it("after hello, aborts after 3 × heartbeat_seconds without a byte; any byte re-arms it; then the backoff row", async () => {
    const { result } = mountProvider();
    await flush(0);
    server.current.hello(); // heartbeat_seconds 15 → 45 s
    await flush(40_000);
    server.current.keepalive();
    await flush(40_000);
    server.current.change({ kind: "jobs" });
    await flush(44_999);
    expect(result.current.up).toBe(true);
    expect(signalOf(1).aborted).toBe(false);
    await flush(1);
    expect(signalOf(1).aborted).toBe(true);
    expect(result.current.up).toBe(false);
    expect(eventsAttribute()).not.toBe("up");
    // A watchdog is the backoff row even though the stream lived > 10 s.
    await expectNextAttemptAfter(1_000);
  });

  it("scales the idle watchdog with the hello's heartbeat_seconds", async () => {
    mountProvider();
    await flush(0);
    server.current.hello({ heartbeat_seconds: 2 });
    await flush(5_999);
    expect(signalOf(1).aborted).toBe(false);
    await flush(1);
    expect(signalOf(1).aborted).toBe(true);
  });
});

describe("EventsProvider: hidden tabs", () => {
  it("drops the stream while hidden and reconnects at once when shown", async () => {
    const { result } = mountProvider();
    await flush(0);
    server.current.hello();
    await flush(0);

    await showTab("hidden");
    expect(signalOf(1).aborted).toBe(true);
    expect(result.current.up).toBe(false);
    expect(eventsAttribute()).not.toBe("up");
    await flush(10 * 60_000);
    expect(attempts()).toBe(1);

    await showTab("visible");
    expect(attempts()).toBe(2);
    server.current.hello();
    await flush(0);
    expect(result.current.up).toBe(true);
    expect(result.current.epoch).toBe(2);
  });

  it("makes no attempt while hidden, even with a backoff timer pending", async () => {
    vi.mocked(openEventStream).mockRejectedValueOnce(new TypeError("Failed to fetch"));
    mountProvider();
    await flush(500);
    await showTab("hidden");
    await flush(10 * 60_000);
    expect(attempts()).toBe(1);
    await showTab("visible");
    expect(attempts()).toBe(2);
  });

  it("connects only once a tab that mounted hidden is shown", async () => {
    setVisibility("hidden");
    mountProvider();
    await flush(60_000);
    expect(attempts()).toBe(0);
    await showTab("visible");
    expect(attempts()).toBe(1);
  });
});
