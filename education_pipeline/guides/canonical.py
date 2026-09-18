"""Canonical guide serialization, content hashing, and the scoped splices."""

from __future__ import annotations

from dataclasses import fields, is_dataclass
import hashlib
import json
from typing import Any

from .model import Guide

_EMPTY_OMITTED_FIELDS = {"serves_goals", "goal_exclusions"}


class SpliceError(ValueError):
    """A scoped repair response cannot be merged into the base guide."""


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

    base = _base_for_splice(base_guide_json)
    fragment, fragment_id = _scoped_fragment(module_json, "module", ("modules",))

    modules = base.get("modules", [])
    index = _index_of_id(modules, module_id, "module", "the base guide")
    _require_same_id(fragment_id, module_id, "module")

    merged = dict(base)
    merged["modules"] = [*modules[:index], fragment, *modules[index + 1 :]]
    return _merged_or_refused(merged)


def _scoped_fragment(
    fragment_json: str, kind: str, forbidden_keys: tuple[str, ...]
) -> tuple[dict, str]:
    """Parse and shape-check one scoped-repair fragment.

    Shared by :func:`splice_module` and :func:`splice_section`: the reply must
    be exactly one JSON object carrying a string ``id`` and none of the keys
    that would make it a wider document (a module carries ``modules``; a
    section carries ``sections`` or ``modules``). Every violation is a
    blocking :class:`SpliceError`, never a silent fix.
    """

    try:
        fragment = json.loads(fragment_json)
    except json.JSONDecodeError as exc:
        raise SpliceError(f"{kind} response is not valid JSON: {exc}") from exc
    if not isinstance(fragment, dict):
        raise SpliceError(f"{kind} response must be a single JSON object")
    fragment_id = fragment.get("id")
    if not isinstance(fragment_id, str) or any(
        key in fragment for key in forbidden_keys
    ):
        raise SpliceError(
            f"{kind} response must be a single {kind} object with a string `id`"
        )
    return fragment, fragment_id


def _index_of_id(items: list, wanted: str, kind: str, where: str) -> int:
    """Locate the entry with ``id == wanted``, or refuse and name the known ids."""

    index = next(
        (
            position
            for position, item in enumerate(items)
            if isinstance(item, dict) and item.get("id") == wanted
        ),
        None,
    )
    if index is None:
        known = ", ".join(
            item.get("id", "?") for item in items if isinstance(item, dict)
        )
        raise SpliceError(
            f"{kind} {wanted!r} is not present in {where}; known {kind}s: {known}"
        )
    return index


def _require_same_id(fragment_id: str, wanted: str, kind: str) -> None:
    """Refuse a renamed fragment; a scoped repair never moves an id."""

    if fragment_id != wanted:
        raise SpliceError(
            f"{kind} id must stay {wanted!r}; the response renamed it to "
            f"{fragment_id!r}, and renames are blocking"
        )


def _merged_or_refused(merged: dict) -> bytes:
    """Strictly re-parse a spliced guide and return its canonical bytes."""

    from .parse import normalize_guide, parse_guide

    parsed_merged = parse_guide(json.dumps(merged, ensure_ascii=False))
    if not parsed_merged.ok:
        details = "; ".join(
            f"{item.code} at {item.path}: {item.message}"
            for item in parsed_merged.diagnostics
        )
        raise SpliceError(f"the spliced guide is not valid: {details}")
    return canonical_guide_bytes(normalize_guide(parsed_merged))


def _base_for_splice(base_guide_json: str | bytes) -> dict:
    """Parse the base guide strictly and return it as a plain dict."""

    from .parse import parse_guide

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
    return json.loads(base_text)


def splice_section(
    base_guide_json: str | bytes,
    module_id: str,
    section_id: str,
    section_json: str,
) -> bytes:
    """Deterministically replace one section of a guide with a regenerated one.

    Mirrors :func:`splice_module` one level down. ``section_json`` must be
    exactly one section object whose ``id`` equals ``section_id`` -- a rename
    is a blocking :class:`SpliceError`, never a silent fix -- carrying no
    ``sections`` or ``modules`` key, so a whole-module or whole-guide reply is
    refused rather than merged. The section is replaced in place (module and
    section order preserved) and the merged guide is re-parsed strictly, so
    element-id collisions with any sibling section or any other module, and
    references to outcomes outside the contract, are refused with the parser's
    exact diagnostics. Returns the canonical bytes of the merged whole guide;
    every section and module outside the target is byte-identical (canonical
    serialization) to the base.

    Pure function: no file I/O, no run-lifecycle coupling.
    """

    base = _base_for_splice(base_guide_json)
    fragment, fragment_id = _scoped_fragment(
        section_json, "section", ("sections", "modules")
    )

    modules = base.get("modules", [])
    module_index = _index_of_id(modules, module_id, "module", "the base guide")
    module = modules[module_index]
    sections = module.get("sections", [])
    section_index = _index_of_id(
        sections, section_id, "section", f"module {module_id!r}"
    )
    _require_same_id(fragment_id, section_id, "section")

    merged_module = dict(module)
    merged_module["sections"] = [
        *sections[:section_index],
        fragment,
        *sections[section_index + 1 :],
    ]
    merged = dict(base)
    merged["modules"] = [
        *modules[:module_index],
        merged_module,
        *modules[module_index + 1 :],
    ]
    return _merged_or_refused(merged)
