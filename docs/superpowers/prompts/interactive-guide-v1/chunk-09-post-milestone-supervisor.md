# Supervisor Prompt — Interactive Guide v1, Chunk 09 (Post-milestone)

You are the supervisor agent for **Chunk 09: independent post-milestone audit
and next-milestone proposal** in
`/Users/jmooney/Documents/education-pipeline`.

Complete only this chunk autonomously. You produce an audit and a proposal;
you do not fix, refactor, or build anything.

## Accepted base and frozen milestone

The interactive-guide-v1 milestone is complete. The accepted feature head is
`434d11e`, with the Chunk 08 closeout committed on top of it. Confirm
`434d11e` is an ancestor of `HEAD`, inspect the live worktree, and preserve
unrelated changes. Do not reset, pull, switch branches, rewrite history, push,
or open a pull request without separate authorization.

The canonical fixture remains
`tests/fixtures/guides/feedback-loops.guide.json`, normalized SHA-256:

```text
99fde906c6bb1231c33c4d5d9f1adab011a1f4313c03c574eb7aa27cdbe70b07
```

**The entire delivered milestone is frozen for this chunk**: guide schema and
parser, canonicalization and the fixture, validation rules and waiver
semantics, runtime assets and data-role behavior (including the `e2cb6f4`
skip-link fix), prompt bytes, content-contract lifecycle, finalize/export
provenance, all `/v1` API response shapes, preview sandboxing, cockpit
behavior (including the `20d9a74` action toolbars), CI workflows, package
metadata, and the 38-test browser acceptance suite. If the audit finds a
defect, you record it with evidence — you do not fix it, however small.

## Authoritative context to reopen

Read the PRD (`docs/product-requirements.md`, noting the delivered-P0 status
and the explicit partials); the implementation plan §12 Chunk 08 status and
completion records, including the owner sign-off that **waived, without
execution**, the screen-reader smoke pass, formal manual keyboard checklist,
real print dialog, and real-device reflow; the acceptance record
`docs/testing/2026-07-11-interactive-guide-v1-acceptance.md`; the four
milestone specs; `docs/interactive-guides.md`; the CI workflows; and the git
history from `f52fc97` through the closeout. Trust live code over any record.

## Authorized scope

1. **Independent audit.** Re-verify the milestone's definition of done against
   live code, not the records: run the full verification suite, rebuild and
   re-inspect the wheel, re-run the clean-install `file:` export smoke, and
   re-derive the fixture hash. Audit for gaps the delivery team was too close
   to see: security posture (daemon auth, preview isolation, export content),
   accessibility debt (start from the waived manual items and the recorded
   Shift+Tab focus-start observation), test blind spots, packaging or
   documentation drift, and record/reality mismatches. Every finding must
   cite exact evidence (file:line, command output, or measured behavior) and
   state its severity and expected impact. **Explicitly call out surfaces you
   audited and found clean** — absence of findings must be a stated
   conclusion, never an omission.
2. **Next-milestone proposal.** Propose exactly one next milestone with
   scope, non-goals, staged waves, acceptance gates, and risks, grounded in
   the PRD's priorities and the audit's findings. Candidates to weigh, with
   the owner's session feedback as evidence: "P0 — Finish model-plan
   configuration" (the PRD's largest remaining gap), the deferred
   blueprint/course-brief depth, and the observed cockpit discoverability
   gaps (empty-board first impression, preview reachable only inside the
   response editor, unexplained read-only state on finalized runs). Recommend
   one primary; justify the ordering.

Write the audit to
`docs/superpowers/specs/2026-07-12-interactive-guide-v1-post-milestone-audit.md`
and the proposal to
`docs/superpowers/specs/2026-07-12-next-milestone-proposal.md` (adjust the
date prefix to the actual date).

## Prohibited work

Do not fix, patch, or silently correct anything you find — including typos,
test flakes, or one-line bugs; findings are recorded, not repaired. Do not
implement any part of the proposal. Do not change the fixture, schema,
runtime, validation, prompts, lifecycle, API, CI, packaging, or cockpit. Do
not begin the next milestone, invoke paid providers, or install Python
runtime dependencies.

## Ownership and recovery

The supervisor owns both deliverable documents and all commits. Delegate only
bounded, non-overlapping read-only inspection tasks with self-contained specs
and exact paths; review every delegated result against live code before
accepting it. Record only evidence you actually produced (exact commands,
versions, counts); if a command fails only due to sandbox policy (sockets,
browser, temp installs), rerun it with the required permission and classify
it environmental only when it passes. If any audit step would require
modifying a frozen surface, stop at the smallest safe state and report the
exact blocker.

## Required verification

At minimum, and recorded with exact counts:

```bash
git diff --check
python3 -m pytest
cd web && npm ci && npm test && npm run build && npm run e2e
python3 -m build   # isolated venv; inspect wheel contents
```

Plus: clean-venv wheel install, out-of-checkout fixture export, `file:` smoke,
and normalized fixture hash re-derivation. Verify the worktree still matches
the closeout records before starting and report any drift as a finding.

## Closeout

When both documents are complete and every verification result is recorded,
commit them as clean logical commits (do not amend milestone history, do not
push or open a PR), and stop. Do not begin the proposed milestone; its
execution requires a separate authorization and its own supervisor prompt.
