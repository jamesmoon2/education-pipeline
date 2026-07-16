"""End-to-end acceptance for the personalization milestone.

These tests intentionally reuse the fixture-driven run helpers in ``test_runs``.
They exercise the integrated profile, trace, audit, finalize, and export paths
without introducing another pipeline harness.
"""

import hashlib
import json
from pathlib import Path

import pytest

import test_runs
from education_pipeline import ConfigError, ProfileStore
from education_pipeline.daemon import read_api, write_api


HIGH_PRIVATE_VALUE = "Synthetic Alderbridge learner cohort secret"
MEDIUM_PRIVATE_VALUE = "Synthetic private objective orchard-47"
HOSTILE_NARRATIVES = (
    "HOSTILE_GOAL_NARRATIVE_SHOULD_STAY_LOCAL",
    "HOSTILE_FACET_NARRATIVE_SHOULD_STAY_LOCAL",
    "HOSTILE_GENERIC_NARRATIVE_SHOULD_STAY_LOCAL",
    "HOSTILE_PRIVATE_FLAG_NARRATIVE_SHOULD_STAY_LOCAL",
    "HOSTILE_OVERALL_NARRATIVE_SHOULD_STAY_LOCAL",
)


def _profile_mapping(profile_id: str = "structured-profile") -> dict[str, object]:
    return {
        "schema_version": 1,
        "id": profile_id,
        "target_learner": HIGH_PRIVATE_VALUE,
        "learning_goals": [MEDIUM_PRIVATE_VALUE],
        "learning_preferences": {"preferred_visual_aids": ["flowcharts"]},
        "privacy": {
            "private_by_default": True,
            "include_in_published_output": False,
        },
        "metadata": {"nested": {"cohort": "Synthetic metadata secret"}},
    }


def _profile_toml(profile_id: str = "acceptance-profile") -> str:
    return f'''\
schema_version = 1
id = "{profile_id}"
target_learner = "{HIGH_PRIVATE_VALUE}"
learning_goals = [
  "{MEDIUM_PRIVATE_VALUE}",
  "Synthetic private goal beta",
  "Synthetic private goal gamma",
]

[learning_preferences]
preferred_visual_aids = ["flowcharts"]

[privacy]
private_by_default = true
include_in_published_output = false
'''


def _hostile_audit_response(runs, topic_id: str) -> str:
    response = json.loads(
        test_runs._valid_personalization_audit_response(runs, topic_id)
    )
    for goal in response["goals"]:
        goal["rationale"] = HOSTILE_NARRATIVES[0]
    for facet in response["facets"]:
        facet["rationale"] = HOSTILE_NARRATIVES[1]
    response["generic_sections"] = [
        {
            "location": {"kind": "block", "id": "loop-introduction"},
            "reason_code": "generic_explanation",
            "rationale": HOSTILE_NARRATIVES[2],
        }
    ]
    response["suspected_private_details"] = [
        {
            "location": {"kind": "block", "id": "garden-connection"},
            "category": "learner_identity",
            "confidence": "high",
            "rationale": HOSTILE_NARRATIVES[3],
        }
    ]
    response["overall_summary"] = HOSTILE_NARRATIVES[4]
    return json.dumps(response, sort_keys=True)


def _set_audit_state(runs, topic_id: str, audit_state: str) -> None:
    if audit_state == "not_run":
        return
    runs.prepare_personalization_audit(topic_id)
    runs.ingest_response(
        topic_id,
        "audit",
        test_runs._valid_personalization_audit_response(runs, topic_id),
    )
    runs.approve_stage(topic_id, "audit")
    if audit_state == "stale":
        projection = runs.audit_projection_path(topic_id)
        projection.write_bytes(projection.read_bytes() + b"\n")


def test_structured_profile_lifecycle_preserves_attached_snapshot(
    tmp_path: Path,
) -> None:
    profiles = ProfileStore(tmp_path)
    profile = _profile_mapping()

    preview = read_api.preview_profile(profile)
    assert preview["parsed"]["id"] == "structured-profile"
    assert preview["parsed"]["target_learner"] == HIGH_PRIVATE_VALUE
    assert preview["parsed"]["learning_goals"] == [MEDIUM_PRIVATE_VALUE]
    assert read_api.list_profiles(profiles) == {"profiles": []}

    status, created = write_api.put_profile(
        profiles,
        "structured-profile",
        {"profile": profile, "base_sha256": None},
    )
    assert status == 201
    assert created == read_api.get_profile(profiles, "structured-profile")
    assert created["parsed"] == preview["parsed"]

    updated_profile = {
        **profile,
        "target_learner": "Synthetic updated source learner",
    }
    status, updated = write_api.put_profile(
        profiles,
        "structured-profile",
        {"profile": updated_profile, "base_sha256": created["content_sha256"]},
    )
    assert status == 200
    assert updated["content_sha256"] != created["content_sha256"]

    duplicate = write_api.duplicate_profile(
        profiles,
        "structured-profile",
        {"new_id": "structured-copy"},
    )
    assert duplicate["parsed"]["id"] == "structured-copy"
    assert [item["id"] for item in read_api.list_profiles(profiles)["profiles"]] == [
        "structured-copy",
        "structured-profile",
    ]

    attached = write_api.attach_profile(
        profiles,
        "structured-topic",
        "structured-copy",
    )
    assert attached["snapshot_path"] == "inputs/profile.toml"
    snapshot_path = profiles.topic_profile_snapshot_path("structured-topic")
    attached_bytes = snapshot_path.read_bytes()
    assert attached_bytes == profiles.profile_path("structured-copy").read_bytes()
    assert read_api.get_profile(profiles, "structured-copy")[
        "attached_topic_count"
    ] == 1

    changed_copy = {
        **duplicate["parsed"],
        "target_learner": "Synthetic later source edit",
    }
    status, changed = write_api.put_profile(
        profiles,
        "structured-copy",
        {"profile": changed_copy, "base_sha256": duplicate["content_sha256"]},
    )
    assert status == 200
    assert changed["content_sha256"] != duplicate["content_sha256"]
    assert profiles.profile_path("structured-copy").read_bytes() != attached_bytes
    assert snapshot_path.read_bytes() == attached_bytes
    assert profiles.load_topic_profile_snapshot("structured-topic").target_learner == (
        "Synthetic updated source learner"
    )


def test_high_and_medium_profile_leaks_refuse_finalize_and_export(
    tmp_path: Path,
) -> None:
    topic_id = "systems-thinking"
    runs = test_runs._create_profiled_guide_run(
        tmp_path,
        profile_toml=_profile_toml(),
        profile_id="acceptance-profile",
        topic_id=topic_id,
    )
    leaked = json.loads(test_runs.PERSONALIZED_GUIDE_FIXTURE)
    leaked["modules"][0]["sections"][0]["blocks"][0]["markdown"] += (
        f" {HIGH_PRIVATE_VALUE} {MEDIUM_PRIVATE_VALUE}"
    )
    test_runs._drive_profiled_guide_to_finalize_ready(
        runs,
        topic_id,
        body=json.dumps(leaked),
    )

    report_bytes = runs.final_report_path(topic_id).read_bytes()
    report = json.loads(report_bytes)
    leak_findings = [
        finding
        for finding in report["findings"]
        if finding["rule_id"] == "privacy.exact_private_value"
    ]
    assert len(leak_findings) >= 2
    assert all(
        finding["blocking"] is True and finding["waivable"] is True
        for finding in leak_findings
    )
    for planted in (HIGH_PRIVATE_VALUE, MEDIUM_PRIVATE_VALUE):
        assert planted.encode() not in report_bytes

    with pytest.raises(ConfigError, match="blocking finding") as finalize_error:
        runs.finalize_run(topic_id)
    with pytest.raises(ConfigError):
        runs.export_run(topic_id)
    assert HIGH_PRIVATE_VALUE not in str(finalize_error.value)
    assert MEDIUM_PRIVATE_VALUE not in str(finalize_error.value)
    assert not runs.export_path(topic_id, "html").exists()
    assert not runs.export_report_path(topic_id).exists()


def test_schema_1_1_trace_construction_and_dangling_reference_refusal(
    tmp_path: Path,
) -> None:
    topic_id = "systems-thinking"
    current = test_runs._create_profiled_guide_run(
        tmp_path / "current",
        profile_toml=_profile_toml(),
        profile_id="acceptance-profile",
        topic_id=topic_id,
    )
    test_runs._drive_profiled_guide_to_finalize_ready(current, topic_id)
    trace_path = current.personalization_trace_path(topic_id)
    trace = json.loads(trace_path.read_bytes())
    snapshot = ProfileStore(tmp_path / "current").topic_profile_snapshot_path(topic_id)

    assert trace["schema_version"] == 1
    assert trace["profile_snapshot_sha256"] == hashlib.sha256(
        snapshot.read_bytes()
    ).hexdigest()
    assert [goal["goal_id"] for goal in trace["goals"]] == [
        "goal-001",
        "goal-002",
        "goal-003",
    ]
    assert [goal["goal_text"] for goal in trace["goals"]] == [
        MEDIUM_PRIVATE_VALUE,
        "Synthetic private goal beta",
        "Synthetic private goal gamma",
    ]
    assert trace["goals"][0]["serving_module_ids"] == ["loop-basics"]
    assert trace["goals"][2]["exclusions"] == [
        {"goal_id": "goal-003", "reason": "Synthetic deferred objective."}
    ]
    assert current.personalization_trace_state(topic_id, phase="final") == "current"

    dangling = test_runs._create_profiled_guide_run(
        tmp_path / "dangling",
        profile_toml=_profile_toml(),
        profile_id="acceptance-profile",
        topic_id=topic_id,
    )
    dangling_guide = json.loads(test_runs.PERSONALIZED_GUIDE_FIXTURE)
    dangling_guide["modules"][0]["serves_goals"].append("goal-999")
    test_runs._drive_profiled_guide_to_finalize_ready(
        dangling,
        topic_id,
        body=json.dumps(dangling_guide),
    )
    report = json.loads(dangling.final_report_path(topic_id).read_bytes())
    assert "personalization.dangling_goal_ref" in {
        finding["rule_id"] for finding in report["findings"]
    }
    with pytest.raises(ConfigError):
        dangling.finalize_run(topic_id)
    assert not dangling.export_path(topic_id, "html").exists()


@pytest.mark.parametrize("trace_failure", ["missing", "stale"])
def test_missing_and_stale_trace_refuse_release(
    tmp_path: Path,
    trace_failure: str,
) -> None:
    topic_id = "systems-thinking"
    runs = test_runs._create_profiled_guide_run(tmp_path)
    test_runs._drive_profiled_guide_to_finalize_ready(runs, topic_id)
    trace_path = runs.personalization_trace_path(topic_id)
    if trace_failure == "missing":
        trace_path.unlink()
    else:
        trace = json.loads(trace_path.read_bytes())
        trace["guide_sha256"] = "0" * 64
        trace_path.write_text(
            json.dumps(trace, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    assert runs.personalization_trace_state(topic_id, phase="final") == trace_failure
    with pytest.raises(ConfigError, match="personalization trace"):
        runs.finalize_run(topic_id)
    with pytest.raises(ConfigError):
        runs.export_run(topic_id)
    assert not runs.export_path(topic_id, "html").exists()
    assert not runs.export_report_path(topic_id).exists()


@pytest.mark.parametrize("audit_timing", ["before_finalize", "after_finalize"])
def test_optional_audit_projects_hostile_narrative_and_stales_existing_export(
    tmp_path: Path,
    audit_timing: str,
) -> None:
    topic_id = "systems-thinking"
    runs = test_runs._create_profiled_guide_run(tmp_path)
    test_runs._drive_profiled_guide_to_finalize_ready(runs, topic_id)
    original_exported_bytes: bytes | None = None
    original_sidecar_bytes: bytes | None = None
    if audit_timing == "after_finalize":
        runs.finalize_run(topic_id)
        original_export_path = runs.export_run(topic_id)
        original_sidecar_path = runs.export_report_path(topic_id)
        original_exported_bytes = original_export_path.read_bytes()
        original_sidecar_bytes = original_sidecar_path.read_bytes()
        assert json.loads(original_sidecar_bytes)["audit"]["state"] == "not_run"
        assert runs.export_state(topic_id) == "current"

    runs.prepare_personalization_audit(topic_id)
    hostile_response = _hostile_audit_response(runs, topic_id)
    runs.ingest_response(topic_id, "audit", hostile_response)
    runs.approve_stage(topic_id, "audit")
    assert runs.audit_state(topic_id) == "current"
    assert all(
        narrative in runs.stage_paths(topic_id, "audit").response_path.read_text(
            encoding="utf-8"
        )
        for narrative in HOSTILE_NARRATIVES
    )

    safe_findings = [
        finding
        for finding in runs.combined_findings(topic_id)
        if finding.stage == "audit"
    ]
    assert {finding.rule_id for finding in safe_findings} == {
        "audit.goal_missing",
        "audit.generic_section",
        "audit.suspected_private_detail",
    }

    if audit_timing == "before_finalize":
        runs.finalize_run(topic_id)
        export_path = runs.export_run(topic_id)
    else:
        assert original_exported_bytes is not None
        assert original_sidecar_bytes is not None
        assert runs.export_state(topic_id) == "stale"
        assert runs.export_path(topic_id, "html").read_bytes() == original_exported_bytes
        assert runs.export_report_path(topic_id).read_bytes() == original_sidecar_bytes
        export_path = runs.export_run(topic_id, overwrite=True)
        assert runs.export_state(topic_id) == "current"
    sidecar_path = runs.export_report_path(topic_id)
    projection_path = runs.audit_projection_path(topic_id)
    exported_bytes = export_path.read_bytes()
    sidecar_bytes = sidecar_path.read_bytes()
    sidecar = json.loads(sidecar_bytes)
    assert sidecar["audit"]["state"] == "current"
    assert len(
        [
            finding
            for finding in sidecar["report"]["findings"]
            if finding["stage"] == "audit"
        ]
    ) == 3

    public_blobs = (exported_bytes, sidecar_bytes, projection_path.read_bytes())
    source_only_values = (
        "Synthetic learner cohort",
        "Synthetic private goal alpha",
        "Synthetic private goal beta",
        "Synthetic private goal gamma",
        "Synthetic deferred objective.",
        "serves_goals",
        "goal_exclusions",
        *HOSTILE_NARRATIVES,
    )
    for value in source_only_values:
        assert all(value.encode() not in blob for blob in public_blobs)


@pytest.mark.parametrize("audit_state", ["not_run", "current", "stale"])
def test_public_sidecar_is_reproducible_for_every_audit_state(
    tmp_path: Path,
    audit_state: str,
) -> None:
    topic_id = "systems-thinking"
    outputs: list[tuple[bytes, bytes]] = []
    for workspace_name in ("workspace-a", "workspace-b"):
        runs = test_runs._create_profiled_guide_run(tmp_path / workspace_name)
        test_runs._drive_profiled_guide_to_finalize_ready(runs, topic_id)
        _set_audit_state(runs, topic_id, audit_state)
        assert runs.audit_state(topic_id) == audit_state
        runs.finalize_run(topic_id)
        export = runs.export_run(topic_id)
        sidecar = runs.export_report_path(topic_id).read_bytes()
        assert json.loads(sidecar)["audit"]["state"] == audit_state
        assert runs.export_state(topic_id) == "current"
        outputs.append((export.read_bytes(), sidecar))

    assert outputs[0] == outputs[1]
