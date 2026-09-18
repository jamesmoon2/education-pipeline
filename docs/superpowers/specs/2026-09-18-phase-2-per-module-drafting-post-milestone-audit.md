# Phase 2 Per-Module Drafting — Post-Milestone Audit Ledger

- **Recorded:** 2026-09-18 (opened with the phase; closed in T28)
- **Source of truth:** thread closeout log in
  [`docs/superpowers/plans/2026-09-18-phase-2-per-module-drafting.md`](../plans/2026-09-18-phase-2-per-module-drafting.md)
- **Purpose:** preserve the decisions and accepted limitations from the
  nine Phase 2 threads for a fresh, independent audit. This ledger does not
  replace that audit.

## Closeout disposition

Nine threads, each merged into the phase branch only after the full pytest
suite was green on the merged result (plus `npm run build`, vitest and the
relevant Playwright spec whenever `web/` changed). Every behaviour thread
was strict TDD with a Sonnet test writer and a separate implementer (Opus
for engine, daemon and prompt work; Sonnet for the cockpit and the fixture),
and every implementer ran a short mutation pass: of fourteen mutations tried
across T21–T24, nine were caught by the red set and five survived and were
pinned before the thread merged (T21 contribution order; T23 admission in
`enqueue` and re-queue-to-tail; T24 assemble without the active-job guard;
T26 `module_level_findings` only type-asserted). Baseline at open was pytest
1775 passed / 1 skipped, vitest 554, Playwright 87; at close 2012 / 1,
596, 88 on Python 3.11.

Three threads (T21, T22, T24) exceeded the ~800-changed-line guideline;
T21 because prompt, check and assembly are one contract, T22 because the
lifecycle is one mixin with a 59-case red set, T24 because it is the whole
API/CLI surface for one feature. None was split; each is reviewable by the
red commit followed by the green commit.

Design-review findings applied before any code (T20): a skeleton cannot pass
`parse_guide`, so it has its own structural check; the unit next-action arms
live inside the draft slot and yield to an existing response file; module
staleness hashes the immutable contract file, not the live outline; batch
admission is evaluated in the worker loop, never under the workspace lock;
`active_for` keeps matching module jobs so every existing guard still holds;
the batch enqueue response stays job-shaped.

## Decisions that departed from the plan text

### T20: a skeleton call precedes the module fan-out

The opportunity map described draft as "N module jobs against the same
contract, spliced deterministically". The guide's course header, outcome
goal links, glossary and sources are model-authored prose that no
deterministic step can produce from the contracts, so the design adds one
small skeleton call (the guide without section content) before the N module
calls. N+1 calls, one approval, no new stage. See the design's decision 2.

### T20: the whole-guide prompt keeps being written

Kept as the single-call alternative for short courses and manual users, and
because it leaves every existing draft test, the example builder and legacy
runs untouched. A `draft_mode` setting was considered and deferred. See the
design's decision 5.

### T20: outline re-approval after draft gets a rebuild arm (7b)

Pre-existing gap, not introduced here: draft has no stage-graph sources, so
re-approving the outline after the draft prompt exists neither marks draft
stale nor rewrites the immutable `inputs/guide-contract.json`. Hashing
modules against the live outline (the map's wording) would therefore
live-lock: every module stale, nothing able to clear it. The design hashes
against the contract file instead and adds one explicit arm, scoped to an
unapproved draft, that offers `write_prompt` to rebuild the contract and
units. An approved draft is left alone. If T22 finds a Phase 1
characterization pin that contradicts the arm, the pin changes and the PR
flags it, as T11 did for the factcheck warning.

## Accepted limitations

- **T21:** `check_skeleton` skips `link.unknown_internal_target` (link
  targets live in sections that do not exist yet); the merged guide's strict
  parse still catches a dangling link. The module draft prompt does not run
  `check_skeleton` itself; `write_module_draft_prompts` is that gate.
- **T22:** response events spell `response_sha256` explicitly rather than
  through the `files` mechanism; `DraftProgress.total` counts orphaned units
  while the "k of N" detail counts contract modules; the assembly-failure
  state stays `save_response` because fixing a module is a human step.
  (The third item recorded here — "the 7b rebuild leaves orphaned unit
  responses on disk" — was a defect, not a limitation; see the PR #39 review
  section below.)
- **T23:** unit jobs write stage provenance for `draft`, so the last module
  to finish is the last writer; `parallelism` is read once at daemon start;
  `worker_parallelism` falls back to 2 on an unloadable plan (the error
  still surfaces per job); the concurrency bound is the thread count, so it
  depends on `start()` creating exactly `parallelism` threads.
- **T24:** the 20-topic poll's local budget in
  `tests/test_final_validation_cache.py` widened 50 → 70 ms (see
  Observations); batch order comes from `metadata.batch_index` because
  same-second job ids do not sort.
- **T25:** the stage-level paste loop still writes the whole-stage response
  (the whole-guide bypass), so the skeleton has its own paste control in the
  panel; the per-module "changes since last run" diff is deferred —
  `response.previous.json` is written but not yet read by the viewer; draft
  content is plain JSON text, so module anchors live on the nav only.
- **T26:** `stage_content`'s `repair_scope` was module-only until T27
  widened it; section-scope QA-item matching reuses the module prompt's
  substring heuristic widened with the section id and title.
- **T27:** the pending-scope notice is one plain string so the text matcher
  can read it; Playwright in this image needs the
  `PLAYWRIGHT_CHROMIUM_EXECUTABLE` override `playwright.config.ts` documents.
- **T28:** the example README's manual-CLI walkthrough is illustrative prose,
  not test-covered; `draft.guide.json` was deleted rather than kept as a
  second, driftable copy of the assembled draft.
- **T20:** the module id namespace is enforced by prompt convention
  (`<module-id>-` prefix) plus an assembly-time collision check; a model
  that ignores the convention gets a named `AssemblyError`, not a silent
  fix. Modules therefore cannot share a section id even when the outline
  would read naturally that way.
- **T20:** parallelism overlaps only module jobs of one batch; two topics
  still cannot run at once. Widening the admission rule is a one-line
  change once cross-topic concurrency has been reasoned about.

## PR #39 review (post-merge)

An automated review of the phase PR raised eight findings against the engine
and daemon. All eight reproduced; each is fixed under its own red-then-green
commit prefixed `review: `. Consequences worth carrying forward:

- **The 7b rebuild now orphans the unit responses** (finding 1). Decision 7b
  always said the rebuild "moves existing unit responses aside as orphaned";
  the implementation left them in place, so the rebuilt skeleton still read
  `response_ingested` and a skeleton written against the old contract could
  be assembled against the new one. `_orphan_draft_units` moves the skeleton
  response and the whole `draft/modules` tree into `draft/orphaned/<ts>/`
  (never deleted) and records `draft_units_orphaned`. Consequence: the
  `orphaned` unit state is no longer reachable *through the rebuild arm* —
  it now describes only a module directory that outlives its contract entry
  without one. The contrary characterization pin was updated and renamed.
- **A second engine lock** (finding 2). "Write a unit response, then attempt
  assembly" is serialized by a process-wide reentrant lock keyed by
  `(workspace root, topic id)`, because the worker pool overlaps the module
  jobs of one batch and the manifest lock only covers each event append.
  Lock order is unit lock → manifest lock, never the reverse; cross-process
  concurrency stays the workspace file lock's job.
- **A refused automatic assembly is recorded** (finding 3). `ingest_draft_unit`
  carries its `force` into the assembly it triggers, and a refusal (superseded
  response, no force) appends `draft_assembly_failed` so it surfaces as
  `draft_progress.assembled.error`. Cost: one manifest event per unforced
  ingest against a superseded draft.
- **Stale modules are recompiled at enqueue** (finding 4), inside the same
  locked section, and their jobs carry `force=True`. A stale module whose
  skeleton no longer passes `check_skeleton` now fails the enqueue with the
  skeleton's own diagnostics instead of queueing an obsolete prompt.
- **Pool admission is FIFO among waiters** (finding 5): with nothing running
  only the head of the waiting deque starts; a batch's members may still join
  a running sibling whatever their position.
- **Unit salvage** (finding 6). The status payload gains `failed_unit_outputs`
  per stage beside the unchanged `failed_outputs`, and `salvage_stage_output`
  promotes a unit failure through `ingest_draft_unit`. Known ambiguity: a
  module whose id is literally `skeleton` would parse as the skeleton unit in
  a salvage file name.
- **`modules: []`** is a 400 at the request parser and a CLI usage error
  (finding 7), not an `IndexError` 500.
- **Contribution owners are tracked per kind** (finding 8): a glossary id
  re-used as a source id is an `AssemblyError` naming both owners rather than
  a bare `StopIteration` out of `assemble_guide`.

## Observations for other owners

- **Retired open questions (T20 §11).** 1: the skeleton has no approval
  gate, and the cockpit lets a user read and re-paste it before "Run
  modules". 2: `parallelism` is workspace-only (`update_run_plan` rejects
  it). 3: the whole-guide prompt is still written. 4: a module response
  replaces its stub wholesale, id fixed.

- **Status poll cost (T24).** `draft_progress` is computed on every status
  read of a guide run (~0.2 ms per topic after trimming). The Phase 0 T01
  local budget for the 20-topic poll moved from 50 ms to 70 ms; the CI budget
  (200 ms) and the zero-revalidation call-count pins are unchanged. If the
  poll grows again, memoize `draft_progress` on the manifest tail and the
  unit directory mtimes the way the final-validation memo is keyed.
