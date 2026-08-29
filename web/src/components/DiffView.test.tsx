import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../lib/diff", async () => {
  const actual = await vi.importActual<typeof import("../lib/diff")>("../lib/diff");
  return { ...actual, diffLines: vi.fn(actual.diffLines) };
});

import DiffView from "./DiffView";
import { diffLines } from "../lib/diff";

let realDiffLines: typeof diffLines;

beforeAll(async () => {
  realDiffLines = (await vi.importActual<typeof import("../lib/diff")>("../lib/diff")).diffLines;
});

beforeEach(() => {
  vi.mocked(diffLines).mockReset().mockImplementation((a, b) => realDiffLines(a, b));
});

describe("DiffView", () => {
  it("does not recompute the diff when a re-render carries equal content", () => {
    const { rerender } = render(<DiffView a={"a\nb"} b={"a\nc"} />);
    expect(diffLines).toHaveBeenCalledTimes(1);

    // Polling replaces the stage payload with fresh-but-equal strings every
    // few seconds; the memo must key on value, not identity.
    rerender(<DiffView a={["a", "b"].join("\n")} b={["a", "c"].join("\n")} />);
    expect(diffLines).toHaveBeenCalledTimes(1);

    rerender(<DiffView a={"a\nb"} b={"a\nd"} />);
    expect(diffLines).toHaveBeenCalledTimes(2);
  });

  it("skips its render body when a parent re-renders with unchanged props", async () => {
    // The diff result is already memoized on the string values, so its call
    // count cannot report a wasted render. Count the body's row reads instead.
    let rowReads = 0;
    vi.mocked(diffLines).mockImplementation(() => [
      {
        type: "same",
        get text() {
          rowReads += 1;
          return "unchanged";
        },
      },
    ]);

    function Harness({ a, b }: { a: string; b: string }) {
      const [bumps, setBumps] = useState(0);
      return (
        <>
          <button onClick={() => setBumps(bumps + 1)}>bump {bumps}</button>
          <DiffView a={a} b={b} />
        </>
      );
    }

    render(<Harness a={"a\nb"} b={"a\nc"} />);
    expect(screen.getByText("unchanged")).toBeInTheDocument();
    expect(rowReads).toBe(1);

    await userEvent.click(screen.getByRole("button"));
    expect(rowReads).toBe(1);
  });
});
