# Phase 4 Mastery in the Runtime — Post-Milestone Audit Ledger

- **Recorded:** 2026-09-19 (opened and closed with the phase)
- **Source of truth:** thread closeout log in
  [`docs/superpowers/plans/2026-09-19-phase-4-mastery.md`](../plans/2026-09-19-phase-4-mastery.md)
- **Purpose:** preserve the decisions and accepted limitations from the
  three Phase 4 threads for a fresh, independent audit. This ledger does not
  replace that audit.

## Closeout disposition

Three threads (T40–T42 from the opportunity map), each merged into the phase
branch only after the full pytest suite and the guide Playwright specs were
green on the result; T40 and T42 ran in parallel worktrees, T41 after T40.
Every thread was strict TDD with a Sonnet test writer and a separate
implementer (Opus for T40 and T41, Sonnet for T42; the manager reviewed every
runtime diff). Nine mutations were tried: eight were caught by the red sets
and one (T41: listing missed blocks under on-track outcomes) is behaviourally
equivalent to the shipped code, so its stronger form was tried and caught
instead. Baseline at open was pytest 2200 / 1 skipped, vitest 627, Playwright
89 counted with the guide specs at 59; at close 2201 / 1, 627, 126 counted
with the guide specs at 96, on Python 3.11.

Manager corrections to red sets: two stale version pins T40's writer missed
(the download file version and the boot error string), the T40 count text
(below), and T42's last-section ArrowRight guard after the merge (below).
No thread exceeded the ~800-changed-line guideline once tests and the
regenerated example export are set aside (T40 is +321 in `runtime.js`).

## Decisions that departed from the plan text

### Decision 4 (refined at T40 review): counts read "correct of answered"

The green implementation printed "{correct} of {total} correct", under which
one right answer and one unanswered check read as one wrong answer. The
plan's wording ("of answered") was restored and the open count is named
separately ("1 of 1 correct, 1 not yet answered").

### T42: the last-section ArrowRight guard

Written against a runtime without a results page, the guard pinned "no-op".
After the T40 merge, Next on the last section opens the results page, so the
guard now pins that and the no-op on the results page itself.

### Decision 1: results, not mastery

The opportunity map titles this phase "Mastery, not just completion". The
runtime spec (§7) had promised the guide "does not claim mastery", and one
knowledge check per outcome is thin evidence for such a claim. The phase
keeps the map's substance (per-outcome roll-up, a summary page, a header
indicator, a review queue) and changes the vocabulary: the guide reports
*results* the learner produced, stored only in their browser, and says so.
Spec §7 is reworded rather than contradicted.

### Decision 5: store version

The map asked for a "progress-store version bump with migration". The
`localStorage` record has no version integer of its own (its key carries the
guide schema major and the content hash, and `validateState` is additive), so
the bump lands where a version exists: the progress *file* format goes to 2
with a version-1 reader, and the runtime asset version goes to 1.1. No stored
record is rewritten in place.

## Accepted limitations

- **T40:** the `none` outcome status (no scorable block links to the outcome)
  is implemented but no fixture exercises it; the header denominator excludes
  such outcomes. A stored `lastSection` of `results` is dropped on restore.
  The results-page print rule uses `!important` to beat the `.is-current`
  display rule.
- **T41:** the review panel recomputes on section entry only; a correct
  answer given from a later section clears the results page at once but the
  panel only on the next entry. No scenario is retryable today (`data-retry`
  is emitted for knowledge checks only); the runtime's one `isRetryable`
  rule would honour it without change. The panel is a complementary landmark
  nested inside a section (axe: moderate, not blocking). The mutation
  "render missed lists for on-track outcomes" is behaviourally equivalent to
  the shipped code and therefore unpinnable; the stronger mutation is pinned.
- **T42:** `/` focuses the first navigation link at every viewport; the
  fallback to the drawer toggle when the navigation is collapsed is not built.
  The four keyboard guards that passed before any listener existed pin the
  absence of behaviour rather than the listener, and the mutation pass is what
  showed the listener is covered.

## Open for the owner

- Whether the results page should ever print (this phase: never).
- Whether a per-section review threshold of two sections is right for long
  courses; it is one constant in the runtime.
