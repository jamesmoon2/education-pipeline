import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from education_pipeline import ContentContract, RunStore, parse_model_catalog, parse_model_plan
from education_pipeline.config import ConfigError
from education_pipeline.daemon.jobs import (
    Job,
    JobRunner,
    JobStore,
    Worker,
    new_job_id,
    popen_kwargs,
    terminate_process,
)
from education_pipeline.providers import Invocation, ProviderResponse, register_runner

FAKE = Path(__file__).parent / "fake_provider.py"


class FakeRunner:
    provider_id = "fake"
    executable = True

    def is_available(self):
        return True

    def build_invocation(self, model, plan, prompt_path):
        return Invocation(argv=[sys.executable, str(FAKE)])

    def parse_response(self, stdout):
        return ProviderResponse(text=stdout, metadata={})


def _factory(tmp_path):
    register_runner(FakeRunner())
    runs = RunStore(tmp_path)
    runs.create_run("t", content_contract=ContentContract.legacy_markdown())
    p = runs.stage_paths("t", "draft").prompt_path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("PROMPT", encoding="utf-8")
    catalog = parse_model_catalog({"providers": [{"id": "fake", "models": [{"id": "m"}]}]})
    plan = parse_model_plan({"provider": "fake", "stages": {"draft": {"model": "m"}}}, catalog)
    store = JobStore(tmp_path)

    def make(job):
        return JobRunner(store, runs, catalog, plan, timeout=30)

    return store, runs, make


def _wait_terminal(store, job_id, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        job = store.find(job_id)
        if job and job.status in {"succeeded", "failed", "canceled", "interrupted"}:
            return job
        time.sleep(0.02)
    raise AssertionError("job did not reach a terminal state")


def test_worker_runs_enqueued_job_to_success(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_STDOUT", "OK\n")
    store, runs, make = _factory(tmp_path)
    worker = Worker(store, make)
    worker.start()
    try:
        job = store.create("t", "draft", "fake", "m", None)
        store.save(job)
        worker.enqueue(job)
        done = _wait_terminal(store, job.id)
        assert done.status == "succeeded"
    finally:
        worker.stop()


def test_worker_refuses_duplicate_active_job(tmp_path):
    store, runs, make = _factory(tmp_path)
    worker = Worker(store, make)
    a = store.create("t", "draft", "fake", "m", None)
    a.status = "queued"
    store.save(a)
    b = store.create("t", "draft", "fake", "m", None)
    with pytest.raises(ConfigError):
        worker.enqueue(b)


def test_reconcile_reenqueues_queued_and_interrupts_running(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_STDOUT", "OK\n")
    store, runs, make = _factory(tmp_path)
    # a leftover running job from a previous life, with a dead pid
    running = store.create("t", "draft", "fake", "m", None)
    running.status = "running"
    running.pid = 999999
    store.save(running)
    # a leftover queued job (different stage to dodge the duplicate guard)
    queued = store.create("t", "spec", "fake", "m", None)
    p = runs.stage_paths("t", "spec").prompt_path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("PROMPT", encoding="utf-8")
    queued.status = "queued"
    store.save(queued)

    worker = Worker(store, make)
    worker.reconcile()
    assert store.find(running.id).status == "interrupted"
    assert not runs.has_ingested_response("t", "draft")
    worker.start()
    try:
        done = _wait_terminal(store, queued.id)
        assert done.status == "succeeded"
    finally:
        worker.stop()


def test_enqueue_duplicate_rejection_leaves_no_orphaned_job_json(tmp_path):
    store, runs, make = _factory(tmp_path)
    worker = Worker(store, make)
    a = store.create("t", "draft", "fake", "m", None)
    worker.enqueue(a)  # succeeds: saves job.json and queues it atomically
    b = store.create("t", "draft", "fake", "m", None)
    with pytest.raises(ConfigError):
        worker.enqueue(b)
    ids = [j.id for j in store.list("t")]
    assert a.id in ids
    # the rejected job must never have gotten a job.json written (no orphan
    # left wedging this topic/stage until a restart)
    assert b.id not in ids


class BrokenExecutableRunner(FakeRunner):
    provider_id = "fake"

    def build_invocation(self, model, plan, prompt_path):
        return Invocation(argv=["/no/such/executable-ep-daemon-test"])


def test_worker_survives_unexpected_exception_in_job_execution(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_STDOUT", "OK\n")
    store, runs, make = _factory(tmp_path)
    register_runner(BrokenExecutableRunner())

    broken_catalog = parse_model_catalog({"providers": [{"id": "fake", "models": [{"id": "m"}]}]})
    broken_plan = parse_model_plan(
        {"provider": "fake", "stages": {"draft": {"model": "m"}}}, broken_catalog
    )
    healthy_catalog = parse_model_catalog({"providers": [{"id": "fake", "models": [{"id": "m"}]}]})
    healthy_plan = parse_model_plan(
        {"provider": "fake", "stages": {"spec": {"model": "m"}}}, healthy_catalog
    )
    p = runs.stage_paths("t", "spec").prompt_path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("PROMPT", encoding="utf-8")

    def make_by_stage(job):
        # draft: build_invocation points at a nonexistent executable, so
        # subprocess.Popen raises FileNotFoundError inside JobRunner.execute.
        if job.stage == "draft":
            return JobRunner(store, runs, broken_catalog, broken_plan, timeout=30)
        return JobRunner(store, runs, healthy_catalog, healthy_plan, timeout=30)

    worker = Worker(store, make_by_stage)
    worker.start()
    try:
        broken_job = store.create("t", "draft", "fake", "m", None)
        worker.enqueue(broken_job)
        done = _wait_terminal(store, broken_job.id)
        assert done.status == "failed"

        # A subsequent job (different stage, healthy runner) processed by the
        # SAME worker thread must still run to completion, proving the loop
        # survived the earlier crash instead of dying.
        register_runner(FakeRunner())
        healthy_job = store.create("t", "spec", "fake", "m", None)
        worker.enqueue(healthy_job)
        done2 = _wait_terminal(store, healthy_job.id)
        assert done2.status == "succeeded"
    finally:
        worker.stop()


def test_worker_survives_raising_runner_factory(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_STDOUT", "OK\n")
    store, runs, make = _factory(tmp_path)
    catalog = parse_model_catalog({"providers": [{"id": "fake", "models": [{"id": "m"}]}]})
    plan = parse_model_plan({"provider": "fake", "stages": {"spec": {"model": "m"}}}, catalog)
    p = runs.stage_paths("t", "spec").prompt_path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("PROMPT", encoding="utf-8")

    def make_by_stage(job):
        # The factory itself raises for the draft job (e.g. bad config building
        # the JobRunner) — this must not kill the worker thread.
        if job.stage == "draft":
            raise RuntimeError("boom building runner")
        return JobRunner(store, runs, catalog, plan, timeout=30)

    worker = Worker(store, make_by_stage)
    worker.start()
    try:
        broken_job = store.create("t", "draft", "fake", "m", None)
        worker.enqueue(broken_job)
        done = _wait_terminal(store, broken_job.id)
        assert done.status == "failed"
        # A later healthy job on the SAME worker still runs, proving survival.
        healthy_job = store.create("t", "spec", "fake", "m", None)
        worker.enqueue(healthy_job)
        assert _wait_terminal(store, healthy_job.id).status == "succeeded"
    finally:
        worker.stop()


def test_cancel_queued_job_marks_canceled(tmp_path):
    store, runs, make = _factory(tmp_path)
    worker = Worker(store, make)  # not started, so the job stays queued
    job = store.create("t", "draft", "fake", "m", None)
    store.save(job)
    worker.enqueue(job)
    result = worker.cancel(job.id)
    assert result.status == "canceled"


# --- T23: bounded parallelism / batch fan-out ------------------------------


def _batch_job(module_id, batch_id, *, stage="draft", topic_id="t"):
    """A module draft job with the T23 fan-out fields set.

    Built via ``Job(...)`` directly (not ``JobStore.create``, whose signature
    the brief leaves unchanged), so this fails with ``TypeError`` on the
    unknown ``unit``/``module_id``/``batch_id`` keywords until ``Job`` gains
    them (item 1) -- ahead of, and independently of, ``Worker`` gaining
    ``parallelism`` (item 3).
    """

    return Job(
        id=new_job_id(),
        topic_id=topic_id,
        stage=stage,
        provider="fake",
        model="m",
        effort=None,
        unit="module",
        module_id=module_id,
        batch_id=batch_id,
    )


class _ConcurrencyTracker:
    """Counts overlapping ``execute`` calls and records each job's [start, end)."""

    def __init__(self):
        self.lock = threading.Lock()
        self.current = 0
        self.peak = 0
        self.spans: dict = {}

    def begin(self, job_id):
        with self.lock:
            self.current += 1
            self.peak = max(self.peak, self.current)
        self.spans[job_id] = [time.monotonic(), None]

    def end(self, job_id):
        with self.lock:
            self.current -= 1
        self.spans[job_id][1] = time.monotonic()


class _ScriptedRunner:
    """A ``JobRunner`` stand-in for Worker fan-out tests.

    Spawns the fake provider directly (a real subprocess, driven by real
    ``FAKE_DELAY``/``FAKE_EXIT`` env vars) so timing and pass/fail behaviour
    are realistic, but never touches ``RunStore`` -- ``Worker``'s pool/
    admission mechanics are independent of stage prompts and ingestion
    (that's ``JobRunner``'s concern, covered in ``test_job_runner.py``).
    Cancellation reuses ``jobs.terminate_process``, the same helper the real
    ``JobRunner`` uses.
    """

    def __init__(self, store, tracker, *, delay=0.0, fail=False):
        self.store = store
        self.tracker = tracker
        self.delay = delay
        self.fail = fail

    def execute(self, job, cancel):
        self.tracker.begin(job.id)
        try:
            job.status = "running"
            self.store.save(job)
            env = dict(os.environ)
            env["FAKE_DELAY"] = str(self.delay)
            env["FAKE_STDOUT"] = "OK\n"
            if self.fail:
                env["FAKE_EXIT"] = "1"
            else:
                env.pop("FAKE_EXIT", None)
            proc = subprocess.Popen(
                [sys.executable, str(FAKE)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=env,
                **popen_kwargs(),
            )
            while proc.poll() is None:
                if cancel.is_set():
                    terminate_process(proc, grace=1.0)
                    job.status = "canceled"
                    self.store.save(job)
                    return job
                time.sleep(0.02)
            job.exit_code = proc.returncode
            job.status = "succeeded" if proc.returncode == 0 else "failed"
            self.store.save(job)
        finally:
            self.tracker.end(job.id)
        return job


def _scripted_factory(store, tracker, configs, *, default_delay=0.0):
    """``runner_factory`` keyed by ``job.id`` (not ``job.module_id``).

    ``Worker._loop`` re-loads each job from disk (``store.find``) before
    handing it to the factory, so any field the round trip doesn't carry
    would be lost -- keying by ``job.id`` (a real field on ``Job`` today)
    keeps these tests independent of whether ``module_id`` survives that
    round trip, which is squarely item 1's concern, not item 3's.
    """

    def factory(job):
        cfg = configs.get(job.id, {})
        return _ScriptedRunner(
            store, tracker, delay=cfg.get("delay", default_delay), fail=cfg.get("fail", False)
        )

    return factory


@pytest.mark.parametrize("bad", [0, 5, -1, 1.5])
def test_worker_rejects_parallelism_outside_one_to_four(tmp_path, bad):
    store = JobStore(tmp_path)
    with pytest.raises(ConfigError):
        Worker(store, lambda job: None, parallelism=bad)


def test_worker_parallelism_defaults_to_two(tmp_path):
    store = JobStore(tmp_path)
    worker = Worker(store, lambda job: None)
    assert worker.parallelism == 2


def test_worker_accepts_explicit_parallelism_within_range(tmp_path):
    store = JobStore(tmp_path)
    worker = Worker(store, lambda job: None, parallelism=3)
    assert worker.parallelism == 3


def test_worker_bounds_concurrent_batch_jobs_to_parallelism_and_overlaps(tmp_path):
    store = JobStore(tmp_path)
    tracker = _ConcurrencyTracker()
    delay = 0.4
    jobs = [_batch_job(f"m{i}", "batch-1") for i in range(4)]
    configs = {job.id: {"delay": delay} for job in jobs}

    worker = Worker(store, _scripted_factory(store, tracker, configs), parallelism=2)
    worker.start()
    try:
        start = time.monotonic()
        for job in jobs:
            worker.enqueue(job)
        for job in jobs:
            _wait_terminal(store, job.id, timeout=15)
        elapsed = time.monotonic() - start
    finally:
        worker.stop()

    assert tracker.peak <= 2
    assert all(store.find(job.id).status == "succeeded" for job in jobs)
    # 4 jobs at parallelism 2 take 2 "rounds": faster than fully serial (4
    # delays -- generous margin below 3) but not faster than fully parallel
    # (1 delay -- generous margin above 2 rounds of 2).
    assert elapsed < 3 * delay
    assert elapsed >= 1.6 * delay


def test_worker_never_runs_a_non_batch_job_concurrently_with_a_batch_job(tmp_path):
    store = JobStore(tmp_path)
    tracker = _ConcurrencyTracker()
    delay = 0.3
    batch_jobs = [_batch_job(f"m{i}", "batch-2") for i in range(2)]
    solo_job = Job(
        id=new_job_id(), topic_id="t", stage="spec", provider="fake", model="m", effort=None
    )
    configs = {job.id: {"delay": delay} for job in (*batch_jobs, solo_job)}

    worker = Worker(store, _scripted_factory(store, tracker, configs), parallelism=2)
    worker.start()
    try:
        # Enqueue the non-batch job *between* two batch jobs of the same batch.
        worker.enqueue(batch_jobs[0])
        worker.enqueue(solo_job)
        worker.enqueue(batch_jobs[1])
        for job in (*batch_jobs, solo_job):
            _wait_terminal(store, job.id, timeout=15)
    finally:
        worker.stop()

    solo_start, solo_end = tracker.spans[solo_job.id]
    batch_spans = [tracker.spans[job.id] for job in batch_jobs]
    assert all(
        solo_start >= batch_end or solo_end <= batch_start
        for batch_start, batch_end in batch_spans
    )
    assert all(store.find(job.id).status == "succeeded" for job in (*batch_jobs, solo_job))


def test_worker_isolates_one_batch_job_failure_from_its_siblings(tmp_path):
    store = JobStore(tmp_path)
    tracker = _ConcurrencyTracker()
    delay = 0.2
    jobs = [_batch_job(f"m{i}", "batch-3") for i in range(3)]
    configs = {job.id: {"delay": delay} for job in jobs}
    configs[jobs[1].id]["fail"] = True

    worker = Worker(store, _scripted_factory(store, tracker, configs), parallelism=2)
    worker.start()
    try:
        for job in jobs:
            worker.enqueue(job)
        for job in jobs:
            _wait_terminal(store, job.id, timeout=15)
    finally:
        worker.stop()

    statuses = {job.id: store.find(job.id).status for job in jobs}
    assert statuses[jobs[1].id] == "failed"
    assert statuses[jobs[0].id] == "succeeded"
    assert statuses[jobs[2].id] == "succeeded"


def test_worker_enqueue_dedup_is_scoped_to_module_id_for_module_jobs(tmp_path):
    store = JobStore(tmp_path)
    tracker = _ConcurrencyTracker()
    worker = Worker(store, _scripted_factory(store, tracker, {}), parallelism=2)
    # not started: jobs stay queued, so the duplicate check is exercised
    # without any timing dependency.

    a = _batch_job("loop-basics", "batch-4")
    worker.enqueue(a)

    dup = _batch_job("loop-basics", "batch-4")
    with pytest.raises(ConfigError):
        worker.enqueue(dup)

    other_module = _batch_job("intervention-practice", "batch-4")
    worker.enqueue(other_module)  # a different module_id at the same stage: fine

    saved_ids = {job.id for job in store.list("t")}
    assert a.id in saved_ids
    assert other_module.id in saved_ids
    assert dup.id not in saved_ids
    worker.stop()


def test_worker_cancel_batch_cancels_queued_and_signals_running(tmp_path):
    store = JobStore(tmp_path)
    tracker = _ConcurrencyTracker()
    delay = 2.0  # long enough that cancel_batch definitely lands mid-flight
    jobs = [_batch_job(f"m{i}", "batch-5") for i in range(4)]
    configs = {job.id: {"delay": delay} for job in jobs}

    worker = Worker(store, _scripted_factory(store, tracker, configs), parallelism=2)
    worker.start()
    try:
        for job in jobs:
            worker.enqueue(job)
        # Wait for the first parallelism-many jobs to actually start running
        # before cancelling, so the "signals running ones" half is exercised.
        deadline = time.monotonic() + 5
        while tracker.current < 2 and time.monotonic() < deadline:
            time.sleep(0.02)
        assert tracker.current >= 1  # sanity: something was actually running

        worker.cancel_batch("batch-5")

        for job in jobs:
            _wait_terminal(store, job.id, timeout=10)
    finally:
        worker.stop()

    statuses = [store.find(job.id).status for job in jobs]
    assert all(status in {"canceled", "interrupted", "failed"} for status in statuses)
    assert "succeeded" not in statuses


# --- T23 mutation pins: where admission is evaluated, and how it waits -----


def test_worker_enqueue_does_not_wait_for_an_inadmissible_job_to_be_admissible(tmp_path):
    """``enqueue`` returns at once even when the job cannot start yet.

    Pins the "never in enqueue" half of the admission rule: enqueue runs
    under the workspace lock (``server.py`` holds it around admission), so
    blocking there would hold the whole workspace -- and the HTTP request --
    for as long as the running job takes. Admission belongs in the
    dispatcher, after dequeue. Without this, moving ``_acquire_slot`` into
    ``enqueue`` passes every other test in this file.
    """

    store = JobStore(tmp_path)
    tracker = _ConcurrencyTracker()
    delay = 1.0
    running = _batch_job("m0", "batch-6")
    # A non-batch job at another stage: inadmissible while the batch job runs.
    solo = Job(
        id=new_job_id(), topic_id="t", stage="spec", provider="fake", model="m", effort=None
    )
    configs = {running.id: {"delay": delay}, solo.id: {"delay": 0.0}}

    worker = Worker(store, _scripted_factory(store, tracker, configs), parallelism=2)
    worker.start()
    try:
        worker.enqueue(running)
        deadline = time.monotonic() + 5
        while tracker.current < 1 and time.monotonic() < deadline:
            time.sleep(0.02)
        assert tracker.current == 1  # sanity: the batch job really is running

        began = time.monotonic()
        worker.enqueue(solo)
        assert time.monotonic() - began < 0.4 * delay

        for job in (running, solo):
            _wait_terminal(store, job.id, timeout=15)
    finally:
        worker.stop()

    assert all(store.find(job.id).status == "succeeded" for job in (running, solo))


def test_worker_thread_holding_an_inadmissible_job_stops_consuming_the_queue(tmp_path):
    """A thread that dequeued an inadmissible job waits; it does not re-queue it.

    Re-queueing to the tail would free that thread to take the *next* job,
    so with ``parallelism=3`` a third batch job would start behind the
    non-batch job's back -- three concurrent jobs where FIFO-plus-wait
    allows only two. (It also spins hot whenever a non-batch job sits
    between two batch jobs, which no assertion can see directly.)
    """

    store = JobStore(tmp_path)
    tracker = _ConcurrencyTracker()
    delay = 0.4
    first = _batch_job("m0", "batch-7")
    solo = Job(
        id=new_job_id(), topic_id="t", stage="spec", provider="fake", model="m", effort=None
    )
    rest = [_batch_job("m1", "batch-7"), _batch_job("m2", "batch-7")]
    order = [first, solo, *rest]
    configs = {job.id: {"delay": delay} for job in order}

    worker = Worker(store, _scripted_factory(store, tracker, configs), parallelism=3)
    worker.start()
    try:
        # `first` must genuinely be running before the rest are enqueued:
        # otherwise `solo` can win the race, run alone, and the three batch
        # jobs legitimately overlap afterwards.
        worker.enqueue(first)
        deadline = time.monotonic() + 5
        while tracker.current < 1 and time.monotonic() < deadline:
            time.sleep(0.02)
        assert tracker.current == 1
        for job in (solo, *rest):
            worker.enqueue(job)
        for job in order:
            _wait_terminal(store, job.id, timeout=20)
    finally:
        worker.stop()

    # One of the three threads is occupied holding `solo`, so at most the
    # other two can run batch jobs at once -- never all three.
    assert tracker.peak == 2
    assert all(store.find(job.id).status == "succeeded" for job in order)


def test_worker_admits_waiting_jobs_in_enqueue_order(tmp_path):
    """Finding 5 (PR #39 review): admission among waiters is FIFO.

    When the pool empties, every parked thread wakes and re-checks the
    admission rule, so a batch job enqueued *after* an ordinary job could win
    the race and start first -- and then keep the pool to itself while its
    siblings joined it. The ordinary job that has been waiting longest must
    go first.
    """

    store = JobStore(tmp_path)
    tracker = _ConcurrencyTracker()
    delay = 0.5
    running = _batch_job("m0", "batch-first")
    solo = Job(
        id=new_job_id(), topic_id="t", stage="spec", provider="fake", model="m", effort=None
    )
    later = [_batch_job("m1", "batch-later"), _batch_job("m2", "batch-later")]
    order = [running, solo, *later]
    configs = {job.id: {"delay": delay} for job in order}

    worker = Worker(store, _scripted_factory(store, tracker, configs), parallelism=4)
    worker.start()
    try:
        worker.enqueue(running)
        deadline = time.monotonic() + 5
        while tracker.current < 1 and time.monotonic() < deadline:
            time.sleep(0.02)
        assert tracker.current == 1  # the first batch really is running

        # `solo` is dequeued (and parked) before the later batch's jobs are.
        worker.enqueue(solo)
        time.sleep(0.1)
        for job in later:
            worker.enqueue(job)
        for job in order:
            _wait_terminal(store, job.id, timeout=30)
    finally:
        worker.stop()

    solo_start = tracker.spans[solo.id][0]
    assert all(solo_start < tracker.spans[job.id][0] for job in later)
    assert all(store.find(job.id).status == "succeeded" for job in order)
