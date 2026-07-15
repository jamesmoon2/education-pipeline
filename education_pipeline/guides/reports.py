"""Immutable deterministic validation report values and serialization."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Mapping


SEVERITY_RANK = {"blocker": 0, "error": 1, "warning": 2, "info": 3}
STAGES = {"spec", "outline", "draft", "qa", "repair", "audit"}
REPORT_SCHEMA_VERSION = 3
_READABLE_REPORT_SCHEMA_VERSIONS = {2, REPORT_SCHEMA_VERSION}
_FINDING_REQUIRED_FIELDS = {
    "id",
    "rule_id",
    "severity",
    "blocking",
    "waivable",
    "path",
    "message",
    "remediation",
    "stage",
}
_FINDING_OPTIONAL_FIELDS = {"related_ids", "source_stage"}
_SUMMARY_FIELDS = {"blocking", "errors", "warnings", "info"}


@dataclass(frozen=True)
class Finding:
    id: str
    rule_id: str
    severity: str
    blocking: bool
    waivable: bool
    path: str
    message: str
    remediation: str
    related_ids: tuple[str, ...] = ()
    stage: str = "draft"
    source_stage: str | None = None

    def __post_init__(self) -> None:
        if self.severity not in SEVERITY_RANK:
            raise ValueError("invalid finding severity")
        if self.stage not in STAGES:
            raise ValueError("invalid finding stage")
        if self.stage == "audit":
            if self.severity not in {"warning", "info"}:
                raise ValueError("audit finding severity must be warning or info")
            if self.blocking or self.waivable:
                raise ValueError("audit findings must be nonblocking and nonwaivable")
            if self.source_stage != "repair":
                raise ValueError("audit finding source_stage must be repair")
        elif self.source_stage is not None:
            raise ValueError("source_stage is permitted only for audit findings")

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "id": self.id,
            "rule_id": self.rule_id,
            "severity": self.severity,
            "blocking": self.blocking,
            "waivable": self.waivable,
            "path": self.path,
            "message": self.message,
            "remediation": self.remediation,
            "stage": self.stage,
        }
        if self.related_ids:
            result["related_ids"] = list(self.related_ids)
        if self.source_stage is not None:
            result["source_stage"] = self.source_stage
        return result

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
        *,
        allow_source_stage: bool = True,
    ) -> "Finding":
        """Strictly read a finding while preserving legacy serialized shape."""

        if not isinstance(value, Mapping) or any(
            not isinstance(key, str) for key in value
        ):
            raise ValueError("finding must be an object with string keys")
        fields = set(value)
        if not _FINDING_REQUIRED_FIELDS <= fields:
            raise ValueError("finding is missing required fields")
        if fields - _FINDING_REQUIRED_FIELDS - _FINDING_OPTIONAL_FIELDS:
            raise ValueError("finding contains unknown fields")
        if not allow_source_stage and "source_stage" in value:
            raise ValueError("finding source_stage is unsupported by this report schema")

        text_fields = (
            "id",
            "rule_id",
            "severity",
            "path",
            "message",
            "remediation",
            "stage",
        )
        if any(not isinstance(value.get(field), str) for field in text_fields):
            raise ValueError("finding contains an invalid text field")
        if type(value.get("blocking")) is not bool or type(
            value.get("waivable")
        ) is not bool:
            raise ValueError("finding blocking and waivable must be booleans")

        raw_related = value.get("related_ids", ())
        if not isinstance(raw_related, list) or any(
            not isinstance(item, str) for item in raw_related
        ):
            raise ValueError("finding related_ids must be an array of strings")
        source_stage = value.get("source_stage")
        if "source_stage" in value and not isinstance(source_stage, str):
            raise ValueError("finding source_stage must be a string")

        return cls(
            id=value["id"],
            rule_id=value["rule_id"],
            severity=value["severity"],
            blocking=value["blocking"],
            waivable=value["waivable"],
            path=value["path"],
            message=value["message"],
            remediation=value["remediation"],
            related_ids=tuple(raw_related),
            stage=value["stage"],
            source_stage=source_stage,
        )


def finding_sort_key(finding: Finding) -> tuple[int, str, str, str]:
    return (SEVERITY_RANK[finding.severity], finding.rule_id, finding.path, finding.id)


@dataclass(frozen=True)
class ValidationSummary:
    blocking: int
    errors: int
    warnings: int
    info: int

    @classmethod
    def from_findings(cls, findings: tuple[Finding, ...]) -> "ValidationSummary":
        return cls(
            blocking=sum(item.blocking for item in findings),
            errors=sum(item.severity == "error" for item in findings),
            warnings=sum(item.severity == "warning" for item in findings),
            info=sum(item.severity == "info" for item in findings),
        )

    def to_dict(self) -> dict[str, int]:
        return {
            "blocking": self.blocking,
            "errors": self.errors,
            "warnings": self.warnings,
            "info": self.info,
        }


@dataclass(frozen=True)
class ValidationReport:
    guide_schema_version: str
    phase: str
    guide_sha256: str
    findings: tuple[Finding, ...]
    report_schema_version: int = REPORT_SCHEMA_VERSION
    validator_version: str = "1"

    def __post_init__(self) -> None:
        if self.phase not in {"draft", "final"}:
            raise ValueError("phase must be 'draft' or 'final'")
        if self.report_schema_version < REPORT_SCHEMA_VERSION and any(
            finding.stage == "audit" for finding in self.findings
        ):
            raise ValueError("legacy validation report schema does not support audit findings")
        ordered = tuple(sorted(self.findings, key=finding_sort_key))
        if ordered != self.findings:
            object.__setattr__(self, "findings", ordered)

    @property
    def summary(self) -> ValidationSummary:
        return ValidationSummary.from_findings(self.findings)

    def to_dict(self) -> dict[str, object]:
        return {
            "report_schema_version": self.report_schema_version,
            "guide_schema_version": self.guide_schema_version,
            "phase": self.phase,
            "guide_sha256": self.guide_sha256,
            "validator_version": self.validator_version,
            "summary": self.summary.to_dict(),
            "findings": [finding.to_dict() for finding in self.findings],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ValidationReport":
        """Read the current report schema or the immediately preceding v2."""

        fields = {
            "report_schema_version",
            "guide_schema_version",
            "phase",
            "guide_sha256",
            "validator_version",
            "summary",
            "findings",
        }
        if not isinstance(value, Mapping) or any(
            not isinstance(key, str) for key in value
        ):
            raise ValueError("validation report must be an object with string keys")
        if set(value) != fields:
            raise ValueError("validation report fields do not match the schema")
        schema_version = value.get("report_schema_version")
        if (
            type(schema_version) is not int
            or schema_version not in _READABLE_REPORT_SCHEMA_VERSIONS
        ):
            raise ValueError("unsupported validation report schema version")
        if any(
            not isinstance(value.get(field), str)
            for field in (
                "guide_schema_version",
                "phase",
                "guide_sha256",
                "validator_version",
            )
        ):
            raise ValueError("validation report contains an invalid text field")
        raw_findings = value.get("findings")
        if not isinstance(raw_findings, list):
            raise ValueError("validation report findings must be an array")
        raw_summary = value.get("summary")
        if not isinstance(raw_summary, Mapping) or any(
            not isinstance(key, str) for key in raw_summary
        ):
            raise ValueError("validation report summary must be an object")
        if set(raw_summary) != _SUMMARY_FIELDS:
            raise ValueError("validation report summary fields do not match the schema")
        if any(type(item) is not int or item < 0 for item in raw_summary.values()):
            raise ValueError(
                "validation report summary values must be nonnegative integers"
            )
        if schema_version < REPORT_SCHEMA_VERSION and any(
            isinstance(finding, Mapping) and finding.get("stage") == "audit"
            for finding in raw_findings
        ):
            raise ValueError("legacy validation report schema does not support audit findings")
        findings = tuple(
            Finding.from_dict(
                finding,
                allow_source_stage=schema_version >= REPORT_SCHEMA_VERSION,
            )
            for finding in raw_findings
        )
        report = cls(
            guide_schema_version=value["guide_schema_version"],
            phase=value["phase"],
            guide_sha256=value["guide_sha256"],
            findings=findings,
            report_schema_version=schema_version,
            validator_version=value["validator_version"],
        )
        if raw_summary != report.summary.to_dict():
            raise ValueError("validation report summary does not match findings")
        return report


def canonical_report_bytes(report: ValidationReport) -> bytes:
    return (json.dumps(report.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
