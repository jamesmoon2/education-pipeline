import { describe, expect, it } from "vitest";
import { STAGE_HELP } from "./planHelp";

describe("STAGE_HELP", () => {
  it("explains the factcheck stage and its relationship to QA", () => {
    expect(STAGE_HELP.factcheck).toMatch(/fact/i);
  });

  it("tells repair it fixes both QA and fact-check findings", () => {
    expect(STAGE_HELP.repair).toMatch(/fact-check/i);
  });
});
