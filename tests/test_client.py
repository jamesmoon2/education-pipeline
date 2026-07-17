import threading

import pytest

from education_pipeline import ContentContract, RunStore
from education_pipeline.client import DaemonError, ensure_daemon, daemon_status
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
        ensure_daemon(tmp_path, autostart=True, timeout=3)
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
