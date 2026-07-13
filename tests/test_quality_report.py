import json

import pytest

from education_pipeline.guides import quality_report_bytes
from education_pipeline.guides.reports import Finding, ValidationReport
from education_pipeline.guides.waivers import Waiver, WaiverSet, apply_waivers


@pytest.fixture
def sample_report_and_waivers():
    finding = Finding(
        "waivable:one",
        "test.rule",
        "error",
        True,
        True,
        "/x",
        "Safe message.",
        "Fix it.",
        stage="repair",
    )
    report = ValidationReport("1.0", "final", "abc123", (finding,))
    waiver_set = WaiverSet("abc123", (Waiver("waivable:one", "Approved exception"),))
    waiver_result = apply_waivers(report, waiver_set)
    return {
        "report": report,
        "waiver_result": waiver_result,
        "waiver_set": waiver_set,
        "export_sha256": "e" * 64,
        "runtime_css_sha256": "c" * 64,
        "runtime_js_sha256": "d" * 64,
        "runtime_version": "1",
    }


def test_quality_report_bytes_are_canonical_and_timestamp_free(sample_report_and_waivers):
    a = quality_report_bytes(**sample_report_and_waivers)
    b = quality_report_bytes(**sample_report_and_waivers)
    assert a == b
    payload = json.loads(a)
    assert payload["quality_report_schema_version"] == 1
    assert "gate" in payload and "report" in payload and "export" in payload
    flat = a.decode("utf-8")
    assert "recorded_at" not in flat and "timestamp" not in flat


def test_quality_report_payload_carries_gate_waivers_and_export(sample_report_and_waivers):
    payload = json.loads(quality_report_bytes(**sample_report_and_waivers))
    assert payload["gate"] == {"open": True, "effective_blocking": 0}
    # The full validation report (schema v2, findings carry stage) is embedded.
    assert payload["report"]["report_schema_version"] == 2
    assert payload["report"]["findings"][0]["stage"] == "repair"
    assert payload["waivers"] == {
        "guide_sha256": "abc123",
        "applied": ["waivable:one"],
        "rejected": [],
        "orphaned": [],
        "stale": False,
    }
    assert payload["export"] == {
        "file_sha256": "e" * 64,
        "runtime_version": "1",
        "runtime_css_sha256": "c" * 64,
        "runtime_js_sha256": "d" * 64,
    }


def test_quality_report_without_waiver_set_uses_report_guide_hash():
    finding = Finding(
        "waivable:one",
        "test.rule",
        "error",
        True,
        True,
        "/x",
        "Safe message.",
        "Fix it.",
        stage="repair",
    )
    report = ValidationReport("1.0", "final", "reporthash", (finding,))
    waiver_result = apply_waivers(report, None)
    payload = json.loads(
        quality_report_bytes(
            report,
            waiver_result,
            None,
            export_sha256="e" * 64,
            runtime_css_sha256="c" * 64,
            runtime_js_sha256="d" * 64,
            runtime_version="1",
        )
    )
    assert payload["gate"]["open"] is False
    assert payload["waivers"]["guide_sha256"] == "reporthash"
