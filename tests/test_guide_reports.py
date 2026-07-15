from __future__ import annotations

import pytest

from education_pipeline.guides.reports import (
    REPORT_SCHEMA_VERSION,
    Finding,
    ValidationReport,
)


def _legacy_finding_dict() -> dict[str, object]:
    return {
        "id": "content.placeholder:/modules/0",
        "rule_id": "content.placeholder",
        "severity": "warning",
        "blocking": False,
        "waivable": True,
        "path": "/modules/0",
        "message": "Safe message.",
        "remediation": "Replace the placeholder.",
        "related_ids": ["loop-basics"],
        "stage": "draft",
    }


def test_legacy_finding_round_trips_without_new_optional_field() -> None:
    payload = _legacy_finding_dict()
    assert Finding.from_dict(payload).to_dict() == payload


def test_finding_round_trips_when_empty_related_ids_are_omitted() -> None:
    finding = Finding(
        "content.safe:/course",
        "content.safe",
        "info",
        False,
        False,
        "/course",
        "Safe message.",
        "No action required.",
        stage="repair",
    )
    payload = finding.to_dict()
    assert "related_ids" not in payload
    assert Finding.from_dict(payload) == finding


@pytest.mark.parametrize("report_schema_version", [2, REPORT_SCHEMA_VERSION])
def test_report_round_trips_findings_with_omitted_empty_related_ids(
    report_schema_version: int,
) -> None:
    finding = Finding(
        "content.safe:/course",
        "content.safe",
        "info",
        False,
        False,
        "/course",
        "Safe message.",
        "No action required.",
        stage="repair",
    )
    report = ValidationReport(
        "1.1",
        "final",
        "a" * 64,
        (finding,),
        report_schema_version=report_schema_version,
    )
    assert ValidationReport.from_dict(report.to_dict()) == report


def test_audit_finding_requires_repair_source_stage() -> None:
    finding = Finding(
        "audit.goal_missing:goal-001",
        "audit.goal_missing",
        "warning",
        False,
        False,
        "/course",
        "Personalization audit found no support for a learner goal.",
        "Review the cited guide evidence.",
        ("goal-001",),
        stage="audit",
        source_stage="repair",
    )
    assert finding.to_dict()["source_stage"] == "repair"
    assert Finding.from_dict(finding.to_dict()) == finding

    with pytest.raises(ValueError, match="source_stage"):
        Finding.from_dict({**finding.to_dict(), "source_stage": "audit"})
    with pytest.raises(ValueError, match="source_stage"):
        Finding.from_dict({**_legacy_finding_dict(), "source_stage": "repair"})


def test_validation_report_schema_increments_with_v2_reader_path() -> None:
    assert REPORT_SCHEMA_VERSION == 3
    legacy = {
        "report_schema_version": 2,
        "guide_schema_version": "1.1",
        "phase": "final",
        "guide_sha256": "a" * 64,
        "validator_version": "1",
        "summary": {"blocking": 0, "errors": 0, "warnings": 1, "info": 0},
        "findings": [_legacy_finding_dict()],
    }
    parsed = ValidationReport.from_dict(legacy)
    assert parsed.report_schema_version == 2
    assert parsed.to_dict() == legacy


def test_validation_report_reader_rejects_source_stage_in_v2() -> None:
    finding = _legacy_finding_dict()
    finding["source_stage"] = "repair"
    legacy = {
        "report_schema_version": 2,
        "guide_schema_version": "1.1",
        "phase": "final",
        "guide_sha256": "a" * 64,
        "validator_version": "1",
        "summary": {"blocking": 0, "errors": 0, "warnings": 1, "info": 0},
        "findings": [finding],
    }
    with pytest.raises(ValueError, match="source_stage"):
        ValidationReport.from_dict(legacy)


def test_finding_reader_rejects_explicit_null_source_stage() -> None:
    payload = _legacy_finding_dict()
    payload["stage"] = "audit"
    payload["source_stage"] = None
    with pytest.raises(ValueError, match="source_stage"):
        Finding.from_dict(payload)


def _report_dict(
    finding: dict[str, object], *, report_schema_version: int = 3
) -> dict[str, object]:
    severity = finding["severity"]
    return {
        "report_schema_version": report_schema_version,
        "guide_schema_version": "1.1",
        "phase": "final",
        "guide_sha256": "a" * 64,
        "validator_version": "1",
        "summary": {
            "blocking": int(finding["blocking"] is True),
            "errors": int(severity == "error"),
            "warnings": int(severity == "warning"),
            "info": int(severity == "info"),
        },
        "findings": [finding],
    }


def _valid_audit_finding_dict() -> dict[str, object]:
    return {
        "id": "audit.goal_missing:goal-001",
        "rule_id": "audit.goal_missing",
        "severity": "warning",
        "blocking": False,
        "waivable": False,
        "path": "/course",
        "message": "Personalization audit found no support for a learner goal.",
        "remediation": "Review the cited guide evidence.",
        "related_ids": ["goal-001"],
        "stage": "audit",
        "source_stage": "repair",
    }


def test_schema_v2_reader_rejects_audit_stage_even_when_shape_is_otherwise_valid() -> None:
    payload = _report_dict(_valid_audit_finding_dict(), report_schema_version=2)
    with pytest.raises(ValueError, match="audit"):
        ValidationReport.from_dict(payload)


def test_schema_v3_reader_accepts_only_nongating_repair_sourced_audit_finding() -> None:
    payload = _report_dict(_valid_audit_finding_dict())
    parsed = ValidationReport.from_dict(payload)
    assert parsed.to_dict() == payload


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("severity", "blocker"),
        ("severity", "error"),
        ("blocking", True),
        ("waivable", True),
        ("source_stage", None),
        ("source_stage", "draft"),
    ],
)
def test_schema_v3_reader_rejects_malformed_audit_finding_combinations(
    field: str, value: object
) -> None:
    finding = _valid_audit_finding_dict()
    if value is None:
        finding.pop(field)
    else:
        finding[field] = value
    payload = _report_dict(finding)
    with pytest.raises(ValueError):
        ValidationReport.from_dict(payload)


def test_hostile_invalid_stage_and_severity_are_not_echoed() -> None:
    for field in ("stage", "severity"):
        secret = f"ATTACKER_PRIVATE_{field.upper()}"
        finding = _valid_audit_finding_dict()
        finding[field] = secret
        with pytest.raises(ValueError) as caught:
            ValidationReport.from_dict(_report_dict(finding))
        assert secret not in str(caught.value)


def test_finding_reader_requires_related_ids_to_be_a_json_array() -> None:
    finding = _legacy_finding_dict()
    finding["related_ids"] = ("loop-basics",)
    with pytest.raises(ValueError, match="related_ids"):
        Finding.from_dict(finding)


@pytest.mark.parametrize(
    "summary",
    [
        (("blocking", 0), ("errors", 0), ("warnings", 1), ("info", 0)),
        {"blocking": 0, "errors": 0, "warnings": 1},
        {"blocking": 0, "errors": 0, "warnings": 1, "info": 0, "extra": 0},
        {"blocking": False, "errors": 0, "warnings": 1, "info": 0},
        {"blocking": 0, "errors": 0.0, "warnings": 1, "info": 0},
        {"blocking": 0, "errors": 0, "warnings": -1, "info": 0},
    ],
)
def test_report_reader_requires_exact_nonnegative_integer_summary_mapping(
    summary: object,
) -> None:
    payload = _report_dict(_legacy_finding_dict())
    payload["summary"] = summary
    with pytest.raises(ValueError, match="summary"):
        ValidationReport.from_dict(payload)
