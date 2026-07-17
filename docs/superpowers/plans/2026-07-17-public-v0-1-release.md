# Public `v0.1` Release Implementation Plan

> Executed on branch `claude/v0-1-p2-item-pph1vo`. Steps use checkbox
> (`- [x]`) syntax for tracking. Docs-only waves need no new tests; the two
> code-adjacent waves (example project, troubleshooting reference) land
> test-first. The Wave Log below records closure.

**Goal:** Complete the executable share of PRD "P2 — Public `v0.1` release":
README rewrite, polished synthetic example + exported guide, CI install
verification across OSes, the four gap-closing user docs, the provenance
review, and the owner release checklist.

**Spec:**
`docs/superpowers/specs/2026-07-17-public-v0-1-release-design.md` — its
Non-goals and Design decisions are binding.

## Global constraints

- No engine/schema/runtime/prompt/validation changes; the canonical fixture
  and its pinned SHA-256 stay untouched.
- Runtime stays standard-library only; no new dev dependencies.
- Example content is fully synthetic; no real learner data. The example must
  not use root-gitignored directory names (`runs/`, `topics/`, `profiles/`).
- Docs stay domain-neutral per `docs/extraction-manifest.md`.

## Waves

### Wave 1 — Example project (`examples/feedback-loops/`)

- [x] Failing test first: `tests/test_example_project.py` — committed export
      bytes match a regeneration, gate open, zero findings, no private
      profile values in HTML, all six interaction types present.
- [x] Example sources: `topic.toml`, `profile.toml`,
      `responses/{spec.md,outline.md,draft.guide.json,qa.md,repair.guide.json}`,
      example `README.md`.
- [x] `scripts/build_example.py` — drives a temp workspace end to end and
      writes `export/guide.html` + `export/guide.report.json`.
- [x] Generate the export; test green.

### Wave 2 — User docs

- [x] `docs/install-and-first-course.md`
- [x] `docs/providers.md`
- [x] `docs/privacy-and-local-trust.md`
- [x] `docs/troubleshooting.md` + failing-first test
      `tests/test_troubleshooting_doc.py` (every `errors.py` catalog code is
      documented).
- [x] `docs/backup-and-migration.md`

### Wave 3 — README rewrite

- [x] Restructure `README.md` around install → first course → example;
      link out to the new docs; keep the reference depth in `docs/`.

### Wave 4 — CI install verification

- [x] `packaging-smoke` becomes an `{ubuntu-latest, macos-latest,
      windows-latest}` matrix with OS-portable steps.

### Wave 5 — Provenance review + release checklist + closeout

- [x] `docs/provenance-review.md` (dependencies, assets, fonts, copied
      material, with dispositions).
- [x] `docs/release-checklist.md` (owner actions: per-OS sign-off, demo,
      tag; open decisions).
- [x] PRD §10 P2 status updated to record what landed and what remains
      owner action.
- [x] Full suite gate: `python3 -m pytest`, `npm test`, `npm run build`.

## Wave Log

- **Wave 1 — Example project.** 2026-07-17, commit `6fe71c7` (milestone
  spec/plan baseline in `4fee1d1`). Five pinning tests failing-first, then
  green; regeneration verified byte-identical twice, and the documented
  manual CLI walkthrough reproduces the shipped `guide.html` exactly.
- **Wave 2 — User docs.** 2026-07-17, commit `32984a5`. The
  `tests/test_troubleshooting_doc.py` sync tests landed failing-first;
  both green with all 21 catalog codes documented verbatim.
- **Wave 3 — README rewrite.** 2026-07-17, commit `7a9e164`. Release-gate
  CLI reference and sidecar report details moved into
  `docs/interactive-guides.md` instead of being dropped.
- **Wave 4 — CI install verification.** 2026-07-17, commit `bfcd63c`.
  OS-matrix packaging smoke; full step sequence executed locally on Linux
  against the built wheel (venv install, CLI smoke, headless `ui`, index
  probe, `daemon stop`). Windows daemon gap documented in-workflow and in
  the release checklist.
- **Wave 5 — Provenance, checklist, closeout.** 2026-07-17 (this commit).
  Provenance review with no blocking findings; owner release checklist;
  PRD §10 P2 status updated. Closeout gate: pytest 1193 passed / 1
  skipped, vitest 261 passed, `npm run build` clean. Playwright e2e was
  not rerun: no engine, daemon, or cockpit source changed on this branch
  (docs, examples, tests, and CI config only).
