"""Section-scoped repair: scope dataclass, scoped base, splice, and D8.

Spec: docs/superpowers/specs/2026-09-18-per-module-drafting-design.md, D8.
The module-scoped cases that already exist live in ``tests/test_runs.py``;
this file covers the section scope, the ``RepairScope`` triple, and the
scoped-base rule that makes a second scoped repair build on the approved
repair instead of silently discarding the first one.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import test_runs

from education_pipeline import ConfigError, StaleContentError
from education_pipeline.runs import RunStore

TOPIC = "systems-thinking"
MODULE_A = "loop-basics"
MODULE_B = "intervention-practice"
SECTION_B2 = "garden-decision"


def _latest_repair_event(runs: RunStore, action: str) -> dict:
    return next(
        event
        for event in reversed(runs.read_manifest(TOPIC)["events"])
        if event.get("stage") == "repair" and event.get("action") == action
    )


def _revised_section_json(
    module_index: int, section_index: int, **changes
) -> str:
    """One revised section of the guide fixture, as a JSON fragment."""

    data = json.loads(test_runs.GUIDE_FIXTURE)
    section = data["modules"][module_index]["sections"][section_index]
    section.update(changes)
    return json.dumps(section, ensure_ascii=False)


def _sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _repair_ready_run(tmp_path: Path) -> RunStore:
    runs = test_runs._create_guide_run(tmp_path)
    test_runs._drive_guide_through_factcheck(runs, TOPIC)
    return runs


def _approved_first_scoped_repair(
    tmp_path: Path, *, module_title: str = "Loop Basics, Round One"
) -> RunStore:
    """A run whose repair stage already holds an approved module-scoped fix."""

    runs = _repair_ready_run(tmp_path)
    runs.write_module_repair_prompt(TOPIC, MODULE_A)
    paths = runs.stage_paths(TOPIC, "repair")
    paths.response_path.write_text(
        test_runs._revised_module_json(0, title=module_title), encoding="utf-8"
    )
    runs.approve_stage(TOPIC, "repair")
    runs.validate_run(TOPIC, "final")
    return runs


# --- RepairScope -------------------------------------------------------------


def test_repair_scope_is_a_frozen_dataclass_shared_by_runs_and_run_core() -> None:
    from education_pipeline import run_core, runs as runs_module
    from education_pipeline.runs import RepairScope

    assert run_core.RepairScope is runs_module.RepairScope is RepairScope
    scope = RepairScope("loop-basics")
    assert (scope.module_id, scope.section_id) == ("loop-basics", None)
    assert scope == RepairScope("loop-basics", None)
    with pytest.raises(Exception):
        scope.module_id = "other"  # frozen


def test_repair_scope_is_none_before_any_repair_prompt(tmp_path: Path) -> None:
    runs = _repair_ready_run(tmp_path)

    assert runs.repair_scope(TOPIC) is None


def test_repair_scope_returns_the_dataclass_for_a_module_scoped_prompt(
    tmp_path: Path,
) -> None:
    from education_pipeline.runs import RepairScope

    runs = _repair_ready_run(tmp_path)
    runs.write_module_repair_prompt(TOPIC, MODULE_A)

    assert runs.repair_scope(TOPIC) == RepairScope(MODULE_A, None)
    assert "repair_section" not in _latest_repair_event(runs, "prompt_written")


def test_whole_guide_repair_prompt_resets_the_scope(tmp_path: Path) -> None:
    runs = _repair_ready_run(tmp_path)
    runs.write_section_repair_prompt(TOPIC, MODULE_B, SECTION_B2)

    runs.write_repair_prompt(TOPIC, overwrite=True)

    assert runs.repair_scope(TOPIC) is None
    event = _latest_repair_event(runs, "prompt_written")
    assert "repair_module" not in event and "repair_section" not in event


# --- write_section_repair_prompt --------------------------------------------


def test_write_section_repair_prompt_records_module_and_section_scope(
    tmp_path: Path,
) -> None:
    from education_pipeline.runs import RepairScope

    runs = _repair_ready_run(tmp_path)

    prompt = runs.write_section_repair_prompt(TOPIC, MODULE_B, SECTION_B2)

    assert prompt.stage == "repair"
    assert "## Section To Regenerate" in prompt.artifact.text
    assert runs.repair_scope(TOPIC) == RepairScope(MODULE_B, SECTION_B2)
    event = _latest_repair_event(runs, "prompt_written")
    assert event["repair_module"] == MODULE_B
    assert event["repair_section"] == SECTION_B2


def test_write_section_repair_prompt_binds_the_approved_draft_as_base(
    tmp_path: Path,
) -> None:
    runs = _repair_ready_run(tmp_path)

    runs.write_section_repair_prompt(TOPIC, MODULE_B, SECTION_B2)

    event = _latest_repair_event(runs, "prompt_written")
    draft_path = runs.stage_paths(TOPIC, "draft").approved_path
    assert event["source_draft_file_sha256"] == _sha256_of(draft_path)
    # No approved repair exists yet, so nothing binds one.
    assert "source_repair_file_sha256" not in event


def test_write_section_repair_prompt_rejects_unknown_module(tmp_path: Path) -> None:
    runs = _repair_ready_run(tmp_path)

    with pytest.raises(ConfigError, match="no-such-module"):
        runs.write_section_repair_prompt(TOPIC, "no-such-module", SECTION_B2)


def test_write_section_repair_prompt_rejects_unknown_section(tmp_path: Path) -> None:
    runs = _repair_ready_run(tmp_path)

    with pytest.raises(ConfigError, match="no-such-section"):
        runs.write_section_repair_prompt(TOPIC, MODULE_B, "no-such-section")


def test_write_section_repair_prompt_requires_repair_to_be_the_active_stage(
    tmp_path: Path,
) -> None:
    runs = test_runs._create_guide_run(tmp_path)
    test_runs._drive_guide_to_draft_approved(runs, TOPIC)
    runs.validate_run(TOPIC, "draft")

    with pytest.raises(ConfigError, match="repair"):
        runs.write_section_repair_prompt(TOPIC, MODULE_B, SECTION_B2)


# --- approval splices exactly one section -----------------------------------


def test_section_scoped_approval_splices_only_that_section(tmp_path: Path) -> None:
    from education_pipeline.guides import (
        canonical_guide_bytes,
        normalize_guide,
        parse_guide,
    )

    runs = _repair_ready_run(tmp_path)
    prompt = runs.write_section_repair_prompt(TOPIC, MODULE_B, SECTION_B2)
    prompt.response_path.write_text(
        _revised_section_json(1, 1, title="Practice a regenerated decision"),
        encoding="utf-8",
    )

    approved_path = runs.approve_stage(TOPIC, "repair")

    merged = json.loads(approved_path.read_text(encoding="utf-8"))
    base = json.loads(
        canonical_guide_bytes(normalize_guide(parse_guide(test_runs.GUIDE_FIXTURE)))
    )
    assert merged["modules"][1]["sections"][1]["title"] == (
        "Practice a regenerated decision"
    )
    # Sibling section, other module, and module frame are byte-identical.
    assert json.dumps(merged["modules"][1]["sections"][0], sort_keys=True) == (
        json.dumps(base["modules"][1]["sections"][0], sort_keys=True)
    )
    assert json.dumps(merged["modules"][0], sort_keys=True) == json.dumps(
        base["modules"][0], sort_keys=True
    )
    assert merged["modules"][1]["summary"] == base["modules"][1]["summary"]

    approval = _latest_repair_event(runs, "response_approved")
    assert approval["repair_module"] == MODULE_B
    assert approval["repair_section"] == SECTION_B2

    # The merged whole guide flows through the ordinary final gates.
    runs.validate_run(TOPIC, "final")
    assert runs.report_state(TOPIC, "final") == "current"


def test_section_scoped_approval_refuses_a_section_id_rename(tmp_path: Path) -> None:
    runs = _repair_ready_run(tmp_path)
    prompt = runs.write_section_repair_prompt(TOPIC, MODULE_B, SECTION_B2)
    prompt.response_path.write_text(
        _revised_section_json(1, 1, id="garden-decision-renamed"), encoding="utf-8"
    )

    with pytest.raises(ConfigError, match="section id must stay"):
        runs.approve_stage(TOPIC, "repair")
    assert not runs.stage_paths(TOPIC, "repair").approved_path.exists()


def test_section_scoped_approval_refuses_a_drifted_draft_base(tmp_path: Path) -> None:
    runs = _repair_ready_run(tmp_path)
    prompt = runs.write_section_repair_prompt(TOPIC, MODULE_B, SECTION_B2)
    prompt.response_path.write_text(_revised_section_json(1, 1), encoding="utf-8")

    draft_path = runs.stage_paths(TOPIC, "draft").approved_path
    data = json.loads(draft_path.read_text(encoding="utf-8"))
    data["course"]["description"] = "Edited after the scoped prompt was written."
    draft_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(StaleContentError, match="scoped repair"):
        runs.approve_stage(TOPIC, "repair")


# --- D8: the scoped base is the approved repair once one exists --------------


def test_second_scoped_prompt_binds_the_approved_repair_as_base(
    tmp_path: Path,
) -> None:
    runs = _approved_first_scoped_repair(tmp_path)

    prompt = runs.write_module_repair_prompt(TOPIC, MODULE_B, overwrite=True)

    event = _latest_repair_event(runs, "prompt_written")
    approved_repair = runs.stage_paths(TOPIC, "repair").approved_path
    assert event["source_repair_file_sha256"] == _sha256_of(approved_repair)
    # The prompt was compiled over the approved repair, so the first round's
    # fix shows up in the "rest of the course" frame.
    assert "Loop Basics, Round One" in prompt.artifact.text


def test_second_module_scoped_repair_keeps_the_first_approved_fix(
    tmp_path: Path,
) -> None:
    """D8 regression: a scoped repair must never discard the previous one."""

    runs = _approved_first_scoped_repair(tmp_path)
    paths = runs.stage_paths(TOPIC, "repair")

    runs.write_module_repair_prompt(TOPIC, MODULE_B, overwrite=True)
    paths.response_path.write_text(
        test_runs._revised_module_json(1, title="Intervention Practice, Round Two"),
        encoding="utf-8",
    )
    approved_path = runs.approve_stage(TOPIC, "repair", overwrite=True)

    merged = json.loads(approved_path.read_text(encoding="utf-8"))
    assert merged["modules"][0]["title"] == "Loop Basics, Round One"
    assert merged["modules"][1]["title"] == "Intervention Practice, Round Two"


def test_third_section_scoped_repair_keeps_both_earlier_fixes(
    tmp_path: Path,
) -> None:
    """D8 regression, section scope: round three preserves rounds one and two."""

    runs = _approved_first_scoped_repair(tmp_path)
    paths = runs.stage_paths(TOPIC, "repair")

    runs.write_module_repair_prompt(TOPIC, MODULE_B, overwrite=True)
    paths.response_path.write_text(
        test_runs._revised_module_json(1, title="Intervention Practice, Round Two"),
        encoding="utf-8",
    )
    runs.approve_stage(TOPIC, "repair", overwrite=True)
    runs.validate_run(TOPIC, "final")

    prompt = runs.write_section_repair_prompt(
        TOPIC, MODULE_B, SECTION_B2, overwrite=True
    )
    event = _latest_repair_event(runs, "prompt_written")
    assert event["repair_section"] == SECTION_B2
    assert event["source_repair_file_sha256"] == _sha256_of(paths.approved_path)
    assert "Intervention Practice, Round Two" in prompt.artifact.text

    paths.response_path.write_text(
        _revised_section_json(1, 1, title="Practice, Round Three"), encoding="utf-8"
    )
    approved_path = runs.approve_stage(TOPIC, "repair", overwrite=True)

    merged = json.loads(approved_path.read_text(encoding="utf-8"))
    assert merged["modules"][0]["title"] == "Loop Basics, Round One"
    assert merged["modules"][1]["title"] == "Intervention Practice, Round Two"
    assert merged["modules"][1]["sections"][1]["title"] == "Practice, Round Three"
    # The untouched sibling section survived all three rounds unchanged.
    assert merged["modules"][1]["sections"][0]["id"] == "delays-and-leverage"


def test_second_round_scoped_approval_refuses_a_drifted_approved_repair(
    tmp_path: Path,
) -> None:
    runs = _approved_first_scoped_repair(tmp_path)
    paths = runs.stage_paths(TOPIC, "repair")
    runs.write_section_repair_prompt(TOPIC, MODULE_B, SECTION_B2, overwrite=True)
    paths.response_path.write_text(_revised_section_json(1, 1), encoding="utf-8")

    data = json.loads(paths.approved_path.read_text(encoding="utf-8"))
    data["course"]["description"] = "Edited after the second scoped prompt."
    paths.approved_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(StaleContentError, match="scoped repair"):
        runs.approve_stage(TOPIC, "repair", overwrite=True)


def test_final_report_findings_feed_the_second_round_scoped_prompt(
    tmp_path: Path,
) -> None:
    runs = _repair_ready_run(tmp_path)
    paths = runs.stage_paths(TOPIC, "repair")

    # Round one introduces a deterministic problem the draft report never saw.
    runs.write_module_repair_prompt(TOPIC, MODULE_A)
    data = json.loads(test_runs.GUIDE_FIXTURE)
    module = data["modules"][0]
    module["sections"][0]["blocks"][0]["markdown"] = (
        "TODO: explain how the loop closes."
    )
    paths.response_path.write_text(json.dumps(module, ensure_ascii=False), encoding="utf-8")
    runs.approve_stage(TOPIC, "repair")
    runs.validate_run(TOPIC, "final")

    final_report = json.loads(runs.final_report_path(TOPIC).read_text(encoding="utf-8"))
    assert any(
        finding["rule_id"] == "content.placeholder"
        for finding in final_report["findings"]
    )
    draft_report = json.loads(runs.draft_report_path(TOPIC).read_text(encoding="utf-8"))
    assert not any(
        finding["rule_id"] == "content.placeholder"
        for finding in draft_report["findings"]
    )

    prompt = runs.write_module_repair_prompt(TOPIC, MODULE_A, overwrite=True)

    # The second-round prompt carries the report over its own base.
    assert "content.placeholder" in prompt.artifact.text
    assert "TODO: explain how the loop closes." in prompt.artifact.text
