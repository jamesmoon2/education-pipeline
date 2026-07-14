"""Canonical learner-profile privacy policy and serialization.

This module owns the deterministic, value-free policy interface shared by the
profile store, editor surfaces, and guide privacy validation.
"""

from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from enum import StrEnum
import hashlib
import json
import math
import re
from types import MappingProxyType
from typing import Any, Iterable, Mapping

from education_pipeline.config import ConfigError
from education_pipeline.profiles import LearnerProfile, parse_learner_profile


class SensitivityTier(StrEnum):
    """Application-owned sensitivity tier for one profile leaf."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass(frozen=True)
class ProfileWarning:
    """Safe profile warning that never carries a source value."""

    code: str
    field_path: str
    fingerprint: str


_PROFILE_FIELD_SENSITIVITY = MappingProxyType(
    {
        "schema_version": SensitivityTier.LOW,
        "id": SensitivityTier.MEDIUM,
        "target_learner": SensitivityTier.HIGH,
        "prior_education": SensitivityTier.HIGH,
        "prior_experience": SensitivityTier.HIGH,
        "professional_experience": SensitivityTier.HIGH,
        "current_skill_level": SensitivityTier.MEDIUM,
        "adjacent_domains": SensitivityTier.MEDIUM,
        "learning_goals": SensitivityTier.MEDIUM,
        "preferred_examples": SensitivityTier.MEDIUM,
        "examples_to_avoid": SensitivityTier.MEDIUM,
        "math_comfort": SensitivityTier.LOW,
        "reading_level": SensitivityTier.LOW,
        "pace": SensitivityTier.LOW,
        "desired_depth": SensitivityTier.LOW,
        "time_budget": SensitivityTier.LOW,
        "assessment_styles": SensitivityTier.LOW,
        "accessibility_constraints": SensitivityTier.HIGH,
        "tone_preference": SensitivityTier.LOW,
        "sensitive_areas": SensitivityTier.HIGH,
        "learning_preferences.preferred_modalities": SensitivityTier.LOW,
        "learning_preferences.explanation_style": SensitivityTier.LOW,
        "learning_preferences.preferred_visual_aids": SensitivityTier.LOW,
        "learning_preferences.diagram_frequency": SensitivityTier.LOW,
        "learning_preferences.interaction_style": SensitivityTier.LOW,
        "learning_preferences.practice_style": SensitivityTier.LOW,
        "learning_preferences.feedback_style": SensitivityTier.LOW,
        "learning_preferences.worked_example_preference": SensitivityTier.LOW,
        "learning_preferences.common_sticking_points": SensitivityTier.MEDIUM,
        "learning_preferences.attention_constraints": SensitivityTier.MEDIUM,
        "learning_preferences.review_style": SensitivityTier.LOW,
        "localization.jurisdiction": SensitivityTier.MEDIUM,
        "localization.locale": SensitivityTier.MEDIUM,
        "localization.units": SensitivityTier.LOW,
        "localization.language_register": SensitivityTier.LOW,
        "privacy.private_by_default": SensitivityTier.LOW,
        "privacy.include_in_published_output": SensitivityTier.LOW,
        "privacy.publishable_summary": SensitivityTier.LOW,
        "metadata.*": SensitivityTier.HIGH,
    }
)

_GENERIC_PRIVATE_VALUES = frozenset(
    {"none", "unknown", "n/a", "na", "user", "learner", "student", "private"}
)
_MIN_PRIVATE_VALUE_LENGTH = 5
_BARE_TOML_KEY = re.compile(r"^[A-Za-z0-9_-]+$")


def profile_field_sensitivity() -> Mapping[str, SensitivityTier]:
    """Return the complete immutable profile leaf-path sensitivity policy."""

    return _PROFILE_FIELD_SENSITIVITY


def normalize_private_value(value: str) -> str:
    """Apply the exact normalization shared with guide leak validation."""

    _require_unicode_scalar(value, "private value")
    return " ".join(value.split()).casefold()


def private_value_fingerprint(value: str) -> str:
    """Return the safe 12-character fingerprint of a normalized value."""

    normalized = normalize_private_value(value)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]


def profile_private_values(profile: LearnerProfile) -> tuple[str, ...]:
    """Return ordered, normalized protected strings eligible for leak checks."""

    protected: list[str] = []
    seen: set[str] = set()
    for _, value in _protected_profile_strings(profile):
        normalized = normalize_private_value(value)
        if not _eligible_private_value(normalized) or normalized in seen:
            continue
        seen.add(normalized)
        protected.append(normalized)
    return tuple(protected)


def profile_summary_warnings(profile: LearnerProfile) -> tuple[ProfileWarning, ...]:
    """Warn safely when an enabled summary contains a protected source value."""

    if not profile.can_publish_summary or profile.privacy.publishable_summary is None:
        return ()
    summary = normalize_private_value(profile.privacy.publishable_summary)
    warnings: list[ProfileWarning] = []
    seen: set[tuple[str, str]] = set()
    for field_path, value in _protected_profile_strings(profile):
        normalized = normalize_private_value(value)
        if not _eligible_private_value(normalized) or normalized not in summary:
            continue
        fingerprint = private_value_fingerprint(normalized)
        identity = (field_path, fingerprint)
        if identity in seen:
            continue
        seen.add(identity)
        warnings.append(
            ProfileWarning(
                code="privacy.summary_contains_private_value",
                field_path=field_path,
                fingerprint=fingerprint,
            )
        )
    return tuple(warnings)


def profile_to_dict(profile: LearnerProfile) -> dict[str, Any]:
    """Project a profile to a JSON-compatible mapping in schema field order."""

    raw = _profile_input_mapping(profile)
    validated = parse_learner_profile(raw)
    return _without_none(validated)


def canonical_profile_toml_bytes(
    value: LearnerProfile | Mapping[str, Any],
) -> bytes:
    """Return deterministic canonical UTF-8 TOML bytes for a profile."""

    profile = value if isinstance(value, LearnerProfile) else parse_learner_profile(value)
    data = profile_to_dict(profile)
    lines: list[str] = []
    nested_tables: list[tuple[str, Mapping[str, Any]]] = []
    for key, item in data.items():
        if isinstance(item, Mapping):
            nested_tables.append((key, item))
        else:
            lines.append(f"{_toml_key(key, key)} = {_toml_value(item, key)}")
    for table_name, table in nested_tables:
        if lines:
            lines.append("")
        lines.append(f"[{_toml_key(table_name, table_name)}]")
        items = table.items()
        if table_name == "metadata":
            items = ((key, table[key]) for key in sorted(table))
        for key, item in items:
            path = "metadata.*" if table_name == "metadata" else f"{table_name}.{key}"
            lines.append(f"{_toml_key(key, path)} = {_toml_value(item, path)}")
    return ("\n".join(lines) + "\n").encode("utf-8")


def canonical_profile_sha256(value: LearnerProfile | Mapping[str, Any]) -> str:
    """Hash the exact canonical profile TOML bytes."""

    return hashlib.sha256(canonical_profile_toml_bytes(value)).hexdigest()


def _eligible_private_value(normalized: str) -> bool:
    return (
        len(normalized) >= _MIN_PRIVATE_VALUE_LENGTH
        and normalized not in _GENERIC_PRIVATE_VALUES
    )


def _protected_profile_strings(profile: LearnerProfile) -> Iterable[tuple[str, str]]:
    data = profile_to_dict(profile)
    for field_path, tier in _PROFILE_FIELD_SENSITIVITY.items():
        if tier not in {SensitivityTier.HIGH, SensitivityTier.MEDIUM}:
            continue
        if field_path == "metadata.*":
            yield from _strings_in_value(data.get("metadata", {}), "metadata.*")
            continue
        value: Any = data
        for segment in field_path.split("."):
            if not isinstance(value, Mapping) or segment not in value:
                value = None
                break
            value = value[segment]
        yield from _strings_in_value(value, field_path, preserve_collection_path=True)


def _strings_in_value(
    value: Any,
    path: str,
    *,
    preserve_collection_path: bool = False,
) -> Iterable[tuple[str, str]]:
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, Mapping):
        for child in value.values():
            yield from _strings_in_value(child, path)
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            child_path = path if preserve_collection_path else f"{path}[{index}]"
            yield from _strings_in_value(
                child,
                child_path,
                preserve_collection_path=preserve_collection_path,
            )


def _profile_input_mapping(profile: LearnerProfile) -> dict[str, Any]:
    raw: dict[str, Any] = {}
    for item in fields(profile):
        child = getattr(profile, item.name)
        if child is None:
            continue
        if item.name == "metadata":
            raw[item.name] = child
        elif is_dataclass(child):
            raw[item.name] = {
                nested.name: _schema_value(getattr(child, nested.name))
                for nested in fields(child)
                if getattr(child, nested.name) is not None
            }
        else:
            raw[item.name] = _schema_value(child)
    return raw


def _schema_value(value: Any) -> Any:
    if isinstance(value, tuple):
        return list(value)
    return value


def _without_none(value: Any) -> Any:
    if is_dataclass(value):
        return {
            item.name: _without_none(child)
            for item in fields(value)
            if (child := getattr(value, item.name)) is not None
        }
    if isinstance(value, Mapping):
        return {
            key: _without_none(child)
            for key, child in value.items()
        }
    if isinstance(value, tuple):
        return [_without_none(child) for child in value]
    if isinstance(value, list):
        return [_without_none(child) for child in value]
    return value


def _toml_key(key: str, path: str) -> str:
    if _BARE_TOML_KEY.fullmatch(key):
        return key
    return _toml_string(key, path)


def _toml_value(value: Any, path: str) -> str:
    if type(value) is str:
        return _toml_string(value, path)
    if type(value) is bool:
        return "true" if value else "false"
    if type(value) is int:
        return str(value)
    if type(value) is float:
        if not math.isfinite(value):
            raise ConfigError(f"profile field '{path}' must be a finite float")
        return repr(value)
    if isinstance(value, list):
        return "[" + ", ".join(
            _toml_value(child, f"{path}[{index}]")
            for index, child in enumerate(value)
        ) + "]"
    if isinstance(value, Mapping):
        pairs = (
            f"{_toml_key(key, path)} = {_toml_value(value[key], path)}"
            for key in sorted(value)
        )
        return "{" + ", ".join(pairs) + "}"
    raise ConfigError(f"profile field '{path}' cannot be serialized as TOML")


def _toml_string(value: str, path: str) -> str:
    _require_unicode_scalar(value, f"profile field '{path}'")
    return json.dumps(value, ensure_ascii=False).replace("\x7f", "\\u007f")


def _require_unicode_scalar(value: str, context: str) -> None:
    if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
        raise ConfigError(f"{context} must contain Unicode scalar values")
