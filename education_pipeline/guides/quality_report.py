"""Canonical, timestamp-free sidecar quality report emitted at export.

The sidecar records the gate decision, the full validation report, the
effective waiver evaluation, and the export/runtime fingerprints for one
exported guide. It is byte-deterministic: identical inputs always yield
identical bytes (no timestamps anywhere), so re-exporting an unchanged run
produces an identical sidecar.
"""

from __future__ import annotations

from dataclasses import replace
import json

from .reports import ValidationReport
from .waivers import WaiverResult, WaiverSet

QUALITY_REPORT_SCHEMA_VERSION = 1


def quality_report_bytes(
    report: ValidationReport,
    waiver_result: WaiverResult,
    waiver_set: WaiverSet | None,
    *,
    export_sha256: str,
    runtime_css_sha256: str,
    runtime_js_sha256: str,
    runtime_version: str,
    public_guide_sha256: str,
) -> bytes:
    """Serialize the sidecar quality report to canonical UTF-8 bytes.

    The local validation report and waiver set remain bound to canonical source
    bytes. The public sidecar consistently substitutes the public-guide
    projection hash so private source-only annotations cannot influence a
    published hash field.
    """

    public_report = replace(report, guide_sha256=public_guide_sha256)
    payload = {
        "quality_report_schema_version": QUALITY_REPORT_SCHEMA_VERSION,
        "gate": {
            "open": waiver_result.gate_open,
            "effective_blocking": waiver_result.effective_blocking,
        },
        "report": public_report.to_dict(),
        "waivers": {
            "guide_sha256": public_guide_sha256,
            "applied": list(waiver_result.waived_finding_ids),
            "rejected": list(waiver_result.rejected_finding_ids),
            "orphaned": list(waiver_result.orphaned_finding_ids),
            "stale": waiver_result.stale,
        },
        "export": {
            "file_sha256": export_sha256,
            "runtime_version": runtime_version,
            "runtime_css_sha256": runtime_css_sha256,
            "runtime_js_sha256": runtime_js_sha256,
        },
    }
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
