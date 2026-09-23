"""Unit tests for the schema 1.2 diagram model and the pure rules module.

Spec: docs/superpowers/specs/2026-09-23-diagram-block-design.md §2 (model)
and §3.1 (`guides/diagrams.py`). New names are imported inside each test so
that a missing name fails only the tests that need it.
"""

from __future__ import annotations

from dataclasses import fields

import pytest

BASE = "/modules/0/sections/0/blocks/1"


def _flow(nodes=("a", "b", "c"), edges=(("a", "b"), ("b", "c")), **extra):
    from education_pipeline.guides.model import Diagram, DiagramEdge, DiagramNode

    return Diagram(
        id="sample-flow",
        kind="flow",
        title="Sample flow",
        nodes=tuple(DiagramNode(node, node.upper()) for node in nodes),
        edges=tuple(DiagramEdge(source, target) for source, target in edges),
        **extra,
    )


def _concept_map(hub="hub", nodes=("hub", "x", "y"), edges=(("hub", "x"), ("hub", "y"))):
    from education_pipeline.guides.model import Diagram, DiagramEdge, DiagramNode

    return Diagram(
        id="sample-map",
        kind="concept_map",
        title="Sample map",
        hub=hub,
        nodes=tuple(DiagramNode(node, node.upper()) for node in nodes),
        edges=tuple(DiagramEdge(source, target) for source, target in edges),
    )


def _comparison():
    from education_pipeline.guides.model import (
        ComparisonCriterion,
        ComparisonItem,
        ComparisonValue,
        Diagram,
    )

    return Diagram(
        id="sample-comparison",
        kind="comparison",
        title="Sample comparison",
        items=(ComparisonItem("left", "Left"), ComparisonItem("right", "Right")),
        criteria=(
            ComparisonCriterion(
                "speed",
                "Speed",
                (ComparisonValue("left", "Fast"), ComparisonValue("right", "Slow")),
            ),
        ),
    )


def _timeline():
    from education_pipeline.guides.model import Diagram, TimelineEvent

    return Diagram(
        id="sample-timeline",
        kind="timeline",
        title="Sample timeline",
        events=(
            TimelineEvent("first", "Day 1", "First"),
            TimelineEvent("second", "Day 2", "Second", "Then this."),
        ),
    )


def _findings(block, base: str = BASE) -> dict[tuple[str, str], str]:
    from education_pipeline.guides.diagrams import diagram_findings

    result = diagram_findings(block, base)
    assert isinstance(result, tuple)
    return {(code, path): message for code, path, message in result}


# --- model ------------------------------------------------------------------


def test_schema_version_sets_are_named_features() -> None:
    from education_pipeline.guides import model

    assert model.SUPPORTED_GUIDE_SCHEMA_VERSIONS == frozenset({"1.0", "1.1", "1.2"})
    assert model.ANNOTATION_SCHEMA_VERSIONS == frozenset({"1.1", "1.2"})
    assert model.DIAGRAM_SCHEMA_VERSIONS == frozenset({"1.2"})
    assert model.LATEST_GUIDE_SCHEMA_VERSION == "1.2"
    # "Assumed when a source does not name one" -- must stay 1.0.
    assert model.DEFAULT_GUIDE_SCHEMA_VERSION == "1.0"
    assert model.DIAGRAM_KINDS == ("flow", "concept_map", "comparison", "timeline")


def test_block_types_stay_the_six_interaction_plannable_types() -> None:
    from education_pipeline.guides.parse import BLOCK_TYPES, DIAGRAM_BLOCK_TYPE

    assert DIAGRAM_BLOCK_TYPE == "diagram"
    assert set(BLOCK_TYPES) == {
        "rich_text",
        "callout",
        "knowledge_check",
        "worked_reveal",
        "scenario",
        "reflection",
    }


def test_diagram_dataclasses_are_frozen_hashable_and_carry_json_metadata() -> None:
    from education_pipeline.guides.model import (
        ComparisonCriterion,
        Diagram,
        DiagramEdge,
    )

    flow = _flow()
    assert flow.type == "diagram"
    assert flow.caption is None and flow.hub is None
    assert flow.outcome_ids == () and flow.source_ids == ()
    assert hash(flow) == hash(_flow())
    with pytest.raises(AttributeError):
        flow.title = "Changed"  # type: ignore[misc]

    edge_fields = {item.name: item for item in fields(DiagramEdge)}
    assert edge_fields["from_id"].metadata["json"] == "from"
    assert edge_fields["to_id"].metadata["json"] == "to"
    criterion_fields = {item.name: item for item in fields(ComparisonCriterion)}
    assert criterion_fields["values"].metadata["json_keyed"] == ("item_id", "text")
    diagram_fields = {item.name: item for item in fields(Diagram)}
    for name in ("nodes", "edges", "events", "items", "criteria"):
        assert diagram_fields[name].metadata["omit_empty"] is True


def test_block_union_includes_diagram() -> None:
    import typing

    from education_pipeline.guides.model import Block, Diagram

    assert Diagram in typing.get_args(Block)


def test_kind_labels_are_exact() -> None:
    from education_pipeline.guides.diagrams import KIND_LABELS

    assert KIND_LABELS == {
        "flow": "Flow diagram",
        "concept_map": "Concept map",
        "comparison": "Comparison",
        "timeline": "Timeline",
    }


# --- back_edge_indices ------------------------------------------------------


@pytest.mark.parametrize(
    ("nodes", "edges", "expected"),
    [
        # The fixture's growth loop: the closing edge is the back edge.
        (
            ("biomass", "leaf-area", "sunlight", "growth"),
            (
                ("biomass", "leaf-area"),
                ("leaf-area", "sunlight"),
                ("sunlight", "growth"),
                ("growth", "biomass"),
            ),
            {3},
        ),
        # The spec's §6 counter-example: DFS order, not document order.
        (("a", "b", "c"), (("a", "c"), ("c", "b"), ("b", "c")), {2}),
        # A two-step loop.
        (("a", "b"), (("a", "b"), ("b", "a")), {1}),
        # Acyclic.
        (("a", "b", "c"), (("a", "b"), ("a", "c"), ("b", "c")), set()),
        # DFS restarts at the next white node in document order.
        (("a", "b", "c", "d"), (("c", "d"), ("d", "c"), ("a", "b")), {1}),
    ],
)
def test_back_edge_indices_follow_the_dfs_rule(nodes, edges, expected) -> None:
    from education_pipeline.guides.diagrams import back_edge_indices

    result = back_edge_indices(_flow(nodes=nodes, edges=edges))

    assert isinstance(result, frozenset)
    assert result == frozenset(expected)


# --- diagram_findings -------------------------------------------------------


@pytest.mark.parametrize(
    "block", [_flow, _concept_map, _comparison, _timeline], ids=lambda f: f.__name__
)
def test_valid_diagrams_have_no_findings(block) -> None:
    from education_pipeline.guides.diagrams import diagram_findings

    assert diagram_findings(block(), BASE) == ()


def test_findings_use_the_given_base_path_verbatim() -> None:
    block = _flow(edges=(("a", "b"), ("b", "c"), ("c", "c")))

    assert _findings(block, "/elsewhere") == {
        ("diagram.self_edge", "/elsewhere/edges/2"): "an edge must connect two different nodes"
    }


def test_cardinality_uses_the_checker_message_with_an_en_dash() -> None:
    from dataclasses import replace

    timeline = _timeline()
    short = replace(timeline, events=timeline.events[:1])

    assert _findings(short) == {
        ("schema.cardinality", f"{BASE}/events"): "must contain 2–10 items"
    }


def test_local_ids_share_one_namespace_and_report_the_first_path() -> None:
    from dataclasses import replace

    comparison = _comparison()
    comparison = replace(
        comparison,
        criteria=(replace(comparison.criteria[0], id="right"),),
    )

    assert _findings(comparison) == {
        ("diagram.duplicate_id", f"{BASE}/criteria/0/id"):
            f"duplicates diagram ID first declared at {BASE}/items/1/id"
    }


def test_invalid_local_id_uses_the_guide_id_pattern() -> None:
    from dataclasses import replace

    timeline = _timeline()
    timeline = replace(timeline, events=(replace(timeline.events[0], id="First"),) + timeline.events[1:])

    assert _findings(timeline) == {
        ("schema.invalid_id", f"{BASE}/events/0/id"): "must match ^[a-z][a-z0-9-]{0,63}$"
    }


def test_text_length_is_measured_after_trimming() -> None:
    from dataclasses import replace

    flow = _flow()
    padded = replace(flow, nodes=(replace(flow.nodes[0], label="  " + "x" * 48 + "  "),) + flow.nodes[1:])
    over = replace(flow, nodes=(replace(flow.nodes[0], label="x" * 49),) + flow.nodes[1:])

    assert _findings(padded) == {}
    assert _findings(over) == {
        ("diagram.text_too_long", f"{BASE}/nodes/0/label"): "must not exceed 48 characters"
    }


@pytest.mark.parametrize("breaker", ["\n", "\r", " ", " "])
def test_multiline_rule_checks_the_raw_string_including_a_trailing_break(breaker) -> None:
    from dataclasses import replace

    flow = replace(_flow(), title="Sample flow" + breaker)

    assert _findings(flow) == {
        ("diagram.multiline_text", f"{BASE}/title"): "must be a single line"
    }


def test_unknown_endpoints_are_reported_per_end() -> None:
    flow = _flow(edges=(("a", "b"), ("b", "c"), ("ghost", "phantom")))

    assert _findings(flow) == {
        ("diagram.unknown_node", f"{BASE}/edges/2/from"): "unknown node ID 'ghost'",
        ("diagram.unknown_node", f"{BASE}/edges/2/to"): "unknown node ID 'phantom'",
    }


def test_flow_duplicates_are_ordered_pairs_concept_map_duplicates_unordered() -> None:
    loop = _flow(edges=(("a", "b"), ("b", "a"), ("b", "c")))
    repeated = _flow(edges=(("a", "b"), ("b", "c"), ("a", "b")))
    reversed_map = _concept_map(edges=(("hub", "x"), ("hub", "y"), ("x", "hub")))

    assert _findings(loop) == {}
    assert _findings(repeated) == {
        ("diagram.duplicate_edge", f"{BASE}/edges/2"): f"duplicates the edge at {BASE}/edges/0"
    }
    assert _findings(reversed_map) == {
        ("diagram.duplicate_edge", f"{BASE}/edges/2"): f"duplicates the edge at {BASE}/edges/0"
    }


def test_isolated_node_applies_to_flows_only() -> None:
    flow = _flow(nodes=("a", "b", "c", "d"))

    assert _findings(flow) == {
        ("diagram.isolated_node", f"{BASE}/nodes/3"): "node 'd' has no edges"
    }


def test_concept_map_connectivity_ignores_direction_and_needs_a_known_hub() -> None:
    inbound = _concept_map(edges=(("x", "hub"), ("y", "x")))
    island = _concept_map(nodes=("hub", "x", "y", "z"), edges=(("hub", "x"), ("y", "z")))
    unknown_hub = _concept_map(hub="nowhere", nodes=("hub", "x", "y"), edges=(("x", "y"),))

    assert _findings(inbound) == {}
    assert _findings(island) == {
        ("diagram.disconnected", f"{BASE}/nodes/2"): "node 'y' is not connected to the hub 'hub'",
        ("diagram.disconnected", f"{BASE}/nodes/3"): "node 'z' is not connected to the hub 'hub'",
    }
    # Rule 9 runs only when the hub resolves.
    assert _findings(unknown_hub) == {
        ("diagram.unknown_node", f"{BASE}/hub"): "unknown node ID 'nowhere'"
    }


def test_comparison_values_must_match_the_item_ids_in_dataclass_form() -> None:
    from dataclasses import replace

    from education_pipeline.guides.model import ComparisonValue

    comparison = _comparison()
    criterion = comparison.criteria[0]
    missing = replace(comparison, criteria=(replace(criterion, values=criterion.values[:1]),))
    extra = replace(
        comparison,
        criteria=(replace(criterion, values=criterion.values + (ComparisonValue("ghost", "Boo"),)),),
    )

    assert _findings(missing) == {
        ("diagram.missing_value", f"{BASE}/criteria/0/values"): "missing a value for item 'right'"
    }
    assert _findings(extra) == {
        ("diagram.unknown_value_key", f"{BASE}/criteria/0/values/ghost"): "unknown item ID 'ghost'"
    }


def test_fields_of_another_kind_are_unknown_fields_in_dataclass_form() -> None:
    from dataclasses import replace

    from education_pipeline.guides.model import DiagramNode, TimelineEvent

    comparison = replace(
        _comparison(),
        nodes=(DiagramNode("node", "Node"),),
        events=(TimelineEvent("event", "Day 1", "Event"),),
    )

    assert _findings(comparison) == {
        ("schema.unknown_field", f"{BASE}/nodes"): "unknown field 'nodes'",
        ("schema.unknown_field", f"{BASE}/events"): "unknown field 'events'",
    }
