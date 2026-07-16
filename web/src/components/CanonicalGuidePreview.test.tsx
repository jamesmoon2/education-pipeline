import { createRef } from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { getStageContent, postGuidePreview } from "../api/client";
import CanonicalGuidePreview, { type CanonicalGuidePreviewHandle } from "./CanonicalGuidePreview";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, getStageContent: vi.fn(), postGuidePreview: vi.fn() };
});

const stage = {
  topic_id: "feedback-loops",
  stage: "repair",
  prompt: "repair prompt",
  response: "UNAPPROVED RESPONSE",
  approved: '{"schema_version":"1.1","course":{"id":"approved"}}',
  response_sha256: "a".repeat(64),
  content_type: "application/vnd.education-pipeline.guide+json;version=1.0" as const,
};

describe("CanonicalGuidePreview", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getStageContent).mockResolvedValue(stage);
    vi.mocked(postGuidePreview).mockResolvedValue({
      html: "<!doctype html><p>Canonical guide</p>",
      content_sha256: "b".repeat(64),
      validation: { blocking: 0, errors: 0, warnings: 0 },
    });
  });

  it("previews only the approved repair artifact, the durable finalization source", async () => {
    render(<CanonicalGuidePreview topicId="feedback-loops" />);

    expect(await screen.findByTitle("Interactive guide preview")).toHaveAttribute(
      "srcdoc",
      expect.stringContaining("Canonical guide"),
    );
    expect(getStageContent).toHaveBeenCalledWith("feedback-loops", "repair");
    expect(postGuidePreview).toHaveBeenCalledWith(stage.approved);
    expect(postGuidePreview).not.toHaveBeenCalledWith(stage.response);
    expect(screen.getByText("Approved repair / final source")).toBeInTheDocument();
  });

  it("does not preview an unapproved response", async () => {
    vi.mocked(getStageContent).mockResolvedValue({ ...stage, approved: null });
    render(<CanonicalGuidePreview topicId="feedback-loops" />);

    expect(await screen.findByText("No approved repair guide is available yet.")).toBeInTheDocument();
    expect(postGuidePreview).not.toHaveBeenCalled();
    expect(screen.queryByTitle("Interactive guide preview")).not.toBeInTheDocument();
  });

  it("forwards the single revealEvidence imperative operation to the frame", async () => {
    const ref = createRef<CanonicalGuidePreviewHandle>();
    render(<CanonicalGuidePreview ref={ref} topicId="feedback-loops" />);
    const frame = (await screen.findByTitle("Interactive guide preview")) as HTMLIFrameElement;
    const postMessage = vi.fn();
    Object.defineProperty(frame, "contentWindow", {
      configurable: true,
      value: { postMessage },
    });

    let accepted = false;
    act(() => {
      accepted = ref.current?.revealEvidence({ kind: "outcome", id: "identify-loop" }) ?? false;
    });
    expect(accepted).toBe(true);
    await waitFor(() => expect(postMessage).toHaveBeenCalledTimes(1));
  });

  it("accepts a pre-mount reveal command and delivers it after fetch, mount, and load", async () => {
    const postMessage = vi.fn();
    const contentWindow = vi
      .spyOn(HTMLIFrameElement.prototype, "contentWindow", "get")
      .mockReturnValue({ postMessage } as unknown as Window);
    let resolveStage!: (value: typeof stage) => void;
    vi.mocked(getStageContent).mockReturnValue(new Promise((resolve) => {
      resolveStage = resolve;
    }));
    const ref = createRef<CanonicalGuidePreviewHandle>();
    render(<CanonicalGuidePreview ref={ref} topicId="feedback-loops" />);

    let accepted = false;
    act(() => {
      expect(
        ref.current?.revealEvidence({ kind: "module", id: "Not A Guide ID" }),
      ).toBe(false);
      accepted = ref.current?.revealEvidence({ kind: "module", id: "loop-basics" }) ?? false;
    });
    expect(accepted).toBe(true);

    await act(async () => {
      resolveStage(stage);
    });
    await screen.findByTitle("Interactive guide preview");
    await waitFor(() => expect(postMessage).toHaveBeenCalledWith(
      expect.objectContaining({ kind: "module", id: "loop-basics" }),
      "*",
    ));
    contentWindow.mockRestore();
  });

  it("never replays an old command after topic A switches to B and returns to A", async () => {
    const requests: Array<{
      topicId: string;
      resolve: (value: typeof stage) => void;
    }> = [];
    vi.mocked(getStageContent).mockImplementation((topicId) => new Promise((resolve) => {
      requests.push({ topicId, resolve });
    }));
    const postMessage = vi.fn();
    const contentWindow = vi
      .spyOn(HTMLIFrameElement.prototype, "contentWindow", "get")
      .mockReturnValue({ postMessage } as unknown as Window);
    const ref = createRef<CanonicalGuidePreviewHandle>();
    const { rerender } = render(
      <CanonicalGuidePreview ref={ref} topicId="topic-a" />,
    );
    expect(requests.map((request) => request.topicId)).toEqual(["topic-a"]);

    act(() => {
      expect(ref.current?.revealEvidence({ kind: "module", id: "loop-basics" })).toBe(true);
    });
    rerender(<CanonicalGuidePreview ref={ref} topicId="topic-b" />);
    rerender(<CanonicalGuidePreview ref={ref} topicId="topic-a" />);
    expect(requests.map((request) => request.topicId)).toEqual([
      "topic-a",
      "topic-b",
      "topic-a",
    ]);

    await act(async () => {
      requests[2].resolve({ ...stage, topic_id: "topic-a" });
    });
    const frame = await screen.findByTitle("Interactive guide preview");
    fireEvent.load(frame);
    expect(postMessage).not.toHaveBeenCalled();
    contentWindow.mockRestore();
  });
});
