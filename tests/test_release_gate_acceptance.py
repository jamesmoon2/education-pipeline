"""Milestone acceptance record for the deterministic release gates.

Four end-to-end tests over guide-v1 runs, exercising the shipped behavior
from Waves 1-3: structural refusal, privacy refusal (with waiver), byte-
identical reproducibility, and stale-waiver refusal. These reuse the
fixture-driven guide-v1 run helpers from ``test_runs`` rather than
reinventing plumbing.
"""

import hashlib
import json
from pathlib import Path

import pytest

import test_runs
from education_pipeline import ConfigError, ProfileStore


PRIVACY_LEAK_FIXTURE = Path(
    "tests/fixtures/guides/feedback-loops.privacy-leak.guide.json"
).read_text(encoding="utf-8")

PRIVATE_VALUE = "Priya Nakamura-Osei's mentorship cohort at Alderbrook Robotics"

PRIVACY_PROFILE_TOML = f"""\
schema_version = 1
id = "gate-acceptance-profile"
target_learner = "{PRIVATE_VALUE}"
professional_experience = "early-career analysts"

[privacy]
private_by_default = true
include_in_published_output = false
publishable_summary = "A cohort of early-career analysts learning systems thinking."
"""


def test_structural_refusal_export_raises_and_leaves_no_artifacts(tmp_path: Path) -> None:
    """A schema blocker in repair content: export_run raises ConfigError and
    writes neither export HTML nor its sidecar report."""

    tid = "systems-thinking"
    runs = test_runs._create_guide_run(tmp_path, tid)
    bad = json.loads(test_runs.GUIDE_FIXTURE)
    bad["schema_version"] = "2.0"
    bad_json = json.dumps(bad)

    test_runs._drive_guide_to_finalize_ready(
        runs, tid, draft_body=test_runs.GUIDE_FIXTURE, repair_body=bad_json
    )

    report = json.loads(runs.final_report_path(tid).read_text(encoding="utf-8"))
    blockers = [f for f in report["findings"] if f["blocking"]]
    assert blockers
    assert blockers[0]["waivable"] is False

    assert not runs.is_finalized(tid)
    with pytest.raises(ConfigError):
        runs.finalize_run(tid)
    with pytest.raises(ConfigError):
        runs.export_run(tid, format="html")

    assert not runs.export_path(tid, "html").exists()
    assert not runs.export_report_path(tid).exists()


def test_privacy_refusal_blocks_export_until_waived(tmp_path: Path) -> None:
    """A private value from the attached profile leaking into guide content
    blocks export via ``privacy.exact_private_value``; a recorded waiver
    (the rule is waivable) opens the gate."""

    tid = "systems-thinking"
    profiles = ProfileStore(tmp_path)
    profiles.save_profile_toml("gate-acceptance-profile", PRIVACY_PROFILE_TOML)
    profiles.attach_profile_to_topic("gate-acceptance-profile", tid)

    runs = test_runs._create_guide_run(tmp_path, tid)
    test_runs._drive_guide_to_finalize_ready(
        runs, tid, draft_body=PRIVACY_LEAK_FIXTURE, repair_body=PRIVACY_LEAK_FIXTURE
    )

    report = json.loads(runs.final_report_path(tid).read_text(encoding="utf-8"))
    leaks = [f for f in report["findings"] if f["rule_id"] == "privacy.exact_private_value"]
    assert leaks, "expected a privacy.exact_private_value finding for the supplied private value"
    assert leaks[0]["blocking"] is True
    assert leaks[0]["waivable"] is True

    with pytest.raises(ConfigError):
        runs.finalize_run(tid)
    with pytest.raises(ConfigError):
        runs.export_run(tid, format="html")

    result = runs.record_waiver(
        tid, "final", leaks[0]["id"], "Reviewed: cohort approved this disclosed example."
    )
    assert result.gate_open is True

    na = runs.run_status(tid).next_action
    assert na.action == "finalize"

    runs.finalize_run(tid)
    exported = runs.export_run(tid, format="html")
    assert exported.is_file()
    assert runs.export_report_path(tid).is_file()


def test_export_and_sidecar_are_byte_identical_across_independent_runs(tmp_path: Path) -> None:
    """Two independent workspaces driven through validate->finalize->export
    on identical content must produce byte-identical export HTML and
    byte-identical sidecar quality reports."""

    tid = "systems-thinking"
    root_a = tmp_path / "workspace-a"
    root_b = tmp_path / "workspace-b"

    runs_a = test_runs._create_guide_run(root_a, tid)
    test_runs._drive_guide_to_finalize_ready(runs_a, tid)
    runs_a.finalize_run(tid)
    export_a = runs_a.export_run(tid, format="html")
    sidecar_a = runs_a.export_report_path(tid)

    runs_b = test_runs._create_guide_run(root_b, tid)
    test_runs._drive_guide_to_finalize_ready(runs_b, tid)
    runs_b.finalize_run(tid)
    export_b = runs_b.export_run(tid, format="html")
    sidecar_b = runs_b.export_report_path(tid)

    assert export_a.read_bytes() == export_b.read_bytes()
    assert sidecar_a.read_bytes() == sidecar_b.read_bytes()


@pytest.mark.parametrize("audit_state", ["not_run", "current", "stale"])
def test_profiled_export_and_sidecar_are_byte_identical_in_every_audit_state(
    tmp_path: Path, audit_state: str
) -> None:
    tid = "systems-thinking"
    outputs = []
    for workspace in ("workspace-a", "workspace-b"):
        runs = test_runs._create_profiled_guide_run(tmp_path / workspace)
        test_runs._drive_profiled_guide_to_finalize_ready(runs, tid)
        if audit_state != "not_run":
            runs.prepare_personalization_audit(tid)
            runs.ingest_response(
                tid,
                "audit",
                test_runs._valid_personalization_audit_response(runs, tid),
            )
            runs.approve_stage(tid, "audit")
            if audit_state == "stale":
                projection = runs.audit_projection_path(tid)
                projection.write_bytes(projection.read_bytes() + b"\n")
        assert runs.audit_state(tid) == audit_state
        runs.finalize_run(tid)
        export = runs.export_run(tid)
        outputs.append((export.read_bytes(), runs.export_report_path(tid).read_bytes()))

    assert outputs[0] == outputs[1]


def test_stale_waiver_never_reopens_the_gate(tmp_path: Path) -> None:
    """A waiver recorded against one hash of repair content must not apply
    once that content changes: ``apply_waivers``/``gate_result`` reports
    ``stale`` and export continues to refuse."""

    tid = "systems-thinking"
    runs = test_runs._create_guide_run(tmp_path, tid)
    leak_json = test_runs._prompt_leak_guide_json()
    test_runs._drive_guide_to_finalize_ready(runs, tid, draft_body=leak_json, repair_body=leak_json)

    report = json.loads(runs.final_report_path(tid).read_text(encoding="utf-8"))
    leak_findings = [
        f for f in report["findings"] if f["rule_id"] == "content.prompt_leak" and f["blocking"]
    ]
    assert leak_findings
    finding_id = leak_findings[0]["id"]
    assert leak_findings[0]["waivable"] is True

    waived = runs.record_waiver(tid, "final", finding_id, "Intentional red-team phrase in example.")
    assert waived.gate_open is True

    runs.finalize_run(tid)
    exported = runs.export_run(tid, format="html")
    assert exported.is_file()

    # Mutate the repair content elsewhere (leave the waived finding's path
    # untouched, so the same finding id persists) after waiving.
    repair_paths = runs.stage_paths(tid, "repair")
    base_sha = hashlib.sha256(repair_paths.response_path.read_bytes()).hexdigest()
    mutated = test_runs._edit_course_description(
        leak_json, "Edited course description to invalidate the stale waiver."
    )
    runs.edit_response(tid, "repair", mutated, base_sha256=base_sha)
    runs.approve_stage(tid, "repair", overwrite=True)
    assert runs.is_finalized(tid) is False

    runs.validate_run(tid, "final")
    gate = runs.gate_result(tid, "final")
    assert gate.stale is True
    assert gate.gate_open is False

    with pytest.raises(ConfigError):
        runs.finalize_run(tid, overwrite=True)
    with pytest.raises(ConfigError):
        runs.export_run(tid, format="html", overwrite=True)


def test_export_refuses_after_unwaive_following_finalize(tmp_path: Path) -> None:
    """Waive a waivable blocking finding, finalize, then remove the waiver
    (the CLI ``unwaive`` path) without touching content or revalidating.

    The run stays finalized and ``report_state`` stays "current" -- every
    export precondition still passes. The only thing standing between this
    state and a bad export is ``_export_guide_v1``'s own
    ``apply_waivers``/gate check: it must still refuse, and export must
    leave no artifacts behind.
    """

    tid = "systems-thinking"
    runs = test_runs._create_guide_run(tmp_path, tid)
    leak_json = test_runs._prompt_leak_guide_json()
    test_runs._drive_guide_to_finalize_ready(runs, tid, draft_body=leak_json, repair_body=leak_json)

    report = json.loads(runs.final_report_path(tid).read_text(encoding="utf-8"))
    leak_findings = [
        f for f in report["findings"] if f["rule_id"] == "content.prompt_leak" and f["blocking"]
    ]
    assert leak_findings
    finding_id = leak_findings[0]["id"]
    assert leak_findings[0]["waivable"] is True

    waived = runs.record_waiver(tid, "final", finding_id, "Intentional red-team phrase in example.")
    assert waived.gate_open is True

    runs.finalize_run(tid)
    assert runs.is_finalized(tid)

    unwaived = runs.remove_waiver(tid, "final", finding_id)
    assert unwaived.gate_open is False

    # Nothing about finalize state or report freshness changed: the internal
    # gate in `_export_guide_v1` is the sole remaining defense.
    assert runs.is_finalized(tid)
    assert runs.report_state(tid, "final") == "current"

    with pytest.raises(ConfigError, match=r"blocking finding\(s\) remain"):
        runs.export_run(tid, format="html")

    assert not runs.export_path(tid, "html").exists()
    assert not runs.export_report_path(tid).exists()
