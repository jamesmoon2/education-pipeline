"""Immutable deterministic validation report values and serialization."""

from __future__ import annotations

from dataclasses import dataclass
import json


SEVERITY_RANK = {"blocker": 0, "error": 1, "warning": 2, "info": 3}


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

    def __post_init__(self) -> None:
        if self.severity not in SEVERITY_RANK:
            raise ValueError(f"invalid finding severity: {self.severity}")

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
        }
        if self.related_ids:
            result["related_ids"] = list(self.related_ids)
        return result


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
    report_schema_version: int = 1
    validator_version: str = "1"

    def __post_init__(self) -> None:
        if self.phase not in {"draft", "final"}:
            raise ValueError("phase must be 'draft' or 'final'")
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


def canonical_report_bytes(report: ValidationReport) -> bytes:
    return (json.dumps(report.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
