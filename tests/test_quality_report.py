import json
from pathlib import Path

import pytest

from education_pipeline.guides import QUALITY_REPORT_SCHEMA_VERSION, quality_report_bytes
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
        "audit_state": "not_run",
        "safe_audit_projection_sha256": None,
        "safe_trace_projection_sha256": "t" * 64,
        "safe_audit_findings": (),
        "export_input_sha256": "i" * 64,
    }


def test_quality_report_bytes_are_canonical_and_timestamp_free(sample_report_and_waivers):
    a = quality_report_bytes(**sample_report_and_waivers)
    b = quality_report_bytes(**sample_report_and_waivers)
    assert a == b
    payload = json.loads(a)
    assert QUALITY_REPORT_SCHEMA_VERSION == 2
    assert payload["quality_report_schema_version"] == 2
    assert "gate" in payload and "report" in payload and "export" in payload
    flat = a.decode("utf-8")
    assert "recorded_at" not in flat and "timestamp" not in flat


def test_quality_report_payload_carries_gate_waivers_and_export(sample_report_and_waivers):
    payload = json.loads(quality_report_bytes(**sample_report_and_waivers))
    assert payload["gate"] == {"open": True, "effective_blocking": 0}
    # The full validation report (schema v3, audit-safe finding shape) is embedded.
    assert payload["report"]["report_schema_version"] == 3
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
        "input_sha256": "i" * 64,
        "runtime_version": "1",
        "runtime_css_sha256": "c" * 64,
        "runtime_js_sha256": "d" * 64,
    }
    assert payload["audit"] == {
        "state": "not_run",
        "safe_trace_projection_sha256": "t" * 64,
        "safe_finding_ids": [],
    }


@pytest.mark.parametrize("audit_state", ["not_run", "current", "stale"])
def test_quality_report_canonical_audit_states_are_safe(
    sample_report_and_waivers, audit_state
):
    safe_finding = Finding(
        "audit.goal:goal-001",
        "audit.goal_weak",
        "warning",
        False,
        False,
        "/course/modules/0",
        "Personalization audit identified weak goal evidence.",
        "Review the cited guide evidence and revise the guide if appropriate.",
        related_ids=("goal-001",),
        stage="audit",
        source_stage="repair",
    )
    kwargs = {
        **sample_report_and_waivers,
        "audit_state": audit_state,
        "safe_audit_projection_sha256": "a" * 64 if audit_state == "current" else None,
        "safe_audit_findings": (safe_finding,) if audit_state == "current" else (),
    }

    first = quality_report_bytes(**kwargs)
    second = quality_report_bytes(**kwargs)

    assert first == second
    payload = json.loads(first)
    assert payload["audit"]["state"] == audit_state
    if audit_state == "current":
        assert payload["audit"]["safe_audit_projection_sha256"] == "a" * 64
    else:
        assert "safe_audit_projection_sha256" not in payload["audit"]
    assert payload["audit"]["safe_finding_ids"] == (
        ["audit.goal:goal-001"] if audit_state == "current" else []
    )
    assert [finding["stage"] for finding in payload["report"]["findings"]] == (
        ["repair", "audit"] if audit_state == "current" else ["repair"]
    )
    assert payload["gate"] == {"open": True, "effective_blocking": 0}
    assert payload["waivers"]["applied"] == ["waivable:one"]
    flat = first.decode("utf-8")
    assert "private audit narrative" not in flat
    assert "f" * 64 not in flat


def test_current_audit_requires_a_valid_projection_sha(sample_report_and_waivers):
    with pytest.raises(ValueError, match="projection SHA"):
        quality_report_bytes(
            **{
                **sample_report_and_waivers,
                "audit_state": "current",
                "safe_audit_projection_sha256": None,
            }
        )
    with pytest.raises(ValueError, match="projection SHA"):
        quality_report_bytes(
            **{
                **sample_report_and_waivers,
                "audit_state": "current",
                "safe_audit_projection_sha256": "not-a-sha",
            }
        )

    payload = json.loads(
        quality_report_bytes(
            **{
                **sample_report_and_waivers,
                "audit_state": "current",
                "safe_audit_projection_sha256": "a" * 64,
            }
        )
    )
    assert payload["audit"]["safe_finding_ids"] == []


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
            audit_state="not_run",
            safe_audit_projection_sha256=None,
            safe_trace_projection_sha256=None,
            safe_audit_findings=(),
            export_input_sha256="i" * 64,
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
        "audit_state": "not_run",
        "safe_audit_projection_sha256": None,
        "safe_trace_projection_sha256": "t" * 64,
        "safe_audit_findings": (),
        "export_input_sha256": "i" * 64,
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
