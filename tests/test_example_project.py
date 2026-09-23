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


def _blocks_by_section(guide: dict) -> dict[tuple[str, str], list[dict]]:
    return {
        (module["id"], section["id"]): section["blocks"]
        for module in guide["modules"]
        for section in module["sections"]
    }


def test_example_guide_is_schema_1_2() -> None:
    """New runs default to 1.2 (diagram spec decision 3); the example is a
    plain new run, so its contract, skeleton, assembled draft and repair
    response all carry 1.2."""

    assert json.loads(SKELETON_RESPONSE.read_text(encoding="utf-8"))[
        "schema_version"
    ] == "1.2"
    assert json.loads(_assembled_draft_bytes())["schema_version"] == "1.2"
    repair = json.loads(
        (RESPONSES_DIR / "repair.guide.json").read_text(encoding="utf-8")
    )
    assert repair["schema_version"] == "1.2"
    spec_text = (RESPONSES_DIR / "spec.md").read_text(encoding="utf-8")
    assert '"guide_schema_version": "1.2"' in spec_text
    html = EXPORT_HTML.read_text(encoding="utf-8")
    assert 'data-guide-schema="1.2"' in html
    assert 'data-guide-runtime="1.2"' in html


def test_example_guide_carries_a_flow_and_a_comparison_diagram() -> None:
    """Diagram spec §12: a flow with a feedback loop in ``loop-basics`` and a
    comparison in ``intervention-practice``."""

    guide = json.loads(_assembled_draft_bytes())
    diagrams = [
        block
        for module in guide["modules"]
        for section in module["sections"]
        for block in section["blocks"]
        if block["type"] == "diagram"
    ]
    assert {block["kind"] for block in diagrams} == {"flow", "comparison"}

    sections = _blocks_by_section(guide)

    foundations = [b["id"] for b in sections[("loop-basics", "feedback-foundations")]]
    position = foundations.index("loop-introduction")
    assert foundations[position + 1] == "growth-loop-flow"
    flow = sections[("loop-basics", "feedback-foundations")][position + 1]
    assert flow["kind"] == "flow"
    assert flow["outcome_ids"] == ["map-loop"]
    assert [node["id"] for node in flow["nodes"]] == [
        "biomass",
        "leaf-area",
        "sunlight",
        "growth",
    ]
    # The last edge closes the reinforcing loop.
    assert {"from": "growth", "to": "biomass", "label": "adds to"} in flow["edges"]

    delays = [b["id"] for b in sections[("intervention-practice", "delays-and-leverage")]]
    position = delays.index("delay-explanation")
    assert delays[position + 1] == "intervention-comparison"
    comparison = sections[("intervention-practice", "delays-and-leverage")][
        position + 1
    ]
    assert comparison["kind"] == "comparison"
    assert comparison["outcome_ids"] == ["choose-intervention"]
    assert [(item["id"], item["label"]) for item in comparison["items"]] == [
        ("act-again", "Act again right away"),
        ("wait-out", "Wait out the delay"),
    ]
    assert [
        (criterion["id"], criterion["label"], criterion["values"])
        for criterion in comparison["criteria"]
    ] == [
        (
            "first-sign",
            "What you see first",
            {"act-again": "A quick visible change", "wait-out": "Little visible change"},
        ),
        (
            "after-delay",
            "After the delay",
            {"act-again": "*Overshoot* past the goal", "wait-out": "Settles near the goal"},
        ),
        (
            "cost",
            "Main cost",
            {
                "act-again": "Wasted effort and swings",
                "wait-out": "Patience while nothing seems to happen",
            },
        ),
    ]


def test_export_renders_both_diagram_figures() -> None:
    html = EXPORT_HTML.read_text(encoding="utf-8")
    assert 'data-diagram-kind="flow"' in html
    assert 'data-diagram-kind="comparison"' in html
    assert 'id="growth-loop-flow"' in html
    assert 'id="intervention-comparison"' in html
