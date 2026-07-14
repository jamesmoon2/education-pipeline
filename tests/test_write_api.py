"""Unit tests for the write-action payload builders (no HTTP layer)."""

import json
import threading
from pathlib import Path

import pytest

import test_runs

from education_pipeline.config import ConfigError, parse_model_catalog, parse_model_plan
from education_pipeline.daemon import StaticConfigSource, read_api, write_api
from education_pipeline.daemon.jobs import JobStore
from education_pipeline.daemon.read_api import NotFoundError
from education_pipeline.privacy import canonical_profile_toml_bytes, profile_to_dict
from education_pipeline.profiles import parse_learner_profile
from education_pipeline.runs import ContentContract, RunStore, SUPPORTED_STAGES
from education_pipeline.workspace import ProfileStore, _profile_lock

FIXTURE = Path(__file__).parent / "fixtures" / "guides" / "feedback-loops.guide.json"


@pytest.fixture
def waiver_env(tmp_path):
    """A topic driven all the way to finalize-ready with a real, waivable
    blocking finding on the ``final`` report -- the shape Task 5's DELETE
    waiver route (and this task's create_waiver test) both need."""

    topic_id = "systems-thinking"
    runs = test_runs._create_guide_run(tmp_path, topic_id)
    leak_json = test_runs._prompt_leak_guide_json()
    test_runs._drive_guide_to_finalize_ready(
        runs, topic_id, draft_body=leak_json, repair_body=leak_json
    )
    finding_id = test_runs._first_waivable_blocking_finding_id(runs, topic_id, "final")
    return runs, topic_id, finding_id


def _report_sha(runs, topic_id):
    report = json.loads(runs.final_report_path(topic_id).read_text(encoding="utf-8"))
    return report["guide_sha256"]


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


def test_update_global_plan_rejects_unknown_stage_key_instead_of_silently_dropping_it():
    """PUT /v1/config/plan is the strict write path: a misspelled stage key
    (e.g. 'modle' instead of 'model') must raise ConfigError, not silently
    discard the key and return 200."""

    config = _config_source()
    base_sha256 = config.plan_sha256()
    with pytest.raises(ConfigError, match="unknown stage-override key"):
        write_api.update_global_plan(
            config,
            {
                "base_sha256": base_sha256,
                "provider": "fake",
                "stages": {"draft": {"modle": "opus"}},
            },
        )
    assert config.plan.provider == "manual"
    assert config.plan_sha256() == base_sha256


def test_update_run_plan_sets_override_and_source_and_command_change(tmp_path):
    config = _config_source()
    runs, _jobs = _workspace(tmp_path)
    result = write_api.update_run_plan(
        runs, config, "t", {"overrides": {"draft": {"model": "m"}}}
    )
    stages = {s["stage"]: s for s in result["stages"]}
    assert stages["draft"]["source"] == "override"
    assert stages["draft"]["model"] == "m"
    other_stages = [s for name, s in stages.items() if name != "draft"]
    assert all(s["source"] == "default" for s in other_stages)


def test_update_run_plan_clear_override_with_null_reverts_to_default(tmp_path):
    config = _config_source()
    runs, _jobs = _workspace(tmp_path)
    write_api.update_run_plan(runs, config, "t", {"overrides": {"draft": {"model": "m"}}})
    result = write_api.update_run_plan(runs, config, "t", {"overrides": {"draft": None}})
    stages = {s["stage"]: s for s in result["stages"]}
    assert stages["draft"]["source"] == "default"


def test_update_run_plan_invalid_model_is_400_and_stored_overrides_untouched(tmp_path):
    config = _config_source()
    runs, _jobs = _workspace(tmp_path)
    write_api.update_run_plan(
        runs, config, "t", {"overrides": {"draft": {"provider": "fake", "model": "m"}}}
    )
    before = runs.read_plan_overrides("t")
    with pytest.raises(ConfigError):
        write_api.update_run_plan(
            runs,
            config,
            "t",
            {"overrides": {"draft": {"provider": "fake", "model": "does-not-exist"}}},
        )
    assert runs.read_plan_overrides("t") == before


def test_update_run_plan_unknown_override_key_is_config_error_and_not_persisted(tmp_path):
    config = _config_source()
    runs, _jobs = _workspace(tmp_path)
    before = runs.read_plan_overrides("t")
    with pytest.raises(ConfigError):
        write_api.update_run_plan(
            runs, config, "t", {"overrides": {"draft": {"modle": "m"}}}
        )
    assert runs.read_plan_overrides("t") == before


def test_update_run_plan_missing_or_bad_overrides_field_is_config_error(tmp_path):
    config = _config_source()
    runs, _jobs = _workspace(tmp_path)
    with pytest.raises(ConfigError):
        write_api.update_run_plan(runs, config, "t", {})
    with pytest.raises(ConfigError):
        write_api.update_run_plan(runs, config, "t", {"overrides": "not-a-dict"})


def test_update_run_plan_unknown_topic_is_404(tmp_path):
    config = _config_source()
    runs = RunStore(tmp_path)
    with pytest.raises(NotFoundError):
        write_api.update_run_plan(runs, config, "nope", {"overrides": {}})


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


def test_ingest_response_records_manual_provenance_entry(tmp_path):
    runs, jobs = _workspace(tmp_path)
    write_api.advance_run(runs, jobs, "t")
    write_api.ingest_response(runs, jobs, "t", "spec", "manual body")
    entries = runs.read_manifest("t")["stage_provenance"]
    assert len(entries) == 1
    entry = entries[0]
    assert entry["stage"] == "spec"
    assert entry["provider"] == "manual"
    assert entry["model"] is None
    assert entry["effort"] is None
    assert entry["source"] == "manual"
    assert "recorded_at" in entry


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


def test_create_topic_from_structured_fields(tmp_path):
    from education_pipeline.workspace import TopicStore

    topics = TopicStore(tmp_path)
    body = {
        "id": "n2",
        "title": "New Two",
        "brief": "A short brief.",
        "audience": "engineers",
        "goals": ["explain X", "explain Y"],
    }

    result = write_api.create_topic(topics, body)

    assert result == {"id": "n2", "title": "New Two"}
    saved = topics.load_topic("n2")
    assert saved.brief == "A short brief."
    assert saved.audience == "engineers"
    assert saved.goals == ("explain X", "explain Y")


def test_create_topic_duplicate_id_conflicts_then_overwrite(tmp_path):
    from education_pipeline.workspace import TopicStore

    topics = TopicStore(tmp_path)
    body = {"id": "n3", "title": "New Three"}
    assert write_api.create_topic(topics, body) == {"id": "n3", "title": "New Three"}

    with pytest.raises(write_api.ConflictError) as exc:
        write_api.create_topic(topics, body)
    assert exc.value.code == "already_exists"

    body["title"] = "New Three Updated"
    result = write_api.create_topic(topics, body, overwrite=True)
    assert result == {"id": "n3", "title": "New Three Updated"}
    assert topics.load_topic("n3").title == "New Three Updated"


def test_create_topic_requires_non_empty_id_and_title(tmp_path):
    from education_pipeline.workspace import TopicStore

    topics = TopicStore(tmp_path)
    with pytest.raises(ConfigError):
        write_api.create_topic(topics, {"title": "No Id"})
    with pytest.raises(ConfigError):
        write_api.create_topic(topics, {"id": "no-title"})
    with pytest.raises(ConfigError):
        write_api.create_topic(topics, {"id": "  ", "title": "Blank Id"})
    with pytest.raises(ConfigError):
        write_api.create_topic(topics, {"id": "bad-goals", "title": "Bad Goals", "goals": ["ok", ""]})


def test_import_profile(tmp_path):
    from education_pipeline.workspace import ProfileStore

    profiles = ProfileStore(tmp_path)
    toml = 'schema_version = 1\nid = "p1"\ntarget_learner = "team cohort"\n'
    assert write_api.import_profile(profiles, toml) == {"id": "p1"}
    with pytest.raises(write_api.ConflictError) as exc:
        write_api.import_profile(profiles, toml)
    assert exc.value.code == "already_exists"


def test_import_profile_malformed_existing_target_is_safe_conflict(tmp_path):
    profiles = ProfileStore(tmp_path)
    planted_value = "PLANTED_MALFORMED_IMPORT_PRIVATE_VALUE"
    profiles.profiles_dir.mkdir(parents=True)
    profiles.profile_path("p1").write_text(
        f'id = "p1"\ntarget_learner = "{planted_value}',
        encoding="utf-8",
    )
    candidate = 'schema_version = 1\nid = "p1"\ntarget_learner = "new cohort"\n'

    with pytest.raises(write_api.ConflictError) as caught:
        write_api.import_profile(profiles, candidate)

    assert caught.value.code == "already_exists"
    assert caught.value.details == {"current_sha256": None}
    assert planted_value not in str(caught.value)
    assert planted_value not in json.dumps(caught.value.details)


def test_import_profile_target_created_before_locked_write_is_safe_conflict(
    tmp_path,
    monkeypatch,
):
    from education_pipeline import workspace

    profiles = ProfileStore(tmp_path)
    target = profiles.profile_path("p1")
    lock = _profile_lock(target)
    lock.acquire()
    lock_attempted = threading.Event()
    real_profile_lock = workspace._profile_lock

    def observed_profile_lock(path):
        lock_attempted.set()
        return real_profile_lock(path)

    monkeypatch.setattr(workspace, "_profile_lock", observed_profile_lock)
    candidate = 'schema_version = 1\nid = "p1"\ntarget_learner = "new cohort"\n'
    concurrent = 'schema_version = 1\nid = "p1"\ntarget_learner = "concurrent cohort"\n'
    results = []

    def import_candidate():
        try:
            results.append(write_api.import_profile(profiles, candidate))
        except BaseException as exc:
            results.append(exc)

    importer = threading.Thread(target=import_candidate)
    importer.start()
    try:
        assert lock_attempted.wait(timeout=5)
        profiles.profiles_dir.mkdir(parents=True, exist_ok=True)
        target.write_text(concurrent, encoding="utf-8")
    finally:
        lock.release()
    importer.join(timeout=5)

    assert not importer.is_alive()
    assert len(results) == 1
    assert isinstance(results[0], write_api.ConflictError)
    assert results[0].code == "already_exists"
    assert results[0].details == {
        "current_sha256": profiles.read_profile_record("p1").content_sha256
    }


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
    with pytest.raises(NotFoundError):
        write_api.attach_profile(ProfileStore(tmp_path), "t", "ghost")


def _structured_profile(profile_id="profile-one", target_learner="Synthetic cohort alpha"):
    return {
        "schema_version": 1,
        "id": profile_id,
        "target_learner": target_learner,
        "learning_goals": ["Trace synthetic systems"],
        "learning_preferences": {
            "preferred_modalities": ["diagrams"],
            "diagram_frequency": "frequent",
        },
        "privacy": {
            "private_by_default": True,
            "include_in_published_output": True,
            "publishable_summary": f"Designed for {target_learner}",
        },
        "metadata": {"nested": {"rank": 7, "enabled": True, "ratio": 1.5}},
    }


def test_profile_read_adapters_return_structured_payloads_counts_and_safe_warnings(tmp_path):
    profiles = ProfileStore(tmp_path)
    profile = _structured_profile()
    record = profiles.create_profile(profile["id"], profile)
    profiles.attach_profile_to_topic(profile["id"], "topic-a")
    profiles.attach_profile_to_topic(profile["id"], "topic-b")

    assert read_api.list_profiles(profiles) == {
        "profiles": [{"id": "profile-one", "attached_topic_count": 2}]
    }
    detail = read_api.get_profile(profiles, "profile-one")
    assert set(detail) == {
        "id",
        "parsed",
        "sensitivity",
        "content_sha256",
        "warnings",
        "attached_topic_count",
    }
    assert detail["parsed"] == profile_to_dict(record.profile)
    assert detail["content_sha256"] == record.content_sha256
    assert detail["attached_topic_count"] == 2
    assert detail["sensitivity"]["target_learner"] == "high"
    assert detail["sensitivity"]["metadata.*"] == "high"
    assert detail["warnings"]
    assert set(detail["warnings"][0]) == {"code", "field_path", "fingerprint"}
    assert detail["warnings"][0]["field_path"] == "target_learner"
    assert profile["target_learner"] not in json.dumps(detail["warnings"])


def test_profile_get_is_non_mutating_for_legacy_noncanonical_toml(tmp_path):
    profiles = ProfileStore(tmp_path)
    path = profiles.profile_path("legacy")
    path.parent.mkdir(parents=True)
    legacy_bytes = b'target_learner = "Synthetic legacy cohort"\nid = "legacy"\n'
    path.write_bytes(legacy_bytes)

    detail = read_api.get_profile(profiles, "legacy")

    assert detail["parsed"]["schema_version"] == 1
    assert path.read_bytes() == legacy_bytes


def test_profile_preview_uses_canonical_renderers_and_performs_no_write(tmp_path):
    profiles = ProfileStore(tmp_path)
    profile = _structured_profile("preview-only")

    result = read_api.preview_profile(profile)

    assert set(result) == {
        "parsed",
        "prompt_context",
        "publishable_summary",
        "sensitivity",
        "warnings",
    }
    assert result["parsed"] == profile_to_dict(parse_learner_profile(profile))
    assert "# Learner Profile Context" in result["prompt_context"]
    assert profile["target_learner"] in result["prompt_context"]
    assert result["publishable_summary"] == profile["privacy"]["publishable_summary"]
    assert result["warnings"][0]["field_path"] == "target_learner"
    assert not profiles.profiles_dir.exists()


def test_put_profile_create_then_update_returns_frozen_status_and_payload_shapes(tmp_path):
    profiles = ProfileStore(tmp_path)
    profile = _structured_profile()

    status, created = write_api.put_profile(
        profiles,
        profile["id"],
        {"profile": profile, "base_sha256": None},
    )
    assert status == 201
    assert created == read_api.get_profile(profiles, profile["id"])
    assert profiles.profile_path(profile["id"]).read_bytes() == canonical_profile_toml_bytes(profile)

    updated_profile = {**profile, "target_learner": "Synthetic cohort beta"}
    status, updated = write_api.put_profile(
        profiles,
        profile["id"],
        {"profile": updated_profile, "base_sha256": created["content_sha256"]},
    )
    assert status == 200
    assert updated["parsed"] == profile_to_dict(parse_learner_profile(updated_profile))
    assert updated["content_sha256"] != created["content_sha256"]


def test_put_profile_rejects_mismatch_wrong_nested_types_unknown_keys_and_bad_preconditions(
    tmp_path,
):
    profiles = ProfileStore(tmp_path)
    profile = _structured_profile()

    mismatch = {**profile, "id": "different"}
    with pytest.raises(ConfigError, match="profile id mismatch"):
        write_api.put_profile(
            profiles,
            profile["id"],
            {"profile": mismatch, "base_sha256": None},
        )

    wrong_nested = {**profile, "learning_preferences": ["diagrams"]}
    with pytest.raises(ConfigError, match="learning_preferences.*table"):
        write_api.put_profile(
            profiles,
            profile["id"],
            {"profile": wrong_nested, "base_sha256": None},
        )

    unknown = {**profile, "privacy": {**profile["privacy"], "secret_copy": "forbidden"}}
    with pytest.raises(ConfigError, match="unknown privacy field"):
        write_api.put_profile(
            profiles,
            profile["id"],
            {"profile": unknown, "base_sha256": None},
        )

    with pytest.raises(ConfigError, match="base_sha256"):
        write_api.put_profile(profiles, profile["id"], {"profile": profile})
    with pytest.raises(ConfigError, match="unknown profile request field"):
        write_api.put_profile(
            profiles,
            profile["id"],
            {"profile": profile, "base_sha256": None, "overwrite": True},
        )


def test_put_profile_conflicts_are_value_free_and_expose_only_current_hash(tmp_path):
    profiles = ProfileStore(tmp_path)
    profile = _structured_profile(target_learner="PLANTED_PRIVATE_VALUE_ALPHA")
    _, created = write_api.put_profile(
        profiles,
        profile["id"],
        {"profile": profile, "base_sha256": None},
    )

    with pytest.raises(write_api.ConflictError) as existing:
        write_api.put_profile(
            profiles,
            profile["id"],
            {"profile": profile, "base_sha256": None},
        )
    assert existing.value.code == "already_exists"
    assert existing.value.details == {"current_sha256": created["content_sha256"]}

    changed = {**profile, "target_learner": "PLANTED_PRIVATE_VALUE_BETA"}
    with pytest.raises(write_api.ConflictError) as stale:
        write_api.put_profile(
            profiles,
            profile["id"],
            {"profile": changed, "base_sha256": "0" * 64},
        )
    assert stale.value.code == "stale_content"
    assert stale.value.details == {"current_sha256": created["content_sha256"]}
    rendered = json.dumps(
        {"message": str(stale.value), "details": stale.value.details}, sort_keys=True
    )
    assert "PLANTED_PRIVATE_VALUE" not in rendered
    assert set(stale.value.details) == {"current_sha256"}


def test_duplicate_profile_replaces_id_returns_detail_and_refuses_collisions(tmp_path):
    profiles = ProfileStore(tmp_path)
    source = _structured_profile("source-profile")
    profiles.create_profile(source["id"], source)

    duplicated = write_api.duplicate_profile(
        profiles, source["id"], {"new_id": "copied-profile"}
    )
    assert duplicated == read_api.get_profile(profiles, "copied-profile")
    assert duplicated["parsed"]["id"] == "copied-profile"
    assert duplicated["parsed"]["target_learner"] == source["target_learner"]

    with pytest.raises(write_api.ConflictError) as collision:
        write_api.duplicate_profile(
            profiles, source["id"], {"new_id": "copied-profile"}
        )
    assert collision.value.code == "already_exists"
    assert collision.value.details == {
        "current_sha256": duplicated["content_sha256"]
    }
    with pytest.raises(NotFoundError):
        write_api.duplicate_profile(profiles, "missing", {"new_id": "unused"})


def test_raw_profile_import_writes_canonical_bytes(tmp_path):
    profiles = ProfileStore(tmp_path)
    raw = 'target_learner = "Synthetic import cohort"\nid = "raw-import"\n'

    assert write_api.import_profile(profiles, raw) == {"id": "raw-import"}
    record = profiles.read_profile_record("raw-import")
    assert profiles.profile_path("raw-import").read_bytes() == record.canonical_bytes
    assert profiles.profile_path("raw-import").read_bytes() != raw.encode("utf-8")


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


def test_run_status_payload_surfaces_stage_provenance(tmp_path):
    runs, jobs = _workspace(tmp_path)
    write_api.advance_run(runs, jobs, "t")
    # Legacy manifests (no stage_provenance key yet) must yield an empty list.
    status = write_api.read_api.run_status_payload(runs, "t")
    assert status["stage_provenance"] == []

    write_api.ingest_response(runs, jobs, "t", "spec", "manual body")
    status = write_api.read_api.run_status_payload(runs, "t")
    assert len(status["stage_provenance"]) == 1
    assert status["stage_provenance"][0]["source"] == "manual"


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


def test_create_waiver_response_built_from_locked_write_not_unlocked_reread(tmp_path, monkeypatch):
    """create_waiver must build its response from the WaiverSet the locked
    write inside RunStore.record_waiver already produced, not via a second,
    unlocked call to load_waiver_set: that extra re-read is racy (a
    concurrent writer bound to a different guide_sha256 could land between
    the two calls and cause the echoed payload to silently drop the
    waiver the client just recorded) and dereferences load_waiver_set's
    Optional return (``.schema_version``) without a guard. Prove the extra
    read is gone: monkeypatch load_waiver_set to explode, and confirm
    create_waiver still succeeds and returns the just-recorded waiver."""
    runs, jobs = _workspace(tmp_path, create_legacy_run=False)
    runs.create_run("t")
    guide = json.loads(FIXTURE.read_text(encoding="utf-8"))
    guide["modules"][0]["sections"][0]["blocks"][0]["markdown"] += " TODO"
    draft = runs.stage_paths("t", "draft")
    draft.approved_path.write_text(json.dumps(guide), encoding="utf-8")
    report = write_api.validate_run(runs, jobs, "t", "draft")["report"]
    finding = next(item for item in report["findings"] if item["waivable"])

    def _boom(self, topic_id):
        raise AssertionError(
            "create_waiver must not re-read load_waiver_set after the locked write"
        )

    monkeypatch.setattr(RunStore, "load_waiver_set", _boom)

    result = write_api.create_waiver(
        runs, "t", "draft", finding["id"], report["guide_sha256"], "Accepted example"
    )
    assert result["waivers"]["waivers"][0]["finding_id"] == finding["id"]
    assert result["waivers"]["waivers"][0]["reason"] == "Accepted example"
    assert result["waivers"]["guide_sha256"] == report["guide_sha256"]


def test_create_waiver_does_not_reach_into_private_store_methods(monkeypatch, waiver_env):
    """write_api must consume the public tuple method, not runs._record_waiver.

    The daemon genuinely needs the WaiverSet written *inside* the lock, but it
    must get it through a public contract rather than a private attribute.

    Note: `record_waiver_with_set` legitimately delegates to `_record_waiver`
    internally (that's the point of the public wrapper), so a boom-on-call
    monkeypatch of `_record_waiver` itself would fire even when write_api is
    calling the public method correctly. Instead this spies on the public
    `record_waiver_with_set` and asserts write_api's own code path goes
    through it.
    """
    from education_pipeline import runs as runs_mod

    runs, topic_id, finding_id = waiver_env

    calls = []
    original = runs_mod.RunStore.record_waiver_with_set

    def spy(self, *args, **kwargs):
        calls.append((args, kwargs))
        return original(self, *args, **kwargs)

    monkeypatch.setattr(runs_mod.RunStore, "record_waiver_with_set", spy)

    payload = write_api.create_waiver(
        runs, topic_id, "final", finding_id, _report_sha(runs, topic_id), "reviewed"
    )

    assert calls, "write_api must call the public record_waiver_with_set"
    assert [w["finding_id"] for w in payload["waivers"]["waivers"]] == [finding_id]


def test_delete_waiver_removes_it_and_returns_the_remaining_set(waiver_env):
    """Record a waiver, then delete it: the gate re-closes and the file is gone."""
    runs, topic_id, finding_id = waiver_env
    write_api.create_waiver(
        runs, topic_id, "final", finding_id, _report_sha(runs, topic_id), "reviewed"
    )
    assert runs.waivers_path(topic_id).exists()

    payload = write_api.delete_waiver(runs, topic_id, "final", finding_id)

    assert payload["waivers"]["waivers"] == []
    assert payload["report"]["summary"]["blocking"] >= 1
    assert not runs.waivers_path(topic_id).exists()


def test_delete_waiver_for_an_unwaived_finding_is_a_no_op(waiver_env):
    """Removing an id that was never waived must not create the waivers file."""
    runs, topic_id, _ = waiver_env

    payload = write_api.delete_waiver(runs, topic_id, "final", "never.waived:/root")

    assert payload["waivers"]["waivers"] == []
    assert not runs.waivers_path(topic_id).exists()


def test_waiver_rejects_wrong_shape_persisted_waivers_file(tmp_path):
    """A corrupted/non-object waivers file on disk must surface as ConfigError
    (400), not crash the process with AttributeError when the builder calls
    .get() on whatever json.loads() handed back."""
    runs, jobs = _workspace(tmp_path, create_legacy_run=False)
    runs.create_run("t")
    guide = json.loads(FIXTURE.read_text(encoding="utf-8"))
    guide["modules"][0]["sections"][0]["blocks"][0]["markdown"] += " TODO"
    draft = runs.stage_paths("t", "draft")
    draft.approved_path.write_text(json.dumps(guide), encoding="utf-8")
    report = write_api.validate_run(runs, jobs, "t", "draft")["report"]
    finding = next(item for item in report["findings"] if item["waivable"])

    path = runs.waivers_path("t")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")

    with pytest.raises(ConfigError):
        write_api.create_waiver(
            runs, "t", "draft", finding["id"], report["guide_sha256"], "reason"
        )


def _corrupt_waivers_setup(tmp_path, corrupt_waivers_list):
    runs, jobs = _workspace(tmp_path, create_legacy_run=False)
    runs.create_run("t")
    guide = json.loads(FIXTURE.read_text(encoding="utf-8"))
    guide["modules"][0]["sections"][0]["blocks"][0]["markdown"] += " TODO"
    draft = runs.stage_paths("t", "draft")
    draft.approved_path.write_text(json.dumps(guide), encoding="utf-8")
    report = write_api.validate_run(runs, jobs, "t", "draft")["report"]
    finding = next(item for item in report["findings"] if item["waivable"])

    path = runs.waivers_path("t")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "guide_sha256": report["guide_sha256"],
                "waivers": corrupt_waivers_list,
            }
        ),
        encoding="utf-8",
    )
    return runs, finding, report


@pytest.mark.parametrize(
    "corrupt_waivers_list",
    [
        [1, 2, 3],
        ["str"],
        [None],
        [[]],
        [{"reason": "no id key"}],
        [{"finding_id": 7}],
        [{"finding_id": None}],
    ],
)
def test_waiver_rejects_element_level_corrupt_waivers_list(tmp_path, corrupt_waivers_list):
    """Even when the root of validation-waivers.json is a well-formed object,
    a corrupt element inside its ``waivers`` list must surface as ConfigError
    (400), not crash the process when the builder calls ``.get()`` / compares
    ``finding_id`` values on whatever json.loads() handed back for an element."""
    runs, finding, report = _corrupt_waivers_setup(tmp_path, corrupt_waivers_list)

    with pytest.raises(ConfigError):
        write_api.create_waiver(
            runs, "t", "draft", finding["id"], report["guide_sha256"], "reason"
        )

    # The write must be atomic: a raised guard must leave no partial write and
    # no orphaned mkstemp temp file (``.tmp-<random>.json``, per
    # ``_write_bytes_atomic``), and the original corrupt file must be
    # untouched.
    path = runs.waivers_path("t")
    assert not list(path.parent.glob(f".tmp-*{path.suffix}"))
    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert persisted["waivers"] == corrupt_waivers_list


@pytest.mark.parametrize(
    "corrupt_waivers_list",
    [
        [1, 2, 3],
        ["str"],
        [None],
        [[]],
        [{"reason": "no id key"}],
        [{"finding_id": 7}],
        [{"finding_id": None}],
    ],
)
def test_waivers_payload_agrees_with_loader_on_corrupt_waivers_file(
    tmp_path, corrupt_waivers_list
):
    """The read-side ``waivers_payload`` builder used to keep a third, weaker
    copy of the waivers schema: it only checked that the file's root was a
    dict, then echoed the corrupt content back verbatim with
    ``"state": "current"``. That let GET report a run as healthy while the
    write endpoint and ``RunStore.load_waiver_set`` both raised ConfigError
    for the exact same file. All three surfaces must agree: a corrupt file
    is a typed error, not a 200."""
    runs, finding, report = _corrupt_waivers_setup(tmp_path, corrupt_waivers_list)

    with pytest.raises(ConfigError):
        write_api.read_api.waivers_payload(runs, "t", "draft")


@pytest.mark.parametrize("bad_reason", [5, None, [], {}])
def test_waiver_rejects_non_string_reason(tmp_path, bad_reason):
    runs, jobs = _workspace(tmp_path, create_legacy_run=False)
    runs.create_run("t")
    guide = json.loads(FIXTURE.read_text(encoding="utf-8"))
    guide["modules"][0]["sections"][0]["blocks"][0]["markdown"] += " TODO"
    draft = runs.stage_paths("t", "draft")
    draft.approved_path.write_text(json.dumps(guide), encoding="utf-8")
    report = write_api.validate_run(runs, jobs, "t", "draft")["report"]
    finding = next(item for item in report["findings"] if item["waivable"])

    with pytest.raises(ConfigError):
        write_api.create_waiver(
            runs, "t", "draft", finding["id"], report["guide_sha256"], bad_reason
        )


@pytest.mark.parametrize(
    "body",
    [
        {"provider": "manual", "stages": "draft"},
        {"provider": "manual", "stages": {"draft": "opus"}},
        {"provider": "manual", "stages": {"draft": {"model": 5}}},
        {"provider": "manual", "stages": {"draft": {"provider": []}}},
        {"provider": {}, "stages": {}},
    ],
)
def test_update_global_plan_rejects_wrong_shape_nested_values(body):
    config = _config_source()
    body = {**body, "base_sha256": config.plan_sha256()}
    with pytest.raises(ConfigError):
        write_api.update_global_plan(config, body)


@pytest.mark.parametrize(
    "body",
    [
        {"overrides": "not-a-dict"},
        {"overrides": {"draft": "opus"}},
        {"overrides": {"draft": {"model": 5}}},
        {"overrides": {"draft": {"provider": []}}},
        {"overrides": {"draft": []}},
    ],
)
def test_update_run_plan_rejects_wrong_shape_nested_values(tmp_path, body):
    config = _config_source()
    runs, _jobs = _workspace(tmp_path)
    with pytest.raises(ConfigError):
        write_api.update_run_plan(runs, config, "t", body)


@pytest.mark.parametrize(
    "body",
    [
        {"id": "x", "title": "T", "goals": "not-a-list"},
        {"id": "x", "title": "T", "goals": {"a": 1}},
        {"id": "x", "title": "T", "goals": [1, 2]},
        {"id": "x", "title": "T", "brief": {}},
        {"id": "x", "title": "T", "audience": []},
        {"id": {"a": 1}, "title": "T"},
        {"id": "x", "title": {"a": 1}},
    ],
)
def test_create_topic_rejects_wrong_shape_nested_values(tmp_path, body):
    from education_pipeline.workspace import TopicStore

    topics = TopicStore(tmp_path)
    with pytest.raises(ConfigError):
        write_api.create_topic(topics, body)
