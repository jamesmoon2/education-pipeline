# Phase 2 Per-Module Drafting — Post-Milestone Audit Ledger

- **Recorded:** 2026-09-18 (opened with the phase; closed in T28)
- **Source of truth:** thread closeout log in
  [`docs/superpowers/plans/2026-09-18-phase-2-per-module-drafting.md`](../plans/2026-09-18-phase-2-per-module-drafting.md)
- **Purpose:** preserve the decisions and accepted limitations from the
  nine Phase 2 threads for a fresh, independent audit. This ledger does not
  replace that audit.

## Closeout disposition

(Filled in at T28.)

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

- **T20:** the module id namespace is enforced by prompt convention
  (`<module-id>-` prefix) plus an assembly-time collision check; a model
  that ignores the convention gets a named `AssemblyError`, not a silent
  fix. Modules therefore cannot share a section id even when the outline
  would read naturally that way.
- **T20:** parallelism overlaps only module jobs of one batch; two topics
  still cannot run at once. Widening the admission rule is a one-line
  change once cross-topic concurrency has been reasoned about.

## Observations for other owners

- **Status poll cost (T24).** `draft_progress` is computed on every status
  read of a guide run (~0.2 ms per topic after trimming). The Phase 0 T01
  local budget for the 20-topic poll moved from 50 ms to 70 ms; the CI budget
  (200 ms) and the zero-revalidation call-count pins are unchanged. If the
  poll grows again, memoize `draft_progress` on the manifest tail and the
  unit directory mtimes the way the final-validation memo is keyed.
