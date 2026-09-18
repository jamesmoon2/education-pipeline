import threading

import pytest

import test_server
import test_draft_units as tdu
from education_pipeline import ContentContract, RunStore
from education_pipeline.client import DaemonClient, DaemonError, ensure_daemon, daemon_status
from education_pipeline.daemon import lifecycle


def test_ensure_daemon_autostarts_and_reports_status(tmp_path):
    RunStore(tmp_path).create_run("t", content_contract=ContentContract.legacy_markdown())
    client = ensure_daemon(tmp_path, autostart=True, timeout=15)
    try:
        health = client.health()
        assert health["ok"] is True
        status = daemon_status(tmp_path)
        assert status["running"] is True
        assert status["port"] == lifecycle.read_discovery(tmp_path)["port"]
    finally:
        client.shutdown()


def test_ensure_daemon_no_autostart_raises_when_absent(tmp_path):
    with pytest.raises(DaemonError):
        ensure_daemon(tmp_path, autostart=False)


def test_ensure_daemon_ignores_claim_placeholder(tmp_path):
    # Simulate the window between a daemon claiming the workspace and it
    # actually binding a port and writing the full discovery record: the
    # placeholder record has only {"pid": <self>}, no "port"/"token". Since
    # this is the current (alive) process, is_stale() would return False.
    assert lifecycle.claim_discovery(tmp_path) is True
    with pytest.raises(DaemonError):
        ensure_daemon(tmp_path, autostart=False)


def test_ensure_daemon_captures_startup_stderr_to_a_log(tmp_path):
    # Pre-claim the workspace from this (live) process so the spawned daemon
    # fails during startup: its claim_discovery() sees a live placeholder and
    # raises. That failure must land in a readable log, not /dev/null, and the
    # timeout error must point at it.
    assert lifecycle.claim_discovery(tmp_path) is True
    with pytest.raises(DaemonError) as excinfo:
        ensure_daemon(tmp_path, autostart=True, timeout=1.5)
    log_path = lifecycle.discovery_dir(tmp_path) / "daemon.log"
    assert str(log_path) in str(excinfo.value)
    assert "a daemon already owns this workspace" in log_path.read_text(
        encoding="utf-8"
    )


def test_daemon_error_carries_catalog_code():
    err = DaemonError("boom", code="job_conflict")
    assert err.code == "job_conflict"
    assert str(err) == "boom"


def test_daemon_error_code_defaults_to_none():
    assert DaemonError("boom").code is None


# ---------------------------------------------------------------------------
# T24: DaemonClient additions for per-module draft fan-out (§6)
#
# None of ``enqueue(..., modules=)``, ``get_batch``, ``cancel_batch``,
# ``ingest_draft_unit`` or ``assemble_draft`` exist on ``DaemonClient`` yet,
# so every test below fails (TypeError on the unknown ``modules`` keyword, or
# AttributeError for the missing methods) until they are added.
# ---------------------------------------------------------------------------


@pytest.fixture
def client_env(tmp_path, monkeypatch):
    srv, worker, context = test_server._start_server(tmp_path, monkeypatch)
    client = DaemonClient(tmp_path, {"port": srv.server_port, "token": context.token})
    try:
        yield client, context, tmp_path
    finally:
        worker.stop()
        srv.shutdown()


def test_daemon_client_enqueue_sends_modules_when_given(client_env):
    client, context, tmp_path = client_env
    tdu._run_with_skeleton_ingested(tmp_path)

    job = client.enqueue(tdu.TID, stage="draft", modules=["loop-basics"])

    assert job["module_id"] == "loop-basics"


def test_daemon_client_get_batch(client_env):
    client, context, tmp_path = client_env
    tdu._run_with_skeleton_ingested(tmp_path)
    job = client.enqueue(tdu.TID, stage="draft")

    batch = client.get_batch(job["batch_id"])

    assert batch["batch_id"] == job["batch_id"]
    assert {j["module_id"] for j in batch["jobs"]} == set(tdu.MODULE_ORDER)


def test_daemon_client_cancel_batch(client_env):
    client, context, tmp_path = client_env
    tdu._run_with_skeleton_ingested(tmp_path)
    job = client.enqueue(tdu.TID, stage="draft")

    result = client.cancel_batch(job["batch_id"])

    assert result["batch_id"] == job["batch_id"]


def test_daemon_client_ingest_draft_unit(client_env):
    client, context, tmp_path = client_env
    tdu._run_with_skeleton_prompt(tmp_path)

    result = client.ingest_draft_unit(tdu.TID, "skeleton", tdu._skeleton_response())

    assert result["unit"] == "skeleton"
    assert result["module_id"] is None


def test_daemon_client_ingest_draft_unit_module_with_force(client_env):
    client, context, tmp_path = client_env
    tdu._run_with_one_module_saved(tmp_path, module_id="loop-basics")

    result = client.ingest_draft_unit(
        tdu.TID,
        "module",
        tdu._module_response("loop-basics"),
        module_id="loop-basics",
        force=True,
    )

    assert result["module_id"] == "loop-basics"


def test_daemon_client_assemble_draft(client_env):
    client, context, tmp_path = client_env
    tdu._run_with_one_module_saved(tmp_path)
    second = "intervention-practice"
    context.runs.draft_unit_paths(
        tdu.TID, "module", module_id=second
    ).response_path.write_text(tdu._module_response(second), encoding="utf-8")

    result = client.assemble_draft(tdu.TID)

    assert result["ok"] is True
