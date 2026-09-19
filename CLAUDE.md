# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Local-first, prompt-first tooling for building interactive education guides. Models generate course content only; the guide shell, runtime, design system, and validation logic stay in maintained source code. Two halves:

- `education_pipeline/` — Python 3.11+ package. **Standard library only at runtime** (`pytest` is the sole dev dependency; do not add runtime dependencies without prior discussion in an issue).
- `web/` — React 18 + TypeScript "cockpit" UI (Vite, vitest, Playwright), talking to the daemon's HTTP API.

## Commands

```bash
# Python (from repo root)
python3 -m pip install -e ".[dev]"      # setup
python3 -m pytest                        # full suite
python3 -m pytest tests/test_runs.py     # one file
python3 -m pytest tests/test_runs.py -k name_fragment   # one test

# Web (from web/)
npm run dev        # Vite dev server (proxies /v1 to a running daemon via .education-pipeline/daemon.json)
npm run build      # tsc --noEmit && vite build — tsc is the only type/lint gate; there is no eslint/prettier
npm run test       # vitest unit tests
npm run e2e        # Playwright tests in web/e2e/ (includes @axe-core accessibility checks)
npx playwright test e2e/editor.spec.ts   # one e2e file
```

CI (`.github/workflows/ci.yml`) runs pytest on Python 3.11 and 3.12 plus a CLI smoke test (`education-pipeline --help`).

## Architecture

The engine is deterministic and file-based: every run lives entirely in a user **workspace** directory (never in this repo — `runs/`, `topics/`, `profiles/`, `queue/` are gitignored). A run can be resumed at any point from the workspace alone.

**Stage pipeline** (`runs.py`, the core): `spec → outline → draft → qa → factcheck → repair`, then deterministic `finalize` and `export`. `stage_graph.py` is the single declarative table of stages (order, upstream sources, mode membership, reasoning flag); `config.py`'s stage tuples and the staleness / next-action walks in `runs.py` derive from it rather than restating the chain. Each stage writes a prompt file to disk, waits for a model response saved to a known path, and gates on explicit approval — `advance` never auto-approves. `RunStore` owns all stage state, paths, and transitions and is assembled from mixins by concern (`runs_waivers.py`, `runs_reports.py`, `runs_personalization.py`, `runs_finalize.py`; shared helpers and public dataclasses in `run_core.py`, re-exported from `runs`). `run_modes.py` holds the per-mode strategy pair: `LegacyMarkdownMode` quarantines the pre-guide Markdown path (old workspaces only; new runs are always interactive-guide v1) and `RunStore._mode` is the one dispatch site. `StaleContentError` guards concurrent edits (writes are keyed by `response_sha256`). On interactive-guide runs the draft stage's model work is split into *units* (`runs_draft_units.py`): a skeleton prompt, then one prompt per outline module under `<run>/draft/`, assembled deterministically (`guides/canonical.py` `assemble_guide`) into the unchanged `responses/draft.response.json`; the stage's single approval, validation and downstream source binding are untouched, and a whole guide pasted into the response file still wins over the units. Repair can be scoped to one module or one section (`RepairScope`, `splice_module` / `splice_section` on approval).

**Three surfaces over one engine:**
1. **CLI** (`cli.py`, entry point `education-pipeline` / `python -m education_pipeline`) — the supported power-user surface; dependency-free.
2. **Daemon** (`daemon/`) — loopback-only (`127.0.0.1`) ThreadingHTTPServer requiring a constant-time-compared `X-EP-Token` header on every request, with Host-header checks against DNS rebinding. `read_api.py`/`write_api.py` define the `/v1` routes; `jobs.py` holds `JobStore`/`Worker` for provider job execution (a small pool: `parallelism` threads, 1–4 from `model-plan.toml`, that only ever overlap module jobs of one draft batch; everything else runs alone); `lifecycle.py` handles auto-start/stop; connection info is published to `<workspace>/.education-pipeline/daemon.json`.
3. **Cockpit** (`web/`) — React UI over the same `/v1` API. Vite dev server discovers the daemon port from `daemon.json`.

**Run-to-judgment loop** (`orchestrate.py`) — `run_until_judgment` takes every mechanical step (prompt, provider job, assemble, validate) over a five-member `Steps` protocol and stops at the first human gate; it has no approve/finalize/export member by design. The CLI drives it with a blocking job runner (`run --until approval`, `queue run` over `<workspace>/queue/courses.json`, `course_queue.py`); the daemon with a non-blocking one (`POST /v1/runs/{id}/continue`), which the cockpit's "Approve & continue" and "Continue to next approval" call; jobs that route starts are marked `chain`, and the worker's completion hook (`DaemonContext.continue_after_job`) resumes the same loop after each chained job or batch until a judgment, recording the outcome on the job and in run status as `continuation`, so one cockpit click ends where `run --until approval` ends. `POST /v1/jobs` never chains. `provider_for_stage` there is the one provider-resolution rule.

**Providers** (`providers/`) — adapters that execute a stage prompt through Claude Code or Codex instead of manual copy/paste. `run` executes exactly the next stage then stops for approval.

**Guides subsystem** (`guides/`) — the interactive-guide document model: parse → normalize → validate (with a waiver mechanism for accepted findings) → project/canonicalize. `guide_runtime/assets/` (runtime.js/runtime.css) is the maintained browser runtime shipped inside exported static HTML; `export.py` renders the self-contained guide.

## Conventions

- Tests come before behavior changes; add/update tests in the same change (this repo is developed strictly TDD).
- Stages that call a model produce a prompt on disk; deterministic steps (finalize, export) never call a model.
- Style: standard-library idioms, small pure functions, explicit file artifacts, no hidden global state.
- Keep public docs and prompt templates domain-neutral; never commit generated runs, real learner profiles, or tuned prompt libraries (see `docs/extraction-manifest.md` for the boundary).
- Design docs, implementation plans, and stage prompts live under `docs/superpowers/` (specs/, plans/, prompts/).
