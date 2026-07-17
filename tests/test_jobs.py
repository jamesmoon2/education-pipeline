import subprocess
import sys
import time
from datetime import datetime, timezone

import pytest

from education_pipeline.daemon.jobs import (
    TERMINAL_STATUSES,
    Job,
    JobStore,
    new_job_id,
    popen_kwargs,
    terminate_process,
)


def test_new_job_id_is_sortable_and_suffixed():
    a = new_job_id(datetime(2026, 7, 9, 18, 30, 42, tzinfo=timezone.utc))
    assert a.startswith("20260709T183042Z-")
    assert len(a.split("-")[-1]) == 4
    # different calls differ in the random suffix
    b = new_job_id(datetime(2026, 7, 9, 18, 30, 42, tzinfo=timezone.utc))
    assert a != b


def test_jobstore_create_save_load_roundtrip(tmp_path):
    store = JobStore(tmp_path)
    job = store.create("systems-thinking", "draft", "claude-code", "premium", "high")
    assert job.status == "queued"
    assert job.topic_id == "systems-thinking"
    store.save(job)
    loaded = store.load("systems-thinking", job.id)
    assert loaded.id == job.id
    assert loaded.stage == "draft"
    assert loaded.provider == "claude-code"
    assert loaded.effort == "high"


def test_jobstore_find_and_list_newest_first(tmp_path):
    store = JobStore(tmp_path)
    j1 = store.create("t", "spec", "codex", "balanced", None)
    store.save(j1)
    j2 = store.create("t", "draft", "codex", "balanced", None)
    store.save(j2)
    assert store.find(j2.id).id == j2.id
    ids = [j.id for j in store.list("t")]
    assert ids == sorted(ids, reverse=True)
    assert store.find("nope") is None


def test_active_for_finds_only_non_terminal(tmp_path):
    store = JobStore(tmp_path)
    job = store.create("t", "draft", "codex", "balanced", None)
    store.save(job)
    assert store.active_for("t", "draft").id == job.id
    job.status = "succeeded"
    store.save(job)
    assert store.active_for("t", "draft") is None
    assert "succeeded" in TERMINAL_STATUSES


def test_read_log_returns_bytes_from_offset(tmp_path):
    store = JobStore(tmp_path)
    job = store.create("t", "draft", "codex", "balanced", None)
    store.log_path(job.topic_id, job.id).write_bytes(b"hello world")
    data, offset = store.read_log(job, 6)
    assert data == b"world"
    assert offset == 11


def test_terminate_process_kills_a_running_child():
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"], **popen_kwargs()
    )
    assert proc.poll() is None
    terminate_process(proc, grace=2.0)
    # after termination the process must be reaped with a non-None returncode
    assert proc.poll() is not None


def _spawn_provider_tree(tmp_path):
    """A provider stand-in that spawns its own helper child (the grandchild).

    Returns the provider Popen and the grandchild pid once the grandchild is
    confirmed running.
    """

    pid_file = tmp_path / "grandchild.pid"
    parent_src = (
        "import pathlib, subprocess, sys, time\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        f"pathlib.Path({str(pid_file)!r}).write_text(str(child.pid), encoding='utf-8')\n"
        "time.sleep(60)\n"
    )
    proc = subprocess.Popen([sys.executable, "-c", parent_src], **popen_kwargs())
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        text = pid_file.read_text(encoding="utf-8") if pid_file.is_file() else ""
        if text.strip():
            return proc, int(text)
        time.sleep(0.05)
    terminate_process(proc, grace=2.0)
    raise AssertionError("provider grandchild never started")


def _wait_until_dead(pid, timeout=10.0):
    from education_pipeline.daemon import lifecycle

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not lifecycle.is_pid_alive(pid):
            return True
        time.sleep(0.1)
    return not lifecycle.is_pid_alive(pid)


def test_terminate_process_kills_the_whole_child_tree(tmp_path):
    # A provider that spawns helpers must not leak them on cancel. POSIX gets
    # this from killpg over the start_new_session group; Windows needs an
    # explicit tree kill (Popen.terminate only signals the root).
    from education_pipeline.daemon import lifecycle

    proc, grandchild_pid = _spawn_provider_tree(tmp_path)
    assert lifecycle.is_pid_alive(grandchild_pid)
    terminate_process(proc, grace=2.0)
    assert proc.poll() is not None
    assert _wait_until_dead(grandchild_pid), "grandchild survived cancellation"


def test_best_effort_kill_kills_the_whole_tree_by_pid(tmp_path):
    # The reconcile path kills by bare pid (no Popen handle); it must tear
    # down the same process tree.
    from education_pipeline.daemon.jobs import _best_effort_kill

    proc, grandchild_pid = _spawn_provider_tree(tmp_path)
    _best_effort_kill(proc.pid)
    proc.wait(timeout=10)
    assert _wait_until_dead(grandchild_pid), "grandchild survived reconcile kill"


def test_popen_kwargs_has_platform_group_flag():
    kwargs = popen_kwargs()
    if sys.platform == "win32":
        assert "creationflags" in kwargs
    else:
        assert kwargs.get("start_new_session") is True


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
