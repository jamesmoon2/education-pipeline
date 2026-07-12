import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import type { TopicSummary } from "../api/types";
import TopicListPage from "./TopicListPage";

vi.mock("../api/client", () => ({
  getTopics: vi.fn(),
  getProfiles: vi.fn(),
  importTopic: vi.fn(),
  importProfile: vi.fn(),
  attachProfile: vi.fn(),
}));

import {
  attachProfile,
  getProfiles,
  getTopics,
  importProfile,
  importTopic,
} from "../api/client";

const summary: TopicSummary = {
  id: "systems-thinking",
  title: "Systems Thinking",
  error: null,
  run: {
    topic_id: "systems-thinking",
    finalized: false,
    content_contract: { kind: "legacy_markdown" },
    stage_provenance: [],
    validations: {
      draft: { state: "missing", blocking: 0, errors: 0, warnings: 0 },
      final: { state: "missing", blocking: 0, errors: 0, warnings: 0 },
    },
    stages: [],
    next_action: {
      topic_id: "systems-thinking",
      stage: "spec",
      action: "write_prompt",
      detail: "Write the spec prompt.",
    },
  },
};

describe("TopicListPage", () => {
  it("renders topics with title, next action, and a run-board link", async () => {
    vi.mocked(getTopics).mockResolvedValue({ topics: [summary] });
    vi.mocked(getProfiles).mockResolvedValue({ profiles: [] });
    render(
      <MemoryRouter>
        <TopicListPage />
      </MemoryRouter>,
    );
    const link = await screen.findByRole("link", { name: "systems-thinking" });
    expect(link).toHaveAttribute("href", "/topics/systems-thinking");
    expect(screen.getByText("Systems Thinking")).toBeInTheDocument();
    expect(screen.getByText("write_prompt")).toBeInTheDocument();
  });

  it("shows the empty state", async () => {
    vi.mocked(getTopics).mockResolvedValue({ topics: [] });
    vi.mocked(getProfiles).mockResolvedValue({ profiles: [] });
    render(
      <MemoryRouter>
        <TopicListPage />
      </MemoryRouter>,
    );
    expect(await screen.findByText(/No topics yet/)).toBeInTheDocument();
    const link = screen.getByRole("link", { name: "Create your first course →" });
    expect(link).toHaveAttribute("href", "/new");
  });

  it("imports a topic from pasted TOML", async () => {
    vi.mocked(getTopics).mockResolvedValue({ topics: [] });
    vi.mocked(getProfiles).mockResolvedValue({ profiles: [] });
    vi.mocked(importTopic).mockResolvedValue({ id: "n1", title: "New One" });
    render(
      <MemoryRouter>
        <TopicListPage />
      </MemoryRouter>,
    );
    await userEvent.click(await screen.findByRole("button", { name: "Import topic…" }));
    await userEvent.type(
      screen.getByLabelText("topic TOML"),
      'id = "n1"',
    );
    await userEvent.click(screen.getByRole("button", { name: "Import" }));
    expect(importTopic).toHaveBeenCalledWith('id = "n1"');
  });

  it("imports a profile from pasted TOML", async () => {
    // Uses a non-empty topic list: the profile-import toolbar affordance
    // lives on the non-empty branch (the empty state only offers topic
    // import, demoted below the "/new" wizard link).
    vi.mocked(getTopics).mockResolvedValue({ topics: [summary] });
    vi.mocked(getProfiles).mockResolvedValue({ profiles: [] });
    vi.mocked(importProfile).mockResolvedValue({ id: "p1" });
    render(
      <MemoryRouter>
        <TopicListPage />
      </MemoryRouter>,
    );
    await userEvent.click(await screen.findByRole("button", { name: "Import profile…" }));
    await userEvent.type(screen.getByLabelText("profile TOML"), 'id = "p1"');
    await userEvent.click(screen.getByRole("button", { name: "Import" }));
    expect(importProfile).toHaveBeenCalledWith('id = "p1"');
  });

  it("attaches a profile to a topic", async () => {
    vi.mocked(getTopics).mockResolvedValue({
      topics: [{ id: "t", title: "Topic", error: null, run: null }],
    });
    vi.mocked(getProfiles).mockResolvedValue({ profiles: ["p1", "p2"] });
    vi.mocked(attachProfile).mockResolvedValue({
      profile_id: "p1",
      topic_id: "t",
      snapshot_path: "inputs/profile.toml",
    });
    render(
      <MemoryRouter>
        <TopicListPage />
      </MemoryRouter>,
    );
    await userEvent.selectOptions(await screen.findByLabelText("Attach profile to t"), "p1");
    await userEvent.click(screen.getByRole("button", { name: "Attach" }));
    expect(attachProfile).toHaveBeenCalledWith("t", "p1");
  });
});
