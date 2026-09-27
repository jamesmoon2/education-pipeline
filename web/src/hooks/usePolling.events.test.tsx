import { act, render, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// T62b (plan decision 13; design note §6 "usePolling"): with an `events`
// filter and the stream up, a poller stops its timer chain and fetches once
// per resync (hello epoch) and once per matching notice, with one in-flight
// fetch plus one queued follow-up at most. Without a filter, or while the
// stream is down, it polls exactly as today — usePolling.test.ts pins that
// and is not edited.
//
// These cases live beside usePolling.test.ts rather than inside it so the
// existing file keeps loading while ./useEvents does not exist yet.

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return {
    ApiRequestError: actual.ApiRequestError,
    openEventStream: vi.fn(),
  };
});

import { openEventStream } from "../api/client";
import { EventsProvider, type NoticeFilter } from "./useEvents";
import { usePolling } from "./usePolling";
import {
  createFakeEventServer,
  flush,
  idleWithKeepalives,
  pendingUntilAborted,
  useFakeClock,
} from "../test/eventStream";

let server: ReturnType<typeof createFakeEventServer>;
const random = () => 0.5;

function Provider({ children }: { children: ReactNode }) {
  return <EventsProvider random={random}>{children}</EventsProvider>;
}

/**
 * Mount a poller under the provider. The filter is spread into a fresh
 * literal on every render, as every call site does.
 */
function mountPoller<T>(fetcher: () => Promise<T>, intervalMs: number, filter?: NoticeFilter) {
  return renderHook(
    () => usePolling(fetcher, intervalMs, filter ? { events: { ...filter } } : undefined),
    { wrapper: Provider },
  );
}

/** A fetcher whose calls stay in flight until the test settles them. */
function deferredFetcher() {
  const pending: Array<{ resolve: (value: { n: number }) => void; reject: (err: Error) => void }> = [];
  let served = 0;
  const fetcher = vi.fn(
    () =>
      new Promise<{ n: number }>((resolve, reject) => {
        pending.push({ resolve, reject });
      }),
  );
  const settle = async () => {
    for (const call of pending.splice(0)) call.resolve({ n: (served += 1) });
    await flush(0);
  };
  return { fetcher, settle, pending };
}

async function hello() {
  server.current.hello();
  await flush(0);
}

const setVisibility = (state: DocumentVisibilityState) =>
  Object.defineProperty(document, "visibilityState", { value: state, configurable: true });

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
  setVisibility("visible");
  delete document.documentElement.dataset.events;
});

describe("usePolling with an events filter", () => {
  it("without a filter, keeps polling on its interval even while the stream is up", async () => {
    const fetcher = vi.fn(async () => "x");
    mountPoller(fetcher, 1_000);
    await flush(0);
    await hello();
    const before = fetcher.mock.calls.length;
    await flush(5_000);
    expect(fetcher.mock.calls.length - before).toBe(5);
  });

  it("with a filter but no stream up, polls exactly as today", async () => {
    vi.mocked(openEventStream).mockImplementation(pendingUntilAborted);
    const fetcher = vi.fn(async () => "x");
    mountPoller(fetcher, 1_000, { run: "t" });
    await flush(0);
    expect(fetcher).toHaveBeenCalledTimes(1);
    await flush(5_000);
    expect(fetcher).toHaveBeenCalledTimes(6);
  });

  it("stops its timer chain while the stream is up: one resync fetch, then nothing while idle", async () => {
    const fetcher = vi.fn(async () => "x");
    mountPoller(fetcher, 1_000, { run: "t" });
    await flush(0);
    expect(fetcher).toHaveBeenCalledTimes(1); // the mount tick
    await hello();
    expect(fetcher).toHaveBeenCalledTimes(2); // the hello resync
    await idleWithKeepalives(server.current, 10 * 60_000);
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("fetches once per matching notice and never for a notice it does not name", async () => {
    const fetcher = vi.fn(async () => "x");
    mountPoller(fetcher, 1_000, { run: "t" });
    await flush(0);
    await hello();
    const count = () => fetcher.mock.calls.length;
    let before = count();

    server.current.change({ kind: "run", topic: "t" });
    await flush(0);
    expect(count() - before).toBe(1);

    before = count();
    server.current.change({ kind: "run", topic: "other" });
    server.current.change({ kind: "jobs" });
    server.current.change({ kind: "topics" });
    await flush(0);
    await idleWithKeepalives(server.current, 60_000);
    expect(count() - before).toBe(0);
  });

  it("turns notices that arrive during an in-flight fetch into exactly one follow-up", async () => {
    const { fetcher, settle } = deferredFetcher();
    mountPoller(fetcher, 1_000, { run: "t" });
    await flush(0);
    await settle(); // mount tick
    await hello();
    await settle(); // resync
    expect(fetcher).toHaveBeenCalledTimes(2);

    server.current.change({ kind: "run", topic: "t" });
    await flush(0);
    expect(fetcher).toHaveBeenCalledTimes(3); // in flight
    for (let i = 0; i < 3; i++) {
      server.current.change({ kind: "run", topic: "t" });
      await flush(0);
    }
    expect(fetcher).toHaveBeenCalledTimes(3); // still one in flight, one queued

    await settle();
    expect(fetcher).toHaveBeenCalledTimes(4); // the single follow-up
    await settle();
    await idleWithKeepalives(server.current, 60_000);
    expect(fetcher).toHaveBeenCalledTimes(4);
  });

  it("queues the hello resync behind a mount fetch still in flight, as one follow-up", async () => {
    const { fetcher, settle } = deferredFetcher();
    mountPoller(fetcher, 1_000, { run: "t" });
    await flush(0);
    expect(fetcher).toHaveBeenCalledTimes(1);
    await hello();
    expect(fetcher).toHaveBeenCalledTimes(1);
    await settle();
    expect(fetcher).toHaveBeenCalledTimes(2);
    await settle();
    await idleWithKeepalives(server.current, 60_000);
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("costs one fetch per hello: a reconnect's hello is one more resync", async () => {
    const fetcher = vi.fn(async () => "x");
    mountPoller(fetcher, 1_000, { run: "t" });
    await flush(0);
    await hello();
    await flush(10_000);
    const beforeEnd = fetcher.mock.calls.length;
    server.current.end(); // lived ≥ 10 s: reconnect in 625 ms
    await flush(0);
    expect(fetcher.mock.calls.length - beforeEnd).toBe(1); // up → down: immediate tick
    await flush(625);
    expect(openEventStream).toHaveBeenCalledTimes(2);
    const beforeHello = fetcher.mock.calls.length;
    await hello();
    expect(fetcher.mock.calls.length - beforeHello).toBe(1);
    await idleWithKeepalives(server.current, 60_000);
    expect(fetcher.mock.calls.length - beforeHello).toBe(1);
  });

  it("restarts the chain with an immediate tick when the stream goes down, then polls on its interval", async () => {
    vi.mocked(openEventStream)
      .mockImplementationOnce(server.open)
      .mockImplementation(pendingUntilAborted);
    const fetcher = vi.fn(async () => "x");
    mountPoller(fetcher, 1_000, { run: "t" });
    await flush(0);
    await hello();
    await idleWithKeepalives(server.current, 30_000);
    const before = fetcher.mock.calls.length;
    server.current.end();
    await flush(0);
    expect(fetcher.mock.calls.length - before).toBe(1);
    await flush(1_000);
    expect(fetcher.mock.calls.length - before).toBe(2);
    await flush(1_000);
    expect(fetcher.mock.calls.length - before).toBe(3);
  });

  it("compares the filter by value: fresh literals on re-render neither restart the chain nor refetch", async () => {
    vi.mocked(openEventStream)
      .mockImplementationOnce(pendingUntilAborted) // down first
      .mockImplementation(server.open);
    const fetcher = vi.fn(async () => ({ same: true }));
    const { result, rerender } = mountPoller(fetcher, 1_000, { run: "t" });
    await flush(0);
    expect(fetcher).toHaveBeenCalledTimes(1);
    const first = result.current.data;

    // Down: a restarted chain would tick at once on every render.
    for (let i = 0; i < 3; i++) rerender();
    await flush(0);
    expect(fetcher).toHaveBeenCalledTimes(1);
    await flush(1_000);
    expect(fetcher).toHaveBeenCalledTimes(2); // one chain, on its interval
    expect(result.current.data).toBe(first); // lastKey survived the renders

    // Up (after the pre-hello watchdog and one backoff step).
    await flush(15_000);
    await flush(1_000);
    expect(openEventStream).toHaveBeenCalledTimes(2);
    await hello();
    const before = fetcher.mock.calls.length;
    for (let i = 0; i < 3; i++) rerender();
    await idleWithKeepalives(server.current, 60_000);
    expect(fetcher.mock.calls.length).toBe(before);
    expect(result.current.data).toBe(first);
  });

  it("keeps the payload bail-out for stream-driven fetches", async () => {
    let status = "running";
    const fetcher = vi.fn(async () => ({ jobs: [{ id: "j1", status }] }));
    const { result } = mountPoller(fetcher, 1_000, { jobs: true });
    await flush(0);
    const first = result.current.data;
    await hello();
    server.current.change({ kind: "jobs" });
    await flush(0);
    expect(fetcher).toHaveBeenCalledTimes(3);
    expect(result.current.data).toBe(first);

    status = "succeeded";
    server.current.change({ kind: "jobs" });
    await flush(0);
    expect(result.current.data).not.toBe(first);
    expect(result.current.data).toEqual({ jobs: [{ id: "j1", status: "succeeded" }] });
  });

  it("refresh() while up fetches once and republishes, without starting a chain", async () => {
    const fetcher = vi.fn(async () => ({ same: true }));
    const { result } = mountPoller(fetcher, 1_000, { run: "t" });
    await flush(0);
    await hello();
    const first = result.current.data;
    const before = fetcher.mock.calls.length;
    await act(async () => {
      result.current.refresh();
    });
    await flush(0);
    expect(fetcher.mock.calls.length - before).toBe(1);
    expect(result.current.data).not.toBe(first);
    expect(result.current.data).toEqual({ same: true });
    await idleWithKeepalives(server.current, 60_000);
    expect(fetcher.mock.calls.length - before).toBe(1);
  });

  it("re-arms its own interval after a stream-driven fetch fails, until one succeeds, then stops", async () => {
    let calls = 0;
    const fetcher = vi.fn(async () => {
      calls += 1;
      if (calls === 3 || calls === 4) throw new Error("sharing violation");
      return calls;
    });
    const { result } = mountPoller(fetcher, 1_000, { run: "t" });
    await flush(0);
    await hello(); // calls 1 (mount) and 2 (resync)
    server.current.change({ kind: "run", topic: "t" });
    await flush(0);
    expect(fetcher).toHaveBeenCalledTimes(3);
    expect(result.current.error?.message).toBe("sharing violation");

    await flush(999);
    expect(fetcher).toHaveBeenCalledTimes(3);
    await flush(1);
    expect(fetcher).toHaveBeenCalledTimes(4); // fails again
    await flush(1_000);
    expect(fetcher).toHaveBeenCalledTimes(5); // succeeds
    expect(result.current.error).toBeNull();
    expect(result.current.data).toBe(5);

    await idleWithKeepalives(server.current, 60_000);
    expect(fetcher).toHaveBeenCalledTimes(5);
  });

  it("mounting while the stream is already up fetches once and starts no chain", async () => {
    const fetcher = vi.fn(async () => "x");
    function Poller() {
      usePolling(fetcher, 1_000, { events: { run: "t" } });
      return null;
    }
    const ui = (show: boolean) => <Provider>{show ? <Poller /> : null}</Provider>;
    const { rerender } = render(ui(false));
    await flush(0);
    await hello();
    rerender(ui(true));
    await flush(0);
    expect(fetcher).toHaveBeenCalledTimes(1);
    await idleWithKeepalives(server.current, 60_000);
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("fetches nothing while the tab is hidden, and at most the visibility tick plus the resync on show", async () => {
    const fetcher = vi.fn(async () => "x");
    mountPoller(fetcher, 1_000, { run: "t" });
    await flush(0);
    await hello();
    const before = fetcher.mock.calls.length;

    setVisibility("hidden");
    document.dispatchEvent(new Event("visibilitychange"));
    await flush(10 * 60_000);
    expect(fetcher.mock.calls.length).toBe(before);

    setVisibility("visible");
    document.dispatchEvent(new Event("visibilitychange"));
    await flush(0);
    await hello();
    const shown = fetcher.mock.calls.length - before;
    expect(shown).toBeGreaterThanOrEqual(1);
    expect(shown).toBeLessThanOrEqual(2);
    await idleWithKeepalives(server.current, 60_000);
    expect(fetcher.mock.calls.length - before).toBe(shown);
  });
});
