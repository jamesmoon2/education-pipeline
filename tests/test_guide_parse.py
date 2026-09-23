from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from education_pipeline.guides import GuideParseError, normalize_guide, parse_guide

FIXTURE = Path(__file__).parent / "fixtures/guides/feedback-loops.guide.json"
PERSONALIZED_FIXTURE = (
    Path(__file__).parent
    / "fixtures/guides/feedback-loops.personalized.guide.json"
)


def fixture_data() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def parse_data(data) -> object:
    return parse_guide(json.dumps(data, ensure_ascii=False))


def codes(result) -> set[str]:
    return {diagnostic.code for diagnostic in result.diagnostics}


def blocks(data: dict) -> dict[str, dict]:
    return {
        block["type"]: block
        for module in data["modules"]
        for section in module["sections"]
        for block in section["blocks"]
    }


def test_complete_fixture_parses_and_normalizes() -> None:
    result = parse_guide(FIXTURE.read_bytes())
    guide = normalize_guide(result)

    assert result.ok
    assert guide.course.title == "Thinking in Feedback Loops"
    assert len(guide.outcomes) == 3
    assert len(guide.modules) == 2
    assert guide.course.goal_exclusions == ()
    assert all(outcome.serves_goals == () for outcome in guide.outcomes)
    assert all(module.serves_goals == () for module in guide.modules)
    assert {
        block.type
        for module in guide.modules
        for section in module.sections
        for block in section.blocks
    } == {
        "rich_text",
        "callout",
        "knowledge_check",
        "worked_reveal",
        "scenario",
        "reflection",
    }


def test_malformed_json_unsupported_version_and_non_object_root_are_useful() -> None:
    malformed = parse_guide('{"schema_version":')
    unsupported = parse_data({**fixture_data(), "schema_version": "2.0"})
    root_array = parse_guide("[]")

    assert codes(malformed) == {"json.invalid"}
    assert "line 1" in malformed.diagnostics[0].message
    assert "schema.unsupported_version" in codes(unsupported)
    assert "schema.invalid_type" in codes(root_array)


def test_unknown_root_nested_and_block_fields_are_rejected() -> None:
    data = fixture_data()
    data["surprise"] = True
    data["course"]["tagline"] = "unknown"
    data["modules"][0]["sections"][0]["blocks"][0]["html"] = "<b>no</b>"

    result = parse_data(data)

    assert [d.code for d in result.diagnostics].count("schema.unknown_field") == 3


def test_unknown_block_type_is_rejected_without_crashing() -> None:
    data = fixture_data()
    data["modules"][0]["sections"][0]["blocks"][0]["type"] = "simulation"

    assert "schema.unknown_block_type" in codes(parse_data(data))


def test_every_id_field_is_globally_validated_and_unique() -> None:
    data = fixture_data()
    knowledge = blocks(data)["knowledge_check"]
    reveal = blocks(data)["worked_reveal"]
    scenario = blocks(data)["scenario"]
    knowledge["choices"][0]["id"] = "Bad_choice"
    reveal["steps"][0]["id"] = scenario["choices"][0]["id"]

    result = parse_data(data)

    assert "schema.invalid_id" in codes(result)
    assert "schema.duplicate_id" in codes(result)


def test_unknown_references_and_duplicate_references_are_rejected() -> None:
    data = fixture_data()
    data["modules"][0]["outcome_ids"] = ["missing-outcome", "missing-outcome"]
    blocks(data)["rich_text"]["source_ids"] = ["missing-source"]

    result = parse_data(data)

    assert "schema.unknown_reference" in codes(result)
    assert "schema.duplicate_reference" in codes(result)


@pytest.mark.parametrize(
    ("kind", "mutate", "expected"),
    [
        ("rich_text", lambda block: block.update(markdown="  "), "content.empty"),
        ("callout", lambda block: block.update(kind="danger"), "schema.invalid_value"),
        (
            "knowledge_check",
            lambda block: block["choices"].__setitem__(
                slice(None), block["choices"][:1]
            ),
            "schema.cardinality",
        ),
        (
            "worked_reveal",
            lambda block: block["steps"].__setitem__(slice(None), block["steps"][:1]),
            "schema.cardinality",
        ),
        (
            "scenario",
            lambda block: [
                choice.update(quality="weak") for choice in block["choices"]
            ],
            "scenario.invalid_quality_set",
        ),
        ("reflection", lambda block: block.pop("prompt"), "schema.missing_field"),
    ],
)
def test_small_mutations_exercise_each_block_shape(kind, mutate, expected) -> None:
    data = fixture_data()
    mutate(blocks(data)[kind])

    assert expected in codes(parse_data(data))


def test_collection_and_scalar_constraints_are_enforced() -> None:
    data = fixture_data()
    data["outcomes"] = []
    data["modules"][0]["sections"] = []
    data["course"]["estimated_minutes"] = True

    result = parse_data(data)

    assert "schema.cardinality" in codes(result)
    assert "schema.invalid_type" in codes(result)


def test_cross_object_outcome_and_module_invariants_are_enforced() -> None:
    data = fixture_data()
    data["modules"][0]["outcome_ids"] = ["identify-loop"]
    data["modules"][1]["outcome_ids"] = ["choose-intervention"]
    for section in data["modules"][1]["sections"]:
        section["blocks"] = [
            block
            for block in section["blocks"]
            if block["type"] not in {"knowledge_check", "scenario", "reflection"}
        ]

    result = parse_data(data)

    assert {
        "outcome.unassigned",
        "outcome.unassessed",
        "module.no_interaction",
    } <= codes(result)


@pytest.mark.parametrize(
    "target",
    [
        "javascript:alert(1)",
        "//evil.example/x",
        "../secret",
        "file:///tmp/x",
        "data:text/html,x",
    ],
)
def test_markdown_rejects_unsafe_link_targets(target: str) -> None:
    data = fixture_data()
    blocks(data)["rich_text"]["markdown"] = f"Read [this]({target})."

    assert "link.unsafe_target" in codes(parse_data(data))


def test_markdown_rejects_raw_html_images_and_unknown_internal_links() -> None:
    data = fixture_data()
    blocks(data)["rich_text"][
        "markdown"
    ] = "<b>unsafe</b> ![track](https://example.com/x.png) [missing](#no-such-id)"

    assert {
        "content.raw_html",
        "link.image_not_supported",
        "link.unknown_internal_target",
    } <= codes(parse_data(data))


def test_plain_text_also_rejects_raw_html() -> None:
    data = fixture_data()
    data["outcomes"][0]["text"] = "Identify <em>important</em> loops."

    assert "content.raw_html" in codes(parse_data(data))


def test_required_interactive_vocabulary_is_enforced() -> None:
    data = fixture_data()
    for module in data["modules"]:
        for section in module["sections"]:
            section["blocks"] = [
                block for block in section["blocks"] if block["type"] != "reflection"
            ]

    result = parse_data(data)

    assert "interaction.missing_required_type" in codes(result)


def test_parser_reports_multiple_structural_problems_and_normalize_refuses() -> None:
    data = fixture_data()
    data["course"].pop("title")
    data["course"]["difficulty"] = "expert"
    data["modules"][0]["sections"][0]["blocks"][0]["extra"] = 1
    result = parse_data(data)

    assert len(result.diagnostics) >= 3
    with pytest.raises(GuideParseError):
        normalize_guide(result)


def test_utf8_bytes_are_required() -> None:
    result = parse_guide(b"\xff")

    assert codes(result) == {"json.invalid_utf8"}


def test_schema_1_0_rejects_authored_personalization_annotations() -> None:
    data = fixture_data()
    data["outcomes"][0]["serves_goals"] = ["goal-001"]
    data["modules"][0]["serves_goals"] = ["goal-001"]
    data["course"]["goal_exclusions"] = [
        {"goal_id": "goal-002", "reason": "Synthetic scope boundary."}
    ]

    result = parse_data(data)

    assert [d.code for d in result.diagnostics].count("schema.unknown_field") == 3


def test_schema_1_1_fixture_round_trips_with_annotations() -> None:
    result = parse_guide(PERSONALIZED_FIXTURE.read_bytes())
    guide = normalize_guide(result)

    assert result.ok
    assert guide.schema_version == "1.1"
    assert guide.outcomes[0].serves_goals == ("goal-001",)
    assert guide.modules[0].serves_goals == ("goal-001", "goal-002")
    assert guide.course.goal_exclusions[0].goal_id == "goal-003"
    assert guide.course.goal_exclusions[0].reason == "Synthetic deferred objective."


@pytest.mark.parametrize("version", ["0.9", "1.3", "2.0", 1.1, None, [], {}])
def test_unknown_or_non_string_schema_versions_fail(version) -> None:
    data = fixture_data()
    data["schema_version"] = version

    assert "schema.unsupported_version" in codes(parse_data(data))


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (
            lambda data: data["outcomes"][0].update(serves_goals="goal-001"),
            "schema.invalid_type",
        ),
        (
            lambda data: data["outcomes"][0].update(serves_goals=["Goal-001"]),
            "schema.invalid_goal_id",
        ),
        (
            lambda data: data["course"].update(goal_exclusions=["goal-001"]),
            "schema.invalid_type",
        ),
        (
            lambda data: data["course"].update(
                goal_exclusions=[{"goal_id": "goal-001"}]
            ),
            "schema.missing_field",
        ),
        (
            lambda data: data["course"].update(
                goal_exclusions=[
                    {"goal_id": "not-a-goal", "reason": "Synthetic reason."}
                ]
            ),
            "schema.invalid_goal_id",
        ),
        (
            lambda data: data["course"].update(
                goal_exclusions=[
                    {
                        "goal_id": "goal-001",
                        "reason": "Synthetic reason.",
                        "goal_text": "Must remain private and unsupported.",
                    }
                ]
            ),
            "schema.unknown_field",
        ),
        (
            lambda data: data["course"].update(
                goal_exclusions=[{"goal_id": "goal-001", "reason": "  "}]
            ),
            "content.empty",
        ),
        (
            lambda data: data["course"].update(
                goal_exclusions=[
                    {"goal_id": "goal-001", "reason": "Synthetic <b>private</b>."}
                ]
            ),
            "content.raw_html",
        ),
    ],
)
def test_schema_1_1_rejects_invalid_goal_annotation_shapes(mutate, expected) -> None:
    data = fixture_data()
    data["schema_version"] = "1.1"
    mutate(data)

    assert expected in codes(parse_data(data))


def test_schema_1_1_leaves_duplicate_and_dangling_goal_ids_for_later_rules() -> None:
    data = fixture_data()
    data["schema_version"] = "1.1"
    data["outcomes"][0]["serves_goals"] = ["goal-999", "goal-999"]
    data["modules"][0]["serves_goals"] = ["goal-999"]
    data["course"]["goal_exclusions"] = [
        {"goal_id": "goal-999", "reason": "Synthetic downstream validation case."},
        {"goal_id": "goal-999", "reason": "Synthetic duplicate exclusion case."},
    ]

    result = parse_data(data)

    assert result.ok
    assert normalize_guide(result).outcomes[0].serves_goals == (
        "goal-999",
        "goal-999",
    )


@pytest.mark.parametrize("goal_id", [" goal-001", "goal-001 ", "goal-001\n"])
def test_schema_1_1_rejects_goal_ids_with_authored_whitespace(goal_id: str) -> None:
    serves_data = fixture_data()
    serves_data["schema_version"] = "1.1"
    serves_data["outcomes"][0]["serves_goals"] = [goal_id]
    exclusion_data = fixture_data()
    exclusion_data["schema_version"] = "1.1"
    exclusion_data["course"]["goal_exclusions"] = [
        {"goal_id": goal_id, "reason": "Synthetic reason."}
    ]

    assert "schema.invalid_goal_id" in codes(parse_data(serves_data))
    assert "schema.invalid_goal_id" in codes(parse_data(exclusion_data))


@pytest.mark.parametrize("goal_id", ["goal-999", "goal-1000"])
def test_schema_1_1_accepts_unbounded_positive_positional_goal_ids(
    goal_id: str,
) -> None:
    data = fixture_data()
    data["schema_version"] = "1.1"
    data["outcomes"][0]["serves_goals"] = [goal_id]
    data["course"]["goal_exclusions"] = [
        {"goal_id": goal_id, "reason": "Synthetic reason."}
    ]

    result = parse_data(data)

    assert result.ok


@pytest.mark.parametrize("goal_id", ["goal-0001", "goal-0999"])
def test_schema_1_1_rejects_over_padded_goal_id_aliases(goal_id: str) -> None:
    serves_data = fixture_data()
    serves_data["schema_version"] = "1.1"
    serves_data["outcomes"][0]["serves_goals"] = [goal_id]
    exclusion_data = fixture_data()
    exclusion_data["schema_version"] = "1.1"
    exclusion_data["course"]["goal_exclusions"] = [
        {"goal_id": goal_id, "reason": "Synthetic reason."}
    ]

    serves_codes = codes(parse_data(serves_data))
    exclusion_codes = codes(parse_data(exclusion_data))

    assert "schema.invalid_goal_id" in serves_codes
    assert "schema.invalid_goal_id" in exclusion_codes


# --- check_skeleton -------------------------------------------------------
#
# A skeleton is a guide JSON object whose every module is a sectionless stub
# (`id, title, summary, outcome_ids, estimated_minutes`, `sections: []`, plus
# `serves_goals` only on schema 1.1). `check_skeleton` validates that shape
# directly rather than delegating to `parse_guide`, which can never accept a
# skeleton (empty `sections` fails cardinality, and no module has an
# interactive block).


def _skeleton_data() -> dict:
    data = fixture_data()
    data["modules"] = [
        {**{key: value for key, value in module.items() if key != "sections"}, "sections": []}
        for module in data["modules"]
    ]
    return data


SKELETON_MODULE_ORDER = ("loop-basics", "intervention-practice")


def test_check_skeleton_accepts_a_valid_sectionless_skeleton() -> None:
    from education_pipeline.guides.parse import check_skeleton

    skeleton = _skeleton_data()

    result = check_skeleton(
        json.dumps(skeleton, ensure_ascii=False), module_order=SKELETON_MODULE_ORDER
    )

    assert result.ok
    assert result.parsed == skeleton


def test_check_skeleton_accepts_mapping_and_bytes_input() -> None:
    from education_pipeline.guides.parse import check_skeleton

    skeleton = _skeleton_data()

    from_mapping = check_skeleton(skeleton, module_order=SKELETON_MODULE_ORDER)
    from_bytes = check_skeleton(
        json.dumps(skeleton, ensure_ascii=False).encode("utf-8"),
        module_order=SKELETON_MODULE_ORDER,
    )

    assert from_mapping.ok
    assert from_bytes.ok


def test_check_skeleton_rejects_a_module_with_sections() -> None:
    from education_pipeline.guides.parse import check_skeleton

    skeleton = _skeleton_data()
    real_module = fixture_data()["modules"][0]
    skeleton["modules"][0]["sections"] = [real_module["sections"][0]]

    result = check_skeleton(
        json.dumps(skeleton, ensure_ascii=False), module_order=SKELETON_MODULE_ORDER
    )
    result_codes = codes(result)

    assert not result.ok
    assert "skeleton.sections_not_empty" in result_codes
    # None of the ordinary guide-completeness rules apply to a skeleton --
    # they can never be satisfied by a document with (mostly) empty modules.
    assert "module.no_interaction" not in result_codes
    assert "interaction.missing_required_type" not in result_codes
    assert "outcome.untaught" not in result_codes
    assert "outcome.unassessed" not in result_codes
    assert "schema.cardinality" not in result_codes


def test_check_skeleton_rejects_a_missing_module() -> None:
    from education_pipeline.guides.parse import check_skeleton

    skeleton = _skeleton_data()
    skeleton["modules"] = skeleton["modules"][:1]

    result = check_skeleton(
        json.dumps(skeleton, ensure_ascii=False), module_order=SKELETON_MODULE_ORDER
    )

    assert not result.ok
    assert "skeleton.missing_module" in codes(result)


def test_check_skeleton_rejects_an_extra_module() -> None:
    from education_pipeline.guides.parse import check_skeleton

    skeleton = _skeleton_data()
    extra = dict(skeleton["modules"][0])
    extra["id"] = "surprise-module"
    skeleton["modules"].append(extra)

    result = check_skeleton(
        json.dumps(skeleton, ensure_ascii=False), module_order=SKELETON_MODULE_ORDER
    )

    assert not result.ok
    assert "skeleton.extra_module" in codes(result)


def test_check_skeleton_rejects_stubs_out_of_module_order() -> None:
    from education_pipeline.guides.parse import check_skeleton

    skeleton = _skeleton_data()
    skeleton["modules"].reverse()

    result = check_skeleton(
        json.dumps(skeleton, ensure_ascii=False), module_order=SKELETON_MODULE_ORDER
    )

    assert not result.ok
    assert "skeleton.module_order" in codes(result)


def test_check_skeleton_rejects_duplicate_ids_across_categories() -> None:
    from education_pipeline.guides.parse import check_skeleton

    skeleton = _skeleton_data()
    # A glossary entry stealing an outcome's id: the parser keeps one id
    # namespace across outcomes, modules, glossary, and sources.
    skeleton["glossary"][0]["id"] = skeleton["outcomes"][0]["id"]

    result = check_skeleton(
        json.dumps(skeleton, ensure_ascii=False), module_order=SKELETON_MODULE_ORDER
    )

    assert not result.ok
    assert "schema.duplicate_id" in codes(result)


def test_check_skeleton_non_json_and_non_object_input_yield_diagnostics_not_exceptions() -> None:
    from education_pipeline.guides.parse import check_skeleton

    malformed = check_skeleton("{not json", module_order=SKELETON_MODULE_ORDER)
    root_array = check_skeleton("[]", module_order=SKELETON_MODULE_ORDER)
    bad_utf8 = check_skeleton(b"\xff", module_order=SKELETON_MODULE_ORDER)

    assert not malformed.ok and malformed.parsed is None
    assert not root_array.ok and root_array.parsed is None
    assert not bad_utf8.ok and bad_utf8.parsed is None
    assert "json.invalid" in codes(malformed)
    assert "schema.invalid_type" in codes(root_array)
    assert "json.invalid_utf8" in codes(bad_utf8)


def test_check_skeleton_allows_serves_goals_on_module_stubs_only_for_schema_1_1() -> None:
    from education_pipeline.guides.parse import check_skeleton

    allowed = _skeleton_data()
    allowed["schema_version"] = "1.1"
    allowed["modules"][0]["serves_goals"] = ["goal-001"]

    rejected = _skeleton_data()
    rejected["modules"][0]["serves_goals"] = ["goal-001"]

    allowed_result = check_skeleton(
        json.dumps(allowed, ensure_ascii=False), module_order=SKELETON_MODULE_ORDER
    )
    rejected_result = check_skeleton(
        json.dumps(rejected, ensure_ascii=False), module_order=SKELETON_MODULE_ORDER
    )

    assert allowed_result.ok
    assert not rejected_result.ok
    assert "schema.unknown_field" in codes(rejected_result)


# --- schema 1.2: the `diagram` block ---------------------------------------
#
# Spec: docs/superpowers/specs/2026-09-23-diagram-block-design.md §1-§3.1.
# The diagrams fixture is schema 1.2 = the base fixture plus one diagram of
# each kind. Rule failures are asserted as exact sets of (code, path) plus
# exact messages.

DIAGRAMS_FIXTURE = (
    Path(__file__).parent / "fixtures/guides/feedback-loops.diagrams.guide.json"
)
FLOW = "/modules/0/sections/0/blocks/1"
CONCEPT_MAP = "/modules/0/sections/0/blocks/3"
COMPARISON = "/modules/0/sections/1/blocks/0"
TIMELINE = "/modules/1/sections/0/blocks/1"
DIAGRAM_IDS = {
    "flow": "growth-loop-flow",
    "concept_map": "loop-kinds-map",
    "comparison": "loop-types-comparison",
    "timeline": "watering-delay-timeline",
}
DIAGRAM_PATHS = {
    "flow": FLOW,
    "concept_map": CONCEPT_MAP,
    "comparison": COMPARISON,
    "timeline": TIMELINE,
}


def diagrams_data() -> dict:
    return json.loads(DIAGRAMS_FIXTURE.read_text(encoding="utf-8"))


def block_by_id(data: dict, block_id: str) -> dict:
    return next(
        block
        for module in data["modules"]
        for section in module["sections"]
        for block in section["blocks"]
        if block["id"] == block_id
    )


def diagram(data: dict, kind: str) -> dict:
    return block_by_id(data, DIAGRAM_IDS[kind])


def diagnostics_by_pair(result) -> dict[tuple[str, str], str]:
    return {(d.code, d.path): d.message for d in result.diagnostics}


def test_diagrams_fixture_parses_and_normalizes_all_four_kinds() -> None:
    from education_pipeline.guides.model import (
        ComparisonCriterion,
        ComparisonItem,
        ComparisonValue,
        Diagram,
        DiagramEdge,
        DiagramNode,
        TimelineEvent,
    )

    result = parse_guide(DIAGRAMS_FIXTURE.read_bytes())

    assert result.diagnostics == ()
    assert result.ok
    guide = normalize_guide(result)
    assert guide.schema_version == "1.2"
    diagrams = {
        block.id: block
        for module in guide.modules
        for section in module.sections
        for block in section.blocks
        if block.type == "diagram"
    }
    assert set(diagrams) == set(DIAGRAM_IDS.values())
    assert all(isinstance(block, Diagram) for block in diagrams.values())
    assert {block.kind for block in diagrams.values()} == set(DIAGRAM_IDS)

    flow = diagrams["growth-loop-flow"]
    assert flow == Diagram(
        id="growth-loop-flow",
        kind="flow",
        title="How plant growth reinforces itself",
        caption="The last connection closes a **reinforcing** loop.",
        outcome_ids=("map-loop",),
        nodes=(
            DiagramNode("biomass", "Plant biomass"),
            DiagramNode(
                "leaf-area", "Leaf area", "More biomass usually means more leaves."
            ),
            DiagramNode("sunlight", "Sunlight captured"),
            DiagramNode("growth", "New growth"),
        ),
        edges=(
            DiagramEdge("biomass", "leaf-area", "increases"),
            DiagramEdge("leaf-area", "sunlight", "increases"),
            DiagramEdge("sunlight", "growth", "fuels"),
            DiagramEdge("growth", "biomass", "adds to"),
        ),
    )
    assert flow.hub is None and flow.events == () and flow.items == ()

    concept_map = diagrams["loop-kinds-map"]
    assert concept_map.hub == "feedback-loop"
    assert [node.id for node in concept_map.nodes] == [
        "feedback-loop",
        "reinforcing",
        "balancing",
        "delay",
    ]
    assert concept_map.edges[2] == DiagramEdge(
        from_id="balancing", to_id="delay", label="overshoots with a"
    )
    assert concept_map.caption is None

    timeline = diagrams["watering-delay-timeline"]
    assert timeline.events[2] == TimelineEvent(
        id="roots",
        when="Day 3",
        label="Moisture reaches the roots",
        detail="The delay hides the effect of the first watering.",
    )
    assert timeline.nodes == () and timeline.edges == ()

    comparison = diagrams["loop-types-comparison"]
    assert comparison.source_ids == ("meadows-2008",)
    assert comparison.items == (
        ComparisonItem("reinforcing", "Reinforcing loop"),
        ComparisonItem("balancing", "Balancing loop"),
    )
    assert comparison.criteria[2] == ComparisonCriterion(
        id="risk",
        label="Main risk",
        values=(
            ComparisonValue("reinforcing", "Runaway growth or collapse"),
            ComparisonValue("balancing", "*Overcorrection* when feedback is delayed"),
        ),
    )
    # Every guide dataclass stays hashable (tuples only).
    assert hash(guide)


def test_comparison_values_are_normalized_in_item_order_not_key_order() -> None:
    data = diagrams_data()
    for criterion in diagram(data, "comparison")["criteria"]:
        criterion["values"] = dict(reversed(list(criterion["values"].items())))

    guide = normalize_guide(parse_data(data))
    comparison = next(
        block
        for module in guide.modules
        for section in module.sections
        for block in section.blocks
        if block.id == DIAGRAM_IDS["comparison"]
    )

    assert [
        [value.item_id for value in criterion.values]
        for criterion in comparison.criteria
    ] == [["reinforcing", "balancing"]] * 3


def test_normalization_keeps_raw_diagram_strings_untrimmed() -> None:
    data = diagrams_data()
    diagram(data, "flow")["nodes"][0]["label"] = "  Plant biomass  "

    guide = normalize_guide(parse_data(data))
    flow = guide.modules[0].sections[0].blocks[1]

    assert flow.nodes[0].label == "  Plant biomass  "


def test_unsupported_version_message_names_every_supported_version() -> None:
    result = parse_data({**fixture_data(), "schema_version": "1.3"})

    assert diagnostics_by_pair(result)[
        ("schema.unsupported_version", "/schema_version")
    ] == "supported schema versions are exactly '1.0', '1.1' and '1.2'"


def test_schema_1_2_without_diagrams_parses_and_allows_goal_annotations() -> None:
    data = fixture_data()
    data["schema_version"] = "1.2"
    data["outcomes"][0]["serves_goals"] = ["goal-001"]
    data["modules"][0]["serves_goals"] = ["goal-001"]
    data["course"]["goal_exclusions"] = [
        {"goal_id": "goal-002", "reason": "Synthetic scope boundary."}
    ]

    result = parse_data(data)

    assert result.diagnostics == ()
    assert normalize_guide(result).outcomes[0].serves_goals == ("goal-001",)


@pytest.mark.parametrize("version", ["1.0", "1.1"])
def test_diagram_before_schema_1_2_is_exactly_an_unknown_block_type(version) -> None:
    data = fixture_data()
    data["schema_version"] = version
    data["modules"][0]["sections"][0]["blocks"].insert(
        1, diagram(diagrams_data(), "flow")
    )

    result = parse_data(data)

    assert diagnostics_by_pair(result) == {
        ("schema.unknown_block_type", f"{FLOW}/type"): "unknown block type 'diagram'"
    }


def test_the_same_diagram_is_accepted_in_schema_1_2() -> None:
    data = fixture_data()
    data["schema_version"] = "1.2"
    data["modules"][0]["sections"][0]["blocks"].insert(
        1, diagram(diagrams_data(), "flow")
    )

    assert parse_data(data).diagnostics == ()


@pytest.mark.parametrize("bad_kind", ["venn", "Flow", "concept-map", 3, None, []])
def test_bad_diagram_kind_is_one_invalid_value_without_cascade(bad_kind) -> None:
    data = diagrams_data()
    flow = diagram(data, "flow")
    flow["kind"] = bad_kind
    # Kind arrays are not shape-checked when the kind is bad.
    flow["nodes"] = "not-an-array"

    result = parse_data(data)

    assert diagnostics_by_pair(result) == {
        ("schema.invalid_value", f"{FLOW}/kind"): "invalid diagram kind"
    }


def _set_path(data: dict, kind: str, *keys, value) -> None:
    target = diagram(data, kind)
    for key in keys[:-1]:
        target = target[key]
    target[keys[-1]] = value


def _append(data: dict, kind: str, array: str, value) -> None:
    diagram(data, kind)[array].append(value)


SHAPE_CASES = {
    "flow-with-events": (
        lambda d: _set_path(d, "flow", "events", value=[]),
        {("schema.unknown_field", f"{FLOW}/events"): "unknown field 'events'"},
    ),
    "flow-with-hub": (
        lambda d: _set_path(d, "flow", "hub", value="biomass"),
        {("schema.unknown_field", f"{FLOW}/hub"): "unknown field 'hub'"},
    ),
    "comparison-with-nodes": (
        lambda d: _set_path(d, "comparison", "nodes", value=[]),
        {("schema.unknown_field", f"{COMPARISON}/nodes"): "unknown field 'nodes'"},
    ),
    "timeline-with-criteria": (
        lambda d: _set_path(d, "timeline", "criteria", value=[]),
        {("schema.unknown_field", f"{TIMELINE}/criteria"): "unknown field 'criteria'"},
    ),
    "flow-missing-edges": (
        lambda d: diagram(d, "flow").pop("edges"),
        {("schema.missing_field", FLOW): "missing required field 'edges'"},
    ),
    "concept-map-missing-hub": (
        lambda d: diagram(d, "concept_map").pop("hub"),
        {("schema.missing_field", CONCEPT_MAP): "missing required field 'hub'"},
    ),
    "diagram-missing-title": (
        lambda d: diagram(d, "timeline").pop("title"),
        {("schema.missing_field", TIMELINE): "missing required field 'title'"},
    ),
    "diagram-unknown-common-field": (
        lambda d: _set_path(d, "flow", "width", value=400),
        {("schema.unknown_field", f"{FLOW}/width"): "unknown field 'width'"},
    ),
    "nodes-not-array": (
        lambda d: _set_path(d, "flow", "nodes", value={"biomass": "Plant biomass"}),
        {("schema.invalid_type", f"{FLOW}/nodes"): "must be an array"},
    ),
    "node-not-object": (
        lambda d: _set_path(d, "flow", "nodes", 0, value="biomass"),
        {("schema.invalid_type", f"{FLOW}/nodes/0"): "must be an object"},
    ),
    "node-missing-label": (
        lambda d: diagram(d, "flow")["nodes"][0].pop("label"),
        {("schema.missing_field", f"{FLOW}/nodes/0"): "missing required field 'label'"},
    ),
    "edge-unknown-key": (
        lambda d: _set_path(d, "flow", "edges", 0, "weight", value=2),
        {("schema.unknown_field", f"{FLOW}/edges/0/weight"): "unknown field 'weight'"},
    ),
    "edge-to-not-string": (
        lambda d: _set_path(d, "flow", "edges", 0, "to", value=5),
        {("schema.invalid_type", f"{FLOW}/edges/0/to"): "must be a string"},
    ),
    "edge-missing-from": (
        lambda d: diagram(d, "flow")["edges"][0].pop("from"),
        {("schema.missing_field", f"{FLOW}/edges/0"): "missing required field 'from'"},
    ),
    "event-missing-when": (
        lambda d: diagram(d, "timeline")["events"][0].pop("when"),
        {("schema.missing_field", f"{TIMELINE}/events/0"): "missing required field 'when'"},
    ),
    "item-with-detail": (
        lambda d: _set_path(d, "comparison", "items", 0, "detail", value="More."),
        {("schema.unknown_field", f"{COMPARISON}/items/0/detail"): "unknown field 'detail'"},
    ),
    "criterion-missing-values": (
        lambda d: diagram(d, "comparison")["criteria"][0].pop("values"),
        {
            ("schema.missing_field", f"{COMPARISON}/criteria/0"):
                "missing required field 'values'"
        },
    ),
    "values-not-object": (
        lambda d: _set_path(
            d, "comparison", "criteria", 0, "values", value=["Amplifies", "Pushes"]
        ),
        {("schema.invalid_type", f"{COMPARISON}/criteria/0/values"): "must be an object"},
    ),
    "values-extra-key": (
        lambda d: _set_path(d, "comparison", "criteria", 0, "values", "ghost", value="Boo"),
        {
            ("diagram.unknown_value_key", f"{COMPARISON}/criteria/0/values/ghost"):
                "unknown item ID 'ghost'"
        },
    ),
    "values-missing-key": (
        lambda d: diagram(d, "comparison")["criteria"][0]["values"].pop("balancing"),
        {
            ("diagram.missing_value", f"{COMPARISON}/criteria/0/values"):
                "missing a value for item 'balancing'"
        },
    ),
    "value-not-string": (
        lambda d: _set_path(
            d, "comparison", "criteria", 0, "values", "balancing", value=3
        ),
        {
            ("schema.invalid_type", f"{COMPARISON}/criteria/0/values/balancing"):
                "must be a string"
        },
    ),
    "empty-title": (
        lambda d: _set_path(d, "flow", "title", value="   "),
        {("content.empty", f"{FLOW}/title"): "must not be empty"},
    ),
    "raw-html-in-detail": (
        lambda d: _set_path(d, "flow", "nodes", 1, "detail", value="More <b>leaves</b>."),
        {("content.raw_html", f"{FLOW}/nodes/1/detail"): "raw HTML is not allowed"},
    ),
    "raw-html-in-label": (
        lambda d: _set_path(d, "timeline", "events", 0, "label", value="<i>Water</i>"),
        {("content.raw_html", f"{TIMELINE}/events/0/label"): "raw HTML is not allowed"},
    ),
    "image-in-cell": (
        lambda d: _set_path(
            d,
            "comparison",
            "criteria",
            0,
            "values",
            "reinforcing",
            value="![x](https://example.com/x.png)",
        ),
        {
            ("link.image_not_supported", f"{COMPARISON}/criteria/0/values/reinforcing"):
                "Markdown images are not supported"
        },
    ),
    "unsafe-link-in-caption": (
        lambda d: _set_path(d, "flow", "caption", value="See [x](javascript:void)."),
        {
            ("link.unsafe_target", f"{FLOW}/caption"):
                "unsafe Markdown link target 'javascript:void'"
        },
    ),
    "diagram-id-reuses-a-guide-id": (
        lambda d: _set_path(d, "flow", "id", value="loop-introduction"),
        {
            ("schema.duplicate_id", f"{FLOW}/id"):
                "duplicates ID first declared at /modules/0/sections/0/blocks/0/id"
        },
    ),
    "diagram-unknown-outcome": (
        lambda d: _set_path(d, "timeline", "outcome_ids", value=["missing-outcome"]),
        {
            ("schema.unknown_reference", f"{TIMELINE}/outcome_ids/0"):
                "unknown outcome ID 'missing-outcome'"
        },
    ),
    "diagram-unknown-source": (
        lambda d: _set_path(d, "comparison", "source_ids", value=["missing-source"]),
        {
            ("schema.unknown_reference", f"{COMPARISON}/source_ids/0"):
                "unknown source ID 'missing-source'"
        },
    ),
}


@pytest.mark.parametrize("case", sorted(SHAPE_CASES))
def test_diagram_shape_cases_report_exact_code_path_and_message(case) -> None:
    mutate, expected = SHAPE_CASES[case]
    data = diagrams_data()
    mutate(data)

    assert diagnostics_by_pair(parse_data(data)) == expected


def _rename_node(block: dict, old: str, new: str) -> None:
    for node in block["nodes"]:
        if node["id"] == old:
            node["id"] = new
    for edge in block["edges"]:
        for end in ("from", "to"):
            if edge[end] == old:
                edge[end] = new
    if block.get("hub") == old:
        block["hub"] = new


RULE_CASES = {
    # §3.1 row 2a
    "invalid-node-id": (
        lambda d: _rename_node(diagram(d, "flow"), "biomass", "Plant_biomass"),
        {
            ("schema.invalid_id", f"{FLOW}/nodes/0/id"):
                "must match ^[a-z][a-z0-9-]{0,63}$"
        },
    ),
    "invalid-event-id": (
        lambda d: _set_path(d, "timeline", "events", 0, "id", value="day_1"),
        {
            ("schema.invalid_id", f"{TIMELINE}/events/0/id"):
                "must match ^[a-z][a-z0-9-]{0,63}$"
        },
    ),
    "invalid-criterion-id": (
        lambda d: _set_path(d, "comparison", "criteria", 1, "id", value="1-example"),
        {
            ("schema.invalid_id", f"{COMPARISON}/criteria/1/id"):
                "must match ^[a-z][a-z0-9-]{0,63}$"
        },
    ),
    # §3.1 row 2b
    "duplicate-event-id": (
        lambda d: _set_path(d, "timeline", "events", 2, "id", value="water"),
        {
            ("diagram.duplicate_id", f"{TIMELINE}/events/2/id"):
                f"duplicates diagram ID first declared at {TIMELINE}/events/0/id"
        },
    ),
    "criterion-id-duplicates-item-id": (
        lambda d: _set_path(d, "comparison", "criteria", 1, "id", value="balancing"),
        {
            ("diagram.duplicate_id", f"{COMPARISON}/criteria/1/id"):
                f"duplicates diagram ID first declared at {COMPARISON}/items/1/id"
        },
    ),
    # §3.1 row 5
    "edge-to-unknown-node": (
        lambda d: _set_path(d, "flow", "edges", 3, "to", value="nowhere"),
        {("diagram.unknown_node", f"{FLOW}/edges/3/to"): "unknown node ID 'nowhere'"},
    ),
    "edge-from-unknown-node": (
        lambda d: _set_path(d, "flow", "edges", 0, "from", value="nowhere"),
        {("diagram.unknown_node", f"{FLOW}/edges/0/from"): "unknown node ID 'nowhere'"},
    ),
    "concept-map-edge-to-unknown-node": (
        lambda d: _set_path(d, "concept_map", "edges", 2, "to", value="lag"),
        {
            ("diagram.unknown_node", f"{CONCEPT_MAP}/edges/2/to"): "unknown node ID 'lag'",
            # `delay` is now in no edge, so it no longer reaches the hub.
            ("diagram.disconnected", f"{CONCEPT_MAP}/nodes/3"):
                "node 'delay' is not connected to the hub 'feedback-loop'",
        },
    ),
    "unknown-hub": (
        lambda d: _set_path(d, "concept_map", "hub", value="nowhere"),
        {("diagram.unknown_node", f"{CONCEPT_MAP}/hub"): "unknown node ID 'nowhere'"},
    ),
    # §3.1 row 6
    "self-edge": (
        lambda d: _set_path(
            d, "flow", "edges", 3, value={"from": "growth", "to": "growth"}
        ),
        {
            ("diagram.self_edge", f"{FLOW}/edges/3"):
                "an edge must connect two different nodes"
        },
    ),
    # §3.1 row 7
    "flow-duplicate-ordered-edge": (
        lambda d: _append(d, "flow", "edges", {"from": "biomass", "to": "leaf-area"}),
        {
            ("diagram.duplicate_edge", f"{FLOW}/edges/4"):
                f"duplicates the edge at {FLOW}/edges/0"
        },
    ),
    "concept-map-duplicate-unordered-edge": (
        lambda d: _append(
            d, "concept_map", "edges", {"from": "reinforcing", "to": "feedback-loop"}
        ),
        {
            ("diagram.duplicate_edge", f"{CONCEPT_MAP}/edges/3"):
                f"duplicates the edge at {CONCEPT_MAP}/edges/0"
        },
    ),
    # §3.1 row 8
    "flow-isolated-node": (
        lambda d: _append(d, "flow", "nodes", {"id": "weather", "label": "Weather"}),
        {("diagram.isolated_node", f"{FLOW}/nodes/4"): "node 'weather' has no edges"},
    ),
    # §3.1 row 9
    "concept-map-orphan-node": (
        lambda d: _append(d, "concept_map", "nodes", {"id": "orphan", "label": "Orphan"}),
        {
            ("diagram.disconnected", f"{CONCEPT_MAP}/nodes/4"):
                "node 'orphan' is not connected to the hub 'feedback-loop'"
        },
    ),
    "concept-map-island-component": (
        lambda d: (
            _append(d, "concept_map", "nodes", {"id": "soil", "label": "Soil"}),
            _append(d, "concept_map", "nodes", {"id": "water", "label": "Water"}),
            _append(d, "concept_map", "edges", {"from": "soil", "to": "water"}),
        ),
        {
            ("diagram.disconnected", f"{CONCEPT_MAP}/nodes/4"):
                "node 'soil' is not connected to the hub 'feedback-loop'",
            ("diagram.disconnected", f"{CONCEPT_MAP}/nodes/5"):
                "node 'water' is not connected to the hub 'feedback-loop'",
        },
    ),
}


@pytest.mark.parametrize("case", sorted(RULE_CASES))
def test_diagram_rule_rows_report_exact_code_path_and_message(case) -> None:
    mutate, expected = RULE_CASES[case]
    data = diagrams_data()
    mutate(data)

    assert diagnostics_by_pair(parse_data(data)) == expected


def test_flow_duplicate_node_id_is_reported_at_the_later_occurrence() -> None:
    data = diagrams_data()
    _append(data, "flow", "nodes", {"id": "biomass", "label": "Biomass again"})

    pairs = diagnostics_by_pair(parse_data(data))

    assert pairs[("diagram.duplicate_id", f"{FLOW}/nodes/4/id")] == (
        f"duplicates diagram ID first declared at {FLOW}/nodes/0/id"
    )


@pytest.mark.parametrize(
    "mutate",
    [
        # A -> B plus B -> A is a legitimate two-step loop in a flow.
        lambda d: _append(d, "flow", "edges", {"from": "leaf-area", "to": "biomass"}),
        # Concept-map connectivity ignores edge direction.
        lambda d: _set_path(
            d, "concept_map", "edges", 0, value={"from": "reinforcing", "to": "feedback-loop"}
        ),
        # Local ids may equal a guide-wide id ...
        lambda d: _rename_node(diagram(d, "flow"), "biomass", "loop-introduction"),
        lambda d: _set_path(d, "timeline", "events", 0, "id", value="delay-warning"),
        # ... and may be reused across diagrams.
        lambda d: _set_path(d, "timeline", "events", 0, "id", value="biomass"),
        lambda d: _rename_node(diagram(d, "concept_map"), "delay", "growth"),
        # A diagram needs no outcomes or sources.
        lambda d: _set_path(d, "timeline", "outcome_ids", value=[]),
        # An internal link to a guide-wide id is fine inside a detail or cell.
        lambda d: _set_path(
            d, "flow", "nodes", 1, "detail", value="See [the introduction](#loop-introduction)."
        ),
        lambda d: _set_path(
            d,
            "comparison",
            "criteria",
            0,
            "values",
            "balancing",
            value="See [the flow](#growth-loop-flow).",
        ),
        # Length is measured after trimming; spaces are not line breaks.
        lambda d: _set_path(d, "flow", "nodes", 0, "label", value="  " + "x" * 48 + "  "),
    ],
)
def test_legal_diagram_variations_parse_cleanly(mutate) -> None:
    data = diagrams_data()
    mutate(data)

    assert parse_data(data).diagnostics == ()


def test_diagram_local_ids_are_not_internal_link_targets() -> None:
    data = diagrams_data()
    _set_path(data, "flow", "nodes", 1, "detail", value="Compare [leaf area](#leaf-area).")

    assert diagnostics_by_pair(parse_data(data)) == {
        ("link.unknown_internal_target", f"{FLOW}/nodes/1/detail"):
            "unknown internal target 'leaf-area'"
    }


def test_an_outcome_taught_only_by_a_diagram_is_not_untaught() -> None:
    data = diagrams_data()
    block_by_id(data, "delay-explanation")["outcome_ids"] = ["map-loop"]
    block_by_id(data, "delay-warning")["outcome_ids"] = []

    result = parse_data(data)

    assert result.diagnostics == ()

    # Control: without the timeline, the same outcome is untaught.
    diagram(data, "timeline")["outcome_ids"] = []
    assert ("outcome.untaught", "/outcomes") in diagnostics_by_pair(parse_data(data))


def test_a_diagram_is_never_an_interaction() -> None:
    data = diagrams_data()
    module = data["modules"][1]
    for section in module["sections"]:
        section["blocks"] = [
            block
            for block in section["blocks"]
            if block["type"] in {"rich_text", "callout", "diagram"}
        ]

    result = parse_data(data)
    pairs = diagnostics_by_pair(result)

    assert "schema.unsupported_version" not in codes(result)
    assert pairs[("module.no_interaction", "/modules/1")] == (
        "module must contain at least one interactive block"
    )


MULTILINE_CASES = {
    "title-inner-newline": (("flow", "title"), "How plant growth\nreinforces itself"),
    "title-trailing-newline": (("flow", "title"), "How plant growth reinforces itself\n"),
    "caption-carriage-return": (("flow", "caption"), "Closes a loop.\r"),
    "node-label-line-separator": (("flow", "nodes", 0, "label"), "Plant biomass"),
    "node-detail-paragraph-separator": (
        ("flow", "nodes", 1, "detail"),
        "More biomass more leaves.",
    ),
    "edge-label": (("flow", "edges", 0, "label"), "in-\ncreases"),
    "event-when": (("timeline", "events", 0, "when"), "Day 1,\nmorning"),
    "event-label": (("timeline", "events", 0, "label"), "\nWater the bed"),
    "item-label": (("comparison", "items", 0, "label"), "Reinforcing\r\nloop"),
    "criterion-label": (("comparison", "criteria", 0, "label"), "What it\ndoes"),
    "cell": (
        ("comparison", "criteria", 0, "values", "reinforcing"),
        "Amplifies change\nin one direction",
    ),
}


@pytest.mark.parametrize("case", sorted(MULTILINE_CASES))
def test_every_diagram_string_must_be_a_single_raw_line(case) -> None:
    (kind, *keys), value = MULTILINE_CASES[case]
    data = diagrams_data()
    _set_path(data, kind, *keys, value=value)
    path = DIAGRAM_PATHS[kind] + "".join(f"/{key}" for key in keys)

    assert diagnostics_by_pair(parse_data(data)) == {
        ("diagram.multiline_text", path): "must be a single line"
    }


TEXT_LIMIT_CASES = {
    "title": (("flow", "title"), 120),
    "caption": (("flow", "caption"), 240),
    "node-label": (("flow", "nodes", 0, "label"), 48),
    "concept-map-node-label": (("concept_map", "nodes", 1, "label"), 48),
    "node-detail": (("flow", "nodes", 1, "detail"), 240),
    "edge-label": (("flow", "edges", 0, "label"), 32),
    "concept-map-edge-label": (("concept_map", "edges", 2, "label"), 32),
    "event-when": (("timeline", "events", 0, "when"), 32),
    "event-label": (("timeline", "events", 0, "label"), 48),
    "event-detail": (("timeline", "events", 2, "detail"), 240),
    "item-label": (("comparison", "items", 0, "label"), 48),
    "criterion-label": (("comparison", "criteria", 0, "label"), 48),
    "cell": (("comparison", "criteria", 0, "values", "balancing"), 240),
}


@pytest.mark.parametrize("case", sorted(TEXT_LIMIT_CASES))
def test_diagram_text_limit_passes_at_the_limit_and_fails_one_over(case) -> None:
    (kind, *keys), limit = TEXT_LIMIT_CASES[case]
    path = DIAGRAM_PATHS[kind] + "".join(f"/{key}" for key in keys)

    at_limit = diagrams_data()
    _set_path(at_limit, kind, *keys, value="x" * limit)
    over_limit = diagrams_data()
    _set_path(over_limit, kind, *keys, value="x" * (limit + 1))

    assert parse_data(at_limit).diagnostics == ()
    assert diagnostics_by_pair(parse_data(over_limit)) == {
        ("diagram.text_too_long", path): f"must not exceed {limit} characters"
    }


def _chain_flow(count: int) -> tuple[list[dict], list[dict]]:
    nodes = [{"id": f"n{i}", "label": f"Node {i}"} for i in range(count)]
    edges = [{"from": f"n{i}", "to": f"n{i + 1}"} for i in range(count - 1)]
    return nodes, edges


def _flow_with_edge_count(count: int) -> tuple[list[dict], list[dict]]:
    nodes = [{"id": f"n{i}", "label": f"Node {i}"} for i in range(6)]
    pairs = [(i, j) for i in range(6) for j in range(6) if i < j]
    pairs += [(j, i) for i in range(6) for j in range(6) if i < j]
    edges = [{"from": f"n{a}", "to": f"n{b}"} for a, b in pairs[:count]]
    return nodes, edges


def _star_map(ring: int, extra_edges: int = 0) -> tuple[list[dict], list[dict]]:
    nodes = [{"id": "hub-node", "label": "Hub"}] + [
        {"id": f"r{i}", "label": f"Ring {i}"} for i in range(ring)
    ]
    edges = [{"from": "hub-node", "to": f"r{i}"} for i in range(ring)]
    edges += [{"from": f"r{i}", "to": f"r{i + 1}"} for i in range(extra_edges)]
    return nodes, edges


def _set_flow(data: dict, nodes: list[dict], edges: list[dict]) -> None:
    flow = diagram(data, "flow")
    flow["nodes"], flow["edges"] = nodes, edges


def _set_map(data: dict, nodes: list[dict], edges: list[dict]) -> None:
    concept_map = diagram(data, "concept_map")
    concept_map["hub"] = "hub-node"
    concept_map["nodes"], concept_map["edges"] = nodes, edges


def _set_events(data: dict, count: int) -> None:
    diagram(data, "timeline")["events"] = [
        {"id": f"e{i}", "when": f"Day {i}", "label": f"Event {i}"} for i in range(count)
    ]


def _set_items(data: dict, count: int) -> None:
    comparison = diagram(data, "comparison")
    comparison["items"] = [{"id": f"i{n}", "label": f"Item {n}"} for n in range(count)]
    for criterion in comparison["criteria"]:
        criterion["values"] = {f"i{n}": f"Cell {n}" for n in range(count)}


def _set_criteria(data: dict, count: int) -> None:
    comparison = diagram(data, "comparison")
    comparison["criteria"] = [
        {
            "id": f"c{n}",
            "label": f"Criterion {n}",
            "values": {"reinforcing": "Yes", "balancing": "No"},
        }
        for n in range(count)
    ]


UPPER_BOUND_CASES = {
    "flow-nodes": (lambda d, n: _set_flow(d, *_chain_flow(n)), 12, f"{FLOW}/nodes", "2–12"),
    "flow-edges": (
        lambda d, n: _set_flow(d, *_flow_with_edge_count(n)),
        16,
        f"{FLOW}/edges",
        "1–16",
    ),
    "concept-map-nodes": (
        lambda d, n: _set_map(d, *_star_map(n - 1)),
        12,
        f"{CONCEPT_MAP}/nodes",
        "2–12",
    ),
    "concept-map-edges": (
        lambda d, n: _set_map(d, *_star_map(7, n - 7)),
        12,
        f"{CONCEPT_MAP}/edges",
        "1–12",
    ),
    "timeline-events": (_set_events, 10, f"{TIMELINE}/events", "2–10"),
    "comparison-items": (_set_items, 4, f"{COMPARISON}/items", "2–4"),
    "comparison-criteria": (_set_criteria, 8, f"{COMPARISON}/criteria", "1–8"),
}


@pytest.mark.parametrize("case", sorted(UPPER_BOUND_CASES))
def test_diagram_array_upper_bound_passes_at_the_limit_and_fails_one_over(case) -> None:
    build, limit, path, bound = UPPER_BOUND_CASES[case]
    at_limit = diagrams_data()
    build(at_limit, limit)
    over_limit = diagrams_data()
    build(over_limit, limit + 1)

    assert parse_data(at_limit).diagnostics == ()
    assert diagnostics_by_pair(parse_data(over_limit)) == {
        ("schema.cardinality", path): f"must contain {bound} items"
    }


LOWER_BOUND_CASES = {
    "flow-nodes": (lambda d, n: _set_flow(d, *_chain_flow(n)), 2, f"{FLOW}/nodes", "2–12"),
    "flow-edges": (
        lambda d, n: _set_flow(
            d,
            [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
            [{"from": "a", "to": "b"}][:n],
        ),
        1,
        f"{FLOW}/edges",
        "1–16",
    ),
    "concept-map-nodes": (
        lambda d, n: _set_map(d, *_star_map(n - 1)),
        2,
        f"{CONCEPT_MAP}/nodes",
        "2–12",
    ),
    "concept-map-edges": (
        lambda d, n: _set_map(d, *_star_map(1)) if n else _set_map(
            d, _star_map(1)[0], []
        ),
        1,
        f"{CONCEPT_MAP}/edges",
        "1–12",
    ),
    "timeline-events": (_set_events, 2, f"{TIMELINE}/events", "2–10"),
    "comparison-items": (_set_items, 2, f"{COMPARISON}/items", "2–4"),
    "comparison-criteria": (_set_criteria, 1, f"{COMPARISON}/criteria", "1–8"),
}


@pytest.mark.parametrize("case", sorted(LOWER_BOUND_CASES))
def test_diagram_array_lower_bound_passes_at_the_limit_and_fails_one_under(case) -> None:
    build, limit, path, bound = LOWER_BOUND_CASES[case]
    at_limit = diagrams_data()
    build(at_limit, limit)
    under_limit = diagrams_data()
    build(under_limit, limit - 1)

    assert parse_data(at_limit).diagnostics == ()
    pairs = diagnostics_by_pair(parse_data(under_limit))
    # Fewer elements can also leave nodes unconnected, so only the count
    # diagnostic is pinned here.
    assert pairs[("schema.cardinality", path)] == f"must contain {bound} items"
