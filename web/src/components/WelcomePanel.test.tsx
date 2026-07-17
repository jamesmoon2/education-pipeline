import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import WelcomePanel, {
  WELCOME_DISMISSED_KEY,
  resetWelcomeDismissal,
} from "./WelcomePanel";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return {
    ApiRequestError: actual.ApiRequestError,
    getWorkspace: vi.fn(),
    getConfigProviders: vi.fn(),
  };
});

import { getConfigProviders, getWorkspace } from "../api/client";

function renderPanel() {
  return render(
    <MemoryRouter>
      <WelcomePanel />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  vi.mocked(getWorkspace).mockResolvedValue({
    path: "/home/learner/EducationPipeline",
    counts: { topics: 0, runs: 0, profiles: 0 },
    first_run: true,
  });
  vi.mocked(getConfigProviders).mockResolvedValue({
    providers: [
      {
        id: "claude-code",
        label: "Claude Code",
        description: "",
        executable: true,
        available: false,
        reason: "claude-code CLI not found on PATH",
      },
    ],
  });
});

describe("WelcomePanel", () => {
  it("shows the three first-run facts and the primary CTA on first run", async () => {
    renderPanel();
    const panel = await screen.findByRole("region", { name: /welcome/i });
    expect(panel.textContent).toMatch(/stored locally/i);
    expect(panel.textContent).toMatch(/copy\/paste/i);
    expect(panel.textContent).toMatch(/review/i);
    const cta = screen.getByRole("link", { name: /create your first course/i });
    expect(cta).toHaveAttribute("href", "/new");
  });

  it("shows detected provider availability with manual mode first-class", async () => {
    renderPanel();
    const panel = await screen.findByRole("region", { name: /welcome/i });
    expect(panel.textContent).toMatch(/Claude Code/);
    expect(panel.textContent).toMatch(/not found on PATH/);
    expect(panel.textContent).toMatch(/Manual copy\/paste — always available/i);
  });

  it("renders nothing when the workspace is not first-run", async () => {
    vi.mocked(getWorkspace).mockResolvedValue({
      path: "/ws",
      counts: { topics: 3, runs: 2, profiles: 1 },
      first_run: false,
    });
    renderPanel();
    await vi.waitFor(() => expect(getWorkspace).toHaveBeenCalled());
    expect(screen.queryByRole("region", { name: /welcome/i })).toBeNull();
  });

  it("dismisses persistently via localStorage", async () => {
    renderPanel();
    await screen.findByRole("region", { name: /welcome/i });
    await userEvent.click(screen.getByRole("button", { name: /dismiss/i }));
    expect(screen.queryByRole("region", { name: /welcome/i })).toBeNull();
    expect(localStorage.getItem(WELCOME_DISMISSED_KEY)).toBe("1");
  });

  it("stays hidden when previously dismissed", async () => {
    localStorage.setItem(WELCOME_DISMISSED_KEY, "1");
    renderPanel();
    await vi.waitFor(() => expect(getWorkspace).toHaveBeenCalled());
    expect(screen.queryByRole("region", { name: /welcome/i })).toBeNull();
  });

  it("reappears after resetWelcomeDismissal (the Settings 'Show welcome' hook)", async () => {
    localStorage.setItem(WELCOME_DISMISSED_KEY, "1");
    resetWelcomeDismissal();
    renderPanel();
    expect(await screen.findByRole("region", { name: /welcome/i })).toBeInTheDocument();
  });

  it("renders nothing while the workspace is unknown or unavailable", async () => {
    vi.mocked(getWorkspace).mockRejectedValue(new Error("offline"));
    renderPanel();
    await vi.waitFor(() => expect(getWorkspace).toHaveBeenCalled());
    expect(screen.queryByRole("region", { name: /welcome/i })).toBeNull();
  });
});
