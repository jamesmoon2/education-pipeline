import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ErrorBoundary from "./ErrorBoundary";

// Phase 6 decision 1: one class component, `resetKey` + `fallback(error, reset)`.
// The route-level and app-level placements are covered in AppShell.test.tsx,
// main.test.tsx and AppErrorFallback.test.tsx.

let shouldThrow = true;

function Bomb() {
  if (shouldThrow) throw new Error("kaboom");
  return <p>safe child</p>;
}

function fallback(error: unknown, reset: () => void) {
  return (
    <div>
      <p>fallback: {error instanceof Error ? error.message : String(error)}</p>
      <button type="button" onClick={reset}>
        reset
      </button>
    </div>
  );
}

beforeEach(() => {
  shouldThrow = true;
  // React logs every caught render error; keep the output readable.
  vi.spyOn(console, "error").mockImplementation(() => {});
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("ErrorBoundary", () => {
  it("renders its children and never calls fallback when nothing throws", () => {
    const spy = vi.fn(fallback);
    render(
      <ErrorBoundary fallback={spy}>
        <p>plain child</p>
      </ErrorBoundary>,
    );
    expect(screen.getByText("plain child")).toBeInTheDocument();
    expect(spy).not.toHaveBeenCalled();
  });

  it("renders the fallback with the thrown error and a reset function", () => {
    const spy = vi.fn(fallback);
    render(
      <ErrorBoundary resetKey="a" fallback={spy}>
        <Bomb />
      </ErrorBoundary>,
    );
    expect(screen.getByText("fallback: kaboom")).toBeInTheDocument();
    expect(screen.queryByText("safe child")).not.toBeInTheDocument();
    const [error, reset] = spy.mock.calls[spy.mock.calls.length - 1];
    expect(error).toBeInstanceOf(Error);
    expect((error as Error).message).toBe("kaboom");
    expect(typeof reset).toBe("function");
  });

  it("keeps a throw inside the boundary: siblings outside it still render", () => {
    render(
      <div>
        <p>outside the boundary</p>
        <ErrorBoundary resetKey="a" fallback={fallback}>
          <Bomb />
        </ErrorBoundary>
      </div>,
    );
    expect(screen.getByText("outside the boundary")).toBeInTheDocument();
    expect(screen.getByText("fallback: kaboom")).toBeInTheDocument();
  });

  it("reset clears the error and re-renders the children", async () => {
    render(
      <ErrorBoundary resetKey="a" fallback={fallback}>
        <Bomb />
      </ErrorBoundary>,
    );
    expect(screen.getByText("fallback: kaboom")).toBeInTheDocument();
    shouldThrow = false;
    await userEvent.click(screen.getByRole("button", { name: "reset" }));
    expect(screen.getByText("safe child")).toBeInTheDocument();
    expect(screen.queryByText(/fallback:/)).not.toBeInTheDocument();
  });

  it("reset shows the fallback again when the children still throw", async () => {
    render(
      <ErrorBoundary resetKey="a" fallback={fallback}>
        <Bomb />
      </ErrorBoundary>,
    );
    await userEvent.click(screen.getByRole("button", { name: "reset" }));
    expect(screen.getByText("fallback: kaboom")).toBeInTheDocument();
    expect(screen.queryByText("safe child")).not.toBeInTheDocument();
  });

  it("a changed resetKey clears the error", () => {
    const { rerender } = render(
      <ErrorBoundary resetKey="/topics/a" fallback={fallback}>
        <Bomb />
      </ErrorBoundary>,
    );
    expect(screen.getByText("fallback: kaboom")).toBeInTheDocument();
    shouldThrow = false;
    rerender(
      <ErrorBoundary resetKey="/profiles" fallback={fallback}>
        <Bomb />
      </ErrorBoundary>,
    );
    expect(screen.getByText("safe child")).toBeInTheDocument();
    expect(screen.queryByText(/fallback:/)).not.toBeInTheDocument();
  });

  it("an unchanged resetKey keeps the fallback across parent re-renders", () => {
    const { rerender } = render(
      <ErrorBoundary resetKey="/topics/a" fallback={fallback}>
        <Bomb />
      </ErrorBoundary>,
    );
    shouldThrow = false;
    rerender(
      <ErrorBoundary resetKey="/topics/a" fallback={fallback}>
        <Bomb />
      </ErrorBoundary>,
    );
    expect(screen.getByText("fallback: kaboom")).toBeInTheDocument();
    expect(screen.queryByText("safe child")).not.toBeInTheDocument();
  });
});
