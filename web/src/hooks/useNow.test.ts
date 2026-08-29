import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useNow } from "./useNow";

describe("useNow", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-07-10T00:00:00.000Z"));
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("returns the current time on first render", () => {
    const { result } = renderHook(() => useNow());
    expect(result.current).toBe(Date.parse("2026-07-10T00:00:00.000Z"));
  });

  it("refreshes on the default 1s interval", () => {
    const { result } = renderHook(() => useNow());
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(result.current).toBe(Date.parse("2026-07-10T00:00:01.000Z"));
    act(() => {
      vi.advanceTimersByTime(2000);
    });
    expect(result.current).toBe(Date.parse("2026-07-10T00:00:03.000Z"));
  });

  it("honors a custom interval", () => {
    const { result } = renderHook(() => useNow(5_000));
    act(() => {
      vi.advanceTimersByTime(4_000);
    });
    expect(result.current).toBe(Date.parse("2026-07-10T00:00:00.000Z"));
    act(() => {
      vi.advanceTimersByTime(1_000);
    });
    expect(result.current).toBe(Date.parse("2026-07-10T00:00:05.000Z"));
  });

  it("stops ticking after unmount", () => {
    const clearSpy = vi.spyOn(window, "clearInterval");
    const { unmount } = renderHook(() => useNow());
    unmount();
    expect(clearSpy).toHaveBeenCalled();
  });
});
