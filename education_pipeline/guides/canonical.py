"""Canonical guide serialization, content hashing, and the module splice."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
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


_FRAME_ROOT_KEYS = ("schema_version", "course", "outcomes", "modules", "glossary", "sources")


def _module_fragment(module_json: str | bytes, module_id: str) -> dict:
    """Load one module response fragment and check it is that single module.

    Shared by :func:`splice_module` and :func:`assemble_guide`: a payload that
    is not a lone module object, or that renames the module, is a blocking
    :class:`SpliceError` rather than a silent fix.
    """

    try:
        text = (
            module_json.decode("utf-8")
            if isinstance(module_json, bytes)
            else module_json
        )
        fragment = json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SpliceError(f"module response is not valid JSON: {exc}") from exc
    if not isinstance(fragment, dict):
        raise SpliceError("module response must be a single JSON object")
    fragment_id = fragment.get("id")
    if not isinstance(fragment_id, str) or "modules" in fragment:
        raise SpliceError(
            "module response must be a single module object with a string `id`"
        )
    if fragment_id != module_id:
        raise SpliceError(
            f"module id must stay {module_id!r}; the response renamed it to "
            f"{fragment_id!r}, and renames are blocking"
        )
    return fragment


def _reparse_strictly(merged: dict, *, subject: str) -> bytes:
    """Re-parse a merged guide strictly and return its canonical bytes.

    Element-id collisions across modules and references to outcomes outside
    the contract surface here with the parser's exact diagnostics.
    """

    from .parse import normalize_guide, parse_guide

    parsed = parse_guide(json.dumps(merged, ensure_ascii=False))
    if not parsed.ok:
        details = "; ".join(
            f"{item.code} at {item.path}: {item.message}"
            for item in parsed.diagnostics
        )
        raise SpliceError(f"the {subject} is not valid: {details}")
    return canonical_guide_bytes(normalize_guide(parsed))


def validate_frame(
    frame_json: str | bytes, *, module_ids: Sequence[str]
) -> dict:
    """Lenient shape check of a course frame; returns the loaded object.

    A frame is the whole guide object with one **stub** per contract module:
    the parser requires at least one section per module, so a frame can never
    pass strict parsing and is never run through ``parse_guide``. The checks
    here are exactly the shape the assembly step depends on: a top-level
    object with exactly the registered root keys, ``modules`` a list of
    objects whose string ``id`` values equal ``module_ids`` in contract
    order, and every stub carrying an empty ``sections`` list. Every other
    key passes through opaquely; strict validation happens on the merged
    guide at assembly.

    Pure function: no file I/O.
    """

    try:
        text = (
            frame_json.decode("utf-8") if isinstance(frame_json, bytes) else frame_json
        )
        frame = json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SpliceError(f"frame response is not valid JSON: {exc}") from exc
    if not isinstance(frame, dict):
        raise SpliceError("frame response must be a single JSON object")

    present = set(frame)
    expected_keys = set(_FRAME_ROOT_KEYS)
    missing = sorted(expected_keys - present)
    unknown = sorted(present - expected_keys)
    if missing or unknown:
        details = []
        if missing:
            details.append(f"missing: {', '.join(missing)}")
        if unknown:
            details.append(f"unknown: {', '.join(unknown)}")
        raise SpliceError(
            "frame response must use exactly the root keys "
            f"{', '.join(_FRAME_ROOT_KEYS)} ({'; '.join(details)})"
        )

    modules = frame["modules"]
    if not isinstance(modules, list):
        raise SpliceError("frame `modules` must be a list of module stubs")
    stub_ids = []
    for position, stub in enumerate(modules):
        if not isinstance(stub, dict):
            raise SpliceError(
                f"frame module stub at position {position} must be a JSON object"
            )
        stub_id = stub.get("id")
        if not isinstance(stub_id, str):
            raise SpliceError(
                f"frame module stub at position {position} must have a string `id`"
            )
        stub_ids.append(stub_id)

    expected_ids = list(module_ids)
    if stub_ids != expected_ids:
        raise SpliceError(
            "frame modules must be exactly the contract's module ids in contract "
            f"order; expected [{', '.join(expected_ids)}], got "
            f"[{', '.join(stub_ids)}]"
        )

    for stub in modules:
        sections = stub.get("sections")
        if not isinstance(sections, list) or sections:
            raise SpliceError(
                f"frame module stub {stub['id']!r} must carry an empty "
                "`sections` list; section content belongs to the module parts"
            )
    return frame


def assemble_guide(
    frame_json: str | bytes,
    modules: Mapping[str, str],
    *,
    module_ids: Sequence[str],
) -> bytes:
    """Merge a validated frame and its per-module responses into one guide.

    ``modules`` maps each module id to that module's JSON response text. The
    frame's stubs must be exactly ``module_ids`` in contract order and the
    mapping must hold exactly those ids; each response must be a single
    module object keeping its id. The merged guide is re-parsed strictly, so
    duplicate element ids and references to outcomes outside the contract are
    refused with the parser's exact diagnostics. Identical inputs yield
    identical canonical bytes.

    Pure function: no file I/O, no run-lifecycle coupling.
    """

    frame = validate_frame(frame_json, module_ids=module_ids)
    expected_ids = list(module_ids)

    supplied = set(modules)
    missing = [module_id for module_id in expected_ids if module_id not in supplied]
    unexpected = sorted(supplied - set(expected_ids))
    if missing:
        raise SpliceError(
            f"no module response was supplied for: {', '.join(missing)}"
        )
    if unexpected:
        raise SpliceError(
            "module responses outside the contract were supplied: "
            f"{', '.join(unexpected)}"
        )

    merged = dict(frame)
    merged["modules"] = [
        _module_fragment(modules[module_id], module_id) for module_id in expected_ids
    ]
    return _reparse_strictly(merged, subject="assembled guide")


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
    base = json.loads(base_text)

    fragment = _module_fragment(module_json, module_id)

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

    merged = dict(base)
    merged["modules"] = [*modules[:index], fragment, *modules[index + 1 :]]
    return _reparse_strictly(merged, subject="spliced guide")
