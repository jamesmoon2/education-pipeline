import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import AppErrorFallback from "./AppErrorFallback";

// Phase 6 decision 1, app level: the last-resort fallback main.tsx renders
// when the rail itself throws. It has no router to lean on, so its only way
// out is a full reload. `onReload` is the test seam; it defaults to
// window.location.reload() in the app.

describe("AppErrorFallback", () => {
  it("is an alert with a heading and the error message inside a <details>", () => {
    render(<AppErrorFallback error={new Error("rail exploded")} />);
    const alert = screen.getByRole("alert");
    expect(within(alert).getByRole("heading")).toBeInTheDocument();
    const details = alert.querySelector("details");
    expect(details).not.toBeNull();
    expect(details).toHaveTextContent("rail exploded");
  });

  it("shows a thrown non-Error value as text", () => {
    render(<AppErrorFallback error="plain failure" />);
    expect(screen.getByRole("alert").querySelector("details")).toHaveTextContent(
      "plain failure",
    );
  });

  it("offers a Reload the cockpit button that calls onReload", async () => {
    const onReload = vi.fn();
    render(<AppErrorFallback error={new Error("rail exploded")} onReload={onReload} />);
    await userEvent.click(screen.getByRole("button", { name: "Reload the cockpit" }));
    expect(onReload).toHaveBeenCalledTimes(1);
  });
});
