"""Pins three worker-safety defects in ``education_pipeline/daemon/``.

(a) PID reuse: crash-recovery ``Worker.reconcile()`` must not signal a
    process just because its (recycled) pid happens to be alive again after
    a reboot -- it must first verify a process *identity* recorded at spawn
    time. Expected new surface (not yet implemented):

    - ``Job.pid_identity: str | None`` -- a new field on the job record,
      persisted through ``to_dict``/``from_dict`` like every other field.
    - ``education_pipeline.daemon.jobs._process_identity(pid: int) -> str | None``
      -- computes a stable identity for a live pid (e.g. from
      ``/proc/<pid>/stat`` start time on Linux); returns ``None`` when it
      cannot be determined.
    - ``JobRunner._spawn`` records ``job.pid_identity = _process_identity(proc.pid)``
      alongside ``job.pid = proc.pid`` before saving.
    - ``Worker.reconcile()`` only kills a "running" job whose recorded
      ``pid_identity`` matches the live process's current identity (a job
      with no recorded identity -- e.g. one written before this feature --
      keeps today's kill-on-alive-pid behavior).

    These three tests only run on Linux, where the identity mechanism
    described in the defect report (``/proc/<pid>/stat``) applies.

(b) Provider timeout must come from the effective per-stage model plan
    instead of the fixed daemon-wide ``DEFAULT_TIMEOUT_SECONDS``. Expected
    new surface:

    - ``StageModelPlan.timeout_seconds: float | None`` parsed from a
      ``timeout_seconds`` key in ``[stages.<name>]``, alongside the existing
      ``model``/``effort``/``provider`` keys.
    - ``parse_model_plan`` rejects a non-positive or non-numeric
      ``timeout_seconds`` with ``ConfigError``.
    - ``education_pipeline.daemon.jobs.effective_timeout_seconds(plan, stage, model) -> float``
      returns the stage's ``timeout_seconds`` when set, else
      ``DEFAULT_TIMEOUT_SECONDS``. NOTE: the model plan has no per-model
      settings layer today (``StageModelPlan`` is per-stage only; model
      catalog entries carry no timeout field) -- ``model`` is accepted for a
      future per-model layer but is currently unused. Only per-stage
      resolution is pinned here.

(c) ``Handler._read_body`` in ``daemon/server.py`` has no socket timeout, so
    a client that promises a body (``Content-Length``) larger than what it
    actually sends, then stalls, parks the handler thread forever. Expected
    new surface: ``build_server(context, *, socket_timeout=...)`` sets the
    handler's socket timeout (``BaseRequestHandler.timeout``), bounding how
    long any blocking read on the connection -- including the one inside
    ``_read_body`` -- can take.
"""

import http.client
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from education_pipeline import ContentContract, RunStore, parse_model_catalog, parse_model_plan
from education_pipeline.config import ConfigError
from education_pipeline.daemon import StaticConfigSource
from education_pipeline.daemon import jobs as jobs_module
from education_pipeline.daemon.jobs import (
    DEFAULT_TIMEOUT_SECONDS,
    JobRunner,
    JobStore,
    Worker,
    popen_kwargs,
)
from education_pipeline.daemon.server import DaemonContext, build_server
from education_pipeline.providers import Invocation, ProviderResponse, register_runner
from education_pipeline.workspace import ProfileStore, TopicStore

FAKE = Path(__file__).parent / "fake_provider.py"


class FakeRunner:
    provider_id = "fake"
    executable = True

    def is_available(self) -> bool:
        return True

    def build_invocation(self, model, plan, prompt_path):
        return Invocation(argv=[sys.executable, str(FAKE)])

    def parse_response(self, stdout):
        return ProviderResponse(text=stdout, metadata={})


def _setup(tmp_path):
    register_runner(FakeRunner())
    runs = RunStore(tmp_path)
    runs.create_run("t", content_contract=ContentContract.legacy_markdown())
    runs.stage_paths("t", "draft").prompt_path.parent.mkdir(parents=True, exist_ok=True)
    runs.stage_paths("t", "draft").prompt_path.write_text("PROMPT", encoding="utf-8")
    catalog = parse_model_catalog({"providers": [{"id": "fake", "models": [{"id": "m"}]}]})
    plan = parse_model_plan({"provider": "fake", "stages": {"draft": {"model": "m"}}}, catalog)
    store = JobStore(tmp_path)
    return runs, catalog, plan, store


def _wait_terminal(store, job_id, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        job = store.find(job_id)
        if job and job.status in {"succeeded", "failed", "canceled", "interrupted"}:
            return job
        time.sleep(0.02)
    raise AssertionError("job did not reach a terminal state")


def _spawn_sleeper():
    return subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"], **popen_kwargs()
    )


# ---------------------------------------------------------------------------
# (a) PID reuse: reconcile must verify a recorded process identity, not just
#     pid liveness, before signalling.
# ---------------------------------------------------------------------------

LINUX_ONLY = pytest.mark.skipif(
    sys.platform != "linux",
    reason="process identity is defined via /proc/<pid>/stat on Linux",
)


@LINUX_ONLY
def test_spawn_persists_process_identity_in_job_record(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_STDOUT", "OK\n")
    runs, catalog, plan, store = _setup(tmp_path)
    job = store.create("t", "draft", "fake", "m", None)
    runner = JobRunner(store, runs, catalog, plan, timeout=30)
    prompt_path = runs.stage_paths("t", "draft").prompt_path
    invocation = Invocation(argv=[sys.executable, str(FAKE)])

    runner._spawn(job, invocation, prompt_path, threading.Event())

    assert job.pid_identity, "spawn must record a process identity alongside the pid"
    on_disk = store.find(job.id)
    assert on_disk.pid_identity == job.pid_identity


@LINUX_ONLY
def test_reconcile_does_not_kill_a_running_job_whose_identity_does_not_match(
    tmp_path, monkeypatch
):
    # A recycled pid: alive, but not the process this job record was spawned
    # for (a mismatched/garbage identity stands in for "some unrelated
    # process now happens to hold this pid after a reboot").
    store = JobStore(tmp_path)
    proc = _spawn_sleeper()
    try:
        assert jobs_module._pid_plausibly_alive(proc.pid)
        job = store.create("t", "draft", "fake", "m", None)
        job.status = "running"
        job.pid = proc.pid
        job.pid_identity = "stale-identity-from-a-different-process"
        store.save(job)

        killpg_calls = []
        monkeypatch.setattr(os, "killpg", lambda *a, **k: killpg_calls.append(a))

        worker = Worker(store, lambda job: None)
        worker.reconcile()

        assert killpg_calls == [], "a recycled pid must never be signalled"
        assert store.find(job.id).status == "interrupted"
        assert proc.poll() is None, "the unrelated live process must be left alone"
    finally:
        proc.terminate()
        proc.wait(timeout=5)


@LINUX_ONLY
def test_reconcile_still_kills_a_running_job_whose_identity_matches(tmp_path, monkeypatch):
    # Regression guard: today's kill-on-alive-pid behavior must survive for
    # the ordinary (non-recycled) case.
    store = JobStore(tmp_path)
    proc = _spawn_sleeper()
    try:
        job = store.create("t", "draft", "fake", "m", None)
        job.status = "running"
        job.pid = proc.pid
        job.pid_identity = jobs_module._process_identity(proc.pid)
        store.save(job)

        killpg_calls = []
        monkeypatch.setattr(os, "killpg", lambda *a, **k: killpg_calls.append(a))

        worker = Worker(store, lambda job: None)
        worker.reconcile()

        assert killpg_calls, "a genuinely-still-running job must still be signalled"
        assert store.find(job.id).status == "interrupted"
    finally:
        proc.terminate()
        proc.wait(timeout=5)


# ---------------------------------------------------------------------------
# (b) Provider timeout must be read from the effective per-stage model plan.
# ---------------------------------------------------------------------------


def test_stage_model_plan_reads_timeout_seconds_per_stage():
    plan = parse_model_plan(
        {"provider": "manual", "stages": {"draft": {"timeout_seconds": 60}}}
    )
    assert plan.stage("draft").timeout_seconds == 60
    # a stage that never set it stays unset (falls back to the daemon default)
    assert plan.stage("qa").timeout_seconds is None


@pytest.mark.parametrize("bad", [0, -5, -0.001, "soon"])
def test_parse_model_plan_rejects_invalid_timeout_seconds(bad):
    with pytest.raises(ConfigError, match="timeout_seconds"):
        parse_model_plan(
            {"provider": "manual", "stages": {"draft": {"timeout_seconds": bad}}}
        )


def test_effective_timeout_seconds_uses_stage_override_else_default():
    catalog = parse_model_catalog({"providers": [{"id": "fake", "models": [{"id": "m"}]}]})
    plan = parse_model_plan(
        {"provider": "fake", "stages": {"draft": {"model": "m", "timeout_seconds": 60}}},
        catalog,
    )
    assert jobs_module.effective_timeout_seconds(plan, "draft", "m") == 60
    assert jobs_module.effective_timeout_seconds(plan, "qa", "m") == DEFAULT_TIMEOUT_SECONDS


def test_worker_times_out_a_job_using_the_stages_effective_timeout(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_STDOUT", "OK\n")
    monkeypatch.setenv("FAKE_DELAY", "2")
    runs, catalog, _plan, store = _setup(tmp_path)
    # A tight per-stage timeout, well under FAKE_DELAY, distinct from the
    # 1800s daemon-wide default -- proves the job actually consults the plan.
    plan = parse_model_plan(
        {"provider": "fake", "stages": {"draft": {"model": "m", "timeout_seconds": 0.3}}},
        catalog,
    )

    def make(job):
        timeout = jobs_module.effective_timeout_seconds(plan, job.stage, job.model)
        return JobRunner(store, runs, catalog, plan, timeout=timeout)

    worker = Worker(store, make)
    worker.start()
    try:
        job = store.create("t", "draft", "fake", "m", None)
        worker.enqueue(job)
        done = _wait_terminal(store, job.id)
        assert done.status == "failed"
        assert done.error == "timeout"
    finally:
        worker.stop()


# ---------------------------------------------------------------------------
# (c) `_read_body` must bound a stalled/truncated request body with a socket
#     timeout instead of parking the handler thread forever.
# ---------------------------------------------------------------------------


def _minimal_context(tmp_path):
    catalog = parse_model_catalog({"providers": [{"id": "manual", "label": "Manual"}]})
    plan = parse_model_plan({"provider": "manual"}, catalog)
    runs = RunStore(tmp_path)
    store = JobStore(tmp_path)
    worker = Worker(store, lambda job: None)
    return DaemonContext(
        root=tmp_path,
        store=store,
        worker=worker,
        runs=runs,
        token="secret-token",
        version="0.1.0",
        config=StaticConfigSource(catalog, plan),
        topics=TopicStore(tmp_path),
        profiles=ProfileStore(tmp_path),
        on_shutdown=lambda: None,
    )


def test_read_body_socket_timeout_bounds_a_truncated_request(tmp_path):
    context = _minimal_context(tmp_path)
    # A short configured timeout keeps this test fast; production would use a
    # much larger default.
    server = build_server(context, socket_timeout=1.0)
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
    )
    thread.start()
    try:
        port = server.server_port
        body = b'{"text": "hi"}'
        promised_length = len(body) + 100  # lie: promise more than we actually send
        request = (
            "POST /v1/preview HTTP/1.1\r\n"
            "Host: 127.0.0.1\r\n"
            f"X-EP-Token: {context.token}\r\n"
            "Content-Type: application/json\r\n"
            f"Content-Length: {promised_length}\r\n"
            "Connection: close\r\n\r\n"
        ).encode("ascii") + body

        sock = socket.create_connection(("127.0.0.1", port), timeout=10)
        try:
            sock.sendall(request)
            # Deliberately never send the remaining promised bytes -- the
            # client stalls. The test's own 5s guard is well above the
            # configured 1s socket_timeout, so a fix resolves this long
            # before the guard would fire; an unfixed handler hangs forever
            # and this raises socket.timeout instead of finishing quickly.
            sock.settimeout(5)
            start = time.monotonic()
            try:
                data = sock.recv(4096)
            except (socket.timeout, TimeoutError):
                data = None
            elapsed = time.monotonic() - start
        finally:
            sock.close()

        assert data is not None, (
            "handler must resolve (respond or close) a truncated body within "
            "the configured socket timeout instead of hanging past the "
            "test's 5s guard"
        )
        assert elapsed < 5
    finally:
        server.shutdown()
        thread.join(timeout=5)
