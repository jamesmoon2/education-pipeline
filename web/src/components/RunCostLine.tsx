import type { CostSource } from "../lib/cost";
import { costSourceLabel, formatUsd } from "../lib/cost";

export interface RunCostLineProps {
  usd: number | null;
  source: CostSource;
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
 */
export default function RunCostLine({ usd, source }: RunCostLineProps) {
  if (usd === null) return null;
  const label = costSourceLabel(source);
  return (
    <p className="muted">
      Cost {formatUsd(usd)}
      {label ? <> ({label})</> : null}
    </p>
  );
}
