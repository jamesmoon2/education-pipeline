# Blueprint-Driven Pedagogy — Post-Milestone Audit Ledger

- **Recorded:** 2026-07-16
- **Source of truth:** Wave 0–5 closeout records in
  [`docs/superpowers/plans/2026-07-16-blueprint-pedagogy.md`](../plans/2026-07-16-blueprint-pedagogy.md)
- **Purpose:** preserve accepted or deferred closeout items for a fresh,
  independent post-milestone audit. This ledger does not replace that audit.

## Closeout disposition

Every wave landed test-first and closed on green focused suites; the milestone
closed on the full four-suite gate (pytest 1068, vitest 221, Playwright e2e
including four new blueprint acceptance specs, clean `npm run build`). The
`blueprint is None` byte-identity regression landed before any prompt change,
and the canonical acceptance fixture was **not** regenerated: the guide schema
and canonicalization are untouched, the fixture already declares
`conceptual-foundations`, and its pinned normalized SHA-256
(`99fde906c6bb1231c33c4d5d9f1adab011a1f4313c03c574eb7aa27cdbe70b07`) still
matches, which the Wave Log records in lieu of a fixture diff.

## Accepted limitations

### Scoped-repair approval state is not byte-derivable in the stage view

After a module-scoped repair is approved, the stage's response file (the
module fragment) intentionally differs from the approved file (the merged
whole guide), so the cockpit's generic response-vs-approved comparison keeps
offering the Approve button, exactly as it does for an edited response.
Re-approving re-runs the deterministic splice against the same recorded base
draft and is refused when the draft drifted, so no incorrect state can be
approved; the pending artifact is explicitly labeled as scoped to its module.

**Revisit when:** the stage view is reworked to derive approval state from
run-status events rather than byte comparison, or scoped repairs gain a
dedicated response panel.

### Report freshness does not track topic-field edits

`report_state` derives freshness from the approved source and profile
snapshot hashes. Editing a topic's `time_budget_minutes` (or `blueprint`
field) after validation does not stale an existing report; the new value is
picked up on the next validation run. Calibration findings are nonblocking
warnings/info (and the blueprint mismatch gate recomputes fresh at
finalize/export), so no gate decision can be made against stale calibration
inputs.

**Revisit when:** topic editing becomes a first-class cockpit operation or
report freshness gains additional input bindings.

### Module-level regeneration granularity

Per the owner decision on the spec's open question 2, regeneration v1 is
module-scoped ("one weak lesson"), not section- or block-scoped. The splice
requires a stable module id and global element-id uniqueness; inner section
and block ids may legitimately change within the regenerated module.

**Revisit when:** real usage shows repairs routinely target a single section
of a large module.

## Recommended independent audit

A fresh post-milestone task should review the complete blueprint-pedagogy
commit set and this ledger read-only. It should confirm the
`blueprint is None` byte-identity boundary, the contract echo/superset
refusal path, recommendation determinism against the pinned keyword table,
calibration constants and presence-only finding messages (no profile values
in any report surface), splice refusal semantics (renames, collisions,
out-of-contract references, drifted base draft), sidecar reproducibility with
calibration findings present, and the merge-friendliness constraint that all
daemon/wizard additions stayed additive in the base branch's current style
for the parallel first-run milestone. It should report only concrete,
reproducible findings and should not reopen the accepted limitations unless
their stated revisit conditions are now true.
