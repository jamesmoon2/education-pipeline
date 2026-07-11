from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from education_pipeline.guides import GuideParseError, normalize_guide, parse_guide

FIXTURE = Path(__file__).parent / "fixtures/guides/feedback-loops.guide.json"


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
