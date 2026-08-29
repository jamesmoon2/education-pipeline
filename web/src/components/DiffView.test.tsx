import { render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../lib/diff", async () => {
  const actual = await vi.importActual<typeof import("../lib/diff")>("../lib/diff");
  return { ...actual, diffLines: vi.fn(actual.diffLines) };
});

import DiffView from "./DiffView";
import { diffLines } from "../lib/diff";

beforeEach(() => {
  vi.mocked(diffLines).mockClear();
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
});
