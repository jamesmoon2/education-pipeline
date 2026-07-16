import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiRequestError } from "../api/client";
import { useAction } from "./useAction";

describe("useAction", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("reports success and calls onSuccess", async () => {
    const onSuccess = vi.fn();
    const { result } = renderHook(() => useAction(onSuccess));
    await act(() => result.current.run(() => Promise.resolve("ok"), { successMessage: "Saved." }));
    expect(onSuccess).toHaveBeenCalledTimes(1);
    expect(result.current.feedback).toBe("Saved.");
    expect(result.current.isError).toBe(false);
  });

  it("surfaces the error message on failure", async () => {
    const { result } = renderHook(() => useAction());
    await act(() =>
      result.current.run(() =>
        Promise.reject(new ApiRequestError(409, "job_active", "job x is running for topic 't'")),
      ),
    );
    expect(result.current.isError).toBe(true);
    expect(result.current.feedback).toBe("job x is running for topic 't'");
  });

  it("retries with overwrite when the user confirms a 409 already_exists", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const retry = vi.fn().mockResolvedValue("done");
    const { result } = renderHook(() => useAction());
    await act(() =>
      result.current.run(
        () => Promise.reject(new ApiRequestError(409, "already_exists", "already approved")),
        { retryWithOverwrite: retry, successMessage: "Approved." },
      ),
    );
    expect(retry).toHaveBeenCalledTimes(1);
    expect(result.current.isError).toBe(false);
    expect(result.current.feedback).toBe("Approved.");
  });

  it("does not retry when the confirm is declined", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(false);
    const retry = vi.fn();
    const { result } = renderHook(() => useAction());
    await act(() =>
      result.current.run(
        () => Promise.reject(new ApiRequestError(409, "already_exists", "already approved")),
        { retryWithOverwrite: retry },
      ),
    );
    expect(retry).not.toHaveBeenCalled();
    expect(result.current.isError).toBe(true);
    expect(result.current.feedback).toBe("already approved");
  });

  it("is busy while the action is in flight", async () => {
    let resolve!: (value: string) => void;
    const pending = new Promise<string>((r) => {
      resolve = r;
    });
    const { result } = renderHook(() => useAction());
    let done!: Promise<boolean>;
    act(() => {
      done = result.current.run(() => pending);
    });
    expect(result.current.busy).toBe(true);
    await act(async () => {
      resolve("ok");
      await done;
    });
    expect(result.current.busy).toBe(false);
  });
});
