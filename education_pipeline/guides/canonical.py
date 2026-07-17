"""Canonical guide serialization, content hashing, and the module splice."""

from __future__ import annotations

from dataclasses import fields, is_dataclass
import hashlib
import json
from typing import Any

from .model import Guide

_EMPTY_OMITTED_FIELDS = {"serves_goals", "goal_exclusions"}


class SpliceError(ValueError):
    """A module-scoped repair response cannot be merged into the base guide."""


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


def splice_module(
    base_guide_json: str | bytes, module_id: str, module_json: str
) -> bytes:
    """Deterministically replace one module of a guide with a regenerated one.

    ``module_json`` must be exactly one module object whose ``id`` equals
    ``module_id`` — a rename is a blocking :class:`SpliceError`, never a
    silent fix. The module is replaced in place (module order preserved) and
    the merged guide is re-parsed strictly, so element-id collisions with the
    rest of the guide and references to outcomes outside the contract are
    refused with the parser's exact diagnostics. Returns the canonical bytes
    of the merged whole guide; every module outside the target is
    byte-identical (canonical serialization) to the base.

    Pure function: no file I/O, no run-lifecycle coupling.
    """

    from .parse import normalize_guide, parse_guide

    parsed_base = parse_guide(base_guide_json)
    if not parsed_base.ok:
        raise SpliceError(
            "the base guide is not a valid guide document; "
            "correct the approved draft before a scoped repair"
        )
    base_text = (
        base_guide_json.decode("utf-8")
        if isinstance(base_guide_json, bytes)
        else base_guide_json
    )
    base = json.loads(base_text)

    try:
        fragment = json.loads(module_json)
    except json.JSONDecodeError as exc:
        raise SpliceError(f"module response is not valid JSON: {exc}") from exc
    if not isinstance(fragment, dict):
        raise SpliceError("module response must be a single JSON object")
    fragment_id = fragment.get("id")
    if not isinstance(fragment_id, str) or "modules" in fragment:
        raise SpliceError(
            "module response must be a single module object with a string `id`"
        )

    modules = base.get("modules", [])
    index = next(
        (
            position
            for position, module in enumerate(modules)
            if isinstance(module, dict) and module.get("id") == module_id
        ),
        None,
    )
    if index is None:
        known = ", ".join(
            module.get("id", "?") for module in modules if isinstance(module, dict)
        )
        raise SpliceError(
            f"module {module_id!r} is not present in the base guide; "
            f"known modules: {known}"
        )
    if fragment_id != module_id:
        raise SpliceError(
            f"module id must stay {module_id!r}; the response renamed it to "
            f"{fragment_id!r}, and renames are blocking"
        )

    merged = dict(base)
    merged["modules"] = [*modules[:index], fragment, *modules[index + 1 :]]
    parsed_merged = parse_guide(json.dumps(merged, ensure_ascii=False))
    if not parsed_merged.ok:
        details = "; ".join(
            f"{item.code} at {item.path}: {item.message}"
            for item in parsed_merged.diagnostics
        )
        raise SpliceError(f"the spliced guide is not valid: {details}")
    return canonical_guide_bytes(normalize_guide(parsed_merged))
