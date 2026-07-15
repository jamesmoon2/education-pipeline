import json
from pathlib import Path

import pytest

from education_pipeline.guides import quality_report_bytes
from education_pipeline.guides import guide_sha256, normalize_guide, parse_guide
from education_pipeline.guides.projection import public_guide_projection
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
        "public_guide_sha256": "p" * 64,
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
        "guide_sha256": "p" * 64,
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
            public_guide_sha256="p" * 64,
        )
    )
    assert payload["gate"]["open"] is False
    assert payload["waivers"]["guide_sha256"] == "p" * 64


def test_public_sidecar_hash_is_stable_when_only_private_exclusion_reason_changes():
    source = json.loads(
        Path(
            "tests/fixtures/guides/feedback-loops.personalized.guide.json"
        ).read_text(encoding="utf-8")
    )
    changed = json.loads(json.dumps(source))
    changed["course"]["goal_exclusions"][0]["reason"] = (
        "A different synthetic private exclusion reason."
    )
    first_guide = normalize_guide(parse_guide(json.dumps(source)))
    second_guide = normalize_guide(parse_guide(json.dumps(changed)))
    assert guide_sha256(first_guide) != guide_sha256(second_guide)
    public_hash = guide_sha256(public_guide_projection(first_guide))
    assert public_hash == guide_sha256(public_guide_projection(second_guide))
    common = {
        "waiver_set": None,
        "export_sha256": "e" * 64,
        "runtime_css_sha256": "c" * 64,
        "runtime_js_sha256": "d" * 64,
        "runtime_version": "1",
        "public_guide_sha256": public_hash,
    }
    first_report = ValidationReport("1.1", "final", guide_sha256(first_guide), ())
    second_report = ValidationReport("1.1", "final", guide_sha256(second_guide), ())
    first = quality_report_bytes(
        report=first_report,
        waiver_result=apply_waivers(first_report, None),
        **common,
    )
    second = quality_report_bytes(
        report=second_report,
        waiver_result=apply_waivers(second_report, None),
        **common,
    )
    assert first == second
    payload = json.loads(first)
    assert payload["report"]["guide_sha256"] == public_hash
    assert payload["waivers"]["guide_sha256"] == public_hash
