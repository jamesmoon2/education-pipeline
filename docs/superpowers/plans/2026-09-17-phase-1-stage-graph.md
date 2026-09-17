# Phase 1 — Stage Graph as Data

**Goal:** Turn the hand-unrolled stage dependency chain (draft → qa → factcheck → repair) into one declarative table that stale detection, next-action, approve-time source binding and the settings surface all derive from; quarantine the legacy Markdown mode behind one dispatch site; then cut `runs.py` to a size a single session can hold. Pure refactor: no user-visible behavior change except the one flagged in T11 (factcheck joins the reasoning stages that get a weak-model warning).

**Source:** the 2026-09-17 opportunity map (reviewed at `d85be72`), "Build plan · Phase 1". Threads are numbered as there. Line anchors below are as of `e7ea8ba` (post Phase 0), not the map's.

**Method:** characterization tests first (T10), then every refactor thread must leave those tests green and unchanged. Strict TDD for any behavior change; one subagent writes failing tests, a different one makes them pass; the manager reviews diffs. Every thread ends on the full pytest suite green, plus `npm run build` and `npm run test` when `web/` changed.

**Baseline at open:** pytest 1642 passed / 1 skipped (43 s). `runs.py` 4321 lines, `config.py` 591, `prompts.py` 1579. 22 `_is_guide_v1(` call sites in `runs.py`.

**Audit ledger:** [`../specs/2026-09-17-phase-1-stage-graph-post-milestone-audit.md`](../specs/2026-09-17-phase-1-stage-graph-post-milestone-audit.md)

## Threads

| ID | Thread | Exit criteria | Status |
| --- | --- | --- | --- |
| T10 | Characterization tests | Table-driven tests pin `next_action`, `stage_status.stale` and approve source binding across a run-state matrix for guide-v1 and legacy runs, including the pre-factcheck grandfather fixture; ≥40 cases; no source changes. | - [ ] |
| T11 | Declare the graph | `stage_graph.py` holds one frozen stage table (upstreams, content type, required-in-mode, reasoning flag, prompt-writer key); `config.py` stage tuples and `REASONING_STAGES` derive from it; factcheck now gets the weak-model warning (flagged behavior change, test-covered). | - [ ] |
| T12 | Stale and source binding from the graph | `_stage_upstream_stale`, approve-time source binding and `_stale_stage_rebuild_action` walk the graph; three of four unrollings gone; T10 green and unchanged. | - [ ] |
| T13 | Next action from the graph | The qa/factcheck/repair loop in `_next_action_guide_v1` walks the graph; grandfather rule is one named predicate; fourth unrolling gone; T10 green. | - [ ] |
| T14 | Quarantine legacy Markdown | `_is_guide_v1` branches collapse behind a mode strategy; `runs.py` has one mode dispatch site; new runs still cannot select legacy; legacy tests unchanged; retire-or-keep decision recorded. | - [ ] |
| T15 | Split runs.py, part 1 | Waivers and reports/quality move to `runs_waivers.py` / `runs_reports.py`; pure move, public imports preserved; `runs.py` under 3,000 lines; no test edits beyond import paths. | - [ ] |
| T16 | Split runs.py, part 2 | Personalization/audit and finalize/export move out; repair-prompt gating duplicated in `write_repair_prompt` / `write_module_repair_prompt` merged into one helper; `runs.py` under 2,200 lines; one schema-version constant. | - [ ] |

## Anchors at open

- Four unrollings of the draft → qa → factcheck → repair chain: `runs.py:995-1010` (next action loop + grandfather), `runs.py:1109-1145` (`_stale_stage_rebuild_action`), `runs.py:1315-1335` (approve-time source binding), `runs.py:4027-4071` (`_stage_upstream_stale`).
- Prompt writers bind the same sources by hand: `runs.py:3210, 3283-3284, 3348-3350, 3438-3440`.
- Stage tuples: `config.py:15-32`; `REASONING_STAGES` at `config.py:389` (spec, outline, repair — no factcheck).
- Two next-action engines: `runs.py:902` (legacy) and `runs.py:931` (guide-v1).

## Closeout log

(One line per thread as it lands: what changed, test counts, accepted limitations.)

## Phase closeout

(Filled at the end of the phase.)
