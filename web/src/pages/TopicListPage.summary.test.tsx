import { describe, expect, it } from "vitest";
import type { TopicSummary } from "../api/types";
import { summarizeLibrary } from "./TopicListPage";

function topic(
  id: string,
  run: { finalized: boolean; action: "approve" | "save_response" } | null,
  archived = false,
): TopicSummary {
  return {
    id,
    title: null,
    error: null,
    archived,
    last_activity: null,
    profile_id: null,
    completion: null,
    run: run
      ? {
          topic_id: id,
          finalized: run.finalized,
          content_contract: { kind: "interactive_guide" },
          next_action: { topic_id: id, stage: "qa", action: run.action, detail: "" },
        }
      : null,
  } as TopicSummary;
}

describe("summarizeLibrary", () => {
  it("counts live courses by where they stand and ignores archived ones", () => {
    const summary = summarizeLibrary([
      topic("a", null),
      topic("b", { finalized: false, action: "approve" }),
      topic("c", { finalized: false, action: "save_response" }),
      topic("d", { finalized: true, action: "approve" }),
      topic("e", { finalized: false, action: "approve" }, true),
    ]);
    expect(summary).toEqual({ courses: 4, inProgress: 2, readyToReview: 2, finalized: 1 });
  });

  it("is all zeros for an empty library", () => {
    expect(summarizeLibrary([])).toEqual({
      courses: 0,
      inProgress: 0,
      readyToReview: 0,
      finalized: 0,
    });
  });
});
