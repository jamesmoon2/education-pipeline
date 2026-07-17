# Public `v0.1` Release Implementation Plan

> Executed on branch `claude/v0-1-p2-item-pph1vo`. Steps use checkbox
> (`- [ ]`) syntax for tracking. Docs-only waves need no new tests; the two
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

- [ ] Failing test first: `tests/test_example_project.py` — committed export
      bytes match a regeneration, gate open, zero findings, no private
      profile values in HTML, all six interaction types present.
- [ ] Example sources: `topic.toml`, `profile.toml`,
      `responses/{spec.md,outline.md,draft.guide.json,qa.md,repair.guide.json}`,
      example `README.md`.
- [ ] `scripts/build_example.py` — drives a temp workspace end to end and
      writes `export/guide.html` + `export/guide.report.json`.
- [ ] Generate the export; test green.

### Wave 2 — User docs

- [ ] `docs/install-and-first-course.md`
- [ ] `docs/providers.md`
- [ ] `docs/privacy-and-local-trust.md`
- [ ] `docs/troubleshooting.md` + failing-first test
      `tests/test_troubleshooting_doc.py` (every `errors.py` catalog code is
      documented).
- [ ] `docs/backup-and-migration.md`

### Wave 3 — README rewrite

- [ ] Restructure `README.md` around install → first course → example;
      link out to the new docs; keep the reference depth in `docs/`.

### Wave 4 — CI install verification

- [ ] `packaging-smoke` becomes an `{ubuntu-latest, macos-latest,
      windows-latest}` matrix with OS-portable steps.

### Wave 5 — Provenance review + release checklist + closeout

- [ ] `docs/provenance-review.md` (dependencies, assets, fonts, copied
      material, with dispositions).
- [ ] `docs/release-checklist.md` (owner actions: per-OS sign-off, demo,
      tag; open decisions).
- [ ] PRD §10 P2 status updated to record what landed and what remains
      owner action.
- [ ] Full suite gate: `python3 -m pytest`, `npm test`, `npm run build`.

## Wave Log

(append one entry per closed wave: date, commit, suite counts)
