import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { ApiRequestError } from "../api/client";
import ErrorNotice from "./ErrorNotice";

function renderNotice(ui: React.ReactElement) {
  return render(<MemoryRouter>{ui}</MemoryRouter>);
}

describe("ErrorNotice code → recovery mapping", () => {
  it("offers Reload latest for stale_content", async () => {
    const onRetry = vi.fn();
    renderNotice(
      <ErrorNotice
        error={new ApiRequestError(409, "stale_content", "changed on disk")}
        onRetry={onRetry}
      />,
    );
    expect(screen.getByRole("alert").textContent).toMatch(/changed since/i);
    await userEvent.click(screen.getByRole("button", { name: /reload latest/i }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("offers a library link for not_found", () => {
    renderNotice(
      <ErrorNotice error={new ApiRequestError(404, "not_found", "no run")} />,
    );
    expect(screen.getByRole("link", { name: /course library/i })).toHaveAttribute(
      "href",
      "/",
    );
  });

  it("explains daemon_unreachable with launcher instructions", () => {
    renderNotice(
      <ErrorNotice
        error={new ApiRequestError(0, "daemon_unreachable", "fetch failed")}
      />,
    );
    expect(screen.getByRole("alert").textContent).toMatch(/education-pipeline ui/);
  });

  it("offers Open Settings for provider_unavailable", () => {
    renderNotice(
      <ErrorNotice
        error={new ApiRequestError(409, "provider_unavailable", "claude missing")}
      />,
    );
    expect(screen.getByRole("link", { name: /settings/i })).toHaveAttribute(
      "href",
      "/settings",
    );
  });

  it("offers Unarchive for archived_course only when a handler is given", () => {
    const onUnarchive = vi.fn();
    const { rerender } = renderNotice(
      <ErrorNotice
        error={new ApiRequestError(409, "archived_course", "archived")}
        onUnarchive={onUnarchive}
      />,
    );
    expect(screen.getByRole("button", { name: /unarchive/i })).toBeInTheDocument();
    rerender(
      <MemoryRouter>
        <ErrorNotice error={new ApiRequestError(409, "archived_course", "archived")} />
      </MemoryRouter>,
    );
    expect(screen.queryByRole("button", { name: /unarchive/i })).toBeNull();
  });

  it("shows the resolved path with a copy button for reveal_unsupported", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText } });
    renderNotice(
      <ErrorNotice
        error={
          new ApiRequestError(409, "reveal_unsupported", "no opener", {
            path: "/ws/runs/topic-1",
          })
        }
      />,
    );
    expect(screen.getByText("/ws/runs/topic-1")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /copy path/i }));
    expect(writeText).toHaveBeenCalledWith("/ws/runs/topic-1");
    vi.unstubAllGlobals();
  });

  it("renders the generic fallback for unknown codes", () => {
    renderNotice(
      <ErrorNotice error={new ApiRequestError(418, "mystery_code", "teapot")} />,
    );
    expect(screen.getByRole("alert").textContent).toMatch(/something went wrong/i);
  });

  it("renders non-Api errors through the generic fallback", () => {
    renderNotice(<ErrorNotice error={new Error("boom")} />);
    expect(screen.getByRole("alert").textContent).toMatch(/something went wrong/i);
  });

  it("hides the raw message behind a details disclosure", async () => {
    renderNotice(
      <ErrorNotice
        error={new ApiRequestError(409, "stale_content", "raw disk message")}
      />,
    );
    expect(screen.queryByText(/raw disk message/)).toBeNull();
    await userEvent.click(screen.getByText(/details/i));
    expect(screen.getByText(/raw disk message/)).toBeInTheDocument();
    expect(screen.getByText(/stale_content/)).toBeInTheDocument();
  });

  it("prefixes the explanation with the caller context", () => {
    renderNotice(
      <ErrorNotice
        prefix="Failed to load topics"
        error={new ApiRequestError(0, "daemon_unreachable", "fetch failed")}
      />,
    );
    expect(screen.getByRole("alert").textContent).toMatch(/Failed to load topics/);
  });

  it("offers a plain Retry for internal errors", async () => {
    const onRetry = vi.fn();
    renderNotice(
      <ErrorNotice
        error={new ApiRequestError(500, "internal", "internal server error")}
        onRetry={onRetry}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });
});
