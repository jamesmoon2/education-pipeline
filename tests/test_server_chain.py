"""Failing (red) tests for thread T33 "Daemon carries the chain across jobs".

Design: docs/superpowers/plans/2026-09-18-phase-3-headless.md (T33 row,
decision 9 addendum). None of ``Job.chain``, ``Job.continuation``,
``Worker(..., on_finished=)`` or ``DaemonContext.continue_after_job`` exist
yet, so every live-server assertion here either 404s/KeyErrors on a missing
``"chain"``/``"continuation"`` field or times out waiting for a
``continuation`` that the (not yet written) completion hook never populates
-- a different subagent makes these pass.

Reuses ``tests/test_server.py``'s server harness (``_start_server``, ``_req``,
``FakeRunner``, ``server_with_context``) exactly as ``tests/
test_server_continue.py`` does, plus ``tests/test_draft_units.py`` (``tdu``)
for the guide-v1 fan-out seeds and canned skeleton/module response bodies,
and ``tests/test_cli.py``'s ``_seed_topic_to_draft`` for a legacy run parked
at "draft prompt written, no response yet".

A note on "the real stop for the parity case" (item 4 of the brief). The red
draft of this file pinned a stall here, because ingesting the skeleton
response synchronously writes the missing module prompts
(``runs_draft_units.py``'s decision 9), leaving the very next
``RunStatus.next_action`` at ``save_response``/``draft`` again -- for the
module batch this time, not the skeleton -- which the T30 stall guard could
not tell from a genuine stall while it compared only ``(action, stage)``.
That was a real bug in the guard (it broke the CLI's ``run --until approval``
on every non-legacy course too), not a fact about the chain; T33 fixes it by
comparing the whole ``NextAction``, detail included, against the action the
finished job was started against. ``test_continue_chain_carries_a_fresh_
guide_run_from_skeleton_to_approve`` below therefore pins the parity case
proper, step by observed step: skeleton job -> module batch -> ``approve``,
with the draft response assembled by the last module job's own ingest.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

import test_cli
import test_draft_units as tdu
from test_server import FakeRunner, _req, _start_server, server_with_context  # noqa: F401 (fixture)

from education_pipeline import ContentContract, parse_model_catalog, parse_model_plan
from education_pipeline.providers import Invocation, ProviderResponse, register_runner

FAKE = Path(__file__).parent / "fake_provider.py"
TERMINAL = {"succeeded", "failed", "canceled", "interrupted"}


def _continue(port: int, topic_id: str):
    return _req(port, "POST", f"/v1/runs/{topic_id}/continue")


def _write_topic(tmp_path: Path, topic_id: str, title: str = "Topic") -> None:
    topics_dir = tmp_path / "topics"
    topics_dir.mkdir(parents=True, exist_ok=True)
    (topics_dir / f"{topic_id}.toml").write_text(
        f'schema_version = 1\nid = "{topic_id}"\ntitle = "{title}"\n', encoding="utf-8"
    )


class ChainFakeRunner:
    """Answers a draft *unit* prompt (skeleton or one module) with the real
    canned fixture body, so a live fan-out runs to completion through actual
    job execution rather than a stub; any other prompt (a legacy stage, or a
    guide stage other than draft) gets a fixed placeholder. ``fail_modules``
    makes the named module ids exit non-zero instead."""

    provider_id = "fake"
    executable = True

    def __init__(self, fail_modules: frozenset[str] = frozenset()):
        self.fail_modules = fail_modules

    def is_available(self) -> bool:
        return True

    def build_invocation(self, model, plan, prompt_path):
        unit = prompt_path.parent.name
        if unit == "skeleton":
            text = tdu._skeleton_response()
        elif unit in tdu.MODULE_ORDER:
            text = tdu._module_response(unit)
        else:
            text = "# Generated draft\n"
        env = {"FAKE_STDOUT": text}
        if unit in self.fail_modules:
            env = {"FAKE_STDOUT": "", "FAKE_EXIT": "1"}
        return Invocation(argv=[sys.executable, str(FAKE)], env=env)

    def parse_response(self, stdout):
        return ProviderResponse(text=stdout, metadata={})


def _wait_job_terminal(port: int, job_id: str, timeout: float = 20.0) -> dict:
    deadline = time.time() + timeout
    body = None
    while time.time() < deadline:
        status, body = _req(port, "GET", f"/v1/jobs/{job_id}")
        assert status == 200
        if body["status"] in TERMINAL:
            return body
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} did not reach a terminal status in time: {body}")


def _wait_job_continuation(port: int, job_id: str, timeout: float = 20.0) -> dict:
    deadline = time.time() + timeout
    body = None
    while time.time() < deadline:
        status, body = _req(port, "GET", f"/v1/jobs/{job_id}")
        assert status == 200
        if body.get("continuation") is not None:
            return body
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} never recorded a continuation: {body}")


def _no_new_job_appears(port: int, context, topic_id: str, before_count: int, wait: float = 1.0) -> None:
    """A bounded negative check: nothing new got enqueued for ``topic_id``."""

    time.sleep(wait)
    assert len(context.store.list(topic_id)) == before_count


# ---------------------------------------------------------------------------
# 1. chain flag: continue route sets it, the plain jobs route never does.
# ---------------------------------------------------------------------------


def test_continue_route_job_carries_chain_true(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_DELAY", "5")
    srv, worker, context = _start_server(tmp_path, monkeypatch)
    try:
        _write_topic(tmp_path, "chain-topic")
        context.runs.create_run("chain-topic", content_contract=ContentContract.legacy_markdown())

        status, body = _continue(srv.server_port, "chain-topic")
        assert status == 200
        assert body["stop"]["kind"] == "started"

        jobs = context.store.list("chain-topic")
        assert len(jobs) == 1
        status, job_body = _req(srv.server_port, "GET", f"/v1/jobs/{jobs[0].id}")
        assert status == 200
        assert job_body["chain"] is True
    finally:
        worker.stop()
        srv.shutdown()


def test_plain_jobs_route_job_carries_chain_false_and_never_gains_a_continuation(
    tmp_path, monkeypatch
):
    srv, worker, context = _start_server(tmp_path, monkeypatch)
    try:
        _write_topic(tmp_path, "plain-topic")
        context.runs.create_run("plain-topic", content_contract=ContentContract.legacy_markdown())
        context.runs.advance("plain-topic")  # writes the spec prompt

        status, job_body = _req(
            srv.server_port,
            "POST",
            "/v1/jobs",
            body={"topic_id": "plain-topic", "stage": "spec"},
        )
        assert status == 200
        assert job_body["chain"] is False
        assert job_body.get("continuation") is None

        done = _wait_job_terminal(srv.server_port, job_body["id"])
        assert done["status"] == "succeeded"
        # Give a would-be completion hook a moment it should never take.
        time.sleep(0.3)
        status, final_body = _req(srv.server_port, "GET", f"/v1/jobs/{job_body['id']}")
        assert status == 200
        assert final_body["chain"] is False
        assert final_body.get("continuation") is None
    finally:
        worker.stop()
        srv.shutdown()


# ---------------------------------------------------------------------------
# 2. Legacy run at draft: the chain lands the draft response and stops at
#    approve with no further request -- legacy draft has no validate gate.
# ---------------------------------------------------------------------------


def test_continue_chain_lands_a_legacy_draft_and_stops_at_approve(tmp_path, monkeypatch):
    register_runner(ChainFakeRunner())
    srv, worker, context = _start_server(tmp_path, monkeypatch)
    try:
        test_cli._seed_topic_to_draft(tmp_path)  # spec+outline approved; draft prompt written
        topic_id = "systems-thinking"

        status, body = _continue(srv.server_port, topic_id)
        assert status == 200
        assert body["stop"]["kind"] == "started"
        jobs = context.store.list(topic_id)
        assert len(jobs) == 1
        job_id = jobs[0].id

        landed = _wait_job_terminal(srv.server_port, job_id)
        assert landed["status"] == "succeeded"
        chained = _wait_job_continuation(srv.server_port, job_id)
        assert chained["chain"] is True
        continuation = chained["continuation"]
        assert continuation["after"] == "job"
        assert continuation["steps"] == []
        assert continuation["stop"] == {"kind": "approve", "stage": "draft"}
        assert isinstance(continuation["at"], str) and continuation["at"]

        status, run_body = _req(srv.server_port, "GET", f"/v1/runs/{topic_id}")
        assert status == 200
        assert run_body["continuation"] == {
            "job_id": job_id,
            "stage": "draft",
            "provider": "fake",
            **continuation,
        }

        draft_status = next(s for s in run_body["stages"] if s["stage"] == "draft")
        assert draft_status["approved"] is False
        assert draft_status["response_ingested"] is True
    finally:
        worker.stop()
        srv.shutdown()


# ---------------------------------------------------------------------------
# 3. Failed and canceled jobs record a failed continuation with the CLI's
#    wording (decision 9: "records the outcome on the finishing job").
# ---------------------------------------------------------------------------


def test_continue_chain_records_failed_continuation_for_a_failed_job(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_EXIT", "1")
    monkeypatch.setenv("FAKE_STDOUT", "")
    srv, worker, context = _start_server(tmp_path, monkeypatch)
    try:
        test_cli._seed_topic_to_draft(tmp_path)
        topic_id = "systems-thinking"

        status, body = _continue(srv.server_port, topic_id)
        assert status == 200
        job_id = context.store.list(topic_id)[0].id

        landed = _wait_job_terminal(srv.server_port, job_id)
        assert landed["status"] == "failed"
        assert landed["error"]

        chained = _wait_job_continuation(srv.server_port, job_id)
        continuation = chained["continuation"]
        assert continuation["stop"]["kind"] == "failed"
        assert continuation["stop"]["action"] == "running draft with fake"
        assert continuation["stop"]["message"] == landed["error"]
    finally:
        worker.stop()
        srv.shutdown()


def test_continue_chain_records_failed_continuation_for_a_canceled_job(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_DELAY", "5")
    srv, worker, context = _start_server(tmp_path, monkeypatch)
    try:
        test_cli._seed_topic_to_draft(tmp_path)
        topic_id = "systems-thinking"

        status, body = _continue(srv.server_port, topic_id)
        assert status == 200
        job_id = context.store.list(topic_id)[0].id

        status, _ = _req(srv.server_port, "POST", f"/v1/jobs/{job_id}/cancel")
        assert status == 200

        landed = _wait_job_terminal(srv.server_port, job_id)
        assert landed["status"] == "canceled"

        chained = _wait_job_continuation(srv.server_port, job_id)
        continuation = chained["continuation"]
        assert continuation["stop"]["kind"] == "failed"
        assert "canceled" in continuation["stop"]["message"]
    finally:
        worker.stop()
        srv.shutdown()


# ---------------------------------------------------------------------------
# 4. The parity case, in its two real halves (see the module docstring for
#    why it splits this way): the skeleton job's own completion stalls
#    before the batch, and a batch that is already ready carries all the way
#    to approve with no further request.
# ---------------------------------------------------------------------------


def test_continue_chain_carries_a_fresh_guide_run_from_skeleton_to_approve(
    tmp_path, server_with_context
):
    """The parity case: from a guide-v1 run with nothing drafted
    (``tdu._run_with_skeleton_prompt``), one ``POST .../continue`` and then
    nothing but polling carries the run through the skeleton job, the module
    batch the skeleton's ingest unlocked, assembly and draft validation, to
    the first judgment -- exactly what ``run --until approval`` does.

    Every step below is the sequence actually observed, not a sketch: the
    skeleton job's continuation *starts the batch* (it does not reach
    approve), and the last module job's own ingest assembles the draft
    response, so the batch's continuation finds the run already at ``approve``
    and takes no mechanical step of its own."""

    port, context = server_with_context
    register_runner(ChainFakeRunner())
    tdu._run_with_skeleton_prompt(tmp_path)

    status, body = _continue(port, tdu.TID)
    assert status == 200
    assert body["stop"]["kind"] == "started"
    assert "count" not in body["stop"]  # a solo skeleton job, not a batch

    jobs = context.store.list(tdu.TID)
    assert len(jobs) == 1
    skeleton_id = jobs[0].id

    landed = _wait_job_terminal(port, skeleton_id)
    assert landed["status"] == "succeeded"
    assert landed["unit"] == "skeleton"

    # Step 1: the skeleton job's own completion hook. Its ingest already wrote
    # the module prompts, so the next action is save_response/draft again --
    # for the module batch, with a different detail. The whole-next-action
    # stall guard lets that through, and the hook enqueues the batch.
    chained = _wait_job_continuation(port, skeleton_id)
    assert chained["chain"] is True
    skeleton_continuation = chained["continuation"]
    assert skeleton_continuation["after"] == "job"
    assert skeleton_continuation["steps"] == [
        {
            "kind": "job",
            "stage": "draft",
            "provider": "fake",
            "count": len(tdu.MODULE_ORDER),
        }
    ]
    assert skeleton_continuation["stop"] == {
        "kind": "started",
        "stage": "draft",
        "provider": "fake",
        "count": len(tdu.MODULE_ORDER),
    }

    # Step 2: the module batch itself -- every job chained, one batch id.
    module_jobs = [job for job in context.store.list(tdu.TID) if job.unit == "module"]
    assert len(module_jobs) == len(tdu.MODULE_ORDER)
    batch_id = module_jobs[0].batch_id
    assert batch_id is not None
    assert all(job.batch_id == batch_id for job in module_jobs)
    for job in module_jobs:
        module_landed = _wait_job_terminal(port, job.id)
        assert module_landed["status"] == "succeeded"
        assert module_landed["chain"] is True

    # Step 3: the batch's completion hook. Ingesting the last module response
    # already assembled responses/draft.response.json (runs_draft_units), so
    # the loop's first read is the run's first judgment and it takes no step.
    deadline = time.time() + 20.0
    batch_continuations: list[dict] = []
    while time.time() < deadline and not batch_continuations:
        status, jobs_body = _req(port, "GET", f"/v1/jobs?topic={tdu.TID}")
        assert status == 200
        batch_continuations = [
            job
            for job in jobs_body["jobs"]
            if job.get("continuation") is not None and job["id"] != skeleton_id
        ]
        if not batch_continuations:
            time.sleep(0.02)
    assert len(batch_continuations) == 1  # exactly one job of the batch records it
    batch_continuation = batch_continuations[0]["continuation"]
    assert batch_continuation["after"] == "batch"
    assert batch_continuation["steps"] == []
    assert batch_continuation["stop"] == {"kind": "approve", "stage": "draft"}

    # The run status names the batch's record (the latest), not the skeleton's.
    status, run_body = _req(port, "GET", f"/v1/runs/{tdu.TID}")
    assert status == 200
    assert run_body["continuation"] == {
        "job_id": batch_continuations[0]["id"],
        "stage": "draft",
        "provider": "fake",
        **batch_continuation,
    }

    # Nothing was approved, and no further job was enqueued past the batch.
    draft_status = next(s for s in run_body["stages"] if s["stage"] == "draft")
    assert draft_status["approved"] is False
    assert draft_status["response_ingested"] is True
    assert run_body["next_action"]["action"] == "approve"
    _no_new_job_appears(
        port, context, tdu.TID, before_count=1 + len(tdu.MODULE_ORDER)
    )

    from education_pipeline import RunStore

    assert RunStore(tmp_path).response_path(tdu.TID, "draft").exists()


def test_continue_chain_carries_a_ready_module_batch_to_approve(tmp_path, server_with_context):
    """From a skeleton that is already ingested (module prompts already on
    disk -- the T24 batch-fan-out seed, ``tdu._run_with_skeleton_ingested``),
    one ``POST .../continue`` plus polling alone carries the whole module
    batch to completion and the run to ``approve``, with no further request:
    the working half of decision 9's parity goal."""

    port, context = server_with_context
    register_runner(ChainFakeRunner())
    tdu._run_with_skeleton_ingested(tmp_path)

    status, body = _continue(port, tdu.TID)
    assert status == 200
    assert body["stop"]["kind"] == "started"
    assert body["stop"]["count"] == len(tdu.MODULE_ORDER)

    batch_jobs = context.store.list(tdu.TID)
    assert len(batch_jobs) == len(tdu.MODULE_ORDER)
    batch_id = batch_jobs[0].batch_id
    assert batch_id is not None
    assert all(job.batch_id == batch_id for job in batch_jobs)

    for job in batch_jobs:
        landed = _wait_job_terminal(port, job.id)
        assert landed["status"] == "succeeded"
        assert landed["chain"] is True

    # Exactly one job of the batch carries the batch's continuation, and only
    # once every module job is terminal (all landed "succeeded" above).
    deadline = time.time() + 20.0
    with_continuation = []
    while time.time() < deadline and not with_continuation:
        status, jobs_body = _req(port, "GET", f"/v1/jobs?topic={tdu.TID}")
        assert status == 200
        with_continuation = [
            job for job in jobs_body["jobs"] if job.get("continuation") is not None
        ]
        if not with_continuation:
            time.sleep(0.02)
    assert len(with_continuation) == 1
    continuation = with_continuation[0]["continuation"]
    assert continuation["after"] == "batch"
    assert continuation["stop"] == {"kind": "approve", "stage": "draft"}

    status, run_body = _req(port, "GET", f"/v1/runs/{tdu.TID}")
    assert status == 200
    assert run_body["continuation"]["job_id"] == with_continuation[0]["id"]

    draft_status = next(s for s in run_body["stages"] if s["stage"] == "draft")
    assert draft_status["approved"] is False
    assert draft_status["response_ingested"] is True

    from education_pipeline import RunStore

    runs = RunStore(tmp_path)
    assert runs.response_path(tdu.TID, "draft").exists()


# ---------------------------------------------------------------------------
# 5. Batch with one failing module: the batch continuation is failed, and no
#    further job is enqueued.
# ---------------------------------------------------------------------------


def test_continue_chain_reports_one_of_n_module_jobs_failed(tmp_path, server_with_context):
    port, context = server_with_context
    failing_module = tdu.MODULE_ORDER[0]
    register_runner(ChainFakeRunner(fail_modules=frozenset({failing_module})))
    tdu._run_with_skeleton_ingested(tmp_path)

    status, body = _continue(port, tdu.TID)
    assert status == 200
    assert body["stop"]["count"] == len(tdu.MODULE_ORDER)

    batch_jobs = context.store.list(tdu.TID)
    assert len(batch_jobs) == len(tdu.MODULE_ORDER)
    for job in batch_jobs:
        _wait_job_terminal(port, job.id)

    deadline = time.time() + 20.0
    with_continuation = []
    while time.time() < deadline and not with_continuation:
        status, jobs_body = _req(port, "GET", f"/v1/jobs?topic={tdu.TID}")
        assert status == 200
        with_continuation = [
            job for job in jobs_body["jobs"] if job.get("continuation") is not None
        ]
        if not with_continuation:
            time.sleep(0.02)
    assert len(with_continuation) == 1
    continuation = with_continuation[0]["continuation"]
    assert continuation["stop"]["kind"] == "failed"
    assert continuation["stop"]["message"] == (
        f"1 of {len(tdu.MODULE_ORDER)} module jobs failed: {failing_module}"
    )

    # No further job (e.g. a retry, or a stray assemble/advance job) appears.
    _no_new_job_appears(port, context, tdu.TID, before_count=len(tdu.MODULE_ORDER))


# ---------------------------------------------------------------------------
# 6. run_status_payload.continuation is null with no chained job at all --
#    both for a topic with no jobs, and for one with only an un-chained job.
# ---------------------------------------------------------------------------


def test_run_status_payload_continuation_is_null_with_no_jobs(server_with_context):
    port, context = server_with_context
    status, body = _req(port, "GET", "/v1/runs/t")
    assert status == 200
    assert "continuation" in body
    assert body["continuation"] is None


def test_run_status_payload_continuation_is_null_after_only_a_plain_job(
    tmp_path, monkeypatch
):
    srv, worker, context = _start_server(tmp_path, monkeypatch)
    try:
        _write_topic(tmp_path, "no-chain-topic")
        context.runs.create_run("no-chain-topic", content_contract=ContentContract.legacy_markdown())
        context.runs.advance("no-chain-topic")

        status, job_body = _req(
            srv.server_port,
            "POST",
            "/v1/jobs",
            body={"topic_id": "no-chain-topic", "stage": "spec"},
        )
        assert status == 200
        _wait_job_terminal(srv.server_port, job_body["id"])
        time.sleep(0.3)

        status, run_body = _req(srv.server_port, "GET", "/v1/runs/no-chain-topic")
        assert status == 200
        assert run_body["continuation"] is None
    finally:
        worker.stop()
        srv.shutdown()
