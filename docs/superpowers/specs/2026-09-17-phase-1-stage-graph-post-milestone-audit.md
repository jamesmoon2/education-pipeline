# Phase 1 Stage Graph — Post-Milestone Audit Ledger

- **Recorded:** 2026-09-17
- **Source of truth:** thread closeout log in
  [`docs/superpowers/plans/2026-09-17-phase-1-stage-graph.md`](../plans/2026-09-17-phase-1-stage-graph.md)
- **Purpose:** preserve the decisions and accepted limitations from the seven
  Phase 1 threads for a fresh, independent audit. This ledger does not
  replace that audit.

## Closeout disposition

Seven threads, each merged into the phase branch only after the full pytest
suite was green on the merged result. T10 wrote the net (88 characterization
cases, no source changes) before any refactor; every later thread left those
cases untouched and green, and three threads added observed-behaviour pins
where mutation testing showed the net had a hole (T12: 2, T13: 2, T10 review:
gap fill). Baseline at open was pytest 1642 passed / 1 skipped; at close 1775
passed / 1 skipped on Python 3.11.

Pure-move threads (T14, T15, T16) exceeded the plan's ~800-changed-line
guideline by their nature (T15 alone deleted 1366 lines from `runs.py`); the
guideline exists to keep a thread reviewable, and a verbatim move with the
suite as the oracle is reviewable by diffstat, so they were not split.

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
- **T15:** moved report methods import `parse_guide`, `normalize_guide`,
  `validate_guide`, `compute_static_checks`, `load_runtime_assets`,
  `personalization_trace_is_fresh`, `_write_bytes_atomic`,
  `QUALITY_REPORT_SCHEMA_VERSION`, `_relative_to` and `StageStatus` lazily
  from `runs` because tests monkeypatch those names on
  `education_pipeline.runs`. The names stay bound in `runs.py` for that
  reason alone. Resolving this means repointing the patches at the mixin
  modules (test-only edits), which T16 is allowed to do.

## Observations for other owners

- **Python 3.12 timing budget (Phase 0 T01's test).** Under 3.12 the 20-topic
  poll measures ~55 ms on `origin/main` and ~56 ms on this branch against the
  50 ms local budget in `tests/test_final_validation_cache.py`; CI sets `CI`
  and gets the 200 ms budget, so CI is green. Not a Phase 1 regression (the
  delta between main and this branch is within run-to-run noise); the local
  budget is simply tuned for 3.11. Either widen the local budget for 3.12 or
  profile `pathlib` use on the poll path.
- **Windows lock test is nondeterministic (Phase 0 T03's test).** On PR #38's
  first CI run, `test (windows-latest, py3.12)` failed once in
  `tests/test_cli_cross_process_guard.py::test_two_threads_racing_for_the_lock_share_one_hold`
  with `depths == [1, 0]`; the rerun on the same commit passed, as did the
  same job on `main` at `e7ea8ba` and on the Phase 0 branch. Phase 1 does not
  touch `workspace_lock.py` or that test. Read from Linux, no path in
  `_acquire`/`_release`/`workspace_lock_depth` yields a depth of 0 for a
  thread that is inside `workspace_lock` while `_HELD` is keyed by a stable
  string: the loser always sees the winner's holder under `_STATE_LOCK` and
  joins it at depth 2. A 0 therefore points at the key itself
  (`os.path.realpath` of a file being created and byte-locked by the other
  thread on NTFS) or at `msvcrt.locking` admitting a second handle in the
  same process. Neither can be checked without a Windows box; the T03 owner
  should capture `key` alongside `depth` in that test so the next failure
  says which.
