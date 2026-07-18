import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ApiRequestError: actual.ApiRequestError, api: vi.fn() };
});

import { api } from "../api/client";
import BuildFreshnessBanner from "./BuildFreshnessBanner";

function healthWith(status: string, buildId: string | null = "b1") {
  return {
    version: "test",
    ok: true,
    cockpit_build: { status, build_id: buildId },
  };
}

describe("BuildFreshnessBanner", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
  });

  it("shows when the build is stale", async () => {
    vi.mocked(api).mockResolvedValue(healthWith("stale"));
    render(<BuildFreshnessBanner />);
    expect(await screen.findByRole("status")).toHaveTextContent(/older than its source/i);
  });

  it("stays hidden when the build is ok", async () => {
    vi.mocked(api).mockResolvedValue(healthWith("ok"));
    render(<BuildFreshnessBanner />);
    await waitFor(() => expect(api).toHaveBeenCalled());
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("dismisses and stays dismissed for the same build", async () => {
    vi.mocked(api).mockResolvedValue(healthWith("stale", "b1"));
    render(<BuildFreshnessBanner />);
    await userEvent.click(await screen.findByRole("button", { name: /dismiss/i }));
    expect(screen.queryByRole("status")).toBeNull();
    expect(localStorage.getItem("ep-cockpit-build-dismissed")).toBe("b1");
  });

  it("re-appears for a different (newer) stale build", async () => {
    localStorage.setItem("ep-cockpit-build-dismissed", "b1");
    vi.mocked(api).mockResolvedValue(healthWith("stale", "b2"));
    render(<BuildFreshnessBanner />);
    expect(await screen.findByRole("status")).toBeInTheDocument();
  });

  it("never blocks the app when health fails", async () => {
    vi.mocked(api).mockRejectedValue(new Error("down"));
    render(<BuildFreshnessBanner />);
    await waitFor(() => expect(api).toHaveBeenCalled());
    expect(screen.queryByRole("status")).toBeNull();
  });
});
