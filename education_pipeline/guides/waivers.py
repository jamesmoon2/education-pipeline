"""Hash-bound waiver evaluation kept separate from validation reports."""

from __future__ import annotations

from dataclasses import dataclass

from .reports import ValidationReport


@dataclass(frozen=True)
class Waiver:
    finding_id: str
    reason: str


@dataclass(frozen=True)
class WaiverSet:
    guide_sha256: str
    waivers: tuple[Waiver, ...]
    schema_version: int = 1


@dataclass(frozen=True)
class WaiverResult:
    gate_open: bool
    effective_blocking: int
    waived_finding_ids: tuple[str, ...]
    rejected_finding_ids: tuple[str, ...]
    orphaned_finding_ids: tuple[str, ...]
    stale: bool


def apply_waivers(report: ValidationReport, waiver_set: WaiverSet | None) -> WaiverResult:
    """Calculate the effective gate without altering or hiding report findings."""
    blocking = {item.id: item for item in report.findings if item.blocking}
    if waiver_set is None:
        return WaiverResult(not blocking, len(blocking), (), (), (), False)
    if waiver_set.guide_sha256 != report.guide_sha256:
        return WaiverResult(not blocking, len(blocking), (), (), (), True)

    findings = {item.id: item for item in report.findings}
    waived: set[str] = set()
    rejected: set[str] = set()
    orphaned: set[str] = set()
    for waiver in waiver_set.waivers:
        finding = findings.get(waiver.finding_id)
        if finding is None:
            orphaned.add(waiver.finding_id)
        elif not waiver.reason.strip() or not finding.waivable:
            rejected.add(waiver.finding_id)
        else:
            waived.add(waiver.finding_id)
    remaining = set(blocking) - waived
    return WaiverResult(
        gate_open=not remaining,
        effective_blocking=len(remaining),
        waived_finding_ids=tuple(sorted(waived)),
        rejected_finding_ids=tuple(sorted(rejected)),
        orphaned_finding_ids=tuple(sorted(orphaned)),
        stale=False,
    )
