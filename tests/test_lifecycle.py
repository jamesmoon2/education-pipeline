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
