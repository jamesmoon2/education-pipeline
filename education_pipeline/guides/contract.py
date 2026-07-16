"""Machine-readable prompt contracts for guide-v1 spec/outline stages.

These are pure helpers with no file I/O: extracting and validating the
fenced JSON blocks that guide-v1 spec and outline prompts require, detecting
conflicts between them, and deterministically building the combined
``inputs/guide-contract.json`` payload bytes. Nothing here writes a file or
wires into the run lifecycle.
"""

from __future__ import annotations

import json
import re
from typing import Any, Mapping

from .parse import BLOCK_TYPES, ID_RE, RAW_HTML_RE

SPEC_CONTRACT_INFO_STRING = "education-pipeline-contract+json"
OUTLINE_CONTRACT_INFO_STRING = "education-pipeline-outline+json"

REQUIRED_INTERACTION_TYPES = {"knowledge_check", "worked_reveal", "scenario", "reflection"}

_SPEC_CONTRACT_FIELDS = {
    "contract_version",
    "guide_schema_version",
    "blueprint",
    "estimated_minutes",
    "outcomes",
    "required_interactions",
    "personalization_requirements",
    "source_policy",
}

_OUTCOME_FIELDS = {"id", "text"}

_OUTLINE_CONTRACT_FIELDS = {"contract_version", "modules"}

_MODULE_PLAN_FIELDS = {"outcome_ids", "estimated_minutes", "interaction_types"}

_FENCE_RE = re.compile(r"^```([^\n`]*)\n(.*?)\n```[ \t]*$", re.S | re.M)

_JAVASCRIPT_RE = re.compile(r"javascript\s*:", re.I)


class ContractError(ValueError):
    """A fenced prompt-contract block is missing, malformed, or schema-invalid."""


def _is_plain_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_non_empty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _extract_fenced_block(markdown_text: str, info_string: str) -> Any:
    """Extract and JSON-parse the single fenced block with ``info_string``.

    Rejects zero matches, more than one match, and malformed JSON with a
    diagnostic that states what was found and what was expected.
    """

    if not isinstance(markdown_text, str):
        raise ContractError("markdown response must be a string")
    matches = [
        match for match in _FENCE_RE.finditer(markdown_text) if match.group(1).strip() == info_string
    ]
    if not matches:
        raise ContractError(
            f"expected exactly one fenced ```{info_string} block in the response, found none"
        )
    if len(matches) > 1:
        raise ContractError(
            f"expected exactly one fenced ```{info_string} block in the response, found {len(matches)}"
        )
    body = matches[0].group(2)
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise ContractError(
            f"fenced ```{info_string} block is not valid JSON: {exc}"
        ) from exc


def _require_object(data: Any, info_string: str) -> Mapping[str, Any]:
    if not isinstance(data, dict):
        raise ContractError(f"fenced ```{info_string} block must contain a JSON object")
    return data


def _require_id(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not ID_RE.match(value):
        raise ContractError(
            f"{field} {value!r} must be a stable machine identifier matching the guide ID pattern "
            "'^[a-z][a-z0-9-]{0,63}$' -- never derive it by slugging prose"
        )
    return value


def _reject_html_or_javascript(value: Any, *, block_label: str, path: str = "") -> None:
    """Reject raw HTML tags or JavaScript in any string within a contract block.

    Spec section 6: neither contract block may contain implementation
    HTML/JavaScript. Reuses the parser's ``RAW_HTML_RE`` so both layers agree
    on what counts as raw HTML.
    """

    if isinstance(value, str):
        if RAW_HTML_RE.search(value) or _JAVASCRIPT_RE.search(value):
            raise ContractError(
                f"{block_label} field {path or 'value'!s} must not contain HTML or JavaScript; "
                f"the block is a plain data contract, got {value!r}"
            )
    elif isinstance(value, dict):
        for key, child in value.items():
            _reject_html_or_javascript(key, block_label=block_label, path=f"{path}/{key}")
            _reject_html_or_javascript(child, block_label=block_label, path=f"{path}/{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_html_or_javascript(child, block_label=block_label, path=f"{path}/{index}")


def validate_spec_contract(data: Mapping[str, Any]) -> None:
    """Validate a spec-contract block. Raises :class:`ContractError` on any defect."""

    if not isinstance(data, dict):
        raise ContractError("spec contract must be a JSON object")
    _reject_html_or_javascript(data, block_label="spec contract")

    unknown = set(data) - _SPEC_CONTRACT_FIELDS
    if unknown:
        raise ContractError(f"spec contract has unknown fields: {sorted(unknown)}")
    missing = _SPEC_CONTRACT_FIELDS - set(data)
    if missing:
        raise ContractError(f"spec contract is missing required fields: {sorted(missing)}")

    if data["contract_version"] != 1:
        raise ContractError(
            f"spec contract contract_version must be exactly 1, got {data['contract_version']!r}"
        )
    if data["guide_schema_version"] != "1.0":
        raise ContractError(
            f"spec contract guide_schema_version must be '1.0', got {data['guide_schema_version']!r}"
        )
    if not _is_non_empty_str(data["blueprint"]):
        raise ContractError("spec contract blueprint must be a non-empty string")

    minutes = data["estimated_minutes"]
    if not _is_plain_int(minutes) or not (5 <= minutes <= 10000):
        raise ContractError(
            f"spec contract estimated_minutes must be an integer between 5 and 10000, got {minutes!r}"
        )

    outcomes = data["outcomes"]
    if not isinstance(outcomes, list) or not (1 <= len(outcomes) <= 20):
        raise ContractError(
            f"spec contract outcomes must be a list of 1 to 20 items, got {outcomes!r}"
        )
    seen_ids: set[str] = set()
    for outcome in outcomes:
        if not isinstance(outcome, dict) or set(outcome) != _OUTCOME_FIELDS:
            raise ContractError(
                f"spec contract outcome entries must have exactly the fields {sorted(_OUTCOME_FIELDS)}, "
                f"got {outcome!r}"
            )
        outcome_id = _require_id(outcome["id"], field="spec contract outcome id")
        if outcome_id in seen_ids:
            raise ContractError(f"spec contract outcome id {outcome_id!r} is duplicated")
        seen_ids.add(outcome_id)
        if not _is_non_empty_str(outcome["text"]):
            raise ContractError(f"spec contract outcome {outcome_id!r} text must be a non-empty string")

    required_interactions = data["required_interactions"]
    if (
        not isinstance(required_interactions, list)
        or not required_interactions
        or len(set(required_interactions)) != len(required_interactions)
        or not set(required_interactions) <= REQUIRED_INTERACTION_TYPES
    ):
        raise ContractError(
            "spec contract required_interactions must be a non-empty subset of "
            f"{sorted(REQUIRED_INTERACTION_TYPES)} with no duplicates, got {required_interactions!r}"
        )

    personalization = data["personalization_requirements"]
    if not isinstance(personalization, list) or not all(_is_non_empty_str(item) for item in personalization):
        raise ContractError(
            "spec contract personalization_requirements must be a list of non-empty strings, "
            f"got {personalization!r}"
        )

    if not _is_non_empty_str(data["source_policy"]):
        raise ContractError("spec contract source_policy must be a non-empty string")


def validate_outline_contract(data: Mapping[str, Any]) -> None:
    """Validate an outline-contract block. Raises :class:`ContractError` on any defect."""

    if not isinstance(data, dict):
        raise ContractError("outline contract must be a JSON object")
    _reject_html_or_javascript(data, block_label="outline contract")

    unknown = set(data) - _OUTLINE_CONTRACT_FIELDS
    if unknown:
        raise ContractError(f"outline contract has unknown fields: {sorted(unknown)}")
    missing = _OUTLINE_CONTRACT_FIELDS - set(data)
    if missing:
        raise ContractError(f"outline contract is missing required fields: {sorted(missing)}")

    if data["contract_version"] != 1:
        raise ContractError(
            f"outline contract contract_version must be exactly 1, got {data['contract_version']!r}"
        )

    modules = data["modules"]
    if not isinstance(modules, dict) or not modules:
        raise ContractError(
            "outline contract modules must be a non-empty object mapping stable module IDs to module plans"
        )

    for module_id, entry in modules.items():
        _require_id(module_id, field="outline contract module id")
        if not isinstance(entry, dict) or set(entry) != _MODULE_PLAN_FIELDS:
            raise ContractError(
                f"outline contract module {module_id!r} must have exactly the fields "
                f"{sorted(_MODULE_PLAN_FIELDS)}, got {entry!r}"
            )

        outcome_ids = entry["outcome_ids"]
        if not isinstance(outcome_ids, list) or not outcome_ids:
            raise ContractError(
                f"outline contract module {module_id!r} outcome_ids must be a non-empty list of guide IDs"
            )
        for outcome_id in outcome_ids:
            _require_id(outcome_id, field=f"outline contract module {module_id!r} outcome id")

        minutes = entry["estimated_minutes"]
        if not _is_plain_int(minutes) or not (1 <= minutes <= 1000):
            raise ContractError(
                f"outline contract module {module_id!r} estimated_minutes must be an integer between "
                f"1 and 1000, got {minutes!r}"
            )

        interaction_types = entry["interaction_types"]
        if not isinstance(interaction_types, list) or not all(
            isinstance(item, str) and item in BLOCK_TYPES for item in interaction_types
        ):
            raise ContractError(
                f"outline contract module {module_id!r} interaction_types must be a list drawn from "
                f"the six registered block types {sorted(BLOCK_TYPES)}, got {interaction_types!r}"
            )


def check_contract_conflict(spec_contract: Mapping[str, Any], outline_contract: Mapping[str, Any]) -> None:
    """Detect conflicts between a validated spec contract and outline contract.

    A conflict (mismatched contract_version, or an outline module referencing
    an outcome ID the spec contract does not define) is a :class:`ContractError`.
    """

    if spec_contract.get("contract_version") != outline_contract.get("contract_version"):
        raise ContractError(
            "spec and outline contract_version values do not match: "
            f"{spec_contract.get('contract_version')!r} != {outline_contract.get('contract_version')!r}"
        )

    outcome_ids = {outcome["id"] for outcome in spec_contract.get("outcomes", [])}
    unknown_refs: set[str] = set()
    for entry in outline_contract.get("modules", {}).values():
        for outcome_id in entry.get("outcome_ids", []):
            if outcome_id not in outcome_ids:
                unknown_refs.add(outcome_id)
    if unknown_refs:
        raise ContractError(
            f"outline contract references unknown outcome ids not defined by the spec contract: "
            f"{sorted(unknown_refs)}"
        )


def extract_spec_contract(markdown_text: str) -> dict[str, Any]:
    """Extract and validate the spec-contract fenced block from a Markdown response."""

    data = _require_object(
        _extract_fenced_block(markdown_text, SPEC_CONTRACT_INFO_STRING), SPEC_CONTRACT_INFO_STRING
    )
    validate_spec_contract(data)
    return dict(data)


def extract_outline_contract(markdown_text: str) -> dict[str, Any]:
    """Extract and validate the outline-contract fenced block from a Markdown response."""

    data = _require_object(
        _extract_fenced_block(markdown_text, OUTLINE_CONTRACT_INFO_STRING), OUTLINE_CONTRACT_INFO_STRING
    )
    validate_outline_contract(data)
    return dict(data)


def build_guide_contract(
    spec_contract: Mapping[str, Any],
    outline_contract: Mapping[str, Any],
    *,
    publishable_profile_summary: str | None = None,
) -> bytes:
    """Deterministically build the ``inputs/guide-contract.json`` payload bytes.

    ``spec_contract`` and ``outline_contract`` must be validated blocks (as
    returned by :func:`extract_spec_contract` / :func:`extract_outline_contract`,
    or equivalent dicts). Identical validated inputs produce identical
    canonical bytes. This is a pure helper: it returns bytes and never writes
    a file.
    """

    validate_spec_contract(spec_contract)
    validate_outline_contract(outline_contract)
    check_contract_conflict(spec_contract, outline_contract)

    summary: str | None = None
    if publishable_profile_summary is not None:
        summary = publishable_profile_summary.strip()
        if not summary:
            raise ContractError("publishable profile summary must be a non-empty string when provided")

    payload: dict[str, Any] = {
        "contract_version": spec_contract["contract_version"],
        "guide_schema_version": spec_contract["guide_schema_version"],
        "blueprint": spec_contract["blueprint"],
        "estimated_minutes": spec_contract["estimated_minutes"],
        "outcomes": [dict(outcome) for outcome in spec_contract["outcomes"]],
        "required_interactions": list(spec_contract["required_interactions"]),
        "personalization_requirements": list(spec_contract["personalization_requirements"]),
        "source_policy": spec_contract["source_policy"],
        "modules": {
            module_id: {
                "outcome_ids": list(entry["outcome_ids"]),
                "estimated_minutes": entry["estimated_minutes"],
                "interaction_types": list(entry["interaction_types"]),
            }
            for module_id, entry in outline_contract["modules"].items()
        },
    }
    if summary is not None:
        payload["publishable_profile_summary"] = summary

    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, separators=(",", ": "))
    return (text + "\n").encode("utf-8")
