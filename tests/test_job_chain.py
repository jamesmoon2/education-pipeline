"""Failing (red) tests for thread T33 "Daemon carries the chain across jobs".

Design: docs/superpowers/plans/2026-09-18-phase-3-headless.md (T33 row,
decision 9 addendum). Covers the two ``daemon/jobs.py`` additions the daemon's
chain hook needs: ``Job.chain`` / ``Job.continuation`` (durable fields the
worker's completion hook reads and writes) and ``Worker(..., on_finished=)``
(the completion callback the chain hook is wired through).

Neither exists yet, so every test here either fails at construction with
``TypeError`` (an unknown ``Job``/``Worker`` keyword) or fails an assertion
once the round trip or the callback contract is checked. Nothing here
implements the daemon's own completion hook (``DaemonContext.
continue_after_job``) -- that is exercised end-to-end by
``tests/test_server_chain.py`` instead.

Reuses the live ``_factory`` fixture pattern from ``tests/test_worker.py``
(a real ``RunStore`` + a real ``fake_provider.py`` subprocess), per the T33
brief.
"""

from __future__ import annotations

import threading
import time

import pytest

from test_worker import FakeRunner, _factory, _wait_terminal  # noqa: F401 (reused)

from education_pipeline.config import ConfigError
from education_pipeline.daemon.jobs import Job, JobStore, Worker, new_job_id
from education_pipeline.providers import register_runner


# ---------------------------------------------------------------------------
# Job.chain / Job.continuation: fields, round trip, legacy default.
# ---------------------------------------------------------------------------


def _make_job(**overrides) -> Job:
    fields = dict(
        id="20260919T120000Z-aaaa",
        topic_id="t",
        stage="draft",
        provider="fake",
        model="m",
        effort=None,
    )
    fields.update(overrides)
    return Job(**fields)


def test_job_defaults_chain_false_and_continuation_none():
    job = _make_job()
    assert job.chain is False
    assert job.continuation is None


def test_job_chain_and_continuation_round_trip_through_to_dict_from_dict():
    continuation = {
        "after": "job",
        "steps": [{"kind": "advance", "stage": "draft"}],
        "stop": {"kind": "approve", "stage": "draft"},
        "at": "2026-09-19T00:00:00+00:00",
    }
    job = _make_job(chain=True, continuation=continuation)
    data = job.to_dict()
    assert data["chain"] is True
    assert data["continuation"] == continuation

    restored = Job.from_dict(data)
    assert restored.chain is True
    assert restored.continuation == continuation
    assert restored == job


def test_job_round_trips_chain_false_and_no_continuation():
    job = _make_job(chain=False, continuation=None)
    data = job.to_dict()
    assert data["chain"] is False
    assert data["continuation"] is None

    restored = Job.from_dict(data)
    assert restored.chain is False
    assert restored.continuation is None


def test_job_from_dict_legacy_record_pins_chain_exactly_false_not_none():
    """``from_dict`` maps every other missing key to ``None`` (see
    ``test_job_from_dict_legacy_record_defaults_unit_fields_to_none``), but
    ``chain`` is a bool with a real default: a record written before this
    phase must load ``chain is False``, not ``None`` -- ``None`` would be
    truthy-adjacent in a ``if job.chain:`` check written against a bool."""

    legacy = {
        "id": "20260919T120000Z-bbbb",
        "topic_id": "t",
        "stage": "draft",
        "provider": "fake",
        "model": "m",
        "effort": None,
        "status": "succeeded",
    }
    job = Job.from_dict(legacy)
    assert job.chain is False
    assert job.chain is not None
    assert job.continuation is None


def test_jobstore_save_load_roundtrips_chain_and_continuation(tmp_path):
    store = JobStore(tmp_path)
    continuation = {
        "after": "batch",
        "steps": [],
        "stop": {"kind": "failed", "action": "running draft with fake", "message": "boom"},
        "at": "2026-09-19T00:00:00+00:00",
    }
    job = _make_job(id=new_job_id(), chain=True, continuation=continuation)
    store.save(job)
    loaded = store.load("t", job.id)
    assert loaded.chain is True
    assert loaded.continuation == continuation


# ---------------------------------------------------------------------------
# Worker(..., on_finished=): called once per terminal job, outside the lock.
# ---------------------------------------------------------------------------


class _Recorder:
    """Collects ``on_finished`` calls with their thread id, under a lock."""

    def __init__(self):
        self.lock = threading.Lock()
        self.calls: list[Job] = []
        self.thread_ids: list[int] = []

    def __call__(self, job: Job) -> None:
        with self.lock:
            self.calls.append(job)
            self.thread_ids.append(threading.get_ident())

    def wait_for(self, count: int, timeout: float = 10.0) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self.lock:
                if len(self.calls) >= count:
                    return
            time.sleep(0.02)
        raise AssertionError(f"on_finished was not called {count} time(s) in time")


def test_on_finished_called_once_for_a_succeeded_job(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_STDOUT", "OK\n")
    store, runs, make = _factory(tmp_path)
    recorder = _Recorder()
    worker = Worker(store, make, on_finished=recorder)
    worker.start()
    try:
        job = store.create("t", "draft", "fake", "m", None)
        store.save(job)
        worker.enqueue(job)
        done = _wait_terminal(store, job.id)
        assert done.status == "succeeded"
        recorder.wait_for(1)
        assert len(recorder.calls) == 1
        assert recorder.calls[0].id == job.id
        assert recorder.calls[0].status == "succeeded"
    finally:
        worker.stop()


def test_on_finished_sees_the_job_already_saved_terminal(tmp_path, monkeypatch):
    """The callback re-loads the job from the store rather than trusting the
    object handed to it, and finds it already terminal -- the save happens
    before the callback fires, not after."""

    monkeypatch.setenv("FAKE_STDOUT", "OK\n")
    store, runs, make = _factory(tmp_path)
    seen_from_store: list[str] = []

    def on_finished(job: Job) -> None:
        reloaded = store.find(job.id)
        seen_from_store.append(reloaded.status if reloaded else "missing")

    worker = Worker(store, make, on_finished=on_finished)
    worker.start()
    try:
        job = store.create("t", "draft", "fake", "m", None)
        store.save(job)
        worker.enqueue(job)
        _wait_terminal(store, job.id)
        deadline = time.time() + 10
        while not seen_from_store and time.time() < deadline:
            time.sleep(0.02)
        assert seen_from_store == ["succeeded"]
    finally:
        worker.stop()


def test_on_finished_called_once_for_a_failed_job(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_EXIT", "1")
    monkeypatch.setenv("FAKE_STDOUT", "")
    store, runs, make = _factory(tmp_path)
    recorder = _Recorder()
    worker = Worker(store, make, on_finished=recorder)
    worker.start()
    try:
        job = store.create("t", "draft", "fake", "m", None)
        store.save(job)
        worker.enqueue(job)
        done = _wait_terminal(store, job.id)
        assert done.status == "failed"
        recorder.wait_for(1)
        assert len(recorder.calls) == 1
        assert recorder.calls[0].status == "failed"
    finally:
        worker.stop()


def test_on_finished_called_once_for_a_job_canceled_while_queued(tmp_path):
    store, runs, make = _factory(tmp_path)
    recorder = _Recorder()
    worker = Worker(store, make, on_finished=recorder)  # never started: stays queued
    job = store.create("t", "draft", "fake", "m", None)
    store.save(job)
    worker.enqueue(job)
    canceled = worker.cancel(job.id)
    assert canceled.status == "canceled"
    recorder.wait_for(1)
    assert len(recorder.calls) == 1
    assert recorder.calls[0].status == "canceled"


def test_on_finished_runs_outside_the_lock_so_it_can_enqueue(tmp_path, monkeypatch):
    """A callback that calls ``worker.enqueue`` of a *new* job must not
    deadlock against the worker's own admission lock, and that follow-up job
    must then actually run to completion."""

    monkeypatch.setenv("FAKE_STDOUT", "OK\n")
    store, runs, make = _factory(tmp_path)
    p = runs.stage_paths("t", "spec").prompt_path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("PROMPT", encoding="utf-8")

    followup_id: list[str] = []

    def on_finished(job: Job) -> None:
        if job.stage == "draft" and not followup_id:
            followup = store.create("t", "spec", "fake", "m", None)
            worker.enqueue(followup)
            followup_id.append(followup.id)

    worker = Worker(store, make, on_finished=on_finished)
    worker.start()
    try:
        job = store.create("t", "draft", "fake", "m", None)
        store.save(job)
        worker.enqueue(job)
        _wait_terminal(store, job.id)
        deadline = time.time() + 10
        while not followup_id and time.time() < deadline:
            time.sleep(0.02)
        assert followup_id, "on_finished never got to enqueue its follow-up job"
        done = _wait_terminal(store, followup_id[0])
        assert done.status == "succeeded"
    finally:
        worker.stop()


# ---------------------------------------------------------------------------
# Codex round 1, F3: cancellation must claim the terminal transition exactly
# once. ``cancel`` reads the record and decides "queued -> canceled" outside
# the worker lock; the loop thread can meanwhile have already dequeued the
# very same job and be parked in ``_acquire_slot`` waiting for an admission
# slot -- its on-disk status stays "queued" the whole time it waits (a job is
# only marked "running" once ``_acquire_slot`` returns True), so both paths
# can independently decide they are the one making it terminal. Today both
# write the terminal record and both call ``on_finished``.
# ---------------------------------------------------------------------------


def test_cancel_while_the_loop_thread_holds_the_job_parked_in_admission_notifies_once(
    tmp_path, monkeypatch
):
    """Job A (ordinary, no batch) occupies the pool's one ordinary-job slot.
    Job B (ordinary, a different batch-less job) is enqueued once A is
    already running, so the second worker thread dequeues B and parks it in
    ``_acquire_slot`` -- admissible only once nothing is running. B is
    canceled while parked there. ``on_finished`` must fire exactly once for
    B (today it fires twice: once from ``cancel`` itself, once from the
    loop's own "canceled while it waited for a slot" branch), and exactly
    once for A, which must still run to completion undisturbed."""

    monkeypatch.setenv("FAKE_STDOUT", "OK\n")
    monkeypatch.setenv("FAKE_DELAY", "3")
    store, runs, make = _factory(tmp_path)
    recorder = _Recorder()
    worker = Worker(store, make, parallelism=2, on_finished=recorder)
    worker.start()
    try:
        a = store.create("t", "draft", "fake", "m", None)
        store.save(a)
        worker.enqueue(a)

        # Wait for A to actually be admitted (running) so B is the only
        # queued job left for the second thread to dequeue and park.
        deadline = time.time() + 5
        while time.time() < deadline:
            current = store.find(a.id)
            if current and current.status == "running":
                break
            time.sleep(0.02)
        else:
            raise AssertionError("job A never started running")

        b = store.create("t", "qa", "fake", "m", None)
        store.save(b)
        worker.enqueue(b)
        # Give the second thread time to dequeue B and park it in
        # _acquire_slot -- its on-disk status stays "queued" while parked.
        time.sleep(0.3)
        assert store.find(b.id).status == "queued", "test setup: B must still be parked, not running"

        canceled = worker.cancel(b.id)
        assert canceled is not None

        done_b = _wait_terminal(store, b.id)
        assert done_b.status == "canceled"
        done_a = _wait_terminal(store, a.id)
        assert done_a.status == "succeeded"

        recorder.wait_for(2)  # one call for A, one for B
        # Give a buggy second notification for B a chance to land.
        time.sleep(0.3)
        a_calls = [job for job in recorder.calls if job.id == a.id]
        b_calls = [job for job in recorder.calls if job.id == b.id]
        assert len(a_calls) == 1, f"on_finished fired {len(a_calls)} times for job A"
        assert len(b_calls) == 1, f"on_finished fired {len(b_calls)} times for job B"
    finally:
        worker.stop()


def test_on_finished_that_raises_does_not_stop_the_worker(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_STDOUT", "OK\n")
    store, runs, make = _factory(tmp_path)
    p = runs.stage_paths("t", "spec").prompt_path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("PROMPT", encoding="utf-8")

    calls: list[str] = []

    def flaky_on_finished(job: Job) -> None:
        calls.append(job.id)
        raise RuntimeError("callback exploded")

    worker = Worker(store, make, on_finished=flaky_on_finished)
    worker.start()
    try:
        first = store.create("t", "draft", "fake", "m", None)
        store.save(first)
        worker.enqueue(first)
        done_first = _wait_terminal(store, first.id)
        assert done_first.status == "succeeded"  # the raise did not corrupt this job

        second = store.create("t", "spec", "fake", "m", None)
        store.save(second)
        worker.enqueue(second)
        done_second = _wait_terminal(store, second.id)
        assert done_second.status == "succeeded"

        deadline = time.time() + 10
        while len(calls) < 2 and time.time() < deadline:
            time.sleep(0.02)
        assert len(calls) == 2
    finally:
        worker.stop()
