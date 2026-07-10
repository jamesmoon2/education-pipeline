import threading

import pytest

from education_pipeline import RunStore
from education_pipeline.client import DaemonError, ensure_daemon, daemon_status
from education_pipeline.daemon import lifecycle


def test_ensure_daemon_autostarts_and_reports_status(tmp_path):
    RunStore(tmp_path).create_run("t")
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
