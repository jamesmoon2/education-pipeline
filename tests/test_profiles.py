from pathlib import Path

import pytest

from education_pipeline import (
    PROFILE_SCHEMA_VERSION,
    ConfigError,
    LearnerPreferences,
    LearnerProfile,
    load_learner_profile,
    parse_learner_profile,
)


def test_loads_example_learner_profile() -> None:
    root = Path(__file__).resolve().parents[1]

    profile = load_learner_profile(root / "config" / "learner-profile.example.toml")

    assert isinstance(profile, LearnerProfile)
    assert profile.schema_version == PROFILE_SCHEMA_VERSION
    assert profile.id == "public-beginner-analytics"
    assert profile.target_learner == "public audience"
    assert profile.professional_experience == "entry-level operations or administrative work"
    assert profile.adjacent_domains == ("spreadsheet formulas", "basic chart reading")
    assert profile.learning_goals == (
        "understand core analytics concepts",
        "practice interpreting simple datasets",
    )
    assert isinstance(profile.learning_preferences, LearnerPreferences)
    assert profile.learning_preferences.explanation_style == "visual-first with concise text"
    assert profile.learning_preferences.preferred_modalities == (
        "visual",
        "hands-on practice",
        "reading",
    )
    assert profile.learning_preferences.preferred_visual_aids == (
        "flowcharts",
        "concept maps",
        "comparison tables",
        "annotated examples",
    )
    assert profile.learning_preferences.diagram_frequency == (
        "frequent for new concepts and multi-step processes"
    )
    assert profile.learning_preferences.worked_example_preference == "before abstract theory"
    assert profile.localization.locale == "en-US"
    assert profile.privacy.private_by_default is True
    assert profile.privacy.include_in_published_output is False
    assert profile.privacy.publishable_summary == (
        "Beginner public audience seeking a practical analytics foundation."
    )
    assert profile.can_publish_summary is False
    assert profile.metadata["source"] == "synthetic public example"


def test_minimal_profile_defaults_to_private_local_profile() -> None:
    profile = parse_learner_profile(
        {
            "id": "cohort-a",
            "target_learner": "team cohort",
        }
    )

    assert profile.id == "cohort-a"
    assert profile.schema_version == PROFILE_SCHEMA_VERSION
    assert profile.adjacent_domains == ()
    assert profile.learning_goals == ()
    assert profile.professional_experience is None
    assert profile.learning_preferences.preferred_modalities == ()
    assert profile.learning_preferences.preferred_visual_aids == ()
    assert profile.learning_preferences.explanation_style is None
    assert profile.localization.locale is None
    assert profile.privacy.private_by_default is True
    assert profile.privacy.include_in_published_output is False
    assert profile.privacy.publishable_summary is None
    assert profile.can_publish_summary is False


def test_profile_allows_explicit_publishable_summary() -> None:
    profile = parse_learner_profile(
        {
            "id": "public-summary",
            "target_learner": "public audience",
            "privacy": {
                "include_in_published_output": True,
                "publishable_summary": "Public audience with beginner-level context.",
            },
        }
    )

    assert profile.can_publish_summary is True


def test_profile_parses_learning_preferences() -> None:
    profile = parse_learner_profile(
        {
            "id": "visual-learner",
            "target_learner": "individual",
            "learning_preferences": {
                "preferred_modalities": ["visual", "hands-on"],
                "explanation_style": "diagram-led",
                "preferred_visual_aids": ["flowcharts", "timelines"],
                "diagram_frequency": "frequent",
                "interaction_style": "guided sequence",
                "practice_style": ["worked scenarios"],
                "feedback_style": "direct correction with rationale",
                "worked_example_preference": "side-by-side with theory",
                "common_sticking_points": ["multi-step branching logic"],
                "attention_constraints": ["short sessions"],
                "review_style": ["quick recap", "spaced review"],
            },
        }
    )

    preferences = profile.learning_preferences

    assert preferences.preferred_modalities == ("visual", "hands-on")
    assert preferences.explanation_style == "diagram-led"
    assert preferences.preferred_visual_aids == ("flowcharts", "timelines")
    assert preferences.diagram_frequency == "frequent"
    assert preferences.interaction_style == "guided sequence"
    assert preferences.practice_style == ("worked scenarios",)
    assert preferences.feedback_style == "direct correction with rationale"
    assert preferences.worked_example_preference == "side-by-side with theory"
    assert preferences.common_sticking_points == ("multi-step branching logic",)
    assert preferences.attention_constraints == ("short sessions",)
    assert preferences.review_style == ("quick recap", "spaced review")


def test_profile_rejects_publishing_without_summary() -> None:
    with pytest.raises(ConfigError, match="requires a non-empty privacy.publishable_summary"):
        parse_learner_profile(
            {
                "id": "unsafe",
                "target_learner": "individual",
                "privacy": {"include_in_published_output": True},
            }
        )


def test_profile_rejects_unknown_top_level_fields() -> None:
    with pytest.raises(ConfigError, match="unknown learner profile field"):
        parse_learner_profile(
            {
                "id": "typo",
                "target_learner": "public audience",
                "learning_goal": "singular typo",
            }
        )


def test_profile_rejects_unknown_nested_fields() -> None:
    with pytest.raises(ConfigError, match="unknown privacy field"):
        parse_learner_profile(
            {
                "id": "nested-typo",
                "target_learner": "public audience",
                "privacy": {"publish_summary": True},
            }
        )


def test_profile_rejects_unknown_learning_preference_fields() -> None:
    with pytest.raises(ConfigError, match="unknown learning_preferences field"):
        parse_learner_profile(
            {
                "id": "nested-learning-typo",
                "target_learner": "public audience",
                "learning_preferences": {"visual_aids": ["flowcharts"]},
            }
        )


def test_profile_rejects_non_string_lists() -> None:
    with pytest.raises(ConfigError, match="item #2 must be a non-empty string"):
        parse_learner_profile(
            {
                "id": "bad-list",
                "target_learner": "public audience",
                "learning_goals": ["valid", ""],
            }
        )


def test_profile_rejects_unsupported_schema_version() -> None:
    with pytest.raises(ConfigError, match="unsupported learner profile schema_version"):
        parse_learner_profile(
            {
                "schema_version": 2,
                "id": "future",
                "target_learner": "public audience",
            }
        )
