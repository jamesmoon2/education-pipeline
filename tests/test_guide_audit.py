from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path

import pytest

from education_pipeline.guides import normalize_guide, parse_guide
from education_pipeline.guides.audit import (
    AUDIT_PROJECTION_SCHEMA_VERSION,
    AUDIT_RESPONSE_SCHEMA_VERSION,
    AuditResponseError,
    canonical_safe_audit_projection_bytes,
    parse_audit_response,
    safe_audit_findings,
    safe_audit_projection,
    safe_audit_projection_sha256,
)
from education_pipeline.guides.personalization import parse_personalization_trace


FIXTURE = Path("tests/fixtures/guides/feedback-loops.personalized.guide.json")
PLANTED_SECRETS = (
    "Secret Orchard Cohort",
    "Private Goal Narrative",
    "Confidential Facet Narrative",
    "Hidden Generic Narrative",
    "Sensitive Flag Narrative",
    "Overall Tailoring Secret",
    "f" * 64,
)


@pytest.fixture
def guide():
    return normalize_guide(parse_guide(FIXTURE.read_bytes()))


@pytest.fixture
def trace():
    return parse_personalization_trace(
        {
            "schema_version": 1,
            "guide_sha256": "a" * 64,
            "profile_snapshot_sha256": "b" * 64,
            "goals": [
                {
                    "goal_id": "goal-001",
                    "goal_text": "Private Goal One",
                    "serving_module_ids": ["loop-basics"],
                    "serving_outcome_ids": ["identify-loop"],
                    "exclusions": [],
                },
                {
                    "goal_id": "goal-002",
                    "goal_text": "Private Goal Two",
                    "serving_module_ids": ["intervention-practice", "loop-basics"],
                    "serving_outcome_ids": ["map-loop"],
                    "exclusions": [],
                },
                {
                    "goal_id": "goal-003",
                    "goal_text": "Private Goal Three",
                    "serving_module_ids": [],
                    "serving_outcome_ids": [],
                    "exclusions": [
                        {"goal_id": "goal-003", "reason": "Private exclusion"}
                    ],
                },
            ],
            "active_facets": [
                "prior_knowledge",
                "interests_examples",
                "pacing",
                "assessment_preferences",
                "accessibility",
            ],
        }
    )


@pytest.fixture
def valid_response() -> dict[str, object]:
    return {
        "schema_version": AUDIT_RESPONSE_SCHEMA_VERSION,
        "goals": [
            {
                "goal_id": "goal-001",
                "verdict": "served",
                "evidence": [{"kind": "module", "id": "loop-basics"}],
                "rationale": "The first module supplies concrete practice.",
            },
            {
                "goal_id": "goal-002",
                "verdict": "weak",
                "evidence": [{"kind": "outcome", "id": "map-loop"}],
                "rationale": "The outcome appears, but practice is narrow.",
            },
            {
                "goal_id": "goal-003",
                "verdict": "missing",
                "evidence": [],
                "rationale": "No guide element serves this goal.",
            },
        ],
        "facets": [
            {
                "facet_id": "prior_knowledge",
                "verdict": "served",
                "evidence": [{"kind": "module", "id": "loop-basics"}],
                "rationale": "The opening builds from familiar systems.",
            },
            {
                "facet_id": "interests_examples",
                "verdict": "served",
                "evidence": [{"kind": "module", "id": "intervention-practice"}],
                "rationale": "Examples consistently use the selected domain.",
            },
            {
                "facet_id": "pacing",
                "verdict": "weak",
                "evidence": [{"kind": "outcome", "id": "choose-intervention"}],
                "rationale": "The final segment may move too quickly.",
            },
            {
                "facet_id": "assessment_preferences",
                "verdict": "served",
                "evidence": [{"kind": "module", "id": "intervention-practice"}],
                "rationale": "The guide includes scenario practice.",
            },
            {
                "facet_id": "accessibility",
                "verdict": "missing",
                "evidence": [],
                "rationale": "The requested support is absent.",
            },
        ],
        "generic_sections": [
            {
                "location": {"kind": "block", "id": "loop-introduction"},
                "reason_code": "generic_explanation",
                "rationale": "The explanation is not tailored.",
            }
        ],
        "suspected_private_details": [
            {
                "location": {"kind": "block", "id": "garden-connection"},
                "category": "learner_identity",
                "confidence": "high",
                "rationale": "This may reveal learner-specific context.",
            }
        ],
        "overall_summary": "The guide is partly tailored and needs focused revision.",
    }


def _parse(payload, guide, trace, *, private_values=()):
    return parse_audit_response(
        payload,
        guide=guide,
        trace=trace,
        private_values=private_values,
    )


def test_valid_response_projects_only_deterministic_safe_findings(
    guide, trace, valid_response
) -> None:
    audit = _parse(valid_response, guide, trace)
    first = safe_audit_findings(audit, guide=guide)
    second = safe_audit_findings(audit, guide=guide)
    assert first == second
    assert {item.rule_id for item in first} == {
        "audit.goal_weak",
        "audit.goal_missing",
        "audit.facet_weak",
        "audit.facet_missing",
        "audit.generic_section",
        "audit.suspected_private_detail",
    }
    assert all(
        item.stage == "audit"
        and item.source_stage == "repair"
        and item.blocking is False
        and item.waivable is False
        and item.severity in {"warning", "info"}
        for item in first
    )
    assert all(
        item.message.startswith("Personalization audit")
        and "rationale" not in item.message.lower()
        for item in first
    )
    private_finding = next(
        item for item in first if item.rule_id == "audit.suspected_private_detail"
    )
    assert private_finding.path == "/modules/0/sections/0/blocks/1"
    assert private_finding.id.rsplit(":", 1)[-1] == hashlib.sha256(
        json.dumps(
            {
                "id": "garden-connection",
                "kind": "block",
                "path": "/modules/0/sections/0/blocks/1",
                "value": asdict(guide.modules[0].sections[0].blocks[1]),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()[:12]


@pytest.mark.parametrize(
    ("mutation", "diagnostic"),
    [
        (lambda value: value.update(extra="ATTACKER_UNKNOWN_ROOT"), "audit response contains unknown fields"),
        (lambda value: value["goals"][0].update(extra="ATTACKER_UNKNOWN_GOAL"), "goal assessment contains unknown fields"),
        (lambda value: value["facets"][0].update(extra="ATTACKER_UNKNOWN_FACET"), "facet assessment contains unknown fields"),
        (lambda value: value["generic_sections"][0].update(extra="ATTACKER_UNKNOWN_GENERIC"), "generic section flag contains unknown fields"),
        (lambda value: value["suspected_private_details"][0].update(value="ATTACKER_VALUE"), "suspected private detail flag contains unknown fields"),
        (lambda value: value["suspected_private_details"][0].update(fingerprint="ATTACKER_FINGERPRINT"), "suspected private detail flag contains unknown fields"),
        (lambda value: value["goals"][0]["evidence"][0].update(extra="ATTACKER_UNKNOWN_EVIDENCE"), "evidence reference contains unknown fields"),
        (lambda value: value["generic_sections"][0]["location"].update(extra="ATTACKER_UNKNOWN_LOCATION"), "guide location contains unknown fields"),
    ],
)
def test_unknown_or_model_owned_fields_are_rejected_without_echo(
    guide, trace, valid_response, mutation, diagnostic
) -> None:
    mutation(valid_response)
    with pytest.raises(AuditResponseError) as caught:
        _parse(valid_response, guide, trace)
    assert str(caught.value) == diagnostic
    assert "ATTACKER" not in str(caught.value)


@pytest.mark.parametrize(
    "payload",
    [
        b"{not-json SECRET_BAD_JSON",
        [],
        {"schema_version": True},
    ],
)
def test_malformed_json_and_root_types_have_non_echoing_diagnostics(
    guide, trace, payload
) -> None:
    with pytest.raises(AuditResponseError) as caught:
        _parse(payload, guide, trace)
    assert "SECRET_BAD_JSON" not in str(caught.value)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update(schema_version=True),
        lambda value: value.update(goals={}),
        lambda value: value.update(facets="not-an-array"),
        lambda value: value.update(generic_sections=None),
        lambda value: value.update(suspected_private_details={}),
        lambda value: value.update(overall_summary=4),
        lambda value: value["goals"][0].update(verdict="excellent"),
        lambda value: value["goals"][0].update(evidence="loop-basics"),
        lambda value: value["goals"][0].update(rationale=False),
        lambda value: value["facets"][0].update(verdict=1),
        lambda value: value["generic_sections"][0].update(reason_code="novel_reason"),
        lambda value: value["suspected_private_details"][0].update(category=[]),
        lambda value: value["suspected_private_details"][0].update(confidence="certain"),
    ],
)
def test_every_response_field_is_strictly_typed(
    guide, trace, valid_response, mutation
) -> None:
    mutation(valid_response)
    with pytest.raises(AuditResponseError):
        _parse(valid_response, guide, trace)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value["goals"][0].update(goal_id="goal-999"),
        lambda value: value["goals"].append(deepcopy(value["goals"][0])),
        lambda value: value["goals"].pop(),
        lambda value: value["facets"][0].update(facet_id="secret-facet"),
        lambda value: value["facets"].append(deepcopy(value["facets"][0])),
        lambda value: value["facets"].pop(),
        lambda value: value["goals"][0]["evidence"][0].update(id="missing-module"),
        lambda value: value["goals"][0]["evidence"][0].update(kind="block"),
        lambda value: value["generic_sections"][0]["location"].update(id="missing-block"),
        lambda value: value["suspected_private_details"][0]["location"].update(kind="source"),
    ],
)
def test_invalid_goal_facet_evidence_and_location_ids_are_rejected(
    guide, trace, valid_response, mutation
) -> None:
    mutation(valid_response)
    with pytest.raises(AuditResponseError):
        _parse(valid_response, guide, trace)


def test_evidence_presence_matches_verdict_and_references_are_unique(
    guide, trace, valid_response
) -> None:
    weak = deepcopy(valid_response)
    weak["goals"][1]["evidence"] = []
    with pytest.raises(AuditResponseError, match="evidence"):
        _parse(weak, guide, trace)

    missing = deepcopy(valid_response)
    missing["goals"][2]["evidence"] = [
        {"kind": "module", "id": "loop-basics"}
    ]
    with pytest.raises(AuditResponseError, match="evidence"):
        _parse(missing, guide, trace)

    duplicate = deepcopy(valid_response)
    duplicate["facets"][0]["evidence"].append(
        deepcopy(duplicate["facets"][0]["evidence"][0])
    )
    with pytest.raises(AuditResponseError, match="duplicate"):
        _parse(duplicate, guide, trace)


@pytest.mark.parametrize(
    ("slot", "secret"),
    [
        (("goals", 0, "rationale"), PLANTED_SECRETS[1]),
        (("facets", 0, "rationale"), PLANTED_SECRETS[2]),
        (("generic_sections", 0, "rationale"), PLANTED_SECRETS[3]),
        (("suspected_private_details", 0, "rationale"), PLANTED_SECRETS[4]),
        (("overall_summary",), PLANTED_SECRETS[5]),
    ],
)
def test_private_string_in_every_narrative_slot_is_rejected_without_echo(
    guide, trace, valid_response, slot, secret
) -> None:
    target = valid_response
    for key in slot[:-1]:
        target = target[key]
    target[slot[-1]] = f"Harmless prefix {secret} harmless suffix"
    with pytest.raises(AuditResponseError) as caught:
        _parse(valid_response, guide, trace, private_values=PLANTED_SECRETS)
    assert str(caught.value) == "audit response contains private profile text"
    assert secret not in str(caught.value)


def test_projection_excludes_all_narratives_and_private_artifact_hashes(
    guide, trace, valid_response
) -> None:
    narratives = [
        item["rationale"] for item in valid_response["goals"]
    ] + [
        item["rationale"] for item in valid_response["facets"]
    ] + [
        item["rationale"] for item in valid_response["generic_sections"]
    ] + [
        item["rationale"] for item in valid_response["suspected_private_details"]
    ] + [valid_response["overall_summary"]]
    audit = _parse(valid_response, guide, trace)
    projection = safe_audit_projection(audit, guide=guide)
    serialized = canonical_safe_audit_projection_bytes(audit, guide=guide)
    assert projection["schema_version"] == AUDIT_PROJECTION_SCHEMA_VERSION
    assert set(projection) == {"schema_version", "findings"}
    assert serialized == canonical_safe_audit_projection_bytes(audit, guide=guide)
    assert safe_audit_projection_sha256(audit, guide=guide) == hashlib.sha256(
        serialized
    ).hexdigest()
    assert b"a" * 64 not in serialized
    assert b"b" * 64 not in serialized
    for secret in (*PLANTED_SECRETS, *narratives, "Private Goal One", "Private exclusion"):
        assert secret.encode("utf-8") not in serialized


def test_duplicate_flags_that_would_collide_are_rejected(
    guide, trace, valid_response
) -> None:
    valid_response["generic_sections"].append(
        deepcopy(valid_response["generic_sections"][0])
    )
    with pytest.raises(AuditResponseError, match="duplicate"):
        _parse(valid_response, guide, trace)


def test_location_fingerprint_ignores_private_source_annotations(
    guide, trace, valid_response
) -> None:
    valid_response["suspected_private_details"][0]["location"] = {
        "kind": "course",
        "id": "feedback-loops",
    }
    changed = replace(
        guide,
        course=replace(
            guide.course,
            goal_exclusions=(
                replace(
                    guide.course.goal_exclusions[0],
                    reason="A different private exclusion reason.",
                ),
            ),
        ),
    )
    first = _parse(valid_response, guide, trace)
    second = _parse(valid_response, changed, trace)
    assert canonical_safe_audit_projection_bytes(
        first, guide=guide
    ) == canonical_safe_audit_projection_bytes(second, guide=changed)


def test_non_json_tuple_is_not_accepted_as_an_array(guide, trace, valid_response) -> None:
    valid_response["goals"] = tuple(valid_response["goals"])
    with pytest.raises(AuditResponseError, match="array"):
        _parse(valid_response, guide, trace)


@pytest.mark.parametrize("as_bytes", [False, True])
def test_raw_json_rejects_duplicate_members_before_secret_value_is_discarded(
    guide, trace, valid_response, as_bytes
) -> None:
    secret = "DUPLICATE RATIONALE SECRET"
    raw = json.dumps(valid_response, ensure_ascii=False)
    original = json.dumps(
        valid_response["goals"][0]["rationale"], ensure_ascii=False
    )
    replacement = f'"rationale": {json.dumps(secret)}, "rationale": {original}'
    raw = raw.replace(f'"rationale": {original}', replacement, 1)
    source = raw.encode("utf-8") if as_bytes else raw
    with pytest.raises(AuditResponseError) as caught:
        _parse(source, guide, trace, private_values=(secret,))
    assert str(caught.value) == "audit response JSON contains duplicate object members"
    assert secret not in str(caught.value)
