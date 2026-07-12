import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { NextAction, RunStatus } from "../api/types";
import PrimaryAction from "./PrimaryAction";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return {
    ApiRequestError: actual.ApiRequestError,
    postAdvance: vi.fn(),
    postApprove: vi.fn(),
    postFinalize: vi.fn(),
    postResponse: vi.fn(),
    postExport: vi.fn(),
    enqueueJob: vi.fn(),
    downloadFinal: vi.fn(),
    downloadExport: vi.fn(),
  };
});

import {
  ApiRequestError,
  enqueueJob,
  postAdvance,
  postApprove,
  postFinalize,
  postResponse,
} from "../api/client";

beforeEach(() => {
  vi.clearAllMocks();
  vi.restoreAllMocks();
});

function makeStatus(action: NextAction["action"], stage: string | null): RunStatus {
  return {
    topic_id: "t",
    finalized: action === "done",
    content_contract: { kind: "legacy_markdown" },
    validations: {
      draft: { state: "missing", blocking: 0, errors: 0, warnings: 0 },
      final: { state: "missing", blocking: 0, errors: 0, warnings: 0 },
    },
    stages: [],
    next_action: { topic_id: "t", stage, action, detail: `detail for ${action}` },
  };
}

function renderAction(status: RunStatus, onChanged = vi.fn()) {
  render(
    <MemoryRouter>
      <PrimaryAction status={status} onChanged={onChanged} />
    </MemoryRouter>,
  );
  return onChanged;
}

describe("PrimaryAction", () => {
  it("write_prompt renders Advance and posts it", async () => {
    vi.mocked(postAdvance).mockResolvedValue({
      performed: "write_prompt",
      status: makeStatus("save_response", "spec"),
    });
    const onChanged = renderAction(makeStatus("write_prompt", "spec"));
    await userEvent.click(screen.getByRole("button", { name: "Advance" }));
    expect(postAdvance).toHaveBeenCalledWith("t");
    expect(onChanged).toHaveBeenCalled();
    expect(await screen.findByText("Prompt written.")).toBeInTheDocument();
  });

  it("save_response renders provider run and paste form", async () => {
    vi.mocked(enqueueJob).mockResolvedValue({} as never);
    vi.mocked(postResponse).mockResolvedValue({} as never);
    const onChanged = renderAction(makeStatus("save_response", "draft"));

    await userEvent.click(screen.getByRole("button", { name: "Run with provider" }));
    expect(enqueueJob).toHaveBeenCalledWith("t");

    await userEvent.click(screen.getByRole("button", { name: "Paste response…" }));
    await userEvent.type(screen.getByLabelText("Response for draft"), "draft body");
    await userEvent.click(screen.getByRole("button", { name: "Save response" }));
    expect(postResponse).toHaveBeenCalledWith("t", "draft", "draft body");
    expect(onChanged).toHaveBeenCalled();
  });

  it("approve renders Approve {stage} with a review link", async () => {
    vi.mocked(postApprove).mockResolvedValue({} as never);
    renderAction(makeStatus("approve", "qa"));
    expect(screen.getByRole("link", { name: "review first" })).toHaveAttribute(
      "href",
      "/topics/t/stages/qa",
    );
    await userEvent.click(screen.getByRole("button", { name: "Approve qa" }));
    expect(postApprove).toHaveBeenCalledWith("t", "qa");
  });

  it("retries approve with overwrite after a confirmed 409", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    vi.mocked(postApprove)
      .mockRejectedValueOnce(new ApiRequestError(409, "already_exists", "already approved"))
      .mockResolvedValueOnce({} as never);
    renderAction(makeStatus("approve", "qa"));
    await userEvent.click(screen.getByRole("button", { name: "Approve qa" }));
    expect(postApprove).toHaveBeenNthCalledWith(1, "t", "qa");
    expect(postApprove).toHaveBeenNthCalledWith(2, "t", "qa", true);
  });

  it("finalize renders Finalize", async () => {
    vi.mocked(postFinalize).mockResolvedValue({} as never);
    renderAction(makeStatus("finalize", null));
    await userEvent.click(screen.getByRole("button", { name: "Finalize" }));
    expect(postFinalize).toHaveBeenCalledWith("t");
  });

  it("shows the envelope message on job_active", async () => {
    vi.mocked(postAdvance).mockRejectedValue(
      new ApiRequestError(409, "job_active", "job j1 is running for topic 't'"),
    );
    renderAction(makeStatus("write_prompt", "spec"));
    await userEvent.click(screen.getByRole("button", { name: "Advance" }));
    expect(
      await screen.findByText(/job j1 is running for topic 't'/),
    ).toBeInTheDocument();
  });
});
