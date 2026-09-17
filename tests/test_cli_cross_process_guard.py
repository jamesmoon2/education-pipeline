"""Cross-process guards: CLI mutating commands vs. daemon job/archive state,
and the workspace-level advisory lock they (and future callers) rely on.

Thread T03. See docs/superpowers/ (or the phase-0 brief) for the problem
statement: the CLI builds its own ``RunStore`` and bypasses the daemon's
``_require_no_active_job`` / ``_require_not_archived`` guards
(``education_pipeline/daemon/write_api.py``), so ``education-pipeline
approve`` during a running provider job -- or against an archived course --
is currently unguarded.

These tests pin two things the implementer is expected to add:

1. CLI ``approve`` refuses (non-zero exit, catalog error printed) when the
   daemon's on-disk job store (``education_pipeline.daemon.jobs.JobStore``)
   shows an active job for the topic, or the course is archived. The catalog
   already carries the right codes for this (``job_conflict``,
   ``archived_course`` in ``education_pipeline/errors.py``) -- no new code
   should be needed here.

2. A new module ``education_pipeline.workspace_lock``, exposing a context
   manager ``workspace_lock(workspace_root, *, timeout_seconds=5.0)`` that
   holds a workspace-level advisory lock file under
   ``<workspace_root>/.education-pipeline/`` for the duration of the `with`
   block, using ``fcntl`` on POSIX and ``msvcrt`` on Windows. Contended
   across processes, it blocks up to ``timeout_seconds`` and then raises an
   exception carrying ``.code == "workspace_locked"`` (a new catalog entry
   the implementer adds to ``ERROR_CATALOG``).

Neither behavior exists yet: every test below is expected to fail against
the current tree (either the CLI silently proceeds where it should refuse,
or ``education_pipeline.workspace_lock`` does not exist).
"""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from education_pipeline.cli import main
from education_pipeline.daemon.jobs import JobStore
from education_pipeline.errors import ERROR_CATALOG
from education_pipeline.runs import RunStore


TOPIC_ID = "systems-thinking"

TOPIC_TOML = """\
schema_version = 1
id = "systems-thinking"
title = "Systems Thinking"
brief = "A public introduction to feedback loops."
goals = ["explain feedback loops"]
"""


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def _run(ws: Path, *args: str) -> int:
    return main(["--workspace", str(ws), *args])


def _prepare_topic_ready_to_approve(tmp_path: Path, ws: Path) -> tuple[RunStore, str]:
    """Create a legacy-markdown run and save a response for its first stage,
    leaving it in the "approve" pending state -- the same setup
    ``test_full_flow_drives_run_to_export`` (tests/test_cli.py) drives
    through the CLI end to end with no job/archive interference.
    """

    assert _run(ws, "topic", "import", str(_write(tmp_path / "topic.toml", TOPIC_TOML))) == 0
    assert _run(ws, "create", TOPIC_ID, "--legacy-markdown") == 0
    runs = RunStore(ws)
    assert _run(ws, "advance", TOPIC_ID) == 0
    action = runs.run_status(TOPIC_ID).next_action
    assert action.action == "save_response"
    stage = action.stage
    assert stage is not None
    runs.stage_paths(TOPIC_ID, stage).response_path.write_text(
        f"# {stage}\n", encoding="utf-8"
    )
    return runs, stage


def _record_active_job(ws: Path, stage: str) -> None:
    jobs = JobStore(ws)
    job = jobs.create(TOPIC_ID, stage, "claude_code", None, None)
    job.status = "running"
    jobs.save(job)


# ---------------------------------------------------------------------------
# CLI `approve` vs. an active job recorded on disk
# ---------------------------------------------------------------------------


def test_approve_refuses_when_job_active_on_disk(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ws = tmp_path / "ws"
    runs, stage = _prepare_topic_ready_to_approve(tmp_path, ws)
    capsys.readouterr()

    _record_active_job(ws, stage)

    rc = _run(ws, "approve", TOPIC_ID, stage)
    captured = capsys.readouterr()

    assert rc != 0
    assert "job_conflict" in captured.err
    assert ERROR_CATALOG["job_conflict"].summary in captured.err
    # The guard must actually block the mutation, not just print a warning.
    assert not runs.stage_paths(TOPIC_ID, stage).approved_path.exists()


def test_approve_refuses_when_course_archived(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ws = tmp_path / "ws"
    runs, stage = _prepare_topic_ready_to_approve(tmp_path, ws)
    runs.archive_run(TOPIC_ID)
    capsys.readouterr()

    rc = _run(ws, "approve", TOPIC_ID, stage)
    captured = capsys.readouterr()

    assert rc != 0
    assert "archived_course" in captured.err
    assert ERROR_CATALOG["archived_course"].summary in captured.err
    assert not runs.stage_paths(TOPIC_ID, stage).approved_path.exists()


def test_approve_still_works_with_no_active_job_and_not_archived(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Regression: the common case (also covered end to end by
    ``test_full_flow_drives_run_to_export`` in tests/test_cli.py, which
    drives an entire run through ``approve`` via the CLI with no job or
    archive interference)."""

    ws = tmp_path / "ws"
    runs, stage = _prepare_topic_ready_to_approve(tmp_path, ws)
    capsys.readouterr()

    rc = _run(ws, "approve", TOPIC_ID, stage)

    assert rc == 0
    assert runs.stage_paths(TOPIC_ID, stage).approved_path.exists()


# ---------------------------------------------------------------------------
# `education_pipeline.workspace_lock`
# ---------------------------------------------------------------------------


def _wait_for_file(path: Path, *, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return
        time.sleep(0.02)
    raise AssertionError(f"{path} was not created within {timeout}s")


def _write_hold_lock_script(tmp_path: Path) -> Path:
    script = tmp_path / "_hold_lock.py"
    script.write_text(
        "import sys, time\n"
        "from education_pipeline.workspace_lock import workspace_lock\n"
        "ws, hold_seconds, ready_file = sys.argv[1], float(sys.argv[2]), sys.argv[3]\n"
        "with workspace_lock(ws):\n"
        "    open(ready_file, 'w').close()\n"
        "    time.sleep(hold_seconds)\n",
        encoding="utf-8",
    )
    return script


def test_lock_file_lives_under_dot_education_pipeline_dir(tmp_path: Path) -> None:
    from education_pipeline.workspace_lock import workspace_lock

    ws = tmp_path / "ws"
    ws.mkdir()

    with workspace_lock(ws):
        pass

    ep_dir = ws / ".education-pipeline"
    assert ep_dir.is_dir()
    assert list(ep_dir.glob("*lock*")), f"expected a lock file under {ep_dir}"


def test_gitignore_covers_dot_education_pipeline_directory() -> None:
    gitignore = Path(__file__).resolve().parents[1] / ".gitignore"
    assert ".education-pipeline/" in gitignore.read_text(encoding="utf-8")


def test_workspace_lock_contention_raises_catalog_error_after_timeout(
    tmp_path: Path,
) -> None:
    from education_pipeline.workspace_lock import workspace_lock

    ws = tmp_path / "ws"
    ws.mkdir()
    ready_file = tmp_path / "ready"
    script = _write_hold_lock_script(tmp_path)

    proc = subprocess.Popen(
        [sys.executable, str(script), str(ws), "2.0", str(ready_file)]
    )
    try:
        _wait_for_file(ready_file, timeout=5.0)

        start = time.monotonic()
        with pytest.raises(Exception) as excinfo:
            with workspace_lock(ws, timeout_seconds=0.3):
                pass
        elapsed = time.monotonic() - start

        # Waited roughly the requested timeout: neither failed instantly
        # (that would mean it never actually contended the lock) nor hung
        # past it (that would mean timeout_seconds is not honored).
        assert 0.2 <= elapsed < 1.5
        assert getattr(excinfo.value, "code", None) == "workspace_locked"
        assert ERROR_CATALOG["workspace_locked"].summary in str(excinfo.value)
    finally:
        proc.wait(timeout=5.0)


def test_workspace_lock_blocks_until_released_then_succeeds(tmp_path: Path) -> None:
    from education_pipeline.workspace_lock import workspace_lock

    ws = tmp_path / "ws"
    ws.mkdir()
    ready_file = tmp_path / "ready"
    script = _write_hold_lock_script(tmp_path)

    hold_seconds = 0.5
    proc = subprocess.Popen(
        [sys.executable, str(script), str(ws), str(hold_seconds), str(ready_file)]
    )
    try:
        _wait_for_file(ready_file, timeout=5.0)

        start = time.monotonic()
        with workspace_lock(ws, timeout_seconds=5.0):
            pass
        elapsed = time.monotonic() - start

        # Acquired only after genuinely waiting for the child to release --
        # not merely because the timeout window happened to be long enough
        # to fail slowly.
        assert elapsed >= hold_seconds * 0.6
    finally:
        proc.wait(timeout=5.0)


def test_workspace_lock_uses_msvcrt_on_windows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Windows branch is exercised on Linux CI by faking ``msvcrt`` and
    ``sys.platform``. This requires the implementation to check
    ``sys.platform`` at call time (inside ``workspace_lock``), not at import
    time, and to keep the platform-specific lock module accessible as a
    module-level attribute named ``msvcrt`` on
    ``education_pipeline.workspace_lock`` (``None`` off Windows), so it can
    be monkeypatched here without a module reload.
    """

    import education_pipeline.workspace_lock as workspace_lock_module

    calls: list[tuple[str, int]] = []

    class FakeMsvcrt:
        LK_LOCK = 1
        LK_NBLCK = 2
        LK_UNLCK = 3

        @staticmethod
        def locking(fd: int, mode: int, nbytes: int) -> None:
            calls.append(("locking", mode))

    monkeypatch.setattr(workspace_lock_module, "msvcrt", FakeMsvcrt)
    monkeypatch.setattr(workspace_lock_module.sys, "platform", "win32")

    ws = tmp_path / "ws"
    ws.mkdir()

    with workspace_lock_module.workspace_lock(ws):
        pass

    assert len(calls) >= 2, "expected both a lock and an unlock call to msvcrt.locking"
    modes = [mode for _, mode in calls]
    assert modes[0] in (FakeMsvcrt.LK_LOCK, FakeMsvcrt.LK_NBLCK)
    assert modes[-1] == FakeMsvcrt.LK_UNLCK


def test_workspace_lock_is_reentrant_within_a_process(tmp_path: Path) -> None:
    """Nested critical sections (approve -> write a prompt) must not deadlock.

    A second lock attempt from the same process blocks under ``flock``, so
    the lock counts depth on one shared descriptor instead of opening a new
    one. Leaving the inner block must keep the lock held; only the outer
    block releases it to other processes.
    """

    from education_pipeline.workspace_lock import workspace_lock

    ws = tmp_path / "ws"
    ws.mkdir()
    probe = tmp_path / "_probe_lock.py"
    probe.write_text(
        "import sys\n"
        "from education_pipeline.workspace_lock import workspace_lock\n"
        "with workspace_lock(sys.argv[1], timeout_seconds=0.2):\n"
        "    pass\n",
        encoding="utf-8",
    )

    def probe_succeeds() -> bool:
        return (
            subprocess.run(
                [sys.executable, str(probe), str(ws)],
                capture_output=True,
            ).returncode
            == 0
        )

    with workspace_lock(ws, timeout_seconds=0.3):
        with workspace_lock(ws, timeout_seconds=0.3):
            pass
        # Still held after the inner block exits.
        assert not probe_succeeds()

    # Released by the outer block.
    assert probe_succeeds()


# ---------------------------------------------------------------------------
# Daemon job admission takes the same lock (P3 follow-up)
# ---------------------------------------------------------------------------


def test_job_store_create_refuses_while_another_process_holds_the_lock(
    tmp_path: Path,
) -> None:
    """Job admission is a workspace mutation, so it must contend for the same
    advisory lock the CLI takes around its check-and-mutate. Otherwise a job
    can be admitted in the gap between the CLI's ``_require_mutable`` scan
    and the mutation it guards."""

    from education_pipeline.workspace_lock import WorkspaceLockedError

    ws = tmp_path / "ws"
    ws.mkdir()
    ready_file = tmp_path / "ready"
    script = _write_hold_lock_script(tmp_path)

    proc = subprocess.Popen(
        [sys.executable, str(script), str(ws), "2.0", str(ready_file)]
    )
    try:
        _wait_for_file(ready_file, timeout=5.0)

        store = JobStore(ws, lock_timeout_seconds=0.3)
        start = time.monotonic()
        with pytest.raises(WorkspaceLockedError) as excinfo:
            store.create(TOPIC_ID, "draft", "claude_code", None, None)
        elapsed = time.monotonic() - start

        assert 0.2 <= elapsed < 1.5
        assert excinfo.value.code == "workspace_locked"
    finally:
        proc.wait(timeout=5.0)


def test_job_store_create_waits_for_the_holder_then_succeeds(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    ready_file = tmp_path / "ready"
    script = _write_hold_lock_script(tmp_path)

    hold_seconds = 0.5
    proc = subprocess.Popen(
        [sys.executable, str(script), str(ws), str(hold_seconds), str(ready_file)]
    )
    try:
        _wait_for_file(ready_file, timeout=5.0)

        store = JobStore(ws)
        start = time.monotonic()
        job = store.create(TOPIC_ID, "draft", "claude_code", None, None)
        elapsed = time.monotonic() - start

        assert job.status == "queued"
        assert elapsed >= hold_seconds * 0.6
    finally:
        proc.wait(timeout=5.0)


def test_cli_holds_the_workspace_lock_across_check_and_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The guard is only a guard if nothing can slip in between it and the
    mutation: both must run inside *one* acquisition of the workspace lock,
    so job admission in another process cannot land in the gap."""

    from education_pipeline.workspace_lock import workspace_lock_depth

    ws = tmp_path / "ws"
    runs, stage = _prepare_topic_ready_to_approve(tmp_path, ws)

    depths: list[tuple[str, int]] = []
    original_any_active = JobStore.any_active_for
    original_approve = RunStore.approve_stage

    def spy_any_active(self, topic_id):
        depths.append(("check", workspace_lock_depth(self.root)))
        return original_any_active(self, topic_id)

    def spy_approve(self, topic_id, stage_name, *args, **kwargs):
        depths.append(("mutate", workspace_lock_depth(self.root)))
        return original_approve(self, topic_id, stage_name, *args, **kwargs)

    monkeypatch.setattr(JobStore, "any_active_for", spy_any_active)
    monkeypatch.setattr(RunStore, "approve_stage", spy_approve)

    rc = _run(ws, "approve", TOPIC_ID, stage)

    assert rc == 0
    # Both observations happened while the lock was held, and at the same
    # depth: one acquisition spanning the check and the mutation, not two.
    assert depths == [("check", 1), ("mutate", 1)]


def test_workspace_lock_depth_reports_zero_when_unheld(tmp_path: Path) -> None:
    from education_pipeline.workspace_lock import (
        workspace_lock,
        workspace_lock_depth,
        workspace_lock_held,
    )

    ws = tmp_path / "ws"
    ws.mkdir()

    assert workspace_lock_depth(ws) == 0
    assert not workspace_lock_held(ws)
    with workspace_lock(ws):
        assert workspace_lock_held(ws)
        with workspace_lock(ws):
            assert workspace_lock_depth(ws) == 2
        assert workspace_lock_depth(ws) == 1
    assert workspace_lock_depth(ws) == 0


def test_polling_for_a_contended_lock_does_not_block_other_threads(
    tmp_path: Path,
) -> None:
    """The poll loop's sleeps must not hold the module's ``_STATE_LOCK``.

    One thread waiting out a foreign holder is normal (the daemon waiting on
    a CLI invocation). It must not also freeze every other thread's lock
    bookkeeping in this process for the length of its timeout: a depth query,
    or a lock on an entirely different workspace, has nothing to do with the
    contended file and must answer immediately.
    """

    from education_pipeline.workspace_lock import (
        WorkspaceLockedError,
        workspace_lock,
        workspace_lock_depth,
    )

    ws = tmp_path / "ws"
    ws.mkdir()
    other = tmp_path / "other"
    other.mkdir()
    ready_file = tmp_path / "ready"
    script = _write_hold_lock_script(tmp_path)

    proc = subprocess.Popen(
        [sys.executable, str(script), str(ws), "2.0", str(ready_file)]
    )
    try:
        _wait_for_file(ready_file, timeout=5.0)

        outcomes: list[str] = []

        def poller() -> None:
            try:
                with workspace_lock(ws, timeout_seconds=1.0):
                    outcomes.append("acquired")
            except WorkspaceLockedError:
                outcomes.append("timed out")

        thread = threading.Thread(target=poller, name="ep-test-poller")
        thread.start()
        try:
            time.sleep(0.1)  # let the poller get into its wait loop

            start = time.monotonic()
            depth = workspace_lock_depth(ws)
            with workspace_lock(other, timeout_seconds=1.0):
                pass
            elapsed = time.monotonic() - start

            assert depth == 0, "the contended lock is not held by this process"
            # Well under the poller's 1s timeout: this thread never queued
            # behind the poller's sleeps.
            assert elapsed < 0.25, f"blocked behind the poller for {elapsed:.3f}s"
        finally:
            thread.join(timeout=5.0)

        assert outcomes == ["timed out"]
    finally:
        proc.wait(timeout=5.0)


def test_two_threads_racing_for_the_lock_share_one_hold(tmp_path: Path) -> None:
    """Dropping ``_STATE_LOCK`` between passes lets two threads here poll at
    once. The loser must join the winner's hold by depth -- not keep a second
    descriptor of its own, which would leave the file lock held after the
    winner released it."""

    from education_pipeline.workspace_lock import workspace_lock, workspace_lock_depth

    ws = tmp_path / "ws"
    ws.mkdir()
    probe = tmp_path / "_probe_lock.py"
    probe.write_text(
        "import sys\n"
        "from education_pipeline.workspace_lock import workspace_lock\n"
        "with workspace_lock(sys.argv[1], timeout_seconds=0.2):\n"
        "    pass\n",
        encoding="utf-8",
    )

    barrier = threading.Barrier(2)
    depths: list[int] = []
    failures: list[BaseException] = []

    def contend() -> None:
        try:
            barrier.wait(timeout=5.0)
            with workspace_lock(ws, timeout_seconds=5.0):
                depths.append(workspace_lock_depth(ws))
                time.sleep(0.1)
        except BaseException as exc:  # pragma: no cover - failure reporting
            failures.append(exc)

    threads = [threading.Thread(target=contend) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10.0)

    assert not failures
    # Both got in, and they shared one hold: a depth of 2 is only reachable
    # by joining an existing holder, never by taking a second descriptor.
    assert len(depths) == 2
    assert max(depths) == 2
    assert workspace_lock_depth(ws) == 0
    # ...and the file lock really was released to other processes.
    assert (
        subprocess.run(
            [sys.executable, str(probe), str(ws)], capture_output=True
        ).returncode
        == 0
    )
