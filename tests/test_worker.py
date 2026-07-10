import sys
import threading
import time
from pathlib import Path

import pytest

from education_pipeline import RunStore, parse_model_catalog, parse_model_plan
from education_pipeline.config import ConfigError
from education_pipeline.daemon.jobs import Job, JobRunner, JobStore, Worker
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
    runs.create_run("t")
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
