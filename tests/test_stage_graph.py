"""Tests for the declarative stage graph (education_pipeline.stage_graph).

This module does not exist yet; these tests pin the exact contract the
implementer must build, and pin that education_pipeline/config.py's
stage-topology constants are derived from it.
"""

from __future__ import annotations

import dataclasses
from types import MappingProxyType

import pytest

from education_pipeline.stage_graph import (
    MODES,
    STAGE_BY_NAME,
    STAGES,
    StageSpec,
    dependents_of,
    optional_stages,
    reasoning_stages,
    required_stages,
    source_labels,
    sources_of,
    stage,
    supported_stages,
)
from education_pipeline.config import (
    GUIDE_V1_REQUIRED_STAGES,
    OPTIONAL_STAGES,
    PRESET_STAGES,
    REASONING_STAGES,
    REQUIRED_STAGES,
    STAGE_ORDER,
    SUPPORTED_STAGES,
)
from education_pipeline.runs import RunStore


BOTH_MODES = frozenset({"legacy_markdown", "interactive_guide"})

EXPECTED_TABLE = {
    "spec": dict(
        sources=(),
        content="markdown",
        modes=BOTH_MODES,
        optional=False,
        reasoning=True,
        prompt_writer="write_spec_prompt",
    ),
    "outline": dict(
        sources=(),
        content="markdown",
        modes=BOTH_MODES,
        optional=False,
        reasoning=True,
        prompt_writer="write_outline_prompt",
    ),
    "draft": dict(
        sources=(),
        content="guide",
        modes=BOTH_MODES,
        optional=False,
        reasoning=False,
        prompt_writer="write_draft_prompt",
    ),
    "qa": dict(
        sources=("draft",),
        content="markdown",
        modes=BOTH_MODES,
        optional=False,
        reasoning=False,
        prompt_writer="write_qa_prompt",
    ),
    "factcheck": dict(
        sources=("draft", "qa"),
        content="markdown",
        modes=frozenset({"interactive_guide"}),
        optional=False,
        reasoning=True,
        prompt_writer="write_factcheck_prompt",
    ),
    "repair": dict(
        sources=("draft", "qa", "factcheck"),
        content="guide",
        modes=BOTH_MODES,
        optional=False,
        reasoning=True,
        prompt_writer="write_repair_prompt",
    ),
    "audit": dict(
        sources=(),
        content="json",
        modes=frozenset(),
        optional=True,
        reasoning=False,
        prompt_writer=None,
    ),
}


def test_modes_tuple():
    assert MODES == ("legacy_markdown", "interactive_guide")


def test_stages_order_and_names():
    assert tuple(s.name for s in STAGES) == (
        "spec",
        "outline",
        "draft",
        "qa",
        "factcheck",
        "repair",
        "audit",
    )


@pytest.mark.parametrize("name", list(EXPECTED_TABLE))
def test_stage_spec_matches_expected_table(name: str) -> None:
    expected = EXPECTED_TABLE[name]
    spec = stage(name)
    assert spec.name == name
    assert spec.sources == expected["sources"]
    assert spec.content == expected["content"]
    assert spec.modes == expected["modes"]
    assert spec.optional == expected["optional"]
    assert spec.reasoning == expected["reasoning"]
    assert spec.prompt_writer == expected["prompt_writer"]


def test_stage_by_name_matches_stages_and_expected_table():
    assert dict(STAGE_BY_NAME) == {s.name: s for s in STAGES}
    assert set(STAGE_BY_NAME) == set(EXPECTED_TABLE)


def test_stage_unknown_name_raises_key_error():
    with pytest.raises(KeyError):
        stage("nope")


def test_stage_names_are_unique():
    names = [s.name for s in STAGES]
    assert len(names) == len(set(names))


def test_sources_reference_only_earlier_stages_in_STAGES_order():
    names = [s.name for s in STAGES]
    for idx, spec in enumerate(STAGES):
        for src in spec.sources:
            assert src in names[:idx], (
                f"{spec.name!r} source {src!r} must be an earlier stage in STAGES"
            )


def test_prompt_writers_exist_on_run_store_when_present():
    for spec in STAGES:
        if spec.prompt_writer is not None:
            assert hasattr(RunStore, spec.prompt_writer), (
                f"RunStore has no attribute {spec.prompt_writer!r} for stage {spec.name!r}"
            )


def test_all_stage_modes_are_subset_of_MODES():
    mode_set = set(MODES)
    for spec in STAGES:
        assert spec.modes <= mode_set


def test_stage_by_name_rejects_item_assignment():
    assert isinstance(STAGE_BY_NAME, MappingProxyType)
    with pytest.raises(TypeError):
        STAGE_BY_NAME["spec"] = stage("spec")


def test_stage_spec_is_frozen():
    spec = stage("spec")
    with pytest.raises(dataclasses.FrozenInstanceError):
        spec.name = "changed"  # type: ignore[misc]


def test_sources_of_matches_stage_sources():
    for spec in STAGES:
        assert sources_of(spec.name) == spec.sources


def test_dependents_of_is_transitively_closed_in_STAGES_order():
    assert dependents_of("draft") == ("qa", "factcheck", "repair")
    assert dependents_of("qa") == ("factcheck", "repair")
    assert dependents_of("factcheck") == ("repair",)
    assert dependents_of("repair") == ()
    assert dependents_of("audit") == ()


def test_source_labels_are_manifest_file_labels():
    assert source_labels("repair") == (
        "source_draft_file",
        "source_qa_file",
        "source_factcheck_file",
    )
    assert source_labels("qa") == ("source_draft_file",)
    assert source_labels("spec") == ()


def test_required_stages_legacy_markdown_in_STAGES_order():
    assert required_stages("legacy_markdown") == (
        "spec",
        "outline",
        "draft",
        "qa",
        "repair",
    )


def test_required_stages_interactive_guide_in_STAGES_order():
    assert required_stages("interactive_guide") == (
        "spec",
        "outline",
        "draft",
        "qa",
        "factcheck",
        "repair",
    )


def test_required_stages_unknown_mode_raises_value_error():
    with pytest.raises(ValueError):
        required_stages("nope")


def test_supported_stages_is_required_plus_optional_in_STAGES_order():
    assert supported_stages() == (
        "spec",
        "outline",
        "draft",
        "qa",
        "factcheck",
        "repair",
        "audit",
    )


def test_optional_stages():
    assert optional_stages() == ("audit",)


def test_reasoning_stages():
    assert reasoning_stages() == frozenset({"spec", "outline", "factcheck", "repair"})


# --- Derivation tests: config.py constants must equal the graph's derivations ---


def test_config_REQUIRED_STAGES_derives_from_graph():
    assert REQUIRED_STAGES == required_stages("legacy_markdown")


def test_config_GUIDE_V1_REQUIRED_STAGES_derives_from_graph():
    assert GUIDE_V1_REQUIRED_STAGES == required_stages("interactive_guide")


def test_config_OPTIONAL_STAGES_derives_from_graph():
    assert OPTIONAL_STAGES == optional_stages()


def test_config_SUPPORTED_STAGES_derives_from_graph():
    assert SUPPORTED_STAGES == supported_stages()


def test_config_PRESET_STAGES_derives_from_graph():
    assert PRESET_STAGES == ("profile",) + supported_stages()


def test_config_STAGE_ORDER_derives_from_graph():
    assert STAGE_ORDER == ("profile",) + supported_stages() + ("finalize", "export")


def test_config_REASONING_STAGES_derives_from_graph():
    assert REASONING_STAGES == reasoning_stages()
