"""Schema 1.3: diagram motion and the ``sequence`` and ``stack`` kinds.

Spec: docs/superpowers/specs/2026-09-27-motion-diagrams-design.md. Schema 1.3
is 1.2 plus one optional diagram field, ``motion`` (``flow``, ``step`` or
``rotate``, each allowed only on the kinds where it means something), and two
kinds: ``sequence`` (participants exchanging ordered messages) and ``stack``
(layers, top first, drawn as 3D slabs). Motion is data: the maintained
runtime decides how anything moves.
"""

from __future__ import annotations

from dataclasses import fields, replace
import json
from pathlib import Path

import pytest

from education_pipeline.guides import (
    assemble_guide_document,
    canonical_guide_bytes,
    normalize_guide,
    parse_guide,
    project_guide_markdown,
    validate_guide,
)

BASE = "/modules/0/sections/0/blocks/1"
MOTION_FIXTURE = Path(__file__).parent / "fixtures/guides/feedback-loops.motion.guide.json"
SEQUENCE = "/modules/1/sections/0/blocks/2"
STACK = "/modules/1/sections/0/blocks/3"
FLOW = "/modules/0/sections/0/blocks/1"


def _sequence(actors=("client", "api"), messages=(("client", "api"), ("api", "client")), **extra):
    from education_pipeline.guides.model import Diagram, DiagramNode, SequenceMessage

    return Diagram(
        id="sample-sequence",
        kind="sequence",
        title="Sample sequence",
        actors=tuple(DiagramNode(actor, actor.upper()) for actor in actors),
        messages=tuple(
            SequenceMessage(source, target, f"{source} to {target}")
            for source, target in messages
        ),
        **extra,
    )


def _stack(layers=("app", "db"), **extra):
    from education_pipeline.guides.model import Diagram, DiagramNode

    return Diagram(
        id="sample-stack",
        kind="stack",
        title="Sample stack",
        layers=tuple(DiagramNode(layer, layer.upper()) for layer in layers),
        **extra,
    )


def _flow(**extra):
    from education_pipeline.guides.model import Diagram, DiagramEdge, DiagramNode

    return Diagram(
        id="sample-flow",
        kind="flow",
        title="Sample flow",
        nodes=(DiagramNode("a", "A"), DiagramNode("b", "B")),
        edges=(DiagramEdge("a", "b"),),
        **extra,
    )


def _concept_map(**extra):
    from education_pipeline.guides.model import Diagram, DiagramEdge, DiagramNode

    return Diagram(
        id="sample-map",
        kind="concept_map",
        title="Sample map",
        hub="hub",
        nodes=(DiagramNode("hub", "Hub"), DiagramNode("x", "X")),
        edges=(DiagramEdge("hub", "x"),),
        **extra,
    )


def _timeline(**extra):
    from education_pipeline.guides.model import Diagram, TimelineEvent

    return Diagram(
        id="sample-timeline",
        kind="timeline",
        title="Sample timeline",
        events=(TimelineEvent("one", "Day 1", "One"), TimelineEvent("two", "Day 2", "Two")),
        **extra,
    )


def _comparison(**extra):
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
                "speed", "Speed", (ComparisonValue("left", "Fast"), ComparisonValue("right", "Slow"))
            ),
        ),
        **extra,
    )


def _findings(block, base: str = BASE, **kwargs) -> dict[tuple[str, str], str]:
    from education_pipeline.guides.diagrams import diagram_findings

    return {(code, path): message for code, path, message in diagram_findings(block, base, **kwargs)}


def _motion_data() -> dict:
    return json.loads(MOTION_FIXTURE.read_text(encoding="utf-8"))


def _blocks(decoded: dict) -> dict[str, dict]:
    return {
        block["id"]: block
        for module in decoded["modules"]
        for section in module["sections"]
        for block in section["blocks"]
    }


def _codes(result) -> set[tuple[str, str]]:
    return {(item.code, item.path) for item in result.diagnostics}


def motion_guide():
    return normalize_guide(parse_guide(MOTION_FIXTURE.read_bytes()))


# --- model -----------------------------------------------------------------


def test_schema_1_3_adds_motion_to_every_diagram_era_feature_set() -> None:
    from education_pipeline.guides import model

    assert model.SUPPORTED_GUIDE_SCHEMA_VERSIONS == frozenset({"1.0", "1.1", "1.2", "1.3"})
    assert model.ANNOTATION_SCHEMA_VERSIONS == frozenset({"1.1", "1.2", "1.3"})
    assert model.DIAGRAM_SCHEMA_VERSIONS == frozenset({"1.2", "1.3"})
    assert model.MOTION_SCHEMA_VERSIONS == frozenset({"1.3"})
    assert model.LATEST_GUIDE_SCHEMA_VERSION == "1.3"
    assert model.DEFAULT_GUIDE_SCHEMA_VERSION == "1.0"
    # The 1.2 kinds keep their list; the 1.3 kinds are named beside it.
    assert model.DIAGRAM_KINDS == ("flow", "concept_map", "comparison", "timeline")
    assert model.MOTION_DIAGRAM_KINDS == ("sequence", "stack")
    assert model.DIAGRAM_MOTIONS == ("flow", "step", "rotate")


def test_each_motion_is_allowed_only_where_it_means_something() -> None:
    from education_pipeline.guides.diagrams import MOTIONS_BY_KIND

    assert MOTIONS_BY_KIND == {
        "flow": ("flow", "step"),
        "concept_map": ("rotate",),
        "comparison": (),
        "timeline": ("step",),
        "sequence": ("step",),
        "stack": ("flow", "step", "rotate"),
    }


def test_sequence_message_and_new_diagram_fields_carry_json_metadata() -> None:
    from education_pipeline.guides.model import Diagram, SequenceMessage

    message_fields = {item.name: item for item in fields(SequenceMessage)}
    assert message_fields["from_id"].metadata["json"] == "from"
    assert message_fields["to_id"].metadata["json"] == "to"
    diagram_fields = {item.name: item for item in fields(Diagram)}
    for name in ("actors", "messages", "layers"):
        assert diagram_fields[name].metadata["omit_empty"] is True
    flow = _flow()
    assert flow.motion is None
    assert flow.actors == () and flow.messages == () and flow.layers == ()
    assert hash(_sequence()) == hash(_sequence())


# --- rules -----------------------------------------------------------------


@pytest.mark.parametrize("block", [_sequence(), _stack(), _sequence(motion="step"), _stack(motion="rotate")])
def test_valid_sequence_and_stack_have_no_findings(block) -> None:
    assert _findings(block) == {}


def test_sequence_messages_must_join_two_declared_actors() -> None:
    findings = _findings(_sequence(actors=("client", "api", "db"), messages=(("client", "ghost"), ("api", "api"))))

    assert findings[("diagram.unknown_node", f"{BASE}/messages/0/to")] == "unknown actor ID 'ghost'"
    assert findings[("diagram.self_edge", f"{BASE}/messages/1")] == (
        "a message must connect two different actors"
    )
    assert findings[("diagram.isolated_node", f"{BASE}/actors/2")] == "actor 'db' sends and receives no message"


def test_repeated_messages_are_legal_in_a_sequence() -> None:
    block = _sequence(messages=(("client", "api"), ("client", "api"), ("api", "client")))
    assert _findings(block) == {}


@pytest.mark.parametrize(
    "block, name, bounds",
    [
        (_sequence(actors=("solo",), messages=()), "actors", "2–6"),
        (_sequence(actors=tuple("abcdefg"), messages=tuple(zip("abcdef", "bcdefg"))), "actors", "2–6"),
        (_sequence(messages=()), "messages", "1–16"),
        (_sequence(messages=(("client", "api"),) * 17), "messages", "1–16"),
        (_stack(layers=("only",)), "layers", "2–6"),
        (_stack(layers=tuple("abcdefg")), "layers", "2–6"),
    ],
)
def test_new_kind_cardinality(block, name: str, bounds: str) -> None:
    assert _findings(block)[("schema.cardinality", f"{BASE}/{name}")] == f"must contain {bounds} items"


def test_actor_and_layer_ids_are_diagram_local_and_unique() -> None:
    findings = _findings(_stack(layers=("app", "app")))
    assert findings[("diagram.duplicate_id", f"{BASE}/layers/1/id")] == (
        f"duplicates diagram ID first declared at {BASE}/layers/0/id"
    )
    assert ("schema.invalid_id", f"{BASE}/actors/0/id") in _findings(
        _sequence(actors=("Client", "api"), messages=(("Client", "api"),))
    )


def test_new_kind_text_limits() -> None:
    from education_pipeline.guides.model import DiagramNode, SequenceMessage

    block = replace(_sequence(), messages=(SequenceMessage("client", "api", "x" * 49, "y" * 241),))
    findings = _findings(block)
    assert ("diagram.text_too_long", f"{BASE}/messages/0/label") in findings
    assert ("diagram.text_too_long", f"{BASE}/messages/0/detail") in findings
    stack = _stack()
    stack = replace(stack, layers=(DiagramNode("app", "A\nB"), DiagramNode("db", "DB", "z" * 241)))
    findings = _findings(stack)
    assert ("diagram.multiline_text", f"{BASE}/layers/0/label") in findings
    assert ("diagram.text_too_long", f"{BASE}/layers/1/detail") in findings


@pytest.mark.parametrize(
    "build, motion, allowed",
    [
        (_flow, "flow", True),
        (_flow, "step", True),
        (_flow, "rotate", False),
        (_concept_map, "rotate", True),
        (_concept_map, "flow", False),
        (_timeline, "step", True),
        (_timeline, "rotate", False),
        (_sequence, "step", True),
        (_sequence, "flow", False),
        (_stack, "flow", True),
        (_stack, "step", True),
        (_stack, "rotate", True),
        (_comparison, "step", False),
        (_flow, "spin", False),
    ],
)
def test_motion_must_suit_the_kind(build, motion: str, allowed: bool) -> None:
    findings = _findings(build(motion=motion))
    if allowed:
        assert findings == {}
    else:
        assert set(findings) == {("diagram.invalid_motion", f"{BASE}/motion")}


def test_invalid_motion_message_names_the_kind_s_choices() -> None:
    assert _findings(_flow(motion="rotate"))[("diagram.invalid_motion", f"{BASE}/motion")] == (
        "motion 'rotate' is not available for a flow diagram; use 'flow' or 'step'"
    )
    assert _findings(_comparison(motion="step"))[("diagram.invalid_motion", f"{BASE}/motion")] == (
        "a comparison diagram has no motion"
    )


def test_motion_era_features_are_refused_before_1_3() -> None:
    assert set(_findings(_sequence(), motion_allowed=False)) == {("schema.invalid_value", f"{BASE}/kind")}
    assert set(_findings(_stack(), motion_allowed=False)) == {("schema.invalid_value", f"{BASE}/kind")}
    assert set(_findings(_flow(motion="flow"), motion_allowed=False)) == {
        ("schema.unknown_field", f"{BASE}/motion")
    }
    assert _findings(_flow(), motion_allowed=False) == {}


def test_fields_of_another_kind_are_unknown_for_the_new_kinds() -> None:
    from education_pipeline.guides.model import DiagramEdge, DiagramNode

    stack = replace(_stack(), nodes=(DiagramNode("n", "N"),), edges=(DiagramEdge("n", "n"),))
    assert {("schema.unknown_field", f"{BASE}/nodes"), ("schema.unknown_field", f"{BASE}/edges")} <= set(
        _findings(stack)
    )
    flow = replace(_flow(), layers=(DiagramNode("l", "L"),))
    assert ("schema.unknown_field", f"{BASE}/layers") in _findings(flow)


# --- parse -----------------------------------------------------------------


def test_motion_fixture_parses_clean_and_normalizes() -> None:
    result = parse_guide(MOTION_FIXTURE.read_bytes())
    assert result.diagnostics == ()
    guide = normalize_guide(result)
    assert guide.schema_version == "1.3"
    blocks = {b.id: b for m in guide.modules for s in m.sections for b in s.blocks}
    sequence = blocks["watering-timer-sequence"]
    assert sequence.motion == "step"
    assert [a.id for a in sequence.actors] == ["sensor", "timer", "valve"]
    assert (sequence.messages[0].from_id, sequence.messages[0].to_id) == ("sensor", "timer")
    assert sequence.messages[0].detail == "Below the 25% target, so the timer acts."
    stack = blocks["garden-bed-stack"]
    assert stack.motion == "flow" and [layer.id for layer in stack.layers][:2] == ["mulch", "topsoil"]
    assert blocks["growth-loop-flow"].motion == "flow"
    assert blocks["loop-kinds-map"].motion == "rotate"
    assert blocks["loop-types-comparison"].motion is None


def test_a_1_2_guide_refuses_every_motion_era_feature() -> None:
    data = _motion_data()
    data["schema_version"] = "1.2"
    codes = _codes(parse_guide(json.dumps(data)))

    assert ("schema.unknown_field", f"{FLOW}/motion") in codes
    assert ("schema.invalid_value", f"{SEQUENCE}/kind") in codes
    assert ("schema.invalid_value", f"{STACK}/kind") in codes


def test_parse_reports_bad_motion_values_and_new_kind_rules() -> None:
    data = _motion_data()
    blocks = _blocks(data)
    blocks["growth-loop-flow"]["motion"] = "rotate"
    blocks["loop-kinds-map"]["motion"] = 5
    blocks["watering-timer-sequence"]["messages"][1]["to"] = "hose"
    blocks["garden-bed-stack"]["layers"][0]["colour"] = "brown"
    codes = _codes(parse_guide(json.dumps(data)))

    assert ("diagram.invalid_motion", f"{FLOW}/motion") in codes
    assert ("schema.invalid_type", "/modules/0/sections/0/blocks/3/motion") in codes
    assert ("diagram.unknown_node", f"{SEQUENCE}/messages/1/to") in codes
    assert ("schema.unknown_field", f"{STACK}/layers/0/colour") in codes


def test_messages_require_a_label() -> None:
    data = _motion_data()
    del _blocks(data)["watering-timer-sequence"]["messages"][0]["label"]
    result = parse_guide(json.dumps(data))
    assert ("schema.missing_field", f"{SEQUENCE}/messages/0") in _codes(result)
    assert "missing required field 'label'" in {item.message for item in result.diagnostics}


# --- validation, canonical form, projection, document -----------------------


def test_motion_rule_is_registered() -> None:
    from education_pipeline.guides.validation import RULES

    rule = RULES["diagram.invalid_motion"]
    assert (rule.severity, rule.blocking, rule.waivable, rule.stage) == ("error", True, False, "draft")
    assert rule.remediation == "Use a motion listed for the diagram's kind, or omit motion."


def test_motion_fixture_validates_with_no_findings() -> None:
    report = validate_guide(motion_guide(), phase="final")
    assert report.findings == ()
    assert report.guide_schema_version == "1.3"
    assert validate_guide(MOTION_FIXTURE.read_text(encoding="utf-8")).findings == ()


def test_in_memory_motion_era_diagram_under_1_2_is_refused() -> None:
    guide = replace(motion_guide(), schema_version="1.2")
    codes = {(item.rule_id, item.path) for item in validate_guide(guide).findings}
    assert ("schema.unknown_field", f"{FLOW}/motion") in codes
    assert ("schema.invalid_value", f"{SEQUENCE}/kind") in codes


def test_canonical_bytes_round_trip_the_motion_fixture() -> None:
    once = canonical_guide_bytes(motion_guide())
    again = canonical_guide_bytes(normalize_guide(parse_guide(once)))
    assert once == again
    decoded = _blocks(json.loads(once))
    assert decoded["watering-timer-sequence"]["messages"][0] == {
        "detail": "Below the 25% target, so the timer acts.",
        "from": "sensor",
        "label": "Moisture is 18%",
        "to": "timer",
    }
    assert set(decoded["garden-bed-stack"]) == {
        "id", "type", "kind", "title", "motion", "outcome_ids", "source_ids", "layers",
    }
    assert "motion" not in decoded["loop-types-comparison"]


def test_projection_names_the_motion_and_draws_the_new_kinds() -> None:
    text = project_guide_markdown(motion_guide())

    assert "*Sequence diagram* · motion: step" in text
    assert "*Flow diagram* · motion: flow" in text
    assert "*Comparison*\n" in text
    assert "1. Soil sensor → Watering timer — Moisture is 18%: Below the 25% target, so the timer acts." in text
    assert "*Layer stack* · motion: flow" in text
    assert "Layers, top to bottom:" in text
    assert "1. Mulch: Slows evaporation from the surface." in text
    assert "4. Drainage gravel" in text


def test_document_marks_motion_and_writes_text_versions_for_new_kinds() -> None:
    document = assemble_guide_document(motion_guide())

    assert 'data-guide-schema="1.3"' in document
    assert (
        '<figure class="block diagram" id="watering-timer-sequence" data-diagram-kind="sequence" '
        'data-diagram-motion="step">'
    ) in document
    assert 'id="loop-types-comparison" data-diagram-kind="comparison">' in document
    assert '<p class="diagram-list-label">Participants</p><ul class="diagram-actors">' in document
    assert (
        '<li><span class="diagram-label">Soil sensor</span>: '
        '<span class="diagram-detail">Measures moisture near the roots.</span></li>'
    ) in document
    assert (
        '<ol class="diagram-messages"><li>Soil sensor → Watering timer — Moisture is 18%: '
        '<span class="diagram-detail">Below the 25% target, so the timer acts.</span></li>'
    ) in document
    assert '<p class="diagram-list-label">Layers, top to bottom</p><ol class="diagram-layers">' in document
    assert '<li><span class="diagram-label">Drainage gravel</span></li></ol>' in document


def test_diagram_without_motion_keeps_its_1_2_markup() -> None:
    from education_pipeline.guides.document import _diagram_block

    block = _flow()
    markup = _diagram_block(block, frozenset())
    assert markup.startswith('<figure class="block diagram" id="sample-flow" data-diagram-kind="flow">')


def test_audit_location_fingerprints_of_pre_1_3_diagrams_do_not_move() -> None:
    """Schema 1.3's new diagram fields stay out of a fingerprint while unset,
    so finding identifiers (and waivers keyed by them) survive the upgrade."""

    from education_pipeline.guides.audit import (
        GuideReference,
        _ResolvedLocation,
        _resolved_location_fingerprint,
    )

    fixture = Path(__file__).parent / "fixtures/guides/feedback-loops.diagrams.guide.json"
    guide = normalize_guide(parse_guide(fixture.read_bytes()))
    section = guide.modules[0].sections[0]
    block = _resolved_location_fingerprint(
        GuideReference("block", "growth-loop-flow"),
        _ResolvedLocation("/modules/0/sections/0/blocks/1", section.blocks[1]),
    )
    whole = _resolved_location_fingerprint(
        GuideReference("section", section.id), _ResolvedLocation("/modules/0/sections/0", section)
    )
    # Recorded from the schema 1.2 code (b171864).
    assert (block, whole) == ("3be07c94c33a", "45f0c3d353e1")
