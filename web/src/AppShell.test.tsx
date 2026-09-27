import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// Phase 6 decisions 1 and 2 at the shell level: the route-level error
// boundary around <Routes> keeps the rail usable, and the theme select sits
// in the rail footer. Pages are stubbed so the test is about the shell only;
// the run board stub throws on demand.

const pages = vi.hoisted(() => ({ runBoardThrows: true }));

vi.mock("./pages/RunBoardPage", () => ({
  default: function RunBoardPageStub() {
    if (pages.runBoardThrows) throw new Error("Run board exploded");
    return <p>Run board stub</p>;
  },
}));
vi.mock("./pages/TopicListPage", () => ({
  default: () => <p>Library stub</p>,
}));
vi.mock("./pages/NewRunPage", () => ({
  default: () => <p>New course stub</p>,
}));
vi.mock("./pages/StageViewerPage", () => ({
  default: () => <p>Stage viewer stub</p>,
}));
vi.mock("./pages/SettingsPage", () => ({
  default: () => <p>Settings stub</p>,
}));
vi.mock("./pages/ProfilesPage", () => ({
  default: () => <p>Profiles stub</p>,
}));
vi.mock("./pages/ProfileEditorPage", () => ({
  default: () => <p>Profile editor stub</p>,
}));

vi.mock("./api/client", async () => {
  const actual = await vi.importActual<typeof import("./api/client")>("./api/client");
  return {
    ApiRequestError: actual.ApiRequestError,
    api: vi.fn(),
    getJobs: vi.fn(),
    getTopics: vi.fn(),
    // T62b: App now owns an EventsProvider; its stream never answers here,
    // so the shell polls exactly as it did before.
    openEventStream: vi.fn(() => new Promise(() => {})),
  };
});

import { api, getJobs, getTopics } from "./api/client";
import App from "./App";

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  pages.runBoardThrows = true;
  vi.clearAllMocks();
  vi.mocked(api).mockResolvedValue({ version: "test", ok: true });
  vi.mocked(getJobs).mockResolvedValue({ jobs: [] });
  vi.mocked(getTopics).mockResolvedValue({ topics: [] });
  // React logs every caught render error; keep the output readable.
  vi.spyOn(console, "error").mockImplementation(() => {});
  localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
});

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
});

describe("App route-level error boundary", () => {
  it("replaces only the route with an alert: heading, message in <details>, Try again, Back to the library", () => {
    renderAt("/topics/t");
    const main = screen.getByRole("main");
    const alert = within(main).getByRole("alert");
    expect(within(alert).getByRole("heading")).toBeInTheDocument();
    const details = alert.querySelector("details");
    expect(details).not.toBeNull();
    expect(details).toHaveTextContent("Run board exploded");
    expect(within(alert).getByRole("button", { name: "Try again" })).toBeInTheDocument();
    expect(within(alert).getByRole("link", { name: "Back to the library" })).toHaveAttribute(
      "href",
      "/",
    );
  });

  it("keeps the rail (brand, primary nav, rail footer) rendered outside the boundary", () => {
    renderAt("/topics/t");
    const rail = screen.getByRole("banner");
    expect(within(rail).queryByRole("alert")).not.toBeInTheDocument();
    expect(within(rail).getByRole("link", { name: "Education Pipeline" })).toBeInTheDocument();
    const nav = within(rail).getByRole("navigation", { name: "Primary" });
    for (const name of ["Courses", "New course", "Profiles", "Settings"]) {
      expect(within(nav).getByRole("link", { name })).toBeInTheDocument();
    }
    expect(within(rail).getByText("Stored on this device")).toBeInTheDocument();
  });

  it("Try again clears the boundary and re-renders the route", async () => {
    renderAt("/topics/t");
    expect(screen.getByRole("alert")).toBeInTheDocument();
    pages.runBoardThrows = false;
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(screen.getByText("Run board stub")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("Back to the library navigates to the library and clears the error", async () => {
    renderAt("/topics/t");
    await userEvent.click(screen.getByRole("link", { name: "Back to the library" }));
    expect(screen.getByText("Library stub")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("navigating with the rail nav clears the error (resetKey is the pathname)", async () => {
    renderAt("/topics/t");
    expect(screen.getByRole("alert")).toBeInTheDocument();
    const nav = screen.getByRole("navigation", { name: "Primary" });
    await userEvent.click(within(nav).getByRole("link", { name: "Profiles" }));
    expect(screen.getByText("Profiles stub")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});

describe("App theme select", () => {
  it("sits in the rail footer, outside main", () => {
    renderAt("/");
    const rail = screen.getByRole("banner");
    const select = within(rail).getByRole("combobox", { name: "Theme" });
    expect(select.closest(".rail-footer")).not.toBeNull();
    expect(within(screen.getByRole("main")).queryByRole("combobox", { name: "Theme" })).toBeNull();
  });

  it("stays usable while a route is showing the error fallback", async () => {
    renderAt("/topics/t");
    expect(screen.getByRole("alert")).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Theme" }), "Dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
  });
});
