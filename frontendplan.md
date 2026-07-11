# Frontend Plan — Education Pipeline Cockpit

A local web app ("cockpit") over the existing education-pipeline workspace and
loopback daemon. It drives a run end to end: import context, advance stages,
read prompts and model responses, approve gates, kick off provider runs, watch
jobs, edit content, and export.

This was a roadmap-level plan; each phase got its own spec → detailed
implementation plan → build.

> **Status (2026-07-11): all three phases built.** Phase 1 merged (PR #1),
> Phase 2 merged (PR #2), Phase 3 complete on PR #3
> (<https://github.com/jamesmoon2/education-pipeline/pull/3>). This document
> is updated to the as-built state; deviations from the original roadmap are
> marked inline.

## Decisions (from brainstorming)

| Question | Decision |
| --- | --- |
| Primary purpose | **Full pipeline cockpit** — replaces the CLI for daily work |
| Form factor | **Local web app with a modern frontend build**, served on loopback |
| Content editing | **Full editor with diff/QA views** (in-browser edits + side-by-side) |
| Frontend stack | **React + Vite + TypeScript** |
| Live updates | **Polling** (fits the stdlib `ThreadingHTTPServer`; reuses the incremental log `offset` cursor). Revisit SSE only if polling proves inadequate. |

## Non-goals

- No remote access, multi-user support, or TLS — loopback single-user only.
- No database — the workspace files stay the source of truth.
- No new provider integrations — the cockpit drives the existing job queue.
- The CLI stays fully supported; the cockpit is an alternative surface over
  the same stores, not a replacement for the library layer.

## Domain recap (for grounding)

- Workspace holds topics (`TopicStore`), learner profiles (`ProfileStore`),
  and runs (`RunStore`) — local files first.
- **Executable stages** (`SUPPORTED_STAGES`): `spec → outline → draft → qa →
  repair`. Each stage cycles through *write prompt → run provider (or paste
  response) → ingest response → approve*; `RunStatus.next_action` names the
  next step. `finalize` and `export` are run-level operations after the
  stages, not stages themselves (`EXPORT_FORMATS = ("markdown", "html")`).
- Provider runs execute a stage's prompt through Claude Code / Codex via the
  daemon's async job queue (`JobStore` + `Worker`); manual provider paths
  ingest a pasted response instead.
- The daemon binds `127.0.0.1` on an **ephemeral port** and writes a
  discovery file (`daemon.json`: pid, port, token, version). Every `/v1`
  request today requires the `X-EP-Token` header and a
  localhost `Host` header.

## Architecture

- **Backend** — extend the existing loopback daemon
  (`education_pipeline/daemon/server.py`), staying **stdlib-only**:
  1. A broader `/v1` read/write API beyond today's jobs endpoints (see the
     endpoint map below). Handlers call the existing `TopicStore` /
     `ProfileStore` / `RunStore` methods; no new business logic in the
     HTTP layer.
  2. Static-asset serving of the built SPA from `web/dist/` (correct
     `Content-Type`, `Cache-Control`, and SPA fallback of unknown non-`/v1`
     paths to `index.html`).
- **Frontend** — a React + Vite + TypeScript SPA in a new top-level `web/`
  directory, built to static assets the daemon serves. `web/` has its own
  `package.json`; Node is a **build-time dependency only** — the installed
  Python package never needs npm at runtime.
- **Live updates** — the client polls `/v1/jobs` and run status on an
  interval (pause when the tab is hidden); logs use the existing incremental
  `offset` cursor on `/v1/jobs/{id}/log`.
- **Launch flow** — `edu daemon start` (or a new `edu ui` convenience
  command) prints/opens `http://127.0.0.1:<port>/` read from the discovery
  file, so the ephemeral port never has to be typed.

### Auth & security model

Today `_guard()` (Host check + token check) runs before routing, so the
browser could never fetch `index.html` to learn the token. The restructure:

- **Route-aware auth.** Static assets and one bootstrap endpoint
  (`GET /v1/session` → `{ token, version }`) are exempt from the token
  check; every other `/v1` route keeps requiring `X-EP-Token`. The SPA
  calls `/v1/session` on load and sends the token on all API calls.
- **Why this is safe on loopback:** a malicious web page can *send* requests
  to `127.0.0.1` but cannot *read* responses cross-origin — the daemon must
  therefore **never emit CORS headers**. The existing `Host` allowlist
  (`127.0.0.1` / `localhost`) stays as the DNS-rebinding backstop. Because
  the token travels in a custom header (never a cookie), cross-site request
  forgery on the write endpoints is structurally blocked.
- **Path traversal.** Static serving must resolve paths against `dist/` and
  reject anything escaping it (`..`, absolute paths, symlinks).
- **Body cap and error shape** (`MAX_REQUEST_BODY_BYTES`,
  `{"error": {"code", "message"}}`) carry over to all new endpoints. The
  Phase 3 spec resolved the cap question: **the 1 MiB cap stays** — far
  beyond any guide this pipeline produces; the UI surfaces the transport
  error in the unlikely event it is hit.

### Dev workflow

- `vite dev` serves the SPA with a proxy for `/v1` → the daemon. A small
  Vite plugin (or proxy `configure` hook) reads `daemon.json` for the port
  and injects `X-EP-Token`, so dev and prod share the same client code path
  (`/v1/session` still works through the proxy).
- Production check: `npm run build` into `web/dist/`, then hit the daemon
  directly.

## API surface by phase

Existing endpoints (baseline): `GET /v1/health`, `GET/POST /v1/jobs`,
`GET /v1/jobs/{id}`, `GET /v1/jobs/{id}/log?offset=`,
`POST /v1/jobs/{id}/cancel`, `POST /v1/shutdown`.

New endpoints map 1:1 onto existing store methods:

| Endpoint | Backing method | Phase |
| --- | --- | --- |
| `GET /v1/session` | discovery token + version | 1 |
| `GET /v1/topics` | `TopicStore.list_topic_ids` (+ per-topic summary) | 1 |
| `GET /v1/topics/{id}` | `TopicStore.read_topic_toml` / `load_topic` | 1 |
| `GET /v1/profiles`, `GET /v1/profiles/{id}` | `ProfileStore.list_profile_ids` / `read_profile_toml` | 1 |
| `GET /v1/runs/{topic}` | `RunStore.run_status` (stages + `next_action`) | 1 |
| `GET /v1/runs/{topic}/stages/{stage}` | prompt / response / approved file contents via `StagePaths` | 1 |
| `GET /v1/runs/{topic}/manifest` | `RunStore.read_manifest` (event history) | 1 |
| `GET /` + static assets | `web/dist/` | 1 |
| `POST /v1/runs/{topic}/advance` | `RunStore.advance` | 2 |
| `POST /v1/runs/{topic}/stages/{stage}/response` | `RunStore.ingest_response` (manual-provider paste) | 2 |
| `POST /v1/runs/{topic}/stages/{stage}/approve` | `RunStore.approve_stage` | 2 |
| `POST /v1/runs/{topic}/finalize` | `RunStore.finalize_run` | 2 |
| `POST /v1/runs/{topic}/export` | `RunStore.export_run` (format in body) | 2 |
| `POST /v1/topics` / `POST /v1/profiles` (import TOML) | store import paths used by `topic import` / `profile import` | 2 |
| `POST /v1/topics/{id}/profile` (attach) | `ProfileStore.attach_profile_to_topic` | 2 |
| `GET /v1/runs/{topic}/final/download`, `GET .../exports/{format}/download` | `read_api` download paths over `RunStore` | 2 |
| `PUT /v1/runs/{topic}/stages/{stage}/response` | `RunStore.edit_response` (atomic write behind a sha256 content-hash precondition → `409 stale_content`; **responses only** — the roadmap's broader `.../content` was narrowed in the Phase 3 spec) | 3 |
| `POST /v1/preview` | `export.render_html_body` (pure body-only markdown rendering; no file access, not job-guarded) | 3 |

Phase 3 also extended `GET /v1/runs/{topic}/stages/{stage}` with
`response_sha256`, the hash the editor round-trips as its save precondition.

Concurrency note for the phase specs: handlers run on
`ThreadingHTTPServer` threads while the `Worker` also touches run files.
Reads are safe (atomic-write pattern already in `RunStore`); Phase 2/3
write endpoints must reuse the same store-level guards (e.g. refuse
approve/edit while a job is active for that topic/stage, as
`enqueue_stage` already does in reverse).

## Phasing

Each phase was independently shipped from its own spec → plan → build.

Phase documents:
- Phase 1 implementation plan: `docs/superpowers/plans/2026-07-10-cockpit-phase1.md`
- Phase 2 spec: `docs/superpowers/specs/2026-07-10-cockpit-phase2-write-actions.md`
- Phase 2 implementation plan: `docs/superpowers/plans/2026-07-10-cockpit-phase2-write-actions.md`
- Phase 3 spec: `docs/superpowers/specs/2026-07-10-cockpit-phase3-editor-design.md`
- Phase 3 implementation plan: `docs/superpowers/plans/2026-07-11-cockpit-phase3-editor.md`

### Phase 1 — Read-only cockpit + app skeleton ✅ (merged, PR #1)

- Daemon: route-aware auth, `/v1/session`, static serving, the read
  endpoints above.
- SPA shell: topic list → run board (stage milestones from `run_status`,
  with `next_action` surfaced prominently) → stage viewer rendering
  prompt / response / QA **read-only**.
- Live job and log monitoring via polling.
- **Done when:** starting the daemon and opening the printed URL shows real
  workspace topics, per-stage status, stage file contents, and a live-tailing
  job log — with zero manual token handling.

### Phase 2 — Write actions ✅ (merged, PR #2)

- Approve gates, advance, manual response ingestion.
- Finalize and export (markdown/html), plus authed downloads.
- Enqueue provider runs and cancel jobs from the UI; topic/profile import
  and profile attach.
- **Done when (verified):** a full run (spec → export) completes from the
  browser without touching the CLI, and every write shows success/error
  feedback mapped from the daemon's error envelope.

### Phase 3 — Editor + diff views ✅ (PR #3)

- In-browser editing of **stage responses** saved back through
  `RunStore.edit_response` — atomic write behind a sha256 content-hash
  precondition (`409 stale_content` on mismatch; the browser buffer is kept
  and the user reconciles by hand — no merge UI). Edits record a
  `response_edited` manifest event; post-approval edits resurface the
  Approve control.
- Live markdown preview rendered server-side by `export.py`'s renderer
  (`POST /v1/preview`), zero new dependencies.
- Side-by-side views: prompt vs response (plain two-pane) and draft vs
  repair (line-level LCS diff, dependency-free client module).
- **Scope trims vs the original roadmap** (decided in the Phase 3 spec):
  editing covers responses only — prompts are regenerated artifacts and
  approved/final files are the audit trail; the inline QA-report view was
  deselected (QA responses render as ordinary stage content).
- **Done when (verified by e2e):** an edit → save → re-approve → finalize
  loop works entirely in the browser with the edited content landing in
  `final/guide.md`, and a concurrent external edit is detected and rejected
  — never overwritten.

## Testing strategy

- **Daemon:** extend `tests/test_server.py` / `test_daemon_serve.py` with
  the same in-process pattern — every new endpoint gets auth, happy-path,
  and error-shape tests; static serving gets traversal-rejection tests.
- **Frontend:** Vitest + React Testing Library for components; API client
  tested against recorded daemon fixtures.
- **End to end:** one Playwright smoke per phase against a real daemon on a
  temp workspace (Phase 1: read flow; Phase 2: approve→export; Phase 3:
  edit→save round-trip).

## Open questions — resolutions

1. `GET /v1/topics` returns **summaries** (id, title, parse error, run
   status) — one round-trip for the topic list. *(Resolved, Phase 1.)*
2. Poll intervals are **fixed** (2s jobs, 5s status/content), pausing when
   the tab is hidden; no adaptive backoff needed. *(Resolved, Phase 1/2.)*
3. Body-size cap: **the 1 MiB cap stays** for stage-content writes.
   *(Resolved, Phase 3 spec.)*
4. `edu ui` convenience command (start daemon if needed + open browser) —
   **still open**; today `daemon start` prints
   `cockpit: http://127.0.0.1:<port>/` from the discovery file. Decide if
   the auto-open nicety is worth a follow-up.
