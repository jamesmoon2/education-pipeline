import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ShortcutsProvider, { usePageShortcut } from "./ShortcutsProvider";

// T61 decision 8: one document-level keydown listener, installed by
// ShortcutsProvider; pages register their page-scoped handlers (`n` and `a`)
// through usePageShortcut. The provider fetches the library itself for `r`.
vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return {
    ApiRequestError: actual.ApiRequestError,
    getTopics: vi.fn(() => new Promise(() => {})),
  };
});

function Probe({
  onApprove,
  onNextStage,
}: {
  onApprove: (() => void) | null;
  onNextStage: (() => void) | null;
}) {
  usePageShortcut("focus-approve", onApprove);
  usePageShortcut("open-next-stage", onNextStage);
  return (
    <div>
      <label>
        Notes
        <textarea />
      </label>
      {/* A page control that handles its own keys first. */}
      <div role="group" aria-label="Own keys" tabIndex={0} onKeyDown={(e) => e.preventDefault()}>
        own keys
      </div>
    </div>
  );
}

function renderProbe(props: {
  onApprove: (() => void) | null;
  onNextStage: (() => void) | null;
}) {
  const ui = (p: typeof props) => (
    <MemoryRouter>
      <ShortcutsProvider>
        <Probe {...p} />
      </ShortcutsProvider>
    </MemoryRouter>
  );
  const view = render(ui(props));
  return { ...view, rerenderWith: (next: typeof props) => view.rerender(ui(next)) };
}

/** Dispatch a keydown on <body>; true when nothing called preventDefault. */
function keyDown(key: string, init: KeyboardEventInit = {}): boolean {
  return fireEvent.keyDown(document.body, { key, ...init });
}

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  (document.activeElement as HTMLElement | null)?.blur();
});

describe("ShortcutsProvider + usePageShortcut", () => {
  it("routes `a` to the page's focus-approve handler and claims the key", () => {
    const onApprove = vi.fn();
    renderProbe({ onApprove, onNextStage: vi.fn() });

    expect(keyDown("a")).toBe(false); // preventDefault was called
    expect(onApprove).toHaveBeenCalledTimes(1);
  });

  it("routes `n` to the page's open-next-stage handler", () => {
    const onNextStage = vi.fn();
    const onApprove = vi.fn();
    renderProbe({ onApprove, onNextStage });

    expect(keyDown("n")).toBe(false);
    expect(onNextStage).toHaveBeenCalledTimes(1);
    expect(onApprove).not.toHaveBeenCalled();
  });

  it("leaves `n` and `a` unclaimed when the page registers no handler", () => {
    renderProbe({ onApprove: null, onNextStage: null });

    expect(keyDown("a")).toBe(true);
    expect(keyDown("n")).toBe(true);
  });

  it("forgets a page's handlers when the page unmounts", () => {
    const onApprove = vi.fn();
    const onNextStage = vi.fn();
    const view = renderProbe({ onApprove, onNextStage });
    view.rerender(
      <MemoryRouter>
        <ShortcutsProvider>
          <p>another page</p>
        </ShortcutsProvider>
      </MemoryRouter>,
    );

    expect(keyDown("a")).toBe(true);
    expect(keyDown("n")).toBe(true);
    expect(onApprove).not.toHaveBeenCalled();
    expect(onNextStage).not.toHaveBeenCalled();
  });

  it("calls the latest handler a page passed, not a stale one", () => {
    const first = vi.fn();
    const second = vi.fn();
    const view = renderProbe({ onApprove: first, onNextStage: null });
    view.rerenderWith({ onApprove: second, onNextStage: null });

    keyDown("a");
    expect(first).not.toHaveBeenCalled();
    expect(second).toHaveBeenCalledTimes(1);
  });

  it("keeps Ctrl/Meta/Alt + a for the browser (select all stays select all)", () => {
    const onApprove = vi.fn();
    renderProbe({ onApprove, onNextStage: vi.fn() });

    expect(keyDown("a", { ctrlKey: true })).toBe(true);
    expect(keyDown("a", { metaKey: true })).toBe(true);
    expect(keyDown("a", { altKey: true })).toBe(true);
    expect(onApprove).not.toHaveBeenCalled();
  });

  it("ignores keys typed into an editable field, which still receives them", async () => {
    const user = userEvent.setup();
    const onApprove = vi.fn();
    const onNextStage = vi.fn();
    renderProbe({ onApprove, onNextStage });
    const notes = screen.getByLabelText("Notes");

    await user.click(notes);
    await user.keyboard("an?/r");

    expect(notes).toHaveValue("an?/r");
    expect(onApprove).not.toHaveBeenCalled();
    expect(onNextStage).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("ignores a key a page control already handled (defaultPrevented)", () => {
    const onApprove = vi.fn();
    renderProbe({ onApprove, onNextStage: vi.fn() });

    fireEvent.keyDown(screen.getByRole("group", { name: "Own keys" }), { key: "a" });

    expect(onApprove).not.toHaveBeenCalled();
  });

  it("calls nothing while the switch is stored off", () => {
    localStorage.setItem("ep.shortcuts", "off");
    const onApprove = vi.fn();
    const onNextStage = vi.fn();
    renderProbe({ onApprove, onNextStage });

    expect(keyDown("a")).toBe(true);
    expect(keyDown("n")).toBe(true);
    expect(onApprove).not.toHaveBeenCalled();
    expect(onNextStage).not.toHaveBeenCalled();
  });

  it("opens the shortcuts overlay on ? without any page registering anything", () => {
    renderProbe({ onApprove: null, onNextStage: null });

    keyDown("?");

    expect(screen.getByRole("dialog", { name: "Keyboard shortcuts" })).toBeInTheDocument();
  });
});
