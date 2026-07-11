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
});
