"""Failing (red) tests for thread T22 "RunStore module lifecycle".

Per-module drafting design:
docs/superpowers/specs/2026-09-18-per-module-drafting-design.md
(decisions 1, 6-9; sections Sec1 "on-disk layout and manifest" and Sec4
"engine lifecycle").

These tests drive the new unit-level draft machinery -- ``draft_unit_paths``,
``write_module_draft_prompts``, ``ingest_draft_unit``/``edit_draft_unit``,
``assemble_draft`` and ``draft_progress`` -- none of which exist yet on
``RunStore``. Every name that does not exist yet is imported inside the test
function that needs it, so collecting this file does not fail outright; a
call to a not-yet-existing ``RunStore`` method raises ``AttributeError`` at
test run time instead, which is exactly what "red" means here.

``tests/`` has no ``__init__.py`` (see ``test_characterization_guide_v1.py``'s
module docstring), but ``import test_runs`` works because pytest puts each
test file's directory on ``sys.path``; several other test files already rely
on this (``test_cli.py``, ``test_server.py``, ...), so this file reuses
``test_runs``'s guide-run fixtures/helpers rather than recopying them.

A note on module ids: ``test_runs.VALID_OUTLINE_CONTRACT`` has exactly one
module (``feedback-loops``), but the committed guide fixture
(``tests/fixtures/guides/feedback-loops.guide.json``) has two
(``loop-basics``, ``intervention-practice``) -- and this thread needs at
least two modules to exercise "k of N" progress and per-module staleness.
So every test here drives spec/outline approval through
``FIXTURE_SPEC_CONTRACT``/``FIXTURE_OUTLINE_CONTRACT`` below, whose module
map lists exactly the fixture's two module ids, in the fixture's authored
order, with outcome/interaction data lifted straight from the fixture (the
same contract ``tests/test_prompts.py`` already pins for the skeleton/module
prompt tests, under the names ``_MODULE_DRAFT_SPEC_CONTRACT`` /
``_MODULE_DRAFT_OUTLINE_CONTRACT``).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import test_runs as tr

from education_pipeline import ConfigError, RunStore, StaleContentError


# --------------------------------------------------------------------------
# Fixtures and small helpers.
# --------------------------------------------------------------------------

TID = "systems-thinking"

FIXTURE_DATA = json.loads(tr.GUIDE_FIXTURE)
MODULE_ORDER = tuple(module["id"] for module in FIXTURE_DATA["modules"])
assert MODULE_ORDER == ("loop-basics", "intervention-practice")

FIXTURE_SPEC_CONTRACT = dict(
    tr.VALID_SPEC_CONTRACT,
    outcomes=[dict(outcome) for outcome in FIXTURE_DATA["outcomes"]],
)

FIXTURE_OUTLINE_CONTRACT = {
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


def _create_guide_run(tmp_path: Path, topic_id: str = TID) -> RunStore:
    return tr._create_guide_run(tmp_path, topic_id)


def _drive_to_outline_approved(runs: RunStore, topic_id: str = TID) -> None:
    """Approve spec + outline with the fixture's two-module contract."""

    spec = runs.write_topic_spec_prompt(topic_id)
    spec.response_path.write_text(
        tr._guide_spec_response(FIXTURE_SPEC_CONTRACT), encoding="utf-8"
    )
    runs.approve_stage(topic_id, "spec")
    outline = runs.write_outline_prompt(topic_id)
    outline.response_path.write_text(
        tr._guide_outline_response(FIXTURE_OUTLINE_CONTRACT), encoding="utf-8"
    )
    runs.approve_stage(topic_id, "outline")


def _skeleton_response(data: dict | None = None) -> str:
    data = data if data is not None else FIXTURE_DATA
    skeleton = json.loads(json.dumps(data))
    skeleton["modules"] = [
        {
            **{key: value for key, value in module.items() if key != "sections"},
            "sections": [],
        }
        for module in data["modules"]
    ]
    return json.dumps(skeleton, ensure_ascii=False)


def _module_response(module_id: str, data: dict | None = None) -> str:
    data = data if data is not None else FIXTURE_DATA
    module = next(m for m in data["modules"] if m["id"] == module_id)
    return json.dumps(module, ensure_ascii=False)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _events(runs: RunStore, topic_id: str, action: str, *, unit: str | None = None) -> list[dict]:
    events = [
        event
        for event in runs.read_manifest(topic_id).get("events", [])
        if event.get("stage") == "draft" and event.get("action") == action
    ]
    if unit is not None:
        events = [event for event in events if event.get("unit") == unit]
    return events


def _run_to_outline_approved(tmp_path: Path, topic_id: str = TID) -> RunStore:
    runs = _create_guide_run(tmp_path, topic_id)
    _drive_to_outline_approved(runs, topic_id)
    return runs


def _run_with_skeleton_prompt(tmp_path: Path, topic_id: str = TID) -> RunStore:
    runs = _run_to_outline_approved(tmp_path, topic_id)
    runs.write_draft_prompt(topic_id)
    return runs


def _write_skeleton_response_directly(
    runs: RunStore, topic_id: str, text: str | None = None
) -> None:
    """Land a skeleton response on disk without going through ``ingest_draft_unit``.

    Used by the "Writers" tests below to exercise ``write_module_draft_prompts``
    in isolation from decision 9's ingest-triggered auto-write.
    """

    paths = runs.draft_unit_paths(topic_id, "skeleton")
    paths.response_path.parent.mkdir(parents=True, exist_ok=True)
    paths.response_path.write_text(
        text if text is not None else _skeleton_response(), encoding="utf-8"
    )


def _run_with_skeleton_response_on_disk(tmp_path: Path, topic_id: str = TID) -> RunStore:
    runs = _run_with_skeleton_prompt(tmp_path, topic_id)
    _write_skeleton_response_directly(runs, topic_id)
    return runs


def _run_with_skeleton_ingested(tmp_path: Path, topic_id: str = TID) -> RunStore:
    """Ingest a valid skeleton response, which (decision 9) auto-writes module prompts."""

    runs = _run_with_skeleton_prompt(tmp_path, topic_id)
    runs.ingest_draft_unit(topic_id, "skeleton", _skeleton_response())
    return runs


def _run_with_one_module_saved(
    tmp_path: Path, topic_id: str = TID, module_id: str = "loop-basics"
) -> RunStore:
    runs = _run_with_skeleton_ingested(tmp_path, topic_id)
    runs.ingest_draft_unit(topic_id, "module", _module_response(module_id), module_id=module_id)
    return runs


def _run_fully_assembled(tmp_path: Path, topic_id: str = TID) -> RunStore:
    runs = _run_with_one_module_saved(tmp_path, topic_id, "loop-basics")
    runs.ingest_draft_unit(
        topic_id, "module", _module_response("intervention-practice"),
        module_id="intervention-practice",
    )
    return runs


# --------------------------------------------------------------------------
# Layout: RunStore.draft_unit_paths
# --------------------------------------------------------------------------


def test_draft_unit_paths_skeleton_layout(tmp_path: Path) -> None:
    runs = _run_to_outline_approved(tmp_path)

    paths = runs.draft_unit_paths(TID, "skeleton")

    run = runs.run_dir(TID)
    assert paths.unit == "skeleton"
    assert paths.module_id is None
    assert paths.prompt_path == run / "draft" / "skeleton" / "prompt.md"
    assert paths.response_path == run / "draft" / "skeleton" / "response.json"
    assert paths.stub_path == run / "draft" / "skeleton" / "SAVE_RESPONSE_HERE.json"
    assert paths.previous_path == run / "draft" / "skeleton" / "response.previous.json"


def test_draft_unit_paths_module_layout(tmp_path: Path) -> None:
    runs = _run_to_outline_approved(tmp_path)

    paths = runs.draft_unit_paths(TID, "module", module_id="loop-basics")

    run = runs.run_dir(TID)
    assert paths.unit == "module"
    assert paths.module_id == "loop-basics"
    base = run / "draft" / "modules" / "loop-basics"
    assert paths.prompt_path == base / "prompt.md"
    assert paths.response_path == base / "response.json"
    assert paths.stub_path == base / "SAVE_RESPONSE_HERE.json"
    assert paths.previous_path == base / "response.previous.json"


def test_draft_unit_paths_module_requires_module_id(tmp_path: Path) -> None:
    runs = _run_to_outline_approved(tmp_path)

    with pytest.raises(ConfigError):
        runs.draft_unit_paths(TID, "module")


def test_draft_unit_paths_rejects_invalid_module_id(tmp_path: Path) -> None:
    runs = _run_to_outline_approved(tmp_path)

    with pytest.raises(ConfigError):
        runs.draft_unit_paths(TID, "module", module_id="not a valid id")


def test_draft_unit_paths_rejects_unknown_unit(tmp_path: Path) -> None:
    runs = _run_to_outline_approved(tmp_path)

    with pytest.raises(ConfigError):
        runs.draft_unit_paths(TID, "chapter")


@pytest.mark.parametrize(
    "call",
    [
        lambda runs: runs.draft_unit_paths(TID, "skeleton"),
        lambda runs: runs.draft_unit_paths(TID, "module", module_id="loop-basics"),
    ],
    ids=["skeleton", "module"],
)
def test_draft_unit_paths_refused_on_legacy_run(tmp_path: Path, call) -> None:
    runs = tr._create_legacy_run(tmp_path, TID)

    with pytest.raises(ConfigError):
        call(runs)


# --------------------------------------------------------------------------
# Writers: write_draft_prompt (skeleton) and write_module_draft_prompts
# --------------------------------------------------------------------------


def test_write_draft_prompt_keeps_writing_the_stage_level_files(tmp_path: Path) -> None:
    runs = _run_to_outline_approved(tmp_path)

    result = runs.write_draft_prompt(TID)

    stage_paths = runs.stage_paths(TID, "draft")
    assert result.prompt_path == stage_paths.prompt_path
    assert result.response_path == stage_paths.response_path
    assert result.prompt_path.is_file()
    assert result.stub_path.is_file()


def test_write_draft_prompt_also_writes_the_skeleton_unit(tmp_path: Path) -> None:
    runs = _run_to_outline_approved(tmp_path)

    runs.write_draft_prompt(TID)

    paths = runs.draft_unit_paths(TID, "skeleton")
    assert paths.prompt_path.is_file()
    assert paths.stub_path.is_file()
    assert not paths.response_path.exists()


def test_write_draft_prompt_records_skeleton_unit_prompt_written_event(tmp_path: Path) -> None:
    runs = _run_to_outline_approved(tmp_path)

    runs.write_draft_prompt(TID)

    events = _events(runs, TID, "unit_prompt_written", unit="skeleton")
    assert len(events) == 1
    event = events[0]
    outline_bytes = runs.stage_paths(TID, "outline").approved_path.read_bytes()
    contract_bytes = (runs.run_dir(TID) / "inputs" / "guide-contract.json").read_bytes()
    assert event["prompt_file"] == "draft/skeleton/prompt.md"
    assert event["response_file"] == "draft/skeleton/response.json"
    assert event["source_outline_file_sha256"] == hashlib.sha256(outline_bytes).hexdigest()
    assert event["contract_file_sha256"] == hashlib.sha256(contract_bytes).hexdigest()
    assert "recorded_at" in event


def test_write_draft_prompt_stage_stub_mentions_the_unit_path(tmp_path: Path) -> None:
    runs = _run_to_outline_approved(tmp_path)

    runs.write_draft_prompt(TID)

    stub_text = runs.stage_paths(TID, "draft").stub_path.read_text(encoding="utf-8")
    assert "draft/skeleton" in stub_text


def test_write_draft_prompt_on_legacy_run_creates_no_draft_unit_directory(tmp_path: Path) -> None:
    # tr._create_legacy_run does not save the topic artifact, and the legacy
    # outline/draft writers load it (test_runs' own legacy cases save it too).
    tr.TopicStore(tmp_path).save_topic_toml(TID, tr.TOPIC_TOML)
    runs = tr._create_legacy_run(tmp_path, TID)
    tr._drive_spec_to_approved(runs, TID)
    tr._drive_outline_to_approved(runs, TID)

    runs.write_draft_prompt(TID)

    assert not (runs.run_dir(TID) / "draft").exists()


def test_write_module_draft_prompts_requires_a_skeleton_response(tmp_path: Path) -> None:
    runs = _run_with_skeleton_prompt(tmp_path)

    with pytest.raises(ConfigError):
        runs.write_module_draft_prompts(TID)


def test_write_module_draft_prompts_requires_the_skeleton_to_pass_check_skeleton(
    tmp_path: Path,
) -> None:
    invalid = json.loads(_skeleton_response())
    del invalid["modules"][1]  # drop the intervention-practice stub
    runs = _run_with_skeleton_prompt(tmp_path)
    _write_skeleton_response_directly(runs, TID, json.dumps(invalid, ensure_ascii=False))

    with pytest.raises(ConfigError) as excinfo:
        runs.write_module_draft_prompts(TID)

    assert "skeleton.missing_module" in str(excinfo.value)


def test_write_module_draft_prompts_writes_every_contract_module_in_outline_order(
    tmp_path: Path,
) -> None:
    runs = _run_with_skeleton_response_on_disk(tmp_path)

    result = runs.write_module_draft_prompts(TID)

    assert tuple(paths.module_id for paths in result) == MODULE_ORDER
    for paths, module_id in zip(result, MODULE_ORDER):
        assert paths.unit == "module"
        assert paths.prompt_path.is_file()
        assert paths.stub_path.is_file()
        assert paths.prompt_path == runs.draft_unit_paths(TID, "module", module_id=module_id).prompt_path


def test_write_module_draft_prompts_accepts_a_module_ids_subset(tmp_path: Path) -> None:
    runs = _run_with_skeleton_response_on_disk(tmp_path)

    result = runs.write_module_draft_prompts(TID, module_ids=["loop-basics"])

    assert [paths.module_id for paths in result] == ["loop-basics"]
    assert runs.draft_unit_paths(TID, "module", module_id="loop-basics").prompt_path.is_file()
    assert not runs.draft_unit_paths(
        TID, "module", module_id="intervention-practice"
    ).prompt_path.exists()


def test_write_module_draft_prompts_rejects_module_id_outside_the_contract(
    tmp_path: Path,
) -> None:
    runs = _run_with_skeleton_response_on_disk(tmp_path)

    with pytest.raises(ConfigError):
        runs.write_module_draft_prompts(TID, module_ids=["no-such-module"])


def test_write_module_draft_prompts_records_unit_prompt_written_event_fields(
    tmp_path: Path,
) -> None:
    runs = _run_with_skeleton_response_on_disk(tmp_path)
    skeleton_bytes = runs.draft_unit_paths(TID, "skeleton").response_path.read_bytes()

    runs.write_module_draft_prompts(TID)

    events = {
        event["module_id"]: event
        for event in _events(runs, TID, "unit_prompt_written", unit="module")
    }
    assert set(events) == set(MODULE_ORDER)
    for module_id, event in events.items():
        assert event["prompt_file"] == f"draft/modules/{module_id}/prompt.md"
        assert event["response_file"] == f"draft/modules/{module_id}/response.json"
        assert isinstance(event["contract_entry_sha256"], str) and event["contract_entry_sha256"]
        assert isinstance(event["skeleton_stub_sha256"], str) and event["skeleton_stub_sha256"]
        assert event["skeleton_response_sha256"] == hashlib.sha256(skeleton_bytes).hexdigest()
    # Different module entries hash differently.
    assert events["loop-basics"]["contract_entry_sha256"] != (
        events["intervention-practice"]["contract_entry_sha256"]
    )


def test_write_module_draft_prompts_refuses_existing_prompt_without_overwrite(
    tmp_path: Path,
) -> None:
    runs = _run_with_skeleton_response_on_disk(tmp_path)
    runs.write_module_draft_prompts(TID)

    with pytest.raises(ConfigError):
        runs.write_module_draft_prompts(TID, module_ids=["loop-basics"])


def test_write_module_draft_prompts_overwrite_rewrites(tmp_path: Path) -> None:
    runs = _run_with_skeleton_response_on_disk(tmp_path)
    runs.write_module_draft_prompts(TID)
    before = len(_events(runs, TID, "unit_prompt_written", unit="module"))

    result = runs.write_module_draft_prompts(TID, module_ids=["loop-basics"], overwrite=True)

    assert [paths.module_id for paths in result] == ["loop-basics"]
    after = len(_events(runs, TID, "unit_prompt_written", unit="module"))
    assert after == before + 1


# --------------------------------------------------------------------------
# Ingest: ingest_draft_unit / edit_draft_unit
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "unit, module_id",
    [("skeleton", None), ("module", "loop-basics")],
    ids=["skeleton", "module"],
)
def test_ingest_draft_unit_rejects_empty_text(tmp_path: Path, unit: str, module_id: str | None) -> None:
    runs = _run_with_skeleton_response_on_disk(tmp_path)
    runs.write_module_draft_prompts(TID)

    with pytest.raises(ConfigError):
        runs.ingest_draft_unit(TID, unit, "   \n", module_id=module_id)


def test_ingest_draft_unit_writes_response_and_removes_stub(tmp_path: Path) -> None:
    runs = _run_with_skeleton_prompt(tmp_path)

    paths = runs.ingest_draft_unit(TID, "skeleton", _skeleton_response())

    assert paths.response_path.is_file()
    assert paths.response_path.read_text(encoding="utf-8") == _skeleton_response()
    assert not paths.stub_path.exists()


def test_ingest_draft_unit_refuses_existing_response_without_force(tmp_path: Path) -> None:
    runs = _run_with_skeleton_prompt(tmp_path)
    runs.ingest_draft_unit(TID, "skeleton", _skeleton_response())

    with pytest.raises(ConfigError):
        runs.ingest_draft_unit(TID, "skeleton", _skeleton_response())


def test_ingest_draft_unit_force_moves_previous_and_records_event(tmp_path: Path) -> None:
    runs = _run_with_skeleton_prompt(tmp_path)
    original = _skeleton_response()
    runs.ingest_draft_unit(TID, "skeleton", original)
    revised_data = json.loads(original)
    revised_data["course"]["subtitle"] = "A revised subtitle"
    revised = json.dumps(revised_data, ensure_ascii=False)

    paths = runs.ingest_draft_unit(TID, "skeleton", revised, force=True)

    assert paths.response_path.read_text(encoding="utf-8") == revised
    assert paths.previous_path.read_text(encoding="utf-8") == original
    events = _events(runs, TID, "unit_response_replaced", unit="skeleton")
    assert len(events) == 1
    event = events[0]
    assert event["response_file"] == "draft/skeleton/response.json"
    assert event["response_sha256"] == _sha256(revised)
    assert event["previous_sha256"] == _sha256(original)


def test_skeleton_ingest_auto_writes_module_prompts(tmp_path: Path) -> None:
    runs = _run_with_skeleton_prompt(tmp_path)

    runs.ingest_draft_unit(TID, "skeleton", _skeleton_response())

    for module_id in MODULE_ORDER:
        assert runs.draft_unit_paths(TID, "module", module_id=module_id).prompt_path.is_file()


def test_skeleton_ingest_failing_check_skeleton_stores_text_without_module_prompts(
    tmp_path: Path,
) -> None:
    invalid = json.loads(_skeleton_response())
    invalid["modules"][0]["sections"] = [FIXTURE_DATA["modules"][0]["sections"][0]]
    invalid_text = json.dumps(invalid, ensure_ascii=False)
    runs = _run_with_skeleton_prompt(tmp_path)

    runs.ingest_draft_unit(TID, "skeleton", invalid_text)

    assert (
        runs.draft_unit_paths(TID, "skeleton").response_path.read_text(encoding="utf-8")
        == invalid_text
    )
    for module_id in MODULE_ORDER:
        assert not runs.draft_unit_paths(TID, "module", module_id=module_id).prompt_path.exists()
    progress = runs.draft_progress(TID)
    assert progress.skeleton.error is not None
    assert "skeleton." in progress.skeleton.error


def test_module_ingest_does_not_assemble_while_modules_are_outstanding(tmp_path: Path) -> None:
    runs = _run_with_one_module_saved(tmp_path, module_id="loop-basics")

    stage_paths = runs.stage_paths(TID, "draft")
    assert not stage_paths.response_path.exists()
    assert not _events(runs, TID, "draft_assembly_failed")
    progress = runs.draft_progress(TID)
    assert progress.assembled is None


def test_module_ingest_assembles_the_whole_guide_once_every_module_is_saved(
    tmp_path: Path,
) -> None:
    from education_pipeline.guides.canonical import assemble_guide

    runs = _run_fully_assembled(tmp_path)

    stage_paths = runs.stage_paths(TID, "draft")
    expected = assemble_guide(
        _skeleton_response(),
        {module_id: _module_response(module_id) for module_id in MODULE_ORDER},
        module_order=MODULE_ORDER,
    )
    assert stage_paths.response_path.read_bytes() == expected
    events = _events(runs, TID, "draft_assembled")
    assert len(events) == 1
    event = events[0]
    assert event["response_file"] == "responses/draft.response.json"
    assert event["response_sha256"] == hashlib.sha256(expected).hexdigest()
    assert event["skeleton_sha256"] == _sha256(_skeleton_response())
    assert event["module_ids"] == list(MODULE_ORDER)
    assert event["module_sha256"] == {
        module_id: _sha256(_module_response(module_id)) for module_id in MODULE_ORDER
    }
    progress = runs.draft_progress(TID)
    assert progress.assembled is not None
    assert progress.assembled.ok is True
    assert progress.assembled.response_sha256 == hashlib.sha256(expected).hexdigest()
    assert progress.assembled.error is None
    assert progress.superseded is False


def test_module_ingest_assembly_failure_on_renamed_module_id(tmp_path: Path) -> None:
    runs = _run_with_one_module_saved(tmp_path, module_id="loop-basics")
    renamed = json.loads(_module_response("intervention-practice"))
    renamed["id"] = "intervention-practice-renamed"

    runs.ingest_draft_unit(
        TID, "module", json.dumps(renamed, ensure_ascii=False), module_id="intervention-practice"
    )

    stage_paths = runs.stage_paths(TID, "draft")
    assert not stage_paths.response_path.exists()
    events = _events(runs, TID, "draft_assembly_failed")
    assert len(events) == 1
    event = events[0]
    assert "intervention-practice" in event["error"]
    assert "intervention-practice" in event["module_ids"]
    progress = runs.draft_progress(TID)
    assert progress.assembled is not None
    assert progress.assembled.ok is False
    assert "intervention-practice" in progress.assembled.error


def test_edit_draft_unit_stale_content_error(tmp_path: Path) -> None:
    runs = _run_with_skeleton_prompt(tmp_path)
    runs.ingest_draft_unit(TID, "skeleton", _skeleton_response())

    with pytest.raises(StaleContentError):
        runs.edit_draft_unit(TID, "skeleton", _skeleton_response(), base_sha256="0" * 64)


def test_edit_draft_unit_success_records_event(tmp_path: Path) -> None:
    runs = _run_with_skeleton_prompt(tmp_path)
    original = _skeleton_response()
    runs.ingest_draft_unit(TID, "skeleton", original)
    base_sha256 = _sha256(original)
    revised_data = json.loads(original)
    revised_data["course"]["subtitle"] = "Edited subtitle"
    revised = json.dumps(revised_data, ensure_ascii=False)

    runs.edit_draft_unit(TID, "skeleton", revised, base_sha256=base_sha256)

    paths = runs.draft_unit_paths(TID, "skeleton")
    assert paths.response_path.read_text(encoding="utf-8") == revised
    events = _events(runs, TID, "unit_response_edited", unit="skeleton")
    assert len(events) == 1
    event = events[0]
    assert event["response_sha256"] == _sha256(revised)
    assert event["base_sha256"] == base_sha256


# --------------------------------------------------------------------------
# Assembly: assemble_draft
# --------------------------------------------------------------------------


def test_assemble_draft_reports_outstanding_modules_and_writes_nothing(tmp_path: Path) -> None:
    runs = _run_with_one_module_saved(tmp_path, module_id="loop-basics")

    result = runs.assemble_draft(TID)

    assert result.ok is False
    assert result.response_sha256 is None
    assert "intervention-practice" in result.error
    assert result.module_ids == ("intervention-practice",)
    assert not runs.stage_paths(TID, "draft").response_path.exists()


def test_assemble_draft_is_idempotent_once_everything_is_saved(tmp_path: Path) -> None:
    runs = _run_fully_assembled(tmp_path)
    first = runs.stage_paths(TID, "draft").response_path.read_bytes()

    result = runs.assemble_draft(TID)

    assert result.ok is True
    assert result.response_sha256 == hashlib.sha256(first).hexdigest()
    assert runs.stage_paths(TID, "draft").response_path.read_bytes() == first


def test_assemble_draft_refuses_a_hand_edited_response_without_force(tmp_path: Path) -> None:
    runs = _run_fully_assembled(tmp_path)
    stage_paths = runs.stage_paths(TID, "draft")
    hand_edited = tr.GUIDE_FIXTURE.replace(
        "Learn to recognize feedback", "Hand-edited course description"
    )
    stage_paths.response_path.write_text(hand_edited, encoding="utf-8")

    with pytest.raises(StaleContentError):
        runs.assemble_draft(TID)


def test_assemble_draft_force_overwrites_and_records_response_replaced(tmp_path: Path) -> None:
    from education_pipeline.guides.canonical import assemble_guide

    runs = _run_fully_assembled(tmp_path)
    stage_paths = runs.stage_paths(TID, "draft")
    hand_edited = tr.GUIDE_FIXTURE.replace(
        "Learn to recognize feedback", "Hand-edited course description"
    )
    stage_paths.response_path.write_text(hand_edited, encoding="utf-8")
    hand_edited_sha = hashlib.sha256(hand_edited.encode("utf-8")).hexdigest()

    result = runs.assemble_draft(TID, force=True)

    expected = assemble_guide(
        _skeleton_response(),
        {module_id: _module_response(module_id) for module_id in MODULE_ORDER},
        module_order=MODULE_ORDER,
    )
    assert result.ok is True
    assert stage_paths.response_path.read_bytes() == expected
    events = [
        event
        for event in runs.read_manifest(TID).get("events", [])
        if event.get("stage") == "draft" and event.get("action") == "response_replaced"
    ]
    assert len(events) == 1
    assert events[0].get("replaced_response_file_sha256") == hand_edited_sha


def test_assemble_draft_success_removes_stub_and_never_approves(tmp_path: Path) -> None:
    runs = _run_fully_assembled(tmp_path)

    stage_paths = runs.stage_paths(TID, "draft")
    assert not stage_paths.stub_path.exists()
    assert not stage_paths.approved_path.exists()
    next_action = runs.run_status(TID).next_action
    assert (next_action.stage, next_action.action) == ("draft", "approve")


# --------------------------------------------------------------------------
# Progress: draft_progress
# --------------------------------------------------------------------------


def test_draft_progress_before_any_prompt(tmp_path: Path) -> None:
    runs = _run_to_outline_approved(tmp_path)

    progress = runs.draft_progress(TID)

    assert progress.skeleton.state == "not_run"
    assert progress.modules == ()
    assert progress.total == 0
    assert progress.saved == 0
    assert progress.stale == 0
    assert progress.assembled is None
    assert progress.superseded is False


def test_draft_progress_after_skeleton_prompt_only(tmp_path: Path) -> None:
    runs = _run_with_skeleton_prompt(tmp_path)

    progress = runs.draft_progress(TID)

    assert progress.skeleton.state == "prompt_written"
    assert progress.modules == ()
    assert progress.total == 0


def test_draft_progress_after_skeleton_response(tmp_path: Path) -> None:
    runs = _run_with_skeleton_ingested(tmp_path)

    progress = runs.draft_progress(TID)

    assert progress.skeleton.state == "response_ingested"
    assert [module.module_id for module in progress.modules] == list(MODULE_ORDER)
    assert [module.title for module in progress.modules] == [
        FIXTURE_DATA["modules"][0]["title"],
        FIXTURE_DATA["modules"][1]["title"],
    ]
    assert all(module.state == "prompt_written" for module in progress.modules)
    assert progress.total == 2
    assert progress.saved == 0


def test_draft_progress_after_one_module_response(tmp_path: Path) -> None:
    runs = _run_with_one_module_saved(tmp_path, module_id="loop-basics")

    progress = runs.draft_progress(TID)
    by_id = {module.module_id: module for module in progress.modules}

    assert by_id["loop-basics"].state == "response_ingested"
    assert by_id["intervention-practice"].state == "prompt_written"
    assert progress.saved == 1
    assert progress.total == 2


def test_draft_progress_marks_the_changed_module_stale_after_forced_skeleton_reingest(
    tmp_path: Path,
) -> None:
    runs = _run_with_skeleton_ingested(tmp_path)
    revised = json.loads(_skeleton_response())
    revised["modules"][1]["title"] = "Retitled module stub"
    runs.ingest_draft_unit(
        TID, "skeleton", json.dumps(revised, ensure_ascii=False), force=True
    )

    progress = runs.draft_progress(TID)
    by_id = {module.module_id: module for module in progress.modules}

    assert by_id["loop-basics"].state == "prompt_written"
    assert by_id["intervention-practice"].state == "stale"
    assert progress.stale == 1


def test_draft_progress_marks_a_module_stale_when_its_contract_entry_changes(
    tmp_path: Path,
) -> None:
    runs = _run_with_skeleton_ingested(tmp_path)
    contract_path = runs.run_dir(TID) / "inputs" / "guide-contract.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    contract["modules"]["loop-basics"]["estimated_minutes"] = 999
    contract_path.write_text(json.dumps(contract), encoding="utf-8")

    progress = runs.draft_progress(TID)
    by_id = {module.module_id: module for module in progress.modules}

    assert by_id["loop-basics"].state == "stale"
    assert by_id["intervention-practice"].state == "prompt_written"


def test_draft_progress_reports_an_orphaned_module_directory(tmp_path: Path) -> None:
    runs = _run_with_skeleton_ingested(tmp_path)
    orphan_dir = runs.run_dir(TID) / "draft" / "modules" / "orphan-module"
    orphan_dir.mkdir(parents=True)
    (orphan_dir / "response.json").write_text("{}", encoding="utf-8")

    progress = runs.draft_progress(TID)

    orphan = next((m for m in progress.modules if m.module_id == "orphan-module"), None)
    assert orphan is not None
    assert orphan.state == "orphaned"


def test_draft_progress_superseded_when_a_whole_guide_is_dropped_by_hand(tmp_path: Path) -> None:
    runs = _run_fully_assembled(tmp_path)
    stage_paths = runs.stage_paths(TID, "draft")
    stage_paths.response_path.write_text(tr.GUIDE_FIXTURE + "\n", encoding="utf-8")

    progress = runs.draft_progress(TID)

    assert progress.superseded is True
    assert all(module.state == "superseded" for module in progress.modules)


def test_draft_progress_saved_and_stale_counts_together(tmp_path: Path) -> None:
    runs = _run_with_one_module_saved(tmp_path, module_id="loop-basics")
    revised = json.loads(_skeleton_response())
    revised["modules"][1]["title"] = "Retitled again"
    runs.ingest_draft_unit(
        TID, "skeleton", json.dumps(revised, ensure_ascii=False), force=True
    )

    progress = runs.draft_progress(TID)

    assert progress.total == 2
    assert progress.saved == 1
    assert progress.stale == 1


# --------------------------------------------------------------------------
# Resume: a fresh RunStore over the same workspace agrees.
# --------------------------------------------------------------------------


def test_resume_from_a_fresh_runstore_matches_progress_and_next_action(tmp_path: Path) -> None:
    runs = _run_with_one_module_saved(tmp_path, module_id="loop-basics")
    progress_before = runs.draft_progress(TID)
    next_action_before = runs.run_status(TID).next_action

    fresh = RunStore(tmp_path)
    progress_after = fresh.draft_progress(TID)
    next_action_after = fresh.run_status(TID).next_action

    assert progress_after == progress_before
    assert (next_action_after.stage, next_action_after.action, next_action_after.detail) == (
        next_action_before.stage,
        next_action_before.action,
        next_action_before.detail,
    )
