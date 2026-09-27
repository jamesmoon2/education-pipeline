import { act } from "@testing-library/react";
import { vi } from "vitest";

// Test-only harness for T62b: a controllable stand-in for the daemon's
// `GET /v1/events` stream (design note §1 wire format, §6 client).
//
// A test mocks `openEventStream` from the api client with `server.open`.
// Every attempt gets a real `Response` over a `ReadableStream` whose
// controller the test holds, so the cockpit reads it exactly as it reads the
// daemon: `resp.body.getReader()`, bytes, a `TextDecoder`. Aborting the
// attempt's signal errors the body with an AbortError, as `fetch` does.

const encoder = new TextEncoder();

export const HELLO = { heartbeat_seconds: 15, lifetime_seconds: 300, protocol: 1 };

export type Notice =
  | { kind: "run"; topic: string }
  | { kind: "jobs" }
  | { kind: "topics" };

export class FakeEventStream {
  readonly response: Response;
  closed = false;
  private controller!: ReadableStreamDefaultController<Uint8Array>;

  constructor(readonly signal: AbortSignal) {
    const body = new ReadableStream<Uint8Array>({
      start: (controller) => {
        this.controller = controller;
      },
    });
    this.response = new Response(body, {
      status: 200,
      headers: { "Content-Type": "text/event-stream; charset=utf-8" },
    });
    signal.addEventListener("abort", () => {
      if (this.closed) return;
      this.closed = true;
      try {
        this.controller.error(new DOMException("The operation was aborted.", "AbortError"));
      } catch {
        // already errored or closed
      }
    });
  }

  /** Raw bytes on the wire, exactly as given. */
  sendBytes(bytes: Uint8Array): void {
    if (this.closed) return;
    this.controller.enqueue(bytes);
  }

  send(text: string): void {
    this.sendBytes(encoder.encode(text));
  }

  hello(overrides: Partial<typeof HELLO> = {}): void {
    this.send(`event: hello\ndata: ${JSON.stringify({ ...HELLO, ...overrides })}\n\n`);
  }

  change(notice: Notice): void {
    this.send(`event: change\ndata: ${JSON.stringify(notice)}\n\n`);
  }

  keepalive(): void {
    this.send(": keepalive\n\n");
  }

  /** Clean EOF: the daemon closed the connection (lifetime end, shutdown). */
  end(): void {
    if (this.closed) return;
    this.closed = true;
    this.controller.close();
  }
}

/**
 * `open` has `openEventStream`'s shape: `(signal) => Promise<Response>`.
 * Attempts that should fail differently (a status, a network error, a fetch
 * that never answers) are queued per call with `mockImplementationOnce` on
 * the mocked client function, or with the helpers below.
 */
export function createFakeEventServer() {
  const streams: FakeEventStream[] = [];
  const open = (signal: AbortSignal): Promise<Response> => {
    const stream = new FakeEventStream(signal);
    streams.push(stream);
    return Promise.resolve(stream.response);
  };
  return {
    streams,
    open,
    get current(): FakeEventStream {
      const stream = streams[streams.length - 1];
      if (!stream) throw new Error("no event stream has been opened");
      return stream;
    },
  };
}

/** An attempt answered with an HTTP status and the standard error envelope. */
export function statusResponse(status: number, code = "error"): Promise<Response> {
  return Promise.resolve(
    new Response(JSON.stringify({ error: { code, message: code } }), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

/** A request the daemon accepted but never answered; rejects on abort, like fetch. */
export function pendingUntilAborted(signal: AbortSignal): Promise<Response> {
  return new Promise((_resolve, reject) => {
    signal.addEventListener("abort", () =>
      reject(new DOMException("The operation was aborted.", "AbortError")),
    );
  });
}

/**
 * Fake timers with both clocks faked: `Date.now()` and `performance.now()`
 * advance together, so the implementation may measure a stream's age with
 * either.
 */
export function useFakeClock(): void {
  vi.useFakeTimers({
    toFake: [
      "setTimeout",
      "clearTimeout",
      "setInterval",
      "clearInterval",
      "setImmediate",
      "clearImmediate",
      "Date",
      "performance",
    ],
  });
}

/** Advance fake time and let React, the stream reader and fetch mocks settle. */
export async function flush(ms = 0): Promise<void> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

/**
 * An idle, healthy stream: `totalMs` of fake time with a `: keepalive`
 * comment every `everyMs` (the daemon's heartbeat), and no change frames.
 */
export async function idleWithKeepalives(
  stream: FakeEventStream,
  totalMs: number,
  everyMs = 15_000,
): Promise<void> {
  for (let elapsed = 0; elapsed < totalMs; elapsed += everyMs) {
    await flush(Math.min(everyMs, totalMs - elapsed));
    stream.keepalive();
  }
  await flush(0);
}

/** The stream state the cockpit mirrors onto <html data-events> for e2e (design note §6). */
export function eventsAttribute(): string | undefined {
  return document.documentElement.dataset.events;
}
