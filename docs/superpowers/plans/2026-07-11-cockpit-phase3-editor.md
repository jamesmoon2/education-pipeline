# Cockpit Phase 3 — In-browser Editing and Diff Views Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Edit a stage response in the browser and save it back safely (atomic content-hash precondition), with server-rendered markdown preview and side-by-side compare/diff views — an edit → save → approve → finalize loop entirely in the browser, where a concurrent external edit is detected and rejected, never overwritten.

**Architecture:** One new store method `RunStore.edit_response` (guarded read-modify-write with `base_sha256` precondition, new typed `StaleContentError`), extended `stage_content` payload (`response_sha256`), a new `do_PUT` handler with `PUT /v1/runs/{topic}/stages/{stage}/response`, a pure `POST /v1/preview` endpoint backed by `export.py`'s renderer (made public as `render_html_body`). The SPA gains a `ResponseEditor` component, a dependency-free line-diff module, and compare/diff toggles on the stage viewer.

**Tech Stack:** Python stdlib (`http.server`, `hashlib`), React 18 + TypeScript + Vite, Vitest + Testing Library, Playwright. Spec: `docs/superpowers/specs/2026-07-10-cockpit-phase3-editor-design.md`.

## Global Constraints

- Backend stays **stdlib-only**; frontend adds **no new npm dependencies**.
- Error envelope everywhere: `{"error": {"code", "message"}}`. New code: **`409 stale_content`** (joins `already_exists` / `not_ready` / `job_active`).
- Every new route requires `X-EP-Token` and the Host allowlist; no CORS.
- 1 MiB request-body cap stays (`MAX_REQUEST_BODY_BYTES`); no changes to it.
- HTTP layer never opens workspace files: all writes go through `RunStore`; no client-supplied paths.
- Run-mutating writes refuse with `409 job_active` while any job for the topic is non-terminal (the PUT edit is run-mutating; `/v1/preview` is pure and is NOT job-guarded).
- The UI derives available actions from server state, never pipeline logic.
- Out of scope: editing prompts/approved/final, merge UI, QA-report view, SSE, multi-user, raising the body cap.

## File Structure

Backend (modify only):
- `education_pipeline/export.py` — rename `_render_blocks` → public `render_html_body`.
- `education_pipeline/runs.py` — `StaleContentError`, `RunStore.edit_response`.
- `education_pipeline/__init__.py` — export `StaleContentError`, `render_html_body`.
- `education_pipeline/daemon/read_api.py` — `response_sha256` in `stage_content`.
- `education_pipeline/daemon/write_api.py` — `edit_response` payload builder.
- `education_pipeline/daemon/server.py` — `do_PUT` + `_api_put_routes`, `/v1/preview` POST route.

Frontend:
- Create `web/src/lib/diff.ts` (+ `web/src/lib/diff.test.ts`) — line-level LCS diff.
- Create `web/src/components/ResponseEditor.tsx` (+ test) — textarea editor with Save/Preview/Cancel and stale-save flow.
- Create `web/src/components/DiffView.tsx` — renders `diffLines` rows (covered by StageViewerPage tests).
- Modify `web/src/api/types.ts`, `web/src/api/client.ts` (+ `client.test.ts`) — `response_sha256`, `EditResponseResult`, `PreviewResult`, `apiPut`, `putResponse`, `postPreview`.
- Modify `web/src/pages/StageViewerPage.tsx` (+ test) — Edit button, compare toggle, draft-vs-repair diff toggle, approve-resurface condition.
- Modify `web/src/styles.css` — compare/editor/diff styles.
- Create `web/e2e/editor.spec.ts` — the two Playwright scenarios.

---

### Task 1: Public body-only markdown renderer (`render_html_body`)

**Files:**
- Modify: `education_pipeline/export.py` (rename `_render_blocks` at line 74; call site in `render_markdown_to_html` at line 57)
- Modify: `education_pipeline/__init__.py` (export block for `education_pipeline.export`, lines 30-34)
- Test: `tests/test_export.py`

**Interfaces:**
- Produces: `render_html_body(markdown_text: str) -> str` — body-only HTML (no `<!DOCTYPE>`, `<html>`, `<head>`, `<body>`), all content HTML-escaped, no scripts. Used by Task 5's `/v1/preview`.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_export.py`:

```python
def test_render_html_body_renders_body_only_markup() -> None:
    html = render_html_body("# Title\n\nSome **bold** text.")

    assert "<h1>Title</h1>" in html
    assert "<strong>bold</strong>" in html
    assert "<!DOCTYPE" not in html
    assert "<body>" not in html
    assert "<style>" not in html


def test_render_html_body_escapes_script_input() -> None:
    html = render_html_body("<script>alert(1)</script>")

    assert "<script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
```

Add `render_html_body` to the existing `from education_pipeline.export import (...)` import at the top of `tests/test_export.py`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_export.py -v -k render_html_body`
Expected: FAIL with `ImportError: cannot import name 'render_html_body'`

- [ ] **Step 3: Implement** — in `education_pipeline/export.py`, rename the function at line 74:

```python
def render_html_body(markdown_text: str) -> str:
    """Render a Markdown subset into body-only HTML markup.

    All content is HTML-escaped by the inline renderers and no scripts are
    ever emitted, so the output is safe to inject into an authed same-origin
    page (the cockpit preview) as well as the full export document.
    """

    lines = markdown_text.replace("\r\n", "\n").split("\n")
    ...  # body unchanged from _render_blocks
```

Keep the body exactly as `_render_blocks` had it. Update the one call site in `render_markdown_to_html` (line 57): `body = render_html_body(markdown_text)`. There are no other callers (verify: `grep -rn "_render_blocks" education_pipeline/ tests/`).

In `education_pipeline/__init__.py` add `render_html_body` to the `from education_pipeline.export import (...)` block (keep it alphabetized: after `build_markdown_bundle`, before `render_markdown_to_html`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_export.py -v`
Expected: all PASS (existing export tests confirm `render_markdown_to_html` still works after the rename)

- [ ] **Step 5: Commit**

```bash
git add education_pipeline/export.py education_pipeline/__init__.py tests/test_export.py
git commit -m "feat(export): expose body-only renderer as render_html_body"
```

---

### Task 2: `StaleContentError` and `RunStore.edit_response`

**Files:**
- Modify: `education_pipeline/runs.py` (add `import hashlib` near the top; add `StaleContentError` after the imports; add `edit_response` method right after `ingest_response`, ~line 377)
- Modify: `education_pipeline/__init__.py` (runs export block, lines 35+)
- Test: `tests/test_runs.py`

**Interfaces:**
- Consumes: existing `stage_paths`, `_write_text_atomic`, `_append_event` in `runs.py`.
- Produces: `RunStore.edit_response(topic_id: str, stage: str, text: str, *, base_sha256: str) -> Path` raising `ConfigError` (bad topic/stage, empty text, missing response file) or `StaleContentError` (hash mismatch). `class StaleContentError(Exception)`. Appends a `response_edited` manifest event. Both exported from `education_pipeline`. Task 4 wraps this.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_runs.py` (add `import hashlib` to the top imports and `StaleContentError` to the `from education_pipeline import (...)` block):

```python
def _response_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_edit_response_rewrites_content_and_records_event(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    store.create_run("t")
    path = store.ingest_response("t", "draft", "old body\n")

    result = store.edit_response(
        "t", "draft", "new body\n", base_sha256=_response_sha(path)
    )

    assert result == path
    assert path.read_text(encoding="utf-8") == "new body\n"
    assert _response_sha(path) == hashlib.sha256(b"new body\n").hexdigest()
    events = store.read_manifest("t")["events"]
    edited = [e for e in events if e["action"] == "response_edited"]
    assert len(edited) == 1
    assert edited[0]["stage"] == "draft"
    assert edited[0]["response_file"] == "responses/draft.response.md"
    assert edited[0]["recorded_at"]


def test_edit_response_rejects_stale_hash(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    store.create_run("t")
    path = store.ingest_response("t", "draft", "old body\n")
    loaded_sha = _response_sha(path)
    path.write_text("changed by someone else\n", encoding="utf-8")

    with pytest.raises(StaleContentError):
        store.edit_response("t", "draft", "my edit\n", base_sha256=loaded_sha)

    # The concurrent edit is never overwritten.
    assert path.read_text(encoding="utf-8") == "changed by someone else\n"


def test_edit_response_requires_existing_response(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    store.create_run("t")

    with pytest.raises(ConfigError):
        store.edit_response("t", "draft", "text\n", base_sha256="0" * 64)


def test_edit_response_rejects_empty_text(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    store.create_run("t")
    path = store.ingest_response("t", "draft", "old body\n")

    with pytest.raises(ConfigError):
        store.edit_response("t", "draft", "   \n", base_sha256=_response_sha(path))


def test_edit_response_rejects_bad_stage_and_topic(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    store.create_run("t")

    with pytest.raises(ConfigError):
        store.edit_response("t", "bogus", "text\n", base_sha256="0" * 64)
    with pytest.raises(ConfigError):
        store.edit_response("../evil", "draft", "text\n", base_sha256="0" * 64)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_runs.py -v -k edit_response`
Expected: FAIL with `ImportError: cannot import name 'StaleContentError'`

- [ ] **Step 3: Implement** — in `education_pipeline/runs.py`:

Add `import hashlib` alongside the existing `import json` / `import re`. After the import block (before `MANIFEST_SCHEMA_VERSION`), add:

```python
class StaleContentError(Exception):
    """The response file changed on disk since the client loaded it."""
```

Add the method to `RunStore`, directly after `ingest_response`:

```python
    def edit_response(
        self, topic_id: str, stage: str, text: str, *, base_sha256: str
    ) -> Path:
        """Guarded read-modify-write of an existing stage response.

        Unlike ``ingest_response`` (wholesale create/replace), editing
        presupposes content: the response file must exist and its current
        bytes must hash to ``base_sha256``, otherwise the file changed since
        the caller loaded it and :class:`StaleContentError` is raised. On a
        match the new text is written atomically and a ``response_edited``
        manifest event is recorded — an in-browser edit is an authored change
        worth auditing.
        """

        paths = self.stage_paths(topic_id, stage)
        if not text.strip():
            raise ConfigError(f"refusing to save empty response for stage {paths.stage!r}")
        if not paths.response_path.exists():
            raise ConfigError(
                f"no response to edit for stage {paths.stage!r}: {paths.response_path}"
            )
        current = hashlib.sha256(paths.response_path.read_bytes()).hexdigest()
        if current != base_sha256:
            raise StaleContentError(
                f"the {paths.stage} response changed on disk since it was loaded; "
                "reload the current content before saving"
            )
        _write_text_atomic(paths.response_path, text)
        self._append_event(
            paths.topic_id,
            stage=paths.stage,
            action="response_edited",
            files={"response_file": paths.response_path},
        )
        return paths.response_path
```

In `education_pipeline/__init__.py`, add `StaleContentError` to the `from education_pipeline.runs import (...)` block (alphabetized among the class names).

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_runs.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add education_pipeline/runs.py education_pipeline/__init__.py tests/test_runs.py
git commit -m "feat(runs): add edit_response with content-hash precondition"
```

---

### Task 3: `response_sha256` in the stage-content payload

**Files:**
- Modify: `education_pipeline/daemon/read_api.py` (`stage_content`, lines 96-109)
- Test: `tests/test_server.py`

**Interfaces:**
- Produces: `GET /v1/runs/{topic}/stages/{stage}` payload gains `"response_sha256": str | null` — sha256 hex of the response file bytes, `null` when no response exists. Tasks 7-9 consume it client-side.

- [ ] **Step 1: Write the failing test** — append to `tests/test_server.py` (near `test_stage_content_returns_prompt_and_nulls`):

```python
def test_stage_content_includes_response_sha256(server):
    import hashlib

    status, body = _req(server, "GET", "/v1/runs/t/stages/draft")
    assert status == 200
    assert body["response_sha256"] is None

    _req(server, "POST", "/v1/runs/t/stages/draft/response", body={"text": "BODY"})
    status, body = _req(server, "GET", "/v1/runs/t/stages/draft")
    assert status == 200
    assert body["response_sha256"] == hashlib.sha256(b"BODY").hexdigest()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_server.py -v -k response_sha256`
Expected: FAIL with `KeyError: 'response_sha256'`

- [ ] **Step 3: Implement** — in `education_pipeline/daemon/read_api.py`, add `import hashlib` to the imports, then in `stage_content` extend the returned dict:

```python
def stage_content(runs: RunStore, topic_id: str, stage: str) -> dict:
    require_run(runs, topic_id)
    paths = runs.stage_paths(topic_id, stage)  # ConfigError on bad stage -> 400

    def _read(path):
        return path.read_text(encoding="utf-8") if path.is_file() else None

    response_sha256 = (
        hashlib.sha256(paths.response_path.read_bytes()).hexdigest()
        if paths.response_path.is_file()
        else None
    )
    return {
        "topic_id": paths.topic_id,
        "stage": paths.stage,
        "prompt": _read(paths.prompt_path),
        "response": _read(paths.response_path),
        "approved": _read(paths.approved_path),
        "response_sha256": response_sha256,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_server.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add education_pipeline/daemon/read_api.py tests/test_server.py
git commit -m "feat(api): include response_sha256 in stage content"
```

---

### Task 4: `PUT /v1/runs/{topic}/stages/{stage}/response` (do_PUT + write_api.edit_response)

**Files:**
- Modify: `education_pipeline/daemon/write_api.py` (new `edit_response` after `ingest_response`, ~line 83; `import hashlib`; import `StaleContentError`)
- Modify: `education_pipeline/daemon/server.py` (new `do_PUT` + `_api_put_routes` after `_api_post_routes`)
- Test: `tests/test_server.py`

**Interfaces:**
- Consumes: `RunStore.edit_response(topic_id, stage, text, *, base_sha256)` and `StaleContentError` from Task 2; existing `_require_no_active_job`, `ConflictError`, `_run_relative`, `_require_str`, `_guard`, `_read_body`.
- Produces: `PUT /v1/runs/{topic}/stages/{stage}/response` with body `{"text": str, "base_sha256": str}` (both required) → 200 `{"topic_id", "stage", "response_path", "response_sha256"}`. Errors: 401 no token; 404 unknown topic/no run; 400 bad stage/empty text/missing fields; `409 stale_content` (hash mismatch or file vanished — body carries no file content); `409 job_active`. `write_api.edit_response(runs, jobs, topic_id, stage, text, *, base_sha256) -> dict`. Task 7's `putResponse` consumes this endpoint.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_server.py`:

```python
def _sha_hex(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_edit_response_put_happy_path(server):
    _req(server, "POST", "/v1/runs/t/stages/draft/response", body={"text": "V1"})
    status, body = _req(
        server,
        "PUT",
        "/v1/runs/t/stages/draft/response",
        body={"text": "V2", "base_sha256": _sha_hex("V1")},
    )
    assert status == 200
    assert body == {
        "topic_id": "t",
        "stage": "draft",
        "response_path": "responses/draft.response.md",
        "response_sha256": _sha_hex("V2"),
    }
    # follow-up GET shows the new content and the new hash
    status, got = _req(server, "GET", "/v1/runs/t/stages/draft")
    assert got["response"] == "V2"
    assert got["response_sha256"] == _sha_hex("V2")


def test_edit_response_put_requires_token(server):
    status, _ = _req(
        server,
        "PUT",
        "/v1/runs/t/stages/draft/response",
        token=None,
        body={"text": "x", "base_sha256": "0" * 64},
    )
    assert status == 401


def test_edit_response_put_unknown_topic_is_404(server):
    status, body = _req(
        server,
        "PUT",
        "/v1/runs/ghost/stages/draft/response",
        body={"text": "x", "base_sha256": "0" * 64},
    )
    assert status == 404 and body["error"]["code"] == "not_found"


def test_edit_response_put_missing_fields_are_400(server):
    _req(server, "POST", "/v1/runs/t/stages/draft/response", body={"text": "V1"})
    status, _ = _req(server, "PUT", "/v1/runs/t/stages/draft/response", body={"text": "x"})
    assert status == 400
    status, _ = _req(
        server, "PUT", "/v1/runs/t/stages/draft/response", body={"base_sha256": "0" * 64}
    )
    assert status == 400
    status, _ = _req(
        server,
        "PUT",
        "/v1/runs/t/stages/bogus/response",
        body={"text": "x", "base_sha256": "0" * 64},
    )
    assert status == 400


def test_edit_response_put_stale_after_external_write(server, tmp_path):
    _req(server, "POST", "/v1/runs/t/stages/draft/response", body={"text": "V1"})
    loaded_sha = _sha_hex("V1")
    response_file = tmp_path / "runs" / "t" / "responses" / "draft.response.md"
    response_file.write_text("EXTERNAL EDIT", encoding="utf-8")

    status, body = _req(
        server,
        "PUT",
        "/v1/runs/t/stages/draft/response",
        body={"text": "V2", "base_sha256": loaded_sha},
    )
    assert status == 409
    assert body["error"]["code"] == "stale_content"
    assert "draft" in body["error"]["message"]
    # the envelope carries no file content and the external edit is intact
    assert "EXTERNAL EDIT" not in json.dumps(body)
    assert response_file.read_text(encoding="utf-8") == "EXTERNAL EDIT"


def test_edit_response_put_missing_file_is_stale(server):
    status, body = _req(
        server,
        "PUT",
        "/v1/runs/t/stages/qa/response",
        body={"text": "x", "base_sha256": "0" * 64},
    )
    assert status == 409 and body["error"]["code"] == "stale_content"


def test_edit_response_put_blocked_while_job_active(server, monkeypatch):
    import time

    _req(server, "POST", "/v1/runs/t/stages/draft/response", body={"text": "V1"})
    monkeypatch.setenv("FAKE_DELAY", "5")
    status, job = _req(server, "POST", "/v1/jobs", body={"topic_id": "t", "stage": "draft"})
    assert status == 200

    status, body = _req(
        server,
        "PUT",
        "/v1/runs/t/stages/draft/response",
        body={"text": "V2", "base_sha256": _sha_hex("V1")},
    )
    assert status == 409 and body["error"]["code"] == "job_active"

    _req(server, "POST", f"/v1/jobs/{job['id']}/cancel")
    for _ in range(200):
        status, current = _req(server, "GET", f"/v1/jobs/{job['id']}")
        if current["status"] in {"succeeded", "failed", "canceled", "interrupted"}:
            break
        time.sleep(0.02)


def test_put_unknown_path_is_404(server):
    status, body = _req(server, "PUT", "/v1/nope", body={"text": "x"})
    assert status == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_server.py -v -k "edit_response_put or put_unknown"`
Expected: FAIL — `do_PUT` doesn't exist, so `http.server` answers `501 Unsupported method` and `_req` sees status 501 (assertions fail).

- [ ] **Step 3: Implement `write_api.edit_response`** — in `education_pipeline/daemon/write_api.py`, add `import hashlib` and change the runs import to `from education_pipeline.runs import RunStore, StaleContentError`. Insert after `ingest_response`:

```python
def edit_response(
    runs: RunStore,
    jobs: JobStore,
    topic_id: str,
    stage: str,
    text: str,
    *,
    base_sha256: str,
) -> dict:
    read_api.require_run(runs, topic_id)
    _require_no_active_job(jobs, topic_id)
    paths = runs.stage_paths(topic_id, stage)
    if not paths.response_path.exists():
        raise ConflictError(
            "stale_content",
            f"the {paths.stage} response no longer exists on disk; "
            "reload the current stage content",
        )
    try:
        path = runs.edit_response(topic_id, stage, text, base_sha256=base_sha256)
    except StaleContentError as exc:
        raise ConflictError("stale_content", str(exc)) from exc
    return {
        "topic_id": paths.topic_id,
        "stage": paths.stage,
        "response_path": _run_relative(runs, topic_id, path),
        "response_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }
```

Also add `stale_content` to the conflict-code list in the module docstring (line 9-10).

- [ ] **Step 4: Implement `do_PUT`** — in `education_pipeline/daemon/server.py`, insert after `_api_post_routes` (mirroring `do_POST`'s auth gate and error mapping exactly):

```python
        def do_PUT(self):
            if not self._guard():
                return
            try:
                return self._api_put_routes()
            except read_api.NotFoundError as exc:
                return self._error(404, "not_found", str(exc))
            except write_api.ConflictError as exc:
                return self._error(409, exc.code, str(exc))
            except ConfigError as exc:
                return self._error(400, "bad_request", str(exc))

        def _api_put_routes(self):
            m = re.match(r"^/v1/runs/([^/?]+)/stages/([^/?]+)/response$", self.path)
            if m:
                body = self._read_body()
                return self._send(
                    200,
                    write_api.edit_response(
                        context.runs,
                        context.store,
                        m.group(1),
                        m.group(2),
                        _require_str(body, "text"),
                        base_sha256=_require_str(body, "base_sha256"),
                    ),
                )
            self._error(404, "not_found", "unknown path")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_server.py tests/test_runs.py -v`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add education_pipeline/daemon/write_api.py education_pipeline/daemon/server.py tests/test_server.py
git commit -m "feat(api): PUT stage response with stale_content conflict detection"
```

---

### Task 5: `POST /v1/preview` endpoint

**Files:**
- Modify: `education_pipeline/daemon/server.py` (import `render_html_body`; new route at the top of `_api_post_routes`)
- Test: `tests/test_server.py`

**Interfaces:**
- Consumes: `render_html_body(markdown_text) -> str` from Task 1.
- Produces: `POST /v1/preview`, body `{"text": str}` → 200 `{"html": "<rendered body markup>"}`. Pure function of the body; touches no files; NOT subject to `job_active`. Errors: 400 missing/non-string text; 401 without token. Task 7's `postPreview` consumes it.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_server.py`:

```python
def test_preview_renders_markdown_body(server):
    status, body = _req(
        server, "POST", "/v1/preview", body={"text": "# Hi\n\nSome **bold** text."}
    )
    assert status == 200
    assert "<h1>Hi</h1>" in body["html"]
    assert "<strong>bold</strong>" in body["html"]
    assert "<!DOCTYPE" not in body["html"]


def test_preview_escapes_script_input(server):
    status, body = _req(
        server, "POST", "/v1/preview", body={"text": "<script>alert(1)</script>"}
    )
    assert status == 200
    assert "<script>" not in body["html"]
    assert "&lt;script&gt;" in body["html"]


def test_preview_missing_text_is_400(server):
    status, _ = _req(server, "POST", "/v1/preview", body={})
    assert status == 400
    status, _ = _req(server, "POST", "/v1/preview", body={"text": 42})
    assert status == 400


def test_preview_requires_token(server):
    status, _ = _req(server, "POST", "/v1/preview", token=None, body={"text": "x"})
    assert status == 401


def test_preview_not_blocked_by_active_job(server, monkeypatch):
    import time

    monkeypatch.setenv("FAKE_DELAY", "5")
    status, job = _req(server, "POST", "/v1/jobs", body={"topic_id": "t", "stage": "draft"})
    assert status == 200

    status, body = _req(server, "POST", "/v1/preview", body={"text": "# still works"})
    assert status == 200 and "<h1>still works</h1>" in body["html"]

    _req(server, "POST", f"/v1/jobs/{job['id']}/cancel")
    for _ in range(200):
        status, current = _req(server, "GET", f"/v1/jobs/{job['id']}")
        if current["status"] in {"succeeded", "failed", "canceled", "interrupted"}:
            break
        time.sleep(0.02)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_server.py -v -k preview`
Expected: FAIL with 404 responses (`not_found` — unknown path)

- [ ] **Step 3: Implement** — in `education_pipeline/daemon/server.py`, add the import:

```python
from education_pipeline.export import render_html_body
```

and add at the top of `_api_post_routes` (before the `/v1/jobs` check):

```python
            if self.path == "/v1/preview":
                body = self._read_body()
                return self._send(
                    200, {"html": render_html_body(_require_str(body, "text"))}
                )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_server.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add education_pipeline/daemon/server.py tests/test_server.py
git commit -m "feat(api): server-side markdown preview endpoint"
```

---

### Task 6: Dependency-free line-diff module (`web/src/lib/diff.ts`)

**Files:**
- Create: `web/src/lib/diff.ts`
- Test: `web/src/lib/diff.test.ts`

**Interfaces:**
- Produces: `diffLines(a: string, b: string): DiffLine[]` where `interface DiffLine { type: "same" | "added" | "removed"; text: string }`. Pure function, line-level LCS, O(n·m). Task 10's `DiffView` consumes it.

- [ ] **Step 1: Write the failing tests** — create `web/src/lib/diff.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { diffLines } from "./diff";

describe("diffLines", () => {
  it("marks identical inputs as all same", () => {
    expect(diffLines("a\nb\nc", "a\nb\nc")).toEqual([
      { type: "same", text: "a" },
      { type: "same", text: "b" },
      { type: "same", text: "c" },
    ]);
  });

  it("marks added and removed lines around a common core", () => {
    expect(diffLines("keep\nold line\nend", "keep\nnew line\nend")).toEqual([
      { type: "same", text: "keep" },
      { type: "removed", text: "old line" },
      { type: "added", text: "new line" },
      { type: "same", text: "end" },
    ]);
  });

  it("treats an empty left input as all additions", () => {
    expect(diffLines("", "a\nb")).toEqual([
      { type: "added", text: "a" },
      { type: "added", text: "b" },
    ]);
  });

  it("treats an empty right input as all removals", () => {
    expect(diffLines("a\nb", "")).toEqual([
      { type: "removed", text: "a" },
      { type: "removed", text: "b" },
    ]);
  });

  it("returns an empty diff for two empty inputs", () => {
    expect(diffLines("", "")).toEqual([]);
  });

  it("finds the longest common subsequence, not just a prefix match", () => {
    expect(diffLines("x\ncommon\ny", "common")).toEqual([
      { type: "removed", text: "x" },
      { type: "same", text: "common" },
      { type: "removed", text: "y" },
    ]);
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd web && npx vitest run src/lib/diff.test.ts`
Expected: FAIL — cannot resolve `./diff`

- [ ] **Step 3: Implement** — create `web/src/lib/diff.ts`:

```ts
export interface DiffLine {
  type: "same" | "added" | "removed";
  text: string;
}

function toLines(text: string): string[] {
  return text === "" ? [] : text.split("\n");
}

/**
 * Line-level diff via longest-common-subsequence. O(n·m) time and space,
 * which is fine for guide-sized inputs (a few thousand lines).
 */
export function diffLines(a: string, b: string): DiffLine[] {
  const left = toLines(a);
  const right = toLines(b);
  const n = left.length;
  const m = right.length;

  // lcs[i][j] = LCS length of left[i:] vs right[j:]
  const lcs: number[][] = Array.from({ length: n + 1 }, () =>
    new Array<number>(m + 1).fill(0),
  );
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      lcs[i][j] =
        left[i] === right[j]
          ? lcs[i + 1][j + 1] + 1
          : Math.max(lcs[i + 1][j], lcs[i][j + 1]);
    }
  }

  const out: DiffLine[] = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (left[i] === right[j]) {
      out.push({ type: "same", text: left[i] });
      i++;
      j++;
    } else if (lcs[i + 1][j] >= lcs[i][j + 1]) {
      out.push({ type: "removed", text: left[i] });
      i++;
    } else {
      out.push({ type: "added", text: right[j] });
      j++;
    }
  }
  while (i < n) out.push({ type: "removed", text: left[i++] });
  while (j < m) out.push({ type: "added", text: right[j++] });
  return out;
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd web && npx vitest run src/lib/diff.test.ts`
Expected: 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/diff.ts web/src/lib/diff.test.ts
git commit -m "feat(web): dependency-free line-level LCS diff module"
```

---

### Task 7: API client additions (`types.ts`, `client.ts`)

**Files:**
- Modify: `web/src/api/types.ts` (`StageContent`; new result types)
- Modify: `web/src/api/client.ts` (`apiPut`, `putResponse`, `postPreview`)
- Test: `web/src/api/client.test.ts`

**Interfaces:**
- Consumes: endpoints from Tasks 3-5; existing `request<T>` core in `client.ts`.
- Produces (Tasks 8-10 rely on these exact names):
  - `StageContent` gains `response_sha256: string | null`
  - `interface EditResponseResult { topic_id: string; stage: string; response_path: string; response_sha256: string }`
  - `interface PreviewResult { html: string }`
  - `apiPut<T>(path: string, body: unknown): Promise<T>`
  - `putResponse(topicId: string, stage: string, text: string, baseSha256: string): Promise<EditResponseResult>`
  - `postPreview(text: string): Promise<PreviewResult>`

- [ ] **Step 1: Write the failing tests** — append to `web/src/api/client.test.ts` (extend the top import from `./client` with `postPreview, putResponse`):

```ts
describe("apiPut", () => {
  afterEach(() => {
    resetSessionForTests();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("putResponse sends a JSON PUT with text and base_sha256", async () => {
    const fetchMock = mockFetchWithInit({
      "/v1/session": { status: 200, body: { token: "tok", version: "0.1.0" } },
      "/v1/runs/t/stages/draft/response": {
        status: 200,
        body: {
          topic_id: "t",
          stage: "draft",
          response_path: "responses/draft.response.md",
          response_sha256: "hash-2",
        },
      },
    });
    vi.stubGlobal("fetch", fetchMock);

    const result = await putResponse("t", "draft", "new body", "hash-1");

    expect(result.response_sha256).toBe("hash-2");
    const call = fetchMock.mock.calls.find(
      ([u]) => String(u) === "/v1/runs/t/stages/draft/response",
    );
    const init = call![1] as RequestInit;
    expect(init.method).toBe("PUT");
    expect(init.headers).toMatchObject({
      "X-EP-Token": "tok",
      "Content-Type": "application/json",
    });
    expect(JSON.parse(init.body as string)).toEqual({
      text: "new body",
      base_sha256: "hash-1",
    });
  });

  it("surfaces the stale_content conflict code", async () => {
    vi.stubGlobal(
      "fetch",
      mockFetchWithInit({
        "/v1/session": { status: 200, body: { token: "tok", version: "0.1.0" } },
        "/v1/runs/t/stages/draft/response": {
          status: 409,
          body: { error: { code: "stale_content", message: "changed on disk" } },
        },
      }),
    );
    const err = (await putResponse("t", "draft", "x", "old").catch(
      (e: unknown) => e,
    )) as ApiRequestError;
    expect(err).toBeInstanceOf(ApiRequestError);
    expect(err.status).toBe(409);
    expect(err.code).toBe("stale_content");
  });

  it("postPreview posts text and returns html", async () => {
    const fetchMock = mockFetchWithInit({
      "/v1/session": { status: 200, body: { token: "tok", version: "0.1.0" } },
      "/v1/preview": { status: 200, body: { html: "<h1>Hi</h1>" } },
    });
    vi.stubGlobal("fetch", fetchMock);

    const result = await postPreview("# Hi");

    expect(result.html).toBe("<h1>Hi</h1>");
    const call = fetchMock.mock.calls.find(([u]) => String(u) === "/v1/preview");
    expect(JSON.parse((call![1] as RequestInit).body as string)).toEqual({
      text: "# Hi",
    });
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd web && npx vitest run src/api/client.test.ts`
Expected: FAIL — `putResponse` / `postPreview` are not exported

- [ ] **Step 3: Implement types** — in `web/src/api/types.ts`, extend `StageContent` and add the new result types after `ExportResult`:

```ts
export interface StageContent {
  topic_id: string;
  stage: string;
  prompt: string | null;
  response: string | null;
  approved: string | null;
  response_sha256: string | null;
}

export interface EditResponseResult {
  topic_id: string;
  stage: string;
  response_path: string;
  response_sha256: string;
}

export interface PreviewResult {
  html: string;
}
```

- [ ] **Step 4: Implement client functions** — in `web/src/api/client.ts`, add `EditResponseResult` and `PreviewResult` to the type import, then after `apiPost`:

```ts
export async function apiPut<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}
```

and with the other endpoint helpers (after `postResponse`):

```ts
export const putResponse = (
  topicId: string,
  stage: string,
  text: string,
  baseSha256: string,
) =>
  apiPut<EditResponseResult>(
    `/v1/runs/${encodeURIComponent(topicId)}/stages/${encodeURIComponent(stage)}/response`,
    { text, base_sha256: baseSha256 },
  );
export const postPreview = (text: string) =>
  apiPost<PreviewResult>("/v1/preview", { text });
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd web && npx vitest run && npx tsc --noEmit`
Expected: all vitest suites PASS; tsc clean. (If tsc flags existing test mocks missing `response_sha256`, that is Task 9's concern only if it appears — `StageViewerPage.test.tsx` mock objects will now be missing the field; add `response_sha256: null` to each `getStageContent` mock literal in that file to keep tsc green.)

- [ ] **Step 6: Commit**

```bash
git add web/src/api/types.ts web/src/api/client.ts web/src/api/client.test.ts web/src/pages/StageViewerPage.test.tsx
git commit -m "feat(web): apiPut, putResponse, postPreview and phase-3 types"
```

---

### Task 8: `ResponseEditor` component

**Files:**
- Create: `web/src/components/ResponseEditor.tsx`
- Test: `web/src/components/ResponseEditor.test.tsx`

**Interfaces:**
- Consumes: `putResponse`, `postPreview`, `getStageContent`, `ApiRequestError` (Task 7); `useAction` hook.
- Produces: `ResponseEditor` default export with props `{ topicId: string; stage: string; content: string; contentSha256: string; onSaved: () => void; onClose: () => void }`. Task 9 mounts it. Behavior: monospace textarea seeded with `content`; remembers `contentSha256` as the save precondition; Save PUTs via `useAction`; Preview toggles a server-rendered pane (populate on toggle + 500 ms debounce while typing, injected with `dangerouslySetInnerHTML` — acceptable because the renderer escapes all content and emits no scripts on an authed same-origin loopback page); Cancel confirms if dirty; a `409 stale_content` keeps the buffer, shows the envelope message, and offers **Reload current content** which refetches stage content into an adjacent read pane and adopts the new hash for the next save. The buffer is never silently replaced.

- [ ] **Step 1: Write the failing tests** — create `web/src/components/ResponseEditor.test.tsx`:

```tsx
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import ResponseEditor from "./ResponseEditor";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return {
    ApiRequestError: actual.ApiRequestError,
    putResponse: vi.fn(),
    postPreview: vi.fn(),
    getStageContent: vi.fn(),
  };
});

import {
  ApiRequestError,
  getStageContent,
  postPreview,
  putResponse,
} from "../api/client";

function renderEditor(overrides: Partial<Parameters<typeof ResponseEditor>[0]> = {}) {
  const props = {
    topicId: "t",
    stage: "repair",
    content: "original body",
    contentSha256: "sha-1",
    onSaved: vi.fn(),
    onClose: vi.fn(),
    ...overrides,
  };
  render(<ResponseEditor {...props} />);
  return props;
}

describe("ResponseEditor", () => {
  afterEach(() => {
    vi.clearAllMocks();
    vi.useRealTimers();
  });

  it("saves the buffer with the remembered base hash", async () => {
    vi.mocked(putResponse).mockResolvedValue({
      topic_id: "t",
      stage: "repair",
      response_path: "responses/repair.response.md",
      response_sha256: "sha-2",
    });
    const props = renderEditor();

    const textarea = screen.getByLabelText("Edit response for repair");
    await userEvent.clear(textarea);
    await userEvent.type(textarea, "edited body");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(putResponse).toHaveBeenCalledWith("t", "repair", "edited body", "sha-1");
    await waitFor(() => expect(props.onSaved).toHaveBeenCalled());
  });

  it("keeps the buffer and offers reload on a stale 409", async () => {
    vi.mocked(putResponse).mockRejectedValue(
      new ApiRequestError(409, "stale_content", "the repair response changed on disk"),
    );
    vi.mocked(getStageContent).mockResolvedValue({
      topic_id: "t",
      stage: "repair",
      prompt: null,
      response: "external content",
      approved: null,
      response_sha256: "sha-external",
    });
    const props = renderEditor();

    const textarea = screen.getByLabelText("Edit response for repair");
    await userEvent.clear(textarea);
    await userEvent.type(textarea, "my edit");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    // envelope message shown, buffer intact, editor still open
    expect(await screen.findByText(/changed on disk/)).toBeInTheDocument();
    expect(textarea).toHaveValue("my edit");
    expect(props.onSaved).not.toHaveBeenCalled();

    // reload shows the now-current content beside the buffer …
    await userEvent.click(
      screen.getByRole("button", { name: "Reload current content" }),
    );
    expect(await screen.findByText("external content")).toBeInTheDocument();
    expect(textarea).toHaveValue("my edit");

    // … and the next save uses the adopted hash
    vi.mocked(putResponse).mockResolvedValue({
      topic_id: "t",
      stage: "repair",
      response_path: "responses/repair.response.md",
      response_sha256: "sha-3",
    });
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(putResponse).toHaveBeenLastCalledWith("t", "repair", "my edit", "sha-external");
  });

  it("populates the preview on toggle and debounces while typing", async () => {
    vi.mocked(postPreview).mockResolvedValue({ html: "<h1>Rendered</h1>" });
    renderEditor();
    vi.useFakeTimers();

    fireEvent.click(screen.getByRole("button", { name: "Preview" }));
    expect(postPreview).toHaveBeenCalledWith("original body");

    fireEvent.change(screen.getByLabelText("Edit response for repair"), {
      target: { value: "# typed" },
    });
    expect(postPreview).not.toHaveBeenCalledWith("# typed");
    await vi.advanceTimersByTimeAsync(500);
    expect(postPreview).toHaveBeenCalledWith("# typed");
  });

  it("confirms before discarding a dirty buffer on cancel", async () => {
    const props = renderEditor();
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);

    const textarea = screen.getByLabelText("Edit response for repair");
    await userEvent.type(textarea, " plus more");
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(confirmSpy).toHaveBeenCalled();
    expect(props.onClose).not.toHaveBeenCalled();

    confirmSpy.mockReturnValue(true);
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(props.onClose).toHaveBeenCalled();
  });

  it("cancels without confirm when the buffer is clean", async () => {
    const props = renderEditor();
    const confirmSpy = vi.spyOn(window, "confirm");

    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(confirmSpy).not.toHaveBeenCalled();
    expect(props.onClose).toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd web && npx vitest run src/components/ResponseEditor.test.tsx`
Expected: FAIL — cannot resolve `./ResponseEditor`

- [ ] **Step 3: Implement** — create `web/src/components/ResponseEditor.tsx`:

```tsx
import { useEffect, useState } from "react";
import {
  ApiRequestError,
  getStageContent,
  postPreview,
  putResponse,
} from "../api/client";
import { useAction } from "../hooks/useAction";

export default function ResponseEditor({
  topicId,
  stage,
  content,
  contentSha256,
  onSaved,
  onClose,
}: {
  topicId: string;
  stage: string;
  content: string;
  contentSha256: string;
  onSaved: () => void;
  onClose: () => void;
}) {
  const [buffer, setBuffer] = useState(content);
  // The save precondition: only adopted from the server, never from polling,
  // so an external edit can never be silently overwritten.
  const [baseSha, setBaseSha] = useState(contentSha256);
  const [stale, setStale] = useState(false);
  const [currentOnDisk, setCurrentOnDisk] = useState<string | null>(null);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewHtml, setPreviewHtml] = useState("");
  const save = useAction(onSaved);

  useEffect(() => {
    if (!previewOpen) return;
    const timer = window.setTimeout(() => {
      postPreview(buffer)
        .then((r) => setPreviewHtml(r.html))
        .catch(() => {}); // keep the last good preview on transient errors
    }, 500);
    return () => window.clearTimeout(timer);
  }, [previewOpen, buffer]);

  const togglePreview = () => {
    const next = !previewOpen;
    setPreviewOpen(next);
    if (next) {
      postPreview(buffer)
        .then((r) => setPreviewHtml(r.html))
        .catch(() => {});
    }
  };

  const doSave = () =>
    save.run(async () => {
      try {
        await putResponse(topicId, stage, buffer, baseSha);
        setStale(false);
      } catch (err) {
        if (
          err instanceof ApiRequestError &&
          err.status === 409 &&
          err.code === "stale_content"
        ) {
          setStale(true);
        }
        throw err;
      }
    });

  const reload = async () => {
    const fresh = await getStageContent(topicId, stage);
    setCurrentOnDisk(fresh.response ?? "(the response was deleted on disk)");
    if (fresh.response_sha256 !== null) setBaseSha(fresh.response_sha256);
    setStale(false);
  };

  const cancel = () => {
    if (buffer !== content && !window.confirm("Discard unsaved changes?")) return;
    onClose();
  };

  return (
    <div className="response-editor">
      <div className="editor-panes">
        <label>
          Edit response for {stage}
          <textarea
            value={buffer}
            onChange={(e) => setBuffer(e.target.value)}
            rows={20}
          />
        </label>
        {previewOpen && (
          <div
            className="preview content"
            // Safe: the server renderer escapes all content and emits no
            // scripts, and this page is same-origin authed loopback.
            dangerouslySetInnerHTML={{ __html: previewHtml }}
          />
        )}
        {currentOnDisk !== null && <pre className="content">{currentOnDisk}</pre>}
      </div>
      <div className="editor-controls">
        <button disabled={save.busy || !buffer.trim()} onClick={doSave}>
          Save
        </button>
        <button onClick={togglePreview}>
          {previewOpen ? "Hide preview" : "Preview"}
        </button>
        <button onClick={cancel}>Cancel</button>
        {stale && (
          <button onClick={() => void reload()}>Reload current content</button>
        )}
      </div>
      {save.feedback && (
        <p className={save.isError ? "error" : "success"}>{save.feedback}</p>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd web && npx vitest run src/components/ResponseEditor.test.tsx`
Expected: 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add web/src/components/ResponseEditor.tsx web/src/components/ResponseEditor.test.tsx
git commit -m "feat(web): ResponseEditor with stale-save reload flow and preview"
```

---

### Task 9: Stage viewer integration — Edit button, finalized gating, approve resurface

**Files:**
- Modify: `web/src/pages/StageViewerPage.tsx`
- Modify: `web/src/pages/StageViewerPage.test.tsx`
- Modify: `web/src/styles.css` (append editor styles)

**Interfaces:**
- Consumes: `ResponseEditor` (Task 8); `getRunStatus` (existing client fn) for the run's `finalized` flag; `StageContent.response_sha256` (Task 7).
- Produces: Response tab shows **Edit** whenever a response exists and the run is not finalized; while editing, the read-only pane is replaced by `ResponseEditor`; on save the page returns to the read view and refreshes. The **Approve {stage}** button condition becomes `response !== null && (approved === null || approved !== response)` so that after an edit of an approved stage the refreshed server state resurfaces it (its existing `retryWithOverwrite` confirm handles the `already_exists` re-approve).

- [ ] **Step 1: Update the mock factory and write the failing tests** — in `web/src/pages/StageViewerPage.test.tsx`, replace the `vi.mock` factory and its import so `getRunStatus` is available:

```tsx
vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return {
    ApiRequestError: actual.ApiRequestError,
    getStageContent: vi.fn(),
    getRunStatus: vi.fn(),
    postApprove: vi.fn(),
    postResponse: vi.fn(),
    putResponse: vi.fn(),
    postPreview: vi.fn(),
  };
});

import {
  getRunStatus,
  getStageContent,
  postApprove,
  postResponse,
  putResponse,
} from "../api/client";
```

Add a helper and a `beforeEach` (import `beforeEach` from vitest) so every existing test has a run status:

```tsx
function mockRun(finalized = false) {
  vi.mocked(getRunStatus).mockResolvedValue({
    topic_id: "t",
    finalized,
    stages: [],
    next_action: { topic_id: "t", stage: null, action: "done", detail: "" },
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  mockRun();
});
```

Ensure every existing `getStageContent` mock literal includes `response_sha256` (e.g. `response_sha256: "sha-1"` when `response` is non-null, `response_sha256: null` otherwise). Then add the new tests:

```tsx
  it("offers Edit on the response tab and opens the editor", async () => {
    vi.mocked(getStageContent).mockResolvedValue({
      topic_id: "t",
      stage: "draft",
      prompt: "# prompt",
      response: "response body",
      approved: null,
      response_sha256: "sha-1",
    });
    vi.mocked(putResponse).mockResolvedValue({
      topic_id: "t",
      stage: "draft",
      response_path: "responses/draft.response.md",
      response_sha256: "sha-2",
    });
    renderAt("/topics/t/stages/draft");
    await userEvent.click(await screen.findByRole("tab", { name: /^response/ }));
    await userEvent.click(await screen.findByRole("button", { name: "Edit" }));

    const textarea = screen.getByLabelText("Edit response for draft");
    expect(textarea).toHaveValue("response body");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(putResponse).toHaveBeenCalledWith("t", "draft", "response body", "sha-1");
    // returns to the read view after a successful save
    expect(
      await screen.findByRole("button", { name: "Edit" }),
    ).toBeInTheDocument();
  });

  it("hides Edit when the run is finalized", async () => {
    mockRun(true);
    vi.mocked(getStageContent).mockResolvedValue({
      topic_id: "t",
      stage: "draft",
      prompt: "# prompt",
      response: "response body",
      approved: "response body",
      response_sha256: "sha-1",
    });
    renderAt("/topics/t/stages/draft");
    await userEvent.click(await screen.findByRole("tab", { name: /^response/ }));
    expect(screen.queryByRole("button", { name: "Edit" })).not.toBeInTheDocument();
  });

  it("resurfaces Approve when the response differs from the approved copy", async () => {
    vi.mocked(getStageContent).mockResolvedValue({
      topic_id: "t",
      stage: "draft",
      prompt: "# prompt",
      response: "edited body",
      approved: "previously approved body",
      response_sha256: "sha-1",
    });
    renderAt("/topics/t/stages/draft");
    expect(
      await screen.findByRole("button", { name: "Approve draft" }),
    ).toBeInTheDocument();
  });
```

The existing test `offers neither action once approved` (where `approved === response`) must keep passing unchanged — it pins the non-resurfaced case.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd web && npx vitest run src/pages/StageViewerPage.test.tsx`
Expected: the three new tests FAIL (no Edit button; Approve absent when approved is non-null)

- [ ] **Step 3: Implement** — rewrite `web/src/pages/StageViewerPage.tsx`:

```tsx
import { useCallback, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  ApiRequestError,
  getRunStatus,
  getStageContent,
  postApprove,
} from "../api/client";
import ResponseEditor from "../components/ResponseEditor";
import ResponseForm from "../components/ResponseForm";
import { useAction } from "../hooks/useAction";
import { usePolling } from "../hooks/usePolling";

const TABS = ["prompt", "response", "approved"] as const;
type Tab = (typeof TABS)[number];

export default function StageViewerPage() {
  const { topicId, stage } = useParams<{ topicId: string; stage: string }>();
  const fetchContent = useCallback(
    () => getStageContent(topicId!, stage!),
    [topicId, stage],
  );
  const fetchRun = useCallback(() => getRunStatus(topicId!), [topicId]);
  const { data, error, refresh } = usePolling(fetchContent, 5_000);
  const { data: run } = usePolling(fetchRun, 5_000);
  const [tab, setTab] = useState<Tab>("prompt");
  const [pasteOpen, setPasteOpen] = useState(false);
  const [editing, setEditing] = useState(false);
  const approve = useAction(refresh);

  if (error instanceof ApiRequestError && error.status === 404) {
    return (
      <p>
        No run started for <strong>{topicId}</strong>.
      </p>
    );
  }
  if (error) return <p className="error">{error.message}</p>;
  if (!data) return <p>Loading…</p>;

  const finalized = run ? run.finalized : true; // hide Edit until status loads
  const canEdit = data.response !== null && !finalized;
  const needsApproval =
    data.response !== null &&
    (data.approved === null || data.approved !== data.response);
  const showEditor = editing && canEdit && tab === "response";

  return (
    <div>
      <p>
        <Link to={`/topics/${topicId}`}>← back to {topicId}</Link>
      </p>
      <h2>
        {topicId} / {data.stage}
      </h2>
      <nav className="tabs" role="tablist">
        {TABS.map((t) => (
          <button
            key={t}
            role="tab"
            aria-selected={t === tab}
            className={t === tab ? "tab active" : "tab"}
            onClick={() => setTab(t)}
          >
            {t}
            {data[t] === null ? " (empty)" : ""}
          </button>
        ))}
      </nav>
      {showEditor ? (
        <ResponseEditor
          topicId={topicId!}
          stage={data.stage}
          content={data.response ?? ""}
          contentSha256={data.response_sha256 ?? ""}
          onSaved={() => {
            setEditing(false);
            refresh();
          }}
          onClose={() => setEditing(false)}
        />
      ) : (
        <pre className="content">{data[tab] ?? `(no ${tab} yet)`}</pre>
      )}
      {tab === "response" && canEdit && !editing && (
        <button onClick={() => setEditing(true)}>Edit</button>
      )}
      {data.response === null && (
        <div>
          <button onClick={() => setPasteOpen((open) => !open)}>Paste response…</button>
          {pasteOpen && (
            <ResponseForm
              topicId={topicId!}
              stage={data.stage}
              onDone={() => {
                setPasteOpen(false);
                refresh();
              }}
            />
          )}
        </div>
      )}
      {needsApproval && (
        <button
          disabled={approve.busy}
          onClick={() =>
            approve.run(() => postApprove(topicId!, data.stage), {
              retryWithOverwrite: () => postApprove(topicId!, data.stage, true),
              successMessage: `Approved ${data.stage}.`,
            })
          }
        >
          Approve {data.stage}
        </button>
      )}
      {approve.feedback && (
        <p className={approve.isError ? "error" : "success"}>{approve.feedback}</p>
      )}
    </div>
  );
}
```

Append to `web/src/styles.css`:

```css
/* Phase 3: response editor */
.editor-panes {
  display: flex;
  gap: 1rem;
  align-items: flex-start;
}
.editor-panes label {
  flex: 1;
  min-width: 0;
}
.editor-panes textarea {
  width: 100%;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}
.editor-panes .preview,
.editor-panes .content {
  flex: 1;
  min-width: 0;
  overflow-x: auto;
}
.editor-controls {
  display: flex;
  gap: 0.5rem;
  margin-top: 0.5rem;
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd web && npx vitest run && npx tsc --noEmit`
Expected: all PASS (including the untouched `offers neither action once approved` pin), tsc clean

- [ ] **Step 5: Commit**

```bash
git add web/src/pages/StageViewerPage.tsx web/src/pages/StageViewerPage.test.tsx web/src/styles.css
git commit -m "feat(web): in-browser response editing on the stage viewer"
```

---

### Task 10: Compare (prompt vs response) and draft-vs-repair diff views

**Files:**
- Create: `web/src/components/DiffView.tsx`
- Modify: `web/src/pages/StageViewerPage.tsx`
- Modify: `web/src/pages/StageViewerPage.test.tsx`
- Modify: `web/src/styles.css` (append compare/diff styles)

**Interfaces:**
- Consumes: `diffLines` (Task 6); `getStageContent` for the draft stage's `approved` content.
- Produces: `DiffView` default export with props `{ a: string; b: string }` rendering line rows in an `overflow-x: auto` container. Stage viewer gains a **Compare prompt ↔ response** toggle (plain two-pane, no diff) and — on the repair stage only — a **Diff against draft** toggle rendering `diffLines(approvedDraft, repairResponse)` with colored added/removed lines.

- [ ] **Step 1: Write the failing tests** — append to `web/src/pages/StageViewerPage.test.tsx`:

```tsx
  it("compare toggle lays prompt and response side by side", async () => {
    vi.mocked(getStageContent).mockResolvedValue({
      topic_id: "t",
      stage: "draft",
      prompt: "the prompt text",
      response: "the response text",
      approved: null,
      response_sha256: "sha-1",
    });
    renderAt("/topics/t/stages/draft");
    await userEvent.click(
      await screen.findByRole("button", { name: "Compare prompt ↔ response" }),
    );
    expect(screen.getByText("the prompt text")).toBeInTheDocument();
    expect(screen.getByText("the response text")).toBeInTheDocument();
    // toggling back returns to the single tab pane
    await userEvent.click(screen.getByRole("button", { name: "Single pane" }));
    expect(screen.queryByText("the response text")).not.toBeInTheDocument();
  });

  it("renders a draft-vs-repair line diff on the repair stage", async () => {
    vi.mocked(getStageContent).mockImplementation(async (_topic, stage) => {
      if (stage === "draft") {
        return {
          topic_id: "t",
          stage: "draft",
          prompt: null,
          response: "same line\nold line",
          approved: "same line\nold line",
          response_sha256: "sha-d",
        };
      }
      return {
        topic_id: "t",
        stage: "repair",
        prompt: null,
        response: "same line\nnew line",
        approved: null,
        response_sha256: "sha-r",
      };
    });
    renderAt("/topics/t/stages/repair");
    await userEvent.click(
      await screen.findByRole("button", { name: "Diff against draft" }),
    );

    expect(await screen.findByText("old line")).toBeInTheDocument();
    expect(screen.getByText("old line").closest(".diff-line")).toHaveClass(
      "diff-removed",
    );
    expect(screen.getByText("new line").closest(".diff-line")).toHaveClass(
      "diff-added",
    );
    expect(getStageContent).toHaveBeenCalledWith("t", "draft");
  });

  it("does not offer the draft diff on non-repair stages", async () => {
    vi.mocked(getStageContent).mockResolvedValue({
      topic_id: "t",
      stage: "draft",
      prompt: "# prompt",
      response: "body",
      approved: null,
      response_sha256: "sha-1",
    });
    renderAt("/topics/t/stages/draft");
    await screen.findByRole("tab", { name: /prompt/ });
    expect(
      screen.queryByRole("button", { name: "Diff against draft" }),
    ).not.toBeInTheDocument();
  });
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd web && npx vitest run src/pages/StageViewerPage.test.tsx`
Expected: the three new tests FAIL (no such buttons)

- [ ] **Step 3: Implement `DiffView`** — create `web/src/components/DiffView.tsx`:

```tsx
import { diffLines } from "../lib/diff";

export default function DiffView({ a, b }: { a: string; b: string }) {
  const rows = diffLines(a, b);
  return (
    <div className="diff">
      {rows.map((row, i) => (
        <div key={i} className={`diff-line diff-${row.type}`}>
          <span className="diff-marker">
            {row.type === "added" ? "+" : row.type === "removed" ? "-" : " "}
          </span>
          <span>{row.text || " "}</span>
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 4: Wire the toggles into `StageViewerPage.tsx`** — add imports:

```tsx
import DiffView from "../components/DiffView";
```

Add state next to the existing `editing` state:

```tsx
  const [compare, setCompare] = useState(false);
  const [diffOpen, setDiffOpen] = useState(false);
  const [draftApproved, setDraftApproved] = useState<string | null>(null);
```

Add a toggle handler above the `return` (after the `showEditor` line):

```tsx
  const toggleDiff = async () => {
    const next = !diffOpen;
    setDiffOpen(next);
    if (next && draftApproved === null) {
      const draft = await getStageContent(topicId!, "draft");
      setDraftApproved(draft.approved ?? "");
    }
  };
```

Add the toggle buttons directly under the `<nav className="tabs">` block:

```tsx
      <div className="view-toggles">
        <button onClick={() => setCompare((c) => !c)}>
          {compare ? "Single pane" : "Compare prompt ↔ response"}
        </button>
        {data.stage === "repair" && (
          <button onClick={() => void toggleDiff()}>
            {diffOpen ? "Hide diff" : "Diff against draft"}
          </button>
        )}
      </div>
```

Replace the read-only pane branch (the `<pre className="content">…` else-arm from Task 9) with:

```tsx
      ) : compare ? (
        <div className="compare">
          <pre className="content">{data.prompt ?? "(no prompt yet)"}</pre>
          <pre className="content">{data.response ?? "(no response yet)"}</pre>
        </div>
      ) : (
        <pre className="content">{data[tab] ?? `(no ${tab} yet)`}</pre>
      )}
      {diffOpen && draftApproved !== null && (
        <DiffView a={draftApproved} b={data.response ?? ""} />
      )}
```

Append to `web/src/styles.css`:

```css
/* Phase 3: compare and diff views */
.view-toggles {
  display: flex;
  gap: 0.5rem;
  margin: 0.5rem 0;
}
.compare {
  display: flex;
  gap: 1rem;
}
.compare .content {
  flex: 1;
  min-width: 0;
  overflow-x: auto;
}
.diff {
  overflow-x: auto;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 0.85rem;
  border: 1px solid #ddd;
  border-radius: 6px;
  padding: 0.4rem 0;
  margin: 0.5rem 0;
}
.diff-line {
  display: flex;
  gap: 0.5rem;
  padding: 0 0.75rem;
  white-space: pre;
}
.diff-marker {
  user-select: none;
  width: 1ch;
}
.diff-added {
  background: #e6ffec;
}
.diff-removed {
  background: #ffebe9;
}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd web && npx vitest run && npx tsc --noEmit`
Expected: all PASS, tsc clean

- [ ] **Step 6: Commit**

```bash
git add web/src/components/DiffView.tsx web/src/pages/StageViewerPage.tsx web/src/pages/StageViewerPage.test.tsx web/src/styles.css
git commit -m "feat(web): compare and draft-vs-repair diff views"
```

---

### Task 11: E2E — edit/save/re-approve/finalize and stale-save rejection

**Files:**
- Create: `web/e2e/editor.spec.ts` (modeled on `web/e2e/full-run.spec.ts`)

**Interfaces:**
- Consumes: the full stack from Tasks 1-10; the daemon spawned against a temp workspace; `RunStore` layout — a topic `w`'s response file lives at `<ws>/runs/w/responses/<stage>.response.md`.

- [ ] **Step 1: Build the SPA so the daemon can serve it**

Run: `cd web && npm run build`
Expected: `web/dist/` produced without errors

- [ ] **Step 2: Write the spec** — create `web/e2e/editor.spec.ts`:

```ts
import { expect, test } from "@playwright/test";
import { spawn, type ChildProcess } from "node:child_process";
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

let daemon: ChildProcess;
let baseURL: string;
let ws: string;

test.beforeAll(async () => {
  ws = mkdtempSync(join(tmpdir(), "ep-e2e-editor-"));
  mkdirSync(join(ws, "topics"), { recursive: true });

  daemon = spawn("python3", ["-m", "education_pipeline.daemon", ws], {
    cwd: resolve(import.meta.dirname, "../.."),
    env: { ...process.env, EP_WEB_DIST: resolve(import.meta.dirname, "../dist") },
    stdio: "inherit",
  });

  const discovery = join(ws, ".education-pipeline", "daemon.json");
  for (let i = 0; i < 100 && !existsSync(discovery); i++) {
    await new Promise((r) => setTimeout(r, 100));
  }
  if (!existsSync(discovery)) throw new Error("daemon never wrote its discovery file");
  const record = JSON.parse(readFileSync(discovery, "utf-8")) as { port: number };
  baseURL = `http://127.0.0.1:${record.port}`;
});

test.afterAll(() => {
  daemon?.kill();
});

async function importTopicAndRunAllStages(page, topicId: string, title: string) {
  await page.goto(`${baseURL}/`);
  await page.getByRole("button", { name: "Import topic…" }).click();
  await page
    .getByLabel("topic TOML")
    .fill(`schema_version = 1\nid = "${topicId}"\ntitle = "${title}"\n`);
  await page.getByRole("button", { name: "Import", exact: true }).click();
  await page.getByRole("link", { name: topicId, exact: true }).click();

  for (const stage of ["spec", "outline", "draft", "qa", "repair"]) {
    await page.getByRole("button", { name: "Advance" }).click();
    await page.getByRole("button", { name: "Paste response…" }).click();
    await page.getByLabel(`Response for ${stage}`).fill(`${stage} response body`);
    await page.getByRole("button", { name: "Save response" }).click();
    await page.getByRole("button", { name: `Approve ${stage}` }).click();
  }
}

test("edit → save → re-approve → finalize entirely in the browser", async ({
  page,
}) => {
  page.on("dialog", (dialog) => dialog.accept());
  await importTopicAndRunAllStages(page, "w", "Editable Topic");

  // open the repair stage viewer and edit its response
  await page
    .getByRole("row", { name: /repair/ })
    .getByRole("link", { name: "view" })
    .click();
  await page.getByRole("tab", { name: /^response/ }).click();
  await page.getByRole("button", { name: "Edit" }).click();
  await page
    .getByLabel("Edit response for repair")
    .fill("repair response body, edited in the browser");
  await page.getByRole("button", { name: "Save" }).click();

  // the edit resurfaces Approve (already approved -> overwrite confirm auto-accepted)
  await page.getByRole("button", { name: "Approve repair" }).click();
  await expect(page.getByText("Approved repair.")).toBeVisible();

  // back to the run board: finalize the edited run
  await page.getByRole("link", { name: /back to w/ }).click();
  await page.getByRole("button", { name: "Finalize" }).click();
  await expect(page.getByText("Finalized: yes")).toBeVisible();

  // the edited content is what got finalized
  const finalGuide = readFileSync(join(ws, "runs", "w", "final", "guide.md"), "utf-8");
  expect(finalGuide).toBe("repair response body, edited in the browser");
});

test("a concurrent external edit is detected and rejected, never overwritten", async ({
  page,
}) => {
  await page.goto(`${baseURL}/`);
  await page.getByRole("button", { name: "Import topic…" }).click();
  await page
    .getByLabel("topic TOML")
    .fill('schema_version = 1\nid = "c"\ntitle = "Conflict Topic"\n');
  await page.getByRole("button", { name: "Import", exact: true }).click();
  await page.getByRole("link", { name: "c", exact: true }).click();
  await page.getByRole("button", { name: "Advance" }).click();
  await page.getByRole("button", { name: "Paste response…" }).click();
  await page.getByLabel("Response for spec").fill("spec response body");
  await page.getByRole("button", { name: "Save response" }).click();

  // open the editor with the loaded content/hash
  await page
    .getByRole("row", { name: /spec/ })
    .getByRole("link", { name: "view" })
    .click();
  await page.getByRole("tab", { name: /^response/ }).click();
  await page.getByRole("button", { name: "Edit" }).click();

  // simulate a concurrent external edit directly on disk
  const responseFile = join(ws, "runs", "c", "responses", "spec.response.md");
  writeFileSync(responseFile, "EXTERNAL EDIT", "utf-8");

  await page.getByLabel("Edit response for spec").fill("my browser edit");
  await page.getByRole("button", { name: "Save" }).click();

  // rejected with the stale-content message; reload is offered
  await expect(page.getByText(/changed on disk/)).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Reload current content" }),
  ).toBeVisible();
  // the buffer is intact and the external edit was never overwritten
  await expect(page.getByLabel("Edit response for spec")).toHaveValue(
    "my browser edit",
  );
  expect(readFileSync(responseFile, "utf-8")).toBe("EXTERNAL EDIT");
});
```

- [ ] **Step 3: Run the new spec**

Run: `cd web && npx playwright test e2e/editor.spec.ts`
Expected: 2 tests PASS. If a locator is ambiguous or a dialog stalls a click, fix the locator (e.g. `exact: true`) rather than adding waits — the app is loopback-local and fast.

- [ ] **Step 4: Run the whole e2e suite to confirm no regression**

Run: `cd web && npx playwright test`
Expected: all specs (smoke, full-run, editor) PASS

- [ ] **Step 5: Commit**

```bash
git add web/e2e/editor.spec.ts
git commit -m "test(e2e): browser edit loop and stale-save rejection"
```

---

### Task 12: Whole-feature verification

**Files:**
- None (verification only; fix regressions in place if any appear)

- [ ] **Step 1: Backend suite**

Run: `python3 -m pytest`
Expected: all tests PASS

- [ ] **Step 2: Frontend unit suite and typecheck/build**

Run: `cd web && npx vitest run && npm run build`
Expected: all tests PASS; build clean

- [ ] **Step 3: E2E suite**

Run: `cd web && npx playwright test`
Expected: all PASS

- [ ] **Step 4: Spec done-check** — confirm against the spec's "Done when": the editor e2e proves edit → save → approve → finalize works entirely in the browser, and the conflict e2e proves a concurrent external edit is detected and rejected, never overwritten.

- [ ] **Step 5: Commit anything outstanding**

```bash
git status --short   # expect empty; commit any stragglers with a descriptive message
```
