"""Unit tests for the write-action payload builders (no HTTP layer)."""

import json
from pathlib import Path

import pytest

from education_pipeline.config import ConfigError, parse_model_catalog, parse_model_plan
from education_pipeline.daemon import StaticConfigSource, write_api
from education_pipeline.daemon.jobs import JobStore
from education_pipeline.daemon.read_api import NotFoundError
from education_pipeline.runs import ContentContract, RunStore, SUPPORTED_STAGES

FIXTURE = Path(__file__).parent / "fixtures" / "guides" / "feedback-loops.guide.json"


def _config_source():
    catalog = parse_model_catalog(
        {
            "providers": [
                {"id": "manual"},
                {"id": "fake", "models": [{"id": "m"}]},
            ]
        }
    )
    plan = parse_model_plan({"provider": "manual", "stages": {}}, catalog)
    return StaticConfigSource(catalog, plan)


def test_update_global_plan_with_correct_sha_updates_plan_and_returns_new_sha():
    config = _config_source()
    base_sha256 = config.plan_sha256()
    result = write_api.update_global_plan(
        config,
        {
            "base_sha256": base_sha256,
            "provider": "fake",
            "stages": {"draft": {"model": "m"}},
        },
    )
    assert result["provider"] == "fake"
    assert result["plan_sha256"] == config.plan_sha256()
    assert result["plan_sha256"] != base_sha256
    stages = {s["stage"]: s for s in result["stages"]}
    assert stages["draft"]["model"] == "m"
    assert config.plan.provider == "fake"


def test_update_global_plan_with_unknown_model_raises_config_error_and_leaves_plan_untouched():
    config = _config_source()
    base_sha256 = config.plan_sha256()
    with pytest.raises(ConfigError):
        write_api.update_global_plan(
            config,
            {
                "base_sha256": base_sha256,
                "provider": "fake",
                "stages": {"draft": {"model": "does-not-exist"}},
            },
        )
    assert config.plan.provider == "manual"
    assert config.plan_sha256() == base_sha256


def _workspace(tmp_path, *, create_legacy_run: bool = True):
    (tmp_path / "topics").mkdir()
    (tmp_path / "topics" / "t.toml").write_text(
        'schema_version = 1\nid = "t"\ntitle = "Test Topic"\n', encoding="utf-8"
    )
    runs = RunStore(tmp_path)
    # Explicit legacy: write-api suite verifies the Markdown compatibility path.
    if create_legacy_run:
        runs.create_run("t", content_contract=ContentContract.legacy_markdown())
    return runs, JobStore(tmp_path)


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
    runs, jobs = _workspace(tmp_path, create_legacy_run=False)
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


def test_import_topic_derives_id_and_refuses_clobber(tmp_path):
    from education_pipeline.workspace import TopicStore

    topics = TopicStore(tmp_path)
    toml = 'schema_version = 1\nid = "n1"\ntitle = "New One"\n'
    assert write_api.import_topic(topics, toml) == {"id": "n1", "title": "New One"}
    with pytest.raises(write_api.ConflictError) as exc:
        write_api.import_topic(topics, toml)
    assert exc.value.code == "already_exists"
    assert write_api.import_topic(topics, toml, overwrite=True)["id"] == "n1"


def test_import_topic_rejects_bad_toml_and_missing_id(tmp_path):
    from education_pipeline.workspace import TopicStore

    topics = TopicStore(tmp_path)
    with pytest.raises(ConfigError):
        write_api.import_topic(topics, "not = [valid")
    with pytest.raises(ConfigError):
        write_api.import_topic(topics, 'schema_version = 1\ntitle = "No Id"\n')


def test_import_profile(tmp_path):
    from education_pipeline.workspace import ProfileStore

    profiles = ProfileStore(tmp_path)
    toml = 'schema_version = 1\nid = "p1"\ntarget_learner = "team cohort"\n'
    assert write_api.import_profile(profiles, toml) == {"id": "p1"}
    with pytest.raises(write_api.ConflictError) as exc:
        write_api.import_profile(profiles, toml)
    assert exc.value.code == "already_exists"


def test_attach_profile_defaults_to_overwrite(tmp_path):
    from education_pipeline.workspace import ProfileStore

    profiles = ProfileStore(tmp_path)
    write_api.import_profile(
        profiles, 'schema_version = 1\nid = "p1"\ntarget_learner = "team cohort"\n'
    )
    result = write_api.attach_profile(profiles, "t", "p1")
    assert result == {"profile_id": "p1", "topic_id": "t", "snapshot_path": "inputs/profile.toml"}
    # re-attach refreshes the snapshot without an explicit flag
    assert write_api.attach_profile(profiles, "t", "p1")["snapshot_path"] == "inputs/profile.toml"


def test_attach_unknown_profile_is_404(tmp_path):
    from education_pipeline.workspace import ProfileStore

    with pytest.raises(NotFoundError):
        write_api.attach_profile(ProfileStore(tmp_path), "t", "ghost")


def test_guide_status_stage_content_and_validate_payloads(tmp_path):
    runs, jobs = _workspace(tmp_path, create_legacy_run=False)
    runs.create_run("t")
    draft = runs.stage_paths("t", "draft")
    draft.approved_path.write_bytes(FIXTURE.read_bytes())

    before = write_api.read_api.run_status_payload(runs, "t")
    assert before["content_contract"] == {"kind": "interactive_guide", "schema_version": "1.0"}
    assert before["validations"]["draft"]["state"] == "missing"
    assert write_api.read_api.stage_content(runs, "t", "draft")["content_type"].endswith("version=1.0")

    result = write_api.validate_run(runs, jobs, "t", "draft")
    assert result["state"] == "current"
    assert result["report"]["guide_sha256"]
    assert result["status"]["validations"]["draft"]["state"] == "current"


def test_waiver_requires_current_hash_reason_and_waivable_finding(tmp_path):
    runs, jobs = _workspace(tmp_path, create_legacy_run=False)
    runs.create_run("t")
    guide = json.loads(FIXTURE.read_text(encoding="utf-8"))
    guide["modules"][0]["sections"][0]["blocks"][0]["markdown"] += " TODO"
    draft = runs.stage_paths("t", "draft")
    draft.approved_path.write_text(json.dumps(guide), encoding="utf-8")
    report = write_api.validate_run(runs, jobs, "t", "draft")["report"]
    finding = next(item for item in report["findings"] if item["waivable"])

    with pytest.raises(write_api.ConflictError):
        write_api.create_waiver(runs, "t", "draft", finding["id"], "0" * 64, "reason")
    with pytest.raises(ConfigError):
        write_api.create_waiver(runs, "t", "draft", finding["id"], report["guide_sha256"], "  ")
    result = write_api.create_waiver(
        runs, "t", "draft", finding["id"], report["guide_sha256"], "Accepted example"
    )
    assert result["waivers"]["waivers"][0]["finding_id"] == finding["id"]
    persisted = write_api.read_api.waivers_payload(runs, "t", "draft")
    assert persisted["state"] == "current"
    assert persisted["waivers"]["waivers"][0]["reason"] == "Accepted example"

    guide["modules"][0]["sections"][0]["blocks"][0]["markdown"] += " <b>unsafe</b>"
    draft.approved_path.write_text(json.dumps(guide), encoding="utf-8")
    report = write_api.validate_run(runs, jobs, "t", "draft")["report"]
    assert write_api.read_api.waivers_payload(runs, "t", "draft")["state"] == "stale"
    nonwaivable = next(item for item in report["findings"] if not item["waivable"])
    with pytest.raises(write_api.UnprocessableError):
        write_api.create_waiver(
            runs, "t", "draft", nonwaivable["id"], report["guide_sha256"], "reason"
        )
