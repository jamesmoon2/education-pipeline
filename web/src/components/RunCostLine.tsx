import type { CostSource } from "../lib/cost";
import { costCompletenessLabel, costSourceLabel, formatUsd } from "../lib/cost";

export interface RunCostLineProps {
  usd: number | null;
  source: CostSource;
  // How many of the jobs behind this figure carry no usable price, and (run
  // totals only) the payload's own completeness flag. Both optional: a payload
  // that reports neither is taken as complete.
  unpricedJobs?: number;
  complete?: boolean;
}

/**
 * One muted "Cost $X.XX (provenance)" line, shared by the run board and the
 * stage viewer (thread T07).
 *
 * Renders nothing at all when the amount is unknown: a run whose stages were
 * all pasted by hand has no job records to sum, and a blank where a figure
 * would go reads as "this cost nothing" rather than "nobody counted". A known
 * $0.00 is a real amount and does render.
 *
 * The provenance is always spelled out, because an estimate and a
 * provider-reported figure are not the same claim — see PRICE_TABLE in
 * education_pipeline/cost.py, whose prices are deliberately placeholders.
 *
 * A figure that leaves jobs unpriced says so too: it is the sum over the jobs
 * whose cost is known, and reading it as the whole spend would understate it.
 */
export default function RunCostLine({ usd, source, unpricedJobs, complete }: RunCostLineProps) {
  if (usd === null) return null;
  const partial = complete === false || (unpricedJobs ?? 0) > 0;
  const parts = [
    costSourceLabel(source),
    partial ? costCompletenessLabel(unpricedJobs ?? 0) : "",
  ].filter(Boolean);
  return (
    <p className="muted">
      Cost {formatUsd(usd)}
      {parts.length > 0 ? <> ({parts.join(", ")})</> : null}
    </p>
  );
}
