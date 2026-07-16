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
