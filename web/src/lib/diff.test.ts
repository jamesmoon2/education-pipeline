import { describe, expect, it } from "vitest";
import { diffLines } from "./diff";

describe("diffLines", () => {
  it("marks identical inputs as all same", () => {
    expect(diffLines("a\nb\nc", "a\nb\nc")).toEqual([
      { type: "same", text: "a" },
      { type: "same", text: "b" },
      { type: "same", text: "c" },
    ]);
  });

  it("marks added and removed lines around a common core", () => {
    expect(diffLines("keep\nold line\nend", "keep\nnew line\nend")).toEqual([
      { type: "same", text: "keep" },
      { type: "removed", text: "old line" },
      { type: "added", text: "new line" },
      { type: "same", text: "end" },
    ]);
  });

  it("treats an empty left input as all additions", () => {
    expect(diffLines("", "a\nb")).toEqual([
      { type: "added", text: "a" },
      { type: "added", text: "b" },
    ]);
  });

  it("treats an empty right input as all removals", () => {
    expect(diffLines("a\nb", "")).toEqual([
      { type: "removed", text: "a" },
      { type: "removed", text: "b" },
    ]);
  });

  it("returns an empty diff for two empty inputs", () => {
    expect(diffLines("", "")).toEqual([]);
  });

  it("finds the longest common subsequence, not just a prefix match", () => {
    expect(diffLines("x\ncommon\ny", "common")).toEqual([
      { type: "removed", text: "x" },
      { type: "same", text: "common" },
      { type: "removed", text: "y" },
    ]);
  });

  it("keeps prefix and suffix trimming from overlapping", () => {
    expect(diffLines("x\ny", "x\ny\nz")).toEqual([
      { type: "same", text: "x" },
      { type: "same", text: "y" },
      { type: "added", text: "z" },
    ]);
    expect(diffLines("x\ny\nz", "x\nz")).toEqual([
      { type: "same", text: "x" },
      { type: "removed", text: "y" },
      { type: "same", text: "z" },
    ]);
    expect(diffLines("x", "y\nx")).toEqual([
      { type: "added", text: "y" },
      { type: "same", text: "x" },
    ]);
    expect(diffLines("x\nx", "x")).toEqual([
      { type: "same", text: "x" },
      { type: "removed", text: "x" },
    ]);
  });

  // The quadratic LCS must only ever see the changed core: without the
  // prefix/suffix trim these inputs would allocate a matrix in the tens of
  // gigabytes, so completing at all is the assertion.
  it("handles a huge identical document", () => {
    const lines = Array.from({ length: 100_000 }, (_, i) => `line ${i}`);
    const text = lines.join("\n");
    const rows = diffLines(text, text);
    expect(rows).toHaveLength(100_000);
    expect(rows.every((row) => row.type === "same")).toBe(true);
  });

  it("handles a small edit inside a huge document", () => {
    const lines = Array.from({ length: 50_000 }, (_, i) => `line ${i}`);
    const edited = [...lines];
    edited[25_000] = "edited line";
    const rows = diffLines(lines.join("\n"), edited.join("\n"));
    expect(rows).toHaveLength(50_001);
    expect(rows[25_000]).toEqual({ type: "removed", text: "line 25000" });
    expect(rows[25_001]).toEqual({ type: "added", text: "edited line" });
    expect(rows.filter((row) => row.type !== "same")).toHaveLength(2);
  });

  it("falls back to removals-then-additions when the changed core is too large to diff", () => {
    // Fully divergent and far past the LCS cell budget: the exact LCS would
    // allocate ~7GB here. For fully divergent inputs the fallback's output is
    // identical to what the LCS would produce.
    const left = Array.from({ length: 30_000 }, (_, i) => `old ${i}`);
    const right = Array.from({ length: 30_000 }, (_, i) => `new ${i}`);
    const rows = diffLines(left.join("\n"), right.join("\n"));
    expect(rows).toHaveLength(60_000);
    expect(rows.slice(0, 30_000).every((row) => row.type === "removed")).toBe(true);
    expect(rows.slice(30_000).every((row) => row.type === "added")).toBe(true);
  });
});
