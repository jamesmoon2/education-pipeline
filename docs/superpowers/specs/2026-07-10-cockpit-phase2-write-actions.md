# Cockpit Phase 2 Spec — Write Actions

Phase 2 makes the cockpit operational: every human step of a run — importing
context, advancing, pasting/approving responses, running providers, finalizing,
exporting — works from the browser. Phase 1 delivered the read-only cockpit
(topic list → run board → stage viewer, job/log polling); this phase adds the
write surface on top of it.

**Done when:** a full run (topic import → spec → … → repair → finalize →
export → download) completes from the browser without touching the CLI, and
every write shows success/error feedback mapped from the daemon's error
envelope.

## Scope

In scope:
- Write endpoints on the daemon (`POST` under `/v1`), backed 1:1 by existing
  `RunStore` / `TopicStore` / `ProfileStore` methods — no new business logic.
- UI actions on the existing pages (buttons, dialogs, paste form, downloads).
- A `409 Conflict` error class so the UI can distinguish "retry with
  overwrite/force?" from genuine bad requests.
- Download endpoints for the finalized guide and exports.

Out of scope (unchanged from the roadmap):
- In-browser content editing and diff/QA views (Phase 3).
- New provider integrations, SSE, multi-user, remote access.
- Daemon lifecycle management from the UI (start/stop stays in the CLI).
- Deleting or renaming topics, profiles, or runs.

## Grounding: the store layer this maps onto

All write behavior already exists with these exact semantics
(`education_pipeline/runs.py`, `workspace.py`):

| Store call | Semantics relevant to the API |
| --- | --- |
| `RunStore.advance(topic_id) -> AdvanceResult` | Performs the next *machine* step (`write_prompt` or `finalize`); no-ops at human steps. `AdvanceResult` = `{performed: str\|None, status: RunStatus}`. |
| `RunStore.ingest_response(topic_id, stage, text, *, force=False) -> Path` | Atomic write; rejects empty/whitespace text; refuses to clobber an existing response unless `force`. |
| `RunStore.approve_stage(topic_id, stage, *, overwrite=False) -> Path` | Copies response → `approved/`; raises if no response ingested; refuses to overwrite an existing approval unless `overwrite`. Appends a `response_approved` manifest event. |
| `RunStore.finalize_run(topic_id, *, overwrite=False) -> Path` | Copies approved `repair` output → `final/guide.md`; raises if repair is unapproved; refuses overwrite. Appends `finalized`. |
| `RunStore.export_run(topic_id, *, format="html", overwrite=False) -> Path` | Requires finalize first; `format` ∈ `EXPORT_FORMATS = ("markdown", "html")`; writes `final/guide.html` or `final/guide.bundle.md`. Appends `exported`. |
| `TopicStore.save_topic_toml(topic_id, toml_text, *, overwrite=False) -> Topic` | Parses + validates; enforces id match; refuses overwrite. |
| `ProfileStore.save_profile_toml(...)` | Same shape for profiles. |
| `ProfileStore.attach_profile_to_topic(profile_id, topic_id, *, overwrite=False) -> ProfileAttachment` | Snapshots the profile into `runs/<topic>/inputs/profile.toml`. Prompt writers pick it up automatically; a run works without one. |
| `JobStore.active_for(topic_id, stage) -> Job \| None` | The existing duplicate-run guard used by job enqueue. |

`POST /v1/jobs` (enqueue provider run) and `POST /v1/jobs/{id}/cancel` already
exist from the daemon baseline; Phase 2 only wires UI onto them.

## Error model (extension)

The envelope stays `{"error": {"code", "message"}}`. Phase 2 adds one HTTP
status and structured codes so the UI can offer targeted recovery:

| Status | When | Codes |
| --- | --- | --- |
| 400 `bad_request` | Invalid input: malformed body, bad id/stage, empty response text, invalid TOML, unsupported export format | (existing) |
| 401 / 404 | As in Phase 1 | (existing) |
| **409** | The request is well-formed but the run/workspace state refuses it | `already_exists`, `not_ready`, `job_active` |

Code semantics:
- `already_exists` — a no-clobber refusal the caller may retry with
  `overwrite`/`force` (response already ingested, stage already approved,
  already finalized, export/topic/profile file exists). The UI maps this to a
  confirm dialog ("already exists — overwrite?") and retries with the flag.
- `not_ready` — a precondition is missing and no flag can fix it (approve
  before a response exists, finalize before repair is approved, export before
  finalize). The UI shows the message; the fix is doing the earlier step.
- `job_active` — a queued/running job exists for the topic (see concurrency
  below). The UI points at the jobs panel.

Implementation note (for the plan): a `write_api.py` module mirroring
`read_api.py` — pure functions that pre-check state and raise typed exceptions
(`NotFoundError` → 404, new `ConflictError(code, message)` → 409), letting
`ConfigError` → 400. Handler adds `_api_post_routes` beside `_api_get_routes`.
Pre-checks use the same paths the store checks (`response_path.exists()`,
etc.) so messages can carry the right conflict code; the store call remains
the authority and its `ConfigError` remains the backstop.

## Concurrency guards

Handlers run on `ThreadingHTTPServer` threads while the `Worker` writes run
files. Rules:

1. **Any run-mutating endpoint** (`advance`, `ingest response`, `approve`,
   `finalize`) refuses with `409 job_active` while **any** job for that topic
   is queued/running (`store.list(topic_id)` filtered on non-terminal status —
   add `JobStore.any_active_for(topic_id)` if needed). This is the mirror
   image of the existing `enqueue_stage` guard and keeps a single writer per
   run at a time. `export` is exempt (it only reads `final/` + writes a new
   file the worker never touches).
2. Workspace-level imports (`topics`, `profiles`, `attach`) don't touch run
   trees the worker writes; no job guard, only the `overwrite` no-clobber.
3. All writes go through the store layer's existing atomic/no-clobber helpers;
   the HTTP layer never opens workspace files directly.

## Endpoint contracts

All Phase 2 endpoints are `POST` (plus two `GET` downloads), require
`X-EP-Token`, and enforce the Host allowlist. Request bodies are JSON, subject
to the existing 1 MiB cap — pasted responses fit comfortably; revisit the cap
in Phase 3 for editing.

### Run actions

**`POST /v1/runs/{topic}/advance`** — body `{}` (empty allowed)
→ `RunStore.advance`. Success `200`:
```json
{"performed": "write_prompt" | "finalize" | null, "status": { ...run status payload... }}
```
(`status` reuses Phase 1's `run_status_payload`.) Errors: 404 no run/topic is
**not** raised — advance on a fresh topic writes the spec prompt and starts
the run, matching `edu advance`; 409 `job_active`.

**`POST /v1/runs/{topic}/stages/{stage}/response`** — body
`{"text": str, "force": false}`
→ `RunStore.ingest_response`. Success `200`:
```json
{"topic_id": "t", "stage": "draft", "response_path": "responses/draft.response.md", "status": { ... }}
```
Errors: 400 empty/whitespace text or bad stage; 404 no run; 409
`already_exists` (response present, no `force`); 409 `job_active`.

**`POST /v1/runs/{topic}/stages/{stage}/approve`** — body
`{"overwrite": false}`
→ `RunStore.approve_stage`. Success `200`:
```json
{"topic_id": "t", "stage": "draft", "approved_path": "approved/draft.md", "status": { ... }}
```
Errors: 404 no run; 409 `not_ready` (no ingested response); 409
`already_exists` (already approved, no `overwrite`); 409 `job_active`.

**`POST /v1/runs/{topic}/finalize`** — body `{"overwrite": false}`
→ `RunStore.finalize_run`. Success `200`:
```json
{"topic_id": "t", "final_path": "final/guide.md", "status": { ... }}
```
Errors: 404 no run; 409 `not_ready` (repair not approved); 409
`already_exists`; 409 `job_active`.

**`POST /v1/runs/{topic}/export`** — body
`{"format": "html" | "markdown", "overwrite": false}`
→ `RunStore.export_run`. Success `200`:
```json
{"topic_id": "t", "format": "html", "export_path": "final/guide.html"}
```
Errors: 400 unsupported format; 404 no run; 409 `not_ready` (not finalized);
409 `already_exists`.

All `*_path` values are returned **relative to the run directory** — they are
display strings, never used by the client to fetch files.

### Downloads

**`GET /v1/runs/{topic}/final/download`** → the finalized `final/guide.md`,
`Content-Type: text/markdown; charset=utf-8`,
`Content-Disposition: attachment; filename="{topic}-guide.md"`.
404 `not_found` if not finalized.

**`GET /v1/runs/{topic}/exports/{format}/download`** → the exported file
(`html` → `final/guide.html` as `text/html`, `markdown` →
`final/guide.bundle.md` as `text/markdown`), same attachment pattern.
400 bad format; 404 if that export hasn't been produced.

Downloads are authed `GET`s. The SPA triggers them via
`fetch` + blob URL (the token travels in the header, so a plain
`<a href>` won't work — the client gains a `download(path, filename)` helper).

### Workspace imports

**`POST /v1/topics`** — body `{"toml": str, "overwrite": false}`.
Parses the TOML, derives the id from the document (like `edu topic import`),
then `TopicStore.save_topic_toml`. Success `200`: `{"id", "title"}`.
Errors: 400 invalid TOML/schema; 409 `already_exists` without `overwrite`.

**`POST /v1/profiles`** — body `{"toml": str, "overwrite": false}` → same
shape via `ProfileStore.save_profile_toml`. Success `200`: `{"id"}`.

**`POST /v1/topics/{topic}/profile`** — body
`{"profile_id": str, "overwrite": true}`
→ `ProfileStore.attach_profile_to_topic`. Default `overwrite: true`, matching
`edu profile attach` (re-attaching refreshes the snapshot). Success `200`:
`{"profile_id", "topic_id", "snapshot_path"}`. Errors: 404 unknown profile;
400 bad ids.

### Already-existing endpoints the UI adopts

- `POST /v1/jobs` body `{"topic_id", "stage"?, "force"?}` — "Run with
  provider" button. Its errors surface verbatim (the daemon already refuses
  duplicate active jobs and non-runnable next actions with 400).
- `POST /v1/jobs/{id}/cancel` — cancel button in the jobs panel.

## UI behavior

Design rule: **the run board renders exactly one primary action, driven by
`next_action.action`** — the server decides what's next, the UI never
re-derives pipeline logic.

| `next_action.action` | Primary action rendered |
| --- | --- |
| `write_prompt` | **Advance** button (`POST .../advance`) |
| `save_response` | **Run with provider** (`POST /v1/jobs`) + **Paste response…** (opens a textarea dialog → `POST .../stages/{stage}/response`) |
| `approve` | **Approve {stage}** (`POST .../stages/{stage}/approve`) — with a "review first" link to the stage viewer |
| `finalize` | **Finalize** button |
| `done` | **Export** controls: format select (html/markdown), Export button, and Download links for `final/guide.md` + any produced exports |

Additional UI:
- **Stage viewer** gains contextual actions for its stage: "Paste response"
  when no response exists, "Approve" when a response exists and isn't
  approved. Approval from the viewer is preferred UX (review-then-approve).
- **Jobs panel** rows gain a **Cancel** button for queued/running jobs.
- **Topic list** gains "Import topic…" and "Import profile…" (textarea/file
  paste of TOML → the import endpoints) and, per topic, an "Attach profile"
  select listing `GET /v1/profiles`.
- **Feedback:** every action shows an inline result (success summary or the
  envelope `message`). On `409 already_exists`, show a confirm dialog and
  retry with `overwrite`/`force` on confirmation. On `409 job_active`, link
  to the jobs panel. After any successful write, refresh the run status
  immediately (don't wait for the poll tick — the client helpers return the
  updated `status` payload precisely so pages can use it).
- All action buttons disable while their request is in flight.

## Client additions (`web/src/api/`)

- `apiPost<T>(path, body): Promise<T>` — same token bootstrap, JSON body,
  maps the envelope to `ApiRequestError` (which already carries `status` +
  `code`, so `409`/`already_exists` handling needs no new error type).
- `download(path, filename)` — authed fetch → blob → temporary object URL.
- Typed helpers: `postAdvance`, `postResponse`, `postApprove`, `postFinalize`,
  `postExport`, `importTopic`, `importProfile`, `attachProfile`, `enqueueJob`,
  `cancelJob`.

## Security notes (unchanged invariants, restated because writes raise stakes)

- Every `POST` requires `X-EP-Token`; there are **no** token-exempt write
  routes. Combined with no-CORS-headers and the custom-header requirement,
  cross-site pages cannot trigger writes.
- No new `Content-Type`-based behavior: bodies are parsed as JSON regardless,
  under the existing 1 MiB cap.
- Download endpoints serve only the two fixed paths inside the run's `final/`
  directory — no client-supplied filenames or paths.

## Testing requirements

- **Daemon:** per endpoint — auth (401), happy path, each error class
  (400/404/409 with the exact `code`), and the `job_active` guard (enqueue a
  slow fake job, assert the write 409s, cancel, assert it succeeds). The
  Phase 1 `_start_server` factory fixture already supports this.
- **Full-pipeline server test:** drive spec→export entirely through HTTP
  (ingest → approve × 5 stages → finalize → export → download) asserting the
  manifest accumulates the expected events.
- **Frontend:** client helper tests (POST body, error mapping); per-page tests
  for the action-button state machine (one per `next_action.action` value)
  and the overwrite-confirm retry flow.
- **E2E:** extend the Playwright smoke to a full browser run: import topic →
  advance → paste response → approve (× stages) → finalize → export →
  download link present.

## Open questions (resolve when writing the Phase 2 implementation plan)

1. Should `advance` auto-loop machine steps (advance repeatedly until a human
   step) or stay single-step like the CLI? Recommendation: single-step —
   matches `edu advance`, and the UI can just show the button again.
2. Does ingest-response need a manifest event? The store doesn't record one
   today (the CLI path doesn't either; the job runner records its own). Parity
   says no; revisit if the manifest is meant to be a complete audit log.
3. File-upload variant for topic/profile import (drag a `.toml`) vs.
   paste-only in Phase 2. Recommendation: paste-only; files are one
   `FileReader` away later.
4. Whether `job_active` should block only same-stage writes instead of
   topic-wide. Topic-wide is safer and simpler; loosen only if it chafes.

## Phasing note

This spec deliberately reuses Phase 1's `run_status_payload`, error envelope,
`_start_server` test factory, `usePolling`, and `ApiRequestError`. The
implementation plan must be written **after Phase 1 merges**, quoting the real
merged code.
