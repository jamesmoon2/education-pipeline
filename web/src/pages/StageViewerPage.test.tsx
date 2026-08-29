import { act, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  Link,
  MemoryRouter,
  Route,
  Routes,
} from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import StageViewerPage from "./StageViewerPage";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return {
    ApiRequestError: actual.ApiRequestError,
    getStageContent: vi.fn(),
    getRepairModules: vi.fn(),
    postAdvance: vi.fn(),
    getRunStatus: vi.fn(),
    postApprove: vi.fn(),
    approveAudit: vi.fn(),
    enqueueAuditJob: vi.fn(),
    postResponse: vi.fn(),
    putResponse: vi.fn(),
    postPreview: vi.fn(),
    // Read by the "Approve & continue" chain (lib/continueRun.ts).
    postValidate: vi.fn(),
    enqueueJob: vi.fn(),
    getConfigPlan: vi.fn(),
  };
});

import {
  ApiRequestError,
  approveAudit,
  enqueueAuditJob,
  enqueueJob,
  getConfigPlan,
  getRepairModules,
  getRunStatus,
  getStageContent,
  postAdvance,
  postApprove,
  postResponse,
  putResponse,
} from "../api/client";
import type { NextAction, RunStatus } from "../api/types";

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/topics/:topicId/stages/:stage" element={<StageViewerPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

function makeRunStatus(
  next: Pick<NextAction, "action" | "stage">,
  finalized = false,
): RunStatus {
  return {
    topic_id: "t",
    finalized,
    content_contract: { kind: "legacy_markdown" },
    stage_provenance: [],
    validations: {
      draft: { state: "missing", blocking: 0, errors: 0, warnings: 0 },
      final: { state: "missing", blocking: 0, errors: 0, warnings: 0 },
    },
    stages: [],
    next_action: { topic_id: "t", detail: "", ...next },
  };
}

function mockRun(finalized = false, next: Pick<NextAction, "action" | "stage"> = {
  action: "done",
  stage: null,
}) {
  vi.mocked(getRunStatus).mockResolvedValue(makeRunStatus(next, finalized));
}

beforeEach(() => {
  vi.clearAllMocks();
  mockRun();
});

describe("StageViewerPage", () => {
  it("clears route-scoped content and rejects a mismatched stage response after navigation", async () => {
    let resolveNext!: (value: Awaited<ReturnType<typeof getStageContent>>) => void;
    vi.mocked(getStageContent).mockImplementation(async (topic, stage) => {
      if (topic === "topic-a") {
        return {
          topic_id: topic,
          stage,
          prompt: "private prompt A",
          response: "private response A",
          approved: null,
          response_sha256: "sha-a",
          content_type: "text/markdown",
        };
      }
      return new Promise((resolve) => {
        resolveNext = resolve;
      });
    });
    vi.mocked(getRunStatus).mockImplementation(async (topic) => ({
      topic_id: topic,
      finalized: false,
      content_contract: { kind: "legacy_markdown" },
      stage_provenance: [],
      validations: {
        draft: { state: "missing", blocking: 0, errors: 0, warnings: 0 },
        final: { state: "missing", blocking: 0, errors: 0, warnings: 0 },
      },
      stages: [],
      next_action: { topic_id: topic, stage: null, action: "done", detail: "" },
    }));
    render(
      <MemoryRouter initialEntries={["/topics/topic-a/stages/draft?tab=response"]}>
        <Link to="/topics/topic-b/stages/audit">Go to topic B audit</Link>
        <Routes>
          <Route
            path="/topics/:topicId/stages/:stage"
            element={<StageViewerPage />}
          />
        </Routes>
      </MemoryRouter>,
    );

    await userEvent.click(await screen.findByRole("button", { name: "Edit" }));
    expect(screen.getByLabelText("Edit response for draft")).toHaveValue(
      "private response A",
    );

    await userEvent.click(screen.getByRole("link", { name: "Go to topic B audit" }));

    expect(screen.queryByText("private prompt A")).not.toBeInTheDocument();
    expect(screen.queryByText("private response A")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Edit response for draft")).not.toBeInTheDocument();
    expect(screen.getByText("Loading…")).toBeInTheDocument();

    await act(async () => {
      resolveNext({
        topic_id: "topic-a",
        stage: "audit",
        prompt: "wrong topic prompt",
        response: "wrong topic response",
        approved: null,
        response_sha256: "sha-wrong",
        content_type: "application/json",
      });
    });

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Stage response does not match this route.",
    );
    expect(screen.queryByText("wrong topic response")).not.toBeInTheDocument();
  });

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
    // Markdown renders as prose by default; the Raw toggle restores the bytes.
    expect(await screen.findByRole("heading", { name: "the prompt" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Raw" }));
    expect(screen.getByText("# the prompt")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: /^response/ }));
    expect(screen.getByRole("heading", { name: "the response" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: /^approved/ }));
    expect(screen.getByText("(no approved yet)")).toBeInTheDocument();
  });

  it("switches to the requested tab on in-page navigation to the same stage", async () => {
    vi.mocked(getStageContent).mockResolvedValue({
      topic_id: "t",
      stage: "qa",
      prompt: "# the prompt",
      response: "# the response",
      approved: null,
      response_sha256: "sha-1",
      content_type: "text/markdown",
    });
    // A job toast's "ready to review" link navigates to the stage the user
    // may already be viewing: only the ?tab= query changes, so the route
    // key stays the same and the viewer must react to the query itself.
    render(
      <MemoryRouter initialEntries={["/topics/t/stages/qa"]}>
        <Link to="/topics/t/stages/qa?tab=response">ready to review</Link>
        <Routes>
          <Route path="/topics/:topicId/stages/:stage" element={<StageViewerPage />} />
        </Routes>
      </MemoryRouter>,
    );
    expect(await screen.findByRole("heading", { name: "the prompt" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("link", { name: "ready to review" }));
    expect(await screen.findByRole("heading", { name: "the response" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /^response/ })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("opens the paste form on in-page navigation with ?paste=1", async () => {
    vi.mocked(getStageContent).mockResolvedValue({
      topic_id: "t",
      stage: "audit",
      prompt: "# audit prompt",
      response: '{"findings": []}',
      approved: null,
      response_sha256: "sha-1",
      content_type: "application/json",
    });
    // AuditControls links to the audit stage with ?tab=response&paste=1;
    // when that stage page is already open only the query changes.
    render(
      <MemoryRouter initialEntries={["/topics/t/stages/audit"]}>
        <Link to="/topics/t/stages/audit?tab=response&paste=1">Paste audit response…</Link>
        <Routes>
          <Route path="/topics/:topicId/stages/:stage" element={<StageViewerPage />} />
        </Routes>
      </MemoryRouter>,
    );
    await screen.findByRole("tab", { name: /^response/ });
    expect(screen.queryByLabelText("Response for audit")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("link", { name: "Paste audit response…" }));
    expect(await screen.findByLabelText("Response for audit")).toBeInTheDocument();
  });

  it("explains the prompt/response/approved workflow with an InfoTip", async () => {
    vi.mocked(getStageContent).mockResolvedValue({
      topic_id: "t",
      stage: "draft",
      prompt: "# the prompt",
      response: null,
      approved: null,
      response_sha256: null,
      content_type: "text/markdown",
    });
    renderAt("/topics/t/stages/draft");
    expect(
      await screen.findByRole("button", { name: "About Stage tabs" }),
    ).toBeInTheDocument();
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

  it("offers Approve & continue for the approval the run is waiting on", async () => {
    // The daemon reports the next action after the approval lands, so the
    // chain sees the run move on exactly as it would against the daemon.
    let next: Pick<NextAction, "action" | "stage"> = { action: "approve", stage: "draft" };
    vi.mocked(getRunStatus).mockImplementation(async () => makeRunStatus(next));
    vi.mocked(postApprove).mockImplementation(async () => {
      next = { action: "save_response", stage: "qa" };
      return {} as never;
    });
    vi.mocked(getConfigPlan).mockResolvedValue({
      provider: "claude-code",
      plan_sha256: "sha-plan",
      stages: [],
    });
    vi.mocked(enqueueJob).mockResolvedValue({} as never);
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

    await userEvent.click(await screen.findByRole("button", { name: "Approve & continue" }));
    expect(postApprove).toHaveBeenCalledWith("t", "draft");
    expect(enqueueJob).toHaveBeenCalledWith("t");
    const feedback = await screen.findByRole("status");
    expect(feedback).toHaveTextContent("Approved draft — started qa with claude-code.");
    expect(feedback).toHaveClass("success");
  });

  it("announces a failed follow-up as an alert while reporting the approval", async () => {
    let next: Pick<NextAction, "action" | "stage"> = { action: "approve", stage: "draft" };
    vi.mocked(getRunStatus).mockImplementation(async () => makeRunStatus(next));
    vi.mocked(postApprove).mockImplementation(async () => {
      next = { action: "write_prompt", stage: "qa" };
      return {} as never;
    });
    vi.mocked(postAdvance).mockRejectedValue(
      new ApiRequestError(409, "job_active", "job j1 is running for topic 't'"),
    );
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

    await userEvent.click(await screen.findByRole("button", { name: "Approve & continue" }));
    const feedback = await screen.findByRole("alert");
    expect(feedback).toHaveTextContent(
      "Approved draft, but writing the qa prompt failed: job j1 is running for topic 't'",
    );
    expect(feedback).toHaveClass("error");
  });

  it("offers only the plain approve button when the run's next action is elsewhere", async () => {
    // Re-approving an earlier stage: the run is waiting on repair, so there
    // is no next step for this stage's approval to continue into.
    mockRun(false, { action: "approve", stage: "repair" });
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

    expect(await screen.findByRole("button", { name: "Approve draft" })).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Approve & continue" }),
    ).not.toBeInTheDocument();
  });

  it("never chains an audit approval", async () => {
    mockRun(false, { action: "approve", stage: "audit" });
    vi.mocked(getStageContent).mockResolvedValue({
      topic_id: "t",
      stage: "audit",
      prompt: "audit prompt",
      response: '{"findings":[]}',
      approved: null,
      response_sha256: "sha-audit",
      content_type: "application/json",
    });
    renderAt("/topics/t/stages/audit?tab=response");

    expect(await screen.findByRole("button", { name: "Approve audit" })).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Approve & continue" }),
    ).not.toBeInTheDocument();
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

  it("opens audit JSON in the JSON editor without a markdown preview", async () => {
    vi.mocked(getStageContent).mockResolvedValue({
      topic_id: "t",
      stage: "audit",
      prompt: "audit prompt",
      response: '{"findings":[]}',
      approved: null,
      response_sha256: "sha-audit",
      content_type: "application/json",
    });
    renderAt("/topics/t/stages/audit");
    await userEvent.click(await screen.findByRole("tab", { name: /^response/ }));
    await userEvent.click(await screen.findByRole("button", { name: "Edit" }));

    const textarea = screen.getByLabelText("Edit response for audit");
    expect(textarea).toHaveValue('{"findings":[]}');
    expect(screen.queryByRole("button", { name: "Preview" })).not.toBeInTheDocument();
  });

  it("uses the audit approval adapter from the shared stage viewer", async () => {
    vi.mocked(getStageContent).mockResolvedValue({
      topic_id: "t",
      stage: "audit",
      prompt: "audit prompt",
      response: '{"findings":[]}',
      approved: null,
      response_sha256: "sha-audit",
      content_type: "application/json",
    });
    vi.mocked(approveAudit).mockResolvedValue({} as never);
    renderAt("/topics/t/stages/audit?tab=response");

    await userEvent.click(await screen.findByRole("button", { name: "Approve audit" }));
    expect(approveAudit).toHaveBeenCalledWith("t", false);
    expect(postApprove).not.toHaveBeenCalled();
  });

  it("uses the forced audit job adapter for a provider rerun", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    vi.mocked(getStageContent).mockResolvedValue({
      topic_id: "t",
      stage: "audit",
      prompt: "audit prompt",
      response: '{"findings":[]}',
      approved: '{"findings":[]}',
      response_sha256: "sha-audit",
      content_type: "application/json",
    });
    vi.mocked(enqueueAuditJob).mockResolvedValue({} as never);
    renderAt("/topics/t/stages/audit");

    await userEvent.click(await screen.findByRole("button", { name: "Rerun with provider…" }));
    expect(enqueueAuditJob).toHaveBeenCalledWith("t", true);
  });

  it("keeps finalized audit response editing and provider rerun available", async () => {
    mockRun(true);
    vi.spyOn(window, "confirm").mockReturnValue(true);
    vi.mocked(getStageContent).mockResolvedValue({
      topic_id: "t",
      stage: "audit",
      prompt: "audit prompt",
      response: '{"findings":[]}',
      approved: '{"findings":[]}',
      response_sha256: "sha-audit",
      content_type: "application/json",
    });
    vi.mocked(enqueueAuditJob).mockResolvedValue({} as never);
    renderAt("/topics/t/stages/audit?tab=response");

    expect(await screen.findByRole("button", { name: "Edit" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Rerun with provider…" }));
    expect(enqueueAuditJob).toHaveBeenCalledWith("t", true);
  });

  it("uses the shared paste form to replace an existing finalized audit response after confirmation", async () => {
    mockRun(true);
    vi.spyOn(window, "confirm").mockReturnValue(true);
    vi.mocked(getStageContent).mockResolvedValue({
      topic_id: "t",
      stage: "audit",
      prompt: "audit prompt",
      response: '{"findings":[]}',
      approved: '{"findings":[]}',
      response_sha256: "sha-audit",
      content_type: "application/json",
    });
    vi.mocked(postResponse)
      .mockRejectedValueOnce(new ApiRequestError(409, "already_exists", "response exists"))
      .mockResolvedValueOnce({} as never);
    renderAt("/topics/t/stages/audit?tab=response&paste=1");

    fireEvent.change(await screen.findByLabelText("Response for audit"), {
      target: { value: '{"findings":[1]}' },
    });
    await userEvent.click(screen.getByRole("button", { name: "Save response" }));

    expect(postResponse).toHaveBeenNthCalledWith(1, "t", "audit", '{"findings":[1]}');
    expect(postResponse).toHaveBeenNthCalledWith(2, "t", "audit", '{"findings":[1]}', true);
  });

  it("never force-overwrites an existing audit response without confirmation", async () => {
    mockRun(true);
    vi.spyOn(window, "confirm").mockReturnValue(false);
    vi.mocked(getStageContent).mockResolvedValue({
      topic_id: "t",
      stage: "audit",
      prompt: "audit prompt",
      response: '{"findings":[]}',
      approved: '{"findings":[]}',
      response_sha256: "sha-audit",
      content_type: "application/json",
    });
    vi.mocked(postResponse).mockRejectedValue(
      new ApiRequestError(409, "already_exists", "response exists"),
    );
    renderAt("/topics/t/stages/audit?tab=response&paste=1");

    fireEvent.change(await screen.findByLabelText("Response for audit"), {
      target: { value: '{"findings":[1]}' },
    });
    await userEvent.click(screen.getByRole("button", { name: "Save response" }));

    expect(postResponse).toHaveBeenCalledTimes(1);
    expect(postResponse).not.toHaveBeenCalledWith("t", "audit", expect.any(String), true);
  });

  it("requires the pending audit response tab before approval", async () => {
    vi.mocked(getStageContent).mockResolvedValue({
      topic_id: "t",
      stage: "audit",
      prompt: "audit prompt",
      response: '{"findings":[{"id":"new"}]}',
      approved: '{"findings":[]}',
      response_sha256: "sha-audit",
      content_type: "application/json",
    });
    renderAt("/topics/t/stages/audit?tab=approved");

    expect(await screen.findByText(/Review the pending audit response before approval/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve audit" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: /^response/ }));
    expect(screen.getByRole("button", { name: "Approve audit" })).toBeInTheDocument();
  });

  it("announces stage action success and errors with status semantics", async () => {
    vi.mocked(getStageContent).mockResolvedValue({
      topic_id: "t",
      stage: "audit",
      prompt: "audit prompt",
      response: '{"findings":[]}',
      approved: null,
      response_sha256: "sha-audit",
      content_type: "application/json",
    });
    vi.mocked(approveAudit).mockResolvedValue({} as never);
    renderAt("/topics/t/stages/audit?tab=response");
    await userEvent.click(await screen.findByRole("button", { name: "Approve audit" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Approved audit.");

    vi.spyOn(window, "confirm").mockReturnValue(true);
    vi.mocked(enqueueAuditJob).mockRejectedValue(new Error("Provider unavailable."));
    await userEvent.click(screen.getByRole("button", { name: "Rerun with provider…" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Provider unavailable.");
  });

  it("groups stage actions in a toolbar above the content", async () => {
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

    const toolbar = await screen.findByRole("toolbar", { name: "Stage actions" });
    const edit = screen.getByRole("button", { name: "Edit" });
    const approve = screen.getByRole("button", { name: "Approve draft" });
    expect(toolbar).toContainElement(edit);
    expect(toolbar).toContainElement(approve);

    // The toolbar renders before the content pane.
    const content = screen.getByText("response body");
    expect(
      toolbar.compareDocumentPosition(content) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
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

  it("shows what changed since the last approval by default on a pending re-approval", async () => {
    vi.mocked(getStageContent).mockResolvedValue({
      topic_id: "t",
      stage: "draft",
      prompt: "# prompt",
      response: "same line\nnew line",
      approved: "same line\nold line",
      response_sha256: "sha-2",
      content_type: "text/markdown",
    });
    renderAt("/topics/t/stages/draft");

    const region = await screen.findByRole("region", {
      name: "What changed since last approval",
    });
    expect(
      within(region).getByRole("heading", { name: "What changed since last approval" }),
    ).toBeInTheDocument();
    expect(within(region).getByText("old line").closest(".diff-line")).toHaveClass(
      "diff-removed",
    );
    expect(within(region).getByText("new line").closest(".diff-line")).toHaveClass(
      "diff-added",
    );

    // The approve toolbar stays above the delta, and the hide toggle sits in
    // the view-toggles row alongside the compare toggle.
    const toolbar = screen.getByRole("toolbar", { name: "Stage actions" });
    expect(toolbar).toContainElement(
      screen.getByRole("button", { name: "Approve draft" }),
    );
    expect(
      toolbar.compareDocumentPosition(region) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    const hide = screen.getByRole("button", { name: "Hide what changed" });
    expect(hide.closest(".view-toggles")).not.toBeNull();
  });

  it("offers no what-changed section or toggle on a first approval", async () => {
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
    expect(
      await screen.findByRole("button", { name: "Approve draft" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("region", { name: "What changed since last approval" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /what changed/i }),
    ).not.toBeInTheDocument();
  });

  it("offers no what-changed section for a module-scoped repair", async () => {
    vi.mocked(getStageContent).mockResolvedValue({
      topic_id: "t",
      stage: "repair",
      prompt: "# prompt",
      response: '{"module": "loop-basics"}',
      approved: '{"whole": "guide with loop-basics spliced in"}',
      response_sha256: "sha-3",
      content_type: "application/json",
      repair_scope: { module_id: "loop-basics" },
    });
    renderAt("/topics/t/stages/repair");
    expect(
      await screen.findByRole("button", { name: "Approve repair" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("region", { name: "What changed since last approval" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /what changed/i }),
    ).not.toBeInTheDocument();
  });

  it("keeps an explicitly hidden what-changed section hidden across poll refreshes", async () => {
    vi.useFakeTimers();
    try {
      vi.mocked(getStageContent).mockResolvedValue({
        topic_id: "t",
        stage: "draft",
        prompt: "# prompt",
        response: "same line\nnew line",
        approved: "same line\nold line",
        response_sha256: "sha-2",
        content_type: "text/markdown",
      });
      renderAt("/topics/t/stages/draft");
      await act(async () => {
        await Promise.resolve();
        await Promise.resolve();
        await Promise.resolve();
      });
      expect(
        screen.getByRole("region", { name: "What changed since last approval" }),
      ).toBeInTheDocument();

      fireEvent.click(screen.getByRole("button", { name: "Hide what changed" }));
      expect(
        screen.queryByRole("region", { name: "What changed since last approval" }),
      ).not.toBeInTheDocument();

      // A polling refresh replaces `data` but must not reopen the section.
      const fetches = vi.mocked(getStageContent).mock.calls.length;
      await act(async () => {
        vi.advanceTimersByTime(5_000);
        await Promise.resolve();
        await Promise.resolve();
        await Promise.resolve();
      });
      expect(vi.mocked(getStageContent).mock.calls.length).toBeGreaterThan(fetches);
      expect(
        screen.queryByRole("region", { name: "What changed since last approval" }),
      ).not.toBeInTheDocument();

      fireEvent.click(
        screen.getByRole("button", { name: "What changed since last approval" }),
      );
      expect(
        screen.getByRole("region", { name: "What changed since last approval" }),
      ).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it("keeps the repair draft diff independent of the what-changed section", async () => {
    vi.mocked(getStageContent).mockImplementation(async (_topic, stage) => {
      if (stage === "draft") {
        return {
          topic_id: "t",
          stage: "draft",
          prompt: null,
          response: "shared line\ndraft line",
          approved: "shared line\ndraft line",
          response_sha256: "sha-d",
          content_type: "text/markdown",
        };
      }
      return {
        topic_id: "t",
        stage: "repair",
        prompt: null,
        response: "shared line\nrepair new line",
        approved: "shared line\nrepair old line",
        response_sha256: "sha-r",
        content_type: "text/markdown",
      };
    });
    renderAt("/topics/t/stages/repair");

    const region = await screen.findByRole("region", {
      name: "What changed since last approval",
    });
    expect(
      within(region).getByText("repair old line").closest(".diff-line"),
    ).toHaveClass("diff-removed");

    await userEvent.click(screen.getByRole("button", { name: "Diff against draft" }));
    // The draft diff renders outside the what-changed region.
    expect(await screen.findByText("draft line")).toBeInTheDocument();
    expect(within(region).queryByText("draft line")).not.toBeInTheDocument();

    // Hiding the what-changed delta leaves the draft diff open.
    await userEvent.click(screen.getByRole("button", { name: "Hide what changed" }));
    expect(
      screen.queryByRole("region", { name: "What changed since last approval" }),
    ).not.toBeInTheDocument();
    expect(screen.getByText("draft line")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Hide diff" })).toBeInTheDocument();
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

  it("labels a scoped repair and offers module regeneration on guide runs", async () => {
    vi.mocked(getRunStatus).mockResolvedValue({
      topic_id: "t",
      finalized: false,
      content_contract: { kind: "interactive_guide", schema_version: "1.0" },
      stage_provenance: [],
      validations: {
        draft: { state: "current", blocking: 0, errors: 0, warnings: 0 },
        final: { state: "missing", blocking: 0, errors: 0, warnings: 0 },
      },
      stages: [],
      next_action: { topic_id: "t", stage: "repair", action: "save_response", detail: "" },
    });
    vi.mocked(getStageContent).mockResolvedValue({
      topic_id: "t",
      stage: "repair",
      prompt: "scoped prompt",
      response: null,
      approved: null,
      response_sha256: null,
      content_type: "application/vnd.education-pipeline.guide+json;version=1.0",
      repair_scope: { module_id: "loop-basics" },
    });
    vi.mocked(getRepairModules).mockResolvedValue({
      topic_id: "t",
      modules: [{ id: "loop-basics", title: "How loops behave", open_findings: 1 }],
      repair_scope: { module_id: "loop-basics" },
    });
    renderAt("/topics/t/stages/repair");

    expect(
      await screen.findByText(/The pending repair is scoped to module/),
    ).toBeInTheDocument();
    expect(
      await screen.findByRole("heading", { name: "Regenerate one module" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("option", { name: /How loops behave \(1 open finding\)/ }),
    ).toBeInTheDocument();
  });
});
