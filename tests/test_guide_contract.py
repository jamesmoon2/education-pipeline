from __future__ import annotations

import json

import pytest

from education_pipeline.guides.contract import (
    ContractError,
    build_guide_contract,
    check_contract_conflict,
    extract_outline_contract,
    extract_spec_contract,
)


VALID_SPEC_CONTRACT = {
    "contract_version": 1,
    "guide_schema_version": "1.0",
    "blueprint": "conceptual-foundations",
    "estimated_minutes": 30,
    "outcomes": [{"id": "identify-loop", "text": "Identify reinforcing and balancing feedback."}],
    "required_interactions": ["knowledge_check", "worked_reveal", "scenario", "reflection"],
    "personalization_requirements": ["Use gardening examples where they clarify the concept."],
    "source_policy": "Sources required for factual claims that are not common knowledge.",
}

VALID_OUTLINE_CONTRACT = {
    "contract_version": 1,
    "modules": {
        "feedback-loops": {
            "outcome_ids": ["identify-loop"],
            "estimated_minutes": 30,
            "interaction_types": ["knowledge_check", "worked_reveal"],
        },
    },
}


def _spec_markdown(contract: dict = VALID_SPEC_CONTRACT, *, extra_fence: str | None = None) -> str:
    body = (
        "# Course Specification: Systems Thinking\n\n"
        "## Learning Outcomes\n"
        "- Identify reinforcing and balancing feedback.\n\n"
        "```education-pipeline-contract+json\n"
        f"{json.dumps(contract)}\n"
        "```\n"
    )
    if extra_fence is not None:
        body += f"\n```education-pipeline-contract+json\n{extra_fence}\n```\n"
    return body


def _outline_markdown(contract: dict = VALID_OUTLINE_CONTRACT) -> str:
    return (
        "# Course Outline: Systems Thinking\n\n"
        "## Modules\n"
        "1. Feedback loops\n\n"
        "```education-pipeline-outline+json\n"
        f"{json.dumps(contract)}\n"
        "```\n"
    )


# --- extract_spec_contract -------------------------------------------------


def test_extract_spec_contract_returns_validated_dict() -> None:
    data = extract_spec_contract(_spec_markdown())
    assert data == VALID_SPEC_CONTRACT


def test_extract_spec_contract_rejects_zero_blocks() -> None:
    markdown = "# Course Specification: X\n\nNo fenced block here.\n"
    with pytest.raises(ContractError, match="found none"):
        extract_spec_contract(markdown)


def test_extract_spec_contract_rejects_multiple_blocks() -> None:
    markdown = _spec_markdown(extra_fence=json.dumps(VALID_SPEC_CONTRACT))
    with pytest.raises(ContractError, match="found 2"):
        extract_spec_contract(markdown)


def test_extract_spec_contract_rejects_malformed_json() -> None:
    markdown = "# Spec\n\n```education-pipeline-contract+json\n{not json\n```\n"
    with pytest.raises(ContractError, match="not valid JSON"):
        extract_spec_contract(markdown)


def test_extract_spec_contract_rejects_non_object_json() -> None:
    markdown = "# Spec\n\n```education-pipeline-contract+json\n[1, 2, 3]\n```\n"
    with pytest.raises(ContractError, match="JSON object"):
        extract_spec_contract(markdown)


@pytest.mark.parametrize(
    "mutation, match",
    [
        ({"contract_version": 2}, "contract_version"),
        ({"guide_schema_version": "2.0"}, "guide_schema_version"),
        ({"blueprint": ""}, "blueprint"),
        ({"estimated_minutes": 1}, "estimated_minutes"),
        ({"estimated_minutes": 100000}, "estimated_minutes"),
        ({"outcomes": []}, "outcomes"),
        ({"required_interactions": []}, "required_interactions"),
        ({"required_interactions": ["knowledge_check", "unknown_type"]}, "required_interactions"),
        ({"source_policy": ""}, "source_policy"),
    ],
)
def test_extract_spec_contract_rejects_invalid_fields(mutation: dict, match: str) -> None:
    contract = {**VALID_SPEC_CONTRACT, **mutation}
    with pytest.raises(ContractError, match=match):
        extract_spec_contract(_spec_markdown(contract))


def test_extract_spec_contract_rejects_unknown_field() -> None:
    contract = {**VALID_SPEC_CONTRACT, "extra_field": "nope"}
    with pytest.raises(ContractError, match="unknown fields"):
        extract_spec_contract(_spec_markdown(contract))


def test_extract_spec_contract_rejects_missing_field() -> None:
    contract = dict(VALID_SPEC_CONTRACT)
    del contract["source_policy"]
    with pytest.raises(ContractError, match="missing required fields"):
        extract_spec_contract(_spec_markdown(contract))


def test_extract_spec_contract_rejects_invalid_outcome_id() -> None:
    contract = {
        **VALID_SPEC_CONTRACT,
        "outcomes": [{"id": "Identify-Loop", "text": "Bad id casing."}],
    }
    with pytest.raises(ContractError, match="guide ID pattern"):
        extract_spec_contract(_spec_markdown(contract))


def test_extract_spec_contract_rejects_duplicate_outcome_id() -> None:
    contract = {
        **VALID_SPEC_CONTRACT,
        "outcomes": [
            {"id": "identify-loop", "text": "First."},
            {"id": "identify-loop", "text": "Duplicate."},
        ],
    }
    with pytest.raises(ContractError, match="duplicated"):
        extract_spec_contract(_spec_markdown(contract))


# --- extract_outline_contract ----------------------------------------------


def test_extract_outline_contract_returns_validated_dict() -> None:
    data = extract_outline_contract(_outline_markdown())
    assert data == VALID_OUTLINE_CONTRACT


def test_extract_outline_contract_rejects_zero_blocks() -> None:
    with pytest.raises(ContractError, match="found none"):
        extract_outline_contract("# Course Outline\n\nNo block.\n")


def test_extract_outline_contract_rejects_empty_modules() -> None:
    contract = {**VALID_OUTLINE_CONTRACT, "modules": {}}
    with pytest.raises(ContractError, match="modules"):
        extract_outline_contract(_outline_markdown(contract))


def test_extract_outline_contract_rejects_invalid_module_id() -> None:
    contract = {
        "contract_version": 1,
        "modules": {
            "Feedback_Loops": {
                "outcome_ids": ["identify-loop"],
                "estimated_minutes": 30,
                "interaction_types": [],
            },
        },
    }
    with pytest.raises(ContractError, match="guide ID pattern"):
        extract_outline_contract(_outline_markdown(contract))


def test_extract_outline_contract_rejects_unknown_interaction_type() -> None:
    contract = {
        "contract_version": 1,
        "modules": {
            "feedback-loops": {
                "outcome_ids": ["identify-loop"],
                "estimated_minutes": 30,
                "interaction_types": ["quiz"],
            },
        },
    }
    with pytest.raises(ContractError, match="interaction_types"):
        extract_outline_contract(_outline_markdown(contract))


def test_extract_outline_contract_rejects_out_of_range_minutes() -> None:
    contract = {
        "contract_version": 1,
        "modules": {
            "feedback-loops": {
                "outcome_ids": ["identify-loop"],
                "estimated_minutes": 0,
                "interaction_types": [],
            },
        },
    }
    with pytest.raises(ContractError, match="estimated_minutes"):
        extract_outline_contract(_outline_markdown(contract))


# --- check_contract_conflict -----------------------------------------------


def test_check_contract_conflict_passes_for_consistent_contracts() -> None:
    check_contract_conflict(VALID_SPEC_CONTRACT, VALID_OUTLINE_CONTRACT)


def test_check_contract_conflict_detects_version_mismatch() -> None:
    outline = {**VALID_OUTLINE_CONTRACT, "contract_version": 2}
    with pytest.raises(ContractError, match="contract_version"):
        check_contract_conflict(VALID_SPEC_CONTRACT, outline)


def test_check_contract_conflict_detects_unknown_outcome_reference() -> None:
    outline = {
        "contract_version": 1,
        "modules": {
            "feedback-loops": {
                "outcome_ids": ["not-a-real-outcome"],
                "estimated_minutes": 30,
                "interaction_types": [],
            },
        },
    }
    with pytest.raises(ContractError, match="unknown outcome"):
        check_contract_conflict(VALID_SPEC_CONTRACT, outline)


# --- build_guide_contract ---------------------------------------------------


def test_build_guide_contract_is_deterministic() -> None:
    first = build_guide_contract(VALID_SPEC_CONTRACT, VALID_OUTLINE_CONTRACT)
    second = build_guide_contract(dict(VALID_SPEC_CONTRACT), dict(VALID_OUTLINE_CONTRACT))
    assert first == second
    assert isinstance(first, bytes)


def test_build_guide_contract_canonical_bytes_shape() -> None:
    payload_bytes = build_guide_contract(VALID_SPEC_CONTRACT, VALID_OUTLINE_CONTRACT)
    text = payload_bytes.decode("utf-8")
    assert text.endswith("\n")
    assert not text.endswith("\n\n")
    payload = json.loads(text)
    assert payload["contract_version"] == 1
    assert payload["guide_schema_version"] == "1.0"
    assert payload["blueprint"] == "conceptual-foundations"
    assert payload["estimated_minutes"] == 30
    assert payload["outcomes"] == VALID_SPEC_CONTRACT["outcomes"]
    assert payload["required_interactions"] == VALID_SPEC_CONTRACT["required_interactions"]
    assert payload["personalization_requirements"] == VALID_SPEC_CONTRACT["personalization_requirements"]
    assert payload["source_policy"] == VALID_SPEC_CONTRACT["source_policy"]
    assert payload["modules"] == VALID_OUTLINE_CONTRACT["modules"]
    assert "publishable_profile_summary" not in payload
    # Canonical formatting: two-space indent, sorted keys, no ASCII escaping.
    reserialized = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    assert reserialized == text


def test_build_guide_contract_includes_publishable_profile_summary() -> None:
    payload_bytes = build_guide_contract(
        VALID_SPEC_CONTRACT,
        VALID_OUTLINE_CONTRACT,
        publishable_profile_summary="Early-career team learning systems thinking.",
    )
    payload = json.loads(payload_bytes.decode("utf-8"))
    assert payload["publishable_profile_summary"] == "Early-career team learning systems thinking."


def test_build_guide_contract_rejects_blank_publishable_profile_summary() -> None:
    with pytest.raises(ContractError, match="publishable profile summary"):
        build_guide_contract(VALID_SPEC_CONTRACT, VALID_OUTLINE_CONTRACT, publishable_profile_summary="   ")


def test_build_guide_contract_rejects_conflicting_inputs() -> None:
    outline = {
        "contract_version": 1,
        "modules": {
            "feedback-loops": {
                "outcome_ids": ["not-a-real-outcome"],
                "estimated_minutes": 30,
                "interaction_types": [],
            },
        },
    }
    with pytest.raises(ContractError, match="unknown outcome"):
        build_guide_contract(VALID_SPEC_CONTRACT, outline)


def test_build_guide_contract_rejects_invalid_spec_contract() -> None:
    with pytest.raises(ContractError):
        build_guide_contract({**VALID_SPEC_CONTRACT, "contract_version": 2}, VALID_OUTLINE_CONTRACT)


# --- HTML/JavaScript rejection (spec section 6: neither block may contain them) ---


def test_extract_spec_contract_rejects_html_in_string_field() -> None:
    contract = {**VALID_SPEC_CONTRACT, "blueprint": "<script>alert(1)</script>"}
    with pytest.raises(ContractError, match="HTML"):
        extract_spec_contract(_spec_markdown(contract))


def test_extract_spec_contract_rejects_html_in_nested_string_field() -> None:
    contract = {
        **VALID_SPEC_CONTRACT,
        "outcomes": [{"id": "identify-loop", "text": "Identify <b>feedback</b> loops."}],
    }
    with pytest.raises(ContractError, match="HTML"):
        extract_spec_contract(_spec_markdown(contract))


def test_extract_outline_contract_rejects_html_in_string_field() -> None:
    contract = {
        "contract_version": 1,
        "modules": {
            "feedback-loops": {
                "outcome_ids": ["identify-loop"],
                "estimated_minutes": 30,
                "interaction_types": ["<img src=x onerror=alert(1)>"],
            },
        },
    }
    with pytest.raises(ContractError, match="HTML"):
        extract_outline_contract(_outline_markdown(contract))


def test_fenced_block_with_inline_backticks_in_json_string_is_not_truncated() -> None:
    contract = {
        **VALID_SPEC_CONTRACT,
        "source_policy": "Cite sources; never use ``` fences in learner text.",
    }
    data = extract_spec_contract(_spec_markdown(contract))
    assert data["source_policy"] == "Cite sources; never use ``` fences in learner text."
