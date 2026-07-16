import http.client
import json
import os
import threading
import time
from pathlib import Path

import pytest

from education_pipeline import ContentContract, RunStore
from education_pipeline.config import ConfigError, parse_model_catalog, parse_model_plan
from education_pipeline.daemon import serve
from education_pipeline.daemon import lifecycle
from education_pipeline.daemon import StaticConfigSource, WorkspaceConfigSource
from education_pipeline.daemon.jobs import JobStore, Worker
from education_pipeline.daemon.server import DaemonContext
from education_pipeline.providers import Invocation, ProviderResponse, register_runner
from education_pipeline.workspace import ProfileStore, TopicStore


def _health(port, token):
    conn = http.client.HTTPConnection("127.0.0.1", port)
    conn.request("GET", "/v1/health", headers={"X-EP-Token": token})
    resp = conn.getresponse()
    body = json.loads(resp.read())
    conn.close()
    return resp.status, body


def test_serve_writes_discovery_and_serves_health(tmp_path):
    RunStore(tmp_path).create_run("t", content_contract=ContentContract.legacy_markdown())
    ready = threading.Event()
    thread = threading.Thread(target=serve, args=(tmp_path,), kwargs={"ready": ready}, daemon=True)
    thread.start()
    assert ready.wait(timeout=10)
    record = lifecycle.read_discovery(tmp_path)
    assert record is not None
    status, body = _health(record["port"], record["token"])
    assert status == 200
    # graceful shutdown via the API
    conn = http.client.HTTPConnection("127.0.0.1", record["port"])
    conn.request("POST", "/v1/shutdown", headers={"X-EP-Token": record["token"]})
    conn.getresponse().read()
    conn.close()
    thread.join(timeout=10)
    assert lifecycle.read_discovery(tmp_path) is None


def test_serve_refuses_when_workspace_already_claimed(tmp_path):
    RunStore(tmp_path).create_run("t", content_contract=ContentContract.legacy_markdown())
    lifecycle.write_discovery(tmp_path, pid=os.getpid(), port=1, token="x", version="0.1.0")
    with pytest.raises(ConfigError):
        serve(tmp_path)


def test_workspace_config_source_rereads_after_disk_edit(tmp_path):
    cfg = tmp_path / "config"; cfg.mkdir()
    (cfg / "model-catalog.toml").write_text('[[providers]]\nid = "manual"\nlabel = "Manual"\n')
    (cfg / "model-plan.toml").write_text('provider = "manual"\n')
    source = WorkspaceConfigSource(tmp_path)
    _, plan1 = source.load()
    assert plan1.stage("draft").model is None
    (cfg / "model-plan.toml").write_text('provider = "manual"\n[stages.draft]\nmodel = "x"\n')
    # invalid model must raise (catalog has none), so use a catalog-less-model provider: models list empty → any model name passes
    _, plan2 = source.load()
    assert plan2.stage("draft").model == "x"
    assert source.plan_sha256() != ""


def test_workspace_config_source_write_plan_creates_config_file_atomically(tmp_path):
    # No config/ directory at all yet — reads fall back to the packaged example.
    source = WorkspaceConfigSource(tmp_path)
    catalog, _ = source.load()
    from education_pipeline.config import emit_model_plan_toml, parse_model_plan

    new_plan = parse_model_plan({"provider": "manual", "stages": {}}, catalog=catalog)
    toml_text = emit_model_plan_toml(new_plan)

    source.write_plan(toml_text)

    written_path = tmp_path / "config" / "model-plan.toml"
    assert written_path.is_file()
    assert written_path.read_text(encoding="utf-8") == toml_text
    # No leftover temp files in config/.
    assert [p.name for p in written_path.parent.iterdir()] == ["model-plan.toml"]

    # A subsequent load() reflects the write, and now reads config/, not the
    # packaged example.
    reread_catalog, reread_plan = source.load()
    assert reread_plan.provider == "manual"
    assert source.plan_path() == written_path


def _make_daemon_context(tmp_path, catalog, plan):
    runs = RunStore(tmp_path)
    runs.create_run("t", content_contract=ContentContract.legacy_markdown())
    prompt_path = runs.stage_paths("t", "draft").prompt_path
    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path.write_text("PROMPT", encoding="utf-8")
    store = JobStore(tmp_path)
    worker = Worker(store, lambda job: None)
    return DaemonContext(
        root=tmp_path,
        store=store,
        worker=worker,
        runs=runs,
        token="secret-token",
        version="0.1.0",
        config=StaticConfigSource(catalog, plan),
        topics=TopicStore(tmp_path),
        profiles=ProfileStore(tmp_path),
        on_shutdown=lambda: None,
    )


def test_enqueue_stage_resolves_effective_plan_from_run_overrides(tmp_path):
    catalog = parse_model_catalog(
        {
            "providers": [
                {"id": "default-provider", "models": [{"id": "default-model"}]},
                {"id": "override-provider", "models": [{"id": "override-model"}]},
            ]
        }
    )
    plan = parse_model_plan(
        {
            "provider": "default-provider",
            "stages": {"draft": {"model": "default-model", "effort": "low"}},
        },
        catalog,
    )
    context = _make_daemon_context(tmp_path, catalog, plan)
    context.runs.write_plan_overrides(
        "t",
        {
            "stages": {
                "draft": {
                    "provider": "override-provider",
                    "model": "override-model",
                    "effort": "high",
                }
            }
        },
    )

    job = context.enqueue_stage("t", "draft", False)

    assert job.provider == "override-provider"
    assert job.model == "override-model"
    assert job.effort == "high"
    assert job.metadata["plan_source"] == "override"


def test_enqueue_stage_marks_plan_source_default_when_no_override(tmp_path):
    catalog = parse_model_catalog(
        {"providers": [{"id": "default-provider", "models": [{"id": "default-model"}]}]}
    )
    plan = parse_model_plan(
        {
            "provider": "default-provider",
            "stages": {"draft": {"model": "default-model"}},
        },
        catalog,
    )
    context = _make_daemon_context(tmp_path, catalog, plan)
    # Overrides exist for a different stage only — draft itself is untouched.
    context.runs.write_plan_overrides(
        "t", {"stages": {"qa": {"model": "default-model"}}}
    )

    job = context.enqueue_stage("t", "draft", False)

    assert job.provider == "default-provider"
    assert job.model == "default-model"
    assert job.metadata["plan_source"] == "default"


def test_enqueue_stage_refuses_only_the_stage_with_an_invalid_override(tmp_path):
    # Reproduces the Wave-3 MUST-FIX: a run's stored override for one stage
    # became invalid (e.g. the global catalog dropped the pinned model), but
    # that must not block enqueuing OTHER stages of the same run.
    catalog = parse_model_catalog(
        {"providers": [{"id": "default-provider", "models": [{"id": "default-model"}]}]}
    )
    plan = parse_model_plan(
        {
            "provider": "default-provider",
            "stages": {
                "draft": {"model": "default-model"},
                "qa": {"model": "default-model"},
            },
        },
        catalog,
    )
    context = _make_daemon_context(tmp_path, catalog, plan)
    context.runs.write_plan_overrides(
        "t", {"stages": {"draft": {"model": "does-not-exist"}}}
    )

    with pytest.raises(ConfigError, match="does-not-exist"):
        context.enqueue_stage("t", "draft", False)

    # A different, un-overridden stage of the same run enqueues normally.
    job = context.enqueue_stage("t", "qa", False)
    assert job.stage == "qa"
    assert job.provider == "default-provider"
    assert job.model == "default-model"
    assert job.metadata["plan_source"] == "default"


_FAKE_PROVIDER = Path(__file__).parent / "fake_provider.py"


class _SlowFakeRunner:
    """Provider 'fake': slow, so a queued job behind it leaves an edit window."""

    provider_id = "fake"

    def is_available(self):
        return True

    def build_invocation(self, model, plan, prompt_path):
        import sys

        return Invocation(
            argv=[sys.executable, str(_FAKE_PROVIDER)],
            env={"FAKE_DELAY": "1", "FAKE_STDOUT": "FROM-FAKE\n"},
        )

    def parse_response(self, stdout):
        return ProviderResponse(text=stdout, metadata={})


class _SecondFakeRunner(_SlowFakeRunner):
    provider_id = "fake2"

    def build_invocation(self, model, plan, prompt_path):
        import sys

        return Invocation(
            argv=[sys.executable, str(_FAKE_PROVIDER)],
            env={"FAKE_STDOUT": "FROM-FAKE2\n"},
        )


def _post(port, token, path, body=None):
    conn = http.client.HTTPConnection("127.0.0.1", port)
    conn.request(
        "POST",
        path,
        body=json.dumps(body) if body is not None else None,
        headers={"X-EP-Token": token, "Content-Type": "application/json"},
    )
    resp = conn.getresponse()
    payload = json.loads(resp.read() or b"{}")
    conn.close()
    return resp.status, payload


def _get(port, token, path):
    conn = http.client.HTTPConnection("127.0.0.1", port)
    conn.request("GET", path, headers={"X-EP-Token": token})
    resp = conn.getresponse()
    payload = json.loads(resp.read() or b"{}")
    conn.close()
    return resp.status, payload


def test_worker_reresolves_overrides_edited_while_job_was_queued(tmp_path):
    """Queued-then-edited: overrides written after enqueue still govern execution.

    A slow job holds the single worker; a draft job enqueued behind it freezes
    plan-A values on its record; the run's overrides are then edited to pin
    draft to a different provider. When the worker finally executes the draft
    job it must re-resolve and spawn the override provider, not the frozen one.
    """

    register_runner(_SlowFakeRunner())
    register_runner(_SecondFakeRunner())
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "model-catalog.toml").write_text(
        '[[providers]]\nid = "fake"\n[[providers.models]]\nid = "m"\n'
        '[[providers]]\nid = "fake2"\n[[providers.models]]\nid = "m2"\n',
        encoding="utf-8",
    )
    (cfg / "model-plan.toml").write_text(
        'provider = "fake"\n'
        '[stages.outline]\nmodel = "m"\n'
        '[stages.draft]\nmodel = "m"\n',
        encoding="utf-8",
    )
    runs = RunStore(tmp_path)
    runs.create_run("t", content_contract=ContentContract.legacy_markdown())
    for stage in ("outline", "draft"):
        prompt = runs.stage_paths("t", stage).prompt_path
        prompt.parent.mkdir(parents=True, exist_ok=True)
        prompt.write_text("PROMPT", encoding="utf-8")

    ready = threading.Event()
    thread = threading.Thread(target=serve, args=(tmp_path,), kwargs={"ready": ready}, daemon=True)
    thread.start()
    assert ready.wait(timeout=10)
    record = lifecycle.read_discovery(tmp_path)
    assert record is not None
    port, token = record["port"], record["token"]
    try:
        # A slow outline job occupies the single worker for ~1s.
        status, _ = _post(port, token, "/v1/jobs", {"topic_id": "t", "stage": "outline"})
        assert status == 200
        # The draft job queues behind it, its record frozen with fake/m.
        status, draft_job = _post(port, token, "/v1/jobs", {"topic_id": "t", "stage": "draft"})
        assert status == 200
        assert draft_job["provider"] == "fake"
        # While the draft job sits queued, the run's overrides are edited.
        runs.write_plan_overrides(
            "t", {"stages": {"draft": {"provider": "fake2", "model": "m2"}}}
        )
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            status, job = _get(port, token, f"/v1/jobs/{draft_job['id']}")
            if job["status"] in {"succeeded", "failed", "canceled", "interrupted"}:
                break
            time.sleep(0.05)
        assert job["status"] == "succeeded"
        # Execution used the edited overrides (plan B), not the frozen record.
        assert (
            runs.response_path("t", "draft").read_text(encoding="utf-8") == "FROM-FAKE2\n"
        )
    finally:
        _post(port, token, "/v1/shutdown")
        thread.join(timeout=10)


def test_worker_restamps_plan_source_when_overrides_edited_while_queued(tmp_path):
    """plan_source must reflect the overrides in effect at execution, not enqueue.

    A job enqueued with no override is stamped plan_source=default. If overrides
    are added for its stage while it sits queued, the daemon re-resolves the
    effective plan at execution time (Task 3.2) — plan_source must be re-stamped
    to match, both on the job record and in the recorded stage provenance.
    """

    register_runner(_SlowFakeRunner())
    register_runner(_SecondFakeRunner())
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "model-catalog.toml").write_text(
        '[[providers]]\nid = "fake"\n[[providers.models]]\nid = "m"\n'
        '[[providers]]\nid = "fake2"\n[[providers.models]]\nid = "m2"\n',
        encoding="utf-8",
    )
    (cfg / "model-plan.toml").write_text(
        'provider = "fake"\n'
        '[stages.outline]\nmodel = "m"\n'
        '[stages.draft]\nmodel = "m"\n',
        encoding="utf-8",
    )
    runs = RunStore(tmp_path)
    runs.create_run("t", content_contract=ContentContract.legacy_markdown())
    for stage in ("outline", "draft"):
        prompt = runs.stage_paths("t", stage).prompt_path
        prompt.parent.mkdir(parents=True, exist_ok=True)
        prompt.write_text("PROMPT", encoding="utf-8")

    ready = threading.Event()
    thread = threading.Thread(target=serve, args=(tmp_path,), kwargs={"ready": ready}, daemon=True)
    thread.start()
    assert ready.wait(timeout=10)
    record = lifecycle.read_discovery(tmp_path)
    assert record is not None
    port, token = record["port"], record["token"]
    try:
        # A slow outline job occupies the single worker for ~1s.
        status, _ = _post(port, token, "/v1/jobs", {"topic_id": "t", "stage": "outline"})
        assert status == 200
        # The draft job queues behind it with no override in effect: default.
        status, draft_job = _post(port, token, "/v1/jobs", {"topic_id": "t", "stage": "draft"})
        assert status == 200
        assert draft_job["metadata"]["plan_source"] == "default"
        # While the draft job sits queued, an override is added for its stage.
        runs.write_plan_overrides(
            "t", {"stages": {"draft": {"provider": "fake2", "model": "m2"}}}
        )
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            status, job = _get(port, token, f"/v1/jobs/{draft_job['id']}")
            if job["status"] in {"succeeded", "failed", "canceled", "interrupted"}:
                break
            time.sleep(0.05)
        assert job["status"] == "succeeded"
        # Re-stamped at execution time, not frozen at enqueue.
        assert job["metadata"]["plan_source"] == "override"
        manifest_status, manifest = _get(port, token, f"/v1/runs/t/manifest")
        assert manifest_status == 200
        draft_provenance = [
            e for e in manifest["stage_provenance"] if e["job_id"] == draft_job["id"]
        ]
        assert len(draft_provenance) == 1
        assert draft_provenance[0]["source"] == "override"
    finally:
        _post(port, token, "/v1/shutdown")
        thread.join(timeout=10)
