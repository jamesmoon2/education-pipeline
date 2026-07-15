from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pytest

import test_runs
from education_pipeline import ConfigError, ProfileStore
from education_pipeline.guides import normalize_guide, parse_guide
from education_pipeline.guides import validation as guide_validation
from education_pipeline.guides.reports import canonical_report_bytes
from education_pipeline.privacy import private_value_fingerprint, profile_private_values


TARGET_LEARNER = "Orchid Harbor mentorship cohort"
LEARNING_GOAL = "Compare crisis playbooks across orbital supply chains"
METADATA_SECRET = "BlueLanternTransitionProgram"


def _profile_toml(*, protected_values: bool = True) -> str:
    if not protected_values:
        return """\
schema_version = 1
id = "user"
target_learner = "learner"
reading_level = "advanced"
pace = "self-paced"

[privacy]
private_by_default = true
include_in_published_output = false
"""
    return f"""\
schema_version = 1
id = "privacy-regression-profile"
target_learner = "{TARGET_LEARNER}"
learning_goals = ["{LEARNING_GOAL}"]
reading_level = "advanced"
pace = "self-paced"

[privacy]
private_by_default = true
include_in_published_output = false

[metadata]
program = {{ details = {{ name = "{METADATA_SECRET}" }} }}
"""


def _attached_run(tmp_path: Path, *, protected_values: bool = True):
    topic_id = "systems-thinking"
    profile_id = "privacy-regression-profile" if protected_values else "user"
    profiles = ProfileStore(tmp_path)
    profiles.save_profile_toml(profile_id, _profile_toml(protected_values=protected_values))
    profiles.attach_profile_to_topic(profile_id, topic_id)
    return test_runs._create_guide_run(tmp_path, topic_id), topic_id


def _run_with_target(tmp_path: Path, target_learner: str):
    topic_id = "systems-thinking"
    profiles = ProfileStore(tmp_path)
    profiles.save_profile_toml(
        "adversarial-profile",
        f'''\
schema_version = 1
id = "adversarial-profile"
target_learner = "{target_learner}"

[privacy]
private_by_default = true
include_in_published_output = false
''',
    )
    profiles.attach_profile_to_topic("adversarial-profile", topic_id)
    return test_runs._create_guide_run(tmp_path, topic_id), topic_id


def _guide_with_text(text: str) -> str:
    data = json.loads(test_runs.GUIDE_FIXTURE)
    data["course"]["description"] = text
    return json.dumps(data)


def _privacy_findings(report_path: Path) -> list[dict[str, object]]:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    return [
        finding
        for finding in report["findings"]
        if finding["rule_id"] == "privacy.exact_private_value"
    ]


def test_attached_profile_policy_blocks_target_goal_and_recursive_metadata_in_draft_and_final(
    tmp_path: Path,
) -> None:
    runs, topic_id = _attached_run(tmp_path)
    planted = _guide_with_text(
        f"For {TARGET_LEARNER}, practice {LEARNING_GOAL} through the "
        f"{METADATA_SECRET}. This advanced self-paced guide stays practical."
    )

    test_runs._drive_guide_to_finalize_ready(
        runs,
        topic_id,
        draft_body=planted,
        repair_body=planted,
    )

    expected_fingerprints = {
        private_value_fingerprint(value)
        for value in (TARGET_LEARNER, LEARNING_GOAL, METADATA_SECRET)
    }
    for report_path in (runs.draft_report_path(topic_id), runs.final_report_path(topic_id)):
        findings = _privacy_findings(report_path)
        assert {str(finding["id"]).rsplit(":", 1)[-1] for finding in findings} >= expected_fingerprints
        assert all(finding["blocking"] is True for finding in findings)
        assert all(finding["waivable"] is True for finding in findings)

    with pytest.raises(ConfigError):
        runs.finalize_run(topic_id)
    with pytest.raises(ConfigError):
        runs.export_run(topic_id, format="html")
    assert not runs.export_path(topic_id, "html").exists()
    assert not runs.export_report_path(topic_id).exists()


def test_low_risk_generic_profile_terms_do_not_block_run_validation(tmp_path: Path) -> None:
    runs, topic_id = _attached_run(tmp_path, protected_values=False)
    guide_json = _guide_with_text("An advanced self-paced course for every learner.")

    test_runs._drive_guide_to_finalize_ready(
        runs,
        topic_id,
        draft_body=guide_json,
        repair_body=guide_json,
    )

    assert runs._private_profile_values(topic_id) == ()
    assert _privacy_findings(runs.draft_report_path(topic_id)) == []
    assert _privacy_findings(runs.final_report_path(topic_id)) == []
    runs.finalize_run(topic_id)
    assert runs.export_run(topic_id, format="html").is_file()


def test_private_profile_values_wrapper_uses_the_shared_policy(tmp_path: Path) -> None:
    runs, topic_id = _attached_run(tmp_path)
    profile = ProfileStore(tmp_path).load_topic_profile_snapshot(topic_id)

    assert runs._private_profile_values(topic_id) == profile_private_values(profile)


def test_private_input_is_redacted_from_diagnostics_reports_manifest_and_logs(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    runs, topic_id = _attached_run(tmp_path)
    data = json.loads(test_runs.GUIDE_FIXTURE)
    data["modules"][0]["sections"][0]["blocks"][0]["markdown"] = (
        f"[unsafe](javascript:{METADATA_SECRET})"
    )
    invalid_guide = json.dumps(data)

    test_runs._drive_guide_to_draft_approved(runs, topic_id, invalid_guide)
    runs.validate_run(topic_id, "draft")

    report_bytes = runs.draft_report_path(topic_id).read_bytes()
    manifest_bytes = json.dumps(runs.read_manifest(topic_id), sort_keys=True).encode("utf-8")
    observed = b"\n".join((report_bytes, manifest_bytes, caplog.text.encode("utf-8"))).lower()
    for private in (TARGET_LEARNER, LEARNING_GOAL, METADATA_SECRET):
        assert private.encode("utf-8").lower() not in observed
    assert b"[redacted]" in report_bytes


def test_profile_presence_is_explicit_and_standalone_validation_has_no_run_only_finding(
    tmp_path: Path,
) -> None:
    context_type = guide_validation.PersonalizationValidationContext
    assert context_type(profile_present=True).authoritative_goal_ids == ()

    standalone = guide_validation.validate_guide(test_runs.GUIDE_FIXTURE)
    assert "personalization.no_profile" not in {finding.rule_id for finding in standalone.findings}

    explicit_missing = guide_validation.validate_guide(
        test_runs.GUIDE_FIXTURE,
        personalization_context=context_type(profile_present=False),
    )
    assert "personalization.no_profile" in {
        finding.rule_id for finding in explicit_missing.findings
    }

    profiled_empty_denylist = guide_validation.validate_guide(
        test_runs.GUIDE_FIXTURE,
        private_values=(),
        personalization_context=context_type(profile_present=True),
    )
    assert "personalization.no_profile" not in {
        finding.rule_id for finding in profiled_empty_denylist.findings
    }

    runs = test_runs._create_guide_run(tmp_path, "systems-thinking")
    test_runs._drive_guide_to_draft_approved(runs, "systems-thinking")
    runs.validate_run("systems-thinking", "draft")
    report = json.loads(runs.draft_report_path("systems-thinking").read_text(encoding="utf-8"))
    no_profile = [
        finding
        for finding in report["findings"]
        if finding["rule_id"] == "personalization.no_profile"
    ]
    assert len(no_profile) == 1
    assert no_profile[0]["severity"] == "info"
    assert no_profile[0]["blocking"] is False
    assert no_profile[0]["waivable"] is False


def test_unicode_private_value_is_removed_from_diagnostic_message_path_id_and_logs(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    private = "StraßeGeheimProgramm"
    runs, topic_id = _run_with_target(tmp_path, private)
    data = json.loads(test_runs.GUIDE_FIXTURE)
    data["course"][private] = "unregistered"

    test_runs._drive_guide_to_draft_approved(
        runs,
        topic_id,
        json.dumps(data, ensure_ascii=False),
    )
    runs.validate_run(topic_id, "draft")

    report_bytes = runs.draft_report_path(topic_id).read_bytes()
    report = json.loads(report_bytes)
    unknown = next(
        finding
        for finding in report["findings"]
        if finding["rule_id"] == "schema.unknown_field"
    )
    assert private.casefold() not in str(unknown).casefold()
    assert private.casefold() not in report_bytes.decode("utf-8").casefold()
    assert private.casefold() not in caplog.text.casefold()


def test_private_identity_is_removed_from_nonprivacy_finding_id_path_and_related_ids(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    private = "secret-course"
    runs, topic_id = _run_with_target(tmp_path, private)
    data = json.loads(test_runs.GUIDE_FIXTURE)
    data["course"]["id"] = private
    data["course"]["estimated_minutes"] += 1

    test_runs._drive_guide_to_draft_approved(runs, topic_id, json.dumps(data))
    runs.validate_run(topic_id, "draft")

    report_bytes = runs.draft_report_path(topic_id).read_bytes()
    report = json.loads(report_bytes)
    mismatch = next(
        finding
        for finding in report["findings"]
        if finding["rule_id"] == "time.module_total_mismatch"
    )
    assert private not in mismatch["id"]
    assert private not in mismatch["path"]
    assert all(private not in related for related in mismatch.get("related_ids", []))
    assert private not in report_bytes.decode("utf-8")
    assert private not in caplog.text


@pytest.mark.parametrize("phase", ["draft", "final"])
def test_each_validation_computation_loads_one_profile_snapshot_and_cannot_mix_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    phase: str,
) -> None:
    private = "single-snapshot-secret"
    runs, topic_id = _run_with_target(tmp_path, private)
    leaked_guide = _guide_with_text(f"A lesson for {private}.")
    if phase == "draft":
        test_runs._drive_guide_to_draft_approved(runs, topic_id, leaked_guide)
    profile = ProfileStore(tmp_path).load_topic_profile_snapshot(topic_id)
    snapshot_path = ProfileStore(tmp_path).topic_profile_snapshot_path(topic_id)
    snapshot = (
        profile,
        snapshot_path,
        hashlib.sha256(snapshot_path.read_bytes()).hexdigest(),
    )
    loads: list[str] = []

    def alternating_snapshot(_runs, topic: str):
        loads.append(topic)
        return snapshot if len(loads) == 1 else None

    monkeypatch.setattr(
        type(runs),
        "_read_attached_profile_snapshot",
        alternating_snapshot,
    )
    if phase == "draft":
        report = runs._compute_phase_report(topic_id, "draft").report
    else:
        report, _, _ = runs._validated_final(topic_id, leaked_guide)

    assert loads == [topic_id]
    rules = {finding.rule_id for finding in report.findings}
    assert "privacy.exact_private_value" in rules
    assert "personalization.no_profile" not in rules


def test_composed_profile_value_blocks_decomposed_guide_equivalent() -> None:
    composed = "Caf\N{LATIN SMALL LETTER E WITH ACUTE} Confidentiel"
    decomposed = "Cafe\N{COMBINING ACUTE ACCENT} Confidentiel"
    report = guide_validation.validate_guide(
        _guide_with_text(f"Designed for {decomposed}."),
        private_values=(composed,),
    )

    leaks = [
        finding
        for finding in report.findings
        if finding.rule_id == "privacy.exact_private_value"
    ]
    assert len(leaks) == 1
    assert private_value_fingerprint(composed) in leaks[0].id


@pytest.mark.parametrize("private_values", [(), ("protected-value",)])
def test_validation_is_total_for_lone_surrogates_in_raw_and_guide_text(
    private_values: tuple[str, ...],
) -> None:
    data = json.loads(test_runs.GUIDE_FIXTURE)
    data["modules"][0]["sections"][0]["blocks"][0]["markdown"] = (
        "Malformed scalar \ud800 with protected-value."
    )
    raw = json.dumps(data, ensure_ascii=False)
    original = normalize_guide(parse_guide(test_runs.GUIDE_FIXTURE))
    module = original.modules[0]
    section = module.sections[0]
    block = replace(
        section.blocks[0],
        markdown="Malformed scalar \ud800 with protected-value.",
    )
    guide = replace(
        original,
        modules=(
            replace(
                module,
                sections=(
                    replace(section, blocks=(block,) + section.blocks[1:]),
                )
                + module.sections[1:],
            ),
        )
        + original.modules[1:],
    )

    for value in (raw, guide):
        personalization_context = (
            guide_validation.PersonalizationValidationContext(profile_present=True)
            if private_values
            else None
        )
        first = guide_validation.validate_guide(
            value,
            private_values=private_values,
            personalization_context=personalization_context,
        )
        second = guide_validation.validate_guide(
            value,
            private_values=private_values,
            personalization_context=personalization_context,
        )
        assert canonical_report_bytes(first) == canonical_report_bytes(second)
        leak_rules = {
            finding.rule_id
            for finding in first.findings
            if finding.rule_id == "privacy.exact_private_value"
        }
        assert bool(leak_rules) is bool(private_values)


@pytest.mark.parametrize("private_values", [(), ("protected-value",)])
def test_escaped_surrogate_in_valid_json_text_fails_closed_deterministically(
    private_values: tuple[str, ...],
) -> None:
    data = json.loads(test_runs.GUIDE_FIXTURE)
    data["modules"][0]["sections"][0]["blocks"][0]["markdown"] = (
        "Escaped scalar \ud800 with protected-value."
    )
    raw = json.dumps(data)
    assert raw.isascii()
    assert r"\ud800" in raw

    reports = [
        guide_validation.validate_guide(raw, private_values=private_values)
        for _ in range(2)
    ]
    assert canonical_report_bytes(reports[0]) == canonical_report_bytes(reports[1])
    invalid = [
        finding
        for finding in reports[0].findings
        if finding.rule_id == "schema.invalid_value"
    ]
    assert invalid
    assert all(finding.blocking and not finding.waivable for finding in invalid)
    assert "\ud800" not in canonical_report_bytes(reports[0]).decode("utf-8")
    assert any(
        finding.rule_id == "privacy.exact_private_value"
        for finding in reports[0].findings
    ) is bool(private_values)


@pytest.mark.parametrize("private_values", [(), ("protected-value",)])
def test_escaped_surrogate_in_unknown_key_has_safe_deterministic_diagnostics(
    private_values: tuple[str, ...],
) -> None:
    data = json.loads(test_runs.GUIDE_FIXTURE)
    data["course"]["unknown-\ud800-protected-value"] = True
    raw = json.dumps(data)
    assert raw.isascii()
    assert r"\ud800" in raw

    reports = [
        guide_validation.validate_guide(raw, private_values=private_values)
        for _ in range(2)
    ]
    rendered = canonical_report_bytes(reports[0])
    assert rendered == canonical_report_bytes(reports[1])
    rules = {finding.rule_id for finding in reports[0].findings}
    assert {"schema.invalid_value", "schema.unknown_field"} <= rules
    assert next(
        finding
        for finding in reports[0].findings
        if finding.rule_id == "schema.invalid_value"
    ).blocking is True
    assert "\ud800" not in rendered.decode("utf-8")


def test_run_report_state_uses_sanitized_hash_for_escaped_surrogate_source(
    tmp_path: Path,
) -> None:
    runs = test_runs._create_guide_run(tmp_path, "systems-thinking")
    data = json.loads(test_runs.GUIDE_FIXTURE)
    data["modules"][0]["sections"][0]["blocks"][0]["markdown"] = (
        "Escaped scalar \ud800 in a run source."
    )
    raw = json.dumps(data)
    assert raw.isascii()

    test_runs._drive_guide_to_draft_approved(runs, "systems-thinking", raw)
    runs.validate_run("systems-thinking", "draft")

    report = json.loads(
        runs.draft_report_path("systems-thinking").read_text(encoding="utf-8")
    )
    assert any(
        finding["rule_id"] == "schema.invalid_value" and finding["blocking"]
        for finding in report["findings"]
    )
    assert runs.report_state("systems-thinking", "draft") == "current"


def test_exact_private_fingerprint_identity_is_not_redacted_by_an_overlapping_value() -> None:
    source_private = "bu8ua"
    fingerprint_prefix = "04c77"
    fingerprint = private_value_fingerprint(source_private)
    assert fingerprint.startswith(fingerprint_prefix)

    report = guide_validation.validate_guide(
        _guide_with_text(f"Private marker: {source_private}."),
        private_values=(source_private, fingerprint_prefix),
    )
    leak = next(
        finding
        for finding in report.findings
        if finding.rule_id == "privacy.exact_private_value"
        and fingerprint in finding.id
    )
    assert leak.id == f"privacy.exact_private_value:{fingerprint}"
    assert fingerprint in leak.message
    assert leak.waivable is True
