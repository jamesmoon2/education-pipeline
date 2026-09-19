"""Failing (red) tests for thread T32 "Daemon endpoint and cockpit handoff".

Design: docs/superpowers/plans/2026-09-18-phase-3-headless.md (T32 row,
decisions 1, 2, 5, 8). ``POST /v1/runs/{id}/continue`` does not exist yet, so
every test here either 404s on the route (``self._error(404, "not_found",
"unknown path")`` -- the do_POST fallback) or fails an assertion once a route
answers something other than what the contract requires. Nothing here builds
the route; a different subagent makes these pass.

Reuses ``tests/test_server.py``'s server harness (``_start_server``, ``_req``,
``FakeRunner``) and ``tests/test_draft_units.py``'s guide-run seed helpers
(``tdu``), exactly as ``test_server.py`` itself does for the T24 draft-unit
route tests.
"""

from __future__ import annotations

import dataclasses
import time
from pathlib import Path

import pytest

import test_draft_units as tdu
from test_server import FakeRunner, _req, _start_server, server_with_context  # noqa: F401 (fixture)

from education_pipeline import ContentContract, parse_model_catalog, parse_model_plan
from education_pipeline.daemon import StaticConfigSource
from education_pipeline.daemon.jobs import Job, new_job_id


def _continue(port: int, topic_id: str):
    return _req(port, "POST", f"/v1/runs/{topic_id}/continue")


def _write_topic(tmp_path: Path, topic_id: str, title: str = "Topic") -> None:
    topics_dir = tmp_path / "topics"
    topics_dir.mkdir(parents=True, exist_ok=True)
    (topics_dir / f"{topic_id}.toml").write_text(
        f'schema_version = 1\nid = "{topic_id}"\ntitle = "{title}"\n', encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# 1. Unknown topic -> 404, same envelope as other run routes.
# ---------------------------------------------------------------------------


def test_continue_unknown_topic_is_404(server_with_context):
    port, _context = server_with_context
    status, body = _continue(port, "ghost")
    assert status == 404
    assert body["error"]["code"] == "not_found"


# ---------------------------------------------------------------------------
# 2. Archived course -> same status/code as POST /v1/jobs
#    (test_archived_course_blocks_writes_over_http pins that as 409/archived_course).
# ---------------------------------------------------------------------------


def test_continue_refuses_archived_course(server_with_context):
    port, context = server_with_context
    status, _ = _req(port, "POST", "/v1/runs/t/archive", body={})
    assert status == 200
    status, body = _continue(port, "t")
    assert status == 409
    assert body["error"]["code"] == "archived_course"


# ---------------------------------------------------------------------------
# 3. An active job for the topic -> job_conflict, before any step runs.
#    Decision 8: "refuses up front on ... an active job for the topic (same
#    catalog codes as POST /v1/jobs)" -- any active job for the topic, not
#    only one for whatever stage the loop would touch first (the seeded job
#    below is for "spec"; "t"'s outstanding stage is "draft").
# ---------------------------------------------------------------------------


def test_continue_refuses_active_job_before_any_step_runs(server_with_context):
    port, context = server_with_context
    before_status, before_body = _req(port, "GET", "/v1/runs/t")
    assert before_status == 200

    context.store.save(
        Job(
            id=new_job_id(),
            topic_id="t",
            stage="spec",
            provider="fake",
            model="m",
            effort=None,
            status="queued",
        )
    )

    status, body = _continue(port, "t")
    assert status == 409
    assert body["error"]["code"] == "job_conflict"

    # No step ran: the spec prompt (never written by the "t" fixture, which
    # only pre-writes the draft prompt) still doesn't exist, and the run's
    # reported status is unchanged.
    assert not context.runs.stage_paths("t", "spec").prompt_path.exists()
    after_status, after_body = _req(port, "GET", "/v1/runs/t")
    assert after_status == 200
    assert after_body["next_action"] == before_body["next_action"]


# ---------------------------------------------------------------------------
# 4. write_prompt for a manual-provider stage -> advance once, stop "manual".
# ---------------------------------------------------------------------------


def test_continue_stops_for_a_manual_provider_stage(tmp_path, monkeypatch):
    catalog = parse_model_catalog(
        {
            "providers": [
                {"id": "manual"},
                {"id": "fake", "models": [{"id": "m"}]},
            ]
        }
    )
    plan = parse_model_plan(
        {"provider": "fake", "stages": {"spec": {"provider": "manual"}}}, catalog
    )
    srv, worker, context = _start_server(tmp_path, monkeypatch, catalog=catalog, plan=plan)
    try:
        _write_topic(tmp_path, "manual-stage")
        context.runs.create_run("manual-stage", content_contract=ContentContract.legacy_markdown())

        status, body = _continue(srv.server_port, "manual-stage")

        assert status == 200
        assert body["steps"] == [{"kind": "advance", "stage": "spec"}]
        assert body["stop"] == {"kind": "manual", "stage": "spec"}
        assert context.runs.stage_paths("manual-stage", "spec").prompt_path.exists()
        assert body["status"]["next_action"]["action"] == "save_response"
        assert body["status"]["next_action"]["stage"] == "spec"
    finally:
        worker.stop()
        srv.shutdown()


# ---------------------------------------------------------------------------
# 5. write_prompt -> save_response for a fake-provider stage -> non-blocking
#    job start; exactly one job created; the loop did not wait for it.
# ---------------------------------------------------------------------------


def test_continue_starts_a_fake_provider_job_without_waiting(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_DELAY", "5")
    srv, worker, context = _start_server(tmp_path, monkeypatch)
    try:
        _write_topic(tmp_path, "job-topic")
        context.runs.create_run("job-topic", content_contract=ContentContract.legacy_markdown())

        status, body = _continue(srv.server_port, "job-topic")

        assert status == 200
        assert body["steps"] == [
            {"kind": "advance", "stage": "spec"},
            {"kind": "job", "stage": "spec", "provider": "fake"},
        ]
        assert body["stop"] == {"kind": "started", "stage": "spec", "provider": "fake"}
        assert "count" not in body["stop"]

        jobs = context.store.list("job-topic")
        assert len(jobs) == 1
        # FAKE_DELAY=5 means the fake provider subprocess is still asleep;
        # the route must have returned before it finished (no blocking wait).
        assert jobs[0].status not in {"succeeded", "failed", "canceled", "interrupted"}
    finally:
        worker.stop()
        srv.shutdown()


# ---------------------------------------------------------------------------
# 6. approve -> steps == [], stop "approve"; the stage stays unapproved.
# ---------------------------------------------------------------------------


def test_continue_stops_at_approve_without_approving(tmp_path, monkeypatch):
    srv, worker, context = _start_server(tmp_path, monkeypatch)
    try:
        _write_topic(tmp_path, "appr")
        context.runs.create_run("appr", content_contract=ContentContract.legacy_markdown())
        context.runs.advance("appr")  # writes the spec prompt
        context.runs.ingest_response("appr", "spec", "SPEC BODY TEXT")

        status, body = _continue(srv.server_port, "appr")

        assert status == 200
        assert body["steps"] == []
        assert body["stop"] == {"kind": "approve", "stage": "spec"}

        spec_status = next(
            s for s in context.runs.run_status("appr").stages if s.stage == "spec"
        )
        assert spec_status.approved is False
    finally:
        worker.stop()
        srv.shutdown()


# ---------------------------------------------------------------------------
# 7. Guide-v1 draft fan-out: stop.count == module count == steps[-1].count.
# ---------------------------------------------------------------------------


def test_continue_reports_the_draft_fan_out_batch_count(tmp_path, server_with_context):
    port, context = server_with_context
    tdu._run_with_skeleton_ingested(tmp_path)

    status, body = _continue(port, tdu.TID)

    assert status == 200
    assert body["stop"]["kind"] == "started"
    assert body["stop"]["count"] == len(tdu.MODULE_ORDER)
    assert body["steps"][-1]["count"] == len(tdu.MODULE_ORDER)


# ---------------------------------------------------------------------------
# 8. Provider resolution pin.
# ---------------------------------------------------------------------------


def test_continue_stops_manual_while_jobs_route_admits_and_later_fails_it(tmp_path, monkeypatch):
    """Pins *today's* POST /v1/jobs behaviour for an explicit manual-provider
    stage (it admits the job synchronously and the job fails once the worker
    picks it up) against the new route, which must never start that job at
    all -- it stops with "manual" before any job exists."""

    catalog = parse_model_catalog(
        {
            "providers": [
                {"id": "manual"},
                {"id": "fake", "models": [{"id": "m"}]},
            ]
        }
    )
    plan = parse_model_plan(
        {"provider": "fake", "stages": {"spec": {"provider": "manual"}}}, catalog
    )
    srv, worker, context = _start_server(tmp_path, monkeypatch, catalog=catalog, plan=plan)
    try:
        _write_topic(tmp_path, "pin")
        context.runs.create_run("pin", content_contract=ContentContract.legacy_markdown())
        context.runs.advance("pin")  # writes the spec prompt

        status, job = _req(
            srv.server_port, "POST", "/v1/jobs", body={"topic_id": "pin", "stage": "spec"}
        )
        assert status == 200  # today's behaviour: admitted, not refused
        current = job
        for _ in range(200):
            status, current = _req(srv.server_port, "GET", f"/v1/jobs/{job['id']}")
            if current["status"] in {"succeeded", "failed", "canceled", "interrupted"}:
                break
            time.sleep(0.02)
        assert current["status"] == "failed"
        assert "manual provider is not executable" in current["error"]

        status, body = _continue(srv.server_port, "pin")
        assert status == 200
        assert body["stop"]["kind"] == "manual"
        # Only the /v1/jobs job above exists; continue must not have started
        # (and failed) a second one.
        assert len(context.store.list("pin")) == 1
    finally:
        worker.stop()
        srv.shutdown()


def test_continue_and_jobs_route_agree_on_a_null_provider_row(tmp_path, monkeypatch):
    """decision 5's INVARIANT: a stage row with no provider of its own is NOT
    manual -- both routes fall back to the plan default ("fake" here)."""

    srv, worker, context = _start_server(tmp_path, monkeypatch)
    try:
        for topic_id in ("fallback-jobs", "fallback-continue"):
            _write_topic(tmp_path, topic_id)
            context.runs.create_run(topic_id, content_contract=ContentContract.legacy_markdown())
            context.runs.advance(topic_id)  # writes the spec prompt

        catalog, plan = context.config.load()
        # A row with provider=None (never produced by parse_model_plan, which
        # always resolves the default at parse time) -- built directly to pin
        # the `row.provider or plan.provider` fallback itself.
        spec_row = dataclasses.replace(plan.stage("spec"), provider=None)
        none_plan = dataclasses.replace(plan, stages={**plan.stages, "spec": spec_row})
        context.config = StaticConfigSource(catalog, none_plan)

        status, job = _req(
            srv.server_port,
            "POST",
            "/v1/jobs",
            body={"topic_id": "fallback-jobs", "stage": "spec"},
        )
        assert status == 200
        assert job["provider"] == "fake"

        status, body = _continue(srv.server_port, "fallback-continue")
        assert status == 200
        assert body["stop"]["kind"] == "started"
        assert body["stop"]["provider"] == "fake"
    finally:
        worker.stop()
        srv.shutdown()


def test_server_module_resolves_provider_through_orchestrate_provider_for_stage(
    server_with_context, monkeypatch
):
    """Pin: education_pipeline.daemon.server must import ``provider_for_stage``
    by name from ``education_pipeline.orchestrate`` and call it from
    ``enqueue_stage`` -- so monkeypatching the name on the server module
    changes what a real POST /v1/jobs enqueue resolves to. Fails today with
    AttributeError: server.py has no such attribute yet."""

    port, context = server_with_context
    from education_pipeline.daemon import server as server_mod

    calls = []

    def fake_provider_for_stage(plan, stage):
        calls.append((plan, stage))
        return "fake"

    monkeypatch.setattr(server_mod, "provider_for_stage", fake_provider_for_stage)

    status, body = _req(port, "POST", "/v1/jobs", body={"topic_id": "t", "stage": "draft"})

    assert status == 200
    assert calls, "enqueue_stage must resolve the provider through orchestrate.provider_for_stage"


# ---------------------------------------------------------------------------
# 9. Route table doc lists the new endpoint.
# ---------------------------------------------------------------------------


def test_route_table_doc_lists_continue_endpoint():
    doc = (
        Path(__file__).parent.parent
        / "docs"
        / "superpowers"
        / "specs"
        / "2026-07-09-provider-run-daemon-design.md"
    )
    text = doc.read_text(encoding="utf-8")
    assert "POST /v1/runs/{id}/continue" in text
