"""Canonical guide serialization and content hashing."""

from __future__ import annotations

from dataclasses import fields, is_dataclass
import hashlib
import json
from typing import Any

from .model import Guide

_EMPTY_OMITTED_FIELDS = {"serves_goals", "goal_exclusions"}


def guide_to_dict(value: Any) -> Any:
    if is_dataclass(value):
        return {
            field.name: guide_to_dict(getattr(value, field.name))
            for field in fields(value)
            if getattr(value, field.name) is not None
            and not (
                field.name in _EMPTY_OMITTED_FIELDS
                and not getattr(value, field.name)
            )
        }
    if isinstance(value, tuple):
        return [guide_to_dict(item) for item in value]
    return value


def canonical_guide_bytes(guide: Guide) -> bytes:
    text = json.dumps(
        guide_to_dict(guide),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        separators=(",", ": "),
    )
    return (text + "\n").encode("utf-8")


def guide_sha256(guide: Guide) -> str:
    return hashlib.sha256(canonical_guide_bytes(guide)).hexdigest()
