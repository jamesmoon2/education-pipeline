# Cockpit Phase 2 (Write Actions) Implementation Plan

## Execution status

| Task | State | Commit |
|------|-------|--------|
| 1. JobStore.any_active_for | complete | 16c92a4 |
| 2. write_api run actions | complete | 2256900 |
| 3. write_api workspace imports | complete | f9e6110 |
| 4. POST run-action routes | complete | ac2fa37 |
| 5. POST import routes | complete | 13b4685 |
| 6. Download endpoints | complete | 0492407 |
| 7. Full-pipeline HTTP test | complete | 3f861da |
| 8. Client apiPost/download | complete | 4d37e02 |
| 9. useAction hook | complete | d7db814 |
| 10. Run board primary action | complete | bd0d7c4 |
| 11. Export controls | complete | 9371979 |
| 12. Stage viewer actions | complete | cd53cdd |
| 13. Jobs panel cancel | complete | ee56da6 |
| 14. Topic list imports/attach | complete | 178ae81 |
| 15. E2E full run | complete | 6444052 |
| 16. Deferred hygiene | complete | 87bef9c |

To resume: all 16 tasks complete; final whole-branch review in progress.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every human step of a run — importing topics/profiles, advancing, pasting/approving responses, running providers, finalizing, exporting, downloading — works from the browser, with success/error feedback mapped from the daemon's error envelope.

**Architecture:** A new `write_api.py` module (mirroring Phase 1's `read_api.py`) holds pure functions that pre-check workspace state and raise typed exceptions (`NotFoundError` → 404, new `ConflictError(code, message)` → 409, `ConfigError` → 400). The handler gains `_api_post_routes` beside `_api_get_routes`, plus two authed GET download routes. The SPA gains `apiPost`/`download` client helpers, a `useAction` hook (in-flight disable, feedback, overwrite-confirm retry), and action controls on the existing pages driven strictly by `next_action.action`.

**Tech Stack:** Backend: Python 3.12 stdlib only, pytest. Frontend: React 18, react-router-dom 6, Vite 5, TypeScript 5 (strict), Vitest + React Testing Library + user-event, Playwright. Node 22 build-time only.

**Spec:** `docs/superpowers/specs/2026-07-10-cockpit-phase2-write-actions.md`

## Global Constraints

- Backend stays **stdlib-only** — no new Python dependencies.
- Every error response uses the envelope `{"error": {"code": "...", "message": "..."}}`. Phase 2 adds HTTP **409** with codes `already_exists`, `not_ready`, `job_active`.
- Every `POST` requires `X-EP-Token`; there are **no** token-exempt write routes. Downloads are authed `GET`s. The Host allowlist (`127.0.0.1` / `localhost`) applies to every request.
- **Never emit CORS headers** from the daemon.
- Request bodies are parsed as JSON regardless of `Content-Type`, under the existing 1 MiB cap (`MAX_REQUEST_BODY_BYTES`).
- All writes go through the store layer's existing atomic/no-clobber helpers; the HTTP layer never opens workspace files directly (downloads read only the fixed paths `RunStore.final_path` / `RunStore.export_path` provide).
- All `*_path` values in responses are **relative to the run directory** — display strings only, never used by the client to fetch files.
- Run-mutating endpoints (`advance`, `response`, `approve`, `finalize`) refuse with `409 job_active` while **any** job for that topic is non-terminal (topic-wide guard). `export` and workspace imports are exempt.
- UI design rule: the run board renders **exactly one primary action, driven by `next_action.action`** — the server decides what's next; the UI never re-derives pipeline logic. All action buttons disable while their request is in flight. `409 already_exists` → confirm dialog, retry with `overwrite`/`force`.
- Resolved spec open questions: (1) `advance` stays **single-step** like `edu advance`; (2) ingest-response records **no** manifest event (CLI parity); (3) imports are **paste-only** (no file upload); (4) the `job_active` guard is **topic-wide**.
- Run backend tests with `python3 -m pytest tests/ -q` from the repo root. Run frontend tests with `npm test` from `web/`; typecheck+build with `npm run build`; E2E with `npm run e2e` (requires `npm run build` first).
- Commit style: conventional commits (`feat(daemon): ...`, `feat(web): ...`, `test: ...`, `chore(web): ...`).

## Key existing interfaces (read before starting)

- `RunStore` (`education_pipeline/runs.py`): `advance(topic_id) -> AdvanceResult` (fields `topic_id`, `performed: str | None`, `status: RunStatus`); `ingest_response(topic_id, stage, text, *, force=False) -> Path` (rejects empty text, refuses clobber without `force`); `approve_stage(topic_id, stage, *, overwrite=False) -> Path` (raises `ConfigError` if no response; appends `response_approved`); `finalize_run(topic_id, *, overwrite=False) -> Path` (copies approved repair → `final/guide.md`; appends `finalized`); `export_run(topic_id, *, format="html", overwrite=False) -> Path` (requires finalize; appends `exported`); `stage_paths(topic_id, stage) -> StagePaths` (fields `prompt_path`, `response_path`, `stub_path`, `approved_path`; `ConfigError` on bad id/stage); `run_dir(topic_id)`, `manifest_path(topic_id)`, `final_path(topic_id)`, `is_finalized(topic_id)`, `run_status(topic_id)`. `SUPPORTED_STAGES = ("spec", "outline", "draft", "qa", "repair")`. `EXPORT_FORMATS = ("markdown", "html")` (`education_pipeline/export.py:16`).
- `TopicStore.save_topic_toml(topic_id, toml_text, *, overwrite=False) -> Topic` and `ProfileStore.save_profile_toml(...) -> LearnerProfile` (`education_pipeline/workspace.py`) — parse+validate, enforce id match, refuse overwrite. `ProfileStore.attach_profile_to_topic(profile_id, topic_id, *, overwrite=False) -> ProfileAttachment` (fields `profile_id`, `topic_id`, `source_path`, `snapshot_path`, `profile`). `ProfileStore.runs_dir` property exists.
- `JobStore` (`education_pipeline/daemon/jobs.py`): `list(topic_id)`, `active_for(topic_id, stage)`, `TERMINAL_STATUSES = frozenset({"succeeded", "failed", "canceled", "interrupted"})`.
- `read_api` (`education_pipeline/daemon/read_api.py`): `NotFoundError`, `run_status_payload(runs, topic_id) -> dict` (keys `topic_id`, `finalized`, `stages`, `next_action`).
- Handler (`education_pipeline/daemon/server.py`): `DaemonContext` (has `runs`, `topics`, `profiles`, `store` (JobStore), `worker`, `enqueue_stage`), `_guard()`, `_read_body()`, `_send(status, payload)`, `_error(status, code, message)`, `_api_get`/`_api_get_routes`, `do_POST` (currently inlines `/v1/jobs`, `/v1/jobs/{id}/cancel`, `/v1/shutdown`).
- Test harness: `tests/test_server.py` `_start_server(tmp_path, monkeypatch, web_dist=None)` boots a real server+worker with topic `t` (title "Test Topic"), a run for `t` with the **draft prompt written**, profile `p`, and a `fake` provider driven by env vars `FAKE_STDOUT`/`FAKE_DELAY`/`FAKE_EXIT` (`tests/fake_provider.py`). Fixtures `server`/`ui_server` yield the port; `_req(port, method, path, token="secret-token", body=None)` returns `(status, json)`.
- Frontend: `web/src/api/client.ts` (`ApiRequestError(status, code, message)`, token bootstrap via `/v1/session`, `api<T>(path)`, `resetSessionForTests()`), `web/src/api/types.ts`, `web/src/hooks/usePolling.ts` (returns `{ data, error, refresh }` — `refresh()` restarts the poll loop immediately). Pages: `TopicListPage`, `RunBoardPage` (+`JobsPanel`, `JobLogView`), `StageViewerPage`. Component tests mock `../api/client` via `vi.mock` factory (see `web/src/pages/RunBoardPage.test.tsx`).

## File structure

Backend:
- Create: `education_pipeline/daemon/write_api.py` — `ConflictError` + all POST payload builders (run actions, workspace imports). One responsibility: state pre-checks + store calls in, JSON dicts out.
- Modify: `education_pipeline/daemon/jobs.py` — add `JobStore.any_active_for`.
- Modify: `education_pipeline/runs.py` — add `RunStore.export_path(topic_id, format)`; `export_run` uses it.
- Modify: `education_pipeline/daemon/read_api.py` — shared `require_run` helper; download path resolvers.
- Modify: `education_pipeline/daemon/server.py` — `do_POST` → `_api_post`/`_api_post_routes` with 409 mapping; `_send_file`; download GET routes; `_require_str`.
- Tests: `tests/test_write_api.py` (new), `tests/test_jobs.py`, `tests/test_runs.py`, `tests/test_server.py`.

Frontend:
- Modify: `web/src/api/types.ts`, `web/src/api/client.ts` (+tests).
- Create: `web/src/hooks/useAction.ts` (+test) — the one shared write-action state machine.
- Create: `web/src/components/PrimaryAction.tsx`, `ResponseForm.tsx`, `ExportControls.tsx`, `ImportForm.tsx`, `AttachProfileControl.tsx` (+tests).
- Modify: `web/src/pages/RunBoardPage.tsx`, `StageViewerPage.tsx`, `TopicListPage.tsx`, `web/src/components/JobsPanel.tsx` (+tests).
- Create: `web/e2e/full-run.spec.ts`.
- Cleanup (Phase 1 deferred findings): `web/src/main.tsx`, `education_pipeline/daemon/static.py`, `web/src/components/JobLogView.test.tsx`, `web/src/hooks/usePolling.test.ts`, `npm audit fix`.

**WATCH (carried from Phase 1):** brief test code may hit (1) strict-tsconfig type errors, (2) Vitest mock.calls not auto-resetting. Apply minimal, test-file-only, behavior-preserving fixes (type annotation, `beforeEach(() => vi.clearAllMocks())`); never change production code or assertions to make a test pass.

---

### Task 1: `JobStore.any_active_for` — the topic-wide concurrency primitive

**Files:**
- Modify: `education_pipeline/daemon/jobs.py` (after `active_for`, ~line 162)
- Test: `tests/test_jobs.py`

**Interfaces:**
- Consumes: existing `JobStore.list(topic_id)`, `TERMINAL_STATUSES`.
- Produces: `JobStore.any_active_for(topic_id: str) -> Job | None` — the first non-terminal job for the topic across **all** stages, else `None`. Task 2's `write_api._require_no_active_job` calls this.

- [x] **Step 1: Write the failing tests**

Append to `tests/test_jobs.py`:

```python
def test_any_active_for_matches_any_stage(tmp_path):
    from education_pipeline.daemon.jobs import JobStore

    store = JobStore(tmp_path)
    job = store.create("t", "draft", "fake", None, None)
    store.save(job)

    found = store.any_active_for("t")
    assert found is not None and found.id == job.id
    # a different stage still counts: the guard is topic-wide
    assert store.any_active_for("t").stage == "draft"
    assert store.any_active_for("other") is None


def test_any_active_for_ignores_terminal_jobs(tmp_path):
    from education_pipeline.daemon.jobs import JobStore

    store = JobStore(tmp_path)
    job = store.create("t", "spec", "fake", None, None)
    job.status = "succeeded"
    store.save(job)
    assert store.any_active_for("t") is None
```

- [x] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_jobs.py -q -k any_active`
Expected: FAIL with `AttributeError: 'JobStore' object has no attribute 'any_active_for'`

- [x] **Step 3: Implement**

In `education_pipeline/daemon/jobs.py`, directly after `active_for` (after line 162):

```python
    def any_active_for(self, topic_id: str) -> Job | None:
        """The first queued/running job for the topic across all stages, if any."""

        for job in self.list(topic_id):
            if job.status not in TERMINAL_STATUSES:
                return job
        return None
```

- [x] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_jobs.py -q`
Expected: PASS (all)

- [x] **Step 5: Commit**

```bash
git add education_pipeline/daemon/jobs.py tests/test_jobs.py
git commit -m "feat(daemon): JobStore.any_active_for topic-wide active-job lookup"
```

---

### Task 2: `write_api.py` run actions + `RunStore.export_path` + shared `require_run`

**Files:**
- Create: `education_pipeline/daemon/write_api.py`
- Modify: `education_pipeline/runs.py` (`export_run`, ~lines 408-422; new `export_path` after `final_path`, ~line 392)
- Modify: `education_pipeline/daemon/read_api.py` (add `require_run`; use it in `run_status_payload` and `stage_content` — this also resolves the Phase 1 Minor finding about the duplicated manifest guard)
- Test: `tests/test_write_api.py` (new), `tests/test_runs.py`

**Interfaces:**
- Consumes: `RunStore` methods, `JobStore.any_active_for` (Task 1), `read_api.NotFoundError`, `read_api.run_status_payload`, `EXPORT_FORMATS`.
- Produces (all used by Task 4's routes):
  - `class ConflictError(Exception)` with attribute `code: str` (one of `"already_exists"`, `"not_ready"`, `"job_active"`); message via `str(exc)`.
  - `advance_run(runs: RunStore, jobs: JobStore, topic_id: str) -> dict` → `{"performed": str | None, "status": <run_status_payload>}`
  - `ingest_response(runs, jobs, topic_id, stage, text, *, force=False) -> dict` → `{"topic_id", "stage", "response_path", "status"}`
  - `approve_stage(runs, jobs, topic_id, stage, *, overwrite=False) -> dict` → `{"topic_id", "stage", "approved_path", "status"}`
  - `finalize_run(runs, jobs, topic_id, *, overwrite=False) -> dict` → `{"topic_id", "final_path", "status"}`
  - `export_run(runs, topic_id, *, format="html", overwrite=False) -> dict` → `{"topic_id", "format", "export_path"}` (no job guard — exempt per spec)
  - `RunStore.export_path(topic_id: str, format: str) -> Path` — `final/guide.html` or `final/guide.bundle.md`; `ConfigError` on bad format. Used by Task 6's downloads too.
  - `read_api.require_run(runs: RunStore, topic_id: str) -> None` — raises `NotFoundError(f"no run started for topic: {topic_id}")` when no manifest.

- [x] **Step 1: Write the failing tests**

Create `tests/test_write_api.py`:

```python
"""Unit tests for the write-action payload builders (no HTTP layer)."""

import pytest

from education_pipeline.config import ConfigError
from education_pipeline.daemon import write_api
from education_pipeline.daemon.jobs import JobStore
from education_pipeline.daemon.read_api import NotFoundError
from education_pipeline.runs import RunStore, SUPPORTED_STAGES


def _workspace(tmp_path):
    (tmp_path / "topics").mkdir()
    (tmp_path / "topics" / "t.toml").write_text(
        'schema_version = 1\nid = "t"\ntitle = "Test Topic"\n', encoding="utf-8"
    )
    return RunStore(tmp_path), JobStore(tmp_path)


def test_advance_starts_run_and_full_loop_reaches_export(tmp_path):
    runs, jobs = _workspace(tmp_path)
    for stage in SUPPORTED_STAGES:
        result = write_api.advance_run(runs, jobs, "t")
        assert result["performed"] == "write_prompt"
        assert result["status"]["next_action"]["action"] == "save_response"
        assert result["status"]["next_action"]["stage"] == stage
        ingest = write_api.ingest_response(runs, jobs, "t", stage, f"{stage} body")
        assert ingest["response_path"] == f"responses/{stage}.response.md"
        assert ingest["status"]["next_action"]["action"] == "approve"
        approved = write_api.approve_stage(runs, jobs, "t", stage)
        assert approved["approved_path"] == f"approved/{stage}.md"
    final = write_api.advance_run(runs, jobs, "t")
    assert final["performed"] == "finalize"
    assert final["status"]["finalized"] is True
    assert final["status"]["next_action"]["action"] == "done"
    export = write_api.export_run(runs, "t", format="html")
    assert export == {"topic_id": "t", "format": "html", "export_path": "final/guide.html"}


def test_advance_is_a_noop_at_human_steps(tmp_path):
    runs, jobs = _workspace(tmp_path)
    write_api.advance_run(runs, jobs, "t")  # writes the spec prompt
    again = write_api.advance_run(runs, jobs, "t")
    assert again["performed"] is None
    assert again["status"]["next_action"]["action"] == "save_response"


def test_ingest_conflict_and_force(tmp_path):
    runs, jobs = _workspace(tmp_path)
    write_api.advance_run(runs, jobs, "t")
    write_api.ingest_response(runs, jobs, "t", "spec", "first")
    with pytest.raises(write_api.ConflictError) as exc:
        write_api.ingest_response(runs, jobs, "t", "spec", "second")
    assert exc.value.code == "already_exists"
    write_api.ingest_response(runs, jobs, "t", "spec", "second", force=True)
    assert runs.stage_paths("t", "spec").response_path.read_text(encoding="utf-8") == "second"


def test_ingest_empty_text_is_config_error(tmp_path):
    runs, jobs = _workspace(tmp_path)
    write_api.advance_run(runs, jobs, "t")
    with pytest.raises(ConfigError):
        write_api.ingest_response(runs, jobs, "t", "spec", "   \n")


def test_run_actions_404_without_a_run(tmp_path):
    runs, jobs = _workspace(tmp_path)
    with pytest.raises(NotFoundError):
        write_api.ingest_response(runs, jobs, "t", "spec", "x")
    with pytest.raises(NotFoundError):
        write_api.approve_stage(runs, jobs, "t", "spec")
    with pytest.raises(NotFoundError):
        write_api.finalize_run(runs, jobs, "t")
    with pytest.raises(NotFoundError):
        write_api.export_run(runs, "t")


def test_approve_not_ready_then_already_exists(tmp_path):
    runs, jobs = _workspace(tmp_path)
    write_api.advance_run(runs, jobs, "t")
    with pytest.raises(write_api.ConflictError) as exc:
        write_api.approve_stage(runs, jobs, "t", "spec")
    assert exc.value.code == "not_ready"
    write_api.ingest_response(runs, jobs, "t", "spec", "body")
    write_api.approve_stage(runs, jobs, "t", "spec")
    with pytest.raises(write_api.ConflictError) as exc:
        write_api.approve_stage(runs, jobs, "t", "spec")
    assert exc.value.code == "already_exists"
    write_api.approve_stage(runs, jobs, "t", "spec", overwrite=True)


def test_finalize_not_ready_before_repair_approved(tmp_path):
    runs, jobs = _workspace(tmp_path)
    write_api.advance_run(runs, jobs, "t")
    with pytest.raises(write_api.ConflictError) as exc:
        write_api.finalize_run(runs, jobs, "t")
    assert exc.value.code == "not_ready"


def test_export_not_ready_bad_format_and_conflict(tmp_path):
    runs, jobs = _workspace(tmp_path)
    write_api.advance_run(runs, jobs, "t")
    with pytest.raises(ConfigError):
        write_api.export_run(runs, "t", format="docx")
    with pytest.raises(write_api.ConflictError) as exc:
        write_api.export_run(runs, "t", format="html")
    assert exc.value.code == "not_ready"


def test_job_active_blocks_run_mutations_but_not_export(tmp_path):
    runs, jobs = _workspace(tmp_path)
    # Drive the run to finalized so export is possible.
    for stage in SUPPORTED_STAGES:
        write_api.advance_run(runs, jobs, "t")
        write_api.ingest_response(runs, jobs, "t", stage, f"{stage} body")
        write_api.approve_stage(runs, jobs, "t", stage)
    write_api.advance_run(runs, jobs, "t")  # finalize

    job = jobs.create("t", "spec", "fake", None, None)
    jobs.save(job)  # queued == active
    blocked = (
        lambda: write_api.advance_run(runs, jobs, "t"),
        lambda: write_api.ingest_response(runs, jobs, "t", "spec", "x", force=True),
        lambda: write_api.approve_stage(runs, jobs, "t", "spec", overwrite=True),
        lambda: write_api.finalize_run(runs, jobs, "t", overwrite=True),
    )
    for call in blocked:
        with pytest.raises(write_api.ConflictError) as exc:
            call()
        assert exc.value.code == "job_active"
    # export is exempt: it only reads final/ and writes a file the worker never touches
    assert write_api.export_run(runs, "t", format="html")["export_path"] == "final/guide.html"

    job.status = "canceled"
    jobs.save(job)
    assert write_api.advance_run(runs, jobs, "t")["performed"] is None
```

Append to `tests/test_runs.py`:

```python
def test_export_path_names_and_bad_format(tmp_path):
    from education_pipeline.config import ConfigError
    from education_pipeline.runs import RunStore

    runs = RunStore(tmp_path)
    assert runs.export_path("t", "html").name == "guide.html"
    assert runs.export_path("t", "markdown").name == "guide.bundle.md"
    import pytest

    with pytest.raises(ConfigError):
        runs.export_path("t", "docx")
```

- [x] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_write_api.py tests/test_runs.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'education_pipeline.daemon.write_api'` and `AttributeError: ... export_path`

- [x] **Step 3: Implement `RunStore.export_path` and refactor `export_run`**

In `education_pipeline/runs.py`, add after `final_path` (after line 392):

```python
    def export_path(self, topic_id: str, format: str) -> Path:
        """Path an export of ``format`` is (or would be) written to."""

        if format not in EXPORT_FORMATS:
            supported = ", ".join(EXPORT_FORMATS)
            raise ConfigError(f"unsupported export format {format!r}; supported: {supported}")
        name = "guide.bundle.md" if format == "markdown" else "guide.html"
        return self.final_path(topic_id).with_name(name)
```

In `export_run`, replace lines 408-421:

```python
        if format not in EXPORT_FORMATS:
            supported = ", ".join(EXPORT_FORMATS)
            raise ConfigError(f"unsupported export format {format!r}; supported: {supported}")

        safe_id = _artifact_id(topic_id, "topic id")
        guide = self._read_final_guide(safe_id)
        topic = TopicStore(self.root).load_topic(safe_id)

        if format == "markdown":
            content = build_markdown_bundle(guide, front_matter=self._export_front_matter(safe_id, topic))
            export_path = self.final_path(safe_id).with_name("guide.bundle.md")
        else:
            content = render_markdown_to_html(guide, title=topic.title)
            export_path = self.final_path(safe_id).with_name("guide.html")
```

with:

```python
        safe_id = _artifact_id(topic_id, "topic id")
        export_path = self.export_path(safe_id, format)
        guide = self._read_final_guide(safe_id)
        topic = TopicStore(self.root).load_topic(safe_id)

        if format == "markdown":
            content = build_markdown_bundle(guide, front_matter=self._export_front_matter(safe_id, topic))
        else:
            content = render_markdown_to_html(guide, title=topic.title)
```

- [x] **Step 4: Add `require_run` to `read_api.py` and deduplicate**

In `education_pipeline/daemon/read_api.py`, add after the `NotFoundError` class (line 16):

```python
def require_run(runs: RunStore, topic_id: str) -> None:
    """Raise :class:`NotFoundError` unless a run manifest exists for the topic."""

    if not runs.manifest_path(topic_id).is_file():
        raise NotFoundError(f"no run started for topic: {topic_id}")
```

In `run_status_payload`, replace lines 59-60:

```python
    if not runs.manifest_path(topic_id).is_file():
        raise NotFoundError(f"no run started for topic: {topic_id}")
```

with:

```python
    require_run(runs, topic_id)
```

In `stage_content`, replace lines 89-90 (the identical two-line guard) with `require_run(runs, topic_id)`. Leave `manifest_payload`'s distinct message untouched.

- [x] **Step 5: Create `write_api.py`**

Create `education_pipeline/daemon/write_api.py`:

```python
"""Write-action payload builders for the cockpit /v1 API.

Pure functions mirroring ``read_api``: stores in, JSON-serializable dicts out.
Each function pre-checks state on the same paths the store checks so refusals
carry a precise conflict code; the store call remains the authority and its
``ConfigError`` remains the backstop. Raises:

- :class:`read_api.NotFoundError` -> HTTP 404
- :class:`ConflictError` -> HTTP 409 (codes: ``already_exists``, ``not_ready``,
  ``job_active``)
- ``ConfigError`` propagates -> HTTP 400
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from education_pipeline.config import ConfigError
from education_pipeline.daemon import read_api
from education_pipeline.daemon.jobs import JobStore
from education_pipeline.daemon.read_api import NotFoundError
from education_pipeline.runs import RunStore
from education_pipeline.workspace import ProfileStore, TopicStore


class ConflictError(Exception):
    """The request is well-formed but current run/workspace state refuses it."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _run_relative(runs: RunStore, topic_id: str, path: Path) -> str:
    return path.relative_to(runs.run_dir(topic_id)).as_posix()


def _require_no_active_job(jobs: JobStore, topic_id: str) -> None:
    job = jobs.any_active_for(topic_id)
    if job is not None:
        raise ConflictError(
            "job_active",
            f"job {job.id} is {job.status} for topic {topic_id!r}; "
            "wait for it to finish or cancel it first",
        )


def advance_run(runs: RunStore, jobs: JobStore, topic_id: str) -> dict:
    _require_no_active_job(jobs, topic_id)
    result = runs.advance(topic_id)
    return {
        "performed": result.performed,
        "status": read_api.run_status_payload(runs, result.topic_id),
    }


def ingest_response(
    runs: RunStore,
    jobs: JobStore,
    topic_id: str,
    stage: str,
    text: str,
    *,
    force: bool = False,
) -> dict:
    read_api.require_run(runs, topic_id)
    _require_no_active_job(jobs, topic_id)
    paths = runs.stage_paths(topic_id, stage)
    if paths.response_path.exists() and not force:
        raise ConflictError(
            "already_exists",
            f"response already ingested for stage {paths.stage!r}; "
            "retry with force to replace it",
        )
    path = runs.ingest_response(topic_id, stage, text, force=force)
    return {
        "topic_id": paths.topic_id,
        "stage": paths.stage,
        "response_path": _run_relative(runs, topic_id, path),
        "status": read_api.run_status_payload(runs, topic_id),
    }


def approve_stage(
    runs: RunStore,
    jobs: JobStore,
    topic_id: str,
    stage: str,
    *,
    overwrite: bool = False,
) -> dict:
    read_api.require_run(runs, topic_id)
    _require_no_active_job(jobs, topic_id)
    paths = runs.stage_paths(topic_id, stage)
    if not paths.response_path.exists():
        raise ConflictError(
            "not_ready",
            f"no ingested response to approve for stage {paths.stage!r}; save a response first",
        )
    if paths.approved_path.exists() and not overwrite:
        raise ConflictError(
            "already_exists",
            f"stage {paths.stage!r} is already approved; retry with overwrite to replace it",
        )
    path = runs.approve_stage(topic_id, stage, overwrite=overwrite)
    return {
        "topic_id": paths.topic_id,
        "stage": paths.stage,
        "approved_path": _run_relative(runs, topic_id, path),
        "status": read_api.run_status_payload(runs, topic_id),
    }


def finalize_run(
    runs: RunStore, jobs: JobStore, topic_id: str, *, overwrite: bool = False
) -> dict:
    read_api.require_run(runs, topic_id)
    _require_no_active_job(jobs, topic_id)
    if not runs.stage_paths(topic_id, "repair").approved_path.exists():
        raise ConflictError(
            "not_ready", "the repair stage is not approved; approve it before finalizing"
        )
    if runs.final_path(topic_id).exists() and not overwrite:
        raise ConflictError(
            "already_exists",
            "run is already finalized; retry with overwrite to rebuild the final guide",
        )
    path = runs.finalize_run(topic_id, overwrite=overwrite)
    return {
        "topic_id": topic_id,
        "final_path": _run_relative(runs, topic_id, path),
        "status": read_api.run_status_payload(runs, topic_id),
    }


def export_run(
    runs: RunStore, topic_id: str, *, format: str = "html", overwrite: bool = False
) -> dict:
    # Deliberately no job guard: export only reads final/ and writes a new
    # file the worker never touches.
    read_api.require_run(runs, topic_id)
    export_path = runs.export_path(topic_id, format)  # ConfigError on bad format -> 400
    if not runs.is_finalized(topic_id):
        raise ConflictError("not_ready", "run is not finalized; finalize before exporting")
    if export_path.exists() and not overwrite:
        raise ConflictError(
            "already_exists",
            f"{format} export already exists; retry with overwrite to replace it",
        )
    path = runs.export_run(topic_id, format=format, overwrite=overwrite)
    return {
        "topic_id": topic_id,
        "format": format,
        "export_path": _run_relative(runs, topic_id, path),
    }
```

(Workspace imports are added to this module in Task 3; `TopicStore`/`ProfileStore`/`tomllib` imports are already in place for it.)

- [x] **Step 6: Run tests to verify they pass**

Run: `python3 -m pytest tests/ -q`
Expected: PASS (full backend suite — the `read_api` refactor must not break Phase 1 tests)

- [x] **Step 7: Commit**

```bash
git add education_pipeline/daemon/write_api.py education_pipeline/daemon/read_api.py education_pipeline/runs.py tests/test_write_api.py tests/test_runs.py
git commit -m "feat(daemon): write_api run actions with typed 409 conflicts"
```

---

### Task 3: `write_api.py` workspace imports (topics, profiles, attach)

**Files:**
- Modify: `education_pipeline/daemon/write_api.py` (append)
- Test: `tests/test_write_api.py` (append)

**Interfaces:**
- Consumes: `TopicStore.save_topic_toml`, `TopicStore.topic_path`, `ProfileStore.save_profile_toml`, `ProfileStore.profile_path`, `ProfileStore.attach_profile_to_topic`, `ProfileStore.runs_dir`, `tomllib`.
- Produces (used by Task 5's routes):
  - `import_topic(topics: TopicStore, toml_text: str, *, overwrite=False) -> dict` → `{"id", "title"}` — id derived from the TOML document, like `edu topic import`.
  - `import_profile(profiles: ProfileStore, toml_text: str, *, overwrite=False) -> dict` → `{"id"}`
  - `attach_profile(profiles: ProfileStore, topic_id: str, profile_id: str, *, overwrite=True) -> dict` → `{"profile_id", "topic_id", "snapshot_path"}` (default `overwrite=True`, matching `edu profile attach`). Unknown profile → `NotFoundError`.
- No job guard on any of these (they never touch run trees the worker writes; the snapshot lands in `inputs/`, which the worker only reads).

- [x] **Step 1: Write the failing tests**

Append to `tests/test_write_api.py`:

```python
def test_import_topic_derives_id_and_refuses_clobber(tmp_path):
    from education_pipeline.workspace import TopicStore

    topics = TopicStore(tmp_path)
    toml = 'schema_version = 1\nid = "n1"\ntitle = "New One"\n'
    assert write_api.import_topic(topics, toml) == {"id": "n1", "title": "New One"}
    with pytest.raises(write_api.ConflictError) as exc:
        write_api.import_topic(topics, toml)
    assert exc.value.code == "already_exists"
    assert write_api.import_topic(topics, toml, overwrite=True)["id"] == "n1"


def test_import_topic_rejects_bad_toml_and_missing_id(tmp_path):
    from education_pipeline.workspace import TopicStore

    topics = TopicStore(tmp_path)
    with pytest.raises(ConfigError):
        write_api.import_topic(topics, "not = [valid")
    with pytest.raises(ConfigError):
        write_api.import_topic(topics, 'schema_version = 1\ntitle = "No Id"\n')


def test_import_profile(tmp_path):
    from education_pipeline.workspace import ProfileStore

    profiles = ProfileStore(tmp_path)
    toml = 'schema_version = 1\nid = "p1"\ntarget_learner = "team cohort"\n'
    assert write_api.import_profile(profiles, toml) == {"id": "p1"}
    with pytest.raises(write_api.ConflictError) as exc:
        write_api.import_profile(profiles, toml)
    assert exc.value.code == "already_exists"


def test_attach_profile_defaults_to_overwrite(tmp_path):
    from education_pipeline.workspace import ProfileStore

    profiles = ProfileStore(tmp_path)
    write_api.import_profile(
        profiles, 'schema_version = 1\nid = "p1"\ntarget_learner = "team cohort"\n'
    )
    result = write_api.attach_profile(profiles, "t", "p1")
    assert result == {"profile_id": "p1", "topic_id": "t", "snapshot_path": "inputs/profile.toml"}
    # re-attach refreshes the snapshot without an explicit flag
    assert write_api.attach_profile(profiles, "t", "p1")["snapshot_path"] == "inputs/profile.toml"


def test_attach_unknown_profile_is_404(tmp_path):
    from education_pipeline.workspace import ProfileStore

    with pytest.raises(NotFoundError):
        write_api.attach_profile(ProfileStore(tmp_path), "t", "ghost")
```

- [x] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_write_api.py -q -k "import or attach"`
Expected: FAIL with `AttributeError: module ... has no attribute 'import_topic'`

- [x] **Step 3: Implement**

Append to `education_pipeline/daemon/write_api.py`:

```python
def _parse_toml_id(toml_text: str, kind: str) -> str:
    try:
        data = tomllib.loads(toml_text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"invalid TOML in {kind} import: {exc}") from exc
    artifact_id = data.get("id")
    if not isinstance(artifact_id, str) or not artifact_id:
        raise ConfigError(f"{kind} TOML must define a string 'id'")
    return artifact_id


def import_topic(topics: TopicStore, toml_text: str, *, overwrite: bool = False) -> dict:
    topic_id = _parse_toml_id(toml_text, "topic")
    if topics.topic_path(topic_id).is_file() and not overwrite:
        raise ConflictError(
            "already_exists",
            f"topic {topic_id!r} already exists; retry with overwrite to replace it",
        )
    topic = topics.save_topic_toml(topic_id, toml_text, overwrite=overwrite)
    return {"id": topic.id, "title": topic.title}


def import_profile(profiles: ProfileStore, toml_text: str, *, overwrite: bool = False) -> dict:
    profile_id = _parse_toml_id(toml_text, "profile")
    if profiles.profile_path(profile_id).is_file() and not overwrite:
        raise ConflictError(
            "already_exists",
            f"profile {profile_id!r} already exists; retry with overwrite to replace it",
        )
    profile = profiles.save_profile_toml(profile_id, toml_text, overwrite=overwrite)
    return {"id": profile.id}


def attach_profile(
    profiles: ProfileStore, topic_id: str, profile_id: str, *, overwrite: bool = True
) -> dict:
    if not profiles.profile_path(profile_id).is_file():
        raise NotFoundError(f"no such profile: {profile_id}")
    attachment = profiles.attach_profile_to_topic(profile_id, topic_id, overwrite=overwrite)
    run_dir = profiles.runs_dir / attachment.topic_id
    return {
        "profile_id": attachment.profile_id,
        "topic_id": attachment.topic_id,
        "snapshot_path": attachment.snapshot_path.relative_to(run_dir).as_posix(),
    }
```

- [x] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_write_api.py -q`
Expected: PASS

- [x] **Step 5: Commit**

```bash
git add education_pipeline/daemon/write_api.py tests/test_write_api.py
git commit -m "feat(daemon): write_api workspace imports (topic, profile, attach)"
```

---

### Task 4: POST routing — run-action endpoints + 409 mapping + job_active guard

**Files:**
- Modify: `education_pipeline/daemon/server.py` (`do_POST`, lines 236-258; new `_api_post_routes`; module-level `_require_str`; import `write_api`)
- Test: `tests/test_server.py` (append)

**Interfaces:**
- Consumes: Task 2's `write_api` functions, `context.runs`, `context.store` (JobStore).
- Produces routes (all require token+host, JSON body ≤ 1 MiB):
  - `POST /v1/runs/{topic}/advance` — body `{}` allowed
  - `POST /v1/runs/{topic}/stages/{stage}/response` — `{"text": str, "force": false}`
  - `POST /v1/runs/{topic}/stages/{stage}/approve` — `{"overwrite": false}`
  - `POST /v1/runs/{topic}/finalize` — `{"overwrite": false}`
  - `POST /v1/runs/{topic}/export` — `{"format": "html"|"markdown", "overwrite": false}`
  - Error mapping: `NotFoundError` → 404 `not_found`; `ConflictError` → 409 with `exc.code`; `ConfigError` → 400 `bad_request`.
  - `_require_str(body: dict, key: str) -> str` helper (400 on non-string).

- [x] **Step 1: Write the failing tests**

Append to `tests/test_server.py`:

```python
def test_write_endpoints_require_token(server):
    status, body = _req(server, "POST", "/v1/runs/t/advance", token=None)
    assert status == 401
    status, body = _req(server, "POST", "/v1/runs/t/stages/spec/response", token=None, body={"text": "x"})
    assert status == 401


def test_advance_writes_spec_prompt_and_returns_status(server):
    status, body = _req(server, "POST", "/v1/runs/t/advance")
    assert status == 200
    assert body["performed"] == "write_prompt"
    assert body["status"]["next_action"]["action"] == "save_response"
    assert body["status"]["next_action"]["stage"] == "spec"
    # single-step: calling again at a human step is a no-op
    status, body = _req(server, "POST", "/v1/runs/t/advance")
    assert status == 200 and body["performed"] is None


def test_response_ingest_conflict_and_force(server):
    status, body = _req(server, "POST", "/v1/runs/t/stages/draft/response", body={"text": "R1"})
    assert status == 200
    assert body["topic_id"] == "t" and body["stage"] == "draft"
    assert body["response_path"] == "responses/draft.response.md"
    assert body["status"]["stages"][2]["response_ingested"] is True
    status, body = _req(server, "POST", "/v1/runs/t/stages/draft/response", body={"text": "R2"})
    assert status == 409 and body["error"]["code"] == "already_exists"
    status, _ = _req(
        server, "POST", "/v1/runs/t/stages/draft/response", body={"text": "R2", "force": True}
    )
    assert status == 200


def test_response_validation_errors(server):
    status, body = _req(server, "POST", "/v1/runs/t/stages/draft/response", body={"text": "  "})
    assert status == 400
    status, body = _req(server, "POST", "/v1/runs/t/stages/draft/response", body={"text": 42})
    assert status == 400
    status, body = _req(server, "POST", "/v1/runs/t/stages/bogus/response", body={"text": "x"})
    assert status == 400
    status, body = _req(server, "POST", "/v1/runs/ghost/stages/draft/response", body={"text": "x"})
    assert status == 404 and body["error"]["code"] == "not_found"


def test_approve_endpoint_conflict_codes(server):
    status, body = _req(server, "POST", "/v1/runs/t/stages/qa/approve")
    assert status == 409 and body["error"]["code"] == "not_ready"
    _req(server, "POST", "/v1/runs/t/stages/qa/response", body={"text": "QA"})
    status, body = _req(server, "POST", "/v1/runs/t/stages/qa/approve")
    assert status == 200 and body["approved_path"] == "approved/qa.md"
    status, body = _req(server, "POST", "/v1/runs/t/stages/qa/approve")
    assert status == 409 and body["error"]["code"] == "already_exists"
    status, _ = _req(server, "POST", "/v1/runs/t/stages/qa/approve", body={"overwrite": True})
    assert status == 200


def test_finalize_and_export_endpoints(server):
    status, body = _req(server, "POST", "/v1/runs/t/finalize")
    assert status == 409 and body["error"]["code"] == "not_ready"
    status, body = _req(server, "POST", "/v1/runs/t/export", body={"format": "html"})
    assert status == 409 and body["error"]["code"] == "not_ready"

    _req(server, "POST", "/v1/runs/t/stages/repair/response", body={"text": "FINAL BODY"})
    _req(server, "POST", "/v1/runs/t/stages/repair/approve")
    status, body = _req(server, "POST", "/v1/runs/t/finalize")
    assert status == 200 and body["final_path"] == "final/guide.md"
    status, body = _req(server, "POST", "/v1/runs/t/finalize")
    assert status == 409 and body["error"]["code"] == "already_exists"

    status, body = _req(server, "POST", "/v1/runs/t/export", body={"format": "docx"})
    assert status == 400
    status, body = _req(server, "POST", "/v1/runs/t/export", body={"format": "html"})
    assert status == 200
    assert body == {"topic_id": "t", "format": "html", "export_path": "final/guide.html"}
    status, body = _req(server, "POST", "/v1/runs/t/export", body={"format": "html"})
    assert status == 409 and body["error"]["code"] == "already_exists"
    status, _ = _req(server, "POST", "/v1/runs/t/export", body={"format": "html", "overwrite": True})
    assert status == 200


def test_run_writes_blocked_while_job_active(server, monkeypatch):
    import time

    monkeypatch.setenv("FAKE_DELAY", "5")
    status, job = _req(server, "POST", "/v1/jobs", body={"topic_id": "t", "stage": "draft"})
    assert status == 200

    for method_path, body in (
        ("/v1/runs/t/advance", None),
        ("/v1/runs/t/stages/draft/response", {"text": "R"}),
        ("/v1/runs/t/stages/draft/approve", None),
        ("/v1/runs/t/finalize", None),
    ):
        status, resp = _req(server, "POST", method_path, body=body)
        assert status == 409, method_path
        assert resp["error"]["code"] == "job_active", method_path

    status, _ = _req(server, "POST", f"/v1/jobs/{job['id']}/cancel")
    assert status == 200
    for _ in range(200):
        status, current = _req(server, "GET", f"/v1/jobs/{job['id']}")
        if current["status"] in {"succeeded", "failed", "canceled", "interrupted"}:
            break
        time.sleep(0.02)
    assert current["status"] == "canceled"

    status, body = _req(server, "POST", "/v1/runs/t/advance")
    assert status == 200
```

- [x] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_server.py -q -k "advance or response_ingest or response_validation or approve_endpoint or finalize_and_export or job_active or write_endpoints"`
Expected: FAIL — new routes 404 as "unknown path"

- [x] **Step 3: Implement**

In `education_pipeline/daemon/server.py`:

1. Add to the imports (line 19 area): `from education_pipeline.daemon import read_api, write_api`

2. Add a module-level helper after `MAX_REQUEST_BODY_BYTES` (line 26):

```python
def _require_str(body: dict, key: str) -> str:
    value = body.get(key)
    if not isinstance(value, str):
        raise ConfigError(f"body field {key!r} must be a string")
    return value
```

3. Replace the whole `do_POST` method (lines 236-258) with:

```python
        def do_POST(self):
            if not self._guard():
                return
            try:
                return self._api_post_routes()
            except read_api.NotFoundError as exc:
                return self._error(404, "not_found", str(exc))
            except write_api.ConflictError as exc:
                return self._error(409, exc.code, str(exc))
            except ConfigError as exc:
                return self._error(400, "bad_request", str(exc))

        def _api_post_routes(self):
            if self.path == "/v1/jobs":
                body = self._read_body()
                job = context.enqueue_stage(
                    body.get("topic_id", ""), body.get("stage"), bool(body.get("force"))
                )
                return self._send(200, job.to_dict())
            m = re.match(r"^/v1/jobs/([^/]+)/cancel$", self.path)
            if m:
                job = context.worker.cancel(m.group(1))
                if job is None:
                    return self._error(404, "not_found", "no such job")
                return self._send(200, job.to_dict())
            if self.path == "/v1/shutdown":
                self._send(200, {"ok": True})
                context.on_shutdown()
                return
            m = re.match(r"^/v1/runs/([^/?]+)/advance$", self.path)
            if m:
                self._read_body()  # enforce the JSON/size rules even for an empty body
                return self._send(
                    200, write_api.advance_run(context.runs, context.store, m.group(1))
                )
            m = re.match(r"^/v1/runs/([^/?]+)/stages/([^/?]+)/response$", self.path)
            if m:
                body = self._read_body()
                return self._send(
                    200,
                    write_api.ingest_response(
                        context.runs,
                        context.store,
                        m.group(1),
                        m.group(2),
                        _require_str(body, "text"),
                        force=bool(body.get("force")),
                    ),
                )
            m = re.match(r"^/v1/runs/([^/?]+)/stages/([^/?]+)/approve$", self.path)
            if m:
                body = self._read_body()
                return self._send(
                    200,
                    write_api.approve_stage(
                        context.runs,
                        context.store,
                        m.group(1),
                        m.group(2),
                        overwrite=bool(body.get("overwrite")),
                    ),
                )
            m = re.match(r"^/v1/runs/([^/?]+)/finalize$", self.path)
            if m:
                body = self._read_body()
                return self._send(
                    200,
                    write_api.finalize_run(
                        context.runs,
                        context.store,
                        m.group(1),
                        overwrite=bool(body.get("overwrite")),
                    ),
                )
            m = re.match(r"^/v1/runs/([^/?]+)/export$", self.path)
            if m:
                body = self._read_body()
                return self._send(
                    200,
                    write_api.export_run(
                        context.runs,
                        m.group(1),
                        format=body.get("format", "html")
                        if isinstance(body.get("format", "html"), str)
                        else "",
                        overwrite=bool(body.get("overwrite")),
                    ),
                )
            self._error(404, "not_found", "unknown path")
```

(A non-string `format` collapses to `""`, which `RunStore.export_path` rejects with the supported-formats `ConfigError` → 400.)

- [x] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_server.py -q`
Expected: PASS (all, including all pre-existing Phase 1 tests — the `/v1/jobs`, cancel, and shutdown routes must behave identically after the refactor)

- [x] **Step 5: Commit**

```bash
git add education_pipeline/daemon/server.py tests/test_server.py
git commit -m "feat(daemon): POST run-action endpoints with 409 conflict mapping"
```

---

### Task 5: POST routing — workspace import endpoints

**Files:**
- Modify: `education_pipeline/daemon/server.py` (`_api_post_routes`, before the trailing `unknown path` fallback)
- Test: `tests/test_server.py` (append)

**Interfaces:**
- Consumes: Task 3's `write_api.import_topic` / `import_profile` / `attach_profile`, `context.topics`, `context.profiles`, `_require_str`.
- Produces routes:
  - `POST /v1/topics` — `{"toml": str, "overwrite": false}` → `{"id", "title"}`
  - `POST /v1/profiles` — `{"toml": str, "overwrite": false}` → `{"id"}`
  - `POST /v1/topics/{topic}/profile` — `{"profile_id": str, "overwrite": true}` → `{"profile_id", "topic_id", "snapshot_path"}`

- [x] **Step 1: Write the failing tests**

Append to `tests/test_server.py`:

```python
def test_import_topic_endpoint(server):
    toml = 'schema_version = 1\nid = "n1"\ntitle = "New One"\n'
    status, body = _req(server, "POST", "/v1/topics", body={"toml": toml})
    assert status == 200 and body == {"id": "n1", "title": "New One"}
    status, body = _req(server, "POST", "/v1/topics", body={"toml": toml})
    assert status == 409 and body["error"]["code"] == "already_exists"
    status, _ = _req(server, "POST", "/v1/topics", body={"toml": toml, "overwrite": True})
    assert status == 200
    # imported topic is visible to the read API
    status, body = _req(server, "GET", "/v1/topics/n1")
    assert status == 200 and body["title"] == "New One"


def test_import_topic_rejects_invalid_input(server):
    status, _ = _req(server, "POST", "/v1/topics", body={"toml": "not = [valid"})
    assert status == 400
    status, _ = _req(server, "POST", "/v1/topics", body={"toml": 'schema_version = 1\ntitle = "No Id"\n'})
    assert status == 400
    status, _ = _req(server, "POST", "/v1/topics", body={"toml": 42})
    assert status == 400


def test_import_profile_endpoint(server):
    toml = 'schema_version = 1\nid = "p2"\ntarget_learner = "new cohort"\n'
    status, body = _req(server, "POST", "/v1/profiles", body={"toml": toml})
    assert status == 200 and body == {"id": "p2"}
    # fixture already created profile "p"
    existing = 'schema_version = 1\nid = "p"\ntarget_learner = "changed"\n'
    status, body = _req(server, "POST", "/v1/profiles", body={"toml": existing})
    assert status == 409 and body["error"]["code"] == "already_exists"


def test_attach_profile_endpoint(server):
    status, body = _req(server, "POST", "/v1/topics/t/profile", body={"profile_id": "p"})
    assert status == 200
    assert body == {"profile_id": "p", "topic_id": "t", "snapshot_path": "inputs/profile.toml"}
    # default overwrite=true: re-attaching refreshes the snapshot
    status, _ = _req(server, "POST", "/v1/topics/t/profile", body={"profile_id": "p"})
    assert status == 200
    status, body = _req(server, "POST", "/v1/topics/t/profile", body={"profile_id": "ghost"})
    assert status == 404
    status, body = _req(server, "POST", "/v1/topics/t/profile", body={"profile_id": 7})
    assert status == 400
```

- [x] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_server.py -q -k "import_topic or import_profile or attach_profile"`
Expected: FAIL — 404 "unknown path"

- [x] **Step 3: Implement**

In `_api_post_routes` (Task 4's method), insert before the trailing `self._error(404, "not_found", "unknown path")`:

```python
            if self.path == "/v1/topics":
                body = self._read_body()
                return self._send(
                    200,
                    write_api.import_topic(
                        context.topics,
                        _require_str(body, "toml"),
                        overwrite=bool(body.get("overwrite")),
                    ),
                )
            if self.path == "/v1/profiles":
                body = self._read_body()
                return self._send(
                    200,
                    write_api.import_profile(
                        context.profiles,
                        _require_str(body, "toml"),
                        overwrite=bool(body.get("overwrite")),
                    ),
                )
            m = re.match(r"^/v1/topics/([^/?]+)/profile$", self.path)
            if m:
                body = self._read_body()
                return self._send(
                    200,
                    write_api.attach_profile(
                        context.profiles,
                        m.group(1),
                        _require_str(body, "profile_id"),
                        overwrite=bool(body.get("overwrite", True)),
                    ),
                )
```

- [x] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_server.py -q`
Expected: PASS

- [x] **Step 5: Commit**

```bash
git add education_pipeline/daemon/server.py tests/test_server.py
git commit -m "feat(daemon): topic/profile import and attach endpoints"
```

---

### Task 6: Download endpoints (final guide + exports)

**Files:**
- Modify: `education_pipeline/daemon/read_api.py` (download path resolvers)
- Modify: `education_pipeline/daemon/server.py` (`_send_file`; two routes in `_api_get_routes` before the bare `^/v1/runs/([^/?]+)$` match)
- Test: `tests/test_server.py` (append)

**Interfaces:**
- Consumes: `RunStore.final_path`, `RunStore.export_path` (Task 2).
- Produces:
  - `read_api.final_download_path(runs, topic_id) -> Path` — 404 `NotFoundError` if not finalized.
  - `read_api.export_download_path(runs, topic_id, format) -> Path` — `ConfigError` (400) on bad format, `NotFoundError` (404) if that export wasn't produced.
  - `GET /v1/runs/{topic}/final/download` → `text/markdown; charset=utf-8`, `Content-Disposition: attachment; filename="{topic}-guide.md"`.
  - `GET /v1/runs/{topic}/exports/{format}/download` → `html` as `text/html; charset=utf-8` filename `{topic}-guide.html`; `markdown` as `text/markdown; charset=utf-8` filename `{topic}-guide.bundle.md`.
  - Both require the token (they are under `/v1/`, so the existing `do_GET` auth gate already applies). Only these two fixed paths inside `final/` are ever served — no client-supplied filenames.

- [x] **Step 1: Write the failing tests**

Append to `tests/test_server.py`:

```python
def _raw_download(port, path, token="secret-token"):
    conn = http.client.HTTPConnection("127.0.0.1", port)
    headers = {}
    if token is not None:
        headers["X-EP-Token"] = token
    conn.request("GET", path, headers=headers)
    resp = conn.getresponse()
    data = resp.read()
    headers_out = {k.lower(): v for k, v in resp.getheaders()}
    conn.close()
    return resp.status, headers_out, data


def _finalize_t_over_http(port):
    _req(port, "POST", "/v1/runs/t/stages/repair/response", body={"text": "FINAL BODY"})
    _req(port, "POST", "/v1/runs/t/stages/repair/approve")
    _req(port, "POST", "/v1/runs/t/finalize")


def test_final_download(server):
    status, _, _ = _raw_download(server, "/v1/runs/t/final/download")
    assert status == 404
    _finalize_t_over_http(server)
    status, headers, data = _raw_download(server, "/v1/runs/t/final/download")
    assert status == 200
    assert headers["content-type"] == "text/markdown; charset=utf-8"
    assert headers["content-disposition"] == 'attachment; filename="t-guide.md"'
    assert data.decode("utf-8") == "FINAL BODY"


def test_export_download(server):
    _finalize_t_over_http(server)
    _req(server, "POST", "/v1/runs/t/export", body={"format": "html"})
    status, headers, data = _raw_download(server, "/v1/runs/t/exports/html/download")
    assert status == 200
    assert headers["content-type"] == "text/html; charset=utf-8"
    assert headers["content-disposition"] == 'attachment; filename="t-guide.html"'
    assert b"FINAL BODY" in data
    status, _, _ = _raw_download(server, "/v1/runs/t/exports/markdown/download")
    assert status == 404
    status, _, _ = _raw_download(server, "/v1/runs/t/exports/docx/download")
    assert status == 400


def test_downloads_require_token(server):
    status, _, _ = _raw_download(server, "/v1/runs/t/final/download", token=None)
    assert status == 401
```

- [x] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_server.py -q -k download`
Expected: FAIL — routes fall through to 404 even after finalize / 401 test may pass already; the 200 assertions fail

- [x] **Step 3: Implement the resolvers in `read_api.py`**

Append to `education_pipeline/daemon/read_api.py` (add `from pathlib import Path` to imports):

```python
def final_download_path(runs: RunStore, topic_id: str) -> Path:
    path = runs.final_path(topic_id)  # ConfigError on a bad id -> 400
    if not path.is_file():
        raise NotFoundError(f"run {topic_id!r} is not finalized")
    return path


def export_download_path(runs: RunStore, topic_id: str, format: str) -> Path:
    path = runs.export_path(topic_id, format)  # ConfigError on bad format -> 400
    if not path.is_file():
        raise NotFoundError(f"no {format} export produced for topic {topic_id!r}")
    return path
```

- [x] **Step 4: Implement `_send_file` and the GET routes**

In `server.py`, add next to `_send` (after line 101):

```python
        def _send_file(self, path, content_type: str, filename: str) -> None:
            body = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.end_headers()
            self.wfile.write(body)
```

In `_api_get_routes`, insert **before** the `^/v1/runs/([^/?]+)$` match (line 208):

```python
            m = re.match(r"^/v1/runs/([^/?]+)/final/download$", self.path)
            if m:
                topic_id = m.group(1)
                path = read_api.final_download_path(context.runs, topic_id)
                return self._send_file(
                    path, "text/markdown; charset=utf-8", f"{topic_id}-guide.md"
                )
            m = re.match(r"^/v1/runs/([^/?]+)/exports/([^/?]+)/download$", self.path)
            if m:
                topic_id, fmt = m.group(1), m.group(2)
                path = read_api.export_download_path(context.runs, topic_id, fmt)
                if fmt == "html":
                    return self._send_file(
                        path, "text/html; charset=utf-8", f"{topic_id}-guide.html"
                    )
                return self._send_file(
                    path, "text/markdown; charset=utf-8", f"{topic_id}-guide.bundle.md"
                )
```

(The filename embeds only the regex-captured topic id, which `RunStore.final_path` has already validated against `_ARTIFACT_ID_PATTERN` — quotes/CR/LF can never appear.)

- [x] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_server.py -q`
Expected: PASS

- [x] **Step 6: Commit**

```bash
git add education_pipeline/daemon/read_api.py education_pipeline/daemon/server.py tests/test_server.py
git commit -m "feat(daemon): authed download endpoints for final guide and exports"
```

---

### Task 7: Full-pipeline HTTP test (spec → export → download, manifest audit)

**Files:**
- Test: `tests/test_server.py` (append)

**Interfaces:**
- Consumes: every endpoint from Tasks 4-6 plus Phase 1's manifest endpoint. No production code.

- [x] **Step 1: Write the test**

Append to `tests/test_server.py`:

```python
def test_full_pipeline_over_http(server):
    toml = 'schema_version = 1\nid = "full"\ntitle = "Full Pipeline"\n'
    status, body = _req(server, "POST", "/v1/topics", body={"toml": toml})
    assert (status, body) == (200, {"id": "full", "title": "Full Pipeline"})

    for stage in ("spec", "outline", "draft", "qa", "repair"):
        status, body = _req(server, "POST", "/v1/runs/full/advance")
        assert status == 200 and body["performed"] == "write_prompt", stage
        assert body["status"]["next_action"]["stage"] == stage
        status, _ = _req(
            server,
            "POST",
            f"/v1/runs/full/stages/{stage}/response",
            body={"text": f"{stage} response"},
        )
        assert status == 200, stage
        status, _ = _req(server, "POST", f"/v1/runs/full/stages/{stage}/approve")
        assert status == 200, stage

    status, body = _req(server, "POST", "/v1/runs/full/advance")
    assert status == 200 and body["performed"] == "finalize"
    assert body["status"]["finalized"] is True
    assert body["status"]["next_action"]["action"] == "done"

    for fmt in ("html", "markdown"):
        status, _ = _req(server, "POST", "/v1/runs/full/export", body={"format": fmt})
        assert status == 200, fmt

    status, manifest = _req(server, "GET", "/v1/runs/full/manifest")
    assert status == 200
    actions = [event["action"] for event in manifest["events"]]
    assert actions.count("prompt_written") == 5
    assert actions.count("response_approved") == 5
    assert actions.count("finalized") == 1
    assert actions.count("exported") == 2

    for path, ctype in (
        ("/v1/runs/full/final/download", "text/markdown; charset=utf-8"),
        ("/v1/runs/full/exports/html/download", "text/html; charset=utf-8"),
        ("/v1/runs/full/exports/markdown/download", "text/markdown; charset=utf-8"),
    ):
        status, headers, _ = _raw_download(server, path)
        assert status == 200, path
        assert headers["content-type"] == ctype, path
```

- [x] **Step 2: Run it**

Run: `python3 -m pytest tests/test_server.py::test_full_pipeline_over_http -v`
Expected: PASS (if it fails, the defect is in Tasks 2-6 — fix there, not here)

- [x] **Step 3: Run the whole backend suite and commit**

Run: `python3 -m pytest tests/ -q`
Expected: PASS

```bash
git add tests/test_server.py
git commit -m "test(daemon): full spec-to-export pipeline over HTTP with manifest audit"
```

---

### Task 8: Client — `apiPost`, `download`, typed helpers, new types

**Files:**
- Modify: `web/src/api/types.ts` (append)
- Modify: `web/src/api/client.ts`
- Test: `web/src/api/client.test.ts` (append)

**Interfaces:**
- Consumes: existing `getToken()`, `ApiRequestError`.
- Produces (used by every UI task):
  - `apiPost<T>(path: string, body: unknown): Promise<T>` — POST, JSON body, token header, same envelope→`ApiRequestError` mapping.
  - `download(path: string, filename: string): Promise<void>` — authed fetch → blob → temporary object URL → anchor click.
  - `getProfiles(): Promise<{ profiles: string[] }>`
  - `postAdvance(topicId)`, `postResponse(topicId, stage, text, force=false)`, `postApprove(topicId, stage, overwrite=false)`, `postFinalize(topicId, overwrite=false)`, `postExport(topicId, format, overwrite=false)`, `importTopic(toml, overwrite=false)`, `importProfile(toml, overwrite=false)`, `attachProfile(topicId, profileId)`, `enqueueJob(topicId, stage?)`, `cancelJob(jobId)`, `downloadFinal(topicId)`, `downloadExport(topicId, format)`.
  - Types: `ExportFormat`, `AdvanceResult`, `ResponseResult`, `ApproveResult`, `FinalizeResult`, `ExportResult`, `ImportTopicResult`, `ImportProfileResult`, `AttachProfileResult`.

- [x] **Step 1: Write the failing tests**

Append to `web/src/api/client.test.ts` (extend the existing `mockFetch`-style setup; add these imports at the top: `apiPost`, `download`, `postResponse` from `./client`, and `afterEach` already imported):

```typescript
function mockFetchWithInit(
  routes: Record<string, { status: number; body: unknown }>,
) {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    const route = routes[path];
    if (!route) throw new Error(`unexpected fetch: ${path}`);
    void init;
    return {
      ok: route.status >= 200 && route.status < 300,
      status: route.status,
      json: async () => route.body,
    } as Response;
  });
}

describe("apiPost", () => {
  afterEach(() => {
    resetSessionForTests();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("sends a JSON POST with the token header", async () => {
    const fetchMock = mockFetchWithInit({
      "/v1/session": { status: 200, body: { token: "tok", version: "0.1.0" } },
      "/v1/runs/t/stages/draft/response": {
        status: 200,
        body: { topic_id: "t", stage: "draft", response_path: "responses/draft.response.md" },
      },
    });
    vi.stubGlobal("fetch", fetchMock);

    await postResponse("t", "draft", "hello");

    const call = fetchMock.mock.calls.find(
      ([u]) => String(u) === "/v1/runs/t/stages/draft/response",
    );
    const init = call![1] as RequestInit;
    expect(init.method).toBe("POST");
    expect(init.headers).toMatchObject({
      "X-EP-Token": "tok",
      "Content-Type": "application/json",
    });
    expect(JSON.parse(init.body as string)).toEqual({ text: "hello", force: false });
  });

  it("maps the error envelope, preserving 409 conflict codes", async () => {
    vi.stubGlobal(
      "fetch",
      mockFetchWithInit({
        "/v1/session": { status: 200, body: { token: "tok", version: "0.1.0" } },
        "/v1/runs/t/finalize": {
          status: 409,
          body: { error: { code: "already_exists", message: "run is already finalized" } },
        },
      }),
    );
    const err = (await apiPost("/v1/runs/t/finalize", {}).catch((e) => e)) as ApiRequestError;
    expect(err).toBeInstanceOf(ApiRequestError);
    expect(err.status).toBe(409);
    expect(err.code).toBe("already_exists");
  });
});

describe("download", () => {
  afterEach(() => {
    resetSessionForTests();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("fetches with auth and clicks a temporary object-URL anchor", async () => {
    const blob = new Blob(["guide body"]);
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
        if (String(input) === "/v1/session") {
          return {
            ok: true,
            status: 200,
            json: async () => ({ token: "tok", version: "0.1.0" }),
          } as Response;
        }
        return {
          ok: true,
          status: 200,
          blob: async () => blob,
          json: async () => ({}),
        } as unknown as Response;
      }),
    );
    const createObjectURL = vi.fn(() => "blob:fake");
    const revokeObjectURL = vi.fn();
    Object.assign(URL, { createObjectURL, revokeObjectURL });
    const click = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => {});

    await download("/v1/runs/t/final/download", "t-guide.md");

    expect(createObjectURL).toHaveBeenCalled();
    expect(click).toHaveBeenCalled();
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:fake");
  });

  it("throws ApiRequestError from the envelope on failure", async () => {
    vi.stubGlobal(
      "fetch",
      mockFetchWithInit({
        "/v1/session": { status: 200, body: { token: "tok", version: "0.1.0" } },
        "/v1/runs/t/final/download": {
          status: 404,
          body: { error: { code: "not_found", message: "run 't' is not finalized" } },
        },
      }),
    );
    const err = (await download("/v1/runs/t/final/download", "t-guide.md").catch(
      (e) => e,
    )) as ApiRequestError;
    expect(err).toBeInstanceOf(ApiRequestError);
    expect(err.status).toBe(404);
    expect(err.code).toBe("not_found");
  });
});
```

- [x] **Step 2: Run tests to verify they fail**

Run (from `web/`): `npm test`
Expected: FAIL — `apiPost`/`download`/`postResponse` not exported

- [x] **Step 3: Add the types**

Append to `web/src/api/types.ts`:

```typescript
export type ExportFormat = "html" | "markdown";

export interface AdvanceResult {
  performed: "write_prompt" | "finalize" | null;
  status: RunStatus;
}

export interface ResponseResult {
  topic_id: string;
  stage: string;
  response_path: string;
  status: RunStatus;
}

export interface ApproveResult {
  topic_id: string;
  stage: string;
  approved_path: string;
  status: RunStatus;
}

export interface FinalizeResult {
  topic_id: string;
  final_path: string;
  status: RunStatus;
}

export interface ExportResult {
  topic_id: string;
  format: ExportFormat;
  export_path: string;
}

export interface ImportTopicResult {
  id: string;
  title: string;
}

export interface ImportProfileResult {
  id: string;
}

export interface AttachProfileResult {
  profile_id: string;
  topic_id: string;
  snapshot_path: string;
}
```

- [x] **Step 4: Refactor `client.ts` around a shared `request` and add the helpers**

In `web/src/api/client.ts`, extend the type-only import to include the new types, then replace the existing `api` function (lines 50-68) with:

```typescript
async function request<T>(
  path: string,
  init: { method?: string; headers?: Record<string, string>; body?: string } = {},
): Promise<T> {
  const token = await getToken();
  const resp = await fetch(path, {
    ...init,
    headers: { ...(init.headers ?? {}), "X-EP-Token": token },
  });
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

export async function api<T>(path: string): Promise<T> {
  return request<T>(path);
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function download(path: string, filename: string): Promise<void> {
  const token = await getToken();
  const resp = await fetch(path, { headers: { "X-EP-Token": token } });
  if (!resp.ok) {
    let body: unknown = {};
    try {
      body = await resp.json();
    } catch {
      // non-JSON body; fall through to the generic error below
    }
    const err = (body as { error?: { code: string; message: string } }).error;
    throw new ApiRequestError(
      resp.status,
      err?.code ?? "unknown",
      err?.message ?? `HTTP ${resp.status}`,
    );
  }
  const blob = await resp.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}
```

Then append after the existing GET helpers:

```typescript
export const getProfiles = () => api<{ profiles: string[] }>("/v1/profiles");

export const postAdvance = (topicId: string) =>
  apiPost<AdvanceResult>(`/v1/runs/${encodeURIComponent(topicId)}/advance`, {});
export const postResponse = (topicId: string, stage: string, text: string, force = false) =>
  apiPost<ResponseResult>(
    `/v1/runs/${encodeURIComponent(topicId)}/stages/${encodeURIComponent(stage)}/response`,
    { text, force },
  );
export const postApprove = (topicId: string, stage: string, overwrite = false) =>
  apiPost<ApproveResult>(
    `/v1/runs/${encodeURIComponent(topicId)}/stages/${encodeURIComponent(stage)}/approve`,
    { overwrite },
  );
export const postFinalize = (topicId: string, overwrite = false) =>
  apiPost<FinalizeResult>(`/v1/runs/${encodeURIComponent(topicId)}/finalize`, { overwrite });
export const postExport = (topicId: string, format: ExportFormat, overwrite = false) =>
  apiPost<ExportResult>(`/v1/runs/${encodeURIComponent(topicId)}/export`, {
    format,
    overwrite,
  });
export const importTopic = (toml: string, overwrite = false) =>
  apiPost<ImportTopicResult>("/v1/topics", { toml, overwrite });
export const importProfile = (toml: string, overwrite = false) =>
  apiPost<ImportProfileResult>("/v1/profiles", { toml, overwrite });
export const attachProfile = (topicId: string, profileId: string) =>
  apiPost<AttachProfileResult>(`/v1/topics/${encodeURIComponent(topicId)}/profile`, {
    profile_id: profileId,
  });
export const enqueueJob = (topicId: string, stage?: string) =>
  apiPost<Job>("/v1/jobs", stage ? { topic_id: topicId, stage } : { topic_id: topicId });
export const cancelJob = (jobId: string) =>
  apiPost<Job>(`/v1/jobs/${encodeURIComponent(jobId)}/cancel`, {});
export const downloadFinal = (topicId: string) =>
  download(`/v1/runs/${encodeURIComponent(topicId)}/final/download`, `${topicId}-guide.md`);
export const downloadExport = (topicId: string, format: ExportFormat) =>
  download(
    `/v1/runs/${encodeURIComponent(topicId)}/exports/${format}/download`,
    format === "html" ? `${topicId}-guide.html` : `${topicId}-guide.bundle.md`,
  );
```

- [x] **Step 5: Run tests + typecheck**

Run (from `web/`): `npm test && npm run build`
Expected: PASS / clean build

- [x] **Step 6: Commit**

```bash
git add web/src/api/types.ts web/src/api/client.ts web/src/api/client.test.ts
git commit -m "feat(web): apiPost/download client helpers and write-action types"
```

---

### Task 9: `useAction` hook — in-flight state, feedback, overwrite-confirm retry

**Files:**
- Create: `web/src/hooks/useAction.ts`
- Test: `web/src/hooks/useAction.test.ts`

**Interfaces:**
- Consumes: `ApiRequestError` from `../api/client`.
- Produces: `useAction(onSuccess?: () => void)` returning `{ busy: boolean; feedback: string | null; isError: boolean; run }` where `run<T>(fn: () => Promise<T>, opts?: { retryWithOverwrite?: () => Promise<T>; successMessage?: string }): Promise<void>`. On a `409 already_exists` with a `retryWithOverwrite` supplied, shows `window.confirm("<message>\n\nOverwrite?")` and retries on OK. Every UI task consumes this.

- [x] **Step 1: Write the failing tests**

Create `web/src/hooks/useAction.test.ts`:

```typescript
import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiRequestError } from "../api/client";
import { useAction } from "./useAction";

describe("useAction", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("reports success and calls onSuccess", async () => {
    const onSuccess = vi.fn();
    const { result } = renderHook(() => useAction(onSuccess));
    await act(() => result.current.run(() => Promise.resolve("ok"), { successMessage: "Saved." }));
    expect(onSuccess).toHaveBeenCalledTimes(1);
    expect(result.current.feedback).toBe("Saved.");
    expect(result.current.isError).toBe(false);
  });

  it("surfaces the error message on failure", async () => {
    const { result } = renderHook(() => useAction());
    await act(() =>
      result.current.run(() =>
        Promise.reject(new ApiRequestError(409, "job_active", "job x is running for topic 't'")),
      ),
    );
    expect(result.current.isError).toBe(true);
    expect(result.current.feedback).toBe("job x is running for topic 't'");
  });

  it("retries with overwrite when the user confirms a 409 already_exists", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const retry = vi.fn().mockResolvedValue("done");
    const { result } = renderHook(() => useAction());
    await act(() =>
      result.current.run(
        () => Promise.reject(new ApiRequestError(409, "already_exists", "already approved")),
        { retryWithOverwrite: retry, successMessage: "Approved." },
      ),
    );
    expect(retry).toHaveBeenCalledTimes(1);
    expect(result.current.isError).toBe(false);
    expect(result.current.feedback).toBe("Approved.");
  });

  it("does not retry when the confirm is declined", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(false);
    const retry = vi.fn();
    const { result } = renderHook(() => useAction());
    await act(() =>
      result.current.run(
        () => Promise.reject(new ApiRequestError(409, "already_exists", "already approved")),
        { retryWithOverwrite: retry },
      ),
    );
    expect(retry).not.toHaveBeenCalled();
    expect(result.current.isError).toBe(true);
    expect(result.current.feedback).toBe("already approved");
  });

  it("is busy while the action is in flight", async () => {
    let resolve!: (value: string) => void;
    const pending = new Promise<string>((r) => {
      resolve = r;
    });
    const { result } = renderHook(() => useAction());
    let done!: Promise<void>;
    act(() => {
      done = result.current.run(() => pending);
    });
    expect(result.current.busy).toBe(true);
    await act(async () => {
      resolve("ok");
      await done;
    });
    expect(result.current.busy).toBe(false);
  });
});
```

- [x] **Step 2: Run tests to verify they fail**

Run (from `web/`): `npm test`
Expected: FAIL — cannot resolve `./useAction`

- [x] **Step 3: Implement**

Create `web/src/hooks/useAction.ts`:

```typescript
import { useCallback, useState } from "react";
import { ApiRequestError } from "../api/client";

interface RunOptions<T> {
  retryWithOverwrite?: () => Promise<T>;
  successMessage?: string;
}

export function useAction(onSuccess?: () => void) {
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [isError, setIsError] = useState(false);

  const run = useCallback(
    async <T>(fn: () => Promise<T>, opts: RunOptions<T> = {}): Promise<void> => {
      setBusy(true);
      setFeedback(null);
      setIsError(false);
      try {
        try {
          await fn();
        } catch (err) {
          const conflict =
            err instanceof ApiRequestError &&
            err.status === 409 &&
            err.code === "already_exists";
          if (
            conflict &&
            opts.retryWithOverwrite &&
            window.confirm(`${(err as Error).message}\n\nOverwrite?`)
          ) {
            await opts.retryWithOverwrite();
          } else {
            throw err;
          }
        }
        setFeedback(opts.successMessage ?? "Done.");
        onSuccess?.();
      } catch (err) {
        setIsError(true);
        setFeedback(err instanceof Error ? err.message : String(err));
      } finally {
        setBusy(false);
      }
    },
    [onSuccess],
  );

  return { busy, feedback, isError, run };
}
```

- [x] **Step 4: Run tests to verify they pass**

Run (from `web/`): `npm test`
Expected: PASS

- [x] **Step 5: Commit**

```bash
git add web/src/hooks/useAction.ts web/src/hooks/useAction.test.ts
git commit -m "feat(web): useAction hook with overwrite-confirm retry"
```

---

### Task 10: Run board primary action (Advance / Run+Paste / Approve / Finalize)

**Files:**
- Create: `web/src/components/PrimaryAction.tsx`, `web/src/components/ResponseForm.tsx`
- Modify: `web/src/pages/RunBoardPage.tsx`
- Test: `web/src/components/PrimaryAction.test.tsx` (new), `web/src/pages/RunBoardPage.test.tsx` (update mock + add cases)

**Interfaces:**
- Consumes: Task 8 helpers (`postAdvance`, `postApprove`, `postFinalize`, `postResponse`, `enqueueJob`), Task 9's `useAction`, `usePolling`'s existing `refresh`, Task 11's `ExportControls` (rendered for `done` — Task 11 creates it; until then use the stub in Step 3).
- Produces:
  - `PrimaryAction({ status, onChanged }: { status: RunStatus; onChanged: () => void })` — renders exactly one primary action from `status.next_action.action`.
  - `ResponseForm({ topicId, stage, onDone }: { topicId: string; stage: string; onDone: () => void })` — textarea labelled `Response for {stage}` + "Save response" button; `force` retry on conflict. Reused by Task 12's stage viewer.
  - RunBoardPage renders `PrimaryAction` and, on the 404 no-run branch, an **Advance** button that starts the run (`POST .../advance` works on a fresh topic, matching `edu advance`). This replaces the `edu advance {topicId}` CLI hint — resolving the Phase 1 Minor finding about that string.

- [x] **Step 1: Write the failing tests**

Create `web/src/components/PrimaryAction.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { NextAction, RunStatus } from "../api/types";
import PrimaryAction from "./PrimaryAction";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return {
    ApiRequestError: actual.ApiRequestError,
    postAdvance: vi.fn(),
    postApprove: vi.fn(),
    postFinalize: vi.fn(),
    postResponse: vi.fn(),
    postExport: vi.fn(),
    enqueueJob: vi.fn(),
    downloadFinal: vi.fn(),
    downloadExport: vi.fn(),
  };
});

import {
  ApiRequestError,
  enqueueJob,
  postAdvance,
  postApprove,
  postFinalize,
  postResponse,
} from "../api/client";

beforeEach(() => {
  vi.clearAllMocks();
  vi.restoreAllMocks();
});

function makeStatus(action: NextAction["action"], stage: string | null): RunStatus {
  return {
    topic_id: "t",
    finalized: action === "done",
    stages: [],
    next_action: { topic_id: "t", stage, action, detail: `detail for ${action}` },
  };
}

function renderAction(status: RunStatus, onChanged = vi.fn()) {
  render(
    <MemoryRouter>
      <PrimaryAction status={status} onChanged={onChanged} />
    </MemoryRouter>,
  );
  return onChanged;
}

describe("PrimaryAction", () => {
  it("write_prompt renders Advance and posts it", async () => {
    vi.mocked(postAdvance).mockResolvedValue({
      performed: "write_prompt",
      status: makeStatus("save_response", "spec"),
    });
    const onChanged = renderAction(makeStatus("write_prompt", "spec"));
    await userEvent.click(screen.getByRole("button", { name: "Advance" }));
    expect(postAdvance).toHaveBeenCalledWith("t");
    expect(onChanged).toHaveBeenCalled();
    expect(await screen.findByText("Prompt written.")).toBeInTheDocument();
  });

  it("save_response renders provider run and paste form", async () => {
    vi.mocked(enqueueJob).mockResolvedValue({} as never);
    vi.mocked(postResponse).mockResolvedValue({} as never);
    const onChanged = renderAction(makeStatus("save_response", "draft"));

    await userEvent.click(screen.getByRole("button", { name: "Run with provider" }));
    expect(enqueueJob).toHaveBeenCalledWith("t");

    await userEvent.click(screen.getByRole("button", { name: "Paste response…" }));
    await userEvent.type(screen.getByLabelText("Response for draft"), "draft body");
    await userEvent.click(screen.getByRole("button", { name: "Save response" }));
    expect(postResponse).toHaveBeenCalledWith("t", "draft", "draft body");
    expect(onChanged).toHaveBeenCalled();
  });

  it("approve renders Approve {stage} with a review link", async () => {
    vi.mocked(postApprove).mockResolvedValue({} as never);
    renderAction(makeStatus("approve", "qa"));
    expect(screen.getByRole("link", { name: "review first" })).toHaveAttribute(
      "href",
      "/topics/t/stages/qa",
    );
    await userEvent.click(screen.getByRole("button", { name: "Approve qa" }));
    expect(postApprove).toHaveBeenCalledWith("t", "qa");
  });

  it("retries approve with overwrite after a confirmed 409", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    vi.mocked(postApprove)
      .mockRejectedValueOnce(new ApiRequestError(409, "already_exists", "already approved"))
      .mockResolvedValueOnce({} as never);
    renderAction(makeStatus("approve", "qa"));
    await userEvent.click(screen.getByRole("button", { name: "Approve qa" }));
    expect(postApprove).toHaveBeenNthCalledWith(1, "t", "qa");
    expect(postApprove).toHaveBeenNthCalledWith(2, "t", "qa", true);
  });

  it("finalize renders Finalize", async () => {
    vi.mocked(postFinalize).mockResolvedValue({} as never);
    renderAction(makeStatus("finalize", null));
    await userEvent.click(screen.getByRole("button", { name: "Finalize" }));
    expect(postFinalize).toHaveBeenCalledWith("t");
  });

  it("shows the envelope message on job_active", async () => {
    vi.mocked(postAdvance).mockRejectedValue(
      new ApiRequestError(409, "job_active", "job j1 is running for topic 't'"),
    );
    renderAction(makeStatus("write_prompt", "spec"));
    await userEvent.click(screen.getByRole("button", { name: "Advance" }));
    expect(
      await screen.findByText(/job j1 is running for topic 't'/),
    ).toBeInTheDocument();
  });
});
```

In `web/src/pages/RunBoardPage.test.tsx`, extend the `vi.mock` factory's returned object with `postAdvance: vi.fn(), postApprove: vi.fn(), postFinalize: vi.fn(), postResponse: vi.fn(), postExport: vi.fn(), enqueueJob: vi.fn(), downloadFinal: vi.fn(), downloadExport: vi.fn(), cancelJob: vi.fn()`, add `postAdvance` to the import from `../api/client`, add `import userEvent from "@testing-library/user-event";`, and append:

```tsx
  it("renders the primary action for the current next_action", async () => {
    vi.mocked(getRunStatus).mockResolvedValue(status); // fixture action: save_response
    vi.mocked(getJobs).mockResolvedValue({ jobs: [] });
    renderAt("/topics/t");
    expect(
      await screen.findByRole("button", { name: "Run with provider" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Paste response…" })).toBeInTheDocument();
  });

  it("offers Advance to start a run on the 404 branch", async () => {
    vi.mocked(getRunStatus).mockRejectedValue(
      new ApiRequestError(404, "not_found", "no run started for topic: t"),
    );
    vi.mocked(getJobs).mockResolvedValue({ jobs: [] });
    vi.mocked(postAdvance).mockResolvedValue({ performed: "write_prompt", status });
    renderAt("/topics/t");
    const advance = await screen.findByRole("button", { name: "Advance" });
    await userEvent.click(advance);
    expect(postAdvance).toHaveBeenCalledWith("t");
  });
```

- [x] **Step 2: Run tests to verify they fail**

Run (from `web/`): `npm test`
Expected: FAIL — `PrimaryAction` unresolved

- [x] **Step 3: Implement the components**

Create `web/src/components/ResponseForm.tsx`:

```tsx
import { useState } from "react";
import { postResponse } from "../api/client";
import { useAction } from "../hooks/useAction";

export default function ResponseForm({
  topicId,
  stage,
  onDone,
}: {
  topicId: string;
  stage: string;
  onDone: () => void;
}) {
  const [text, setText] = useState("");
  const { busy, feedback, isError, run } = useAction(onDone);
  return (
    <div className="response-form">
      <label>
        Response for {stage}
        <textarea value={text} onChange={(e) => setText(e.target.value)} rows={10} />
      </label>
      <button
        disabled={busy || !text.trim()}
        onClick={() =>
          run(() => postResponse(topicId, stage, text), {
            retryWithOverwrite: () => postResponse(topicId, stage, text, true),
            successMessage: "Response saved.",
          })
        }
      >
        Save response
      </button>
      {feedback && <p className={isError ? "error" : "success"}>{feedback}</p>}
    </div>
  );
}
```

Create `web/src/components/PrimaryAction.tsx`:

```tsx
import { useState } from "react";
import { Link } from "react-router-dom";
import { enqueueJob, postAdvance, postApprove, postFinalize } from "../api/client";
import type { RunStatus } from "../api/types";
import { useAction } from "../hooks/useAction";
import ExportControls from "./ExportControls";
import ResponseForm from "./ResponseForm";

export default function PrimaryAction({
  status,
  onChanged,
}: {
  status: RunStatus;
  onChanged: () => void;
}) {
  const { busy, feedback, isError, run } = useAction(onChanged);
  const [pasteOpen, setPasteOpen] = useState(false);
  const { topic_id: topicId, next_action: next } = status;
  const stage = next.stage;

  return (
    <div className="primary-action">
      {next.action === "write_prompt" && (
        <button
          disabled={busy}
          onClick={() =>
            run(() => postAdvance(topicId), { successMessage: "Prompt written." })
          }
        >
          Advance
        </button>
      )}
      {next.action === "save_response" && stage && (
        <>
          <button
            disabled={busy}
            onClick={() => run(() => enqueueJob(topicId), { successMessage: "Job enqueued." })}
          >
            Run with provider
          </button>{" "}
          <button disabled={busy} onClick={() => setPasteOpen((open) => !open)}>
            Paste response…
          </button>
          {pasteOpen && (
            <ResponseForm
              topicId={topicId}
              stage={stage}
              onDone={() => {
                setPasteOpen(false);
                onChanged();
              }}
            />
          )}
        </>
      )}
      {next.action === "approve" && stage && (
        <>
          <button
            disabled={busy}
            onClick={() =>
              run(() => postApprove(topicId, stage), {
                retryWithOverwrite: () => postApprove(topicId, stage, true),
                successMessage: `Approved ${stage}.`,
              })
            }
          >
            Approve {stage}
          </button>{" "}
          <Link to={`/topics/${topicId}/stages/${stage}`}>review first</Link>
        </>
      )}
      {next.action === "finalize" && (
        <button
          disabled={busy}
          onClick={() =>
            run(() => postFinalize(topicId), {
              retryWithOverwrite: () => postFinalize(topicId, true),
              successMessage: "Finalized.",
            })
          }
        >
          Finalize
        </button>
      )}
      {next.action === "done" && <ExportControls topicId={topicId} />}
      {feedback && <p className={isError ? "error" : "success"}>{feedback}</p>}
    </div>
  );
}
```

Create a minimal `web/src/components/ExportControls.tsx` stub so this task compiles standalone (Task 11 replaces it with the real implementation — if Task 11 is already merged, skip this file):

```tsx
export default function ExportControls({ topicId }: { topicId: string }) {
  return <p>Run {topicId} is complete.</p>;
}
```

- [x] **Step 4: Wire the run board**

Replace `web/src/pages/RunBoardPage.tsx` with:

```tsx
import { useCallback } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiRequestError, getRunStatus, postAdvance } from "../api/client";
import JobsPanel from "../components/JobsPanel";
import PrimaryAction from "../components/PrimaryAction";
import { useAction } from "../hooks/useAction";
import { usePolling } from "../hooks/usePolling";

export default function RunBoardPage() {
  const { topicId } = useParams<{ topicId: string }>();
  const fetchStatus = useCallback(() => getRunStatus(topicId!), [topicId]);
  const { data: status, error, refresh } = usePolling(fetchStatus, 5_000);
  const start = useAction(refresh);

  if (error instanceof ApiRequestError && error.status === 404) {
    return (
      <div>
        <p>
          No run started for <strong>{topicId}</strong> yet.
        </p>
        <button
          disabled={start.busy}
          onClick={() =>
            start.run(() => postAdvance(topicId!), { successMessage: "Run started." })
          }
        >
          Advance
        </button>
        {start.feedback && (
          <p className={start.isError ? "error" : "success"}>{start.feedback}</p>
        )}
      </div>
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
      <PrimaryAction status={status} onChanged={refresh} />
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

- [x] **Step 5: Run tests + build**

Run (from `web/`): `npm test && npm run build`
Expected: PASS / clean

- [x] **Step 6: Commit**

```bash
git add web/src/components/PrimaryAction.tsx web/src/components/ResponseForm.tsx web/src/components/ExportControls.tsx web/src/components/PrimaryAction.test.tsx web/src/pages/RunBoardPage.tsx web/src/pages/RunBoardPage.test.tsx
git commit -m "feat(web): run-board primary action driven by next_action"
```

---

### Task 11: Export controls and downloads (done state)

**Files:**
- Modify (replace stub): `web/src/components/ExportControls.tsx`
- Test: `web/src/components/ExportControls.test.tsx` (new)

**Interfaces:**
- Consumes: `postExport`, `downloadFinal`, `downloadExport` (Task 8), `useAction` (Task 9), `ExportFormat` type.
- Produces: `ExportControls({ topicId }: { topicId: string })` — format select (html default), Export button (overwrite-confirm retry), and three download buttons: "Download final guide", "Download html export", "Download markdown export". A not-yet-produced export surfaces its 404 envelope message inline ("no html export produced…"), which tells the user to export first — the API has no export-listing endpoint, so buttons are always shown.

- [x] **Step 1: Write the failing tests**

Create `web/src/components/ExportControls.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ExportControls from "./ExportControls";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return {
    ApiRequestError: actual.ApiRequestError,
    postExport: vi.fn(),
    downloadFinal: vi.fn(),
    downloadExport: vi.fn(),
  };
});

import { ApiRequestError, downloadExport, downloadFinal, postExport } from "../api/client";

beforeEach(() => {
  vi.clearAllMocks();
  vi.restoreAllMocks();
});

describe("ExportControls", () => {
  it("exports the selected format", async () => {
    vi.mocked(postExport).mockResolvedValue({
      topic_id: "t",
      format: "markdown",
      export_path: "final/guide.bundle.md",
    });
    render(<ExportControls topicId="t" />);
    await userEvent.selectOptions(screen.getByRole("combobox"), "markdown");
    await userEvent.click(screen.getByRole("button", { name: "Export" }));
    expect(postExport).toHaveBeenCalledWith("t", "markdown");
    expect(await screen.findByText("Exported markdown.")).toBeInTheDocument();
  });

  it("retries export with overwrite after a confirmed 409", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    vi.mocked(postExport)
      .mockRejectedValueOnce(new ApiRequestError(409, "already_exists", "html export already exists"))
      .mockResolvedValueOnce({ topic_id: "t", format: "html", export_path: "final/guide.html" });
    render(<ExportControls topicId="t" />);
    await userEvent.click(screen.getByRole("button", { name: "Export" }));
    expect(postExport).toHaveBeenNthCalledWith(1, "t", "html");
    expect(postExport).toHaveBeenNthCalledWith(2, "t", "html", true);
  });

  it("triggers downloads and surfaces a missing-export 404 inline", async () => {
    vi.mocked(downloadFinal).mockResolvedValue(undefined);
    vi.mocked(downloadExport).mockRejectedValue(
      new ApiRequestError(404, "not_found", "no markdown export produced for topic 't'"),
    );
    render(<ExportControls topicId="t" />);
    await userEvent.click(screen.getByRole("button", { name: "Download final guide" }));
    expect(downloadFinal).toHaveBeenCalledWith("t");
    await userEvent.click(screen.getByRole("button", { name: "Download markdown export" }));
    expect(downloadExport).toHaveBeenCalledWith("t", "markdown");
    expect(
      await screen.findByText(/no markdown export produced/),
    ).toBeInTheDocument();
  });
});
```

- [x] **Step 2: Run tests to verify they fail**

Run (from `web/`): `npm test`
Expected: FAIL — stub renders none of the controls

- [x] **Step 3: Implement**

Replace `web/src/components/ExportControls.tsx` with:

```tsx
import { useState } from "react";
import { downloadExport, downloadFinal, postExport } from "../api/client";
import type { ExportFormat } from "../api/types";
import { useAction } from "../hooks/useAction";

export default function ExportControls({ topicId }: { topicId: string }) {
  const [format, setFormat] = useState<ExportFormat>("html");
  const { busy, feedback, isError, run } = useAction();
  return (
    <div className="export-controls">
      <label>
        Format{" "}
        <select
          value={format}
          onChange={(e) => setFormat(e.target.value as ExportFormat)}
        >
          <option value="html">html</option>
          <option value="markdown">markdown</option>
        </select>
      </label>{" "}
      <button
        disabled={busy}
        onClick={() =>
          run(() => postExport(topicId, format), {
            retryWithOverwrite: () => postExport(topicId, format, true),
            successMessage: `Exported ${format}.`,
          })
        }
      >
        Export
      </button>{" "}
      <button
        disabled={busy}
        onClick={() => run(() => downloadFinal(topicId), { successMessage: "Download started." })}
      >
        Download final guide
      </button>{" "}
      <button
        disabled={busy}
        onClick={() =>
          run(() => downloadExport(topicId, "html"), { successMessage: "Download started." })
        }
      >
        Download html export
      </button>{" "}
      <button
        disabled={busy}
        onClick={() =>
          run(() => downloadExport(topicId, "markdown"), { successMessage: "Download started." })
        }
      >
        Download markdown export
      </button>
      {feedback && <p className={isError ? "error" : "success"}>{feedback}</p>}
    </div>
  );
}
```

- [x] **Step 4: Run tests + build**

Run (from `web/`): `npm test && npm run build`
Expected: PASS / clean

- [x] **Step 5: Commit**

```bash
git add web/src/components/ExportControls.tsx web/src/components/ExportControls.test.tsx
git commit -m "feat(web): export controls with format select and authed downloads"
```

---

### Task 12: Stage viewer contextual actions (+ ARIA tab roles cleanup)

**Files:**
- Modify: `web/src/pages/StageViewerPage.tsx`
- Test: `web/src/pages/StageViewerPage.test.tsx` (extend)

**Interfaces:**
- Consumes: `ResponseForm` (Task 10), `postApprove` (Task 8), `useAction` (Task 9), `usePolling`'s `refresh`.
- Produces: on the stage viewer — "Paste response…" (opens `ResponseForm`) when `response === null`; "Approve {stage}" when `response !== null && approved === null` (the preferred review-then-approve UX). Also applies the Phase 1 deferred a11y finding: tabs get `role="tab"`, `aria-selected`, and the nav gets `role="tablist"`.

- [x] **Step 1: Write the failing tests**

Update `web/src/pages/StageViewerPage.test.tsx`. It currently has one test that renders inline and clicks tabs via `getByRole("button", ...)`. Three coordinated changes:

1. Extend the `vi.mock("../api/client", ...)` factory (line 9) to `return { ApiRequestError: actual.ApiRequestError, getStageContent: vi.fn(), postApprove: vi.fn(), postResponse: vi.fn() };` and change the import on line 12 to `import { getStageContent, postApprove, postResponse } from "../api/client";`.

2. Add a shared render helper after the imports, and rewrite the existing test's inline `render(...)` to use it. Because the tab buttons gain `role="tab"`, the existing test's two tab clicks change from `getByRole("button", { name: /^response/ })` / `getByRole("button", { name: /^approved/ })` to `getByRole("tab", { name: /^response/ })` / `getByRole("tab", { name: /^approved/ })` — same names, new role. Assertions stay identical.

```tsx
function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/topics/:topicId/stages/:stage" element={<StageViewerPage />} />
      </Routes>
    </MemoryRouter>,
  );
}
```

3. Append the new tests:

```tsx
  it("offers Paste response when no response exists", async () => {
    vi.mocked(getStageContent).mockResolvedValue({
      topic_id: "t",
      stage: "draft",
      prompt: "# prompt",
      response: null,
      approved: null,
    });
    vi.mocked(postResponse).mockResolvedValue({} as never);
    renderAt("/topics/t/stages/draft");
    await userEvent.click(await screen.findByRole("button", { name: "Paste response…" }));
    await userEvent.type(screen.getByLabelText("Response for draft"), "pasted body");
    await userEvent.click(screen.getByRole("button", { name: "Save response" }));
    expect(postResponse).toHaveBeenCalledWith("t", "draft", "pasted body");
    expect(screen.queryByRole("button", { name: /Approve/ })).not.toBeInTheDocument();
  });

  it("offers Approve when a response exists and is not approved", async () => {
    vi.mocked(getStageContent).mockResolvedValue({
      topic_id: "t",
      stage: "draft",
      prompt: "# prompt",
      response: "response body",
      approved: null,
    });
    vi.mocked(postApprove).mockResolvedValue({} as never);
    renderAt("/topics/t/stages/draft");
    await userEvent.click(await screen.findByRole("button", { name: "Approve draft" }));
    expect(postApprove).toHaveBeenCalledWith("t", "draft");
    expect(screen.queryByRole("button", { name: "Paste response…" })).not.toBeInTheDocument();
  });

  it("offers neither action once approved", async () => {
    vi.mocked(getStageContent).mockResolvedValue({
      topic_id: "t",
      stage: "draft",
      prompt: "# prompt",
      response: "response body",
      approved: "response body",
    });
    renderAt("/topics/t/stages/draft");
    expect(await screen.findByRole("tab", { name: /prompt/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Approve/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Paste response…" })).not.toBeInTheDocument();
  });
```

- [x] **Step 2: Run tests to verify they fail**

Run (from `web/`): `npm test`
Expected: FAIL — no such buttons / no `tab` role

- [x] **Step 3: Implement**

Replace `web/src/pages/StageViewerPage.tsx` with:

```tsx
import { useCallback, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiRequestError, getStageContent, postApprove } from "../api/client";
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
  const { data, error, refresh } = usePolling(fetchContent, 5_000);
  const [tab, setTab] = useState<Tab>("prompt");
  const [pasteOpen, setPasteOpen] = useState(false);
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
      <pre className="content">{data[tab] ?? `(no ${tab} yet)`}</pre>
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
      {data.response !== null && data.approved === null && (
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

- [x] **Step 4: Run tests + build**

Run (from `web/`): `npm test && npm run build`
Expected: PASS (including the pre-existing StageViewerPage test — the tab buttons still render their text)

- [x] **Step 5: Commit**

```bash
git add web/src/pages/StageViewerPage.tsx web/src/pages/StageViewerPage.test.tsx
git commit -m "feat(web): stage viewer paste/approve actions with ARIA tab roles"
```

---

### Task 13: Jobs panel cancel button

**Files:**
- Modify: `web/src/components/JobsPanel.tsx`
- Test: `web/src/components/JobsPanel.test.tsx` (new; the panel was previously covered only via RunBoardPage tests)

**Interfaces:**
- Consumes: `cancelJob` (Task 8), `useAction` (Task 9). The 2-second `usePolling` tick picks up the resulting status change; no manual refresh plumbing needed.
- Produces: a **cancel** button on queued/running rows.

- [x] **Step 1: Write the failing tests**

Create `web/src/components/JobsPanel.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Job } from "../api/types";
import JobsPanel from "./JobsPanel";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return {
    ApiRequestError: actual.ApiRequestError,
    getJobs: vi.fn(),
    getJobLog: vi.fn(),
    cancelJob: vi.fn(),
  };
});

import { cancelJob, getJobs } from "../api/client";

beforeEach(() => {
  vi.clearAllMocks();
});

function makeJob(id: string, status: Job["status"]): Job {
  return {
    id,
    topic_id: "t",
    stage: "draft",
    provider: "fake",
    model: null,
    effort: null,
    status,
    created_at: "2026-07-10T00:00:00Z",
    started_at: null,
    ended_at: null,
    exit_code: null,
    error: null,
  };
}

describe("JobsPanel cancel", () => {
  it("cancels an active job", async () => {
    vi.mocked(getJobs).mockResolvedValue({ jobs: [makeJob("j1", "running")] });
    vi.mocked(cancelJob).mockResolvedValue(makeJob("j1", "canceled"));
    render(<JobsPanel topicId="t" />);
    await userEvent.click(await screen.findByRole("button", { name: "cancel" }));
    expect(cancelJob).toHaveBeenCalledWith("j1");
  });

  it("offers no cancel for terminal jobs", async () => {
    vi.mocked(getJobs).mockResolvedValue({ jobs: [makeJob("j2", "succeeded")] });
    render(<JobsPanel topicId="t" />);
    expect(await screen.findByText("j2")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "cancel" })).not.toBeInTheDocument();
  });
});
```

- [x] **Step 2: Run tests to verify they fail**

Run (from `web/`): `npm test`
Expected: FAIL — no cancel button

- [x] **Step 3: Implement**

In `web/src/components/JobsPanel.tsx`:

1. Extend imports: `import { cancelJob, getJobs } from "../api/client";` and `import { useAction } from "../hooks/useAction";`
2. Inside the component, after `openJobId` state: `const cancel = useAction();`
3. Replace the actions `<td>` (the one holding the log toggle) with:

```tsx
                  <td>
                    <button
                      onClick={() => setOpenJobId(openJobId === job.id ? null : job.id)}
                    >
                      {openJobId === job.id ? "hide log" : "log"}
                    </button>
                    {ACTIVE_STATUSES.has(job.status) && (
                      <button
                        disabled={cancel.busy}
                        onClick={() =>
                          cancel.run(() => cancelJob(job.id), {
                            successMessage: `Canceling ${job.id}.`,
                          })
                        }
                      >
                        cancel
                      </button>
                    )}
                  </td>
```

4. After the closing `</table>` (inside the section), add:

```tsx
      {cancel.feedback && (
        <p className={cancel.isError ? "error" : "success"}>{cancel.feedback}</p>
      )}
```

- [x] **Step 4: Run tests + build**

Run (from `web/`): `npm test && npm run build`
Expected: PASS / clean

- [x] **Step 5: Commit**

```bash
git add web/src/components/JobsPanel.tsx web/src/components/JobsPanel.test.tsx
git commit -m "feat(web): cancel button for active jobs"
```

---

### Task 14: Topic list imports and profile attach

**Files:**
- Create: `web/src/components/ImportForm.tsx`, `web/src/components/AttachProfileControl.tsx`
- Modify: `web/src/pages/TopicListPage.tsx`
- Test: `web/src/pages/TopicListPage.test.tsx` (extend)

**Interfaces:**
- Consumes: `importTopic`, `importProfile`, `attachProfile`, `getProfiles` (Task 8), `useAction` (Task 9), `usePolling`'s `refresh`.
- Produces:
  - `ImportForm({ kind, onDone }: { kind: "topic" | "profile"; onDone: () => void })` — textarea labelled `{kind} TOML`, "Import" button, overwrite-confirm retry.
  - `AttachProfileControl({ topicId, profiles, onDone })` — select (accessible name `Attach profile to {topicId}`) + "Attach" button; renders nothing when no profiles exist.
  - Topic list toolbar with "Import topic…" / "Import profile…" (visible even when the list is empty) and a per-row Attach column.

- [x] **Step 1: Write the failing tests**

In `web/src/pages/TopicListPage.test.tsx`, extend the `vi.mock("../api/client", ...)` factory with `getProfiles: vi.fn(), importTopic: vi.fn(), importProfile: vi.fn(), attachProfile: vi.fn()`, import them plus `userEvent`, and append:

```tsx
  it("imports a topic from pasted TOML", async () => {
    vi.mocked(getTopics).mockResolvedValue({ topics: [] });
    vi.mocked(getProfiles).mockResolvedValue({ profiles: [] });
    vi.mocked(importTopic).mockResolvedValue({ id: "n1", title: "New One" });
    render(
      <MemoryRouter>
        <TopicListPage />
      </MemoryRouter>,
    );
    await userEvent.click(await screen.findByRole("button", { name: "Import topic…" }));
    await userEvent.type(
      screen.getByLabelText("topic TOML"),
      'id = "n1"',
    );
    await userEvent.click(screen.getByRole("button", { name: "Import" }));
    expect(importTopic).toHaveBeenCalledWith('id = "n1"');
  });

  it("imports a profile from pasted TOML", async () => {
    vi.mocked(getTopics).mockResolvedValue({ topics: [] });
    vi.mocked(getProfiles).mockResolvedValue({ profiles: [] });
    vi.mocked(importProfile).mockResolvedValue({ id: "p1" });
    render(
      <MemoryRouter>
        <TopicListPage />
      </MemoryRouter>,
    );
    await userEvent.click(await screen.findByRole("button", { name: "Import profile…" }));
    await userEvent.type(screen.getByLabelText("profile TOML"), 'id = "p1"');
    await userEvent.click(screen.getByRole("button", { name: "Import" }));
    expect(importProfile).toHaveBeenCalledWith('id = "p1"');
  });

  it("attaches a profile to a topic", async () => {
    vi.mocked(getTopics).mockResolvedValue({
      topics: [{ id: "t", title: "Topic", error: null, run: null }],
    });
    vi.mocked(getProfiles).mockResolvedValue({ profiles: ["p1", "p2"] });
    vi.mocked(attachProfile).mockResolvedValue({
      profile_id: "p1",
      topic_id: "t",
      snapshot_path: "inputs/profile.toml",
    });
    render(
      <MemoryRouter>
        <TopicListPage />
      </MemoryRouter>,
    );
    await userEvent.selectOptions(await screen.findByLabelText("Attach profile to t"), "p1");
    await userEvent.click(screen.getByRole("button", { name: "Attach" }));
    expect(attachProfile).toHaveBeenCalledWith("t", "p1");
  });
```

(Note: `userEvent.type` into a textarea treats `[` and `{` as special keybind characters — that is why the test TOML strings above avoid them. Keep it that way, or use `paste` instead of `type`.)

- [x] **Step 2: Run tests to verify they fail**

Run (from `web/`): `npm test`
Expected: FAIL — no toolbar buttons

- [x] **Step 3: Implement the components**

Create `web/src/components/ImportForm.tsx`:

```tsx
import { useState } from "react";
import { importProfile, importTopic } from "../api/client";
import { useAction } from "../hooks/useAction";

export default function ImportForm({
  kind,
  onDone,
}: {
  kind: "topic" | "profile";
  onDone: () => void;
}) {
  const [toml, setToml] = useState("");
  const { busy, feedback, isError, run } = useAction(onDone);
  const doImport = kind === "topic" ? importTopic : importProfile;
  return (
    <div className="import-form">
      <label>
        {kind} TOML
        <textarea value={toml} onChange={(e) => setToml(e.target.value)} rows={8} />
      </label>
      <button
        disabled={busy || !toml.trim()}
        onClick={() =>
          run(() => doImport(toml), {
            retryWithOverwrite: () => doImport(toml, true),
            successMessage: `Imported ${kind}.`,
          })
        }
      >
        Import
      </button>
      {feedback && <p className={isError ? "error" : "success"}>{feedback}</p>}
    </div>
  );
}
```

Create `web/src/components/AttachProfileControl.tsx`:

```tsx
import { useState } from "react";
import { attachProfile } from "../api/client";
import { useAction } from "../hooks/useAction";

export default function AttachProfileControl({
  topicId,
  profiles,
  onDone,
}: {
  topicId: string;
  profiles: string[];
  onDone: () => void;
}) {
  const [profileId, setProfileId] = useState("");
  const { busy, feedback, isError, run } = useAction(onDone);
  if (profiles.length === 0) return null;
  return (
    <span className="attach-profile">
      <select
        aria-label={`Attach profile to ${topicId}`}
        value={profileId}
        onChange={(e) => setProfileId(e.target.value)}
      >
        <option value="">attach profile…</option>
        {profiles.map((p) => (
          <option key={p} value={p}>
            {p}
          </option>
        ))}
      </select>
      <button
        disabled={busy || !profileId}
        onClick={() =>
          run(() => attachProfile(topicId, profileId), {
            successMessage: `Attached ${profileId}.`,
          })
        }
      >
        Attach
      </button>
      {feedback && <span className={isError ? "error" : "success"}> {feedback}</span>}
    </span>
  );
}
```

- [x] **Step 4: Rework the topic list page**

Replace `web/src/pages/TopicListPage.tsx` with:

```tsx
import { useState } from "react";
import { Link } from "react-router-dom";
import { getProfiles, getTopics } from "../api/client";
import AttachProfileControl from "../components/AttachProfileControl";
import ImportForm from "../components/ImportForm";
import { usePolling } from "../hooks/usePolling";

export default function TopicListPage() {
  const { data, error, refresh } = usePolling(getTopics, 10_000);
  const { data: profileData } = usePolling(getProfiles, 30_000);
  const [importKind, setImportKind] = useState<"topic" | "profile" | null>(null);

  if (error) return <p className="error">Failed to load topics: {error.message}</p>;
  if (!data) return <p>Loading…</p>;

  const profiles = profileData?.profiles ?? [];

  return (
    <div>
      <p className="toolbar">
        <button onClick={() => setImportKind(importKind === "topic" ? null : "topic")}>
          Import topic…
        </button>{" "}
        <button onClick={() => setImportKind(importKind === "profile" ? null : "profile")}>
          Import profile…
        </button>
      </p>
      {importKind && (
        <ImportForm
          kind={importKind}
          onDone={() => {
            setImportKind(null);
            refresh();
          }}
        />
      )}
      {data.topics.length === 0 ? (
        <p>No topics yet. Import one above.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Topic</th>
              <th>Title</th>
              <th>Next action</th>
              <th>Finalized</th>
              <th>Profile</th>
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
                <td>
                  <AttachProfileControl topicId={t.id} profiles={profiles} onDone={refresh} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
```

(The empty-state copy changes from the CLI hint to "Import one above." — update the pre-existing empty-state test's assertion accordingly, and its mock must now also resolve `getProfiles`.)

- [x] **Step 5: Run tests + build**

Run (from `web/`): `npm test && npm run build`
Expected: PASS / clean

- [x] **Step 6: Commit**

```bash
git add web/src/components/ImportForm.tsx web/src/components/AttachProfileControl.tsx web/src/pages/TopicListPage.tsx web/src/pages/TopicListPage.test.tsx
git commit -m "feat(web): topic/profile TOML import and profile attach on the topic list"
```

---

### Task 15: E2E — full browser run (import → stages → finalize → export → download)

**Files:**
- Create: `web/e2e/full-run.spec.ts`

**Interfaces:**
- Consumes: the whole Phase 2 surface, a real daemon, a real `web/dist` build. Pattern copied from `web/e2e/smoke.spec.ts` (daemon spawn + discovery-file wait), but with an **empty** workspace so the UI does all the work.

- [x] **Step 1: Write the test**

Create `web/e2e/full-run.spec.ts`:

```typescript
import { expect, test } from "@playwright/test";
import { spawn, type ChildProcess } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

let daemon: ChildProcess;
let baseURL: string;

test.beforeAll(async () => {
  const ws = mkdtempSync(join(tmpdir(), "ep-e2e-write-"));
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

test("full write flow: import → advance/paste/approve ×5 → finalize → export → download", async ({
  page,
}) => {
  await page.goto(`${baseURL}/`);

  await page.getByRole("button", { name: "Import topic…" }).click();
  await page
    .getByLabel("topic TOML")
    .fill('schema_version = 1\nid = "w"\ntitle = "Write Topic"\n');
  await page.getByRole("button", { name: "Import", exact: true }).click();
  await page.getByRole("link", { name: "w", exact: true }).click();

  for (const stage of ["spec", "outline", "draft", "qa", "repair"]) {
    await page.getByRole("button", { name: "Advance" }).click();
    await page.getByRole("button", { name: "Paste response…" }).click();
    await page.getByLabel(`Response for ${stage}`).fill(`${stage} response body`);
    await page.getByRole("button", { name: "Save response" }).click();
    await page.getByRole("button", { name: `Approve ${stage}` }).click();
  }

  await page.getByRole("button", { name: "Finalize" }).click();
  await page.getByRole("button", { name: "Export", exact: true }).click();
  await expect(page.getByText("Exported html.")).toBeVisible();

  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download final guide" }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe("w-guide.md");
});
```

- [x] **Step 2: Build and run E2E**

Run (from `web/`): `npm run build && npm run e2e`
Expected: 2 passed (smoke + full-run). If the smoke test's assertions changed pages break (they shouldn't — Task 10/12/14 kept the read surface), fix the page, not the smoke test.

- [x] **Step 3: Run everything**

Run: `python3 -m pytest tests/ -q` and (from `web/`) `npm test`
Expected: PASS across the board

- [x] **Step 4: Commit**

```bash
git add web/e2e/full-run.spec.ts
git commit -m "test(web): e2e full browser run from import to download"
```

---

### Task 16: Phase 1 deferred hygiene (from `.superpowers/sdd/progress.md` roll-up)

**Files:**
- Modify: `web/src/main.tsx` (React Router future flags)
- Modify: `education_pipeline/daemon/static.py` (`.woff` content type, line 27 area)
- Modify: `web/src/components/JobLogView.test.tsx` (de-flake)
- Modify: `web/src/hooks/usePolling.test.ts` (visibility-clause coverage)
- Run: `npm audit fix` in `web/`

These are the actionable Minor findings deferred at Phase 1 final review. The remaining roll-up items stay consciously deferred: `smoke.spec.ts stdio: "inherit"` noise (harmless), pure coverage-gap items on Phase 1 code not touched here, and the two dead-logic/brief-mandated shapes in `static.py`/`read_api.py` (the `read_api` guard duplication and the `edu advance` CLI-string finding are already resolved by Tasks 2 and 10).

- [x] **Step 1: Router future flags**

In `web/src/main.tsx`, change line 9 from `<BrowserRouter>` to:

```tsx
    <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
```

Run (from `web/`): `npm run build` → clean. (Page tests using `MemoryRouter` may still print the warnings; that is acceptable — the finding targeted the app shell.)

- [x] **Step 2: `.woff` content type**

In `education_pipeline/daemon/static.py`, in `_CONTENT_TYPES` (line 16), add directly above the `.woff2` entry (line 27):

```python
    ".woff": "font/woff",
```

Run: `python3 -m pytest tests/test_static.py -q` → PASS.

- [x] **Step 3: De-flake the JobLogView accumulation test**

In `web/src/components/JobLogView.test.tsx`, the "accumulates chunks" test races a real 1000ms poll timer against `findByText`'s default 1000ms timeout. Change line 25 from:

```typescript
    expect(await screen.findByText(/hello world/)).toBeInTheDocument();
```

to:

```typescript
    expect(await screen.findByText(/hello world/, undefined, { timeout: 3000 })).toBeInTheDocument();
```

(Test-file-only, behavior-preserving; assertions unchanged.)

- [x] **Step 4: Cover the usePolling visibility clause**

Append to `web/src/hooks/usePolling.test.ts` (add `renderHook`/`waitFor` imports from `@testing-library/react` and `afterEach` from `vitest` if not already imported):

```typescript
describe("usePolling visibility", () => {
  const setVisibility = (state: DocumentVisibilityState) =>
    Object.defineProperty(document, "visibilityState", {
      value: state,
      configurable: true,
    });

  afterEach(() => {
    setVisibility("visible");
  });

  it("skips ticks while hidden and resumes on visibilitychange", async () => {
    const fetcher = vi.fn().mockResolvedValue("x");
    setVisibility("hidden");
    renderHook(() => usePolling(fetcher, 60_000));
    await new Promise((r) => setTimeout(r, 20));
    expect(fetcher).not.toHaveBeenCalled();

    setVisibility("visible");
    document.dispatchEvent(new Event("visibilitychange"));
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
  });
});
```

Run (from `web/`): `npm test` → PASS.

- [x] **Step 5: npm audit fix**

Run (from `web/`): `npm audit fix` then `npm test && npm run build && npm run e2e`.
Expected: tests/build/e2e still green. If `npm audit fix` would require breaking major bumps (`--force`), do **not** force — record the remaining advisories in the commit message and move on (they are build-time dev deps only).

- [x] **Step 6: Commit**

```bash
git add web/src/main.tsx education_pipeline/daemon/static.py web/src/components/JobLogView.test.tsx web/src/hooks/usePolling.test.ts web/package.json web/package-lock.json
git commit -m "chore: phase 1 deferred hygiene (router flags, woff type, test de-flake, audit fix)"
```

---

## Final verification (whole branch)

- [ ] `python3 -m pytest tests/ -q` — all pass
- [ ] `cd web && npm test && npm run build && npm run e2e` — all pass
- [ ] Manual spot-check of the spec's **Done when**: with `edu daemon start`, a full run (import → spec → … → repair → finalize → export → download) completes from the browser without touching the CLI, and a deliberate double-approve shows the overwrite confirm.
