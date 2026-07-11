import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import StageViewerPage from "./StageViewerPage";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ApiRequestError: actual.ApiRequestError, getStageContent: vi.fn(), postApprove: vi.fn(), postResponse: vi.fn() };
});

import { getStageContent, postApprove, postResponse } from "../api/client";

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/topics/:topicId/stages/:stage" element={<StageViewerPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("StageViewerPage", () => {
  it("shows the prompt by default and switches tabs", async () => {
    vi.mocked(getStageContent).mockResolvedValue({
      topic_id: "t",
      stage: "draft",
      prompt: "# the prompt",
      response: "# the response",
      approved: null,
    });
    renderAt("/topics/t/stages/draft");
    expect(await screen.findByText("# the prompt")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: /^response/ }));
    expect(screen.getByText("# the response")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: /^approved/ }));
    expect(screen.getByText("(no approved yet)")).toBeInTheDocument();
  });

  it("offers Paste response when no response exists", async () => {
    vi.mocked(getStageContent).mockResolvedValue({
      topic_id: "t",
      stage: "draft",
      prompt: "# prompt",
      response: null,
      approved: null,
    });
    vi.mocked(postResponse).mockResolvedValue({} as never);
    renderAt("/topics/t/stages/draft");
    await userEvent.click(await screen.findByRole("button", { name: "Paste response…" }));
    await userEvent.type(screen.getByLabelText("Response for draft"), "pasted body");
    await userEvent.click(screen.getByRole("button", { name: "Save response" }));
    expect(postResponse).toHaveBeenCalledWith("t", "draft", "pasted body");
    expect(screen.queryByRole("button", { name: /Approve/ })).not.toBeInTheDocument();
  });

  it("offers Approve when a response exists and is not approved", async () => {
    vi.mocked(getStageContent).mockResolvedValue({
      topic_id: "t",
      stage: "draft",
      prompt: "# prompt",
      response: "response body",
      approved: null,
    });
    vi.mocked(postApprove).mockResolvedValue({} as never);
    renderAt("/topics/t/stages/draft");
    await userEvent.click(await screen.findByRole("button", { name: "Approve draft" }));
    expect(postApprove).toHaveBeenCalledWith("t", "draft");
    expect(screen.queryByRole("button", { name: "Paste response…" })).not.toBeInTheDocument();
  });

  it("offers neither action once approved", async () => {
    vi.mocked(getStageContent).mockResolvedValue({
      topic_id: "t",
      stage: "draft",
      prompt: "# prompt",
      response: "response body",
      approved: "response body",
    });
    renderAt("/topics/t/stages/draft");
    expect(await screen.findByRole("tab", { name: /prompt/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Approve/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Paste response…" })).not.toBeInTheDocument();
  });
});
