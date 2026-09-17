# Phase 1 Stage Graph — Post-Milestone Audit Ledger

- **Recorded:** 2026-09-17
- **Source of truth:** thread closeout log in
  [`docs/superpowers/plans/2026-09-17-phase-1-stage-graph.md`](../plans/2026-09-17-phase-1-stage-graph.md)
- **Purpose:** preserve the decisions and accepted limitations from the seven
  Phase 1 threads for a fresh, independent audit. This ledger does not
  replace that audit.

## Closeout disposition

(Filled as threads land.)

### T10

Characterization only; nothing under `education_pipeline/` changed. The
tests pin observed behaviour, including three pre-existing quirks that the
refactor threads must preserve rather than fix:

- `report_state` keys freshness on the semantic guide hash while
  `StageStatus.stale` for qa/factcheck/repair keys on raw approved bytes, so a
  whitespace-only repair re-approval can leave the chain stale while the final
  report still reads current.
- `_stale_stage_rebuild_action` advertises `save_response` when the prompt is
  already current, even though the superseded response is still on disk
  (there is no `approve` arm).
- `run_status` lists a `factcheck` entry for legacy Markdown runs even though
  `write_factcheck_prompt` refuses them; legacy stages never report stale.

Not pinned by decision: the personalization trace-integrity branch in
`_next_action_guide_v1` (covered by the personalization suite) and the
unreachable label filters in `_prompt_bound_source_hashes`.

## Decisions that departed from the plan text

(None yet.)

## Accepted limitations

(None yet.)
