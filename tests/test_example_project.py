"""Pinning tests for the shipped synthetic example project (PRD §10 P2).

``examples/feedback-loops/`` is a complete synthetic guide-v1 project:
topic, learner profile, every stage response, and the exported offline
guide. ``scripts/build_example.py`` regenerates the export by driving a
real run in a temporary workspace; engine exports are byte-deterministic
(see ``test_release_gate_acceptance``), so the committed artifacts must
match a regeneration exactly.
"""

import importlib.util
import json
from pathlib import Path

EXAMPLE_DIR = Path("examples/feedback-loops")
EXPORT_HTML = EXAMPLE_DIR / "export" / "guide.html"
EXPORT_REPORT = EXAMPLE_DIR / "export" / "guide.report.json"

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


def test_committed_export_matches_a_regeneration(tmp_path: Path) -> None:
    html, report = _builder().build_export(EXAMPLE_DIR, tmp_path / "workspace")
    assert EXPORT_HTML.read_bytes() == html
    assert EXPORT_REPORT.read_bytes() == report


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
    guide = json.loads(
        (EXAMPLE_DIR / "responses" / "draft.guide.json").read_text(encoding="utf-8")
    )
    block_types = {
        block["type"]
        for module in guide["modules"]
        for section in module["sections"]
        for block in section["blocks"]
    }
    assert SUPPORTED_INTERACTIONS <= block_types


def test_draft_and_repair_ship_identical_content() -> None:
    """The example models a clean run: QA found nothing, so the repair
    response re-submits the draft guide unchanged."""

    draft = (EXAMPLE_DIR / "responses" / "draft.guide.json").read_bytes()
    repair = (EXAMPLE_DIR / "responses" / "repair.guide.json").read_bytes()
    assert draft == repair
