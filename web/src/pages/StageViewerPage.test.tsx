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
    content_contract: { kind: "legacy_markdown" },
    validations: {
      draft: { state: "missing", blocking: 0, errors: 0, warnings: 0 },
      final: { state: "missing", blocking: 0, errors: 0, warnings: 0 },
    },
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
      content_type: "text/markdown",
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
      content_type: "text/markdown",
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
      content_type: "text/markdown",
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
      content_type: "text/markdown",
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
      content_type: "text/markdown",
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
      content_type: "text/markdown",
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
      content_type: "text/markdown",
    });
    renderAt("/topics/t/stages/draft");
    expect(
      await screen.findByRole("button", { name: "Approve draft" }),
    ).toBeInTheDocument();
  });

  it("compare toggle lays prompt and response side by side", async () => {
    vi.mocked(getStageContent).mockResolvedValue({
      topic_id: "t",
      stage: "draft",
      prompt: "the prompt text",
      response: "the response text",
      approved: null,
      response_sha256: "sha-1",
      content_type: "text/markdown",
    });
    renderAt("/topics/t/stages/draft");
    await userEvent.click(
      await screen.findByRole("button", { name: "Compare prompt ↔ response" }),
    );
    expect(screen.getByText("the prompt text")).toBeInTheDocument();
    expect(screen.getByText("the response text")).toBeInTheDocument();
    // toggling back returns to the single tab pane
    await userEvent.click(screen.getByRole("button", { name: "Single pane" }));
    expect(screen.queryByText("the response text")).not.toBeInTheDocument();
  });

  it("renders a draft-vs-repair line diff on the repair stage", async () => {
    vi.mocked(getStageContent).mockImplementation(async (_topic, stage) => {
      if (stage === "draft") {
        return {
          topic_id: "t",
          stage: "draft",
          prompt: null,
          response: "same line\nold line",
          approved: "same line\nold line",
          response_sha256: "sha-d",
          content_type: "text/markdown",
        };
      }
      return {
        topic_id: "t",
        stage: "repair",
        prompt: null,
        response: "same line\nnew line",
        approved: null,
        response_sha256: "sha-r",
        content_type: "text/markdown",
      };
    });
    renderAt("/topics/t/stages/repair");
    await userEvent.click(
      await screen.findByRole("button", { name: "Diff against draft" }),
    );

    expect(await screen.findByText("old line")).toBeInTheDocument();
    expect(screen.getByText("old line").closest(".diff-line")).toHaveClass(
      "diff-removed",
    );
    expect(screen.getByText("new line").closest(".diff-line")).toHaveClass(
      "diff-added",
    );
    expect(getStageContent).toHaveBeenCalledWith("t", "draft");
  });

  it("does not offer the draft diff on non-repair stages", async () => {
    vi.mocked(getStageContent).mockResolvedValue({
      topic_id: "t",
      stage: "draft",
      prompt: "# prompt",
      response: "body",
      approved: null,
      response_sha256: "sha-1",
      content_type: "text/markdown",
    });
    renderAt("/topics/t/stages/draft");
    await screen.findByRole("tab", { name: /prompt/ });
    expect(
      screen.queryByRole("button", { name: "Diff against draft" }),
    ).not.toBeInTheDocument();
  });

  it("disables tab switching while the editor is open", async () => {
    vi.mocked(getStageContent).mockResolvedValue({
      topic_id: "t",
      stage: "draft",
      prompt: "# prompt",
      response: "response body",
      approved: null,
      response_sha256: "sha-1",
      content_type: "text/markdown",
    });
    renderAt("/topics/t/stages/draft");
    await userEvent.click(await screen.findByRole("tab", { name: /^response/ }));
    await userEvent.click(await screen.findByRole("button", { name: "Edit" }));

    expect(screen.getByRole("tab", { name: /prompt/ })).toBeDisabled();
    // the buffer survives an attempted tab click
    await userEvent.click(screen.getByRole("tab", { name: /prompt/ }));
    expect(screen.getByLabelText("Edit response for draft")).toHaveValue("response body");
  });

  it("closes the diff toggle when the draft fetch fails", async () => {
    vi.mocked(getStageContent).mockImplementation(async (_topic, stage) => {
      if (stage === "draft") throw new Error("boom");
      return {
        topic_id: "t",
        stage: "repair",
        prompt: null,
        response: "body",
        approved: null,
        response_sha256: "sha-r",
        content_type: "text/markdown",
      };
    });
    renderAt("/topics/t/stages/repair");
    await userEvent.click(await screen.findByRole("button", { name: "Diff against draft" }));
    expect(await screen.findByRole("button", { name: "Diff against draft" })).toBeInTheDocument();
    expect(document.querySelector(".diff")).toBeNull();
  });
});
