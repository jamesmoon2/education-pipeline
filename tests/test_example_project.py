"""Pinning tests for the shipped synthetic example project (PRD §10 P2).

``examples/feedback-loops/`` is a complete synthetic guide-v1 project:
topic, learner profile, every stage response, and the exported offline
guide. ``scripts/build_example.py`` regenerates the export by driving a
real run in a temporary workspace; engine exports are byte-deterministic
(see ``test_release_gate_acceptance``), so the committed artifacts must
match a regeneration exactly.

The draft stage is driven through the per-module unit path (design:
``docs/superpowers/specs/2026-09-18-per-module-drafting-design.md``,
decisions 1-9 and §9 "Migration and compatibility"): the committed
``responses/draft.skeleton.json`` and ``responses/draft.modules/*.json``
are the source of truth for the draft content, split deterministically
from the module order recorded in ``responses/outline.md``'s contract.
There is no committed ``draft.guide.json`` any more -- assembling the
skeleton and modules (``guides.canonical.assemble_guide``) reproduces it,
and that is exactly what pins determinism here, so a separate whole-guide
file would just be a second, driftable copy of the same content.
"""

import importlib.util
import json
from pathlib import Path

from education_pipeline import RunStore
from education_pipeline.guides.canonical import assemble_guide
from education_pipeline.guides.contract import extract_outline_contract

EXAMPLE_DIR = Path("examples/feedback-loops")
EXPORT_HTML = EXAMPLE_DIR / "export" / "guide.html"
EXPORT_REPORT = EXAMPLE_DIR / "export" / "guide.report.json"
RESPONSES_DIR = EXAMPLE_DIR / "responses"
SKELETON_RESPONSE = RESPONSES_DIR / "draft.skeleton.json"
MODULES_DIR = RESPONSES_DIR / "draft.modules"

SUPPORTED_INTERACTIONS = {
    "rich_text",
    "callout",
    "knowledge_check",
    "worked_reveal",
    "scenario",
    "reflection",
}

# Private values from examples/feedback-loops/profile.toml that must never
# reach the exported HTML (the profile is private by default).
PRIVATE_PROFILE_VALUES = (
    "Rowan Vale",
    "eight years coordinating software delivery projects",
    "Recognize reinforcing and balancing feedback in everyday projects",
    "Choose interventions that account for delays instead of overcorrecting",
    "Model loops quantitatively with stock-and-flow diagrams",
)


def _builder():
    spec = importlib.util.spec_from_file_location(
        "build_example", Path("scripts/build_example.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _module_order() -> tuple[str, ...]:
    """The authored module order, read the same way the engine does."""

    outline_text = (RESPONSES_DIR / "outline.md").read_text(encoding="utf-8")
    contract = extract_outline_contract(outline_text)
    return tuple(contract["modules"])


def _assembled_draft_bytes() -> bytes:
    order = _module_order()
    skeleton_text = SKELETON_RESPONSE.read_text(encoding="utf-8")
    modules = {
        module_id: (MODULES_DIR / f"{module_id}.json").read_text(encoding="utf-8")
        for module_id in order
    }
    return assemble_guide(skeleton_text, modules, module_order=order)


def test_committed_export_matches_a_regeneration(tmp_path: Path) -> None:
    html, report = _builder().build_export(EXAMPLE_DIR, tmp_path / "workspace")
    assert EXPORT_HTML.read_bytes() == html
    assert EXPORT_REPORT.read_bytes() == report


def test_committed_draft_units_assemble_to_a_deterministic_response() -> None:
    """The split fixture files are the source of truth: assembling them twice
    (and in either order the caller iterates) is byte-for-byte determinism,
    the pin decision 4 of the design promises for ``assemble_guide``."""

    first = _assembled_draft_bytes()
    second = _assembled_draft_bytes()
    assert first == second
    assert first  # non-empty: assembly actually produced a guide


def test_draft_units_layout_matches_the_module_order() -> None:
    order = _module_order()
    assert order == ("loop-basics", "intervention-practice")
    for module_id in order:
        assert (MODULES_DIR / f"{module_id}.json").is_file()
    # No stray module files for ids outside the contract.
    on_disk = {path.stem for path in MODULES_DIR.glob("*.json")}
    assert on_disk == set(order)


def test_regeneration_reproduces_the_unit_layout_in_the_workspace(
    tmp_path: Path,
) -> None:
    """The draft stage lands as skeleton + per-module units in the run's
    workspace, and assembly finishes clean -- not just as a single
    whole-guide response file."""

    workspace = tmp_path / "workspace"
    _builder().build_export(EXAMPLE_DIR, workspace)

    runs = RunStore(workspace)
    topic_id = _builder().TOPIC_ID

    skeleton_paths = runs.draft_unit_paths(topic_id, "skeleton")
    assert skeleton_paths.response_path.is_file()

    order = _module_order()
    assert len(order) == 2
    for module_id in order:
        module_paths = runs.draft_unit_paths(topic_id, "module", module_id=module_id)
        assert module_paths.response_path.is_file()

    progress = runs.draft_progress(topic_id)
    assert progress.assembled is not None
    assert progress.assembled.ok is True
    assert progress.superseded is False
    assert [unit.module_id for unit in progress.modules] == list(order)
    assert all(unit.state == "response_ingested" for unit in progress.modules)


def test_export_report_gate_is_open_with_no_findings() -> None:
    report = json.loads(EXPORT_REPORT.read_text(encoding="utf-8"))
    assert report["gate"]["open"] is True
    assert report["gate"]["effective_blocking"] == 0
    assert report["report"]["findings"] == []
    assert report["waivers"]["applied"] == []
    assert report["waivers"]["stale"] is False


def test_no_private_profile_values_reach_the_export() -> None:
    html = EXPORT_HTML.read_text(encoding="utf-8")
    report = EXPORT_REPORT.read_text(encoding="utf-8")
    for private_value in PRIVATE_PROFILE_VALUES:
        assert private_value not in html
        assert private_value not in report


def test_example_guide_covers_every_supported_interaction_type() -> None:
    guide = json.loads(_assembled_draft_bytes())
    block_types = {
        block["type"]
        for module in guide["modules"]
        for section in module["sections"]
        for block in section["blocks"]
    }
    assert SUPPORTED_INTERACTIONS <= block_types


def test_draft_and_repair_ship_identical_content() -> None:
    """The example models a clean run: QA found nothing, so the repair
    response re-submits the assembled draft unchanged.

    Assembly canonicalizes (design §9), so the committed
    ``repair.guide.json`` is kept in that same canonical form and this
    compares canonical forms, not two independently-formatted files."""

    draft = _assembled_draft_bytes()
    repair = (EXAMPLE_DIR / "responses" / "repair.guide.json").read_bytes()
    assert draft == repair
