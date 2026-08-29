import json
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


def test_jobstore_save_retries_replace_on_permission_error(tmp_path, monkeypatch):
    # Windows sharing semantics: os.replace onto job.json while an API reader
    # holds it open fails with PermissionError. Readers are transient, so the
    # save must retry instead of crashing the worker.
    import os

    store = JobStore(tmp_path)
    job = store.create("t", "draft", "codex", "balanced", None)

    real_replace = os.replace
    calls = {"count": 0}

    def flaky_replace(src, dst):
        calls["count"] += 1
        if calls["count"] == 1:
            raise PermissionError("sharing violation")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", flaky_replace)
    store.save(job)
    assert calls["count"] == 2
    assert store.load("t", job.id).id == job.id


def test_jobstore_load_retries_read_on_permission_error(tmp_path, monkeypatch):
    # Windows sharing semantics: reading job.json at the moment the worker
    # os.replace()s it fails with PermissionError. The replace is transient,
    # so the read must retry instead of surfacing a daemon 500.
    from pathlib import Path

    store = JobStore(tmp_path)
    job = store.create("t", "draft", "codex", "balanced", None)
    store.save(job)

    real_read_text = Path.read_text
    calls = {"count": 0}

    def flaky_read_text(self, *args, **kwargs):
        if self.name == "job.json":
            calls["count"] += 1
            if calls["count"] == 1:
                raise PermissionError("sharing violation")
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", flaky_read_text)
    assert store.load("t", job.id).id == job.id
    assert calls["count"] == 2


def test_jobstore_find_retries_read_on_permission_error(tmp_path, monkeypatch):
    # find() scans every job.json via all_jobs(); a scan that races a worker's
    # os.replace must retry the affected record, not crash the request.
    from pathlib import Path

    store = JobStore(tmp_path)
    job = store.create("t", "draft", "codex", "balanced", None)
    store.save(job)

    real_read_text = Path.read_text
    calls = {"count": 0}

    def flaky_read_text(self, *args, **kwargs):
        if self.name == "job.json":
            calls["count"] += 1
            if calls["count"] == 1:
                raise PermissionError("sharing violation")
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", flaky_read_text)
    assert store.find(job.id).id == job.id
    assert calls["count"] == 2


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


def _dead_or_zombie(pid) -> bool:
    """True once ``pid`` no longer exists or is a terminated, unreaped zombie.

    A grandchild orphaned by killing its parent reparents to PID 1; on
    runners whose PID 1 does not reap promptly it lingers as a zombie, and
    ``os.kill(pid, 0)`` (lifecycle.is_pid_alive) still "sees" it. For these
    tests terminated-but-unreaped counts as dead.
    """

    from education_pipeline.daemon import lifecycle

    if not lifecycle.is_pid_alive(pid):
        return True
    if sys.platform == "win32":
        return False  # no zombie state on Windows
    state = subprocess.run(
        ["ps", "-o", "stat=", "-p", str(pid)],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    return state == "" or state.startswith("Z")


def _wait_until_dead(pid, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _dead_or_zombie(pid):
            return True
        time.sleep(0.1)
    return _dead_or_zombie(pid)


@pytest.mark.skipif(sys.platform == "win32", reason="no zombie state on Windows")
def test_wait_until_dead_treats_unreaped_zombie_as_dead():
    proc = subprocess.Popen([sys.executable, "-c", "raise SystemExit(0)"])
    # Deliberately no wait()/poll() before the assertion: once the child
    # exits it sits unreaped as a zombie, exactly like an orphaned grandchild
    # under a non-reaping PID 1.
    try:
        assert _wait_until_dead(proc.pid, timeout=5)
    finally:
        proc.wait()


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


# --- scoped lookups: id -> path is deterministic, so no workspace-wide scan ---


def _seed_workspace(store, topics=("alpha", "beta", "gamma"), per_topic=4):
    """Save ``per_topic`` jobs per topic with a mix of stages and statuses."""

    stages = ("spec", "outline", "draft", "qa")
    statuses = ("succeeded", "failed", "queued", "running")
    saved = []
    for topic_index, topic_id in enumerate(topics):
        for index in range(per_topic):
            job = store.create(
                topic_id, stages[index % len(stages)], "fake", None, None
            )
            job.status = statuses[(topic_index + index) % len(statuses)]
            store.save(job)
            saved.append(job)
    return saved


def _scan_equivalents(store, topic_id=None):
    """The all_jobs()-derived answer the scoped accessors must reproduce."""

    jobs = [j for j in store.all_jobs() if topic_id is None or j.topic_id == topic_id]
    return sorted(jobs, key=lambda j: j.id, reverse=True)


def test_scoped_lookups_match_a_full_workspace_scan(tmp_path):
    # find/list/active_for/any_active_for read job.json by its deterministic
    # path instead of scanning the whole runs tree; the answers must stay
    # byte-for-byte what the old all_jobs() scan produced.
    store = JobStore(tmp_path)
    saved = _seed_workspace(store)

    for job in saved:
        found = store.find(job.id)
        assert found is not None
        expected = next(j for j in store.all_jobs() if j.id == job.id)
        assert found.to_dict() == expected.to_dict()

    assert store.find("nope") is None

    for topic_id in ("alpha", "beta", "gamma"):
        listed = [j.to_dict() for j in store.list(topic_id)]
        assert listed == [j.to_dict() for j in _scan_equivalents(store, topic_id)]
        for stage in ("spec", "outline", "draft", "qa"):
            active = store.active_for(topic_id, stage)
            expected = next(
                (
                    j
                    for j in _scan_equivalents(store, topic_id)
                    if j.stage == stage and j.status not in TERMINAL_STATUSES
                ),
                None,
            )
            assert (active.to_dict() if active else None) == (
                expected.to_dict() if expected else None
            )
        any_active = store.any_active_for(topic_id)
        expected_any = next(
            (
                j
                for j in _scan_equivalents(store, topic_id)
                if j.status not in TERMINAL_STATUSES
            ),
            None,
        )
        assert (any_active.to_dict() if any_active else None) == (
            expected_any.to_dict() if expected_any else None
        )

    # A topic with no jobs at all, and the workspace-wide listing, are unchanged.
    assert store.list("unknown-topic") == []
    assert store.any_active_for("unknown-topic") is None
    assert [j.to_dict() for j in store.list()] == [
        j.to_dict() for j in _scan_equivalents(store)
    ]


def test_scoped_lookups_read_only_the_records_they_need(tmp_path, monkeypatch):
    # The point of the scoping: find() and list(topic) sit on the daemon's 1s
    # log poll and the CLI's 0.25s job poll, under Worker.enqueue's lock.
    # Neither may parse every job.json in the workspace.
    from education_pipeline.daemon import jobs as jobs_module

    store = JobStore(tmp_path)
    saved = _seed_workspace(store, per_topic=5)
    target = saved[7]

    reads = []
    real_read = jobs_module._read_job_record

    def counting_read(path):
        reads.append(path)
        return real_read(path)

    monkeypatch.setattr(jobs_module, "_read_job_record", counting_read)

    reads.clear()
    assert store.find(target.id).id == target.id
    assert len(reads) == 1

    reads.clear()
    assert store.find("20260101T000000Z-dead") is None
    assert reads == []

    reads.clear()
    listed = store.list(target.topic_id)
    assert len(listed) == 5
    assert len(reads) == 5
    assert all(target.topic_id in path.parts for path in reads)

    reads.clear()
    store.active_for(target.topic_id, "draft")
    assert all(target.topic_id in path.parts for path in reads)

    # all_jobs() stays the genuinely workspace-wide listing.
    reads.clear()
    store.all_jobs()
    assert len(reads) == 15


def test_scoped_lookups_tolerate_missing_directories(tmp_path):
    store = JobStore(tmp_path)
    # No runs/ tree at all.
    assert store.find("20260101T000000Z-aaaa") is None
    assert store.list("t") == []
    assert store.active_for("t", "draft") is None
    assert store.any_active_for("t") is None

    # runs/ exists, but the topic has no jobs/ directory.
    (tmp_path / "runs" / "t").mkdir(parents=True)
    assert store.find("20260101T000000Z-aaaa") is None
    assert store.list("t") == []

    # A job directory that exists but was never saved (create() mkdirs it
    # before Worker.enqueue writes job.json) must stay invisible.
    unsaved = store.create("t", "draft", "fake", None, None)
    assert store.job_dir("t", unsaved.id).is_dir()
    assert store.find(unsaved.id) is None
    assert store.list("t") == []

    # A stray file inside jobs/ is not a job directory.
    (store.runs_dir / "t" / "jobs" / "README.txt").write_text("x", encoding="utf-8")
    assert store.list("t") == []

    saved = store.create("t", "draft", "fake", None, None)
    store.save(saved)
    assert store.find(saved.id).id == saved.id
    assert [j.id for j in store.list("t")] == [saved.id]


def test_scoped_find_skips_a_corrupt_record_in_another_topic(tmp_path):
    # _read_job_record does not swallow malformed JSON: reading a corrupt
    # record still raises. Scoping means an unrelated topic's corrupt record
    # no longer breaks a lookup that never needed to read it.
    store = JobStore(tmp_path)
    good = store.create("alpha", "draft", "fake", None, None)
    store.save(good)
    bad = store.create("beta", "draft", "fake", None, None)
    (store.job_dir("beta", bad.id) / "job.json").write_text("{ not json", encoding="utf-8")

    assert store.find(good.id).id == good.id
    assert [j.id for j in store.list("alpha")] == [good.id]

    # The targeted record's own corruption still surfaces, unchanged.
    with pytest.raises(json.JSONDecodeError):
        store.find(bad.id)
    with pytest.raises(json.JSONDecodeError):
        store.list("beta")
    with pytest.raises(json.JSONDecodeError):
        store.all_jobs()


def test_scoped_lookups_refuse_path_escaping_ids(tmp_path):
    # find()/list() build paths from ids that arrive straight off the HTTP
    # route (`/v1/jobs/<id>`, `/v1/jobs?topic=<id>`). A separator or ".."
    # must never be joined into the runs tree.
    store = JobStore(tmp_path)
    job = store.create("alpha", "draft", "fake", None, None)
    store.save(job)
    (tmp_path / "runs" / "alpha" / "job.json").write_text("{}", encoding="utf-8")

    for hostile in ("..", ".", "", "../..", "alpha/jobs", "/etc/passwd", "a/../b"):
        assert store.find(hostile) is None
        assert store.list(hostile) == []
        assert store.active_for(hostile, "draft") is None
        assert store.any_active_for(hostile) is None
