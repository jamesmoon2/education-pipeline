"""Canonical guide serialization, content hashing, and the module splice."""

from __future__ import annotations

from dataclasses import fields, is_dataclass
import hashlib
import json
from typing import Any, Mapping, Sequence

from .model import Guide

_EMPTY_OMITTED_FIELDS = {"serves_goals", "goal_exclusions"}


class SpliceError(ValueError):
    """A module-scoped repair response cannot be merged into the base guide."""


class AssemblyError(SpliceError):
    """Per-module draft responses cannot be assembled into one guide.

    ``module_ids`` names the modules implicated by the failure -- both owners
    of a cross-module id collision, the missing or extra module, the module
    whose fragment is malformed -- so a caller can rerun exactly those units.
    It is empty when the failure belongs to the skeleton rather than to any
    module. A subclass of :class:`SpliceError` so callers that already map
    splice failures onto their own error type keep working.
    """

    def __init__(self, module_ids: Sequence[str], message: str) -> None:
        self.module_ids: tuple[str, ...] = tuple(module_ids)
        super().__init__(message)


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


def _guide_text(value: str | bytes) -> str:
    return value.decode("utf-8") if isinstance(value, bytes) else value


def _load_module_fragment(module_json: str | bytes) -> dict[str, Any]:
    """Decode one module fragment and apply the shape rules a splice requires.

    Exactly one JSON object, a string ``id``, and no ``modules`` key (which
    would mean a whole guide was returned instead of one module). Shared by
    :func:`splice_module` and :func:`assemble_guide` so both refuse the same
    shapes with the same wording.
    """

    try:
        fragment = json.loads(_guide_text(module_json))
    except json.JSONDecodeError as exc:
        raise SpliceError(f"module response is not valid JSON: {exc}") from exc
    if not isinstance(fragment, dict):
        raise SpliceError("module response must be a single JSON object")
    if not isinstance(fragment.get("id"), str) or "modules" in fragment:
        raise SpliceError(
            "module response must be a single module object with a string `id`"
        )
    return fragment


def _check_fragment_id(fragment_id: str, module_id: str) -> None:
    """Refuse a renamed module; a rename is blocking, never a silent fix."""

    if fragment_id != module_id:
        raise SpliceError(
            f"module id must stay {module_id!r}; the response renamed it to "
            f"{fragment_id!r}, and renames are blocking"
        )


def _parse_merged_guide(merged: Mapping[str, Any]) -> tuple[Any, str]:
    """Strictly re-parse a merged guide; return ``(parsed, details)``."""

    from .parse import parse_guide

    parsed = parse_guide(json.dumps(merged, ensure_ascii=False))
    details = "; ".join(
        f"{item.code} at {item.path}: {item.message}" for item in parsed.diagnostics
    )
    return parsed, details


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
    base = json.loads(_guide_text(base_guide_json))

    fragment = _load_module_fragment(module_json)
    fragment_id = fragment["id"]

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
    _check_fragment_id(fragment_id, module_id)

    merged = dict(base)
    merged["modules"] = [*modules[:index], fragment, *modules[index + 1 :]]
    parsed_merged, details = _parse_merged_guide(merged)
    if not parsed_merged.ok:
        raise SpliceError(f"the spliced guide is not valid: {details}")
    return canonical_guide_bytes(normalize_guide(parsed_merged))


def _collect_ids(value: Any) -> list[str]:
    """Every id the parser's single namespace would claim inside ``value``.

    Element ids live at the ``id`` key of every object in the guide model
    (module, section, block, choice, reveal step, glossary entry, source), so
    one recursive walk finds them all.
    """

    found: list[str] = []
    if isinstance(value, Mapping):
        identifier = value.get("id")
        if isinstance(identifier, str):
            found.append(identifier)
        for key, item in value.items():
            if key != "id":
                found.extend(_collect_ids(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(_collect_ids(item))
    return found


def _merge_contributions(
    merged: dict[str, list[Any]],
    owners: dict[str, str],
    entries: Any,
    key: str,
    owner: str,
) -> None:
    """Merge one ``glossary``/``sources`` contribution list by id.

    The same id contributed twice with identical content is allowed (two
    modules may legitimately need the same term); differing content is an
    :class:`AssemblyError` naming both contributors, because no deterministic
    rule can pick a winner.
    """

    if entries is None:
        return
    if not isinstance(entries, list):
        raise AssemblyError((owner,), f"`{key}` contributions must be a JSON array")
    for entry in entries:
        if not isinstance(entry, Mapping) or not isinstance(entry.get("id"), str):
            raise AssemblyError(
                (owner,),
                f"every `{key}` contribution must be an object with a string `id`",
            )
        entry_id = entry["id"]
        previous_owner = owners.get(entry_id)
        if previous_owner is None:
            owners[entry_id] = owner
            merged[key].append(dict(entry))
            continue
        existing = next(item for item in merged[key] if item.get("id") == entry_id)
        if dict(entry) != existing:
            implicated = tuple(
                dict.fromkeys(
                    name for name in (previous_owner, owner) if name is not None
                )
            )
            raise AssemblyError(
                implicated,
                f"`{key}` entry {entry_id!r} is contributed twice with different "
                f"content (by {previous_owner} and {owner}); "
                "identical duplicates are allowed, conflicting ones are not",
            )


def _implicated_modules(diagnostics: Any, module_order: tuple[str, ...]) -> tuple[str, ...]:
    """Map ``/modules/<i>`` diagnostic paths back to module ids."""

    implicated: list[str] = []
    for item in diagnostics:
        parts = item.path.split("/")
        if len(parts) >= 3 and parts[1] == "modules" and parts[2].isdigit():
            index = int(parts[2])
            if index < len(module_order) and module_order[index] not in implicated:
                implicated.append(module_order[index])
    return tuple(implicated)


def assemble_guide(
    skeleton_json: str | bytes,
    modules: Mapping[str, str | bytes],
    *,
    module_order: Sequence[str],
) -> bytes:
    """Deterministically assemble one guide from a skeleton and its modules.

    ``skeleton_json`` is a course skeleton (see
    :func:`education_pipeline.guides.parse.check_skeleton`): the whole guide
    with every module reduced to a sectionless stub. ``modules`` maps module
    id to that module's drafted JSON fragment -- exactly one module object
    with the same ``id`` and no ``modules`` key, the same rules
    :func:`splice_module` applies -- optionally carrying ``glossary`` and
    ``sources`` contribution lists for entries the skeleton lacks. Each stub
    is replaced by its fragment in ``module_order``, contributions are merged
    by id (skeleton first, then modules in order), and the merged document is
    re-parsed strictly.

    Cross-module element-id collisions are detected *before* the strict parse,
    so the :class:`AssemblyError` names both owners and only those modules
    need rerunning. Mapping insertion order is irrelevant; only
    ``module_order`` decides. Returns the canonical bytes of the merged guide.

    Pure function: no file I/O, no run-lifecycle coupling.
    """

    from .parse import check_skeleton, normalize_guide

    order = tuple(module_order)
    checked = check_skeleton(skeleton_json, module_order=order)
    if not checked.ok or checked.parsed is None:
        details = "; ".join(
            f"{item.code} at {item.path}: {item.message}"
            for item in checked.diagnostics
        )
        raise AssemblyError((), f"the draft skeleton is not valid: {details}")
    skeleton = dict(checked.parsed)

    provided = set(modules)
    expected = set(order)
    missing = sorted(expected - provided)
    extra = sorted(provided - expected)
    if missing or extra:
        parts = []
        if missing:
            parts.append(f"missing module responses: {', '.join(missing)}")
        if extra:
            parts.append(f"unexpected module responses: {', '.join(extra)}")
        raise AssemblyError((*missing, *extra), "; ".join(parts))

    merged_lists: dict[str, list[Any]] = {"glossary": [], "sources": []}
    id_owners: dict[str, str] = {}
    contribution_owners: dict[str, str] = {}
    for key in merged_lists:
        skeleton_entries = skeleton.get(key)
        if isinstance(skeleton_entries, list):
            for entry in skeleton_entries:
                if isinstance(entry, Mapping) and isinstance(entry.get("id"), str):
                    contribution_owners[entry["id"]] = "the skeleton"
                merged_lists[key].append(dict(entry) if isinstance(entry, Mapping) else entry)

    skeleton_without_modules = {
        key: value for key, value in skeleton.items() if key != "modules"
    }
    for identifier in _collect_ids(skeleton_without_modules):
        id_owners.setdefault(identifier, "the skeleton")

    fragments: dict[str, dict[str, Any]] = {}
    for module_id in order:
        try:
            fragment = _load_module_fragment(modules[module_id])
            _check_fragment_id(fragment["id"], module_id)
        except SpliceError as exc:
            raise AssemblyError((module_id,), f"module {module_id!r}: {exc}") from exc
        body = {
            key: value
            for key, value in fragment.items()
            if key not in merged_lists
        }
        for identifier in _collect_ids(body):
            owner = id_owners.get(identifier)
            if owner is None:
                id_owners[identifier] = module_id
                continue
            implicated = tuple(
                dict.fromkeys(
                    name for name in (owner, module_id) if name != "the skeleton"
                )
            )
            raise AssemblyError(
                implicated,
                f"element id {identifier!r} is declared twice: by {owner} and by "
                f"module {module_id!r}; every section and block id must start "
                f"with its own `<module-id>-` prefix",
            )
        for key in merged_lists:
            _merge_contributions(
                merged_lists, contribution_owners, fragment.get(key), key, module_id
            )
        fragments[module_id] = body

    merged = dict(skeleton)
    merged["modules"] = [fragments[module_id] for module_id in order]
    for key, entries in merged_lists.items():
        merged[key] = entries

    parsed, details = _parse_merged_guide(merged)
    if not parsed.ok:
        raise AssemblyError(
            _implicated_modules(parsed.diagnostics, order),
            f"the assembled guide is not valid: {details}",
        )
    return canonical_guide_bytes(normalize_guide(parsed))
