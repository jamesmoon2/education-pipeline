# Phase 2 — Per-Module Drafting and Section-Level Repair

**Goal:** Let a run opt into drafting the guide as one frame job plus N parallel module jobs, assembled deterministically into the one `responses/draft.response.json` the rest of the pipeline consumes, with one approval over the assembled guide; and extend scoped repair from module to section. Course length stops being bounded by one model response, a failed draft costs one module, and the worker can run parts in parallel. Nothing auto-approves; runs that do not opt in are unchanged.

**Source:** the 2026-09-17 opportunity map (reviewed at `d85be72`), "Build plan · Phase 2". Threads are numbered as there. Design: [`../specs/2026-09-18-per-module-drafting-design.md`](../specs/2026-09-18-per-module-drafting-design.md). Line anchors are as of `55cfc82` (post Phase 1).

**Method:** strict TDD; one subagent writes the failing tests, a different one makes them pass; the manager reviews diffs. Every thread ends on the full pytest suite green, plus `npm run build` and `npm run test` when `web/` changed; e2e only where the thread says so. Existing tests are extended, never edited to pass.

**Baseline at open:** pytest 1775 passed / 1 skipped (49 s, Python 3.11); `npm run build` clean. `runs.py` 2179 lines, `prompts.py` 1582, `daemon/jobs.py` 901.

**Audit ledger:** [`../specs/2026-09-18-phase-2-per-module-drafting-post-milestone-audit.md`](../specs/2026-09-18-phase-2-per-module-drafting-post-milestone-audit.md)

## Threads

| ID | Thread | Exit criteria | Status |
| --- | --- | --- | --- |
| T20 | Design spec | Spec in the repo's shape, adversarially reviewed against `runs.py` invariants, every line reference verified; this plan lists T21–T28. | - [x] |
| T21 | Frame/module draft prompts and assembly | `compile_guide_v1_frame_draft_prompt`, `compile_guide_v1_module_draft_prompt`; `assemble_guide(frame, modules, module_ids)` in `canonical.py` is byte-deterministic and refuses id collisions, renames, missing or extra stubs; prompt snapshot tests. | - [ ] |
| T22 | RunStore module lifecycle | `draft_strategy` recorded at `create_run`; part paths under `prompts/draft/`, `responses/draft/`; per-part events and staleness; `NextAction.part`; `advance` writes part prompts and performs `assemble`; `ingest_part_response`; characterization cases for every row of the D5 table; resume from workspace alone. | - [ ] |
| T23 | Job fan-out and bounded parallelism | `Job.batch_id` / `Job.part`; batch enqueue; worker pool with `[jobs] parallelism` (default 2, cap 4); batch cancel; one failure leaves siblings running; part ingest and salvage paths; fake-provider tests. | - [ ] |
| T24 | API and CLI surface | `POST /v1/jobs/batch`, batch cancel, part response routes, `draft_parts` and `draft_strategy` in run status, `draft_strategy` on create; `POST /v1/jobs` refuses modular drafts; CLI `create --draft-strategy`, `status` parts, `advance --parts`, `run`, `cancel --batch`; server tests; CLI smoke shows "draft: 3 of 5 modules". | - [ ] |
| T25 | Cockpit: module progress | New Run wizard strategy option; draft step shows per-part state, run batch, rerun, per-part copy/paste; stage viewer marks module boundaries; unit tests; `full-run.spec.ts` covers the fan-out path. | - [ ] |
| T26 | Section-scoped repair, engine | `splice_section`, section repair prompt, `RepairScope` with section, `repair_section` on manifest events, `repair/modules` payload with sections, `advance --repair-section`; splice preserves every other byte. | - [ ] |
| T27 | Section-scoped repair, cockpit | `ModuleRepairControl` becomes a scope picker with findings preselecting scope; unit tests; `blueprints.spec.ts` covers a section repair. | - [ ] |
| T28 | Fixture, docs, closeout | Example regenerates through the modular path with `build_example.py`; docs updated; post-milestone audit written; final gates green. | - [ ] |

## Closeout log

(One line per thread as it lands: what changed, test counts, accepted limitations.)

- **T20** landed: `2026-09-18-per-module-drafting-design.md` (decisions D1–D9, surface table, thread map). Opus adversarial review returned twelve findings; four were blockers and all twelve are folded in: frame stubs cannot pass `parse_guide` (min one section, `parse.py:368`) so the frame gets a lenient shape check; the three "latest draft event" helpers must filter by part; the worker's single-job state becomes a dict and batches persist across reconcile; `frame` is a legal module id so `parts` filters name modules only; there is no create-run route so `draft_strategy` rides the first `advance` body like `blueprint`. Sonnet checked 32 line references, one range off by one, fixed. Owner review is still open on the two questions in the spec (default strategy, where `parallelism` lives); the phase proceeds on the spec's answers.
