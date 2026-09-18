"""Failing-first tests for the modular draft lifecycle (thread T22).

Written strictly TDD: none of the API exercised here exists yet
(``education_pipeline.draft_parts``, ``RunStore.draft_strategy`` and
friends). Every test therefore fails today with ``ImportError`` /
``AttributeError`` / ``TypeError`` while the rest of the suite is untouched --
the new names are imported *inside* helper functions (``_dp()``) rather than
at module scope, so this file still collects cleanly.

The fixtures/helpers at the top are copied verbatim (or lightly adapted --
two modules instead of one, matching the shipped guide fixture) from
``tests/test_characterization_guide_v1.py``; ``tests/`` has no
``__init__.py``, so they cannot be imported.

Contract under test: ``docs/superpowers/specs/2026-09-18-per-module-drafting-design.md``
decisions D1, D3, D4, D5.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from education_pipeline import (
    ConfigError,
    ContentContract,
    RunStore,
    StageStatus,
    TopicStore,
)
from education_pipeline.guides.canonical import assemble_guide
from education_pipeline.run_core import StaleContentError

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "guides"

TID = "systems-thinking"

# --------------------------------------------------------------------------
# Fixtures and helpers copied from tests/test_characterization_guide_v1.py.
# --------------------------------------------------------------------------

TOPIC_TOML = """\
schema_version = 1
id = "systems-thinking"
title = "Systems Thinking"
brief = "A public introduction to feedback loops."
audience = "early-career analysts"
goals = ["explain feedback loops"]
"""

GUIDE_FIXTURE = (FIXTURES_DIR / "feedback-loops.guide.json").read_text(encoding="utf-8")
GUIDE = json.loads(GUIDE_FIXTURE)
MODULES_BY_ID = {module["id"]: module for module in GUIDE["modules"]}

# The spec contract's outcomes are exactly the fixture guide's outcomes, so the
# assembled guide's outcome references all resolve inside the contract.
VALID_SPEC_CONTRACT = {
    "contract_version": 1,
    "guide_schema_version": "1.0",
    "blueprint": "conceptual-foundations",
    "estimated_minutes": 30,
    "outcomes": [dict(outcome) for outcome in GUIDE["outcomes"]],
    "required_interactions": ["knowledge_check", "worked_reveal", "scenario", "reflection"],
    "personalization_requirements": ["Use gardening examples where they clarify the concept."],
    "source_policy": "Sources required for factual claims that are not common knowledge.",
}

# Two modules, ids/outcome ids/minutes/interaction types taken from the fixture
# guide's two modules, so the assembled guide passes strict parse + validation.
VALID_OUTLINE_CONTRACT = {
    "contract_version": 1,
    "modules": {
        "loop-basics": {
            "outcome_ids": ["identify-loop", "map-loop"],
            "estimated_minutes": 14,
            "interaction_types": ["knowledge_check", "worked_reveal"],
        },
        "intervention-practice": {
            "outcome_ids": ["map-loop", "choose-intervention"],
            "estimated_minutes": 16,
            "interaction_types": ["knowledge_check", "scenario", "reflection"],
        },
    },
}


def _guide_spec_response(contract: dict | None = None) -> str:
    body = contract if contract is not None else VALID_SPEC_CONTRACT
    return (
        "# Course Specification: Systems Thinking\n\n"
        "## Learning Outcomes\n"
        "- Identify reinforcing and balancing feedback.\n\n"
        "```education-pipeline-contract+json\n"
        f"{json.dumps(body)}\n"
        "```\n"
    )


def _guide_outline_response(contract: dict | None = None) -> str:
    body = contract if contract is not None else VALID_OUTLINE_CONTRACT
    return (
        "# Course Outline: Systems Thinking\n\n"
        "## Modules\n"
        "1. How loops behave\n"
        "2. Intervene with the whole loop in view\n\n"
        "```education-pipeline-outline+json\n"
        f"{json.dumps(body)}\n"
        "```\n"
    )


def _drive_guide_spec_to_approved(runs: RunStore, topic_id: str) -> None:
    result = runs.write_topic_spec_prompt(topic_id)
    result.response_path.write_text(_guide_spec_response(), encoding="utf-8")
    runs.approve_stage(topic_id, "spec")


def _drive_guide_outline_to_approved(runs: RunStore, topic_id: str) -> None:
    result = runs.write_outline_prompt(topic_id)
    result.response_path.write_text(_guide_outline_response(), encoding="utf-8")
    runs.approve_stage(topic_id, "outline")


# --------------------------------------------------------------------------
# Deferred imports of the not-yet-written API. Called from inside test bodies
# so collection of this file never fails.
# --------------------------------------------------------------------------


def _dp():
    """The new ``education_pipeline.draft_parts`` module."""

    from education_pipeline import draft_parts

    return draft_parts


def _frame_part():
    return _dp().FRAME


def _module_part(module_id: str):
    return _dp().DraftPart("module", module_id)


# --------------------------------------------------------------------------
# Run builders.
# --------------------------------------------------------------------------


def _create_run(tmp_path: Path, *, strategy: str | None = "modular", topic_id: str = TID) -> RunStore:
    TopicStore(tmp_path).save_topic_toml(topic_id, TOPIC_TOML)
    runs = RunStore(tmp_path)
    kwargs = {} if strategy is None else {"draft_strategy": strategy}
    runs.create_run(
        topic_id,
        content_contract=ContentContract.interactive_guide_v1(),
        **kwargs,
    )
    return runs


def _contract_module_ids(runs: RunStore, topic_id: str = TID) -> tuple[str, ...]:
    """Module ids in *contract* order: the order in inputs/guide-contract.json."""

    path = runs.run_dir(topic_id) / "inputs" / "guide-contract.json"
    if path.is_file():
        return tuple(json.loads(path.read_text(encoding="utf-8"))["modules"])
    return tuple(sorted(VALID_OUTLINE_CONTRACT["modules"]))


def _frame_text(module_ids, *, description: str | None = None) -> str:
    """The fixture guide with every module's sections emptied (a frame)."""

    frame = dict(GUIDE)
    frame["modules"] = [
        {
            **{k: v for k, v in MODULES_BY_ID[module_id].items() if k != "sections"},
            "sections": [],
        }
        for module_id in module_ids
    ]
    if description is not None:
        frame["course"] = dict(GUIDE["course"], description=description)
    return json.dumps(frame, indent=2, sort_keys=True) + "\n"


def _module_text(module_id: str) -> str:
    return json.dumps(MODULES_BY_ID[module_id], indent=2, sort_keys=True) + "\n"


def _drive_to_outline_approved(tmp_path: Path, *, strategy: str = "modular") -> RunStore:
    runs = _create_run(tmp_path, strategy=strategy)
    _drive_guide_spec_to_approved(runs, TID)
    _drive_guide_outline_to_approved(runs, TID)
    return runs


def _drive_to_frame_prompted(tmp_path: Path) -> RunStore:
    runs = _drive_to_outline_approved(tmp_path)
    runs.write_draft_part_prompts(TID)
    return runs


def _drive_to_frame_responded(tmp_path: Path) -> RunStore:
    runs = _drive_to_frame_prompted(tmp_path)
    ids = _contract_module_ids(runs)
    runs.ingest_part_response(TID, _frame_part(), _frame_text(ids))
    return runs


def _drive_to_modules_prompted(tmp_path: Path) -> RunStore:
    runs = _drive_to_frame_responded(tmp_path)
    runs.write_draft_part_prompts(TID)
    return runs


def _drive_all_parts_responded(tmp_path: Path) -> RunStore:
    runs = _drive_to_modules_prompted(tmp_path)
    for module_id in _contract_module_ids(runs):
        runs.ingest_part_response(TID, _module_part(module_id), _module_text(module_id))
    return runs


def _drive_to_assembled(tmp_path: Path) -> RunStore:
    runs = _drive_all_parts_responded(tmp_path)
    runs.assemble_draft(TID)
    return runs


# --------------------------------------------------------------------------
# Small readers.
# --------------------------------------------------------------------------


def _next(runs: RunStore, topic_id: str = TID) -> tuple[str | None, str, str | None]:
    action = runs.run_status(topic_id).next_action
    return (action.stage, action.action, action.wave)


def _next_detail(runs: RunStore, topic_id: str = TID) -> str:
    return runs.run_status(topic_id).next_action.detail


def _events(runs: RunStore, topic_id: str = TID) -> list[dict]:
    return [e for e in runs.read_manifest(topic_id)["events"] if isinstance(e, dict)]


def _part_key(event: dict) -> str | None:
    part = event.get("part")
    if not isinstance(part, dict):
        return None
    if part.get("kind") == "frame":
        return "frame"
    return f"module:{part.get('module_id')}"


def _latest_part_event(
    runs: RunStore, action: str, part_key: str, topic_id: str = TID
) -> dict | None:
    for event in reversed(_events(runs, topic_id)):
        if event.get("stage") == "draft" and event.get("action") == action:
            if _part_key(event) == part_key:
                return event
    return None


def _module_status(status, module_id: str):
    for part_status in status.modules:
        if part_status.part.module_id == module_id:
            return part_status
    raise AssertionError(f"no module part {module_id!r} in {status.modules!r}")


def _stage(runs: RunStore, stage: str, topic_id: str = TID) -> StageStatus:
    return {s.stage: s for s in runs.run_status(topic_id).stages}[stage]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ==========================================================================
# create_run / draft_strategy (D1)
# ==========================================================================


def test_create_run_defaults_to_whole_strategy(tmp_path: Path) -> None:
    runs = _create_run(tmp_path, strategy=None)
    assert runs.draft_strategy(TID) == "whole"


def test_create_run_records_modular_strategy_on_the_manifest(tmp_path: Path) -> None:
    runs = _create_run(tmp_path)
    assert runs.read_manifest(TID)["draft_strategy"] == "modular"
    assert runs.draft_strategy(TID) == "modular"


def test_create_run_rejects_unknown_draft_strategy(tmp_path: Path) -> None:
    TopicStore(tmp_path).save_topic_toml(TID, TOPIC_TOML)
    runs = RunStore(tmp_path)
    with pytest.raises(ConfigError):
        runs.create_run(
            TID,
            content_contract=ContentContract.interactive_guide_v1(),
            draft_strategy="per-section",
        )


def test_create_run_rejects_modular_on_a_legacy_markdown_run(tmp_path: Path) -> None:
    TopicStore(tmp_path).save_topic_toml(TID, TOPIC_TOML)
    runs = RunStore(tmp_path)
    with pytest.raises(ConfigError):
        runs.create_run(
            TID,
            content_contract=ContentContract.legacy_markdown(),
            draft_strategy="modular",
        )


def test_create_run_without_strategy_leaves_an_existing_one_unchanged(tmp_path: Path) -> None:
    runs = _create_run(tmp_path)
    runs.create_run(TID)
    assert runs.draft_strategy(TID) == "modular"


def test_create_run_with_the_same_strategy_is_a_no_op(tmp_path: Path) -> None:
    runs = _create_run(tmp_path)
    runs.create_run(TID, draft_strategy="modular")
    assert runs.draft_strategy(TID) == "modular"


def test_create_run_with_a_conflicting_strategy_raises(tmp_path: Path) -> None:
    runs = _create_run(tmp_path)
    with pytest.raises(ConfigError):
        runs.create_run(TID, draft_strategy="whole")


def test_draft_strategy_reads_whole_for_a_manifest_without_the_key(tmp_path: Path) -> None:
    runs = _create_run(tmp_path, strategy=None)
    manifest_path = runs.manifest_path(TID)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.pop("draft_strategy", None)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    assert runs.draft_strategy(TID) == "whole"


def test_run_modes_expose_a_modular_capability_flag() -> None:
    from education_pipeline import run_modes

    assert run_modes.InteractiveGuideMode.supports_modular_draft is True
    assert run_modes.LegacyMarkdownMode.supports_modular_draft is False


def test_draft_part_value_types_are_exported_from_the_package() -> None:
    import education_pipeline as pkg

    for name in ("DraftPart", "PartStatus", "DraftPartsStatus", "PartPaths"):
        assert hasattr(pkg, name), name


# ==========================================================================
# DraftPart value type (D3/D4)
# ==========================================================================


def test_draft_part_key_and_from_key_roundtrip() -> None:
    dp = _dp()
    assert dp.FRAME.key == "frame"
    assert dp.DraftPart("module", "loop-basics").key == "module:loop-basics"
    assert dp.DraftPart.from_key("frame") == dp.FRAME
    assert dp.DraftPart.from_key("module:loop-basics") == dp.DraftPart("module", "loop-basics")


def test_draft_part_manifest_roundtrip() -> None:
    dp = _dp()
    assert dp.FRAME.to_manifest() == {"kind": "frame"}
    module = dp.DraftPart("module", "loop-basics")
    assert module.to_manifest() == {"kind": "module", "module_id": "loop-basics"}
    assert dp.DraftPart.from_manifest(module.to_manifest()) == module
    assert dp.DraftPart.from_manifest({"kind": "frame"}) == dp.FRAME


# ==========================================================================
# Part paths (D3)
# ==========================================================================


def test_draft_part_paths_for_the_frame(tmp_path: Path) -> None:
    runs = _drive_to_outline_approved(tmp_path)
    paths = runs.draft_part_paths(TID, _frame_part())
    run = runs.run_dir(TID)
    assert paths.prompt_path == run / "prompts" / "draft" / "frame.prompt.md"
    assert paths.response_path == run / "responses" / "draft" / "frame.response.json"
    assert paths.stub_path == run / "responses" / "draft" / "frame.SAVE_RESPONSE_HERE.json"


def test_draft_part_paths_for_a_module(tmp_path: Path) -> None:
    runs = _drive_to_frame_prompted(tmp_path)
    paths = runs.draft_part_paths(TID, _module_part("loop-basics"))
    run = runs.run_dir(TID)
    assert paths.prompt_path == run / "prompts" / "draft" / "modules" / "loop-basics.prompt.md"
    assert (
        paths.response_path
        == run / "responses" / "draft" / "modules" / "loop-basics.response.json"
    )
    assert (
        paths.stub_path
        == run / "responses" / "draft" / "modules" / "loop-basics.SAVE_RESPONSE_HERE.json"
    )


def test_draft_part_paths_rejects_an_unknown_module_id(tmp_path: Path) -> None:
    runs = _drive_to_frame_prompted(tmp_path)
    with pytest.raises(ConfigError):
        runs.draft_part_paths(TID, _module_part("no-such-module"))


def test_draft_part_paths_rejects_a_whole_strategy_run(tmp_path: Path) -> None:
    runs = _drive_to_outline_approved(tmp_path, strategy="whole")
    with pytest.raises(ConfigError):
        runs.draft_part_paths(TID, _frame_part())


# ==========================================================================
# draft_parts snapshot
# ==========================================================================


def test_draft_parts_is_none_on_a_whole_run(tmp_path: Path) -> None:
    runs = _drive_to_outline_approved(tmp_path, strategy="whole")
    _dp()  # the new module must exist for this assertion to mean anything
    assert runs.draft_parts(TID) is None


def test_draft_parts_before_the_outline_is_approved_has_no_modules(tmp_path: Path) -> None:
    runs = _create_run(tmp_path)
    _drive_guide_spec_to_approved(runs, TID)
    status = runs.draft_parts(TID)
    assert status.module_ids == ()
    assert status.frame.state == "missing"


def test_draft_parts_states_after_the_frame_wave(tmp_path: Path) -> None:
    runs = _drive_to_frame_prompted(tmp_path)
    status = runs.draft_parts(TID)
    assert status.strategy == "modular"
    assert set(status.module_ids) == {"loop-basics", "intervention-practice"}
    assert status.frame.state == "prompted"
    assert all(part.state == "missing" for part in status.modules)
    assert status.assembled == "absent"
    assert status.wave == "frame"


def test_draft_parts_states_once_every_part_is_responded(tmp_path: Path) -> None:
    runs = _drive_all_parts_responded(tmp_path)
    status = runs.draft_parts(TID)
    assert status.frame.state == "responded"
    assert [part.state for part in status.modules] == ["responded", "responded"]
    assert status.assembled == "absent"
    assert status.assembled_stale is True
    assert status.wave == "modules"


def test_a_fresh_run_store_reports_the_same_draft_parts(tmp_path: Path) -> None:
    runs = _drive_all_parts_responded(tmp_path)
    before = runs.draft_parts(TID)
    after = RunStore(tmp_path).draft_parts(TID)
    assert after == before


# ==========================================================================
# write_draft_prompt refusal + the frame wave (D1/D4)
# ==========================================================================


def test_write_draft_prompt_refuses_a_modular_run(tmp_path: Path) -> None:
    runs = _drive_to_outline_approved(tmp_path)
    _dp()
    with pytest.raises(ConfigError) as excinfo:
        runs.write_draft_prompt(TID)
    assert "write_draft_part_prompts" in str(excinfo.value)


def test_write_draft_part_prompts_requires_an_approved_outline(tmp_path: Path) -> None:
    runs = _create_run(tmp_path)
    _drive_guide_spec_to_approved(runs, TID)
    with pytest.raises(ConfigError):
        runs.write_draft_part_prompts(TID)


def test_frame_wave_writes_the_frame_prompt_the_stub_and_the_contract(tmp_path: Path) -> None:
    runs = _drive_to_outline_approved(tmp_path)
    written = runs.write_draft_part_prompts(TID)
    assert [prompt.stage for prompt in written] == ["draft"]
    paths = runs.draft_part_paths(TID, _frame_part())
    assert paths.prompt_path.is_file()
    assert paths.stub_path.is_file()
    assert not paths.response_path.exists()
    contract_path = runs.run_dir(TID) / "inputs" / "guide-contract.json"
    assert contract_path.is_file()
    assert set(json.loads(contract_path.read_text(encoding="utf-8"))["modules"]) == {
        "loop-basics",
        "intervention-practice",
    }


def test_frame_prompt_written_event_shape(tmp_path: Path) -> None:
    runs = _drive_to_frame_prompted(tmp_path)
    event = _latest_part_event(runs, "prompt_written", "frame")
    assert event is not None
    assert event["part"] == {"kind": "frame"}
    assert event["prompt_file"] == "prompts/draft/frame.prompt.md"
    assert event["response_file"] == "responses/draft/frame.response.json"
    assert event["source_outline_file_sha256"] == _sha(
        runs.stage_paths(TID, "outline").approved_path
    )
    assert event["contract_file_sha256"] == _sha(
        runs.run_dir(TID) / "inputs" / "guide-contract.json"
    )
    assert "frame_file_sha256" not in event


def test_frame_wave_rejects_a_parts_argument(tmp_path: Path) -> None:
    runs = _drive_to_outline_approved(tmp_path)
    with pytest.raises(ConfigError):
        runs.write_draft_part_prompts(TID, parts=["loop-basics"])


# ==========================================================================
# Frame ingest (D4)
# ==========================================================================


def test_ingest_frame_response_writes_the_file_removes_the_stub_and_logs(tmp_path: Path) -> None:
    runs = _drive_to_frame_prompted(tmp_path)
    ids = _contract_module_ids(runs)
    written = runs.ingest_part_response(TID, _frame_part(), _frame_text(ids))
    paths = runs.draft_part_paths(TID, _frame_part())
    assert written == paths.response_path
    assert paths.response_path.read_text(encoding="utf-8") == _frame_text(ids)
    assert not paths.stub_path.exists()
    event = _latest_part_event(runs, "response_ingested", "frame")
    assert event is not None
    assert event["part"] == {"kind": "frame"}
    assert event["response_file"] == "responses/draft/frame.response.json"
    assert event["response_file_sha256"] == _sha(paths.response_path)


def test_ingest_frame_rejects_a_stub_with_sections(tmp_path: Path) -> None:
    runs = _drive_to_frame_prompted(tmp_path)
    ids = _contract_module_ids(runs)
    frame = json.loads(_frame_text(ids))
    frame["modules"][0]["sections"] = [{"id": "x", "title": "X", "blocks": []}]
    with pytest.raises(ConfigError):
        runs.ingest_part_response(TID, _frame_part(), json.dumps(frame))


def test_ingest_frame_rejects_modules_out_of_contract_order(tmp_path: Path) -> None:
    runs = _drive_to_frame_prompted(tmp_path)
    ids = _contract_module_ids(runs)
    frame = json.loads(_frame_text(tuple(reversed(ids))))
    with pytest.raises(ConfigError):
        runs.ingest_part_response(TID, _frame_part(), json.dumps(frame))


def test_ingest_frame_rejects_empty_text(tmp_path: Path) -> None:
    runs = _drive_to_frame_prompted(tmp_path)
    with pytest.raises(ConfigError):
        runs.ingest_part_response(TID, _frame_part(), "   \n")


def test_ingest_frame_twice_without_force_raises(tmp_path: Path) -> None:
    runs = _drive_to_frame_responded(tmp_path)
    ids = _contract_module_ids(runs)
    with pytest.raises(ConfigError):
        runs.ingest_part_response(TID, _frame_part(), _frame_text(ids))


def test_ingest_frame_with_force_records_response_replaced(tmp_path: Path) -> None:
    runs = _drive_to_frame_responded(tmp_path)
    ids = _contract_module_ids(runs)
    replacement = _frame_text(ids, description="A revised course description.")
    runs.ingest_part_response(TID, _frame_part(), replacement, force=True)
    paths = runs.draft_part_paths(TID, _frame_part())
    assert paths.response_path.read_text(encoding="utf-8") == replacement
    replaced = _latest_part_event(runs, "response_replaced", "frame")
    assert replaced is not None
    assert replaced["part"] == {"kind": "frame"}


# ==========================================================================
# The modules wave (D4)
# ==========================================================================


def test_modules_wave_writes_one_prompt_per_module(tmp_path: Path) -> None:
    runs = _drive_to_frame_responded(tmp_path)
    written = runs.write_draft_part_prompts(TID)
    assert len(written) == 2
    for module_id in ("loop-basics", "intervention-practice"):
        assert runs.draft_part_paths(TID, _module_part(module_id)).prompt_path.is_file()
        assert runs.draft_part_paths(TID, _module_part(module_id)).stub_path.is_file()


def test_module_prompt_written_event_binds_frame_and_contract_module(tmp_path: Path) -> None:
    runs = _drive_to_modules_prompted(tmp_path)
    contract = json.loads(
        (runs.run_dir(TID) / "inputs" / "guide-contract.json").read_text(encoding="utf-8")
    )
    for module_id in ("loop-basics", "intervention-practice"):
        event = _latest_part_event(runs, "prompt_written", f"module:{module_id}")
        assert event is not None, module_id
        assert event["part"] == {"kind": "module", "module_id": module_id}
        assert event["prompt_file"] == f"prompts/draft/modules/{module_id}.prompt.md"
        assert event["response_file"] == f"responses/draft/modules/{module_id}.response.json"
        assert event["frame_file_sha256"] == _sha(
            runs.draft_part_paths(TID, _frame_part()).response_path
        )
        assert event["contract_file_sha256"] == _sha(
            runs.run_dir(TID) / "inputs" / "guide-contract.json"
        )
        expected = hashlib.sha256(
            json.dumps(
                contract["modules"][module_id], sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest()
        assert event["contract_module_sha256"] == expected


def test_modules_wave_parts_subset_writes_only_that_module(tmp_path: Path) -> None:
    runs = _drive_to_frame_responded(tmp_path)
    written = runs.write_draft_part_prompts(TID, parts=["loop-basics"])
    assert len(written) == 1
    assert runs.draft_part_paths(TID, _module_part("loop-basics")).prompt_path.is_file()
    assert not runs.draft_part_paths(
        TID, _module_part("intervention-practice")
    ).prompt_path.exists()


def test_modules_wave_rejects_an_unknown_part_id(tmp_path: Path) -> None:
    runs = _drive_to_frame_responded(tmp_path)
    with pytest.raises(ConfigError):
        runs.write_draft_part_prompts(TID, parts=["no-such-module"])


def test_modules_wave_rejects_frame_in_the_parts_filter(tmp_path: Path) -> None:
    runs = _drive_to_frame_responded(tmp_path)
    with pytest.raises(ConfigError):
        runs.write_draft_part_prompts(TID, parts=["frame"])


def test_modules_wave_skips_current_parts_and_overwrite_rewrites_all(tmp_path: Path) -> None:
    runs = _drive_to_modules_prompted(tmp_path)
    assert runs.write_draft_part_prompts(TID) == ()
    assert len(runs.write_draft_part_prompts(TID, overwrite=True)) == 2


# ==========================================================================
# Module ingest (D4)
# ==========================================================================


def test_ingest_module_response_writes_the_file_and_logs(tmp_path: Path) -> None:
    runs = _drive_to_modules_prompted(tmp_path)
    part = _module_part("loop-basics")
    written = runs.ingest_part_response(TID, part, _module_text("loop-basics"))
    paths = runs.draft_part_paths(TID, part)
    assert written == paths.response_path
    assert not paths.stub_path.exists()
    event = _latest_part_event(runs, "response_ingested", "module:loop-basics")
    assert event is not None
    assert event["part"] == {"kind": "module", "module_id": "loop-basics"}
    assert event["response_file_sha256"] == _sha(paths.response_path)


def test_ingest_module_rejects_a_renamed_module(tmp_path: Path) -> None:
    runs = _drive_to_modules_prompted(tmp_path)
    renamed = dict(MODULES_BY_ID["loop-basics"], id="something-else")
    with pytest.raises(ConfigError):
        runs.ingest_part_response(TID, _module_part("loop-basics"), json.dumps(renamed))


def test_ingest_module_rejects_a_whole_guide_payload(tmp_path: Path) -> None:
    runs = _drive_to_modules_prompted(tmp_path)
    with pytest.raises(ConfigError):
        runs.ingest_part_response(TID, _module_part("loop-basics"), GUIDE_FIXTURE)


def test_ingest_module_rejects_empty_text(tmp_path: Path) -> None:
    runs = _drive_to_modules_prompted(tmp_path)
    with pytest.raises(ConfigError):
        runs.ingest_part_response(TID, _module_part("loop-basics"), "")


def test_ingest_module_twice_without_force_raises(tmp_path: Path) -> None:
    runs = _drive_all_parts_responded(tmp_path)
    with pytest.raises(ConfigError):
        runs.ingest_part_response(TID, _module_part("loop-basics"), _module_text("loop-basics"))


# ==========================================================================
# next_action table (D5) -- asserted as (stage, action, wave)
# ==========================================================================


def test_next_action_frame_write_prompt(tmp_path: Path) -> None:
    runs = _drive_to_outline_approved(tmp_path)
    _dp()
    assert _next(runs) == ("draft", "write_prompt", "frame")


def test_next_action_frame_save_response_names_the_frame_path(tmp_path: Path) -> None:
    runs = _drive_to_frame_prompted(tmp_path)
    assert _next(runs) == ("draft", "save_response", "frame")
    response_path = runs.draft_part_paths(TID, _frame_part()).response_path
    assert str(response_path) in _next_detail(runs)


def test_next_action_modules_write_prompt_lists_the_module_ids(tmp_path: Path) -> None:
    runs = _drive_to_frame_responded(tmp_path)
    assert _next(runs) == ("draft", "write_prompt", "modules")
    detail = _next_detail(runs)
    assert "loop-basics" in detail and "intervention-practice" in detail


def test_next_action_modules_save_response_counts_the_waiting_modules(tmp_path: Path) -> None:
    runs = _drive_to_modules_prompted(tmp_path)
    runs.ingest_part_response(
        TID, _module_part("loop-basics"), _module_text("loop-basics")
    )
    assert _next(runs) == ("draft", "save_response", "modules")
    detail = _next_detail(runs)
    assert "1 of 2" in detail
    assert "intervention-practice" in detail


def test_next_action_assemble_once_every_part_is_responded(tmp_path: Path) -> None:
    runs = _drive_all_parts_responded(tmp_path)
    assert _next(runs) == ("draft", "assemble", "modules")


def test_next_action_after_assembly_falls_through_with_no_wave(tmp_path: Path) -> None:
    runs = _drive_to_assembled(tmp_path)
    stage, action, wave = _next(runs)
    assert (stage, wave) == ("draft", None)
    assert action in {"approve", "validate"}


def test_next_action_for_an_edited_assembly_never_says_assemble(tmp_path: Path) -> None:
    runs = _drive_to_assembled(tmp_path)
    response_path = runs.stage_paths(TID, "draft").response_path
    edited = json.loads(response_path.read_text(encoding="utf-8"))
    edited["course"]["description"] = "Hand-edited after assembly."
    runs.edit_response(
        TID,
        "draft",
        json.dumps(edited, indent=2, sort_keys=True) + "\n",
        base_sha256=_sha(response_path),
    )
    assert runs.draft_parts(TID).assembled == "edited"
    stage, action, wave = _next(runs)
    assert (stage, wave) == ("draft", None)
    assert action != "assemble"


def test_next_action_returns_to_the_frame_wave_when_the_frame_prompt_is_stale(
    tmp_path: Path,
) -> None:
    runs = _drive_to_frame_prompted(tmp_path)
    contract_path = runs.run_dir(TID) / "inputs" / "guide-contract.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    contract["estimated_minutes"] = 45
    contract_path.write_text(json.dumps(contract, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    assert runs.draft_parts(TID).frame.state == "stale"
    assert _next(runs) == ("draft", "write_prompt", "frame")


def test_whole_run_next_actions_carry_no_wave(tmp_path: Path) -> None:
    runs = _drive_to_outline_approved(tmp_path, strategy="whole")
    _dp()
    assert _next(runs) == ("draft", "write_prompt", None)


# ==========================================================================
# assemble_draft (D3)
# ==========================================================================


def test_assemble_writes_the_bytes_assemble_guide_produces(tmp_path: Path) -> None:
    runs = _drive_all_parts_responded(tmp_path)
    ids = _contract_module_ids(runs)
    written = runs.assemble_draft(TID)
    assert written == runs.stage_paths(TID, "draft").response_path
    expected = assemble_guide(
        _frame_text(ids),
        {module_id: _module_text(module_id) for module_id in ids},
        module_ids=ids,
    )
    assert written.read_bytes() == expected


def test_assemble_records_the_part_shas_on_a_draft_assembled_event(tmp_path: Path) -> None:
    runs = _drive_to_assembled(tmp_path)
    event = next(
        e
        for e in reversed(_events(runs))
        if e.get("stage") == "draft" and e.get("action") == "draft_assembled"
    )
    response_path = runs.stage_paths(TID, "draft").response_path
    assert event["response_file"] == "responses/draft.response.json"
    assert event["response_file_sha256"] == _sha(response_path)
    assert event["parts"]["frame"] == _sha(
        runs.draft_part_paths(TID, _frame_part()).response_path
    )
    assert event["parts"]["modules"] == {
        module_id: _sha(runs.draft_part_paths(TID, _module_part(module_id)).response_path)
        for module_id in _contract_module_ids(runs)
    }


def test_assemble_refuses_while_a_module_response_is_missing(tmp_path: Path) -> None:
    runs = _drive_to_modules_prompted(tmp_path)
    runs.ingest_part_response(
        TID, _module_part("loop-basics"), _module_text("loop-basics")
    )
    with pytest.raises(ConfigError) as excinfo:
        runs.assemble_draft(TID)
    assert "intervention-practice" in str(excinfo.value)


def test_assemble_removes_the_whole_stage_stub_and_reports_matches_record(
    tmp_path: Path,
) -> None:
    runs = _drive_to_assembled(tmp_path)
    assert not runs.stage_paths(TID, "draft").stub_path.exists()
    status = runs.draft_parts(TID)
    assert status.assembled == "matches_record"
    assert status.assembled_stale is False
    assert status.wave is None


def test_reassembling_after_a_hand_edit_raises_stale_content_error(tmp_path: Path) -> None:
    runs = _drive_to_assembled(tmp_path)
    response_path = runs.stage_paths(TID, "draft").response_path
    edited = json.loads(response_path.read_text(encoding="utf-8"))
    edited["course"]["description"] = "Hand-edited after assembly."
    runs.edit_response(
        TID,
        "draft",
        json.dumps(edited, indent=2, sort_keys=True) + "\n",
        base_sha256=_sha(response_path),
    )
    with pytest.raises(StaleContentError):
        runs.assemble_draft(TID)


def test_forced_reassembly_after_a_hand_edit_records_response_replaced(tmp_path: Path) -> None:
    runs = _drive_to_assembled(tmp_path)
    response_path = runs.stage_paths(TID, "draft").response_path
    edited = json.loads(response_path.read_text(encoding="utf-8"))
    edited["course"]["description"] = "Hand-edited after assembly."
    runs.edit_response(
        TID,
        "draft",
        json.dumps(edited, indent=2, sort_keys=True) + "\n",
        base_sha256=_sha(response_path),
    )
    runs.assemble_draft(TID, force=True)
    ids = _contract_module_ids(runs)
    expected = assemble_guide(
        _frame_text(ids),
        {module_id: _module_text(module_id) for module_id in ids},
        module_ids=ids,
    )
    assert response_path.read_bytes() == expected
    assert any(
        e.get("stage") == "draft" and e.get("action") == "response_replaced"
        for e in _events(runs)
    )


def test_reassembling_an_unchanged_assembly_is_allowed(tmp_path: Path) -> None:
    runs = _drive_to_assembled(tmp_path)
    before = runs.stage_paths(TID, "draft").response_path.read_bytes()
    runs.assemble_draft(TID)
    assert runs.stage_paths(TID, "draft").response_path.read_bytes() == before


# ==========================================================================
# Per-part staleness (D4)
# ==========================================================================


def test_reapproving_the_outline_unchanged_keeps_every_module_current(tmp_path: Path) -> None:
    runs = _drive_all_parts_responded(tmp_path)
    outline = runs.write_outline_prompt(TID, overwrite=True)
    outline.response_path.write_text(_guide_outline_response(), encoding="utf-8")
    runs.approve_stage(TID, "outline", overwrite=True)
    status = runs.draft_parts(TID)
    assert [part.state for part in status.modules] == ["responded", "responded"]
    assert runs.write_draft_part_prompts(TID) == ()


def test_a_changed_contract_entry_stales_only_that_module(tmp_path: Path) -> None:
    runs = _drive_all_parts_responded(tmp_path)
    contract_path = runs.run_dir(TID) / "inputs" / "guide-contract.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    contract["modules"]["intervention-practice"]["estimated_minutes"] = 21
    contract_path.write_text(
        json.dumps(contract, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    status = runs.draft_parts(TID)
    assert _module_status(status, "intervention-practice").state == "stale"
    assert _module_status(status, "loop-basics").state == "responded"


def test_a_replaced_frame_response_stales_every_module(tmp_path: Path) -> None:
    runs = _drive_all_parts_responded(tmp_path)
    ids = _contract_module_ids(runs)
    runs.ingest_part_response(
        TID,
        _frame_part(),
        _frame_text(ids, description="A revised course description."),
        force=True,
    )
    status = runs.draft_parts(TID)
    assert [part.state for part in status.modules] == ["stale", "stale"]
    assert _next(runs) == ("draft", "write_prompt", "modules")


def test_a_stale_assembly_is_reported_when_a_part_response_changes(tmp_path: Path) -> None:
    runs = _drive_to_assembled(tmp_path)
    module_paths = runs.draft_part_paths(TID, _module_part("loop-basics"))
    module = dict(MODULES_BY_ID["loop-basics"], summary="A revised module summary.")
    runs.ingest_part_response(
        TID, _module_part("loop-basics"), json.dumps(module), force=True
    )
    assert module_paths.response_path.is_file()
    assert runs.draft_parts(TID).assembled_stale is True


# ==========================================================================
# stage_status, advance, end to end (D4/D5)
# ==========================================================================


def test_stage_status_prompt_written_tracks_the_required_part_prompts(tmp_path: Path) -> None:
    runs = _drive_to_frame_prompted(tmp_path)
    draft = _stage(runs, "draft")
    assert (draft.prompt_written, draft.response_ingested, draft.approved) == (
        True,
        False,
        False,
    )

    ids = _contract_module_ids(runs)
    runs.ingest_part_response(TID, _frame_part(), _frame_text(ids))
    draft = _stage(runs, "draft")
    assert (draft.prompt_written, draft.response_ingested) == (False, False)

    runs.write_draft_part_prompts(TID)
    draft = _stage(runs, "draft")
    assert (draft.prompt_written, draft.response_ingested) == (True, False)


def test_stage_status_response_ingested_tracks_the_assembled_file(tmp_path: Path) -> None:
    runs = _drive_all_parts_responded(tmp_path)
    assert _stage(runs, "draft").response_ingested is False
    runs.assemble_draft(TID)
    draft = _stage(runs, "draft")
    assert (draft.prompt_written, draft.response_ingested, draft.approved) == (
        True,
        True,
        False,
    )


def test_advance_writes_the_frame_prompt_then_the_module_prompts(tmp_path: Path) -> None:
    runs = _drive_to_outline_approved(tmp_path)
    _dp()

    first = runs.advance(TID)
    assert first.performed == "write_prompt"
    assert runs.draft_part_paths(TID, _frame_part()).prompt_path.is_file()

    ids = _contract_module_ids(runs)
    runs.ingest_part_response(TID, _frame_part(), _frame_text(ids))

    second = runs.advance(TID)
    assert second.performed == "write_prompt"
    assert all(
        runs.draft_part_paths(TID, _module_part(module_id)).prompt_path.is_file()
        for module_id in ids
    )
    assert second.status.next_action.wave == "modules"


def test_advance_performs_the_assembly_step(tmp_path: Path) -> None:
    runs = _drive_all_parts_responded(tmp_path)
    result = runs.advance(TID)
    assert result.performed == "assemble"
    assert runs.stage_paths(TID, "draft").response_path.is_file()
    assert (result.status.next_action.stage, result.status.next_action.wave) == ("draft", None)


def test_advance_drives_the_waves_end_to_end_and_the_run_continues_to_qa(
    tmp_path: Path,
) -> None:
    runs = _drive_to_outline_approved(tmp_path)
    _dp()

    assert runs.advance(TID).performed == "write_prompt"  # frame wave
    ids = _contract_module_ids(runs)
    runs.ingest_part_response(TID, _frame_part(), _frame_text(ids))

    assert runs.advance(TID).performed == "write_prompt"  # modules wave
    for module_id in ids:
        runs.ingest_part_response(TID, _module_part(module_id), _module_text(module_id))

    assert runs.advance(TID).performed == "assemble"
    assert _next(runs) == ("draft", "approve", None)

    runs.approve_stage(TID, "draft")
    assert runs.advance(TID).performed == "validate"
    assert _next(runs) == ("qa", "write_prompt", None)
