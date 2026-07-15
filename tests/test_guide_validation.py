from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

from education_pipeline.guides import normalize_guide, parse_guide
from education_pipeline.guides.model import GoalExclusion
from education_pipeline.guides.reports import canonical_report_bytes
from education_pipeline.guides.validation import (
    RULES,
    PersonalizationValidationContext,
    ValidationContext,
    validate_guide,
)

FIXTURE = Path(__file__).parent / "fixtures/guides/feedback-loops.guide.json"


def guide():
    return normalize_guide(parse_guide(FIXTURE.read_bytes()))


def test_fixture_report_is_deterministic_and_has_no_blockers() -> None:
    first = validate_guide(guide(), phase="final")
    second = validate_guide(guide(), phase="final")
    assert first.summary.blocking == 0
    assert canonical_report_bytes(first) == canonical_report_bytes(second)
    assert b"timestamp" not in canonical_report_bytes(first)
    assert first.findings == ()


def test_parse_diagnostics_become_stable_sorted_findings() -> None:
    data = json.loads(FIXTURE.read_text())
    data["course"].pop("title")
    data["surprise"] = True
    report = validate_guide(json.dumps(data))
    assert [item.rule_id for item in report.findings] == [
        "schema.missing_field",
        "schema.unknown_field",
    ]
    assert report.findings[0].id == "schema.missing_field:/course"
    assert report.summary.blocking == 2


def test_parse_diagnostics_also_redact_private_values() -> None:
    private = "SecretOrchard"
    data = json.loads(FIXTURE.read_text())
    data["modules"][0]["sections"][0]["blocks"][0]["markdown"] = f"[x](javascript:{private})"
    rendered = canonical_report_bytes(validate_guide(json.dumps(data), private_values=[private])).decode()
    assert private not in rendered
    assert "[redacted]" in rendered


def test_content_time_privacy_and_accessibility_rules_have_stable_ids() -> None:
    original = guide()
    first_module = original.modules[0]
    first_section = first_module.sections[0]
    first_block = replace(
        first_section.blocks[0],
        markdown="# Private\nContact jane@example.com. TODO use the red button. Secret Orchard.",
    )
    changed = replace(
        original,
        modules=(
            replace(first_module, estimated_minutes=99, sections=(replace(first_section, blocks=(first_block,) + first_section.blocks[1:]),) + first_module.sections[1:]),
        ) + original.modules[1:],
    )
    report = validate_guide(changed, private_values=["Secret Orchard", "none", "user"])
    ids = {item.rule_id for item in report.findings}
    assert {
        "privacy.exact_private_value",
        "privacy.possible_identifier",
        "content.placeholder",
        "markdown.invalid_heading_level",
        "a11y.color_only_instruction",
        "time.module_total_mismatch",
    } <= ids
    rendered = canonical_report_bytes(report).decode()
    assert "Secret Orchard" not in rendered
    assert "jane@example.com" not in rendered


def test_unclosed_fence_is_reported_without_changing_parser() -> None:
    original = guide()
    module = original.modules[0]
    section = module.sections[0]
    block = replace(section.blocks[0], markdown="Example:\n```python\nprint('safe')")
    changed = replace(original, modules=(replace(module, sections=(replace(section, blocks=(block,) + section.blocks[1:]),) + module.sections[1:]),) + original.modules[1:])
    finding = next(x for x in validate_guide(changed).findings if x.rule_id == "markdown.unclosed_fence")
    assert finding.id == "markdown.unclosed_fence:/modules/0/sections/0/blocks/0/markdown"


def test_complete_milestone_rule_catalog_is_declared() -> None:
    required = {
        "json.invalid", "schema.size_limit", "privacy.exact_private_value",
        "content.prompt_leak", "outcome.unassessed", "knowledge_check.invalid_answer_set",
        "source.missing_for_required_claim", "runtime.render_failed",
        "runtime.asset_mismatch", "a11y.control_label_missing", "a11y.heading_order",
    }
    assert required <= RULES.keys()


def test_raw_size_limit_runs_before_parsing() -> None:
    report = validate_guide(b" " * 2_000_001)
    assert [x.rule_id for x in report.findings] == ["schema.size_limit"]


def test_source_reference_diagnostic_uses_source_rule() -> None:
    data = json.loads(FIXTURE.read_text())
    data["modules"][0]["sections"][0]["blocks"][0]["source_ids"] = ["missing-source"]
    assert "source.unknown_reference" in {x.rule_id for x in validate_guide(json.dumps(data)).findings}


def test_source_policy_and_all_static_runtime_invariants_are_executable() -> None:
    context = ValidationContext(
        sources_required=True,
        render_succeeded=False,
        assets_match=False,
        controls_have_labels=False,
        heading_order_valid=False,
    )
    ids = {x.rule_id for x in validate_guide(guide(), context=context).findings}
    assert {
        "source.missing_for_required_claim",
        "runtime.render_failed",
        "runtime.asset_mismatch",
        "a11y.control_label_missing",
        "a11y.heading_order",
    } <= ids


def test_parser_backed_outcome_pedagogy_and_content_rules_are_mapped() -> None:
    data = json.loads(FIXTURE.read_text())
    data["outcomes"].append({"id": "extra-outcome", "text": "An extra outcome"})
    data["modules"][0]["sections"][0]["blocks"][0]["markdown"] = "x" * 20_001
    ids = {x.rule_id for x in validate_guide(json.dumps(data)).findings}
    assert {"outcome.unassigned", "outcome.untaught", "outcome.unassessed", "content.excessive_length"} <= ids


def test_parser_diagnostics_map_to_catalog_specific_rule_ids() -> None:
    data = json.loads(FIXTURE.read_text())
    blocks = [block for module in data["modules"] for section in module["sections"] for block in section["blocks"]]
    reveal = next(block for block in blocks if block["type"] == "worked_reveal")
    reveal["steps"] = reveal["steps"][:1]
    rich = next(block for block in blocks if block["type"] == "rich_text")
    rich["markdown"] = "[unsafe](javascript:alert(1))"
    ids = {x.rule_id for x in validate_guide(json.dumps(data)).findings}
    assert {"worked_reveal.too_few_steps", "link.unsafe_scheme"} <= ids


def test_every_rule_declares_a_responsible_stage():
    from education_pipeline.guides.validation import RULES

    assert all(rule.stage in {"spec", "outline", "draft", "qa", "repair"} for rule in RULES.values())
    assert RULES["outcome.untaught"].stage == "outline"
    assert RULES["a11y.heading_order"].stage == "repair"
    assert RULES["privacy.exact_private_value"].stage == "draft"


def test_personalization_rule_catalog_has_frozen_severities() -> None:
    expected = {
        "personalization.goal_uncovered": ("warning", False, True),
        "personalization.no_annotations": ("warning", False, True),
        "personalization.dangling_goal_ref": ("error", True, False),
        "personalization.duplicate_goal_ref": ("error", True, False),
        "personalization.unexpected_annotations": ("warning", False, True),
        "personalization.no_profile": ("info", False, False),
    }
    assert {
        rule_id: (RULES[rule_id].severity, RULES[rule_id].blocking, RULES[rule_id].waivable)
        for rule_id in expected
    } == expected
    assert all(RULES[rule_id].stage == "draft" for rule_id in expected)


def test_profile_goals_without_annotations_are_uncovered_and_warn_once() -> None:
    report = validate_guide(
        guide(),
        personalization_context=PersonalizationValidationContext(
            profile_present=True,
            authoritative_goal_ids=("goal-001", "goal-002"),
        ),
    )
    rule_ids = [finding.rule_id for finding in report.findings]
    assert rule_ids.count("personalization.no_annotations") == 1
    assert rule_ids.count("personalization.goal_uncovered") == 2


def test_goal_service_and_nonempty_exclusion_clear_uncovered() -> None:
    original = guide()
    changed = replace(
        original,
        schema_version="1.1",
        outcomes=(replace(original.outcomes[0], serves_goals=("goal-001",)),)
        + original.outcomes[1:],
        course=replace(
            original.course,
            goal_exclusions=(GoalExclusion("goal-002", "Synthetic deferral."),),
        ),
    )
    report = validate_guide(
        changed,
        personalization_context=PersonalizationValidationContext(
            profile_present=True,
            authoritative_goal_ids=("goal-001", "goal-002"),
        ),
    )
    assert not {
        "personalization.goal_uncovered",
        "personalization.no_annotations",
        "personalization.duplicate_goal_ref",
    } & {finding.rule_id for finding in report.findings}

    empty_exclusion = replace(
        original,
        schema_version="1.1",
        course=replace(
            original.course,
            goal_exclusions=(GoalExclusion("goal-001", ""),),
        ),
    )
    empty_report = validate_guide(
        empty_exclusion,
        personalization_context=PersonalizationValidationContext(
            profile_present=True,
            authoritative_goal_ids=("goal-001",),
        ),
    )
    assert "personalization.goal_uncovered" in {
        finding.rule_id for finding in empty_report.findings
    }


def test_exact_duplicate_semantics_allow_cross_element_service_only() -> None:
    original = guide()
    legal = replace(
        original,
        schema_version="1.1",
        outcomes=(replace(original.outcomes[0], serves_goals=("goal-001",)),)
        + original.outcomes[1:],
        modules=(replace(original.modules[0], serves_goals=("goal-001",)),)
        + original.modules[1:],
    )
    context = PersonalizationValidationContext(
        profile_present=True,
        authoritative_goal_ids=("goal-001",),
    )
    assert "personalization.duplicate_goal_ref" not in {
        finding.rule_id for finding in validate_guide(legal, personalization_context=context).findings
    }

    duplicate_field = replace(
        legal,
        modules=(replace(legal.modules[0], serves_goals=("goal-001", "goal-001")),)
        + legal.modules[1:],
    )
    duplicate_exclusion = replace(
        legal,
        course=replace(
            legal.course,
            goal_exclusions=(
                GoalExclusion("goal-001", "First synthetic reason."),
                GoalExclusion("goal-001", "Second synthetic reason."),
            ),
        ),
    )
    for candidate in (duplicate_field, duplicate_exclusion):
        finding = next(
            finding
            for finding in validate_guide(candidate, personalization_context=context).findings
            if finding.rule_id == "personalization.duplicate_goal_ref"
        )
        assert (finding.severity, finding.blocking, finding.waivable) == (
            "error",
            True,
            False,
        )


def test_dangling_and_unprofiled_annotations_use_safe_findings() -> None:
    original = guide()
    changed = replace(
        original,
        schema_version="1.1",
        modules=(replace(original.modules[0], serves_goals=("goal-999",)),)
        + original.modules[1:],
    )
    profiled = validate_guide(
        changed,
        personalization_context=PersonalizationValidationContext(
            profile_present=True,
            authoritative_goal_ids=("goal-001",),
        ),
    )
    assert "personalization.dangling_goal_ref" in {
        finding.rule_id for finding in profiled.findings
    }
    unprofiled = validate_guide(
        changed,
        personalization_context=PersonalizationValidationContext(profile_present=False),
    )
    assert {
        "personalization.no_profile",
        "personalization.unexpected_annotations",
    } <= {finding.rule_id for finding in unprofiled.findings}


def test_annotation_finding_paths_are_exact_json_pointers() -> None:
    original = guide()
    changed = replace(
        original,
        schema_version="1.1",
        outcomes=(replace(original.outcomes[0], serves_goals=("goal-999",)),)
        + original.outcomes[1:],
        modules=(
            replace(
                original.modules[0],
                serves_goals=("goal-001", "goal-001"),
            ),
        )
        + original.modules[1:],
    )
    report = validate_guide(
        changed,
        personalization_context=PersonalizationValidationContext(
            profile_present=True,
            authoritative_goal_ids=("goal-001",),
        ),
    )
    paths = {
        (finding.rule_id, finding.path)
        for finding in report.findings
        if finding.rule_id in {
            "personalization.dangling_goal_ref",
            "personalization.duplicate_goal_ref",
        }
    }
    assert (
        "personalization.dangling_goal_ref",
        "/outcomes/0/serves_goals",
    ) in paths
    assert (
        "personalization.duplicate_goal_ref",
        "/modules/0/serves_goals",
    ) in paths


def test_private_exclusion_reason_is_not_scanned_as_public_guide_text() -> None:
    original = guide()
    private_reason = "Synthetic Private Exclusion Reason"
    changed = replace(
        original,
        schema_version="1.1",
        course=replace(
            original.course,
            goal_exclusions=(GoalExclusion("goal-001", private_reason),),
        ),
    )
    report = validate_guide(
        changed,
        private_values=(private_reason,),
        personalization_context=PersonalizationValidationContext(
            profile_present=True,
            authoritative_goal_ids=("goal-001",),
        ),
    )
    assert "privacy.exact_private_value" not in {
        finding.rule_id for finding in report.findings
    }


def test_findings_carry_stage_and_report_schema_bumped():
    report = validate_guide('{"schema_version": "1.0"}', phase="draft")
    payload = report.to_dict()
    assert payload["report_schema_version"] == 2
    assert all("stage" in f for f in payload["findings"])
