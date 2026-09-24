from pathlib import Path

from education_pipeline.guides import (
    normalize_guide,
    parse_guide,
    project_guide_markdown,
)
from education_pipeline.guides.projection import public_guide_projection

FIXTURE = Path(__file__).parent / "fixtures/guides/feedback-loops.guide.json"
PERSONALIZED_FIXTURE = (
    Path(__file__).parent
    / "fixtures/guides/feedback-loops.personalized.guide.json"
)


def guide():
    return normalize_guide(parse_guide(FIXTURE.read_text(encoding="utf-8")))


def test_projection_is_deterministic_and_has_one_final_newline() -> None:
    first = project_guide_markdown(guide())

    assert first == project_guide_markdown(guide())
    assert first.endswith("\n") and not first.endswith("\n\n")


def test_projection_contains_every_educational_field() -> None:
    markdown = project_guide_markdown(guide())
    expected = [
        "Thinking in Feedback Loops",
        "A practical introduction through projects and gardens",
        "Learn to recognize feedback",
        "Identify reinforcing and balancing feedback",
        "How loops behave",
        "From events to loops",
        "A **feedback loop** exists",
        "Connect it to gardening",
        "What kind of loop dominates?",
        "Reinforcing",
        "Success increases learning",
        "Map the reinforcing loop",
        "Choose the quantity",
        "Start with **plant biomass**",
        "The loop reinforces growth",
        "Delays change what you see",
        "Which actions help",
        "Mapping the delay",
        "Pest damage rises",
        "Immediately increase pesticide use",
        "This treats visible damage",
        "A thoughtful intervention",
        "Where might a delayed feedback loop",
        "Name the changing quantity",
        "Draft a private loop map",
        "Feedback loop",
        "Thinking in Systems: A Primer",
        "Donella H. Meadows",
        "https://www.chelseagreen.com/product/thinking-in-systems/",
    ]
    for text in expected:
        assert text in markdown


def test_projection_contains_no_learner_notes() -> None:
    markdown = project_guide_markdown(guide())

    assert "learner response" not in markdown.lower()
    assert "private loop map" in markdown


def test_public_projection_strips_source_only_personalization_annotations() -> None:
    source = normalize_guide(parse_guide(PERSONALIZED_FIXTURE.read_bytes()))

    projected = public_guide_projection(source)

    assert source.schema_version == projected.schema_version == "1.1"
    assert source.course.goal_exclusions[0].reason == "Synthetic deferred objective."
    assert source.outcomes[0].serves_goals == ("goal-001",)
    assert source.modules[0].serves_goals == ("goal-001", "goal-002")
    assert projected.course.goal_exclusions == ()
    assert all(outcome.serves_goals == () for outcome in projected.outcomes)
    assert all(module.serves_goals == () for module in projected.modules)


# --- schema 1.2 diagrams (spec §6) ----------------------------------------

DIAGRAMS_FIXTURE = (
    Path(__file__).parent / "fixtures/guides/feedback-loops.diagrams.guide.json"
)


def diagrams_guide():
    return normalize_guide(parse_guide(DIAGRAMS_FIXTURE.read_bytes()))


def _diagram(guide_value, block_id: str):
    return next(
        block
        for module in guide_value.modules
        for section in module.sections
        for block in section.blocks
        if block.id == block_id
    )


FLOW_LINES = [
    "",
    "#### How plant growth reinforces itself",
    "",
    "*Flow diagram*",
    "",
    "1. Plant biomass",
    "2. Leaf area: More biomass usually means more leaves.",
    "3. Sunlight captured",
    "4. New growth",
    "",
    "Connections:",
    "",
    "- Plant biomass → Leaf area — increases",
    "- Leaf area → Sunlight captured — increases",
    "- Sunlight captured → New growth — fuels",
    "- New growth → Plant biomass — adds to (loops back)",
    "",
    "The last connection closes a **reinforcing** loop.",
]

CONCEPT_MAP_LINES = [
    "",
    "#### Kinds of feedback",
    "",
    "*Concept map*",
    "",
    "- Feedback loop (central idea)",
    "  - can be → Reinforcing loop",
    "  - can be → Balancing loop",
    "- Reinforcing loop: Amplifies change in one direction.",
    "- Balancing loop: Pushes a quantity toward a goal or limit.",
    "  - overshoots with a → Delay",
    "- Delay",
]

TIMELINE_LINES = [
    "",
    "#### Why watering again too soon overcorrects",
    "",
    "*Timeline*",
    "",
    "1. Day 1, morning — Water the bed",
    "2. Day 1, evening — Surface still looks dry",
    "3. Day 3 — Moisture reaches the roots: The delay hides the effect of the first watering.",
    "4. Day 4 — Leaves recover",
]

COMPARISON_LINES = [
    "",
    "#### Reinforcing and balancing loops side by side",
    "",
    "*Comparison*",
    "",
    "| Criterion | Reinforcing loop | Balancing loop |",
    "| --- | --- | --- |",
    "| What it does | Amplifies change in one direction | Pushes toward a goal or limit |",
    "| Garden example | More leaves capture more light | Watering stops once the soil is moist |",
    "| Main risk | Runaway growth or collapse | *Overcorrection* when feedback is delayed |",
]


def test_flow_projection_is_exactly_the_spec_text() -> None:
    markdown = project_guide_markdown(diagrams_guide())

    # The spec's §6 example, following the section heading and earlier blocks.
    assert "\n" + "\n".join(FLOW_LINES) + "\n" in markdown


def test_each_diagram_kind_projects_to_exact_lines() -> None:
    from education_pipeline.guides.projection import _project_block

    source = diagrams_guide()

    assert _project_block(_diagram(source, "growth-loop-flow")) == FLOW_LINES
    assert _project_block(_diagram(source, "loop-kinds-map")) == CONCEPT_MAP_LINES
    assert _project_block(_diagram(source, "watering-delay-timeline")) == TIMELINE_LINES
    assert _project_block(_diagram(source, "loop-types-comparison")) == COMPARISON_LINES


def test_diagram_projection_follows_document_order_and_stays_deterministic() -> None:
    markdown = project_guide_markdown(diagrams_guide())

    assert markdown == project_guide_markdown(diagrams_guide())
    assert markdown.endswith("\n") and not markdown.endswith("\n\n")
    positions = [
        markdown.index(title)
        for title in (
            "#### How plant growth reinforces itself",
            "#### Kinds of feedback",
            "#### Reinforcing and balancing loops side by side",
            "#### Why watering again too soon overcorrects",
        )
    ]
    assert positions == sorted(positions)


def test_flow_loop_back_marks_the_dfs_back_edge_without_a_step_number() -> None:
    from dataclasses import replace

    from education_pipeline.guides.model import DiagramEdge, DiagramNode
    from education_pipeline.guides.projection import _project_block

    flow = replace(
        _diagram(diagrams_guide(), "growth-loop-flow"),
        caption=None,
        nodes=(DiagramNode("a", "A"), DiagramNode("b", "B"), DiagramNode("c", "C")),
        edges=(
            DiagramEdge("a", "c"),
            DiagramEdge("c", "b"),
            DiagramEdge("b", "c"),
        ),
    )

    assert _project_block(flow)[-3:] == [
        "- A → C",
        "- C → B",
        "- B → C (loops back)",
    ]


def test_comparison_projection_escapes_pipes_in_labels_and_cells() -> None:
    from dataclasses import replace

    from education_pipeline.guides.model import (
        ComparisonCriterion,
        ComparisonItem,
        ComparisonValue,
    )
    from education_pipeline.guides.projection import _project_block

    comparison = replace(
        _diagram(diagrams_guide(), "loop-types-comparison"),
        items=(ComparisonItem("a", "Cost | time"), ComparisonItem("b", "Plain")),
        criteria=(
            ComparisonCriterion(
                "c",
                "Either | or",
                (ComparisonValue("a", "x | y"), ComparisonValue("b", "z")),
            ),
        ),
    )

    assert _project_block(comparison)[5:] == [
        "| Criterion | Cost \\| time | Plain |",
        "| --- | --- | --- |",
        "| Either \\| or | x \\| y | z |",
    ]


def test_diagram_caption_closes_every_kind() -> None:
    from dataclasses import replace

    from education_pipeline.guides.projection import _project_block

    timeline = replace(
        _diagram(diagrams_guide(), "watering-delay-timeline"),
        caption="Watch the *delay*.",
    )

    assert _project_block(timeline) == TIMELINE_LINES + ["", "Watch the *delay*."]
