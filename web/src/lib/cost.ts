// Cost formatting helpers shared by the run board, stage viewer, topic
// library, and settings surfaces (thread T07). Pure, presentation-only:
// callers own deciding *whether* a cost is known (null vs. a number) --
// these two functions only decide how a known value or its source reads.

/** Where a cost figure came from, per the daemon's cost block
 *  (education_pipeline/cost.py / read_api.py, thread T06). */
export type CostSource = "provider" | "estimate" | "mixed" | null;

/** Formats a USD amount to two decimal places with a leading "$", or "—"
 *  when the amount is unknown (null). Never call this to decide *whether*
 *  to show a cost -- callers gate on `usd !== null` themselves so a $0.00
 *  run (e.g. every job on that stage happened to cost nothing) still
 *  renders as a real, known amount rather than being hidden like null. */
export function formatUsd(usd: number | null): string {
  if (usd === null) return "\u2014";
  return `$${usd.toFixed(2)}`;
}

const SOURCE_LABELS: Record<string, string> = {
  provider: "provider-reported",
  estimate: "estimated",
  mixed: "mixed",
};

/** Maps a cost block's `source` to the human label the cockpit shows next
 *  to the amount: "provider-reported", "estimated", or "mixed". Returns
 *  "" for null (no known source) -- callers already gate display on the
 *  amount being non-null, so this only needs to cover the three real
 *  sources plus a harmless fallback. Typed on `string | null` rather than
 *  `CostSource` so a source read straight off a payload (the settings
 *  page's per-stage observation) needs no cast; an unrecognised one is
 *  shown verbatim. */
export function costSourceLabel(source: string | null): string {
  if (!source) return "";
  return SOURCE_LABELS[source] ?? source;
}

/** The parenthetical that marks a cost as a known-cost subtotal: some of the
 *  jobs it covers have no price, so the figure is a floor, not a total.
 *  `unpriced` is the count of those jobs (education_pipeline/cost.py's
 *  `unpriced_jobs`); a count of 0 means the payload reported incompleteness
 *  without a usable number, which still must not read as a total. */
export function costCompletenessLabel(unpriced: number): string {
  if (!Number.isFinite(unpriced) || unpriced < 1) return "partial: some jobs unpriced";
  return `partial: ${unpriced} job${unpriced === 1 ? "" : "s"} unpriced`;
}

/** The longer sentence behind a "(partial)" marker's tooltip, for the compact
 *  surfaces (the library's total and per-row cells) that have no room to spell
 *  the gap out inline. Same `unpriced` convention as costCompletenessLabel. */
export function costCompletenessTitle(unpriced: number): string {
  if (!Number.isFinite(unpriced) || unpriced < 1) {
    return "Known-cost subtotal: some jobs have no known cost and are not counted.";
  }
  const jobs =
    unpriced === 1
      ? "1 job has no known cost and is not counted"
      : `${unpriced} jobs have no known cost and are not counted`;
  return `Known-cost subtotal: ${jobs}.`;
}
