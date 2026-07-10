"""Unit tests for the write-action payload builders (no HTTP layer)."""

import pytest

from education_pipeline.config import ConfigError
from education_pipeline.daemon import write_api
from education_pipeline.daemon.jobs import JobStore
from education_pipeline.daemon.read_api import NotFoundError
from education_pipeline.runs import RunStore, SUPPORTED_STAGES


def _workspace(tmp_path):
    (tmp_path / "topics").mkdir()
    (tmp_path / "topics" / "t.toml").write_text(
        'schema_version = 1\nid = "t"\ntitle = "Test Topic"\n', encoding="utf-8"
    )
    return RunStore(tmp_path), JobStore(tmp_path)


def test_advance_starts_run_and_full_loop_reaches_export(tmp_path):
    runs, jobs = _workspace(tmp_path)
    for stage in SUPPORTED_STAGES:
        result = write_api.advance_run(runs, jobs, "t")
        assert result["performed"] == "write_prompt"
        assert result["status"]["next_action"]["action"] == "save_response"
        assert result["status"]["next_action"]["stage"] == stage
        ingest = write_api.ingest_response(runs, jobs, "t", stage, f"{stage} body")
        assert ingest["response_path"] == f"responses/{stage}.response.md"
        assert ingest["status"]["next_action"]["action"] == "approve"
        approved = write_api.approve_stage(runs, jobs, "t", stage)
        assert approved["approved_path"] == f"approved/{stage}.md"
    final = write_api.advance_run(runs, jobs, "t")
    assert final["performed"] == "finalize"
    assert final["status"]["finalized"] is True
    assert final["status"]["next_action"]["action"] == "done"
    export = write_api.export_run(runs, "t", format="html")
    assert export == {"topic_id": "t", "format": "html", "export_path": "final/guide.html"}


def test_advance_is_a_noop_at_human_steps(tmp_path):
    runs, jobs = _workspace(tmp_path)
    write_api.advance_run(runs, jobs, "t")  # writes the spec prompt
    again = write_api.advance_run(runs, jobs, "t")
    assert again["performed"] is None
    assert again["status"]["next_action"]["action"] == "save_response"


def test_ingest_conflict_and_force(tmp_path):
    runs, jobs = _workspace(tmp_path)
    write_api.advance_run(runs, jobs, "t")
    write_api.ingest_response(runs, jobs, "t", "spec", "first")
    with pytest.raises(write_api.ConflictError) as exc:
        write_api.ingest_response(runs, jobs, "t", "spec", "second")
    assert exc.value.code == "already_exists"
    write_api.ingest_response(runs, jobs, "t", "spec", "second", force=True)
    assert runs.stage_paths("t", "spec").response_path.read_text(encoding="utf-8") == "second"


def test_ingest_empty_text_is_config_error(tmp_path):
    runs, jobs = _workspace(tmp_path)
    write_api.advance_run(runs, jobs, "t")
    with pytest.raises(ConfigError):
        write_api.ingest_response(runs, jobs, "t", "spec", "   \n")


def test_run_actions_404_without_a_run(tmp_path):
    runs, jobs = _workspace(tmp_path)
    with pytest.raises(NotFoundError):
        write_api.ingest_response(runs, jobs, "t", "spec", "x")
    with pytest.raises(NotFoundError):
        write_api.approve_stage(runs, jobs, "t", "spec")
    with pytest.raises(NotFoundError):
        write_api.finalize_run(runs, jobs, "t")
    with pytest.raises(NotFoundError):
        write_api.export_run(runs, "t")


def test_approve_not_ready_then_already_exists(tmp_path):
    runs, jobs = _workspace(tmp_path)
    write_api.advance_run(runs, jobs, "t")
    with pytest.raises(write_api.ConflictError) as exc:
        write_api.approve_stage(runs, jobs, "t", "spec")
    assert exc.value.code == "not_ready"
    write_api.ingest_response(runs, jobs, "t", "spec", "body")
    write_api.approve_stage(runs, jobs, "t", "spec")
    with pytest.raises(write_api.ConflictError) as exc:
        write_api.approve_stage(runs, jobs, "t", "spec")
    assert exc.value.code == "already_exists"
    write_api.approve_stage(runs, jobs, "t", "spec", overwrite=True)


def test_finalize_not_ready_before_repair_approved(tmp_path):
    runs, jobs = _workspace(tmp_path)
    write_api.advance_run(runs, jobs, "t")
    with pytest.raises(write_api.ConflictError) as exc:
        write_api.finalize_run(runs, jobs, "t")
    assert exc.value.code == "not_ready"


def test_export_not_ready_bad_format_and_conflict(tmp_path):
    runs, jobs = _workspace(tmp_path)
    write_api.advance_run(runs, jobs, "t")
    with pytest.raises(ConfigError):
        write_api.export_run(runs, "t", format="docx")
    with pytest.raises(write_api.ConflictError) as exc:
        write_api.export_run(runs, "t", format="html")
    assert exc.value.code == "not_ready"


def test_job_active_blocks_run_mutations_but_not_export(tmp_path):
    runs, jobs = _workspace(tmp_path)
    # Drive the run to finalized so export is possible.
    for stage in SUPPORTED_STAGES:
        write_api.advance_run(runs, jobs, "t")
        write_api.ingest_response(runs, jobs, "t", stage, f"{stage} body")
        write_api.approve_stage(runs, jobs, "t", stage)
    write_api.advance_run(runs, jobs, "t")  # finalize

    job = jobs.create("t", "spec", "fake", None, None)
    jobs.save(job)  # queued == active
    blocked = (
        lambda: write_api.advance_run(runs, jobs, "t"),
        lambda: write_api.ingest_response(runs, jobs, "t", "spec", "x", force=True),
        lambda: write_api.approve_stage(runs, jobs, "t", "spec", overwrite=True),
        lambda: write_api.finalize_run(runs, jobs, "t", overwrite=True),
    )
    for call in blocked:
        with pytest.raises(write_api.ConflictError) as exc:
            call()
        assert exc.value.code == "job_active"
    # export is exempt: it only reads final/ and writes a file the worker never touches
    assert write_api.export_run(runs, "t", format="html")["export_path"] == "final/guide.html"

    job.status = "canceled"
    jobs.save(job)
    assert write_api.advance_run(runs, jobs, "t")["performed"] is None
