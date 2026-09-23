"""Canonical guide serialization, content hashing, and the scoped splices."""

from __future__ import annotations

from dataclasses import Field, fields, is_dataclass
import hashlib
import json
from typing import Any, Iterator, Mapping, Sequence

from .model import Guide

_EMPTY_OMITTED_FIELDS = {"serves_goals", "goal_exclusions"}


class SpliceError(ValueError):
    """A scoped repair response cannot be merged into the base guide."""


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


def json_field_items(value: Any) -> Iterator[tuple[str, Any, Field]]:
    """Yield ``(json key, value, field)`` for each serialized field of a dataclass.

    The key is ``field.metadata["json"]`` when set (``from`` is a Python
    keyword), else the field name. A field is skipped when it is ``None``, or
    empty and either named in ``_EMPTY_OMITTED_FIELDS`` or marked
    ``omit_empty``. Shared by :func:`guide_to_dict` and validation's text walk
    so their paths agree.
    """

    for field in fields(value):
        item = getattr(value, field.name)
        if item is None:
            continue
        if not item and (
            field.name in _EMPTY_OMITTED_FIELDS or field.metadata.get("omit_empty")
        ):
            continue
        yield field.metadata.get("json", field.name), item, field


def guide_to_dict(value: Any) -> Any:
    if is_dataclass(value):
        result = {}
        for key, item, field in json_field_items(value):
            keyed = field.metadata.get("json_keyed")
            if keyed is not None:
                key_attr, value_attr = keyed
                result[key] = {
                    getattr(entry, key_attr): guide_to_dict(getattr(entry, value_attr))
                    for entry in item
                }
            else:
                result[key] = guide_to_dict(item)
        return result
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


def _scoped_fragment(
    fragment_json: str | bytes, kind: str, forbidden_keys: tuple[str, ...]
) -> tuple[dict[str, Any], str]:
    """Parse and shape-check one scoped fragment.

    Shared by :func:`splice_module`, :func:`splice_section` and
    :func:`assemble_guide`: the reply must be exactly one JSON object carrying
    a string ``id`` and none of the keys that would make it a wider document
    (a module carries ``modules``; a section carries ``sections`` or
    ``modules``). Every violation is a blocking :class:`SpliceError`, never a
    silent fix, and every caller refuses the same shapes with the same
    wording.
    """

    try:
        fragment = json.loads(_guide_text(fragment_json))
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


def _base_for_splice(base_guide_json: str | bytes) -> dict:
    """Parse the base guide strictly and return it as a plain dict."""

    from .parse import parse_guide

    parsed_base = parse_guide(base_guide_json)
    if not parsed_base.ok:
        raise SpliceError(
            "the base guide is not a valid guide document; "
            "correct the approved draft before a scoped repair"
        )
    return json.loads(_guide_text(base_guide_json))


def _parse_merged_guide(merged: Mapping[str, Any]) -> tuple[Any, str]:
    """Strictly re-parse a merged guide; return ``(parsed, details)``."""

    from .parse import parse_guide

    parsed = parse_guide(json.dumps(merged, ensure_ascii=False))
    details = "; ".join(
        f"{item.code} at {item.path}: {item.message}" for item in parsed.diagnostics
    )
    return parsed, details


def _merged_or_refused(merged: Mapping[str, Any]) -> bytes:
    """Strictly re-parse a spliced guide and return its canonical bytes."""

    from .parse import normalize_guide

    parsed_merged, details = _parse_merged_guide(merged)
    if not parsed_merged.ok:
        raise SpliceError(f"the spliced guide is not valid: {details}")
    return canonical_guide_bytes(normalize_guide(parsed_merged))


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


def _collect_ids(value: Any) -> list[str]:
    """Every id the parser's single namespace would claim inside ``value``.

    Element ids live at the ``id`` key of every object in the guide model
    (module, section, block, choice, reveal step, glossary entry, source), so
    one recursive walk finds them all. A diagram's node, event, item and
    criterion ids are diagram-local, so only the diagram's own id is claimed.
    """

    found: list[str] = []
    if isinstance(value, Mapping):
        identifier = value.get("id")
        if isinstance(identifier, str):
            found.append(identifier)
        if value.get("type") == "diagram":
            return found
        for key, item in value.items():
            if key != "id":
                found.extend(_collect_ids(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(_collect_ids(item))
    return found


def _merge_contributions(
    merged: dict[str, list[Any]],
    owners: dict[str, tuple[str, str]],
    entries: Any,
    key: str,
    owner: str,
) -> None:
    """Merge one ``glossary``/``sources`` contribution list by id.

    The same id contributed twice with identical content is allowed (two
    modules may legitimately need the same term); differing content is an
    :class:`AssemblyError` naming both contributors, because no deterministic
    rule can pick a winner.

    ``owners`` spans both kinds -- the parser keeps one id namespace, so a
    glossary entry and a source may not share an id -- but it records which
    kind claimed each id, because the duplicate lookup below searches only
    the current kind's merged list. A cross-kind duplicate is refused by name
    rather than left to raise a bare ``StopIteration``.
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
        previous = owners.get(entry_id)
        if previous is None:
            owners[entry_id] = (key, owner)
            merged[key].append(dict(entry))
            continue
        previous_kind, previous_owner = previous
        implicated = tuple(
            dict.fromkeys(name for name in (previous_owner, owner) if name is not None)
        )
        if previous_kind != key:
            raise AssemblyError(
                implicated,
                f"id {entry_id!r} is contributed as a `{previous_kind}` entry by "
                f"{previous_owner} and as a `{key}` entry by {owner}; the guide "
                "keeps one id namespace, so the same id cannot name both",
            )
        existing = next(item for item in merged[key] if item.get("id") == entry_id)
        if dict(entry) != existing:
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
    contribution_owners: dict[str, tuple[str, str]] = {}
    for key in merged_lists:
        skeleton_entries = skeleton.get(key)
        if isinstance(skeleton_entries, list):
            for entry in skeleton_entries:
                if isinstance(entry, Mapping) and isinstance(entry.get("id"), str):
                    contribution_owners[entry["id"]] = (key, "the skeleton")
                merged_lists[key].append(dict(entry) if isinstance(entry, Mapping) else entry)

    skeleton_without_modules = {
        key: value for key, value in skeleton.items() if key != "modules"
    }
    for identifier in _collect_ids(skeleton_without_modules):
        id_owners.setdefault(identifier, "the skeleton")

    fragments: dict[str, dict[str, Any]] = {}
    for module_id in order:
        try:
            fragment, fragment_id = _scoped_fragment(
                modules[module_id], "module", ("modules",)
            )
            _require_same_id(fragment_id, module_id, "module")
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
