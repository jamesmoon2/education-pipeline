import { describe, expect, it } from "vitest";
import {
  costCompletenessLabel,
  costCompletenessTitle,
  costSourceLabel,
  formatUsd,
} from "./cost";

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

describe("costCompletenessLabel", () => {
  it("names the number of unpriced jobs in a partial subtotal", () => {
    expect(costCompletenessLabel(2)).toBe("partial: 2 jobs unpriced");
  });

  it("uses the singular for a single unpriced job", () => {
    expect(costCompletenessLabel(1)).toBe("partial: 1 job unpriced");
  });

  it("still reads as partial when the unpriced count is unknown", () => {
    // A payload may report completeness without a usable count; the figure is
    // still a subtotal and must not read as a total.
    expect(costCompletenessLabel(0)).toBe("partial: some jobs unpriced");
  });
});

describe("costCompletenessTitle", () => {
  it("explains that the named jobs have no known cost", () => {
    expect(costCompletenessTitle(2)).toBe(
      "Known-cost subtotal: 2 jobs have no known cost and are not counted.",
    );
  });

  it("uses the singular for a single unpriced job", () => {
    expect(costCompletenessTitle(1)).toBe(
      "Known-cost subtotal: 1 job has no known cost and is not counted.",
    );
  });

  it("falls back to an unquantified explanation when the count is unknown", () => {
    expect(costCompletenessTitle(0)).toBe(
      "Known-cost subtotal: some jobs have no known cost and are not counted.",
    );
  });
});
