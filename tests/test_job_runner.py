import sys
import threading
from pathlib import Path

import pytest

from education_pipeline import ContentContract, RunStore, parse_model_catalog, parse_model_plan
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


class SecondFakeRunner(FakeRunner):
    provider_id = "fake2"

    def build_invocation(self, model, plan, prompt_path):
        return Invocation(
            argv=[sys.executable, str(FAKE)],
            env={"FAKE_STDOUT": f"FROM-FAKE2:{model.id}\n"},
        )


def _setup(tmp_path, provider="fake"):
    register_runner(FakeRunner())
    register_runner(UnavailableRunner())
    runs = RunStore(tmp_path)
    runs.create_run("t", content_contract=ContentContract.legacy_markdown())
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


def test_execute_truncated_stdout_fails_instead_of_ingesting(tmp_path, monkeypatch):
    import education_pipeline.daemon.jobs as jobs_mod

    monkeypatch.setattr(jobs_mod, "MAX_LOG_BYTES", 100)
    monkeypatch.setenv("FAKE_STDOUT", "X" * 500)
    runs, catalog, plan, store = _setup(tmp_path)
    job = store.create("t", "draft", "fake", "m", None)
    done = JobRunner(store, runs, catalog, plan, timeout=30).execute(job, threading.Event())
    assert done.status == "failed"
    assert done.error
    assert not runs.has_ingested_response("t", "draft")


def test_execute_survives_manifest_event_append_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_STDOUT", "GENERATED\n")
    runs, catalog, plan, store = _setup(tmp_path)
    job = store.create("t", "draft", "fake", "m", None)

    def _boom(self, *args, **kwargs):
        raise RuntimeError("manifest disk full")

    monkeypatch.setattr(type(runs), "append_manifest_event", _boom)
    done = JobRunner(store, runs, catalog, plan, timeout=30).execute(job, threading.Event())
    # The response already landed durably; a manifest-event append failure
    # must not downgrade an already-committed success.
    assert done.status == "succeeded"
    assert runs.response_path("t", "draft").read_text(encoding="utf-8") == "GENERATED\n"
    assert "manifest disk full" in str(done.metadata.get("manifest_event_error", ""))


def test_execute_resolves_provider_model_from_plan_not_frozen_job_fields(tmp_path, monkeypatch):
    """The runner's (re-resolved) plan wins over the enqueue-time Job fields.

    The daemon rebuilds the effective plan when the worker picks a job up; a
    run override edited while the job sat queued must therefore change which
    provider/model actually execute, not just what the record displayed.
    """

    monkeypatch.setenv("FAKE_STDOUT", "FROM-FAKE\n")
    register_runner(FakeRunner())
    register_runner(SecondFakeRunner())
    runs = RunStore(tmp_path)
    runs.create_run("t", content_contract=ContentContract.legacy_markdown())
    runs.stage_paths("t", "draft").prompt_path.parent.mkdir(parents=True, exist_ok=True)
    runs.stage_paths("t", "draft").prompt_path.write_text("PROMPT", encoding="utf-8")
    catalog = parse_model_catalog(
        {
            "providers": [
                {"id": "fake", "models": [{"id": "m"}]},
                {"id": "fake2", "models": [{"id": "m2"}]},
            ]
        }
    )
    # The effective plan (as re-resolved at execution time) pins draft to fake2/m2.
    plan = parse_model_plan(
        {
            "provider": "fake",
            "stages": {"draft": {"provider": "fake2", "model": "m2", "effort": "high"}},
        },
        catalog,
    )
    store = JobStore(tmp_path)
    # The job record was frozen at enqueue time under the old plan: fake/m.
    job = store.create("t", "draft", "fake", "m", None)

    done = JobRunner(store, runs, catalog, plan, timeout=30).execute(job, threading.Event())

    assert done.status == "succeeded"
    # Execution must have gone through fake2 with model m2, not the frozen fields.
    assert runs.response_path("t", "draft").read_text(encoding="utf-8") == "FROM-FAKE2:m2\n"
    # The record reflects what actually ran.
    assert done.provider == "fake2"
    assert done.model == "m2"
    assert done.effort == "high"


def test_execute_cancel_marks_canceled_without_response(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_DELAY", "10")
    runs, catalog, plan, store = _setup(tmp_path)
    job = store.create("t", "draft", "fake", "m", None)
    cancel = threading.Event()
    cancel.set()  # already cancelled before spawn's read loop begins
    done = JobRunner(store, runs, catalog, plan, timeout=30).execute(job, cancel)
    assert done.status == "canceled"
    assert not runs.has_ingested_response("t", "draft")
