import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import StageViewerPage from "./StageViewerPage";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return {
    ApiRequestError: actual.ApiRequestError,
    getStageContent: vi.fn(),
    getRunStatus: vi.fn(),
    postApprove: vi.fn(),
    postResponse: vi.fn(),
    putResponse: vi.fn(),
    postPreview: vi.fn(),
  };
});

import {
  getRunStatus,
  getStageContent,
  postApprove,
  postResponse,
  putResponse,
} from "../api/client";

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/topics/:topicId/stages/:stage" element={<StageViewerPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

function mockRun(finalized = false) {
  vi.mocked(getRunStatus).mockResolvedValue({
    topic_id: "t",
    finalized,
    stages: [],
    next_action: { topic_id: "t", stage: null, action: "done", detail: "" },
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  mockRun();
});

describe("StageViewerPage", () => {
  it("shows the prompt by default and switches tabs", async () => {
    vi.mocked(getStageContent).mockResolvedValue({
      topic_id: "t",
      stage: "draft",
      prompt: "# the prompt",
      response: "# the response",
      approved: null,
      response_sha256: null,
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
      response_sha256: null,
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
      response_sha256: "hash-1",
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
      response_sha256: "hash-1",
    });
    renderAt("/topics/t/stages/draft");
    expect(await screen.findByRole("tab", { name: /prompt/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Approve/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Paste response…" })).not.toBeInTheDocument();
  });

  it("offers Edit on the response tab and opens the editor", async () => {
    vi.mocked(getStageContent).mockResolvedValue({
      topic_id: "t",
      stage: "draft",
      prompt: "# prompt",
      response: "response body",
      approved: null,
      response_sha256: "sha-1",
    });
    vi.mocked(putResponse).mockResolvedValue({
      topic_id: "t",
      stage: "draft",
      response_path: "responses/draft.response.md",
      response_sha256: "sha-2",
    });
    renderAt("/topics/t/stages/draft");
    await userEvent.click(await screen.findByRole("tab", { name: /^response/ }));
    await userEvent.click(await screen.findByRole("button", { name: "Edit" }));

    const textarea = screen.getByLabelText("Edit response for draft");
    expect(textarea).toHaveValue("response body");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(putResponse).toHaveBeenCalledWith("t", "draft", "response body", "sha-1");
    // returns to the read view after a successful save
    expect(
      await screen.findByRole("button", { name: "Edit" }),
    ).toBeInTheDocument();
  });

  it("hides Edit when the run is finalized", async () => {
    mockRun(true);
    vi.mocked(getStageContent).mockResolvedValue({
      topic_id: "t",
      stage: "draft",
      prompt: "# prompt",
      response: "response body",
      approved: "response body",
      response_sha256: "sha-1",
    });
    renderAt("/topics/t/stages/draft");
    await userEvent.click(await screen.findByRole("tab", { name: /^response/ }));
    expect(screen.queryByRole("button", { name: "Edit" })).not.toBeInTheDocument();
  });

  it("resurfaces Approve when the response differs from the approved copy", async () => {
    vi.mocked(getStageContent).mockResolvedValue({
      topic_id: "t",
      stage: "draft",
      prompt: "# prompt",
      response: "edited body",
      approved: "previously approved body",
      response_sha256: "sha-1",
    });
    renderAt("/topics/t/stages/draft");
    expect(
      await screen.findByRole("button", { name: "Approve draft" }),
    ).toBeInTheDocument();
  });
});
