from pathlib import Path

from education_pipeline.guides import normalize_guide, parse_guide
from education_pipeline.guides.reports import Finding, ValidationReport
from education_pipeline.guides.validation import validate_guide
from education_pipeline.guides.waivers import Waiver, WaiverSet, apply_waivers

FIXTURE = Path(__file__).parent / "fixtures/guides/feedback-loops.guide.json"


def report_with(*findings: Finding) -> ValidationReport:
    return ValidationReport("1.0", "final", "abc", findings)


def finding(identifier="waivable:one", *, waivable=True) -> Finding:
    return Finding(identifier, "test.rule", "error", True, waivable, "/x", "Safe message.", "Fix it.")


def test_valid_waiver_opens_gate_without_removing_finding() -> None:
    report = report_with(finding())
    result = apply_waivers(report, WaiverSet("abc", (Waiver("waivable:one", "Approved exception"),)))
    assert result.gate_open and result.effective_blocking == 0
    assert result.waived_finding_ids == ("waivable:one",)
    assert len(report.findings) == 1


def test_stale_hash_never_opens_gate() -> None:
    result = apply_waivers(report_with(finding()), WaiverSet("old", (Waiver("waivable:one", "reason"),)))
    assert result.stale and not result.gate_open and result.effective_blocking == 1


def test_blank_nonwaivable_and_orphaned_waivers_are_rejected_or_ignored() -> None:
    report = report_with(finding(), finding("fixed:no", waivable=False))
    result = apply_waivers(report, WaiverSet("abc", (
        Waiver("waivable:one", "  "), Waiver("fixed:no", "please"), Waiver("gone:id", "old exception")
    )))
    assert not result.gate_open and result.effective_blocking == 2
    assert result.rejected_finding_ids == ("fixed:no", "waivable:one")
    assert result.orphaned_finding_ids == ("gone:id",)


def test_waiver_requires_exact_finding_id() -> None:
    result = apply_waivers(report_with(finding()), WaiverSet("abc", (Waiver("waivable", "reason"),)))
    assert not result.gate_open
    assert result.orphaned_finding_ids == ("waivable",)


def test_real_fixture_warning_does_not_close_gate() -> None:
    guide = normalize_guide(parse_guide(FIXTURE.read_bytes()))
    report = validate_guide(guide)
    result = apply_waivers(report, None)
    assert result.gate_open and result.effective_blocking == 0
