import sys
import threading
from pathlib import Path

import pytest

from education_pipeline import RunStore, parse_model_catalog, parse_model_plan
from education_pipeline.daemon.jobs import JobRunner, JobStore
from education_pipeline.providers import (
    Invocation,
    ProviderResponse,
    register_runner,
)

FAKE = Path(__file__).parent / "fake_provider.py"


class FakeRunner:
    provider_id = "fake"
    executable = True

    def is_available(self) -> bool:
        return True

    def build_invocation(self, model, plan, prompt_path):
        return Invocation(argv=[sys.executable, str(FAKE)])

    def parse_response(self, stdout):
        return ProviderResponse(text=stdout, metadata={"echo": True})


class UnavailableRunner(FakeRunner):
    provider_id = "gone"

    def is_available(self) -> bool:
        return False


def _setup(tmp_path, provider="fake"):
    register_runner(FakeRunner())
    register_runner(UnavailableRunner())
    runs = RunStore(tmp_path)
    runs.create_run("t")
    # a prompt must exist for the stage the job runs
    runs.stage_paths("t", "draft").prompt_path.parent.mkdir(parents=True, exist_ok=True)
    runs.stage_paths("t", "draft").prompt_path.write_text("PROMPT", encoding="utf-8")
    catalog = parse_model_catalog(
        {"providers": [{"id": provider, "models": [{"id": "m", "argv_model": "x"}]}]}
    )
    plan = parse_model_plan({"provider": provider, "stages": {"draft": {"model": "m"}}}, catalog)
    store = JobStore(tmp_path)
    return runs, catalog, plan, store


def test_execute_success_ingests_response(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_STDOUT", "GENERATED\n")
    runs, catalog, plan, store = _setup(tmp_path)
    job = store.create("t", "draft", "fake", "m", None)
    runner = JobRunner(store, runs, catalog, plan, timeout=30)
    done = runner.execute(job, threading.Event())
    assert done.status == "succeeded"
    assert done.exit_code == 0
    assert runs.response_path("t", "draft").read_text(encoding="utf-8") == "GENERATED\n"
    # manifest carries a job event
    actions = [e["action"] for e in runs.read_manifest("t")["events"]]
    assert "job" in actions


def test_execute_nonzero_exit_fails_without_response(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_EXIT", "3")
    runs, catalog, plan, store = _setup(tmp_path)
    job = store.create("t", "draft", "fake", "m", None)
    done = JobRunner(store, runs, catalog, plan, timeout=30).execute(job, threading.Event())
    assert done.status == "failed"
    assert done.exit_code == 3
    assert not runs.has_ingested_response("t", "draft")


def test_execute_empty_output_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_STDOUT", "   \n")
    runs, catalog, plan, store = _setup(tmp_path)
    job = store.create("t", "draft", "fake", "m", None)
    done = JobRunner(store, runs, catalog, plan, timeout=30).execute(job, threading.Event())
    assert done.status == "failed"
    assert not runs.has_ingested_response("t", "draft")


def test_execute_timeout_marks_failed(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_DELAY", "10")
    runs, catalog, plan, store = _setup(tmp_path)
    job = store.create("t", "draft", "fake", "m", None)
    done = JobRunner(store, runs, catalog, plan, timeout=0.5).execute(job, threading.Event())
    assert done.status == "failed"
    assert done.error == "timeout"


def test_execute_provider_unavailable_fails_before_spawn(tmp_path):
    runs, catalog, plan, store = _setup(tmp_path, provider="gone")
    job = store.create("t", "draft", "gone", "m", None)
    done = JobRunner(store, runs, catalog, plan, timeout=30).execute(job, threading.Event())
    assert done.status == "failed"
    assert "gone" in (done.error or "")


def test_execute_log_truncation_keeps_head_and_tail(tmp_path, monkeypatch):
    import education_pipeline.daemon.jobs as jobs_mod

    monkeypatch.setattr(jobs_mod, "MAX_LOG_BYTES", 200)
    # stdout stays small and clean (so the response parses fine); the noisy
    # stream is stderr, which pushes the *combined* log over the cap.
    monkeypatch.setenv("FAKE_STDOUT", "GENERATED\n")
    head_marker = "HEAD_START_" + "A" * 300
    tail_marker = "Z" * 300 + "_TAIL_END"
    monkeypatch.setenv("FAKE_STDERR", head_marker + tail_marker)
    runs, catalog, plan, store = _setup(tmp_path)
    job = store.create("t", "draft", "fake", "m", None)
    done = JobRunner(store, runs, catalog, plan, timeout=30).execute(job, threading.Event())
    assert done.status == "succeeded"
    assert runs.response_path("t", "draft").read_text(encoding="utf-8") == "GENERATED\n"
    log_text = store.log_path("t", job.id).read_text(encoding="utf-8")
    assert "output truncated" in log_text  # marker present
    # bounded footprint: cap + a small allowance for the marker line
    assert len(log_text.encode("utf-8")) <= 200 + 128


def test_execute_parses_stdout_only_not_stderr(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_STDOUT", "REAL RESPONSE\n")
    monkeypatch.setenv("FAKE_STDERR", "noisy progress line\n")
    runs, catalog, plan, store = _setup(tmp_path)
    job = store.create("t", "draft", "fake", "m", None)
    done = JobRunner(store, runs, catalog, plan, timeout=30).execute(job, threading.Event())
    assert done.status == "succeeded"
    response_text = runs.response_path("t", "draft").read_text(encoding="utf-8")
    assert response_text == "REAL RESPONSE\n"
    assert "noisy progress" not in response_text
    log_text = store.log_path("t", job.id).read_text(encoding="utf-8")
    assert "REAL RESPONSE" in log_text
    assert "noisy progress" in log_text

