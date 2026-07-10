import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import type { TopicSummary } from "../api/types";
import TopicListPage from "./TopicListPage";

vi.mock("../api/client", () => ({
  getTopics: vi.fn(),
}));

import { getTopics } from "../api/client";

const summary: TopicSummary = {
  id: "systems-thinking",
  title: "Systems Thinking",
  error: null,
  run: {
    topic_id: "systems-thinking",
    finalized: false,
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
    render(
      <MemoryRouter>
        <TopicListPage />
      </MemoryRouter>,
    );
    expect(await screen.findByText(/No topics yet/)).toBeInTheDocument();
  });
});
