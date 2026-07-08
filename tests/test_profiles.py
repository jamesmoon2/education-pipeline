from pathlib import Path

import pytest

from education_pipeline import (
    PROFILE_SCHEMA_VERSION,
    ConfigError,
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
    assert profile.adjacent_domains == ("spreadsheet formulas", "basic chart reading")
    assert profile.learning_goals == (
        "understand core analytics concepts",
        "practice interpreting simple datasets",
    )
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
