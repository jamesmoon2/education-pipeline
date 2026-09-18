import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from education_pipeline import ContentContract, RunStore, parse_model_catalog, parse_model_plan
from education_pipeline.config import ConfigError
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
    # manifest carries a stage-provenance entry for this job
    provenance = runs.read_manifest("t")["stage_provenance"]
    assert len(provenance) == 1
    entry = provenance[0]
    assert entry["job_id"] == job.id
    assert entry["stage"] == "draft"
    assert entry["provider"] == "fake"
    assert entry["model"] == "m"
    assert entry["source"] == "default"
    assert "recorded_at" in entry


def test_execute_normalizes_provider_crlf_output(tmp_path, monkeypatch):
    # Windows provider CLIs write \r\n to stdout; responses are sha-keyed
    # byte-exact artifacts, so the platform newline convention must be
    # normalized out before ingestion.
    monkeypatch.setenv("FAKE_STDOUT", "LINE ONE\r\nLINE TWO\r\n")
    runs, catalog, plan, store = _setup(tmp_path)
    job = store.create("t", "draft", "fake", "m", None)
    done = JobRunner(store, runs, catalog, plan, timeout=30).execute(
        job, threading.Event()
    )
    assert done.status == "succeeded"
    assert runs.response_path("t", "draft").read_bytes() == b"LINE ONE\nLINE TWO\n"


@pytest.mark.parametrize("prompt_state", ["missing", "stale"])
def test_execute_audit_stage_refuses_unready_prompt_before_provider_build(
    tmp_path, monkeypatch, prompt_state
):
    monkeypatch.setenv("FAKE_STDOUT", '{"findings": []}\n')
    provider = FakeRunner()
    build_calls = []
    original_build = provider.build_invocation

    def tracking_build(model, plan, prompt_path):
        build_calls.append(prompt_path)
        return original_build(model, plan, prompt_path)

    monkeypatch.setattr(provider, "build_invocation", tracking_build)
    register_runner(provider)
    runs = RunStore(tmp_path)
    runs.create_run("t", content_contract=ContentContract.legacy_markdown())
    prompt = runs.stage_paths("t", "audit").prompt_path
    if prompt_state == "stale":
        prompt.parent.mkdir(parents=True, exist_ok=True)
        prompt.write_text("AUDIT PROMPT", encoding="utf-8")
    catalog = parse_model_catalog(
        {"providers": [{"id": "fake", "models": [{"id": "m", "argv_model": "x"}]}]}
    )
    plan = parse_model_plan(
        {"provider": "fake", "stages": {"audit": {"model": "m"}}},
        catalog,
    )
    store = JobStore(tmp_path)
    job = store.create("t", "audit", "fake", "m", None)

    done = JobRunner(store, runs, catalog, plan, timeout=30).execute(
        job, threading.Event()
    )

    assert done.status == "failed"
    expected = (
        "audit prompt is missing; prepare it before enqueue"
        if prompt_state == "missing"
        else "audit prompt is stale; rebuild it before enqueue or response ingest"
    )
    assert done.error == expected
    assert build_calls == []
    assert runs.stage_paths("t", "audit").response_path.exists() is False


def test_execute_ready_audit_preflights_then_runs_and_ingests_json(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("FAKE_STDOUT", '{"schema_version":1}\n')
    call_order = []

    class TrackingRunner(FakeRunner):
        def build_invocation(self, model, plan, prompt_path):
            call_order.append("build")
            return super().build_invocation(model, plan, prompt_path)

    register_runner(TrackingRunner())
    runs = RunStore(tmp_path)
    runs.create_run("t", content_contract=ContentContract.legacy_markdown())
    paths = runs.stage_paths("t", "audit")
    paths.prompt_path.parent.mkdir(parents=True, exist_ok=True)
    paths.prompt_path.write_text("BOUND AUDIT PROMPT", encoding="utf-8")

    def ready_prompt(self, topic_id, stage):
        call_order.append("preflight")
        assert (topic_id, stage) == ("t", "audit")
        return paths.prompt_path

    def ingest(self, topic_id, stage, text, *, force=False):
        call_order.append("ingest")
        assert (topic_id, stage, force) == ("t", "audit", False)
        paths.response_path.parent.mkdir(parents=True, exist_ok=True)
        paths.response_path.write_text(text, encoding="utf-8")
        return paths.response_path

    monkeypatch.setattr(RunStore, "require_provider_ready_prompt", ready_prompt)
    monkeypatch.setattr(RunStore, "ingest_response", ingest)
    catalog = parse_model_catalog(
        {"providers": [{"id": "fake", "models": [{"id": "m", "argv_model": "x"}]}]}
    )
    plan = parse_model_plan(
        {"provider": "fake", "stages": {"audit": {"model": "m"}}},
        catalog,
    )
    store = JobStore(tmp_path)
    job = store.create("t", "audit", "fake", "m", None)

    done = JobRunner(store, runs, catalog, plan, timeout=30).execute(
        job, threading.Event()
    )

    assert done.status == "succeeded"
    assert done.response_path == str(paths.response_path)
    assert call_order == ["preflight", "build", "ingest"]
    assert paths.response_path.read_text(encoding="utf-8") == '{"schema_version":1}\n'


def test_audit_stdout_is_ingested_but_never_mirrored_to_job_log(
    tmp_path, monkeypatch
):
    planted = "PLANTED PRIVATE AUDIT NARRATIVE"
    planted_stderr = "PLANTED PRIVATE AUDIT STDERR"
    monkeypatch.setenv(
        "FAKE_STDOUT",
        '{"schema_version":1,"overall_summary":"' + planted + '"}\n',
    )
    monkeypatch.setenv("FAKE_STDERR", planted_stderr + "\n")
    register_runner(FakeRunner())
    runs = RunStore(tmp_path)
    runs.create_run("t", content_contract=ContentContract.legacy_markdown())
    paths = runs.stage_paths("t", "audit")
    paths.prompt_path.parent.mkdir(parents=True, exist_ok=True)
    paths.prompt_path.write_text("BOUND AUDIT PROMPT", encoding="utf-8")

    monkeypatch.setattr(
        RunStore,
        "require_provider_ready_prompt",
        lambda self, topic_id, stage: paths.prompt_path,
    )

    def ingest(self, topic_id, stage, text, *, force=False):
        paths.response_path.parent.mkdir(parents=True, exist_ok=True)
        paths.response_path.write_text(text, encoding="utf-8")
        return paths.response_path

    monkeypatch.setattr(RunStore, "ingest_response", ingest)
    catalog = parse_model_catalog(
        {"providers": [{"id": "fake", "models": [{"id": "m"}]}]}
    )
    plan = parse_model_plan(
        {"provider": "fake", "stages": {"audit": {"model": "m"}}}, catalog
    )
    store = JobStore(tmp_path)
    job = store.create("t", "audit", "fake", "m", None)

    done = JobRunner(store, runs, catalog, plan, timeout=30).execute(
        job, threading.Event()
    )

    assert done.status == "succeeded"
    assert planted in paths.response_path.read_text(encoding="utf-8")
    log_text = store.log_path("t", job.id).read_text(encoding="utf-8")
    assert planted not in log_text
    assert planted_stderr not in log_text
    assert log_text == ""


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


# --- T23: JobRunner dispatch for unit jobs (draft skeleton/module) ---------
#
# `RunStore.draft_unit_paths`/`ingest_draft_unit` are thread T22's engine-side
# work and don't exist on this worktree's RunStore yet (see the T23 prompt
# and docs/superpowers/specs/2026-09-18-per-module-drafting-design.md §5).
# These tests stub the two methods onto the real `RunStore` class -- same
# `monkeypatch.setattr(RunStore, ...)` pattern the audit-preflight tests
# above already use for `require_provider_ready_prompt`/`ingest_response` --
# so JobRunner.execute is exercised against exactly the two-method contract
# the brief specifies, with everything else (append_manifest_event,
# record_stage_provenance, ...) staying real.


def _unit_paths(run_dir: Path, unit: str, module_id: str | None) -> SimpleNamespace:
    base = run_dir / "draft" / "skeleton" if unit == "skeleton" else run_dir / "draft" / "modules" / module_id
    return SimpleNamespace(
        unit=unit,
        module_id=module_id,
        prompt_path=base / "prompt.md",
        response_path=base / "response.json",
        stub_path=base / "SAVE_RESPONSE_HERE.json",
        previous_path=base / "response.previous.json",
    )


def _install_unit_stub(monkeypatch, run_dir: Path, ingest_calls: list, *, ingest_error=None):
    def draft_unit_paths(self, topic_id, unit, *, module_id=None):
        return _unit_paths(run_dir, unit, module_id)

    def ingest_draft_unit(self, topic_id, unit, text, *, module_id=None, force=False):
        ingest_calls.append((topic_id, unit, text, module_id, force))
        if ingest_error is not None:
            raise ingest_error
        paths = _unit_paths(run_dir, unit, module_id)
        paths.response_path.parent.mkdir(parents=True, exist_ok=True)
        paths.response_path.write_text(text, encoding="utf-8")
        return paths

    monkeypatch.setattr(RunStore, "draft_unit_paths", draft_unit_paths, raising=False)
    monkeypatch.setattr(RunStore, "ingest_draft_unit", ingest_draft_unit, raising=False)


def _unit_job_setup(tmp_path, monkeypatch, *, unit, module_id, ingest_error=None):
    register_runner(FakeRunner())
    runs = RunStore(tmp_path)
    runs.create_run("t", content_contract=ContentContract.legacy_markdown())
    run_dir = runs.run_dir("t")
    ingest_calls: list = []
    _install_unit_stub(monkeypatch, run_dir, ingest_calls, ingest_error=ingest_error)

    prompt_path = _unit_paths(run_dir, unit, module_id).prompt_path
    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path.write_text("UNIT PROMPT", encoding="utf-8")

    catalog = parse_model_catalog({"providers": [{"id": "fake", "models": [{"id": "m"}]}]})
    plan = parse_model_plan({"provider": "fake", "stages": {"draft": {"model": "m"}}}, catalog)
    store = JobStore(tmp_path)
    job = store.create("t", "draft", "fake", "m", None)
    job.unit = unit
    job.module_id = module_id
    return runs, catalog, plan, store, job, ingest_calls


def test_execute_module_unit_reads_and_ingests_through_draft_unit_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_STDOUT", "MODULE BODY\n")
    runs, catalog, plan, store, job, ingest_calls = _unit_job_setup(
        tmp_path, monkeypatch, unit="module", module_id="loop-basics"
    )

    done = JobRunner(store, runs, catalog, plan, timeout=30).execute(job, threading.Event())

    assert done.status == "succeeded"
    assert ingest_calls == [("t", "module", "MODULE BODY\n", "loop-basics", False)]
    expected_response = runs.run_dir("t") / "draft" / "modules" / "loop-basics" / "response.json"
    assert done.response_path == str(expected_response)
    assert expected_response.read_text(encoding="utf-8") == "MODULE BODY\n"
    # The ordinary stage-level draft response must never be touched by a
    # module-unit job.
    assert not runs.stage_paths("t", "draft").response_path.exists()
    provenance = runs.read_manifest("t")["stage_provenance"]
    assert provenance[-1]["stage"] == "draft"
    assert provenance[-1]["job_id"] == job.id


def test_execute_skeleton_unit_reads_and_ingests_through_draft_unit_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_STDOUT", "SKELETON BODY\n")
    runs, catalog, plan, store, job, ingest_calls = _unit_job_setup(
        tmp_path, monkeypatch, unit="skeleton", module_id=None
    )

    done = JobRunner(store, runs, catalog, plan, timeout=30).execute(job, threading.Event())

    assert done.status == "succeeded"
    assert ingest_calls == [("t", "skeleton", "SKELETON BODY\n", None, False)]
    expected_response = runs.run_dir("t") / "draft" / "skeleton" / "response.json"
    assert done.response_path == str(expected_response)
    assert not runs.stage_paths("t", "draft").response_path.exists()


def test_execute_module_unit_salvage_filename_uses_module_id_on_ingest_failure(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("FAKE_STDOUT", "BAD BODY\n")
    runs, catalog, plan, store, job, ingest_calls = _unit_job_setup(
        tmp_path,
        monkeypatch,
        unit="module",
        module_id="loop-basics",
        ingest_error=ConfigError("boom"),
    )

    done = JobRunner(store, runs, catalog, plan, timeout=30).execute(job, threading.Event())

    assert done.status == "failed"
    responses_dir = runs.stage_paths("t", "draft").response_path.parent
    salvaged = list(responses_dir.glob("draft.loop-basics.failed.*.txt"))
    assert len(salvaged) == 1
    assert salvaged[0].read_text(encoding="utf-8") == "BAD BODY\n"
    # never the bare stage-name salvage name used for non-unit jobs
    assert not list(responses_dir.glob("draft.failed.*.txt"))


def test_execute_skeleton_unit_salvage_filename_uses_skeleton_on_ingest_failure(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("FAKE_STDOUT", "BAD SKELETON\n")
    runs, catalog, plan, store, job, ingest_calls = _unit_job_setup(
        tmp_path,
        monkeypatch,
        unit="skeleton",
        module_id=None,
        ingest_error=ConfigError("boom"),
    )

    done = JobRunner(store, runs, catalog, plan, timeout=30).execute(job, threading.Event())

    assert done.status == "failed"
    responses_dir = runs.stage_paths("t", "draft").response_path.parent
    salvaged = list(responses_dir.glob("draft.skeleton.failed.*.txt"))
    assert len(salvaged) == 1
    assert salvaged[0].read_text(encoding="utf-8") == "BAD SKELETON\n"


def test_execute_module_unit_consults_its_own_prompt_not_the_ordinary_stage_one(
    tmp_path, monkeypatch
):
    # The *ordinary* stage-level draft prompt is present, but the module's
    # own unit prompt (what execute() must actually consult for a unit job)
    # is absent. A runner that still fell back to stage_paths would spawn
    # the provider against the ordinary prompt and succeed -- which is
    # exactly the (wrong, pre-item-4) behaviour this pins against.
    monkeypatch.setenv("FAKE_STDOUT", "MODULE BODY\n")
    register_runner(FakeRunner())
    runs = RunStore(tmp_path)
    runs.create_run("t", content_contract=ContentContract.legacy_markdown())
    run_dir = runs.run_dir("t")
    ingest_calls: list = []
    _install_unit_stub(monkeypatch, run_dir, ingest_calls)
    # The ordinary stage prompt exists...
    ordinary_prompt = runs.stage_paths("t", "draft").prompt_path
    ordinary_prompt.parent.mkdir(parents=True, exist_ok=True)
    ordinary_prompt.write_text("ORDINARY STAGE PROMPT", encoding="utf-8")
    # ...but the module's own prompt (draft_unit_paths) does not.

    catalog = parse_model_catalog({"providers": [{"id": "fake", "models": [{"id": "m"}]}]})
    plan = parse_model_plan({"provider": "fake", "stages": {"draft": {"model": "m"}}}, catalog)
    store = JobStore(tmp_path)
    job = store.create("t", "draft", "fake", "m", None)
    job.unit = "module"
    job.module_id = "loop-basics"

    done = JobRunner(store, runs, catalog, plan, timeout=30).execute(job, threading.Event())

    assert done.status == "failed"
    assert ingest_calls == []
    assert not runs.stage_paths("t", "draft").response_path.exists()
