"""Learner profile data model and TOML parsing."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping
import tomllib

from education_pipeline.config import ConfigError


PROFILE_SCHEMA_VERSION = 1

_TOP_LEVEL_KEYS = {
    "schema_version",
    "id",
    "target_learner",
    "prior_education",
    "prior_experience",
    "professional_experience",
    "current_skill_level",
    "adjacent_domains",
    "learning_goals",
    "preferred_examples",
    "examples_to_avoid",
    "math_comfort",
    "reading_level",
    "pace",
    "desired_depth",
    "time_budget",
    "assessment_styles",
    "accessibility_constraints",
    "tone_preference",
    "sensitive_areas",
    "learning_preferences",
    "localization",
    "privacy",
    "metadata",
}


@dataclass(frozen=True)
class LearnerLocalization:
    """Locale and language preferences that can shape examples and wording."""

    jurisdiction: str | None = None
    locale: str | None = None
    units: str | None = None
    language_register: str | None = None


@dataclass(frozen=True)
class LearnerPrivacy:
    """Publication rules for profile-derived information."""

    private_by_default: bool = True
    include_in_published_output: bool = False
    publishable_summary: str | None = None


@dataclass(frozen=True)
class LearnerPreferences:
    """Learning experience preferences used to adapt explanations and practice."""

    preferred_modalities: tuple[str, ...] = ()
    explanation_style: str | None = None
    preferred_visual_aids: tuple[str, ...] = ()
    diagram_frequency: str | None = None
    interaction_style: str | None = None
    practice_style: tuple[str, ...] = ()
    feedback_style: str | None = None
    worked_example_preference: str | None = None
    common_sticking_points: tuple[str, ...] = ()
    attention_constraints: tuple[str, ...] = ()
    review_style: tuple[str, ...] = ()


@dataclass(frozen=True)
class LearnerProfile:
    """Learner or cohort context used by the profile pipeline stage."""

    id: str
    target_learner: str
    schema_version: int = PROFILE_SCHEMA_VERSION
    prior_education: str | None = None
    prior_experience: str | None = None
    professional_experience: str | None = None
    current_skill_level: str | None = None
    adjacent_domains: tuple[str, ...] = ()
    learning_goals: tuple[str, ...] = ()
    preferred_examples: tuple[str, ...] = ()
    examples_to_avoid: tuple[str, ...] = ()
    math_comfort: str | None = None
    reading_level: str | None = None
    pace: str | None = None
    desired_depth: str | None = None
    time_budget: str | None = None
    assessment_styles: tuple[str, ...] = ()
    accessibility_constraints: tuple[str, ...] = ()
    tone_preference: str | None = None
    sensitive_areas: tuple[str, ...] = ()
    learning_preferences: LearnerPreferences = field(default_factory=LearnerPreferences)
    localization: LearnerLocalization = field(default_factory=LearnerLocalization)
    privacy: LearnerPrivacy = field(default_factory=LearnerPrivacy)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def can_publish_summary(self) -> bool:
        """Whether this profile has an explicit non-sensitive summary to publish."""

        return self.privacy.include_in_published_output and self.privacy.publishable_summary is not None


def load_learner_profile(path: str | Path) -> LearnerProfile:
    """Load and validate a learner profile TOML file."""

    profile_path = Path(path)
    try:
        with profile_path.open("rb") as handle:
            data = tomllib.load(handle)
    except FileNotFoundError as exc:
        raise ConfigError(f"learner profile file not found: {profile_path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"invalid TOML in {profile_path}: {exc}") from exc

    return parse_learner_profile(data)


def parse_learner_profile(data: Mapping[str, Any]) -> LearnerProfile:
    """Parse a learner profile mapping from TOML-decoded data."""

    if not isinstance(data, Mapping):
        raise ConfigError("learner profile must be a table")

    unknown = sorted(set(data) - _TOP_LEVEL_KEYS)
    if unknown:
        unknown_fields = ", ".join(unknown)
        raise ConfigError(f"unknown learner profile field(s): {unknown_fields}")

    schema_version = data.get("schema_version", PROFILE_SCHEMA_VERSION)
    if not isinstance(schema_version, int) or isinstance(schema_version, bool):
        raise ConfigError("learner profile field 'schema_version' must be an integer")
    if schema_version != PROFILE_SCHEMA_VERSION:
        raise ConfigError(
            f"unsupported learner profile schema_version {schema_version}; "
            f"expected {PROFILE_SCHEMA_VERSION}"
        )

    localization = _parse_localization(data.get("localization", {}))
    learning_preferences = _parse_learning_preferences(data.get("learning_preferences", {}))
    privacy = _parse_privacy(data.get("privacy", {}))
    if privacy.include_in_published_output and privacy.publishable_summary is None:
        raise ConfigError(
            "privacy.include_in_published_output requires a non-empty privacy.publishable_summary"
        )

    metadata = data.get("metadata", {})
    if not isinstance(metadata, Mapping):
        raise ConfigError("learner profile field 'metadata' must be a table")

    return LearnerProfile(
        schema_version=schema_version,
        id=_required_string(data, "id", "learner profile"),
        target_learner=_required_string(data, "target_learner", "learner profile"),
        prior_education=_optional_string(data, "prior_education", "learner profile"),
        prior_experience=_optional_string(data, "prior_experience", "learner profile"),
        professional_experience=_optional_string(
            data,
            "professional_experience",
            "learner profile",
        ),
        current_skill_level=_optional_string(data, "current_skill_level", "learner profile"),
        adjacent_domains=_string_tuple(data, "adjacent_domains", "learner profile"),
        learning_goals=_string_tuple(data, "learning_goals", "learner profile"),
        preferred_examples=_string_tuple(data, "preferred_examples", "learner profile"),
        examples_to_avoid=_string_tuple(data, "examples_to_avoid", "learner profile"),
        math_comfort=_optional_string(data, "math_comfort", "learner profile"),
        reading_level=_optional_string(data, "reading_level", "learner profile"),
        pace=_optional_string(data, "pace", "learner profile"),
        desired_depth=_optional_string(data, "desired_depth", "learner profile"),
        time_budget=_optional_string(data, "time_budget", "learner profile"),
        assessment_styles=_string_tuple(data, "assessment_styles", "learner profile"),
        accessibility_constraints=_string_tuple(
            data,
            "accessibility_constraints",
            "learner profile",
        ),
        tone_preference=_optional_string(data, "tone_preference", "learner profile"),
        sensitive_areas=_string_tuple(data, "sensitive_areas", "learner profile"),
        learning_preferences=learning_preferences,
        localization=localization,
        privacy=privacy,
        metadata=MappingProxyType(dict(metadata)),
    )


def _parse_localization(raw: Any) -> LearnerLocalization:
    if raw is None:
        raw = {}
    if not isinstance(raw, Mapping):
        raise ConfigError("learner profile field 'localization' must be a table")

    _reject_unknown(
        raw,
        {"jurisdiction", "locale", "units", "language_register"},
        "localization",
    )
    return LearnerLocalization(
        jurisdiction=_optional_string(raw, "jurisdiction", "localization"),
        locale=_optional_string(raw, "locale", "localization"),
        units=_optional_string(raw, "units", "localization"),
        language_register=_optional_string(raw, "language_register", "localization"),
    )


def _parse_learning_preferences(raw: Any) -> LearnerPreferences:
    if raw is None:
        raw = {}
    if not isinstance(raw, Mapping):
        raise ConfigError("learner profile field 'learning_preferences' must be a table")

    _reject_unknown(
        raw,
        {
            "preferred_modalities",
            "explanation_style",
            "preferred_visual_aids",
            "diagram_frequency",
            "interaction_style",
            "practice_style",
            "feedback_style",
            "worked_example_preference",
            "common_sticking_points",
            "attention_constraints",
            "review_style",
        },
        "learning_preferences",
    )
    return LearnerPreferences(
        preferred_modalities=_string_tuple(
            raw,
            "preferred_modalities",
            "learning_preferences",
        ),
        explanation_style=_optional_string(raw, "explanation_style", "learning_preferences"),
        preferred_visual_aids=_string_tuple(
            raw,
            "preferred_visual_aids",
            "learning_preferences",
        ),
        diagram_frequency=_optional_string(raw, "diagram_frequency", "learning_preferences"),
        interaction_style=_optional_string(raw, "interaction_style", "learning_preferences"),
        practice_style=_string_tuple(raw, "practice_style", "learning_preferences"),
        feedback_style=_optional_string(raw, "feedback_style", "learning_preferences"),
        worked_example_preference=_optional_string(
            raw,
            "worked_example_preference",
            "learning_preferences",
        ),
        common_sticking_points=_string_tuple(
            raw,
            "common_sticking_points",
            "learning_preferences",
        ),
        attention_constraints=_string_tuple(
            raw,
            "attention_constraints",
            "learning_preferences",
        ),
        review_style=_string_tuple(raw, "review_style", "learning_preferences"),
    )


def _parse_privacy(raw: Any) -> LearnerPrivacy:
    if raw is None:
        raw = {}
    if not isinstance(raw, Mapping):
        raise ConfigError("learner profile field 'privacy' must be a table")

    _reject_unknown(
        raw,
        {"private_by_default", "include_in_published_output", "publishable_summary"},
        "privacy",
    )
    return LearnerPrivacy(
        private_by_default=_optional_bool(raw, "private_by_default", True, "privacy"),
        include_in_published_output=_optional_bool(
            raw,
            "include_in_published_output",
            False,
            "privacy",
        ),
        publishable_summary=_optional_string(raw, "publishable_summary", "privacy"),
    )


def _reject_unknown(data: Mapping[str, Any], allowed: set[str], context: str) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        unknown_fields = ", ".join(unknown)
        raise ConfigError(f"unknown {context} field(s): {unknown_fields}")


def _required_string(data: Mapping[str, Any], key: str, context: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{context} must define non-empty string {key!r}")
    return value


def _optional_string(data: Mapping[str, Any], key: str, context: str) -> str | None:
    if key not in data:
        return None
    value = data[key]
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{context} field {key!r} must be a non-empty string when set")
    return value


def _optional_bool(data: Mapping[str, Any], key: str, default: bool, context: str) -> bool:
    if key not in data:
        return default
    value = data[key]
    if not isinstance(value, bool):
        raise ConfigError(f"{context} field {key!r} must be a boolean")
    return value


def _string_tuple(data: Mapping[str, Any], key: str, context: str) -> tuple[str, ...]:
    if key not in data:
        return ()
    value = data[key]
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ConfigError(f"{context} field {key!r} must be a list of strings")
    strings: list[str] = []
    for index, item in enumerate(value, start=1):
        if not isinstance(item, str) or not item.strip():
            raise ConfigError(
                f"{context} field {key!r} item #{index} must be a non-empty string"
            )
        strings.append(item)
    return tuple(strings)
