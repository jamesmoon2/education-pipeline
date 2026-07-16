"""Strict private audit-response parsing and public-safe projection.

Model-authored narratives remain in :class:`PersonalizationAuditResponse` for
local inspection only.  Public consumers must use the projection helpers in
this module, which emit application-owned fixed messages and fingerprints.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
import hashlib
import json
from typing import Any

from education_pipeline.privacy import normalize_private_value

from .model import Guide
from .personalization import (
    ACTIVE_FACET_IDS,
    PersonalizationTrace,
    parse_personalization_trace,
)
from .projection import public_guide_projection
from .reports import Finding, finding_sort_key


AUDIT_RESPONSE_SCHEMA_VERSION = 1
AUDIT_PROJECTION_SCHEMA_VERSION = 1

AUDIT_VERDICTS = ("served", "weak", "missing")
GENERIC_REASON_CODES = (
    "generic_explanation",
    "generic_example",
    "generic_practice",
    "generic_feedback",
)
PRIVATE_DETAIL_CATEGORIES = (
    "learner_identity",
    "contact_detail",
    "organization",
    "location",
    "health_accessibility",
    "learner_goal",
    "learner_preference",
    "other_private_detail",
)
CONFIDENCE_LEVELS = ("low", "medium", "high")

_ROOT_FIELDS = {
    "schema_version",
    "goals",
    "facets",
    "generic_sections",
    "suspected_private_details",
    "overall_summary",
}
_ASSESSMENT_FIELDS = {"goal_id", "verdict", "evidence", "rationale"}
_FACET_FIELDS = {"facet_id", "verdict", "evidence", "rationale"}
_EVIDENCE_FIELDS = {"kind", "id"}
_GENERIC_FIELDS = {"location", "reason_code", "rationale"}
_PRIVATE_DETAIL_FIELDS = {"location", "category", "confidence", "rationale"}
_LOCATION_FIELDS = {"kind", "id"}
_EVIDENCE_KINDS = frozenset({"module", "outcome"})
_LOCATION_KINDS = frozenset({"course", "module", "outcome", "section", "block"})


class AuditResponseError(ValueError):
    """A safe, non-echoing audit response validation error."""


class _DuplicateJSONMember(ValueError):
    """Internal sentinel; never include attacker-controlled key/value text."""


@dataclass(frozen=True)
class GuideReference:
    kind: str
    id: str


@dataclass(frozen=True)
class GoalAuditAssessment:
    goal_id: str
    verdict: str
    evidence: tuple[GuideReference, ...]
    rationale: str


@dataclass(frozen=True)
class FacetAuditAssessment:
    facet_id: str
    verdict: str
    evidence: tuple[GuideReference, ...]
    rationale: str


@dataclass(frozen=True)
class GenericSectionFlag:
    location: GuideReference
    reason_code: str
    rationale: str


@dataclass(frozen=True)
class SuspectedPrivateDetailFlag:
    location: GuideReference
    category: str
    confidence: str
    rationale: str


@dataclass(frozen=True)
class PersonalizationAuditResponse:
    schema_version: int
    goals: tuple[GoalAuditAssessment, ...]
    facets: tuple[FacetAuditAssessment, ...]
    generic_sections: tuple[GenericSectionFlag, ...]
    suspected_private_details: tuple[SuspectedPrivateDetailFlag, ...]
    overall_summary: str


@dataclass(frozen=True)
class _ResolvedLocation:
    path: str
    value: Any


def parse_audit_response(
    source: bytes | str | Mapping[str, Any],
    *,
    guide: Guide,
    trace: bytes | str | Mapping[str, Any] | PersonalizationTrace,
    private_values: Sequence[str] = (),
) -> PersonalizationAuditResponse:
    """Strictly parse hostile model JSON without echoing rejected content."""

    if isinstance(source, (bytes, str)):
        try:
            value: Any = json.loads(source, object_pairs_hook=_strict_json_object)
        except _DuplicateJSONMember as exc:
            raise AuditResponseError(
                "audit response JSON contains duplicate object members"
            ) from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AuditResponseError("invalid personalization audit response JSON") from exc
    else:
        value = source

    root = _object(value, _ROOT_FIELDS, "audit response")
    schema_version = root.get("schema_version")
    if (
        type(schema_version) is not int
        or schema_version != AUDIT_RESPONSE_SCHEMA_VERSION
    ):
        raise AuditResponseError("unsupported audit response schema_version")

    normalized_trace = parse_personalization_trace(trace)
    locations = _guide_locations(guide)
    private_denylist = _normalize_private_denylist(private_values)

    goals = _parse_assessments(
        root.get("goals"),
        id_field="goal_id",
        expected_ids=tuple(goal.goal_id for goal in normalized_trace.goals),
        label="goal assessment",
        locations=locations,
        private_denylist=private_denylist,
    )
    facets = _parse_assessments(
        root.get("facets"),
        id_field="facet_id",
        expected_ids=tuple(
            facet_id
            for facet_id in ACTIVE_FACET_IDS
            if facet_id in normalized_trace.active_facets
        ),
        label="facet assessment",
        locations=locations,
        private_denylist=private_denylist,
    )

    generic_sections: list[GenericSectionFlag] = []
    seen_generic: set[tuple[str, str, str]] = set()
    for raw_flag in _array(root.get("generic_sections"), "generic_sections"):
        flag = _object(raw_flag, _GENERIC_FIELDS, "generic section flag")
        location = _parse_reference(
            flag.get("location"),
            allowed_kinds=_LOCATION_KINDS,
            locations=locations,
            label="guide location",
        )
        reason_code = _enum(
            flag.get("reason_code"),
            GENERIC_REASON_CODES,
            "generic section reason_code",
        )
        rationale = _narrative(
            flag.get("rationale"), private_denylist=private_denylist
        )
        identity = (location.kind, location.id, reason_code)
        if identity in seen_generic:
            raise AuditResponseError("generic_sections contains a duplicate flag")
        seen_generic.add(identity)
        generic_sections.append(GenericSectionFlag(location, reason_code, rationale))

    private_details: list[SuspectedPrivateDetailFlag] = []
    seen_private: set[tuple[str, str, str, str]] = set()
    for raw_flag in _array(
        root.get("suspected_private_details"), "suspected_private_details"
    ):
        flag = _object(
            raw_flag,
            _PRIVATE_DETAIL_FIELDS,
            "suspected private detail flag",
        )
        location = _parse_reference(
            flag.get("location"),
            allowed_kinds=_LOCATION_KINDS,
            locations=locations,
            label="guide location",
        )
        category = _enum(
            flag.get("category"),
            PRIVATE_DETAIL_CATEGORIES,
            "suspected private detail category",
        )
        confidence = _enum(
            flag.get("confidence"),
            CONFIDENCE_LEVELS,
            "suspected private detail confidence",
        )
        rationale = _narrative(
            flag.get("rationale"), private_denylist=private_denylist
        )
        identity = (location.kind, location.id, category, confidence)
        if identity in seen_private:
            raise AuditResponseError(
                "suspected_private_details contains a duplicate flag"
            )
        seen_private.add(identity)
        private_details.append(
            SuspectedPrivateDetailFlag(
                location=location,
                category=category,
                confidence=confidence,
                rationale=rationale,
            )
        )

    overall_summary = _narrative(
        root.get("overall_summary"), private_denylist=private_denylist
    )
    return PersonalizationAuditResponse(
        schema_version=schema_version,
        goals=tuple(goals),
        facets=tuple(facets),
        generic_sections=tuple(
            sorted(
                generic_sections,
                key=lambda item: (
                    locations[item.location].path,
                    item.reason_code,
                ),
            )
        ),
        suspected_private_details=tuple(
            sorted(
                private_details,
                key=lambda item: (
                    locations[item.location].path,
                    item.category,
                    item.confidence,
                ),
            )
        ),
        overall_summary=overall_summary,
    )


def guide_location_fingerprint(guide: Guide, *, kind: str, id: str) -> str:
    """Return an application-owned fingerprint of one resolved guide location."""

    reference = GuideReference(kind, id)
    locations = _guide_locations(public_guide_projection(guide))
    if reference not in locations:
        raise AuditResponseError("guide location does not reference an existing element")
    return _resolved_location_fingerprint(reference, locations[reference])


def safe_audit_findings(
    audit: PersonalizationAuditResponse,
    *,
    guide: Guide,
) -> tuple[Finding, ...]:
    """Project local audit judgments into fixed-message, non-gating findings."""

    locations = _guide_locations(guide)
    fingerprint_locations = _guide_locations(public_guide_projection(guide))
    findings: list[Finding] = []
    for assessment in audit.goals:
        if assessment.verdict == "served":
            continue
        is_missing = assessment.verdict == "missing"
        rule_id = "audit.goal_missing" if is_missing else "audit.goal_weak"
        findings.append(
            _audit_finding(
                identifier=f"{rule_id}:{assessment.goal_id}",
                rule_id=rule_id,
                severity="warning",
                path=_assessment_path(assessment.evidence, locations),
                message=(
                    "Personalization audit found no support for a learner goal."
                    if is_missing
                    else "Personalization audit found weak support for a learner goal."
                ),
                related_ids=(assessment.goal_id,),
            )
        )
    for assessment in audit.facets:
        if assessment.verdict == "served":
            continue
        is_missing = assessment.verdict == "missing"
        rule_id = "audit.facet_missing" if is_missing else "audit.facet_weak"
        findings.append(
            _audit_finding(
                identifier=f"{rule_id}:{assessment.facet_id}",
                rule_id=rule_id,
                severity="warning" if is_missing else "info",
                path=_assessment_path(assessment.evidence, locations),
                message=(
                    "Personalization audit found no support for an active learner facet."
                    if is_missing
                    else "Personalization audit found weak support for an active learner facet."
                ),
                related_ids=(assessment.facet_id,),
            )
        )
    for flag in audit.generic_sections:
        findings.append(
            _audit_finding(
                identifier=(
                    f"audit.generic_section:{flag.reason_code}:"
                    f"{flag.location.kind}:{flag.location.id}"
                ),
                rule_id="audit.generic_section",
                severity="info",
                path=_resolved_path(flag.location, locations),
                message="Personalization audit identified a potentially generic guide section.",
                related_ids=(flag.location.id,),
            )
        )
    for flag in audit.suspected_private_details:
        location_fingerprint = _resolved_location_fingerprint(
            flag.location,
            _resolved_location(flag.location, fingerprint_locations),
        )
        findings.append(
            _audit_finding(
                identifier=(
                    "audit.suspected_private_detail:"
                    f"{flag.category}:{flag.confidence}:{location_fingerprint}"
                ),
                rule_id="audit.suspected_private_detail",
                severity="warning",
                path=_resolved_path(flag.location, locations),
                message="Personalization audit identified a possible private detail.",
                related_ids=(flag.location.id,),
            )
        )
    return tuple(sorted(findings, key=finding_sort_key))


def safe_audit_projection(
    audit: PersonalizationAuditResponse,
    *,
    guide: Guide,
) -> dict[str, Any]:
    """Return the complete public-safe audit projection."""

    return {
        "schema_version": AUDIT_PROJECTION_SCHEMA_VERSION,
        "findings": [
            finding.to_dict() for finding in safe_audit_findings(audit, guide=guide)
        ],
    }


def canonical_safe_audit_projection_bytes(
    audit: PersonalizationAuditResponse,
    *,
    guide: Guide,
) -> bytes:
    """Serialize the public-safe projection as canonical UTF-8 JSON."""

    text = json.dumps(
        safe_audit_projection(audit, guide=guide),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        separators=(",", ": "),
    )
    return (text + "\n").encode("utf-8")


def safe_audit_projection_sha256(
    audit: PersonalizationAuditResponse,
    *,
    guide: Guide,
) -> str:
    """Hash only canonical safe projection bytes."""

    return hashlib.sha256(
        canonical_safe_audit_projection_bytes(audit, guide=guide)
    ).hexdigest()


def _parse_assessments(
    value: Any,
    *,
    id_field: str,
    expected_ids: tuple[str, ...],
    label: str,
    locations: Mapping[GuideReference, _ResolvedLocation],
    private_denylist: tuple[str, ...],
) -> tuple[GoalAuditAssessment, ...] | tuple[FacetAuditAssessment, ...]:
    raw_items = _array(value, f"{id_field} assessments")
    fields = _ASSESSMENT_FIELDS if id_field == "goal_id" else _FACET_FIELDS
    parsed: dict[str, GoalAuditAssessment | FacetAuditAssessment] = {}
    expected = frozenset(expected_ids)
    for raw_item in raw_items:
        item = _object(raw_item, fields, label)
        identifier = item.get(id_field)
        if not isinstance(identifier, str) or identifier not in expected:
            raise AuditResponseError(f"{label} contains an invalid {id_field}")
        if identifier in parsed:
            raise AuditResponseError(f"{label} contains a duplicate {id_field}")
        verdict = _enum(item.get("verdict"), AUDIT_VERDICTS, f"{label} verdict")
        evidence = _parse_evidence(item.get("evidence"), locations=locations)
        if verdict == "missing" and evidence:
            raise AuditResponseError("missing audit verdict must not include evidence")
        if verdict != "missing" and not evidence:
            raise AuditResponseError("served or weak audit verdict requires evidence")
        rationale = _narrative(
            item.get("rationale"), private_denylist=private_denylist
        )
        if id_field == "goal_id":
            parsed[identifier] = GoalAuditAssessment(
                identifier, verdict, evidence, rationale
            )
        else:
            parsed[identifier] = FacetAuditAssessment(
                identifier, verdict, evidence, rationale
            )
    if set(parsed) != expected:
        raise AuditResponseError(f"{label} ids do not match the expected set")
    return tuple(parsed[identifier] for identifier in expected_ids)


def _parse_evidence(
    value: Any,
    *,
    locations: Mapping[GuideReference, _ResolvedLocation],
) -> tuple[GuideReference, ...]:
    parsed: list[GuideReference] = []
    seen: set[GuideReference] = set()
    for raw_reference in _array(value, "evidence"):
        reference = _parse_reference(
            raw_reference,
            allowed_kinds=_EVIDENCE_KINDS,
            locations=locations,
            label="evidence reference",
        )
        if reference in seen:
            raise AuditResponseError("evidence contains a duplicate reference")
        seen.add(reference)
        parsed.append(reference)
    return tuple(sorted(parsed, key=lambda item: locations[item].path))


def _parse_reference(
    value: Any,
    *,
    allowed_kinds: frozenset[str],
    locations: Mapping[GuideReference, _ResolvedLocation],
    label: str,
) -> GuideReference:
    reference = _object(value, _LOCATION_FIELDS, label)
    kind = reference.get("kind")
    identifier = reference.get("id")
    if not isinstance(kind, str) or kind not in allowed_kinds:
        raise AuditResponseError(f"{label} contains an invalid kind")
    if not isinstance(identifier, str):
        raise AuditResponseError(f"{label} contains an invalid id")
    parsed = GuideReference(kind, identifier)
    if parsed not in locations:
        raise AuditResponseError(f"{label} does not reference an existing element")
    return parsed


def _guide_locations(guide: Guide) -> dict[GuideReference, _ResolvedLocation]:
    locations: dict[GuideReference, _ResolvedLocation] = {
        GuideReference("course", guide.course.id): _ResolvedLocation(
            "/course", guide.course
        )
    }
    for index, outcome in enumerate(guide.outcomes):
        locations[GuideReference("outcome", outcome.id)] = _ResolvedLocation(
            f"/outcomes/{index}", outcome
        )
    for module_index, module in enumerate(guide.modules):
        locations[GuideReference("module", module.id)] = _ResolvedLocation(
            f"/modules/{module_index}", module
        )
        for section_index, section in enumerate(module.sections):
            locations[GuideReference("section", section.id)] = _ResolvedLocation(
                f"/modules/{module_index}/sections/{section_index}", section
            )
            for block_index, block in enumerate(section.blocks):
                locations[GuideReference("block", block.id)] = _ResolvedLocation(
                    f"/modules/{module_index}/sections/{section_index}/blocks/{block_index}",
                    block,
                )
    return locations


def _resolved_location_fingerprint(
    reference: GuideReference,
    resolved: _ResolvedLocation,
) -> str:
    payload = {
        "id": reference.id,
        "kind": reference.kind,
        "path": resolved.path,
        "value": asdict(resolved.value),
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()[:12]


def _assessment_path(
    evidence: tuple[GuideReference, ...],
    locations: Mapping[GuideReference, _ResolvedLocation],
) -> str:
    return _resolved_path(evidence[0], locations) if evidence else "/course"


def _resolved_location(
    reference: GuideReference,
    locations: Mapping[GuideReference, _ResolvedLocation],
) -> _ResolvedLocation:
    resolved = locations.get(reference)
    if resolved is None:
        raise AuditResponseError("audit reference is not present in the guide")
    return resolved


def _resolved_path(
    reference: GuideReference,
    locations: Mapping[GuideReference, _ResolvedLocation],
) -> str:
    return _resolved_location(reference, locations).path


def _audit_finding(
    *,
    identifier: str,
    rule_id: str,
    severity: str,
    path: str,
    message: str,
    related_ids: tuple[str, ...],
) -> Finding:
    return Finding(
        id=identifier,
        rule_id=rule_id,
        severity=severity,
        blocking=False,
        waivable=False,
        path=path,
        message=message,
        remediation="Review the cited guide evidence and revise the guide if appropriate.",
        related_ids=related_ids,
        stage="audit",
        source_stage="repair",
    )


def _normalize_private_denylist(values: Sequence[str]) -> tuple[str, ...]:
    normalized: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            raise AuditResponseError("private_values must contain only strings")
        try:
            candidate = normalize_private_value(value)
        except ValueError as exc:
            raise AuditResponseError("private_values contains invalid text") from exc
        if candidate:
            normalized.add(candidate)
    return tuple(sorted(normalized))


def _narrative(value: Any, *, private_denylist: tuple[str, ...]) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise AuditResponseError("audit narrative must be a trimmed non-empty string")
    try:
        normalized = normalize_private_value(value)
    except ValueError as exc:
        raise AuditResponseError("audit narrative contains invalid text") from exc
    if any(private in normalized for private in private_denylist):
        raise AuditResponseError("audit response contains private profile text")
    return value


def _enum(value: Any, allowed: Sequence[str], label: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise AuditResponseError(f"{label} is invalid")
    return value


def _object(value: Any, fields: set[str], label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(
        not isinstance(key, str) for key in value
    ):
        raise AuditResponseError(f"{label} must be an object")
    if fields - value.keys():
        raise AuditResponseError(f"{label} is missing required fields")
    if value.keys() - fields:
        raise AuditResponseError(f"{label} contains unknown fields")
    return value


def _array(value: Any, label: str) -> Sequence[Any]:
    if not isinstance(value, list):
        raise AuditResponseError(f"{label} must be an array")
    return value


def _strict_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJSONMember
        result[key] = value
    return result
