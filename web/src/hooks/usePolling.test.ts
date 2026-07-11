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

describe("usePolling visibility", () => {
  const setVisibility = (state: DocumentVisibilityState) =>
    Object.defineProperty(document, "visibilityState", {
      value: state,
      configurable: true,
    });

  afterEach(() => {
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
});
