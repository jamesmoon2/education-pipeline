import { describe, expect, it } from "vitest";
import { costSourceLabel, formatUsd } from "./cost";

describe("formatUsd", () => {
  it("formats a known amount to two decimal places with a leading dollar sign", () => {
    // Mirrors tests/test_run_cost.py's CLI assertion: 0.4231 -> "$0.42".
    expect(formatUsd(0.4231)).toBe("$0.42");
  });

  it("pads a whole-dollar amount to two decimal places", () => {
    expect(formatUsd(1)).toBe("$1.00");
  });

  it("renders an em dash for a null (unknown) amount", () => {
    expect(formatUsd(null)).toBe("—");
  });

  it("formats a zero cost as a real known amount, not the null placeholder", () => {
    expect(formatUsd(0)).toBe("$0.00");
  });
});

describe("costSourceLabel", () => {
  it('labels "provider" as provider-reported', () => {
    expect(costSourceLabel("provider")).toBe("provider-reported");
  });

  it('labels "estimate" as estimated', () => {
    expect(costSourceLabel("estimate")).toBe("estimated");
  });

  it('labels "mixed" as mixed', () => {
    expect(costSourceLabel("mixed")).toBe("mixed");
  });

  it("returns an empty label for a null (unknown) source", () => {
    expect(costSourceLabel(null)).toBe("");
  });
});
