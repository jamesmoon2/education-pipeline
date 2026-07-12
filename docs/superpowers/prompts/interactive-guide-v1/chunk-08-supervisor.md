# Supervisor Prompt — Interactive Guide v1, Chunk 08

You are the supervisor agent for **Chunk 08: Wave 7 release-quality milestone
closeout** in `/Users/jmooney/Documents/education-pipeline`.

Complete only this chunk autonomously. Do not begin post-milestone work.

## Accepted base and frozen contracts

The accepted Wave 6 integration head is `f52fc97`, following `ed0aa28`. Confirm
it is an ancestor of `HEAD`, inspect the live worktree, and preserve unrelated
changes. Do not reset, pull, switch branches, rewrite history, push, or open a
pull request without separate authorization.

The canonical fixture remains
`tests/fixtures/guides/feedback-loops.guide.json`, with normalized SHA-256:

```text
99fde906c6bb1231c33c4d5d9f1adab011a1f4313c03c574eb7aa27cdbe70b07
```

Freeze all accepted public guide APIs, canonicalization and fixture order,
runtime assets/data-role behavior, prompt bytes, content-contract lifecycle,
validation/finalization/export provenance, Wave 5 API response shapes and
preview sandbox, and Wave 6 findings/waiver/recovery behavior. This includes
the additive waiver read endpoint, current/stale/waived separation, exact-hash
waivers, source navigation, replacement confirmation/provenance, separate
finalize/export controls, mixed-run compatibility, and the full 37-test browser
acceptance suite.

Stop at the smallest safe state and report an exact blocker if release work
would require changing a frozen contract.

## Authoritative files to reopen

Read the PRD; milestone/runtime/validation specs; implementation plan section
12 and Chunk 07 completion record; package metadata; GitHub workflows; guide
runtime package-data declarations; build/test scripts; README and user docs;
all accessibility/browser tests; accepted Wave 6 commits; and repository-local
instructions. Trust live code over this prompt.

## Authorized Wave 7 scope

1. **CI:** keep the Python 3.11/3.12 and artifact-leak coverage; add frontend
   `npm ci`, unit tests, production build, supported Playwright browser setup,
   and the full guide/mixed-run acceptance suite. If assets are generated, CI
   must detect drift.
2. **Packaging:** build and inspect the wheel for runtime JavaScript/CSS and
   required schema/package assets; install into a clean environment without
   relying on the source checkout; export the fixture; prove the exported HTML
   works from `file:` with no daemon and Node is not required after install.
3. **Accessibility acceptance:** run automated axe on the full fixture and
   record a dated manual keyboard pass for navigation and all interactions,
   one supported screen-reader smoke pass, 320 CSS-pixel reflow, dark theme,
   reduced motion, and print inspection under `docs/testing/`. Do not claim a
   manual check that was not actually performed; record an exact human-required
   blocker if necessary.
4. **Documentation:** update README/user documentation for guide-v1 workflow,
   compatibility, content contracts/artifacts, findings and waivers, preview
   isolation, local progress/reset, export/privacy boundaries, and recovery.
5. **Milestone closeout:** run every required gate, update the milestone/plan
   only when evidence supports completion, and record exact versions, commands,
   counts, package inspection, accessibility evidence, deviations, and risks.

## Prohibited work

Do not change the fixture/hash, guide schema or runtime behavior, validation
rules, prompt contracts, lifecycle/API shapes, findings/waiver semantics,
provider behavior, or product features. Do not begin a new milestone, hosted
publishing, sync, collaboration, accounts, analytics, new interactions, or
post-milestone refactors. Do not invoke paid providers or install Python runtime
dependencies.

## Ownership and recovery

The supervisor owns CI, package metadata, shared docs, acceptance evidence, and
integration. Delegate only bounded non-overlapping inspection or leaf-doc tasks
after contracts are fixed. Treat workflows, package configuration, and shared
acceptance records as hot files. Fix ordinary in-scope failures; if sandbox
policy denies sockets/browser/temp installation, rerun the identical command
with required permission and classify it as environmental only when it passes.

Use explicit paths for staging, preserve unrelated changes, and create clean
logical commits without amending Waves 1–6.

## Required verification

At minimum:

```bash
git diff --check
python3 -m pytest
cd web && npm ci && npm test && npm run build && npm run e2e
python3 -m build
```

Inspect wheel contents, install the wheel in a clean environment, run a fixture
finalize/export smoke test from outside the checkout, open the export from
`file:`, and rerun the normalized fixture hash. Verify frozen sources and prompt
snapshots remain untouched. Record exact evidence rather than inferred success.

## Closeout and next prompt

After every Wave 7 criterion genuinely passes, set Chunk 08 and the milestone
to `Complete`; record all accepted commits, verification counts, wheel/package
contents, clean-install export evidence, accessibility/manual results,
documentation changes, fixture hash, deviations, and remaining risks or
`None`.

Then create the complete next supervisor prompt at:

```text
docs/superpowers/prompts/interactive-guide-v1/chunk-09-post-milestone-supervisor.md
```

It must freeze the completed milestone, authorize only an independent audit and
next-milestone proposal, require evidence-grounded findings and explicit clean
surface callouts, prohibit silent fixes or implementation of the proposal,
define ownership/recovery/verification/commit rules, and stop without beginning
the next milestone.
