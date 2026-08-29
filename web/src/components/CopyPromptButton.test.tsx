import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import CopyPromptButton from "./CopyPromptButton";

const FAILURE_MESSAGE =
  "Copy failed — select the prompt text and copy it manually.";

function stubClipboard() {
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.assign(navigator, { clipboard: { writeText } });
  return writeText;
}

beforeEach(() => {
  vi.clearAllMocks();
  delete (navigator as { clipboard?: unknown }).clipboard;
});

describe("CopyPromptButton", () => {
  it("copies the text from getText and shows Copied ✓ as a status", async () => {
    const writeText = stubClipboard();
    render(<CopyPromptButton getText={() => Promise.resolve("raw prompt bytes")} />);
    await userEvent.click(screen.getByRole("button", { name: "Copy prompt" }));
    expect(writeText).toHaveBeenCalledWith("raw prompt bytes");
    expect(await screen.findByRole("status")).toHaveTextContent("Copied ✓");
  });

  it("clears the copied feedback after a few seconds", async () => {
    vi.useFakeTimers();
    try {
      stubClipboard();
      render(<CopyPromptButton getText={() => Promise.resolve("p")} />);
      fireEvent.click(screen.getByRole("button", { name: "Copy prompt" }));
      await act(async () => {
        await Promise.resolve();
        await Promise.resolve();
        await Promise.resolve();
      });
      expect(screen.getByRole("status")).toHaveTextContent("Copied ✓");
      act(() => {
        vi.advanceTimersByTime(5000);
      });
      expect(screen.queryByRole("status")).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it("shows an alert when the clipboard write is rejected", async () => {
    const writeText = vi.fn().mockRejectedValue(new Error("denied"));
    Object.assign(navigator, { clipboard: { writeText } });
    render(<CopyPromptButton getText={() => Promise.resolve("p")} />);
    await userEvent.click(screen.getByRole("button", { name: "Copy prompt" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(FAILURE_MESSAGE);
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("fails gracefully when navigator.clipboard is unavailable", async () => {
    render(<CopyPromptButton getText={() => Promise.resolve("p")} />);
    await userEvent.click(screen.getByRole("button", { name: "Copy prompt" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(FAILURE_MESSAGE);
  });

  it("shows the alert when getText itself rejects", async () => {
    const writeText = stubClipboard();
    render(
      <CopyPromptButton getText={() => Promise.reject(new Error("no prompt"))} />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Copy prompt" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(FAILURE_MESSAGE);
    expect(writeText).not.toHaveBeenCalled();
  });

  it("recovers: a successful copy after a failure replaces the alert", async () => {
    const writeText = vi
      .fn()
      .mockRejectedValueOnce(new Error("denied"))
      .mockResolvedValueOnce(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    render(<CopyPromptButton getText={() => Promise.resolve("p")} />);
    await userEvent.click(screen.getByRole("button", { name: "Copy prompt" }));
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Copy prompt" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Copied ✓");
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
