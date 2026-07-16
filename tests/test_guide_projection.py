from pathlib import Path

from education_pipeline.guides import (
    normalize_guide,
    parse_guide,
    project_guide_markdown,
)

FIXTURE = Path(__file__).parent / "fixtures/guides/feedback-loops.guide.json"


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
