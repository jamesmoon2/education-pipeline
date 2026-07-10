# Cockpit Phase 1 (Read-Only UI) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

## Execution status (updated 2026-07-10)

Executed with superpowers:subagent-driven-development. Branch: `feat/cockpit-phase1` (base `6a3027a`).
Durable ledger: `.superpowers/sdd/progress.md` — trust it and `git log` over memory after a disconnect.

| Task | State | Commit |
|---|---|---|
| 1. Route-aware auth + `/v1/session` | complete, review clean | `6ccdce8` |
| 2. Read-API module + topic/profile endpoints | complete, review clean | `1ca1483` |
| 3. Run read endpoints | complete, review clean | `56756de` |
| 4. Static-asset resolver | complete, review clean | `35c2cac` |
| 5. Serve SPA from daemon | complete, review clean | `e50f8dd` |
| 6. CLI prints cockpit URL | complete, review clean | `5cc6869` |
| 7–14 (frontend) | not started | — |

Backend suite at `56756de`: **195 passing, 0 failing.**

**To resume:** continue with Task 4 (static-asset resolver). Do not re-dispatch Tasks 1–3.

---

**Goal:** A read-only browser cockpit served by the existing loopback daemon: topic list → run board → stage viewer, with live job/log monitoring via polling.

**Architecture:** The stdlib-only daemon (`education_pipeline/daemon/server.py`) gains route-aware auth, a `/v1/session` token bootstrap, read endpoints backed by the existing `TopicStore`/`ProfileStore`/`RunStore`, and static serving of a React + Vite + TypeScript SPA built into `web/dist/`. The SPA polls the API; logs use the existing incremental `offset` cursor.

**Tech Stack:** Backend: Python 3.12 stdlib only, pytest. Frontend: React 18, react-router-dom 6, Vite 5, TypeScript 5, Vitest + React Testing Library, Playwright (smoke only). Node 22 is a **build-time** dependency only.

## Global Constraints

- Backend stays **stdlib-only** — no new Python dependencies.
- Every error response uses the existing envelope: `{"error": {"code": "...", "message": "..."}}`.
- **Never emit CORS headers** (`Access-Control-*`) from the daemon — the security model depends on cross-origin responses staying unreadable.
- The `Host` allowlist check (`127.0.0.1` / `localhost`) applies to **every** request, including static assets and `/v1/session`.
- Token comparison stays `secrets.compare_digest` (already in `_authed`).
- `POST` routes keep requiring `X-EP-Token` — only `GET /v1/session` and non-`/v1` static paths are token-exempt.
- Run backend tests with `python3 -m pytest tests/ -q` from the repo root. Run frontend tests with `npm test` from `web/`.
- Commit style: conventional commits (`feat(daemon): ...`, `feat(web): ...`, `test: ...`), matching recent history.
- Frontend files live under a new top-level `web/` directory; built assets go to `web/dist/` (gitignored).

## Key existing interfaces (read before starting)

- `DaemonContext` (`education_pipeline/daemon/server.py:27`) — dataclass the handler closes over; `serve()` in `education_pipeline/daemon/__init__.py:46` constructs it and tests construct it directly.
- `RunStore` (`education_pipeline/runs.py`): `list_run_ids() -> tuple[str, ...]`, `run_status(topic_id) -> RunStatus`, `stage_paths(topic_id, stage) -> StagePaths` (raises `ConfigError` on bad id/stage), `manifest_path(topic_id) -> Path`, `read_manifest(topic_id) -> dict`. `RunStatus` has `topic_id: str`, `stages: tuple[StageStatus, ...]`, `finalized: bool`, `next_action: NextAction`. `StageStatus` has `stage`, `prompt_written`, `response_ingested`, `approved`, and property `state` (one of `pending | prompt_written | response_ingested | approved`). `NextAction` has `topic_id`, `stage: str | None`, `action` (one of `write_prompt | save_response | approve | finalize | done`), `detail`.
- `TopicStore` / `ProfileStore` (`education_pipeline/workspace.py`): `list_topic_ids()`, `topic_path(id)`, `load_topic(id) -> Topic` (has `.title`), `read_topic_toml(id)`; `list_profile_ids()`, `profile_path(id)`, `read_profile_toml(id)`. Reads raise `ConfigError` when files are missing; id validation also raises `ConfigError`.
- `SUPPORTED_STAGES = ("spec", "outline", "draft", "qa", "repair")`.
- Discovery file: `<workspace>/.education-pipeline/daemon.json` with keys `pid`, `port`, `token`, `started_at`, `version` (`education_pipeline/daemon/lifecycle.py`).
- Test pattern: `tests/test_server.py` starts a real `ThreadingHTTPServer` in a thread via a `server` fixture and issues requests with `http.client` through the `_req` helper.

---

### Task 1: Route-aware auth + `GET /v1/session`

The current `_guard()` requires the token for every route, so a browser could never bootstrap. Restructure `do_GET` so: Host check always first; `GET /v1/session` returns the token with no token required; all other `/v1` GETs require the token; non-`/v1` GETs return 404 for now (static serving arrives in Task 5). `do_POST` keeps using `_guard()` unchanged.

**Files:**
- Modify: `education_pipeline/daemon/server.py` (the `Handler.do_GET` method, ~lines 127–151)
- Test: `tests/test_server.py`

**Interfaces:**
- Consumes: existing `DaemonContext.token`, `DaemonContext.version`.
- Produces: `GET /v1/session` → `200 {"token": str, "version": str}`; a private method `_api_get(self)` containing all authed `/v1` GET routes (Tasks 2–3 extend it); non-`/v1` GET → `404 not_found` (Task 5 replaces this branch with `_static_get`).

- [x] **Step 1: Write the failing tests**

Append to `tests/test_server.py`:

```python
def test_session_returns_token_without_auth(server):
    status, body = _req(server, "GET", "/v1/session", token=None)
    assert status == 200
    assert body["token"] == "secret-token"
    assert body["version"] == "0.1.0"


def test_session_rejects_bad_host(server):
    conn = http.client.HTTPConnection("127.0.0.1", server)
    conn.putrequest("GET", "/v1/session", skip_host=True)
    conn.putheader("Host", "evil.example.com")
    conn.endheaders()
    resp = conn.getresponse()
    conn.close()
    assert resp.status == 400


def test_non_api_path_is_not_unauthorized(server):
    # Static serving lands in a later task; until then unknown non-/v1 paths
    # must 404 (or 503), never 401 — the browser has no token yet.
    status, _ = _req(server, "GET", "/favicon.ico", token=None)
    assert status in (404, 503)


def test_api_get_still_requires_token(server):
    status, body = _req(server, "GET", "/v1/jobs", token=None)
    assert status == 401
    assert body["error"]["code"] == "unauthorized"
```

- [x] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_server.py -q`
Expected: the four new tests FAIL (session returns 401 today; `/favicon.ico` returns 401); all pre-existing tests PASS.

- [x] **Step 3: Restructure `do_GET`**

In `education_pipeline/daemon/server.py`, replace the entire `do_GET` method with:

```python
        def do_GET(self):
            if not self._host_ok():
                return self._error(400, "bad_host", "host not allowed")
            path = self.path.split("?", 1)[0]
            if path == "/v1/session":
                # Token bootstrap for the browser SPA. Safe without auth on
                # loopback: no CORS headers are ever sent, so a cross-origin
                # page can issue this request but never read the response.
                return self._send(
                    200, {"token": context.token, "version": context.version}
                )
            if path.startswith("/v1/"):
                if not self._authed():
                    return self._error(401, "unauthorized", "missing or invalid token")
                return self._api_get()
            return self._error(404, "not_found", "unknown path")

        def _api_get(self):
            if self.path.startswith("/v1/health"):
                return self._send(
                    200, {"version": context.version, "started_at": None, "ok": True}
                )
            m = re.match(r"^/v1/jobs/([^/]+)/log(?:\?offset=(\d+))?$", self.path)
            if m:
                job = context.store.find(m.group(1))
                if job is None:
                    return self._error(404, "not_found", "no such job")
                offset = int(m.group(2) or 0)
                data, next_offset = context.store.read_log(job, offset)
                return self._send(
                    200,
                    {"data": data.decode("utf-8", "replace"), "offset": next_offset},
                )
            m = re.match(r"^/v1/jobs/([^/]+)$", self.path)
            if m:
                job = context.store.find(m.group(1))
                if job is None:
                    return self._error(404, "not_found", "no such job")
                return self._send(200, job.to_dict())
            m = re.match(r"^/v1/jobs(?:\?topic=([^&]+))?$", self.path)
            if m:
                jobs = context.store.list(m.group(1))
                return self._send(200, {"jobs": [j.to_dict() for j in jobs]})
            self._error(404, "not_found", "unknown path")
```

(The job/health bodies are moved verbatim from the old `do_GET`; only the wrapping changed.)

- [x] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_server.py -q`
Expected: all PASS, including the pre-existing `test_health_requires_token`.

- [x] **Step 5: Run the full suite and commit**

Run: `python3 -m pytest tests/ -q` — expected: all PASS.

```bash
git add education_pipeline/daemon/server.py tests/test_server.py
git commit -m "feat(daemon): route-aware auth with /v1/session token bootstrap"
```

---

### Task 2: Read-API module + topic/profile endpoints

New pure-function module `read_api.py` (stores in, JSON dicts out), wired into the handler. `DaemonContext` gains `topics` and `profiles` stores.

**Files:**
- Create: `education_pipeline/daemon/read_api.py`
- Modify: `education_pipeline/daemon/server.py` (imports, `DaemonContext`, `_api_get`)
- Modify: `education_pipeline/daemon/__init__.py` (`serve()` constructs the stores)
- Test: `tests/test_server.py`

**Interfaces:**
- Consumes: `TopicStore`, `ProfileStore`, `RunStore` methods listed at the top of this plan.
- Produces (used by Task 3 and the frontend):
  - `class NotFoundError(Exception)` in `read_api` — the handler maps it to HTTP 404; `ConfigError` maps to 400.
  - `list_topics(topics, runs) -> dict` → `{"topics": [{"id", "title", "error", "run"}]}` where `run` is the Task 3 run-status payload or `null`.
  - `get_topic(topics, topic_id) -> dict` → `{"id", "title", "toml"}`.
  - `list_profiles(profiles) -> dict` → `{"profiles": [str, ...]}`.
  - `get_profile(profiles, profile_id) -> dict` → `{"id", "toml"}`.
  - `run_status_payload(runs, topic_id) -> dict` (defined here, also used by `list_topics`; exposed as an endpoint in Task 3).
  - `DaemonContext` fields `topics: TopicStore`, `profiles: ProfileStore` (required, keyword-constructed everywhere).

- [x] **Step 1: Update the test fixture and write the failing tests**

In `tests/test_server.py`, add imports at the top:

```python
from education_pipeline.workspace import ProfileStore, TopicStore
```

Inside the `server` fixture, after `runs.create_run("t")`, seed workspace artifacts:

```python
    topics_dir = tmp_path / "topics"
    topics_dir.mkdir(parents=True, exist_ok=True)
    (topics_dir / "t.toml").write_text(
        'schema_version = 1\nid = "t"\ntitle = "Test Topic"\n', encoding="utf-8"
    )
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir(parents=True, exist_ok=True)
    (profiles_dir / "p.toml").write_text(
        'schema_version = 1\nid = "p"\ntarget_learner = "team cohort"\n',
        encoding="utf-8",
    )
```

And extend the `DaemonContext(...)` construction in the fixture with:

```python
        topics=TopicStore(tmp_path),
        profiles=ProfileStore(tmp_path),
```

Append tests:

```python
def test_topics_list_includes_title_and_run(server):
    status, body = _req(server, "GET", "/v1/topics")
    assert status == 200
    (entry,) = body["topics"]
    assert entry["id"] == "t"
    assert entry["title"] == "Test Topic"
    assert entry["error"] is None
    # the fixture created a run for "t"; spec prompt not written yet
    assert entry["run"]["next_action"]["action"] == "write_prompt"
    assert entry["run"]["next_action"]["stage"] == "spec"


def test_topics_list_requires_token(server):
    status, _ = _req(server, "GET", "/v1/topics", token=None)
    assert status == 401


def test_topic_get_returns_toml(server):
    status, body = _req(server, "GET", "/v1/topics/t")
    assert status == 200
    assert body["id"] == "t"
    assert body["title"] == "Test Topic"
    assert 'title = "Test Topic"' in body["toml"]


def test_topic_get_unknown_is_404(server):
    status, body = _req(server, "GET", "/v1/topics/nope")
    assert status == 404
    assert body["error"]["code"] == "not_found"


def test_profiles_list_and_get(server):
    status, body = _req(server, "GET", "/v1/profiles")
    assert status == 200
    assert body["profiles"] == ["p"]
    status, body = _req(server, "GET", "/v1/profiles/p")
    assert status == 200
    assert 'target_learner = "team cohort"' in body["toml"]
    status, body = _req(server, "GET", "/v1/profiles/nope")
    assert status == 404
```

- [x] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_server.py -q`
Expected: fixture errors (`DaemonContext` has no `topics` field) — every test in the module fails. That confirms the fixture change is live.

- [x] **Step 3: Create `education_pipeline/daemon/read_api.py`**

```python
"""Read-only JSON payload builders for the cockpit /v1 API.

Pure functions: stores in, JSON-serializable dicts out. Raise
:class:`NotFoundError` for missing resources (HTTP 404) and let
``ConfigError`` propagate for invalid input (HTTP 400).
"""

from __future__ import annotations

from education_pipeline.config import ConfigError
from education_pipeline.runs import RunStore
from education_pipeline.workspace import ProfileStore, TopicStore


class NotFoundError(Exception):
    """A referenced workspace resource does not exist."""


def list_topics(topics: TopicStore, runs: RunStore) -> dict:
    entries = []
    for topic_id in topics.list_topic_ids():
        title: str | None = None
        error: str | None = None
        try:
            title = topics.load_topic(topic_id).title
        except ConfigError as exc:
            error = str(exc)
        run = (
            run_status_payload(runs, topic_id)
            if runs.manifest_path(topic_id).is_file()
            else None
        )
        entries.append({"id": topic_id, "title": title, "error": error, "run": run})
    return {"topics": entries}


def get_topic(topics: TopicStore, topic_id: str) -> dict:
    if not topics.topic_path(topic_id).is_file():
        raise NotFoundError(f"no such topic: {topic_id}")
    title: str | None = None
    try:
        title = topics.load_topic(topic_id).title
    except ConfigError:
        pass  # surface the raw TOML even if it no longer parses
    return {"id": topic_id, "title": title, "toml": topics.read_topic_toml(topic_id)}


def list_profiles(profiles: ProfileStore) -> dict:
    return {"profiles": list(profiles.list_profile_ids())}


def get_profile(profiles: ProfileStore, profile_id: str) -> dict:
    if not profiles.profile_path(profile_id).is_file():
        raise NotFoundError(f"no such profile: {profile_id}")
    return {"id": profile_id, "toml": profiles.read_profile_toml(profile_id)}


def run_status_payload(runs: RunStore, topic_id: str) -> dict:
    if not runs.manifest_path(topic_id).is_file():
        raise NotFoundError(f"no run started for topic: {topic_id}")
    status = runs.run_status(topic_id)
    return {
        "topic_id": status.topic_id,
        "finalized": status.finalized,
        "stages": [
            {
                "stage": s.stage,
                "state": s.state,
                "prompt_written": s.prompt_written,
                "response_ingested": s.response_ingested,
                "approved": s.approved,
            }
            for s in status.stages
        ],
        "next_action": {
            "topic_id": status.next_action.topic_id,
            "stage": status.next_action.stage,
            "action": status.next_action.action,
            "detail": status.next_action.detail,
        },
    }
```

- [x] **Step 4: Wire the context and routes**

In `education_pipeline/daemon/server.py`:

1. Add imports:

```python
from education_pipeline.daemon import read_api
from education_pipeline.workspace import ProfileStore, TopicStore
```

2. Add two fields to `DaemonContext` (after `plan: ModelPlan`, before `on_shutdown`):

```python
    topics: TopicStore
    profiles: ProfileStore
```

3. Replace the entire `_api_get` method (from Task 1) with:

```python
        def _api_get(self):
            try:
                return self._api_get_routes()
            except read_api.NotFoundError as exc:
                return self._error(404, "not_found", str(exc))
            except ConfigError as exc:
                return self._error(400, "bad_request", str(exc))

        def _api_get_routes(self):
            if self.path.startswith("/v1/health"):
                return self._send(
                    200, {"version": context.version, "started_at": None, "ok": True}
                )
            if self.path == "/v1/topics":
                return self._send(
                    200, read_api.list_topics(context.topics, context.runs)
                )
            m = re.match(r"^/v1/topics/([^/?]+)$", self.path)
            if m:
                return self._send(200, read_api.get_topic(context.topics, m.group(1)))
            if self.path == "/v1/profiles":
                return self._send(200, read_api.list_profiles(context.profiles))
            m = re.match(r"^/v1/profiles/([^/?]+)$", self.path)
            if m:
                return self._send(
                    200, read_api.get_profile(context.profiles, m.group(1))
                )
            m = re.match(r"^/v1/jobs/([^/]+)/log(?:\?offset=(\d+))?$", self.path)
            if m:
                job = context.store.find(m.group(1))
                if job is None:
                    return self._error(404, "not_found", "no such job")
                offset = int(m.group(2) or 0)
                data, next_offset = context.store.read_log(job, offset)
                return self._send(
                    200,
                    {"data": data.decode("utf-8", "replace"), "offset": next_offset},
                )
            m = re.match(r"^/v1/jobs/([^/]+)$", self.path)
            if m:
                job = context.store.find(m.group(1))
                if job is None:
                    return self._error(404, "not_found", "no such job")
                return self._send(200, job.to_dict())
            m = re.match(r"^/v1/jobs(?:\?topic=([^&]+))?$", self.path)
            if m:
                jobs = context.store.list(m.group(1))
                return self._send(200, {"jobs": [j.to_dict() for j in jobs]})
            self._error(404, "not_found", "unknown path")
```

4. In `education_pipeline/daemon/__init__.py`, import the stores and pass them when constructing `DaemonContext` inside `serve()`:

```python
from education_pipeline.workspace import ProfileStore, TopicStore
```

and in the `DaemonContext(...)` call add:

```python
            topics=TopicStore(root),
            profiles=ProfileStore(root),
```

- [x] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest tests/ -q`
Expected: all PASS. If any other test module constructs `DaemonContext` directly, add the same two keyword fields there.

- [x] **Step 6: Commit**

```bash
git add education_pipeline/daemon/read_api.py education_pipeline/daemon/server.py education_pipeline/daemon/__init__.py tests/test_server.py
git commit -m "feat(daemon): read API for topics and profiles"
```

---

### Task 3: Run read endpoints (list, status, stage content, manifest)

**Files:**
- Modify: `education_pipeline/daemon/read_api.py`
- Modify: `education_pipeline/daemon/server.py` (`_api_get_routes`)
- Test: `tests/test_server.py`

**Interfaces:**
- Consumes: `run_status_payload` from Task 2; `RunStore.stage_paths`, `read_manifest`, `list_run_ids`.
- Produces:
  - `GET /v1/runs` → `{"runs": [str, ...]}`
  - `GET /v1/runs/{topic}` → the `run_status_payload` shape from Task 2.
  - `GET /v1/runs/{topic}/stages/{stage}` → `{"topic_id", "stage", "prompt": str|null, "response": str|null, "approved": str|null}`
  - `GET /v1/runs/{topic}/manifest` → the manifest dict verbatim (`{"schema_version", "topic_id", "events": [...]}`).
  - `read_api.list_runs(runs) -> dict`, `read_api.stage_content(runs, topic_id, stage) -> dict`, `read_api.manifest_payload(runs, topic_id) -> dict`.

- [x] **Step 1: Write the failing tests**

Append to `tests/test_server.py`:

```python
def test_runs_list(server):
    status, body = _req(server, "GET", "/v1/runs")
    assert status == 200
    assert body["runs"] == ["t"]


def test_run_status_endpoint(server):
    status, body = _req(server, "GET", "/v1/runs/t")
    assert status == 200
    assert body["topic_id"] == "t"
    assert body["finalized"] is False
    draft = next(s for s in body["stages"] if s["stage"] == "draft")
    assert draft["state"] == "prompt_written"  # fixture wrote the draft prompt
    assert body["next_action"]["action"] == "write_prompt"


def test_run_status_unknown_topic_is_404(server):
    status, body = _req(server, "GET", "/v1/runs/nope")
    assert status == 404


def test_stage_content_returns_prompt_and_nulls(server):
    status, body = _req(server, "GET", "/v1/runs/t/stages/draft")
    assert status == 200
    assert body == {
        "topic_id": "t",
        "stage": "draft",
        "prompt": "PROMPT",
        "response": None,
        "approved": None,
    }


def test_stage_content_bad_stage_is_400(server):
    status, body = _req(server, "GET", "/v1/runs/t/stages/banana")
    assert status == 400
    assert body["error"]["code"] == "bad_request"


def test_manifest_endpoint(server):
    status, body = _req(server, "GET", "/v1/runs/t/manifest")
    assert status == 200
    assert body["topic_id"] == "t"
    assert isinstance(body["events"], list)
```

- [x] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_server.py -q`
Expected: the six new tests FAIL with 404 `unknown path` payloads.

- [x] **Step 3: Implement the payload builders**

Append to `education_pipeline/daemon/read_api.py`:

```python
def list_runs(runs: RunStore) -> dict:
    return {"runs": list(runs.list_run_ids())}


def stage_content(runs: RunStore, topic_id: str, stage: str) -> dict:
    if not runs.manifest_path(topic_id).is_file():
        raise NotFoundError(f"no run started for topic: {topic_id}")
    paths = runs.stage_paths(topic_id, stage)  # ConfigError on bad stage -> 400

    def _read(path):
        return path.read_text(encoding="utf-8") if path.is_file() else None

    return {
        "topic_id": paths.topic_id,
        "stage": paths.stage,
        "prompt": _read(paths.prompt_path),
        "response": _read(paths.response_path),
        "approved": _read(paths.approved_path),
    }


def manifest_payload(runs: RunStore, topic_id: str) -> dict:
    if not runs.manifest_path(topic_id).is_file():
        raise NotFoundError(f"no run manifest for topic: {topic_id}")
    return runs.read_manifest(topic_id)
```

- [x] **Step 4: Add the routes**

In `_api_get_routes` in `server.py`, insert after the profiles routes (order matters: `manifest` and `stages` before the bare `runs/{topic}` match):

```python
            if self.path == "/v1/runs":
                return self._send(200, read_api.list_runs(context.runs))
            m = re.match(r"^/v1/runs/([^/?]+)/manifest$", self.path)
            if m:
                return self._send(
                    200, read_api.manifest_payload(context.runs, m.group(1))
                )
            m = re.match(r"^/v1/runs/([^/?]+)/stages/([^/?]+)$", self.path)
            if m:
                return self._send(
                    200, read_api.stage_content(context.runs, m.group(1), m.group(2))
                )
            m = re.match(r"^/v1/runs/([^/?]+)$", self.path)
            if m:
                return self._send(
                    200, read_api.run_status_payload(context.runs, m.group(1))
                )
```

- [x] **Step 5: Run tests and commit**

Run: `python3 -m pytest tests/ -q` — expected: all PASS.

```bash
git add education_pipeline/daemon/read_api.py education_pipeline/daemon/server.py tests/test_server.py
git commit -m "feat(daemon): run status, stage content, and manifest read endpoints"
```

---

### Task 4: Static-asset resolver module

A pure resolver, unit-tested without HTTP: URL path in, safe file + headers out.

**Files:**
- Create: `education_pipeline/daemon/static.py`
- Test: `tests/test_static.py` (new)

**Interfaces:**
- Produces (used by Task 5):
  - `@dataclass(frozen=True) StaticFile(path: Path, content_type: str, cache_control: str)`
  - `resolve_static(dist: Path, url_path: str) -> StaticFile | None` — `None` means 404. Extension-less missing paths fall back to `index.html` (SPA deep links); paths escaping `dist` are rejected.
  - `default_web_dist() -> Path | None` — `$EP_WEB_DIST` override, else the repo's `web/dist` if it exists.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_static.py`:

```python
from pathlib import Path

import pytest

from education_pipeline.daemon.static import default_web_dist, resolve_static


@pytest.fixture
def dist(tmp_path):
    d = tmp_path / "dist"
    (d / "assets").mkdir(parents=True)
    (d / "index.html").write_text("<html>app</html>", encoding="utf-8")
    (d / "assets" / "index-abc123.js").write_text("js", encoding="utf-8")
    (d / "assets" / "index-abc123.css").write_text("css", encoding="utf-8")
    return d


def test_root_serves_index(dist):
    sf = resolve_static(dist, "/")
    assert sf.path == dist / "index.html"
    assert sf.content_type == "text/html; charset=utf-8"
    assert sf.cache_control == "no-store"


def test_asset_gets_immutable_cache(dist):
    sf = resolve_static(dist, "/assets/index-abc123.js")
    assert sf.path == dist / "assets" / "index-abc123.js"
    assert sf.content_type == "text/javascript; charset=utf-8"
    assert "immutable" in sf.cache_control


def test_spa_route_falls_back_to_index(dist):
    sf = resolve_static(dist, "/topics/t/stages/draft")
    assert sf.path == dist / "index.html"
    assert sf.cache_control == "no-store"


def test_missing_asset_is_none_not_index(dist):
    assert resolve_static(dist, "/assets/gone.js") is None


def test_traversal_is_rejected(dist, tmp_path):
    (tmp_path / "secret.txt").write_text("s", encoding="utf-8")
    assert resolve_static(dist, "/../secret.txt") is None
    assert resolve_static(dist, "/%2e%2e/secret.txt") is None


def test_symlink_escape_is_rejected(dist, tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("s", encoding="utf-8")
    (dist / "link.txt").symlink_to(outside)
    assert resolve_static(dist, "/link.txt") is None


def test_query_string_is_ignored(dist):
    sf = resolve_static(dist, "/assets/index-abc123.css?v=1")
    assert sf.path == dist / "assets" / "index-abc123.css"


def test_default_web_dist_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("EP_WEB_DIST", str(tmp_path))
    assert default_web_dist() == tmp_path
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_static.py -q`
Expected: FAIL — `ModuleNotFoundError: education_pipeline.daemon.static`.

- [ ] **Step 3: Implement `education_pipeline/daemon/static.py`**

```python
"""Static-asset resolution for the built cockpit SPA.

Pure path logic so it is unit-testable without HTTP: a request path either
maps to a real file under ``dist`` (with content type and cache policy) or to
``None`` (HTTP 404). Anything resolving outside ``dist`` — ``..`` segments,
percent-encoded dots, symlinks pointing out — is rejected.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote

_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json",
    ".map": "application/json",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".txt": "text/plain; charset=utf-8",
    ".woff2": "font/woff2",
}

#: Vite emits content-hashed filenames under assets/, so they never change.
_IMMUTABLE_CACHE = "public, max-age=31536000, immutable"
_NO_CACHE = "no-store"


@dataclass(frozen=True)
class StaticFile:
    path: Path
    content_type: str
    cache_control: str


def default_web_dist() -> Path | None:
    """Locate the built SPA: $EP_WEB_DIST override, else the repo's web/dist."""

    env = os.environ.get("EP_WEB_DIST")
    if env:
        return Path(env)
    candidate = Path(__file__).resolve().parents[2] / "web" / "dist"
    return candidate if candidate.is_dir() else None


def resolve_static(dist: Path, url_path: str) -> StaticFile | None:
    relative = unquote(url_path.split("?", 1)[0].split("#", 1)[0]).lstrip("/")
    if relative == "":
        relative = "index.html"
    dist = dist.resolve()
    candidate = (dist / relative).resolve()
    if candidate != dist and dist not in candidate.parents:
        return None
    if not candidate.is_file():
        final_segment = relative.rsplit("/", 1)[-1]
        if "." in final_segment:
            return None  # looks like a real asset request; don't mask a 404
        candidate = dist / "index.html"
        if not candidate.is_file():
            return None
        relative = "index.html"
    content_type = _CONTENT_TYPES.get(
        candidate.suffix.lower(), "application/octet-stream"
    )
    cache = _IMMUTABLE_CACHE if relative.startswith("assets/") else _NO_CACHE
    return StaticFile(path=candidate, content_type=content_type, cache_control=cache)
```

- [ ] **Step 4: Run tests and commit**

Run: `python3 -m pytest tests/test_static.py -q` — expected: all PASS.

```bash
git add education_pipeline/daemon/static.py tests/test_static.py
git commit -m "feat(daemon): static-asset resolver with traversal protection"
```

---

### Task 5: Serve the SPA from the daemon

Wire the resolver into the handler; `DaemonContext` gains `web_dist`; `serve()` discovers the dist directory.

**Files:**
- Modify: `education_pipeline/daemon/server.py`
- Modify: `education_pipeline/daemon/__init__.py`
- Test: `tests/test_server.py`

**Interfaces:**
- Consumes: `resolve_static`, `StaticFile`, `default_web_dist` from Task 4.
- Produces: `DaemonContext.web_dist: Path | None = None` (defaulted, so Tasks 1–3 constructions stay valid); non-`/v1` GETs serve files (no token needed) or `503 ui_unavailable` when no build exists.

- [ ] **Step 1: Refactor the test fixture into a factory and write the failing tests**

In `tests/test_server.py`, extract the body of the `server` fixture into a helper so a variant fixture can serve a dist directory (keep behavior identical):

```python
def _start_server(tmp_path, monkeypatch, web_dist=None):
    monkeypatch.setenv("FAKE_STDOUT", "GENERATED\n")
    register_runner(FakeRunner())
    runs = RunStore(tmp_path)
    runs.create_run("t")
    p = runs.stage_paths("t", "draft").prompt_path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("PROMPT", encoding="utf-8")
    topics_dir = tmp_path / "topics"
    topics_dir.mkdir(parents=True, exist_ok=True)
    (topics_dir / "t.toml").write_text(
        'schema_version = 1\nid = "t"\ntitle = "Test Topic"\n', encoding="utf-8"
    )
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir(parents=True, exist_ok=True)
    (profiles_dir / "p.toml").write_text(
        'schema_version = 1\nid = "p"\ntarget_learner = "team cohort"\n',
        encoding="utf-8",
    )
    catalog = parse_model_catalog({"providers": [{"id": "fake", "models": [{"id": "m"}]}]})
    plan = parse_model_plan({"provider": "fake", "stages": {"draft": {"model": "m"}}}, catalog)
    store = JobStore(tmp_path)
    worker = Worker(store, lambda job: JobRunner(store, runs, catalog, plan, timeout=30))
    context = DaemonContext(
        root=tmp_path,
        store=store,
        worker=worker,
        runs=runs,
        token="secret-token",
        version="0.1.0",
        catalog=catalog,
        plan=plan,
        topics=TopicStore(tmp_path),
        profiles=ProfileStore(tmp_path),
        on_shutdown=lambda: None,
        web_dist=web_dist,
    )
    srv = build_server(context)
    import threading

    threading.Thread(target=srv.serve_forever, daemon=True).start()
    worker.start()
    return srv, worker


@pytest.fixture
def server(tmp_path, monkeypatch):
    srv, worker = _start_server(tmp_path, monkeypatch)
    yield srv.server_port
    worker.stop()
    srv.shutdown()


@pytest.fixture
def ui_server(tmp_path, monkeypatch):
    dist = tmp_path / "webdist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>cockpit</html>", encoding="utf-8")
    (dist / "assets" / "app-abc.js").write_text("js", encoding="utf-8")
    srv, worker = _start_server(tmp_path, monkeypatch, web_dist=dist)
    yield srv.server_port
    worker.stop()
    srv.shutdown()
```

Append tests (raw `http.client` so headers are visible):

```python
def _raw_get(port, path, host=None):
    conn = http.client.HTTPConnection("127.0.0.1", port)
    if host is None:
        conn.request("GET", path)
    else:
        conn.putrequest("GET", path, skip_host=True)
        conn.putheader("Host", host)
        conn.endheaders()
    resp = conn.getresponse()
    body = resp.read()
    headers = dict(resp.getheaders())
    conn.close()
    return resp.status, body, headers


def test_index_served_without_token(ui_server):
    status, body, headers = _raw_get(ui_server, "/")
    assert status == 200
    assert b"cockpit" in body
    assert headers["Content-Type"] == "text/html; charset=utf-8"
    assert headers["Cache-Control"] == "no-store"
    assert not any(h.lower().startswith("access-control") for h in headers)


def test_asset_served_with_immutable_cache(ui_server):
    status, _, headers = _raw_get(ui_server, "/assets/app-abc.js")
    assert status == 200
    assert "immutable" in headers["Cache-Control"]


def test_spa_route_serves_index(ui_server):
    status, body, _ = _raw_get(ui_server, "/topics/t/stages/draft")
    assert status == 200
    assert b"cockpit" in body


def test_static_traversal_rejected(ui_server):
    status, _, _ = _raw_get(ui_server, "/../topics/t.toml")
    assert status == 404


def test_static_still_checks_host(ui_server):
    status, _, _ = _raw_get(ui_server, "/", host="evil.example.com")
    assert status == 400


def test_no_dist_returns_503(server):
    status, body = _req(server, "GET", "/", token=None)
    assert status == 503
    assert body["error"]["code"] == "ui_unavailable"
```

Also update Task 1's `test_non_api_path_is_not_unauthorized` expectation comment if needed — it already accepts 404 or 503.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_server.py -q`
Expected: new static tests FAIL (`DaemonContext` has no `web_dist`; `/` returns 404, not 503); prior tests PASS once the fixture refactor is correct.

- [ ] **Step 3: Implement static serving in the handler**

In `education_pipeline/daemon/server.py`:

1. Import: `from education_pipeline.daemon.static import resolve_static` and add `from pathlib import Path` if not present (it is).
2. Add the last `DaemonContext` field: `web_dist: Path | None = None`.
3. In `do_GET` (from Task 1), replace the final line `return self._error(404, "not_found", "unknown path")` with `return self._static_get()`.
4. Add the method:

```python
        def _static_get(self):
            dist = context.web_dist
            if dist is None:
                return self._error(
                    503,
                    "ui_unavailable",
                    "web UI not built; run `npm run build` in web/ or set EP_WEB_DIST",
                )
            static = resolve_static(dist, self.path)
            if static is None:
                return self._error(404, "not_found", "unknown path")
            body = static.path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", static.content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", static.cache_control)
            self.end_headers()
            self.wfile.write(body)
```

5. In `education_pipeline/daemon/__init__.py`, import `default_web_dist` from `education_pipeline.daemon.static` and add to the `DaemonContext(...)` call in `serve()`:

```python
            web_dist=default_web_dist(),
```

- [ ] **Step 4: Run tests and commit**

Run: `python3 -m pytest tests/ -q` — expected: all PASS.

```bash
git add education_pipeline/daemon/server.py education_pipeline/daemon/__init__.py tests/test_server.py
git commit -m "feat(daemon): serve the built cockpit SPA with SPA fallback"
```

---

### Task 6: CLI prints the cockpit URL

The daemon binds an ephemeral port; the user should never have to read `daemon.json` by hand.

**Files:**
- Modify: `education_pipeline/cli.py` (`_cmd_daemon_start`, `_cmd_daemon_status`)
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `daemon_status(root)` returns a dict with `running`, `pid`, `port`, `version`, `version_mismatch`; `lifecycle.read_discovery(root)` returns the discovery record.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cli.py`:

```python
def test_daemon_status_prints_cockpit_url(tmp_path, capsys, monkeypatch):
    from education_pipeline import cli

    monkeypatch.setattr(
        cli,
        "daemon_status",
        lambda root: {
            "running": True,
            "pid": 123,
            "port": 4242,
            "version": "0.1.0",
            "version_mismatch": False,
        },
    )
    assert _run(tmp_path, "daemon", "status") == 0
    out = capsys.readouterr().out
    assert "http://127.0.0.1:4242/" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_cli.py -q`
Expected: the new test FAILS (no URL in output).

- [ ] **Step 3: Implement**

In `education_pipeline/cli.py`, replace `_cmd_daemon_status` with:

```python
def _cmd_daemon_status(args: argparse.Namespace) -> int:
    status = daemon_status(_root(args))
    if not status["running"]:
        print("daemon: stopped")
        return 0
    warn = "  [version mismatch: restart the daemon]" if status["version_mismatch"] else ""
    print(f"daemon: running  pid={status['pid']}  port={status['port']}  "
          f"version={status['version']}{warn}")
    print(f"cockpit: http://127.0.0.1:{status['port']}/")
    return 0
```

And in `_cmd_daemon_start`, after `print(f"daemon started (version {health['version']})")`, add:

```python
    record = lifecycle.read_discovery(root) or {}
    if record.get("port"):
        print(f"cockpit: http://127.0.0.1:{record['port']}/")
```

- [ ] **Step 4: Run tests and commit**

Run: `python3 -m pytest tests/ -q` — expected: all PASS.

```bash
git add education_pipeline/cli.py tests/test_cli.py
git commit -m "feat(cli): print the cockpit URL from daemon start/status"
```

---

### Task 7: `web/` scaffold (Vite + React + TS + Vitest)

The app shell builds, tests, and dev-serves with a `/v1` proxy that reads the daemon's discovery file. No pages yet — those come in Tasks 10–13.

**Files:**
- Create: `web/package.json`, `web/vite.config.ts`, `web/tsconfig.json`, `web/index.html`, `web/.gitignore`, `web/src/main.tsx`, `web/src/App.tsx`, `web/src/styles.css`, `web/src/test/setup.ts`
- Modify: `.gitignore` (add `web/node_modules/` and `web/dist/` if the repo root ignores are not already generic)

**Interfaces:**
- Produces: `App` renders a `<header>` with an `<h1>` link to `/` and a `<main>` containing `<Routes>`. Tasks 10–13 add `<Route>` entries. `npm run dev|build|test` all work.

- [ ] **Step 1: Write the config and entry files**

`web/package.json`:

```json
{
  "name": "education-pipeline-cockpit",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc --noEmit && vite build",
    "test": "vitest run --passWithNoTests",
    "preview": "vite preview"
  },
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "react-router-dom": "^6.26.0"
  },
  "devDependencies": {
    "@testing-library/jest-dom": "^6.4.8",
    "@testing-library/react": "^16.0.0",
    "@types/react": "^18.3.3",
    "@types/react-dom": "^18.3.0",
    "@vitejs/plugin-react": "^4.3.1",
    "jsdom": "^24.1.1",
    "typescript": "^5.5.4",
    "vite": "^5.4.0",
    "vitest": "^2.0.5"
  }
}
```

`web/vite.config.ts` (the proxy reads the workspace discovery file; `EP_WORKSPACE` overrides the workspace root, defaulting to the repo root):

```ts
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

function devProxy() {
  try {
    const workspace = process.env.EP_WORKSPACE ?? resolve(__dirname, "..");
    const file = resolve(workspace, ".education-pipeline/daemon.json");
    const record = JSON.parse(readFileSync(file, "utf-8")) as { port: number };
    return { "/v1": { target: `http://127.0.0.1:${record.port}` } };
  } catch {
    // No daemon running; dev server still starts, API calls will fail.
    return undefined;
  }
}

export default defineConfig({
  plugins: [react()],
  server: { proxy: devProxy() },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: "./src/test/setup.ts",
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
```

`web/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2020",
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "moduleResolution": "bundler",
    "jsx": "react-jsx",
    "strict": true,
    "skipLibCheck": true,
    "noEmit": true,
    "types": ["vite/client", "vitest/globals", "@testing-library/jest-dom"]
  },
  "include": ["src"]
}
```

`web/index.html`:

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Education Pipeline Cockpit</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

`web/.gitignore`:

```
node_modules/
dist/
```

`web/src/main.tsx`:

```tsx
import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </React.StrictMode>,
);
```

`web/src/App.tsx` (routes fill in across Tasks 10–13):

```tsx
import { Link, Route, Routes } from "react-router-dom";

export default function App() {
  return (
    <div className="app">
      <header>
        <h1>
          <Link to="/">Education Pipeline Cockpit</Link>
        </h1>
      </header>
      <main>
        <Routes>
          <Route path="/" element={<p>Cockpit is running. Pages arrive in later tasks.</p>} />
        </Routes>
      </main>
    </div>
  );
}
```

`web/src/styles.css`:

```css
:root {
  color-scheme: light dark;
  font-family: system-ui, -apple-system, sans-serif;
  line-height: 1.5;
}
body { margin: 0; }
.app { max-width: 64rem; margin: 0 auto; padding: 0 1rem 3rem; }
header h1 { font-size: 1.2rem; }
header a { color: inherit; text-decoration: none; }
table { border-collapse: collapse; width: 100%; }
th, td { text-align: left; padding: 0.4rem 0.75rem; border-bottom: 1px solid color-mix(in srgb, currentColor 20%, transparent); }
.error { color: #c0392b; }
.next-action { padding: 0.5rem 0.75rem; border-left: 3px solid #2b6cb0; background: color-mix(in srgb, #2b6cb0 8%, transparent); }
.state { padding: 0.1rem 0.5rem; border-radius: 0.75rem; font-size: 0.85em; border: 1px solid currentColor; }
.state-approved { color: #1e7e34; }
.state-response_ingested { color: #2b6cb0; }
.state-prompt_written { color: #b7791f; }
.state-pending { opacity: 0.6; }
.tabs { display: flex; gap: 0.5rem; margin: 0.75rem 0; }
.tab { padding: 0.3rem 0.8rem; cursor: pointer; }
.tab.active { font-weight: 600; text-decoration: underline; }
pre.content, pre.log {
  padding: 0.75rem;
  overflow-x: auto;
  border: 1px solid color-mix(in srgb, currentColor 20%, transparent);
  border-radius: 4px;
  white-space: pre-wrap;
}
pre.log { max-height: 20rem; overflow-y: auto; font-size: 0.85em; }
```

`web/src/test/setup.ts`:

```ts
import "@testing-library/jest-dom/vitest";
```

- [ ] **Step 2: Verify install, test, and build**

Run from `web/`:
- `npm install` — expected: completes without errors.
- `npm test` — expected: exits 0 ("no test files found" is fine — `--passWithNoTests`).
- `npm run build` — expected: `dist/index.html` and `dist/assets/*.js` exist.

- [ ] **Step 3: Verify the daemon serves the real build**

From the repo root:

```bash
EP_WEB_DIST=$PWD/web/dist python3 - <<'EOF'
from education_pipeline.daemon.static import default_web_dist
d = default_web_dist()
assert d is not None and (d / "index.html").is_file(), d
print("dist ok:", d)
EOF
```

Expected: `dist ok: .../web/dist`.

- [ ] **Step 4: Commit**

```bash
git add web/ .gitignore
git commit -m "feat(web): scaffold the cockpit SPA (Vite + React + TS + Vitest)"
```

---

### Task 8: API types + client

**Files:**
- Create: `web/src/api/types.ts`, `web/src/api/client.ts`
- Test: `web/src/api/client.test.ts`

**Interfaces:**
- Consumes: the endpoint payload shapes from Tasks 1–3.
- Produces (used by all page tasks):
  - Types: `Session`, `NextAction`, `StageStatus`, `RunStatus`, `TopicSummary`, `TopicDetail`, `StageContent`, `Job`, `LogChunk`.
  - `class ApiRequestError extends Error { status: number; code: string }`
  - `api<T>(path: string): Promise<T>` — bootstraps the token from `/v1/session` once, sends `X-EP-Token`, throws `ApiRequestError` on non-2xx.
  - Helpers: `getTopics()`, `getTopic(id)`, `getRunStatus(topicId)`, `getStageContent(topicId, stage)`, `getJobs(topicId?)`, `getJobLog(jobId, offset)`.
  - `resetSessionForTests()` — clears the cached token between tests.

- [ ] **Step 1: Write the types**

`web/src/api/types.ts`:

```ts
export interface Session {
  token: string;
  version: string;
}

export interface NextAction {
  topic_id: string;
  stage: string | null;
  action: "write_prompt" | "save_response" | "approve" | "finalize" | "done";
  detail: string;
}

export type StageState =
  | "pending"
  | "prompt_written"
  | "response_ingested"
  | "approved";

export interface StageStatus {
  stage: string;
  state: StageState;
  prompt_written: boolean;
  response_ingested: boolean;
  approved: boolean;
}

export interface RunStatus {
  topic_id: string;
  finalized: boolean;
  stages: StageStatus[];
  next_action: NextAction;
}

export interface TopicSummary {
  id: string;
  title: string | null;
  error: string | null;
  run: RunStatus | null;
}

export interface TopicDetail {
  id: string;
  title: string | null;
  toml: string;
}

export interface StageContent {
  topic_id: string;
  stage: string;
  prompt: string | null;
  response: string | null;
  approved: string | null;
}

export interface Job {
  id: string;
  topic_id: string;
  stage: string;
  provider: string;
  model: string | null;
  effort: string | null;
  status: "queued" | "running" | "succeeded" | "failed" | "canceled" | "interrupted";
  created_at: string;
  started_at: string | null;
  ended_at: string | null;
  exit_code: number | null;
  error: string | null;
}

export interface LogChunk {
  data: string;
  offset: number;
}
```

- [ ] **Step 2: Write the failing tests**

`web/src/api/client.test.ts`:

```ts
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiRequestError, api, resetSessionForTests } from "./client";

function mockFetch(routes: Record<string, { status: number; body: unknown }>) {
  return vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input);
    const route = routes[path];
    if (!route) throw new Error(`unexpected fetch: ${path}`);
    return {
      ok: route.status >= 200 && route.status < 300,
      status: route.status,
      json: async () => route.body,
    } as Response;
  });
}

describe("api client", () => {
  afterEach(() => {
    resetSessionForTests();
    vi.unstubAllGlobals();
  });

  it("bootstraps the token once and sends it on requests", async () => {
    const fetchMock = mockFetch({
      "/v1/session": { status: 200, body: { token: "tok", version: "0.1.0" } },
      "/v1/topics": { status: 200, body: { topics: [] } },
    });
    vi.stubGlobal("fetch", fetchMock);

    await api("/v1/topics");
    await api("/v1/topics");

    const sessionCalls = fetchMock.mock.calls.filter(([u]) => String(u) === "/v1/session");
    expect(sessionCalls).toHaveLength(1);
    const topicCall = fetchMock.mock.calls.find(([u]) => String(u) === "/v1/topics");
    expect((topicCall![1] as RequestInit).headers).toMatchObject({ "X-EP-Token": "tok" });
  });

  it("throws ApiRequestError with the server's code on non-2xx", async () => {
    vi.stubGlobal(
      "fetch",
      mockFetch({
        "/v1/session": { status: 200, body: { token: "tok", version: "0.1.0" } },
        "/v1/runs/nope": {
          status: 404,
          body: { error: { code: "not_found", message: "no run" } },
        },
      }),
    );
    const err = await api("/v1/runs/nope").catch((e) => e);
    expect(err).toBeInstanceOf(ApiRequestError);
    expect(err.status).toBe(404);
    expect(err.code).toBe("not_found");
    expect(err.message).toBe("no run");
  });
});
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `npm test` (from `web/`)
Expected: FAIL — `./client` does not exist.

- [ ] **Step 4: Implement `web/src/api/client.ts`**

```ts
import type {
  Job,
  LogChunk,
  RunStatus,
  Session,
  StageContent,
  TopicDetail,
  TopicSummary,
} from "./types";

export class ApiRequestError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = "ApiRequestError";
  }
}

let tokenPromise: Promise<string> | null = null;

async function fetchToken(): Promise<string> {
  const resp = await fetch("/v1/session");
  if (!resp.ok) {
    throw new ApiRequestError(
      resp.status,
      "session_failed",
      `session bootstrap failed (HTTP ${resp.status})`,
    );
  }
  return ((await resp.json()) as Session).token;
}

function getToken(): Promise<string> {
  if (tokenPromise === null) {
    tokenPromise = fetchToken().catch((err) => {
      tokenPromise = null; // allow retry on the next call
      throw err;
    });
  }
  return tokenPromise;
}

export function resetSessionForTests(): void {
  tokenPromise = null;
}

export async function api<T>(path: string): Promise<T> {
  const token = await getToken();
  const resp = await fetch(path, { headers: { "X-EP-Token": token } });
  let body: unknown = {};
  try {
    body = await resp.json();
  } catch {
    // non-JSON body; fall through to the generic error below
  }
  if (!resp.ok) {
    const err = (body as { error?: { code: string; message: string } }).error;
    throw new ApiRequestError(
      resp.status,
      err?.code ?? "unknown",
      err?.message ?? `HTTP ${resp.status}`,
    );
  }
  return body as T;
}

export const getTopics = () => api<{ topics: TopicSummary[] }>("/v1/topics");
export const getTopic = (id: string) =>
  api<TopicDetail>(`/v1/topics/${encodeURIComponent(id)}`);
export const getRunStatus = (topicId: string) =>
  api<RunStatus>(`/v1/runs/${encodeURIComponent(topicId)}`);
export const getStageContent = (topicId: string, stage: string) =>
  api<StageContent>(
    `/v1/runs/${encodeURIComponent(topicId)}/stages/${encodeURIComponent(stage)}`,
  );
export const getJobs = (topicId?: string) =>
  api<{ jobs: Job[] }>(
    topicId ? `/v1/jobs?topic=${encodeURIComponent(topicId)}` : "/v1/jobs",
  );
export const getJobLog = (jobId: string, offset: number) =>
  api<LogChunk>(`/v1/jobs/${encodeURIComponent(jobId)}/log?offset=${offset}`);
```

- [ ] **Step 5: Run tests and commit**

Run: `npm test` — expected: all PASS. Also `npm run build` — expected: clean.

```bash
git add web/src/api/
git commit -m "feat(web): typed API client with /v1/session token bootstrap"
```

---

### Task 9: `usePolling` hook

**Files:**
- Create: `web/src/hooks/usePolling.ts`
- Test: `web/src/hooks/usePolling.test.ts`

**Interfaces:**
- Produces: `usePolling<T>(fetcher: () => Promise<T>, intervalMs: number): { data: T | null; error: Error | null; refresh: () => void }`. Fetches immediately, then every `intervalMs`; skips fetches while the tab is hidden and refreshes immediately when it becomes visible; `error` is cleared on the next success; `data` is retained across transient errors. **Callers must memoize `fetcher` (or the identity change is fine — the hook keeps the latest via a ref).**

- [ ] **Step 1: Write the failing tests**

`web/src/hooks/usePolling.test.ts`:

```ts
import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { usePolling } from "./usePolling";

describe("usePolling", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("fetches immediately and then on the interval", async () => {
    vi.useFakeTimers();
    let n = 0;
    const fetcher = vi.fn(async () => ++n);
    const { result, unmount } = renderHook(() => usePolling(fetcher, 1000));

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(result.current.data).toBe(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(result.current.data).toBe(2);
    unmount();
  });

  it("keeps the last data and reports the error on failure", async () => {
    vi.useFakeTimers();
    let calls = 0;
    const fetcher = vi.fn(async () => {
      calls += 1;
      if (calls === 2) throw new Error("boom");
      return calls;
    });
    const { result, unmount } = renderHook(() => usePolling(fetcher, 1000));

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(result.current.data).toBe(1);
    expect(result.current.error).toBeNull();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(result.current.data).toBe(1); // retained
    expect(result.current.error?.message).toBe("boom");

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(result.current.data).toBe(3);
    expect(result.current.error).toBeNull();
    unmount();
  });

  it("stops polling after unmount", async () => {
    vi.useFakeTimers();
    const fetcher = vi.fn(async () => 1);
    const { unmount } = renderHook(() => usePolling(fetcher, 1000));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    unmount();
    const callsAtUnmount = fetcher.mock.calls.length;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(fetcher.mock.calls.length).toBe(callsAtUnmount);
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `npm test` — expected: FAIL, module not found.

- [ ] **Step 3: Implement `web/src/hooks/usePolling.ts`**

```ts
import { useCallback, useEffect, useRef, useState } from "react";

export function usePolling<T>(fetcher: () => Promise<T>, intervalMs: number) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [nonce, setNonce] = useState(0);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;

    const tick = async () => {
      if (document.visibilityState === "visible") {
        try {
          const result = await fetcherRef.current();
          if (!cancelled) {
            setData(result);
            setError(null);
          }
        } catch (err) {
          if (!cancelled) setError(err instanceof Error ? err : new Error(String(err)));
        }
      }
      if (!cancelled) timer = window.setTimeout(tick, intervalMs);
    };

    void tick();

    const onVisibility = () => {
      if (document.visibilityState === "visible" && !cancelled) {
        window.clearTimeout(timer);
        void tick();
      }
    };
    document.addEventListener("visibilitychange", onVisibility);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [intervalMs, nonce]);

  const refresh = useCallback(() => setNonce((n) => n + 1), []);
  return { data, error, refresh };
}
```

- [ ] **Step 4: Run tests and commit**

Run: `npm test` — expected: all PASS.

```bash
git add web/src/hooks/
git commit -m "feat(web): visibility-aware polling hook"
```

---

### Task 10: Topic list page

**Files:**
- Create: `web/src/pages/TopicListPage.tsx`
- Modify: `web/src/App.tsx`
- Test: `web/src/pages/TopicListPage.test.tsx`

**Interfaces:**
- Consumes: `getTopics` (Task 8), `usePolling` (Task 9), `TopicSummary` type.
- Produces: default export `TopicListPage`, mounted at route `/`. Topic ids link to `/topics/{id}`.

- [ ] **Step 1: Write the failing test**

`web/src/pages/TopicListPage.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import type { TopicSummary } from "../api/types";
import TopicListPage from "./TopicListPage";

vi.mock("../api/client", () => ({
  getTopics: vi.fn(),
}));

import { getTopics } from "../api/client";

const summary: TopicSummary = {
  id: "systems-thinking",
  title: "Systems Thinking",
  error: null,
  run: {
    topic_id: "systems-thinking",
    finalized: false,
    stages: [],
    next_action: {
      topic_id: "systems-thinking",
      stage: "spec",
      action: "write_prompt",
      detail: "Write the spec prompt.",
    },
  },
};

describe("TopicListPage", () => {
  it("renders topics with title, next action, and a run-board link", async () => {
    vi.mocked(getTopics).mockResolvedValue({ topics: [summary] });
    render(
      <MemoryRouter>
        <TopicListPage />
      </MemoryRouter>,
    );
    const link = await screen.findByRole("link", { name: "systems-thinking" });
    expect(link).toHaveAttribute("href", "/topics/systems-thinking");
    expect(screen.getByText("Systems Thinking")).toBeInTheDocument();
    expect(screen.getByText("write_prompt")).toBeInTheDocument();
  });

  it("shows the empty state", async () => {
    vi.mocked(getTopics).mockResolvedValue({ topics: [] });
    render(
      <MemoryRouter>
        <TopicListPage />
      </MemoryRouter>,
    );
    expect(await screen.findByText(/No topics yet/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `npm test` — expected: FAIL, module not found.

- [ ] **Step 3: Implement `web/src/pages/TopicListPage.tsx`**

```tsx
import { Link } from "react-router-dom";
import { getTopics } from "../api/client";
import { usePolling } from "../hooks/usePolling";

export default function TopicListPage() {
  const { data, error } = usePolling(getTopics, 10_000);

  if (error) return <p className="error">Failed to load topics: {error.message}</p>;
  if (!data) return <p>Loading…</p>;
  if (data.topics.length === 0) {
    return (
      <p>
        No topics yet. Import one with <code>edu topic import &lt;file.toml&gt;</code>.
      </p>
    );
  }
  return (
    <table>
      <thead>
        <tr>
          <th>Topic</th>
          <th>Title</th>
          <th>Next action</th>
          <th>Finalized</th>
        </tr>
      </thead>
      <tbody>
        {data.topics.map((t) => (
          <tr key={t.id}>
            <td>
              <Link to={`/topics/${t.id}`}>{t.id}</Link>
            </td>
            <td>{t.error ? <span className="error">{t.error}</span> : (t.title ?? "—")}</td>
            <td>{t.run ? t.run.next_action.action : "no run"}</td>
            <td>{t.run?.finalized ? "yes" : "no"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
```

In `web/src/App.tsx`, replace the placeholder root route:

```tsx
import TopicListPage from "./pages/TopicListPage";
```

```tsx
          <Route path="/" element={<TopicListPage />} />
```

- [ ] **Step 4: Run tests and commit**

Run: `npm test` and `npm run build` — expected: all PASS / clean build.

```bash
git add web/src/pages/ web/src/App.tsx
git commit -m "feat(web): topic list page"
```

---

### Task 11: Job log view (incremental offset polling)

Built before the run board so the board can compose it.

**Files:**
- Create: `web/src/components/JobLogView.tsx`
- Test: `web/src/components/JobLogView.test.tsx`

**Interfaces:**
- Consumes: `getJobLog(jobId, offset)` (Task 8).
- Produces: default export `JobLogView({ jobId, active }: { jobId: string; active: boolean })` — accumulates log text using the server's `offset` cursor; polls every second while `active` (job queued/running), fetches once when not.

- [ ] **Step 1: Write the failing test**

`web/src/components/JobLogView.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import JobLogView from "./JobLogView";

vi.mock("../api/client", () => ({
  getJobLog: vi.fn(),
}));

import { getJobLog } from "../api/client";

describe("JobLogView", () => {
  it("accumulates chunks using the returned offset", async () => {
    vi.mocked(getJobLog)
      .mockResolvedValueOnce({ data: "hello ", offset: 6 })
      .mockResolvedValueOnce({ data: "world", offset: 11 })
      .mockResolvedValue({ data: "", offset: 11 });

    render(<JobLogView jobId="j1" active={true} />);

    expect(await screen.findByText(/hello/)).toBeInTheDocument();
    expect(await screen.findByText(/hello world/)).toBeInTheDocument();
    // second call must pass the cursor from the first response
    expect(vi.mocked(getJobLog).mock.calls[1]).toEqual(["j1", 6]);
  });

  it("fetches once when the job is not active", async () => {
    vi.mocked(getJobLog).mockResolvedValue({ data: "done output", offset: 11 });
    render(<JobLogView jobId="j2" active={false} />);
    expect(await screen.findByText(/done output/)).toBeInTheDocument();
    await new Promise((r) => setTimeout(r, 50));
    expect(vi.mocked(getJobLog)).toHaveBeenCalledTimes(1);
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `npm test` — expected: FAIL, module not found.

- [ ] **Step 3: Implement `web/src/components/JobLogView.tsx`**

```tsx
import { useEffect, useRef, useState } from "react";
import { getJobLog } from "../api/client";

export default function JobLogView({ jobId, active }: { jobId: string; active: boolean }) {
  const [text, setText] = useState("");
  const offsetRef = useRef(0);

  useEffect(() => {
    setText("");
    offsetRef.current = 0;
    let cancelled = false;
    let timer: number | undefined;

    const tick = async () => {
      try {
        const chunk = await getJobLog(jobId, offsetRef.current);
        if (cancelled) return;
        if (chunk.data) setText((t) => t + chunk.data);
        offsetRef.current = chunk.offset;
      } catch {
        // transient: keep the text we have; retry on the next tick if active
      }
      if (!cancelled && active) timer = window.setTimeout(tick, 1000);
    };

    void tick();
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [jobId, active]);

  return <pre className="log">{text || "(no output yet)"}</pre>;
}
```

- [ ] **Step 4: Run tests and commit**

Run: `npm test` — expected: all PASS.

```bash
git add web/src/components/
git commit -m "feat(web): incremental job log view"
```

---

### Task 12: Run board page with jobs panel

**Files:**
- Create: `web/src/pages/RunBoardPage.tsx`, `web/src/components/JobsPanel.tsx`
- Modify: `web/src/App.tsx`
- Test: `web/src/pages/RunBoardPage.test.tsx`

**Interfaces:**
- Consumes: `getRunStatus`, `getJobs`, `ApiRequestError` (Task 8), `usePolling` (Task 9), `JobLogView` (Task 11).
- Produces: `RunBoardPage` at route `/topics/:topicId` — next-action banner, stage table (each row links to `/topics/{id}/stages/{stage}`, the Task 13 route), and `JobsPanel({ topicId })` polling jobs every 2s with an expandable log per job.

- [ ] **Step 1: Write the failing test**

`web/src/pages/RunBoardPage.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import type { RunStatus } from "../api/types";
import RunBoardPage from "./RunBoardPage";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return {
    ApiRequestError: actual.ApiRequestError,
    getRunStatus: vi.fn(),
    getJobs: vi.fn(),
    getJobLog: vi.fn(),
  };
});

import { ApiRequestError, getJobs, getRunStatus } from "../api/client";

const status: RunStatus = {
  topic_id: "t",
  finalized: false,
  stages: [
    { stage: "spec", state: "approved", prompt_written: true, response_ingested: true, approved: true },
    { stage: "outline", state: "prompt_written", prompt_written: true, response_ingested: false, approved: false },
    { stage: "draft", state: "pending", prompt_written: false, response_ingested: false, approved: false },
    { stage: "qa", state: "pending", prompt_written: false, response_ingested: false, approved: false },
    { stage: "repair", state: "pending", prompt_written: false, response_ingested: false, approved: false },
  ],
  next_action: {
    topic_id: "t",
    stage: "outline",
    action: "save_response",
    detail: "Run the outline prompt and save the response.",
  },
};

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/topics/:topicId" element={<RunBoardPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("RunBoardPage", () => {
  it("renders stages, next action, and jobs", async () => {
    vi.mocked(getRunStatus).mockResolvedValue(status);
    vi.mocked(getJobs).mockResolvedValue({
      jobs: [
        {
          id: "20260710T000000Z-abcd",
          topic_id: "t",
          stage: "outline",
          provider: "claude-code",
          model: "m",
          effort: null,
          status: "running",
          created_at: "2026-07-10T00:00:00Z",
          started_at: "2026-07-10T00:00:01Z",
          ended_at: null,
          exit_code: null,
          error: null,
        },
      ],
    });
    renderAt("/topics/t");

    expect(await screen.findByText(/Run the outline prompt/)).toBeInTheDocument();
    expect(screen.getByText("approved")).toBeInTheDocument();
    const stageLink = screen.getAllByRole("link", { name: "view" })[0];
    expect(stageLink).toHaveAttribute("href", "/topics/t/stages/spec");
    expect(await screen.findByText("20260710T000000Z-abcd")).toBeInTheDocument();
    expect(screen.getByText("running")).toBeInTheDocument();
  });

  it("shows a friendly message when no run exists", async () => {
    vi.mocked(getRunStatus).mockRejectedValue(
      new ApiRequestError(404, "not_found", "no run started for topic: t"),
    );
    vi.mocked(getJobs).mockResolvedValue({ jobs: [] });
    renderAt("/topics/t");
    expect(await screen.findByText(/No run started/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `npm test` — expected: FAIL, module not found.

- [ ] **Step 3: Implement**

`web/src/components/JobsPanel.tsx`:

```tsx
import { Fragment, useCallback, useState } from "react";
import { getJobs } from "../api/client";
import { usePolling } from "../hooks/usePolling";
import JobLogView from "./JobLogView";

const ACTIVE_STATUSES = new Set(["queued", "running"]);

export default function JobsPanel({ topicId }: { topicId: string }) {
  const fetchJobs = useCallback(() => getJobs(topicId), [topicId]);
  const { data, error } = usePolling(fetchJobs, 2_000);
  const [openJobId, setOpenJobId] = useState<string | null>(null);

  if (error) return <p className="error">Failed to load jobs: {error.message}</p>;
  if (!data) return <p>Loading jobs…</p>;

  return (
    <section>
      <h3>Jobs</h3>
      {data.jobs.length === 0 ? (
        <p>No jobs yet for this topic.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Job</th>
              <th>Stage</th>
              <th>Provider</th>
              <th>Status</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {data.jobs.map((job) => (
              <Fragment key={job.id}>
                <tr>
                  <td>{job.id}</td>
                  <td>{job.stage}</td>
                  <td>{job.provider}</td>
                  <td>
                    {job.status}
                    {job.error ? <span className="error"> — {job.error}</span> : null}
                  </td>
                  <td>
                    <button
                      onClick={() => setOpenJobId(openJobId === job.id ? null : job.id)}
                    >
                      {openJobId === job.id ? "hide log" : "log"}
                    </button>
                  </td>
                </tr>
                {openJobId === job.id ? (
                  <tr>
                    <td colSpan={5}>
                      <JobLogView jobId={job.id} active={ACTIVE_STATUSES.has(job.status)} />
                    </td>
                  </tr>
                ) : null}
              </Fragment>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
```

`web/src/pages/RunBoardPage.tsx`:

```tsx
import { useCallback } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiRequestError, getRunStatus } from "../api/client";
import JobsPanel from "../components/JobsPanel";
import { usePolling } from "../hooks/usePolling";

export default function RunBoardPage() {
  const { topicId } = useParams<{ topicId: string }>();
  const fetchStatus = useCallback(() => getRunStatus(topicId!), [topicId]);
  const { data: status, error } = usePolling(fetchStatus, 5_000);

  if (error instanceof ApiRequestError && error.status === 404) {
    return (
      <p>
        No run started for <strong>{topicId}</strong> yet. Start one with{" "}
        <code>edu advance {topicId}</code>.
      </p>
    );
  }
  if (error) return <p className="error">Failed to load run: {error.message}</p>;
  if (!status) return <p>Loading…</p>;

  return (
    <div>
      <h2>{status.topic_id}</h2>
      <p className="next-action">
        <strong>Next:</strong> {status.next_action.detail}
      </p>
      <table>
        <thead>
          <tr>
            <th>Stage</th>
            <th>State</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {status.stages.map((s) => (
            <tr key={s.stage}>
              <td>{s.stage}</td>
              <td>
                <span className={`state state-${s.state}`}>{s.state}</span>
              </td>
              <td>
                <Link to={`/topics/${status.topic_id}/stages/${s.stage}`}>view</Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p>Finalized: {status.finalized ? "yes" : "no"}</p>
      <JobsPanel topicId={status.topic_id} />
    </div>
  );
}
```

In `web/src/App.tsx`, add:

```tsx
import RunBoardPage from "./pages/RunBoardPage";
```

```tsx
          <Route path="/topics/:topicId" element={<RunBoardPage />} />
```

- [ ] **Step 4: Run tests and commit**

Run: `npm test` and `npm run build` — expected: all PASS / clean.

```bash
git add web/src/pages/ web/src/components/ web/src/App.tsx
git commit -m "feat(web): run board with next-action banner and live jobs panel"
```

---

### Task 13: Stage viewer page

**Files:**
- Create: `web/src/pages/StageViewerPage.tsx`
- Modify: `web/src/App.tsx`
- Test: `web/src/pages/StageViewerPage.test.tsx`

**Interfaces:**
- Consumes: `getStageContent`, `ApiRequestError` (Task 8), `usePolling` (Task 9).
- Produces: `StageViewerPage` at route `/topics/:topicId/stages/:stage` — tabs for prompt / response / approved rendered read-only in a `<pre>`.

- [ ] **Step 1: Write the failing test**

`web/src/pages/StageViewerPage.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import StageViewerPage from "./StageViewerPage";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ApiRequestError: actual.ApiRequestError, getStageContent: vi.fn() };
});

import { getStageContent } from "../api/client";

describe("StageViewerPage", () => {
  it("shows the prompt by default and switches tabs", async () => {
    vi.mocked(getStageContent).mockResolvedValue({
      topic_id: "t",
      stage: "draft",
      prompt: "# the prompt",
      response: "# the response",
      approved: null,
    });
    render(
      <MemoryRouter initialEntries={["/topics/t/stages/draft"]}>
        <Routes>
          <Route path="/topics/:topicId/stages/:stage" element={<StageViewerPage />} />
        </Routes>
      </MemoryRouter>,
    );
    expect(await screen.findByText("# the prompt")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /^response/ }));
    expect(screen.getByText("# the response")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /^approved/ }));
    expect(screen.getByText("(no approved yet)")).toBeInTheDocument();
  });
});
```

Note: `userEvent` needs `@testing-library/user-event` — add it:

```bash
npm install --save-dev @testing-library/user-event@^14.5.2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `npm test` — expected: FAIL, module not found.

- [ ] **Step 3: Implement `web/src/pages/StageViewerPage.tsx`**

```tsx
import { useCallback, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiRequestError, getStageContent } from "../api/client";
import { usePolling } from "../hooks/usePolling";

const TABS = ["prompt", "response", "approved"] as const;
type Tab = (typeof TABS)[number];

export default function StageViewerPage() {
  const { topicId, stage } = useParams<{ topicId: string; stage: string }>();
  const fetchContent = useCallback(
    () => getStageContent(topicId!, stage!),
    [topicId, stage],
  );
  const { data, error } = usePolling(fetchContent, 5_000);
  const [tab, setTab] = useState<Tab>("prompt");

  if (error instanceof ApiRequestError && error.status === 404) {
    return (
      <p>
        No run started for <strong>{topicId}</strong>.
      </p>
    );
  }
  if (error) return <p className="error">{error.message}</p>;
  if (!data) return <p>Loading…</p>;

  return (
    <div>
      <p>
        <Link to={`/topics/${topicId}`}>← back to {topicId}</Link>
      </p>
      <h2>
        {topicId} / {data.stage}
      </h2>
      <nav className="tabs">
        {TABS.map((t) => (
          <button
            key={t}
            className={t === tab ? "tab active" : "tab"}
            onClick={() => setTab(t)}
          >
            {t}
            {data[t] === null ? " (empty)" : ""}
          </button>
        ))}
      </nav>
      <pre className="content">{data[tab] ?? `(no ${tab} yet)`}</pre>
    </div>
  );
}
```

In `web/src/App.tsx`, add:

```tsx
import StageViewerPage from "./pages/StageViewerPage";
```

```tsx
          <Route path="/topics/:topicId/stages/:stage" element={<StageViewerPage />} />
```

- [ ] **Step 4: Run tests and commit**

Run: `npm test` and `npm run build` — expected: all PASS / clean.

```bash
git add web/src/pages/ web/src/App.tsx web/package.json web/package-lock.json
git commit -m "feat(web): read-only stage viewer with prompt/response/approved tabs"
```

---

### Task 14: End-to-end smoke test (Playwright)

One browser test against a real daemon on a temp workspace, using the real `web/dist` build. Runs locally (not wired into CI in this phase).

**Files:**
- Create: `web/playwright.config.ts`, `web/e2e/smoke.spec.ts`
- Modify: `web/package.json` (dev dependency + script)

**Interfaces:**
- Consumes: the built `web/dist`, `python3 -m education_pipeline.daemon <workspace>`, the discovery file format (`.education-pipeline/daemon.json` with `port`).

- [ ] **Step 1: Install Playwright**

From `web/`:

```bash
npm install --save-dev @playwright/test@^1.46.0
npx playwright install chromium
```

Add to `web/package.json` scripts: `"e2e": "playwright test"`.

- [ ] **Step 2: Write the config and test**

`web/playwright.config.ts`:

```ts
import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  use: { headless: true },
});
```

`web/e2e/smoke.spec.ts`:

```ts
import { expect, test } from "@playwright/test";
import { spawn, type ChildProcess } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

let daemon: ChildProcess;
let baseURL: string;

test.beforeAll(async () => {
  const ws = mkdtempSync(join(tmpdir(), "ep-e2e-"));
  mkdirSync(join(ws, "topics"), { recursive: true });
  writeFileSync(
    join(ws, "topics", "t.toml"),
    'schema_version = 1\nid = "t"\ntitle = "E2E Topic"\n',
  );
  const run = join(ws, "runs", "t");
  for (const d of ["inputs", "prompts", "responses", "approved", "reports", "final"]) {
    mkdirSync(join(run, d), { recursive: true });
  }
  writeFileSync(
    join(run, "manifest.json"),
    JSON.stringify({ schema_version: 1, topic_id: "t", events: [] }),
  );
  writeFileSync(join(run, "prompts", "spec.prompt.md"), "# spec prompt\n");

  daemon = spawn("python3", ["-m", "education_pipeline.daemon", ws], {
    cwd: resolve(__dirname, "../.."),
    env: { ...process.env, EP_WEB_DIST: resolve(__dirname, "../dist") },
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

test("read flow: topic list → run board → stage viewer", async ({ page }) => {
  await page.goto(`${baseURL}/`);
  await expect(page.getByRole("link", { name: "t", exact: true })).toBeVisible();
  await page.getByRole("link", { name: "t", exact: true }).click();
  // spec prompt written, no response → next action is save_response
  await expect(page.getByText(/Run the spec prompt/)).toBeVisible();
  await page.getByRole("link", { name: "view" }).first().click();
  await expect(page.getByText("# spec prompt")).toBeVisible();
});
```

Exclude e2e from Vitest (already done — Task 7's `include` only matches `src/`).

- [ ] **Step 3: Build and run the smoke test**

From `web/`:

```bash
npm run build
npm run e2e
```

Expected: 1 passed. If the daemon fails to start, check that `python3 -m education_pipeline.daemon` works from the repo root.

- [ ] **Step 4: Commit**

```bash
git add web/playwright.config.ts web/e2e/ web/package.json web/package-lock.json
git commit -m "test(web): end-to-end smoke test against a real daemon"
```

---

## Phase 1 acceptance check (manual, after all tasks)

From the repo root:

1. `cd web && npm run build && cd ..`
2. `python3 -m education_pipeline.cli --workspace <some-workspace> daemon start` — output includes `cockpit: http://127.0.0.1:<port>/`.
3. Open that URL: topic list renders real topics; clicking a topic shows the run board with stage states and the next action; a stage's prompt/response render read-only; if a job is enqueued via `edu run <topic>`, it appears within 2s and its log tails live.
4. No token was ever pasted anywhere.
