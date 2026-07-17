import os
import stat

import pytest

from education_pipeline.daemon import lifecycle


def test_write_read_remove_discovery_roundtrip(tmp_path):
    lifecycle.write_discovery(tmp_path, pid=1234, port=5555, token="tok", version="0.1.0")
    record = lifecycle.read_discovery(tmp_path)
    assert record["pid"] == 1234
    assert record["port"] == 5555
    assert record["token"] == "tok"
    assert record["version"] == "0.1.0"
    assert "started_at" in record
    lifecycle.remove_discovery(tmp_path)
    assert lifecycle.read_discovery(tmp_path) is None


@pytest.mark.skipif(os.name == "nt", reason="POSIX file mode")
def test_discovery_file_is_0600(tmp_path):
    lifecycle.write_discovery(tmp_path, pid=1, port=1, token="t", version="0.1.0")
    mode = stat.S_IMODE(os.stat(lifecycle.discovery_path(tmp_path)).st_mode)
    assert mode == 0o600


def test_read_discovery_absent_is_none(tmp_path):
    assert lifecycle.read_discovery(tmp_path) is None


def test_read_discovery_tolerates_transient_permission_error(tmp_path, monkeypatch):
    # Windows sharing semantics: reading daemon.json at the moment the daemon
    # os.replace()s it can raise PermissionError. A poll loop must see "not
    # ready yet" (None), not crash.
    lifecycle.write_discovery(tmp_path, pid=1, port=1, token="t", version="0.1.0")

    def _sharing_violation(*args, **kwargs):
        raise PermissionError("sharing violation")

    monkeypatch.setattr(lifecycle.Path, "read_text", _sharing_violation)
    assert lifecycle.read_discovery(tmp_path) is None


def test_write_discovery_retries_replace_on_permission_error(tmp_path, monkeypatch):
    # Windows sharing semantics: os.replace onto a file another process holds
    # open for reading fails with PermissionError. A concurrent reader is
    # transient (the client polls every 100ms), so the write must retry
    # instead of crashing the daemon at startup.
    real_replace = os.replace
    calls = {"count": 0}

    def flaky_replace(src, dst):
        calls["count"] += 1
        if calls["count"] == 1:
            raise PermissionError("sharing violation")
        return real_replace(src, dst)

    monkeypatch.setattr(lifecycle.os, "replace", flaky_replace)
    lifecycle.write_discovery(tmp_path, pid=1, port=7777, token="t", version="0.1.0")
    assert calls["count"] == 2
    assert lifecycle.read_discovery(tmp_path)["port"] == 7777


def test_is_pid_alive_for_self_and_dead():
    assert lifecycle.is_pid_alive(os.getpid()) is True
    assert lifecycle.is_pid_alive(999999) is False


def test_claim_discovery_replaces_stale_and_blocks_live(tmp_path):
    # stale: dead pid → claimable
    lifecycle.write_discovery(tmp_path, pid=999999, port=1, token="t", version="0.1.0")
    assert lifecycle.claim_discovery(tmp_path) is True
    # live: our own pid → not claimable by a second caller
    lifecycle.write_discovery(tmp_path, pid=os.getpid(), port=1, token="t", version="0.1.0")
    assert lifecycle.claim_discovery(tmp_path) is False


def test_claim_discovery_empty_placeholder_blocks_second_claim(tmp_path):
    # An in-flight claimant's empty/unparseable placeholder must block a racing caller.
    path = lifecycle.discovery_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()  # empty file → unparseable
    assert lifecycle.claim_discovery(tmp_path) is False


def test_claim_discovery_pid_record_blocks_second_claim(tmp_path):
    # First claimant wins and writes a parseable {"pid": <self>} record.
    assert lifecycle.claim_discovery(tmp_path) is True
    record = lifecycle.read_discovery(tmp_path)
    assert record["pid"] == os.getpid()
    # Second caller sees a live pid → loses.
    assert lifecycle.claim_discovery(tmp_path) is False
