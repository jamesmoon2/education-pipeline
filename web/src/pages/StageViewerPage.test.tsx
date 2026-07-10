import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import StageViewerPage from "./StageViewerPage";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ApiRequestError: actual.ApiRequestError, getStageContent: vi.fn() };
});

import { getStageContent } from "../api/client";

describe("StageViewerPage", () => {
  it("shows the prompt by default and switches tabs", async () => {
    vi.mocked(getStageContent).mockResolvedValue({
      topic_id: "t",
      stage: "draft",
      prompt: "# the prompt",
      response: "# the response",
      approved: null,
    });
    render(
      <MemoryRouter initialEntries={["/topics/t/stages/draft"]}>
        <Routes>
          <Route path="/topics/:topicId/stages/:stage" element={<StageViewerPage />} />
        </Routes>
      </MemoryRouter>,
    );
    expect(await screen.findByText("# the prompt")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /^response/ }));
    expect(screen.getByText("# the response")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /^approved/ }));
    expect(screen.getByText("(no approved yet)")).toBeInTheDocument();
  });
});
