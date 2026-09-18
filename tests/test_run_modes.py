"""Tests for the per-mode strategy seam behind ``RunStore._mode``.

These pin the dispatch itself -- which strategy a run resolves to, and which
capabilities each strategy advertises -- not the pipeline behavior the
strategies implement, which the characterization suites already cover.
"""

from __future__ import annotations

from pathlib import Path

from education_pipeline import ContentContract, RunStore
from education_pipeline import stage_graph
from education_pipeline.run_modes import (
    INTERACTIVE_GUIDE_MODE,
    LEGACY_MARKDOWN_MODE,
    InteractiveGuideMode,
    LegacyMarkdownMode,
    mode_for_kind,
)


def _legacy_store(tmp_path: Path, topic_id: str = "systems-thinking") -> RunStore:
    runs = RunStore(tmp_path)
    runs.create_run(topic_id, content_contract=ContentContract.legacy_markdown())
    return runs


def _guide_store(tmp_path: Path, topic_id: str = "systems-thinking") -> RunStore:
    runs = RunStore(tmp_path)
    runs.create_run(topic_id)
    return runs


def test_mode_resolves_legacy_strategy_for_a_legacy_contract(tmp_path: Path) -> None:
    runs = _legacy_store(tmp_path)

    assert isinstance(runs._mode("systems-thinking"), LegacyMarkdownMode)


def test_mode_resolves_guide_strategy_for_a_default_run(tmp_path: Path) -> None:
    runs = _guide_store(tmp_path)

    assert isinstance(runs._mode("systems-thinking"), InteractiveGuideMode)


def test_mode_is_the_strategy_registered_for_the_contract_kind(tmp_path: Path) -> None:
    """The dispatch reads the contract kind and nothing else."""

    legacy = _legacy_store(tmp_path / "legacy")
    guide = _guide_store(tmp_path / "guide")

    assert legacy._mode("systems-thinking") is LEGACY_MARKDOWN_MODE
    assert guide._mode("systems-thinking") is INTERACTIVE_GUIDE_MODE


def test_unknown_contract_kinds_resume_as_legacy_markdown() -> None:
    """Matches the pre-strategy test: anything but the guide kind was legacy."""

    assert mode_for_kind("legacy_markdown") is LEGACY_MARKDOWN_MODE
    assert mode_for_kind("interactive_guide") is INTERACTIVE_GUIDE_MODE
    assert mode_for_kind("something-else") is LEGACY_MARKDOWN_MODE


def test_strategy_graph_modes_are_exactly_the_stage_graph_modes() -> None:
    graph_modes = {LEGACY_MARKDOWN_MODE.graph_mode, INTERACTIVE_GUIDE_MODE.graph_mode}

    assert graph_modes == set(stage_graph.MODES)
    assert LEGACY_MARKDOWN_MODE.graph_mode == LEGACY_MARKDOWN_MODE.name
    assert INTERACTIVE_GUIDE_MODE.graph_mode == INTERACTIVE_GUIDE_MODE.name


def test_capability_flags_differ_between_the_two_modes() -> None:
    guide_only = (
        "binds_sources",
        "prompt_overwrite_on_advance",
        "scoped_repair_on_approve",
        "supports_validation",
        "supports_factcheck",
        "supports_module_repair",
        "supports_audit",
    )
    for flag in guide_only:
        assert getattr(INTERACTIVE_GUIDE_MODE, flag) is True, flag
        assert getattr(LEGACY_MARKDOWN_MODE, flag) is False, flag

    # The one capability that runs the other way: only legacy exports Markdown.
    assert LEGACY_MARKDOWN_MODE.supports_markdown_export is True
    assert INTERACTIVE_GUIDE_MODE.supports_markdown_export is False


def test_required_stages_follow_the_resolved_graph_mode(tmp_path: Path) -> None:
    legacy = _legacy_store(tmp_path / "legacy")
    guide = _guide_store(tmp_path / "guide")

    assert legacy.required_stages("systems-thinking") == stage_graph.required_stages(
        LEGACY_MARKDOWN_MODE.graph_mode
    )
    assert guide.required_stages("systems-thinking") == stage_graph.required_stages(
        INTERACTIVE_GUIDE_MODE.graph_mode
    )
