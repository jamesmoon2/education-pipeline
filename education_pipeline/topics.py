"""Topic artifact data model and TOML parsing."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping
import json
import tomllib

from education_pipeline.config import ConfigError


TOPIC_SCHEMA_VERSION = 1

_TOP_LEVEL_KEYS = {
    "schema_version",
    "id",
    "title",
    "brief",
    "audience",
    "goals",
    "scope_includes",
    "scope_excludes",
    "key_questions",
    "prerequisites",
    "constraints",
    "tags",
    "notes",
    "metadata",
}


@dataclass(frozen=True)
class Topic:
    """The subject of a guide, used to drive the spec and later stages."""

    id: str
    title: str
    schema_version: int = TOPIC_SCHEMA_VERSION
    brief: str | None = None
    audience: str | None = None
    goals: tuple[str, ...] = ()
    scope_includes: tuple[str, ...] = ()
    scope_excludes: tuple[str, ...] = ()
    key_questions: tuple[str, ...] = ()
    prerequisites: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


def load_topic(path: str | Path) -> Topic:
    """Load and validate a topic artifact from a TOML file."""

    topic_path = Path(path)
    try:
        with topic_path.open("rb") as handle:
            data = tomllib.load(handle)
    except FileNotFoundError as exc:
        raise ConfigError(f"topic file not found: {topic_path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"invalid TOML in {topic_path}: {exc}") from exc
    return parse_topic(data)


def parse_topic(data: Mapping[str, Any]) -> Topic:
    """Validate a topic mapping and build a :class:`Topic`."""

    if not isinstance(data, Mapping):
        raise ConfigError("topic must be a table")

    unknown = sorted(set(data) - _TOP_LEVEL_KEYS)
    if unknown:
        raise ConfigError(f"unknown topic field(s): {', '.join(unknown)}")

    schema_version = data.get("schema_version", TOPIC_SCHEMA_VERSION)
    if not isinstance(schema_version, int) or isinstance(schema_version, bool):
        raise ConfigError("topic field 'schema_version' must be an integer")
    if schema_version != TOPIC_SCHEMA_VERSION:
        raise ConfigError(
            f"unsupported topic schema_version {schema_version}; expected {TOPIC_SCHEMA_VERSION}"
        )

    metadata = data.get("metadata", {})
    if not isinstance(metadata, Mapping):
        raise ConfigError("topic field 'metadata' must be a table")

    return Topic(
        schema_version=schema_version,
        id=_required_string(data, "id", "topic"),
        title=_required_string(data, "title", "topic"),
        brief=_optional_string(data, "brief", "topic"),
        audience=_optional_string(data, "audience", "topic"),
        goals=_string_tuple(data, "goals", "topic"),
        scope_includes=_string_tuple(data, "scope_includes", "topic"),
        scope_excludes=_string_tuple(data, "scope_excludes", "topic"),
        key_questions=_string_tuple(data, "key_questions", "topic"),
        prerequisites=_string_tuple(data, "prerequisites", "topic"),
        constraints=_string_tuple(data, "constraints", "topic"),
        tags=_string_tuple(data, "tags", "topic"),
        notes=_optional_string(data, "notes", "topic"),
        metadata=MappingProxyType(dict(metadata)),
    )


def emit_topic_toml(topic: Topic) -> str:
    """Serialize a Topic to TOML. String fields via json.dumps (valid TOML
    basic strings); tuple fields as TOML arrays of quoted strings; omit
    None/empty fields; always emit id, title, schema_version."""

    def q(value: str) -> str:
        return json.dumps(value)

    lines = [
        f"id = {q(topic.id)}",
        f"title = {q(topic.title)}",
        f"schema_version = {topic.schema_version}",
    ]
    if topic.brief:
        lines.append(f"brief = {q(topic.brief)}")
    if topic.audience:
        lines.append(f"audience = {q(topic.audience)}")

    def array(key: str, values: tuple[str, ...]) -> None:
        if values:
            items = ", ".join(q(v) for v in values)
            lines.append(f"{key} = [{items}]")

    array("goals", topic.goals)
    array("scope_includes", topic.scope_includes)
    array("scope_excludes", topic.scope_excludes)
    array("key_questions", topic.key_questions)
    array("prerequisites", topic.prerequisites)
    array("constraints", topic.constraints)
    array("tags", topic.tags)

    if topic.notes:
        lines.append(f"notes = {q(topic.notes)}")

    if topic.metadata:
        lines.append("")
        lines.append("[metadata]")
        for key, value in topic.metadata.items():
            if isinstance(value, str):
                lines.append(f"{key} = {q(value)}")
            else:
                lines.append(f"{key} = {json.dumps(value)}")

    return "\n".join(lines) + "\n"


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
            raise ConfigError(f"{context} field {key!r} item #{index} must be a non-empty string")
        strings.append(item)
    return tuple(strings)
