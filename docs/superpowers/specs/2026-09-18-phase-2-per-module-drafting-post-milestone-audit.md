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

## Accepted limitations

(One entry per thread as it lands.)

## Observations for other owners

(Filled in as found.)
