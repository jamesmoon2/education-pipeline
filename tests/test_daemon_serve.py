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
