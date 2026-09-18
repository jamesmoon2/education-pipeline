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

### T11: factcheck joins the reasoning stages

The factcheck design doc (`2026-07-22-adversarial-factcheck-stage-design.md`,
open question 2) had deferred this with "default leave unchanged". The
opportunity map read the omission as drift and the Phase 1 plan made it T11's
one behaviour change, so it was applied and the design doc's open question is
marked resolved. Effect: a below-`strong` model planned for factcheck now
produces the same weak-model warning as spec, outline and repair. Nothing else
in the plan changes.

### T14: legacy Markdown stays, behind the strategy

The plan left "retire in a later release or keep behind the strategy" open.
Decision: keep. `LegacyMarkdownMode` in `run_modes.py` is the only place the
legacy bodies live; nothing new can select it (`create_run` defaults to the
guide contract and neither the CLI nor the daemon exposes the legacy kind),
but workspaces created before the guide format still resume. Retiring it
means a migration story for those workspaces, which is a release decision
for the owner, not a refactor thread's.

## Accepted limitations

- **T11:** `StageSpec.content == "guide"` reads as unconditional but means
  "guide JSON on interactive-guide runs, Markdown on legacy runs"; the mode
  conditional stays in `RunStore.stage_paths`. T14 may fold it into the mode
  strategy. `supported_stages()` selects every row today (its predicate only
  matters once a row is neither required in a mode nor optional).
- **T11:** `docs/superpowers/specs/2026-07-11-next-milestone-proposal.md:69`
  still lists the warning as covering spec/outline/repair; left as a dated
  historical proposal.
- **T14:** `run_modes.py` imports a few `runs.py` names lazily inside method
  bodies (`NextAction`, `_FINAL_SOURCE_STAGE`, `_write_text`) because `runs`
  imports `run_modes` at module scope. T15/T16 can move those names to a leaf
  module and drop the lazy imports. `REQUIRED_STAGES` stays imported in
  `runs.py` only as a re-export that two test files rely on.
