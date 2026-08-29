import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../lib/markdown", async () => {
  const actual = await vi.importActual<typeof import("../lib/markdown")>("../lib/markdown");
  return { ...actual, parseMarkdown: vi.fn(actual.parseMarkdown) };
});

import MarkdownView from "./MarkdownView";
import { parseMarkdown } from "../lib/markdown";

let realParseMarkdown: typeof parseMarkdown;

beforeAll(async () => {
  realParseMarkdown = (
    await vi.importActual<typeof import("../lib/markdown")>("../lib/markdown")
  ).parseMarkdown;
});

beforeEach(() => {
  vi.mocked(parseMarkdown).mockReset().mockImplementation((text) => realParseMarkdown(text));
});

/** A parent that re-renders on its own state, like a polled page around it. */
function Harness({ markdown }: { markdown: string }) {
  const [bumps, setBumps] = useState(0);
  return (
    <>
      <button onClick={() => setBumps(bumps + 1)}>bump {bumps}</button>
      <MarkdownView markdown={markdown} />
    </>
  );
}

describe("MarkdownView", () => {
  it("does not re-parse when a parent re-renders with unchanged markdown", async () => {
    const { rerender } = render(<Harness markdown={"# Title\n\nBody."} />);
    expect(screen.getByRole("heading", { name: "Title" })).toBeInTheDocument();
    expect(parseMarkdown).toHaveBeenCalledTimes(1);

    // A parent re-render alone must not reach this leaf.
    await userEvent.click(screen.getByRole("button"));
    expect(parseMarkdown).toHaveBeenCalledTimes(1);

    // Nor must a fresh-but-equal string — every poll tick rebuilds the payload.
    rerender(<Harness markdown={["# Title", "", "Body."].join("\n")} />);
    expect(parseMarkdown).toHaveBeenCalledTimes(1);
  });

  it("still re-renders when the markdown changes", () => {
    const { rerender } = render(<MarkdownView markdown="# Title" />);
    rerender(<MarkdownView markdown="# Changed" />);
    expect(parseMarkdown).toHaveBeenCalledTimes(2);
    expect(screen.getByRole("heading", { name: "Changed" })).toBeInTheDocument();
  });
});
