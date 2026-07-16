# Cockpit Phase 3 — In-browser editing and diff views

Phase 3 of the cockpit UI (per `docs/archive/frontendplan.md`). Phase 2 made every human
step of a run work from the browser; Phase 3 makes the *content* workable
there too: edit a stage response in the browser and save it back safely, see
a live preview, and compare documents side by side.

**Done when:** an edit → save → approve → finalize loop works entirely in the
browser, and a concurrent external edit is detected and rejected — never
overwritten.

## Scope

In scope:
- Editing **stage responses only**, in the browser, saved back through the
  store layer with an atomic content-hash precondition.
- A markdown preview rendered server-side by the existing `export.py`
  renderer (one new endpoint, no new dependencies).
- Two side-by-side views on the stage viewer: prompt vs response (plain
  two-pane), and draft vs repair (line-level diff).
- A dependency-free line-diff module in the SPA.

Out of scope (decided during design):
- Editing prompts, approved snapshots, or the final guide. Prompts are
  regenerated artifacts; approved/final are the audit trail.
- An inline structured QA-report view (deselected; QA responses render as
  ordinary stage content).
- A merge UI for conflicts. On a stale save the user re-applies changes by
  hand; their buffer is never discarded.
- Raising the 1 MiB request-body cap. 1 MiB of markdown is far beyond any
  guide this pipeline produces; the UI surfaces the 413 envelope error in the
  unlikely event it is hit. (Resolves `docs/archive/frontendplan.md` open question 3:
  **keep the cap**.)
- Anything already out of scope for the cockpit: SSE, multi-user, remote
  access, daemon lifecycle from the UI, deleting/renaming artifacts.

## Grounding: existing machinery this maps onto

- `RunStore.ingest_response(topic_id, stage, text, *, force=False)`
  (`education_pipeline/runs.py`) — validates topic/stage, rejects empty text,
  atomic write. Phase 3 adds a sibling `edit_response` (below) rather than
  overloading it: paste (create/replace wholesale) and edit (guarded
  read-modify-write) have different preconditions.
- `read_api.stage_content(runs, topic_id, stage)`
  (`education_pipeline/daemon/read_api.py`) — returns
  `{prompt, response, approved, stub}` content. Phase 3 extends its payload.
- `export.py`'s dependency-free markdown renderer.
  `render_markdown_to_html` emits a full document; its block renderer
  (`_render_blocks`) becomes a public `render_html_body(markdown_text) -> str`
  so the preview endpoint can render body-only HTML. All content is
  HTML-escaped by the renderer; it emits no scripts.
- Phase 2 invariants, all unchanged: stdlib-only backend; error envelope
  `{"error": {"code", "message"}}`; token on every write; Host allowlist;
  no CORS; store-layer-only writes; 1 MiB body cap; run-mutating writes
  refuse with `409 job_active` while any job for the topic is non-terminal;
  the UI derives available actions from server state, never pipeline logic.

## Store layer (one new method)

**`RunStore.edit_response(topic_id, stage, text, *, base_sha256) -> Path`**

1. Validates topic id and stage exactly as `ingest_response` does
   (`ConfigError` on bad input); rejects empty/whitespace-only text.
2. Requires the response file to exist (`ConfigError` if absent — editing
   presupposes content; creating one is the paste flow's job).
3. Computes sha256 of the current response file bytes. If it differs from
   `base_sha256`, raises the new typed error `StaleContentError(message)`
   — mapped to HTTP `409 stale_content`. The check and the write happen
   under the same store call against the same read; the atomic
   temp-file+rename write means a losing concurrent writer is either fully
   before (detected by the hash) or fully after (its save then fails the
   hash check).
4. On match: atomic write, then appends a `response_edited` manifest event
   (unlike paste-ingest, which records none — an in-browser edit is an
   authored change worth auditing).

## Error model (extension)

One new envelope code, joining Phase 2's `already_exists` / `not_ready` /
`job_active`:

- **`409 stale_content`** — the response file changed since the client
  loaded it (`base_sha256` mismatch, or the file vanished). The message
  names the stage and says the content changed on disk. The body carries no
  file content — the client refetches stage content to see the current
  state, keeping the envelope shape universal.

## Endpoint contracts

All new routes require `X-EP-Token` and the Host allowlist; bodies are JSON
under the existing 1 MiB cap.

**`GET /v1/runs/{topic}/stages/{stage}`** (existing) — payload gains
`"response_sha256": str | null` — sha256 hex of the response file bytes,
`null` when no response exists. Computed in `read_api.stage_content`.

**`PUT /v1/runs/{topic}/stages/{stage}/response`** — body
`{"text": str, "base_sha256": str}` (both required; `_require_str`).
→ `RunStore.edit_response`. The handler gains `do_PUT`, mirroring
`do_POST`'s auth gate, body parsing, and error mapping, with a
`_api_put_routes` table. Guarded by the topic-wide `job_active` check like
every run-mutating write. Success `200`:
```json
{"topic_id": "...", "stage": "...", "response_path": "stages/.../response.md", "response_sha256": "<new hash>"}
```
Errors: `404` unknown topic/no run; `400` bad stage/empty text/missing
fields; `409 stale_content`; `409 job_active`.
(`POST .../response` — paste — is unchanged, including its no-manifest-event
CLI parity.)

**`POST /v1/preview`** — body `{"text": str}` →
`{"html": "<rendered body markup>"}` via `render_html_body`. Pure function
of the body; touches no files; not subject to `job_active`. Errors: `400`
missing/non-string text. (Oversize bodies get the transport-level 413 like
every endpoint.)

## UI behavior

**ResponseEditor** (stage viewer, response tab). An **Edit** button shows
whenever a response exists and the run is not finalized. It swaps the
read-only response pane for a monospace textarea seeded with the loaded
content, remembering the `response_sha256` that came with it. Controls:

- **Save** — `PUT` with the remembered `base_sha256` via `useAction`
  (in-flight disable, envelope feedback). Success returns to the read view
  and refreshes stage content. If the stage was already approved, the
  refreshed server state resurfaces **Approve {stage}** (Phase 2's existing
  control, with its overwrite-confirm) — re-approving records the manifest
  event; the UI re-derives nothing.
- **Preview** — toggles a rendered pane beside the textarea, populated by
  `POST /v1/preview` on toggle and on a 500 ms debounce while typing. The
  HTML is injected with `dangerouslySetInnerHTML`; this is acceptable
  because the renderer escapes all content and emits no scripts, and the
  page is same-origin authed loopback.
- **Cancel** — discards the buffer after a `window.confirm` if it differs
  from the loaded content.

**Stale-save flow.** A `409 stale_content` keeps the editor open with the
buffer intact, shows the envelope message, and offers **Reload current
content** — which refetches stage content and shows the now-current file in
the adjacent read pane (with its new `response_sha256` adopted for the next
save). The user re-applies their changes by hand. The buffer is never
silently replaced.

**Compare (prompt vs response).** A toggle on the stage viewer lays the
prompt and response panes side by side. Plain layout of content the API
already serves — no diff; they are different documents.

**Diff against draft (draft vs repair).** On the repair stage only, a toggle
renders a line-level diff of the *approved draft* vs the *repair response*
(both already served by stage content endpoints), colored added/removed
lines, in an `overflow-x: auto` container.

**Diff module** — `web/src/lib/diff.ts`: dependency-free line-level LCS,
`diffLines(a: string, b: string) -> { type: "same" | "added" | "removed"; text: string }[]`.
Pure function, unit-tested in isolation. Guide-sized inputs (a few thousand
lines) are well within O(n·m) LCS on the client; no need for anything
fancier.

## Client additions (`web/src/api/`)

- `types.ts`: `response_sha256: string | null` on the stage-content type;
  `EditResponseResult`; `PreviewResult`.
- `client.ts`: `apiPut<T>(path, body)` (same request core as `apiPost`,
  method PUT), `putResponse(topicId, stage, text, baseSha256)`,
  `postPreview(text)`.

## Security notes (restated)

- The PUT route writes only through `RunStore.edit_response`; the HTTP layer
  never opens workspace files. No client-supplied paths anywhere.
- Preview renders untrusted text but the renderer escapes everything; the
  endpoint reads and writes no files.
- Token + Host allowlist on every new route; no CORS; `do_PUT` reuses the
  same guard as `do_POST`, so unauthenticated PUTs get 401 before routing.

## Testing requirements

**Backend (`tests/test_runs.py`, `tests/test_server.py`):**
- `edit_response`: happy path (write + manifest `response_edited` event +
  returned hash matches new content); stale hash → `StaleContentError`;
  missing response file → `ConfigError`; empty text → `ConfigError`;
  bad stage/topic → `ConfigError`.
- PUT endpoint: 200 happy path (and follow-up GET shows new content +
  new hash); 401 without token; 404 unknown topic; 400 missing fields;
  409 `stale_content` after an out-of-band file write; 409 `job_active`
  while a fake-provider job runs.
- Preview endpoint: 200 renders markdown; script-ish input comes back
  escaped; 400 on missing text; 401 without token.
- `stage_content` includes correct `response_sha256` (and `null` before any
  response).

**Frontend (Vitest):**
- `diff.ts`: same/added/removed cases, empty inputs, identical inputs.
- ResponseEditor: edit → save calls `putResponse` with the loaded hash;
  stale 409 keeps buffer + shows reload action; preview debounce calls
  `postPreview`; cancel-confirm on dirty buffer.
- Compare and draft-vs-repair toggles render both panes / diff rows from
  mocked stage content.

**E2E (Playwright, one new spec):** in the browser on an empty workspace —
run a topic to the repair stage (Phase 2 flow), edit the repair response,
save, re-approve, finalize; then, in a second scenario, load the editor,
write the response file directly on disk (simulating a concurrent external
edit), save from the browser, and assert the save is rejected with the
stale-content message and the on-disk external edit is still intact.

## Resolved design questions

1. Edit scope: **responses only** (prompts regenerated; approved/final
   immutable).
2. Conflict model: **content-hash precondition**, checked in the store call.
3. Editor: **plain textarea + preview** (no editor dependency).
4. Preview: **server-side via `export.py`** (faithful to export, zero deps).
5. Views: **prompt-vs-response and draft-vs-repair diff** (QA report view
   and conflict-diff view deselected).
6. Body cap: **stays 1 MiB**.
7. Post-approval edits: **allowed**; the approve control resurfaces and
   re-approval is recorded in the manifest.
