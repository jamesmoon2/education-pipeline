# Public `v0.1` Release — Milestone Design

- **Date:** 2026-07-17
- **Status:** In execution on branch `claude/v0-1-p2-item-pph1vo`.
- **Grounding:** PRD [`docs/product-requirements.md`](../../product-requirements.md)
  §10 "P2 — Public `v0.1` release" and §11 release criteria. All P0/P1 roadmap
  milestones are delivered; this is the final roadmap item before tagging
  `v0.1`.

## 1. Goal

Turn the delivered product into a releasable public project: a new user can
discover the project, install it from documented instructions, complete the
documented example workflow, and trust the privacy/local-trust story — and the
owner has everything needed to sign off, record the demo, and tag `v0.1`.

## 2. Scope (the PRD's six P2 bullets, mapped to deliverables)

1. **README rewrite** — restructure `README.md` around installation and the
   first successful course; move reference-depth material into `docs/`.
2. **Polished synthetic example** — `examples/feedback-loops/`: a complete,
   synthetic, personalized guide-v1 project (topic, learner profile, every
   stage response) plus its exported offline `guide.html` and
   `guide.report.json`, regenerated deterministically by
   `scripts/build_example.py` and pinned by a byte-comparison test.
3. **Install verification** — extend the CI `packaging-smoke` job to an
   OS matrix (Linux, macOS, Windows) so wheel installation and `ui` serving
   are verified on every supported OS on every push.
4. **User documentation** — new docs for the four audited gaps: provider
   authentication/setup, privacy and local trust, troubleshooting (error-code
   reference), and workspace backup/migration.
5. **Provenance review** — a recorded dependency/asset/font/copied-material
   review with findings and disposition.
6. **Release checklist** — an owner-facing checklist covering the remaining
   human steps: per-OS manual sign-off, demo recording, and tagging.

## 3. Non-goals

- No engine, schema, runtime-asset, prompt, or validation-rule changes. The
  canonical acceptance fixture and its pinned normalized SHA-256
  (`99fde906…b07`) are untouched.
- No new dependencies (runtime stays standard-library only).
- No cockpit UI changes.
- No hosting, packaging beyond the existing wheel, or release automation
  beyond CI verification (tagging remains a manual owner action).

## 4. Design decisions

### Example project (bullet 2)

- **Content**: a copy of the personalized guide-v1 fixture family
  ("Thinking in Feedback Loops", `conceptual-foundations`, guide schema 1.1,
  all six interaction types), with three deliberate polish edits in the
  example's own copy: declared course time 15 minutes (modules 7 + 8) so the
  deterministic reading-time calibration check passes cleanly, a
  human-readable goal-exclusion reason, and a topic `time_budget_minutes`
  matching the declared estimate. The canonical test fixture itself is not
  modified.
- **Personalization**: the example attaches a fully synthetic learner profile
  (`example-learner`) with three goals — two served, one excluded — so the
  exported guide demonstrates the personalization boundary: the private
  values must not appear in the export, which the pinning test asserts.
- **Reproducibility**: `scripts/build_example.py` drives a real run
  (spec → outline → draft → qa → repair → validate → finalize → export) in a
  temporary workspace from the committed sources and copies
  `guide.html` + `guide.report.json` into `examples/feedback-loops/export/`.
  Engine exports are byte-deterministic (proven by
  `tests/test_release_gate_acceptance.py`), so
  `tests/test_example_project.py` regenerates the export and asserts the
  committed bytes match, the gate is open, the report carries zero findings,
  and no private profile value appears in the HTML.
- **Layout constraint**: the repo `.gitignore` ignores unanchored `runs/`,
  `topics/`, `profiles/` — the example uses flat files (`topic.toml`,
  `profile.toml`) and `responses/` + `export/` directories to stay trackable.

### Install verification (bullet 3)

CI is the reproducible half of "verify package installation on supported
operating systems": the existing `packaging-smoke` job becomes a
`{ubuntu, macos, windows}` matrix, with the shell steps made portable
(Python for the port lookup and index probe instead of `curl | grep`). The
release checklist keeps a small manual per-OS confirmation for the
interactive parts CI cannot cover (browser open, first-run prompt).

### Documentation set (bullets 1 and 4)

Grounded in the 2026-07-17 docs gap audit (provider auth mostly missing;
backup/migration largely missing; troubleshooting partial; privacy well
covered but scattered):

- `docs/install-and-first-course.md` — the canonical walkthrough the README
  links to; ends with the user opening the exported example guide offline.
- `docs/providers.md` — `manual` / `claude-code` / `codex`: what each shells
  out to, how availability is detected (`PATH` lookup of `claude` / `codex`),
  how to authenticate each CLI, exact flags the adapters pass and their
  security posture, and the model-catalog/plan TOML fields.
- `docs/privacy-and-local-trust.md` — one consolidated page: what stays
  local, the export allowlist boundary, the daemon loopback + token +
  Host-check model, `daemon.json` (0600, per-workspace), and what SECURITY.md
  covers at author-time trust.
- `docs/troubleshooting.md` — user-facing error-code reference generated
  from `education_pipeline/errors.py` content (kept in sync by a test that
  asserts every catalog code is documented), plus common first-run failures
  and workspace-check findings.
- `docs/backup-and-migration.md` — what a complete workspace is, plain-file
  backup, moving between machines/paths, registry re-pointing, what to
  exclude (`.education-pipeline/` runtime state), and provider re-auth after
  a move.

### Provenance review (bullet 5)

`docs/provenance-review.md` records the audit: Python runtime (stdlib only),
dev dependencies, `web/` npm dependency tree licenses, `guide_runtime`
assets (maintained first-party, no vendored code), fonts (system font
stacks only — no bundled font files), and copied material (none; synthetic
fixtures authored in-repo). Findings get an explicit disposition.

## 5. Acceptance gates

- `python3 -m pytest` green including the two new test modules
  (example pinning, troubleshooting-doc coverage); `npm test` and
  `npm run build` green; e2e unchanged.
- `scripts/build_example.py` run twice from a clean tree produces
  byte-identical `examples/feedback-loops/export/` artifacts.
- The example's `guide.report.json` shows `gate.open == true` with zero
  findings; `guide.html` contains no private profile value.
- CI workflow changes are syntactically valid and the packaging-smoke steps
  are OS-portable (no bash-isms in the Windows leg).
- No change to `education_pipeline/` engine modules, prompts, schemas,
  runtime assets, or the canonical fixture (`git diff` scope check).
- Artifact-leak CI guard stays green (nothing under root `runs/`, `topics/`,
  `profiles/`, `queue/`).

## 6. Out of scope for this branch / owner actions

- Recording the demo, per-OS manual sign-off, and pushing the `v0.1` tag —
  owner actions listed in `docs/release-checklist.md`.
- Any PyPI publication decision (the PRD does not require it; the checklist
  flags it as an open owner decision).
