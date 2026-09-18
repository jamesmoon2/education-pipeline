# Phase 2 — Per-Module Drafting and Section-Scoped Repair

**Goal:** Lift the one-response ceiling on course length. Draft becomes a skeleton call plus one model call per outline module, run by the daemon at bounded parallelism and assembled deterministically into the unchanged draft response; repair gains a section scope. One draft approval, no new stage, legacy Markdown untouched. Design: [`../specs/2026-09-18-per-module-drafting-design.md`](../specs/2026-09-18-per-module-drafting-design.md).

**Source:** the 2026-09-17 opportunity map (reviewed at `d85be72`), "Build plan · Phase 2". Threads are numbered as there. Line anchors are as of `55cfc82` (post Phase 1).

**Method:** strict TDD; one subagent writes the failing tests and a different one makes them pass; the manager reviews diffs, never transcripts. Every thread ends on the full pytest suite green, plus `npm run build` and `npm run test` when `web/` changed; Playwright only where a thread says so. A thread that grows past ~800 changed lines or 12 files is split.

**Baseline at open:** pytest 1775 passed / 1 skipped (46 s, Python 3.11). `runs.py` 2179 lines, `prompts.py` 1582, `daemon/jobs.py` 901, `guides/canonical.py` (splice_module at :50). vitest and `npm run build` not yet run this phase (recorded at T25).

**Audit ledger:** [`../specs/2026-09-18-phase-2-per-module-drafting-post-milestone-audit.md`](../specs/2026-09-18-phase-2-per-module-drafting-post-milestone-audit.md)

## Threads

| ID | Thread | Exit criteria | Status |
| --- | --- | --- | --- |
| T20 | Design spec | Spec in the repo's shape with the owner decisions settled by default; adversarial review against `runs.py` invariants applied; every cited line reference verified; this plan lists T21–T28. | - [x] |
| T21 | Module draft prompt and assembly | `check_skeleton` in `parse.py`; `compile_guide_v1_skeleton_prompt`, `compile_guide_v1_module_draft_prompt` with snapshot tests (module-prefixed ids, contribution lists); `assemble_guide` in `canonical.py` is byte-deterministic and refuses renames, missing/extra modules, contribution conflicts and cross-module id collisions naming both owners; `splice_module` shares its internals. | - [ ] |
| T22 | RunStore module lifecycle | `draft_unit_paths`, skeleton + module prompts, unit ingest/edit, `assemble_draft`, `draft_progress`, unit manifest events, per-module staleness against the contract file, `next_action` unit arms inside the draft slot plus the 7b outline-changed rebuild arm (checked against the Phase 1 table; any pin change flagged); characterization table for unit states; resume from the workspace alone. | - [ ] |
| T23 | Job fan-out and bounded parallelism | `Job.unit/module_id/batch_id`; `active_unit_for` beside an unchanged `active_for`; worker pool honouring `parallelism` (default 2, cap 4) with the dispatcher-side batch admission rule (wait, never re-queue); batch cancel; per-module salvage; fake-provider tests show bounded concurrency and one failure not blocking the rest. | - [ ] |
| T24 | API and CLI surface | `POST /v1/jobs` batches draft modules (with `modules` subset; job-shaped response plus `batch_id`/`jobs`); unit ingest/edit/assemble routes; `draft_progress` in run status; `run --wait`/`--modules`, `status` prints `draft: k of N modules`; server and CLI tests. | - [ ] |
| T25 | Cockpit: module progress | Board draft stage shows skeleton and per-module state with run/rerun/paste; batch status and cancel; stage viewer with module anchors and per-module change diff; Settings `parallelism`; `continueRun` handles batches; vitest green; `full-run.spec.ts` covers the unit paste path. | - [ ] |
| T26 | Section-scoped repair, engine | `RepairScope`, `write_scoped_repair_prompt`, section repair prompt, `splice_section` byte-preserving siblings, findings→section mapping in `repair_modules_payload`, `repair_section` in manifest/advance/CLI. | - [ ] |
| T27 | Section-scoped repair, cockpit | `ModuleRepairControl` is a module+section scope picker with findings preselecting scope; vitest; `blueprints.spec.ts` covers a section repair. | - [ ] |
| T28 | Fixture, docs, closeout | `build_example.py` drives the unit path; `draft.guide.json` and `repair.guide.json` canonicalized together and the export regenerated if bytes change; interactive-guides and install docs updated; post-milestone audit written with accepted limitations. | - [ ] |

## Order and parallelism between threads

T21 and T26 touch disjoint behaviour (module assembly vs section splice) and share only `canonical.py` and `prompts.py`; they run in parallel worktrees and merge in that order. T22 → T23 → T24 are sequential (each consumes the previous API). T25 and T27 are both cockpit and run in parallel after T24. T28 closes.

## Anchors at open

- Whole-guide draft prompt: `runs.py:1480` (`write_draft_prompt`), `runs.py:1503` (`_guide_v1_draft_artifact`), `prompts.py:856` (`compile_guide_v1_draft_prompt`), `prompts.py:530` (output contract lines).
- Module repair: `runs.py:1776` (`write_module_repair_prompt`), `runs.py:1110` (`repair_scope`), `runs.py:1124` (`_spliced_scoped_repair`), `prompts.py:1188` (module repair prompt), `prompts.py:1260` (path-prefix filter), `guides/canonical.py:50` (`splice_module`).
- Ingest/approve: `runs.py:1162` (`ingest_response`), `runs.py:1204` (`edit_response`), `runs.py:1051` (`approve_stage`), `runs.py:1837` (`_write_prompt`), `runs.py:2050` (`_append_event_locked`).
- Contract: `guides/contract.py:321` (`extract_outline_contract`), `:331` (`build_guide_contract`, sorted keys).
- Daemon: `daemon/jobs.py:45` (`Job`), `:367` (`JobRunner.execute`), `:423` (ingest call), `:703` (`Worker`), `:729-745` (enqueue guard), `:862` (`effective_timeout_seconds`); `daemon/server.py:88-152` (`enqueue_stage`), `:600-611` (job routes); `daemon/read_api.py:389` (`run_status_payload`), `:545-600` (`repair_modules_payload`).
- Cockpit: `web/src/components/PrimaryAction.tsx:84-220`, `web/src/lib/continueRun.ts:96-184`, `web/src/components/ModuleRepairControl.tsx`, `web/src/pages/RunBoardPage.tsx:161-170`.

## Closeout log

(One line per thread as it lands: what changed, test counts, accepted limitations.)

- **T20** landed: design spec (538 lines), this plan, and the ledger skeleton. Two code maps (engine; daemon/CLI/cockpit) preceded the draft; an Opus adversarial pass then found three blocking flaws and seven must/should-changes, all applied: a skeleton cannot pass `parse_guide` (cardinality, coverage and interaction rules), so it gets a dedicated `check_skeleton`; the unit `next_action` arms live inside the draft slot of the unbound-stages loop and yield to an existing response file, which keeps the whole-guide drop and the characterization pins intact; per-module staleness hashes against the immutable contract file, with a separate, explicitly scoped rebuild arm (7b) for outline re-approval before draft approval; `active_for` keeps matching module jobs; batch admission is dispatcher-side and waits rather than re-queues; the batch enqueue response stays job-shaped; the example fixture's two committed guide responses are canonicalized together. A Sonnet pass verified all 59 cited line references. Suite untouched at 1775 passed / 1 skipped.
