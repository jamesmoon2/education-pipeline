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

// T63 (plan decisions 15-17). The frame reports its section with
// {type: "education-pipeline:preview-position", id, initial} and the cockpit
// answers a boot report with {type: "education-pipeline:preview-show", id}.
// The srcDoc sandbox has an opaque origin ("null"), so a message is accepted
// only when event.source is this iframe's contentWindow, and the answer can
// only be addressed with "*".
describe("GuidePreviewFrame preview position bridge", () => {
  const POSITION = "education-pipeline:preview-position";
  const SHOW = "education-pipeline:preview-show";

  function fakeWindow() {
    return { postMessage: vi.fn() };
  }

  function attachWindow(frame: HTMLElement) {
    const contentWindow = fakeWindow();
    Object.defineProperty(frame, "contentWindow", {
      configurable: true,
      value: contentWindow,
    });
    return contentWindow;
  }

  function frameElement() {
    return screen.getByTitle("Interactive guide preview") as HTMLIFrameElement;
  }

  /** A message as the cockpit window receives it from `source`. */
  function receive(source: unknown, data: unknown) {
    const event = new MessageEvent("message", { data, origin: "null" });
    Object.defineProperty(event, "source", { value: source });
    act(() => {
      window.dispatchEvent(event);
    });
  }

  const report = (id: string, initial: boolean) => ({ type: POSITION, id, initial });

  it("reports each non-initial position from its own frame upward, never the boot position", () => {
    const onSectionChange = vi.fn();
    const html = "<!doctype html><p>Guide</p>";
    const { rerender, unmount } = render(
      <GuidePreviewFrame html={html} onSectionChange={onSectionChange} />,
    );
    const frame = frameElement();
    const contentWindow = attachWindow(frame);

    receive(contentWindow, report("feedback-foundations", true));
    expect(onSectionChange).not.toHaveBeenCalled();

    receive(contentWindow, report("garden-decision", false));
    expect(onSectionChange).toHaveBeenCalledTimes(1);
    expect(onSectionChange).toHaveBeenCalledWith("garden-decision");
    expect(contentWindow.postMessage).not.toHaveBeenCalled();

    // The board feeds the reported section back as restoreSection; that
    // re-render must not replace the document the reviewer is reading.
    rerender(
      <GuidePreviewFrame
        html={html}
        restoreSection="garden-decision"
        onSectionChange={onSectionChange}
      />,
    );
    expect(frameElement()).toBe(frame);

    unmount();
    receive(contentWindow, report("recognize-loop-types", false));
    expect(onSectionChange).toHaveBeenCalledTimes(1);
  });

  it("answers a boot report that differs from restoreSection with preview-show to the frame, before load", () => {
    const onSectionChange = vi.fn();
    render(
      <GuidePreviewFrame
        html="<!doctype html><p>Guide</p>"
        restoreSection="garden-decision"
        onSectionChange={onSectionChange}
      />,
    );
    const contentWindow = attachWindow(frameElement());

    // The runtime reports while it boots, which can precede the iframe's
    // load event: the answer must not wait for it.
    receive(contentWindow, report("feedback-foundations", true));
    expect(contentWindow.postMessage).toHaveBeenCalledTimes(1);
    expect(contentWindow.postMessage).toHaveBeenCalledWith(
      { type: SHOW, id: "garden-decision" },
      "*",
    );
    expect(Object.keys(contentWindow.postMessage.mock.calls[0][0]).sort()).toEqual(["id", "type"]);
    expect(onSectionChange).not.toHaveBeenCalled();
  });

  it("posts nothing when the boot report matches restoreSection, when nothing is remembered, or for a non-initial report", () => {
    const onSectionChange = vi.fn();
    const html = "<!doctype html><p>Guide</p>";
    const { rerender } = render(
      <GuidePreviewFrame
        html={html}
        restoreSection="garden-decision"
        onSectionChange={onSectionChange}
      />,
    );
    const contentWindow = attachWindow(frameElement());

    receive(contentWindow, report("garden-decision", true));
    receive(contentWindow, report("recognize-loop-types", false));
    expect(onSectionChange).toHaveBeenCalledWith("recognize-loop-types");

    rerender(<GuidePreviewFrame html={html} restoreSection={null} onSectionChange={onSectionChange} />);
    receive(contentWindow, report("feedback-foundations", true));
    rerender(<GuidePreviewFrame html={html} onSectionChange={onSectionChange} />);
    receive(contentWindow, report("feedback-foundations", true));

    expect(contentWindow.postMessage).not.toHaveBeenCalled();
  });

  it("ignores forged sources and malformed reports, accepting only the exact shape from its own frame", () => {
    const onSectionChange = vi.fn();
    render(
      <GuidePreviewFrame
        html="<!doctype html><p>Guide</p>"
        restoreSection="garden-decision"
        onSectionChange={onSectionChange}
      />,
    );
    // A frame without a window (detached) must not match a null source.
    Object.defineProperty(frameElement(), "contentWindow", { configurable: true, value: null });
    receive(null, report("delays-and-leverage", false));
    receive(null, report("feedback-foundations", true));

    const contentWindow = attachWindow(frameElement());
    const otherFrame = fakeWindow();

    for (const source of [window, null, otherFrame, new MessageChannel().port1, undefined]) {
      receive(source, report("delays-and-leverage", false));
      receive(source, report("feedback-foundations", true));
    }
    for (const data of [
      { ...report("delays-and-leverage", false), extra: true },
      { type: POSITION, id: "delays-and-leverage" },
      { type: POSITION, initial: false },
      { id: "delays-and-leverage", initial: false },
      { type: POSITION, id: "delays-and-leverage", initial: "false" },
      { type: POSITION, id: "delays-and-leverage", initial: 0 },
      { type: POSITION, id: "Not A Guide ID", initial: false },
      { type: POSITION, id: "x".repeat(65), initial: false },
      { type: POSITION, id: 7, initial: false },
      { type: SHOW, id: "delays-and-leverage" },
      { type: SHOW, id: "delays-and-leverage", initial: false },
      { type: "education-pipeline:preview-evidence", id: "delays-and-leverage", initial: false },
      "delays-and-leverage",
      null,
      [POSITION, "delays-and-leverage", false],
    ]) {
      receive(contentWindow, data);
    }
    receive(contentWindow, { ...report("feedback-foundations", true), extra: true });
    receive(contentWindow, { type: POSITION, id: "Not A Guide ID", initial: true });

    expect(onSectionChange).not.toHaveBeenCalled();
    expect(contentWindow.postMessage).not.toHaveBeenCalled();
    expect(otherFrame.postMessage).not.toHaveBeenCalled();

    // The exact shape from this frame's own window is accepted.
    receive(contentWindow, report("delays-and-leverage", false));
    expect(onSectionChange).toHaveBeenCalledTimes(1);
    expect(onSectionChange).toHaveBeenCalledWith("delays-and-leverage");
    receive(contentWindow, report("feedback-foundations", true));
    expect(contentWindow.postMessage).toHaveBeenCalledTimes(1);
    expect(contentWindow.postMessage).toHaveBeenCalledWith(
      { type: SHOW, id: "garden-decision" },
      "*",
    );
  });

  it("after the HTML changes, listens only to the new document and restores into it", () => {
    const onSectionChange = vi.fn();
    const { rerender } = render(
      <GuidePreviewFrame
        html="<!doctype html><p>First guide</p>"
        restoreSection="garden-decision"
        onSectionChange={onSectionChange}
      />,
    );
    const firstFrame = frameElement();
    const firstWindow = attachWindow(firstFrame);

    rerender(
      <GuidePreviewFrame
        html="<!doctype html><p>Updated guide</p>"
        restoreSection="garden-decision"
        onSectionChange={onSectionChange}
      />,
    );
    const replacementFrame = frameElement();
    expect(replacementFrame).not.toBe(firstFrame);
    const replacementWindow = attachWindow(replacementFrame);

    receive(firstWindow, report("recognize-loop-types", false));
    receive(firstWindow, report("feedback-foundations", true));
    expect(onSectionChange).not.toHaveBeenCalled();
    expect(firstWindow.postMessage).not.toHaveBeenCalled();
    expect(replacementWindow.postMessage).not.toHaveBeenCalled();

    receive(replacementWindow, report("feedback-foundations", true));
    expect(replacementWindow.postMessage).toHaveBeenCalledTimes(1);
    expect(replacementWindow.postMessage).toHaveBeenCalledWith(
      { type: SHOW, id: "garden-decision" },
      "*",
    );
    expect(firstWindow.postMessage).not.toHaveBeenCalled();
  });
});
