import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import JsonTreeView from "./JsonTreeView";

/**
 * The tree has no injectable collaborator to spy on, so the probe rides on the
 * value itself: walking an object reads its enumerable properties exactly once
 * per render of the tree.
 */
function probeValue(reads: { count: number }) {
  return {
    get modules() {
      reads.count += 1;
      return ["intro"];
    },
  };
}

/** A parent that re-renders on its own state, like a polled page around it. */
function Harness({ value }: { value: unknown }) {
  const [bumps, setBumps] = useState(0);
  return (
    <>
      <button onClick={() => setBumps(bumps + 1)}>bump {bumps}</button>
      <JsonTreeView value={value} />
    </>
  );
}

describe("JsonTreeView", () => {
  it("skips its render when a parent re-renders with the same value", async () => {
    const reads = { count: 0 };
    const value = probeValue(reads);
    render(<Harness value={value} />);
    expect(screen.getByText("modules")).toBeInTheDocument();
    expect(reads.count).toBe(1);

    await userEvent.click(screen.getByRole("button"));
    expect(reads.count).toBe(1);
  });

  it("re-renders for a new value, including a fresh-but-equal object graph", () => {
    // StageContentView re-parses only when the stage text changes, so a new
    // object here means new content: freshness must win over the memo.
    const first = { count: 0 };
    const second = { count: 0 };
    const { rerender } = render(<JsonTreeView value={probeValue(first)} />);
    expect(first.count).toBe(1);

    rerender(<JsonTreeView value={probeValue(second)} />);
    expect(second.count).toBe(1);

    rerender(<JsonTreeView value={{ modules: ["outro"] }} />);
    expect(screen.getByText('"outro"')).toBeInTheDocument();
  });
});
