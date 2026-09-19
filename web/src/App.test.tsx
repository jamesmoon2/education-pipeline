import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";

vi.mock("./api/client", async () => {
  const actual = await vi.importActual<typeof import("./api/client")>("./api/client");
  return {
    ApiRequestError: actual.ApiRequestError,
    api: vi.fn().mockResolvedValue({ status: "ok", cockpit_build: null }),
    getJobs: vi.fn().mockResolvedValue({ jobs: [] }),
    getTopics: vi.fn().mockResolvedValue({ topics: [] }),
    getProfiles: vi.fn().mockResolvedValue({ profiles: [] }),
    getWorkspace: vi
      .fn()
      .mockResolvedValue({ path: "/ws", counts: { topics: 0, runs: 0, profiles: 0 }, first_run: false }),
    getConfigProviders: vi.fn().mockResolvedValue({ providers: [] }),
  };
});

beforeEach(() => {
  localStorage.clear();
});

describe("App shell", () => {
  it("renders the dock: brand, primary navigation, activity, theme and tour controls", async () => {
    render(
      <MemoryRouter>
        <App />
      </MemoryRouter>,
    );
    expect(screen.getByRole("link", { name: "Education Pipeline" })).toHaveAttribute("href", "/");
    const nav = screen.getByRole("navigation", { name: "Primary" });
    for (const name of ["Courses", "New course", "Profiles", "Settings"]) {
      expect(screen.getByRole("link", { name })).toBeInTheDocument();
    }
    expect(nav).toHaveAttribute("data-tour", "nav");
    expect(screen.getByRole("region", { name: "Workspace activity" })).toHaveAttribute(
      "data-tour",
      "activity",
    );
    expect(screen.getByRole("radiogroup", { name: "Theme" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Take the tour" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Skip to content" })).toHaveAttribute(
      "href",
      "#workspace",
    );
    expect(screen.getByRole("main")).toHaveAttribute("id", "workspace");
  });

  it("launches the guided tour from the dock", async () => {
    render(
      <MemoryRouter>
        <App />
      </MemoryRouter>,
    );
    await userEvent.click(screen.getByRole("button", { name: "Take the tour" }));
    expect(
      await screen.findByRole("dialog", { name: "Your course workbench" }),
    ).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Skip tour" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("marks the current route in the dock", () => {
    render(
      <MemoryRouter initialEntries={["/settings"]}>
        <App />
      </MemoryRouter>,
    );
    expect(screen.getByRole("link", { name: "Settings" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Courses" })).not.toHaveAttribute("aria-current");
  });
});
