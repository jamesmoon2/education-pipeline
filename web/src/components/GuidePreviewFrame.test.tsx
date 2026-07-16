import { createRef } from "react";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import GuidePreviewFrame, {
  GUIDE_PREVIEW_EVIDENCE_MESSAGE_TYPE,
  type GuidePreviewFrameHandle,
} from "./GuidePreviewFrame";

describe("GuidePreviewFrame", () => {
  it("keeps the preview opaque and queues the frozen evidence message until load", () => {
    const ref = createRef<GuidePreviewFrameHandle>();
    render(<GuidePreviewFrame ref={ref} html="<!doctype html><p>Guide</p>" />);

    const frame = screen.getByTitle("Interactive guide preview") as HTMLIFrameElement;
    expect(frame).toHaveAttribute("sandbox", "allow-scripts");
    expect(frame).not.toHaveAttribute("sandbox", expect.stringContaining("allow-same-origin"));

    const postMessage = vi.fn();
    Object.defineProperty(frame, "contentWindow", {
      configurable: true,
      value: { postMessage },
    });

    act(() => {
      expect(ref.current?.revealEvidence({ kind: "module", id: "loop-basics" })).toBe(true);
    });
    expect(postMessage).not.toHaveBeenCalled();
    fireEvent.load(frame);
    expect(postMessage).toHaveBeenCalledWith(
      {
        type: GUIDE_PREVIEW_EVIDENCE_MESSAGE_TYPE,
        kind: "module",
        id: "loop-basics",
      },
      "*",
    );
    expect(Object.keys(postMessage.mock.calls[0][0])).toEqual(["type", "kind", "id"]);
  });

  it("queues the latest command during a srcDoc reload and flushes it only after the new load", () => {
    const ref = createRef<GuidePreviewFrameHandle>();
    const { rerender } = render(
      <GuidePreviewFrame ref={ref} html="<!doctype html><p>First guide</p>" />,
    );
    const frame = screen.getByTitle("Interactive guide preview") as HTMLIFrameElement;
    const postMessage = vi.fn();
    Object.defineProperty(frame, "contentWindow", {
      configurable: true,
      value: { postMessage },
    });
    fireEvent.load(frame);

    rerender(<GuidePreviewFrame ref={ref} html="<!doctype html><p>Updated guide</p>" />);
    const replacementFrame = screen.getByTitle("Interactive guide preview") as HTMLIFrameElement;
    Object.defineProperty(replacementFrame, "contentWindow", {
      configurable: true,
      value: { postMessage },
    });
    act(() => {
      expect(ref.current?.revealEvidence({ kind: "module", id: "loop-basics" })).toBe(true);
      expect(ref.current?.revealEvidence({ kind: "outcome", id: "identify-loop" })).toBe(true);
    });
    expect(postMessage).not.toHaveBeenCalled();

    fireEvent.load(replacementFrame);
    expect(postMessage).toHaveBeenCalledTimes(1);
    expect(postMessage).toHaveBeenCalledWith(
      {
        type: GUIDE_PREVIEW_EVIDENCE_MESSAGE_TYPE,
        kind: "outcome",
        id: "identify-loop",
      },
      "*",
    );
  });

  it("discards a command queued for an older srcDoc generation", () => {
    const ref = createRef<GuidePreviewFrameHandle>();
    const { rerender } = render(
      <GuidePreviewFrame ref={ref} html="<!doctype html><p>First guide</p>" />,
    );
    const firstFrame = screen.getByTitle("Interactive guide preview") as HTMLIFrameElement;
    const postMessage = vi.fn();
    Object.defineProperty(firstFrame, "contentWindow", {
      configurable: true,
      value: { postMessage },
    });

    act(() => {
      expect(ref.current?.revealEvidence({ kind: "module", id: "loop-basics" })).toBe(true);
    });
    rerender(<GuidePreviewFrame ref={ref} html="<!doctype html><p>Replacement guide</p>" />);

    const replacementFrame = screen.getByTitle("Interactive guide preview") as HTMLIFrameElement;
    Object.defineProperty(replacementFrame, "contentWindow", {
      configurable: true,
      value: { postMessage },
    });
    fireEvent.load(replacementFrame);
    expect(postMessage).not.toHaveBeenCalled();
  });

  it("rejects malformed evidence before crossing the iframe boundary", () => {
    const ref = createRef<GuidePreviewFrameHandle>();
    render(<GuidePreviewFrame ref={ref} html="<!doctype html><p>Guide</p>" />);
    const frame = screen.getByTitle("Interactive guide preview") as HTMLIFrameElement;
    const postMessage = vi.fn();
    Object.defineProperty(frame, "contentWindow", {
      configurable: true,
      value: { postMessage },
    });

    expect(ref.current?.revealEvidence({ kind: "module", id: "Not A Guide ID" })).toBe(false);
    expect(
      ref.current?.revealEvidence({ kind: "block", id: "loop-basics" } as never),
    ).toBe(false);
    expect(postMessage).not.toHaveBeenCalled();
  });
});
