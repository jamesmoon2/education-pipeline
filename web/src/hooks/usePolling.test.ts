import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { usePolling } from "./usePolling";

describe("usePolling", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("fetches immediately and then on the interval", async () => {
    vi.useFakeTimers();
    let n = 0;
    const fetcher = vi.fn(async () => ++n);
    const { result, unmount } = renderHook(() => usePolling(fetcher, 1000));

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(result.current.data).toBe(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(result.current.data).toBe(2);
    unmount();
  });

  it("keeps the last data and reports the error on failure", async () => {
    vi.useFakeTimers();
    let calls = 0;
    const fetcher = vi.fn(async () => {
      calls += 1;
      if (calls === 2) throw new Error("boom");
      return calls;
    });
    const { result, unmount } = renderHook(() => usePolling(fetcher, 1000));

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(result.current.data).toBe(1);
    expect(result.current.error).toBeNull();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(result.current.data).toBe(1); // retained
    expect(result.current.error?.message).toBe("boom");

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(result.current.data).toBe(3);
    expect(result.current.error).toBeNull();
    unmount();
  });

  it("stops polling after unmount", async () => {
    vi.useFakeTimers();
    const fetcher = vi.fn(async () => 1);
    const { unmount } = renderHook(() => usePolling(fetcher, 1000));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    unmount();
    const callsAtUnmount = fetcher.mock.calls.length;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(fetcher.mock.calls.length).toBe(callsAtUnmount);
  });
});

describe("usePolling change gating", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  // Every tick parses a brand-new object graph (response.json()), so without a
  // value-level gate `data` changes identity every interval and every consumer
  // subtree re-renders on a payload nothing has touched.
  const freshPayload = () => ({ jobs: [{ id: "j1", status: "running" }] });

  it("keeps the same data reference — and skips the render — when a tick repeats the payload", async () => {
    vi.useFakeTimers();
    const fetcher = vi.fn(async () => freshPayload());
    let renders = 0;
    const { result, unmount } = renderHook(() => {
      renders += 1;
      return usePolling(fetcher, 1000);
    });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    const first = result.current.data;
    expect(first).toEqual(freshPayload());
    const rendersAfterFirstPayload = renders;

    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });
    expect(fetcher.mock.calls.length).toBeGreaterThan(1);
    expect(result.current.data).toBe(first);
    expect(renders).toBe(rendersAfterFirstPayload);
    unmount();
  });

  it("publishes a new reference on the tick a payload actually changes", async () => {
    vi.useFakeTimers();
    let status = "running";
    const fetcher = vi.fn(async () => ({ jobs: [{ id: "j1", status }] }));
    const { result, unmount } = renderHook(() => usePolling(fetcher, 1000));

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    const first = result.current.data;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(result.current.data).toBe(first);

    status = "succeeded";
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(result.current.data).not.toBe(first);
    expect(result.current.data).toEqual({ jobs: [{ id: "j1", status: "succeeded" }] });
    unmount();
  });

  it("republishes after refresh() even when the payload is unchanged", async () => {
    vi.useFakeTimers();
    const fetcher = vi.fn(async () => freshPayload());
    const { result, unmount } = renderHook(() => usePolling(fetcher, 1000));

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    const first = result.current.data;

    await act(async () => {
      result.current.refresh();
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(result.current.data).not.toBe(first);
    expect(result.current.data).toEqual(freshPayload());
    unmount();
  });

  it("gates on value even when the payload is not serializable", async () => {
    vi.useFakeTimers();
    const circular: Record<string, unknown> = {};
    circular.self = circular;
    const fetcher = vi.fn(async () => circular);
    const { result, unmount } = renderHook(() => usePolling(fetcher, 1000));

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(result.current.data).toBe(circular);
    expect(result.current.error).toBeNull();
    unmount();
  });
});

describe("usePolling visibility", () => {
  const setVisibility = (state: DocumentVisibilityState) =>
    Object.defineProperty(document, "visibilityState", {
      value: state,
      configurable: true,
    });

  afterEach(() => {
    vi.useRealTimers();
    setVisibility("visible");
  });

  it("skips ticks while hidden and resumes on visibilitychange", async () => {
    const fetcher = vi.fn().mockResolvedValue("x");
    setVisibility("hidden");
    renderHook(() => usePolling(fetcher, 60_000));
    await new Promise((r) => setTimeout(r, 20));
    expect(fetcher).not.toHaveBeenCalled();

    setVisibility("visible");
    document.dispatchEvent(new Event("visibilitychange"));
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
  });

  it("does not fork a second poll chain when the tab returns mid-fetch", async () => {
    vi.useFakeTimers();
    const pending: Array<(value: number) => void> = [];
    let served = 0;
    const fetcher = vi.fn(() => new Promise<number>((resolve) => pending.push(resolve)));
    const settle = async () => {
      for (const resolve of pending.splice(0)) resolve((served += 1));
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
    };

    const { unmount } = renderHook(() => usePolling(fetcher, 1000));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(fetcher).toHaveBeenCalledTimes(1);
    await settle(); // the first tick lands and schedules the next timeout

    // That timeout fires; its fetch is still in flight, so the timeout id the
    // effect holds is the id of a timeout that has ALREADY fired.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(fetcher).toHaveBeenCalledTimes(2);

    // Returning to the tab now must not clear-and-restart: clearing a spent id
    // is a no-op, so restarting would leave two chains polling forever.
    setVisibility("hidden");
    setVisibility("visible");
    await act(async () => {
      document.dispatchEvent(new Event("visibilitychange"));
    });
    expect(fetcher).toHaveBeenCalledTimes(2);

    // One chain, one fetch per interval, from here on.
    await settle();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(fetcher).toHaveBeenCalledTimes(3);
    await settle();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(fetcher).toHaveBeenCalledTimes(4);
    unmount();
  });

  it("still resumes promptly when the tab returns with no fetch in flight", async () => {
    vi.useFakeTimers();
    const fetcher = vi.fn(async () => ({ tick: fetcher.mock.calls.length }));
    const { unmount } = renderHook(() => usePolling(fetcher, 60_000));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(fetcher).toHaveBeenCalledTimes(1);

    setVisibility("hidden");
    setVisibility("visible");
    await act(async () => {
      document.dispatchEvent(new Event("visibilitychange"));
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(fetcher).toHaveBeenCalledTimes(2);

    // The restart replaced the pending timeout rather than adding to it.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });
    expect(fetcher).toHaveBeenCalledTimes(3);
    unmount();
  });
});
