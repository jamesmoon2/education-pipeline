# Model-Plan Configuration in the Cockpit — Design

- **Date:** 2026-07-11
- **Status:** Approved design (brainstorm output). Supersedes nothing; executes
  the milestone proposed in
  `docs/superpowers/specs/2026-07-11-next-milestone-proposal.md`.
- **Grounding:** PRD `docs/product-requirements.md` §6.3–§6.4, §7.4, §10
  ("P0 — Finish model-plan configuration"), §11 release criterion #3; audit
  findings F1/F2 in
  `docs/superpowers/specs/2026-07-11-interactive-guide-v1-post-milestone-audit.md`.

## Goal and exit criterion

A user configures and executes a mixed-provider run entirely from the cockpit —
"Use recommended models" or per-stage provider/model/effort overrides, with
availability display, weak-configuration warnings, and manual operation as a
first-class choice — without editing TOML. An advanced user can still hand-edit
the local TOML and have it take effect. The effective provider/model/effort is
recorded with the run and displayed as provenance.

## Decisions made during brainstorming

1. **TOML stays the source of truth for the global plan.** Cockpit edits
   rewrite `<workspace>/config/model-plan.toml` via a small purpose-built
   emitter in `config.py` (stdlib `tomllib` is read-only; no runtime
   dependency is added). Hand edits and UI edits round-trip through the same
   file.
2. **Effective config is resolved at each stage execution**, not snapshotted at
   run creation: global plan overlaid with the run's sparse per-stage
   overrides, resolved fresh when the stage executes. Provenance records what
   actually ran.
3. **The New-run flow creates topics too.** A structured form (id, title,
   outcome/brief) generates the topic TOML server-side; raw TOML import
   remains available for advanced users.
4. **The daemon re-reads catalog and plan from disk on each config-related
   request** (files are tiny), so hand edits take effect without a restart.
5. **Weak-config warnings are catalog-driven**: for reasoning-heavy stages
   (`spec`, `outline`, `repair`), warn when the chosen model's `quality` is
   set and is not `"strong"` or `"premium"` (ordering: `fast` < `strong` <
   `premium`). A model with no `quality` value never warns — unannotated
   catalogs are not nagged. No model names in code.

## 1. Configuration model & persistence

- `config.py` gains `emit_model_plan_toml(plan: ModelPlan) -> str`, a
  serializer for our narrow flat schema only (top-level `provider`; per-stage
  `provider`/`model`/`effort`/`recommendation` tables). It is not a general
  TOML writer.
- Global-plan writes are atomic (temp file + `os.replace`) and guarded against
  clobbering concurrent hand edits: the `PUT` carries the SHA-256 of the plan
  file content the edit was based on; a mismatch returns the existing
  stale-content error shape used by response edits.
- Per-run overrides live in a daemon-managed JSON file,
  `<run>/model-plan-overrides.json`, holding only stages the user explicitly
  overrode (sparse; never a full plan copy). "Use recommended" for a stage
  deletes that stage's entry.
- Effective config for a stage = global plan + that run's override for that
  stage. `daemon/jobs.py` changes from receiving the plan at `Worker`
  construction to loading catalog/plan (and the run's overrides) per job.

## 2. `/v1` API surface

Read endpoints:

- `GET /v1/config/providers` — catalog providers plus live `is_available()`
  results (each provider runner's PATH check, run without sending any course
  content per PRD §7.4) and a human-readable reason when unavailable.
  `manual` is always listed and always available.
- `GET /v1/config/catalog` — providers, models, quality, default effort, and
  descriptions from `model-catalog.toml`.
- `GET /v1/config/plan` — the global plan, the plan file's SHA-256, and
  computed per-stage weak-config warnings.
- `GET /v1/runs/{topic}/plan` — the run's effective plan (per stage:
  provider/model/effort plus `source: "default" | "override"`), warnings, and
  the would-be local command line per stage (reusing the provider argv
  builders) for the "show the exact command before execution" requirement.

Write endpoints:

- `PUT /v1/config/plan` — full global-plan replace; validated against the
  catalog before write; SHA-guarded as above.
- `PUT /v1/runs/{topic}/plan` — set or clear per-stage overrides.
- `POST /v1/topics` — create a topic from structured fields (id, title,
  outcome/brief); the server generates topic TOML through `TopicStore`, so
  the form and the existing raw-TOML import share one code path.

Warnings are computed server-side so the CLI and cockpit agree.

## 3. Provenance

When a stage executes (provider job or manual ingest), the resolved
provider/model/effort and per-stage `source` are appended to the run's
`manifest.json` under an additive `stage_provenance` key — one entry per stage
execution, never mutated retroactively. Manual stages record
`provider: "manual"`. Legacy manifests without the key remain valid. The run
status payload surfaces provenance and the cockpit shows it on the stage card
(e.g. "draft ran on codex / gpt-5.4 / effort high — overridden").

## 4. Cockpit UI

- **Settings page** (new route): global per-stage defaults, "Use recommended"
  global reset, provider availability list with explanations for unavailable
  providers, and quality/speed/cost guidance text sourced from the catalog —
  never exact prices.
- **Run plan editor**, reachable from a run: per-stage provider/model/effort
  selectors with "Manual" as a first-class option, per-stage "Use
  recommended" reset, inline weak-config warnings, and an effective
  command/model/effort preview shown before run/advance fires.
- **New-run flow** replacing the empty-board paste-TOML dead end:
  topic (form or raw-TOML toggle) → profile selection → model-plan review
  (embedding the same plan-editor component) → create run. No library
  management, blueprint pedagogy, or onboarding tour (those stay P1).

## 5. Wave 0 hardening (lands first, own PR)

- URL-scheme allowlist (`http`, `https`, `mailto`, relative) in the legacy
  Markdown renderer; test asserts
  `render_html_body('[x](javascript:alert(1))')` yields no live
  `javascript:` href.
- CSP on the legacy export and the cockpit shell; if the CSP breaks the
  same-origin legacy preview, move the preview into a sandboxed iframe (as
  guide-v1 already does) rather than loosening the CSP; covered by tests.
- Commit/clean the `.gitignore` drift (audit F2); `git diff --check` clean.

## Non-goals

Unchanged from the milestone proposal §4: no first-run onboarding or course
library management; no blueprint prompt/QA contracts; no change to the frozen
guide schema, runtime, validation, prompts, or canonical fixture
(normalized SHA-256 `99fde906…b07`); no new provider adapters; no price
claims; no profile-editing UI.

## Wave order

Wave 0 (hardening) → Wave 1 (read API) → Wave 2 (Settings) → Wave 3
(per-stage editor + provenance) → Wave 4 (New-run flow) → Wave 5
(acceptance + closeout). Waves 1–4 are strictly ordered; Wave 4 reuses the
Wave 3 plan editor as its review step.

## Error handling

- Unavailable provider: selectable state degrades to "unavailable, here's
  why"; starting a job on an unavailable provider keeps today's explicit job
  failure.
- Invalid plan edits (unknown provider/model/effort): rejected server-side
  with `ConfigError` details before any file write.
- Concurrent plan edits: SHA-guarded writes return the stale-content error
  shape; the UI refetches and re-presents.
- Catalog/plan file unreadable: config endpoints return a structured error
  rather than crashing the daemon.

## Testing & acceptance gates

- Strict TDD throughout; suites: `python3 -m pytest`, `npm test`,
  `npm run build`, `npm run e2e` — all pass with recorded counts; no
  regression to the 404 / 79 / 38 baselines beyond intended additions.
- New pytest coverage: TOML emitter round-trip (parse → emit → parse
  equality), SHA-guarded plan writes, availability endpoint with mocked
  provider presence, override resolution, provenance append, topic-create
  endpoint.
- New e2e coverage: configure a per-stage override and see a weak-config
  warning; drive a mixed-provider run (recommended + one override + one
  manual stage) end to end without editing TOML; confirm the effective plan
  is persisted and displayed as provenance.
- Regression: a hand edit to `model-plan.toml` takes effect and round-trips
  through the UI.
- Frozen-surface guard and CI leak guard stay green.
