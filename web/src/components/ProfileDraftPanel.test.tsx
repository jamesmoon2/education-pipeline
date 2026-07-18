import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ProfileDraftPanel from "./ProfileDraftPanel";

vi.mock("../api/client", () => ({
  getConfigProviders: vi.fn(),
  getConfigCatalog: vi.fn(),
  draftProfile: vi.fn(),
  importProfile: vi.fn(),
}));
import {
  draftProfile,
  getConfigCatalog,
  getConfigProviders,
  importProfile,
} from "../api/client";

const providers = [
  { id: "manual", label: "Manual", description: "", executable: false, available: true, reason: null },
  { id: "claude-code", label: "Claude Code", description: "", executable: true, available: true, reason: null },
  { id: "codex", label: "Codex", description: "", executable: true, available: false, reason: "not on PATH" },
];
const catalog = [
  {
    id: "claude-code",
    label: "Claude Code",
    description: "",
    models: [{ id: "sonnet", label: "Sonnet", description: "", quality: null, default_effort: null }],
  },
];

const draftResult = {
  toml: 'id = "drafted-learner"\ntarget_learner = "Someone"\n',
  profile_id: "drafted-learner",
  provider: "claude-code",
  model: "sonnet",
  effort: null,
};

describe("ProfileDraftPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getConfigProviders).mockResolvedValue({ providers });
    vi.mocked(getConfigCatalog).mockResolvedValue({ providers: catalog, presets: [] });
  });

  it("drafts TOML from a description and imports it after review", async () => {
    vi.mocked(draftProfile).mockResolvedValue(draftResult);
    vi.mocked(importProfile).mockResolvedValue({ id: "drafted-learner" });
    const onCreated = vi.fn();
    render(<ProfileDraftPanel onCreated={onCreated} />);

    await userEvent.type(
      await screen.findByLabelText("Learner description"),
      "A nurse returning to statistics.",
    );
    await userEvent.selectOptions(screen.getByLabelText("Model"), "sonnet");
    await userEvent.click(screen.getByRole("button", { name: "Draft profile TOML" }));

    expect(draftProfile).toHaveBeenCalledWith("A nurse returning to statistics.", {
      provider: "claude-code",
      model: "sonnet",
    });
    const tomlBox = await screen.findByLabelText(/Drafted TOML/);
    expect(tomlBox).toHaveValue(draftResult.toml);

    await userEvent.click(screen.getByRole("button", { name: "Create profile" }));
    expect(importProfile).toHaveBeenCalledWith(draftResult.toml);
    expect(await screen.findByText('Profile "drafted-learner" created.')).toBeInTheDocument();
    expect(onCreated).toHaveBeenCalledWith("drafted-learner");
  });

  it("imports the edited TOML, not the original draft", async () => {
    vi.mocked(draftProfile).mockResolvedValue(draftResult);
    vi.mocked(importProfile).mockResolvedValue({ id: "renamed" });
    render(<ProfileDraftPanel />);

    await userEvent.type(await screen.findByLabelText("Learner description"), "desc");
    await userEvent.click(screen.getByRole("button", { name: "Draft profile TOML" }));
    const tomlBox = await screen.findByLabelText(/Drafted TOML/);
    await userEvent.clear(tomlBox);
    await userEvent.type(tomlBox, 'id = "renamed"');
    await userEvent.click(screen.getByRole("button", { name: "Create profile" }));
    expect(importProfile).toHaveBeenCalledWith('id = "renamed"');
  });

  it("surfaces drafting errors from the provider", async () => {
    vi.mocked(draftProfile).mockRejectedValue(new Error("provider 'claude-code' is not available on PATH"));
    render(<ProfileDraftPanel />);

    await userEvent.type(await screen.findByLabelText("Learner description"), "desc");
    await userEvent.click(screen.getByRole("button", { name: "Draft profile TOML" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/not available on PATH/);
  });

  it("disables drafting when no executable provider is available", async () => {
    vi.mocked(getConfigProviders).mockResolvedValue({
      providers: providers.map((item) => ({ ...item, available: item.id === "manual" })),
    });
    render(<ProfileDraftPanel />);

    expect(await screen.findByText(/No provider CLI is available/)).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Learner description"), "desc");
    expect(screen.getByRole("button", { name: "Draft profile TOML" })).toBeDisabled();
  });
});
