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


def _calibrated(guide_value, context, **kwargs):
    from education_pipeline.guides.validation import validate_guide as _vg

    return _vg(guide_value, calibration_context=context, **kwargs)


def _rule_ids(report):
    return {finding.rule_id for finding in report.findings}


def _course_with(guide_value, **course_fields):
    return replace(guide_value, course=replace(guide_value.course, **course_fields))


def test_calibration_rule_catalog_has_frozen_severities() -> None:
    expected = {
        "blueprint.unknown": ("warning", False, False, "draft"),
        "blueprint.contract_mismatch": ("error", True, True, "draft"),
        "time.budget_exceeded": ("warning", False, False, "outline"),
        "time.budget_underrun": ("info", False, False, "outline"),
        "time.estimate_implausible": ("warning", False, False, "draft"),
        "time.module_overrun": ("warning", False, False, "outline"),
        "difficulty.learner_mismatch": ("warning", False, False, "outline"),
    }
    assert {
        rule_id: (
            RULES[rule_id].severity,
            RULES[rule_id].blocking,
            RULES[rule_id].waivable,
            RULES[rule_id].stage,
        )
        for rule_id in expected
    } == expected


def test_reading_time_constants_are_pinned() -> None:
    """Calibration only changes deliberately: the model constants are pinned."""

    from education_pipeline.guides.validation import (
        DIFFICULTY_LEVELS,
        READING_TIME_BLOCK_SECONDS,
        READING_TIME_WPM,
        SKILL_LEVEL_KEYWORDS,
    )

    assert READING_TIME_WPM == 200
    assert READING_TIME_BLOCK_SECONDS == {
        "rich_text": 0,
        "callout": 0,
        "knowledge_check": 45,
        "worked_reveal": 90,
        "scenario": 60,
        "reflection": 60,
    }
    assert DIFFICULTY_LEVELS == {
        "introductory": 0,
        "intermediate": 1,
        "advanced": 2,
    }
    assert SKILL_LEVEL_KEYWORDS == {
        "beginner": 0,
        "novice": 0,
        "introductory": 0,
        "intermediate": 1,
        "advanced": 2,
        "expert": 2,
        "experienced": 2,
    }


def test_no_calibration_context_produces_no_calibration_findings() -> None:
    changed = _course_with(guide(), blueprint="custom-unregistered-blueprint")
    report = validate_guide(changed)
    assert not any(
        finding.rule_id.startswith(("blueprint.", "difficulty."))
        or finding.rule_id
        in {"time.budget_exceeded", "time.budget_underrun", "time.estimate_implausible", "time.module_overrun"}
        for finding in report.findings
    )


def test_blueprint_unknown_warns_only_without_configured_blueprint() -> None:
    from education_pipeline.guides.validation import CalibrationContext

    changed = _course_with(guide(), blueprint="custom-unregistered-blueprint")

    unconfigured = _calibrated(changed, CalibrationContext())
    assert "blueprint.unknown" in _rule_ids(unconfigured)
    finding = next(f for f in unconfigured.findings if f.rule_id == "blueprint.unknown")
    assert not finding.blocking and not finding.waivable

    configured = _calibrated(
        changed, CalibrationContext(configured_blueprint="casebook")
    )
    assert "blueprint.unknown" not in _rule_ids(configured)
    assert "blueprint.contract_mismatch" in _rule_ids(configured)

    registered = _calibrated(guide(), CalibrationContext())
    assert "blueprint.unknown" not in _rule_ids(registered)


def test_blueprint_contract_mismatch_is_blocking_and_waivable() -> None:
    from education_pipeline.guides.validation import CalibrationContext

    report = _calibrated(
        guide(), CalibrationContext(configured_blueprint="procedural-skill")
    )
    finding = next(
        f for f in report.findings if f.rule_id == "blueprint.contract_mismatch"
    )
    assert finding.blocking and finding.waivable and finding.severity == "error"
    assert finding.stage == "draft"

    matching = _calibrated(
        guide(), CalibrationContext(configured_blueprint="conceptual-foundations")
    )
    assert "blueprint.contract_mismatch" not in _rule_ids(matching)


def test_time_budget_exceeded_fires_strictly_above_ten_percent() -> None:
    from education_pipeline.guides.validation import CalibrationContext

    # Fixture estimate is 30 minutes. 30 <= 1.1 * 28 is false -> fires;
    # budget 30 (exactly on target) and 28 with estimate 30.8... use ints:
    # budget=27: 1.1*27 = 29.7 < 30 -> fires. budget=28: 30.8 >= 30 -> silent.
    fires = _calibrated(guide(), CalibrationContext(time_budget_minutes=27))
    assert "time.budget_exceeded" in _rule_ids(fires)
    finding = next(f for f in fires.findings if f.rule_id == "time.budget_exceeded")
    assert finding.stage == "outline" and not finding.blocking and not finding.waivable

    silent = _calibrated(guide(), CalibrationContext(time_budget_minutes=28))
    assert "time.budget_exceeded" not in _rule_ids(silent)

    no_budget = _calibrated(guide(), CalibrationContext())
    assert "time.budget_exceeded" not in _rule_ids(no_budget)


def test_time_budget_underrun_fires_strictly_below_half() -> None:
    from education_pipeline.guides.validation import CalibrationContext

    # Fixture estimate 30: budget 61 -> 30 < 30.5 fires; budget 60 -> silent.
    fires = _calibrated(guide(), CalibrationContext(time_budget_minutes=61))
    assert "time.budget_underrun" in _rule_ids(fires)
    finding = next(f for f in fires.findings if f.rule_id == "time.budget_underrun")
    assert finding.severity == "info" and finding.stage == "outline"

    silent = _calibrated(guide(), CalibrationContext(time_budget_minutes=60))
    assert "time.budget_underrun" not in _rule_ids(silent)


def test_estimate_implausible_fires_beyond_factor_two_either_direction() -> None:
    from education_pipeline.guides.validation import (
        CalibrationContext,
        estimated_reading_minutes,
    )

    base = guide()
    model_minutes = estimated_reading_minutes(base)
    assert model_minutes > 0

    # The fixture declares 30 minutes for ~8 minutes of content: implausible.
    report = _calibrated(base, CalibrationContext())
    assert "time.estimate_implausible" in _rule_ids(report)
    finding = next(
        f for f in report.findings if f.rule_id == "time.estimate_implausible"
    )
    assert finding.stage == "draft" and not finding.blocking

    # A declared estimate within 2x of the model in both directions is silent.
    plausible_minutes = max(1, round(model_minutes))
    modules = list(base.modules)
    modules[0] = replace(
        modules[0],
        estimated_minutes=max(1, plausible_minutes - modules[1].estimated_minutes),
    )
    plausible = replace(
        _course_with(base, estimated_minutes=plausible_minutes),
        modules=tuple(modules),
    )
    silent = _calibrated(plausible, CalibrationContext())
    assert "time.estimate_implausible" not in _rule_ids(silent)


def test_module_overrun_requires_attention_constraints_and_46_minutes() -> None:
    from education_pipeline.guides.validation import CalibrationContext

    base = guide()

    def with_module_minutes(minutes: int):
        modules = list(base.modules)
        modules[0] = replace(modules[0], estimated_minutes=minutes)
        return replace(base, modules=tuple(modules))

    fires = _calibrated(
        with_module_minutes(46),
        CalibrationContext(attention_constraints_present=True),
    )
    assert "time.module_overrun" in _rule_ids(fires)
    finding = next(f for f in fires.findings if f.rule_id == "time.module_overrun")
    assert finding.stage == "outline"
    assert base.modules[0].id in finding.id

    at_boundary = _calibrated(
        with_module_minutes(45),
        CalibrationContext(attention_constraints_present=True),
    )
    assert "time.module_overrun" not in _rule_ids(at_boundary)

    without_constraints = _calibrated(with_module_minutes(46), CalibrationContext())
    assert "time.module_overrun" not in _rule_ids(without_constraints)


def test_difficulty_learner_mismatch_uses_the_mechanical_mapping() -> None:
    from education_pipeline.guides.validation import CalibrationContext

    base = guide()  # difficulty: introductory

    fires = _calibrated(base, CalibrationContext(learner_skill_level="advanced"))
    assert "difficulty.learner_mismatch" in _rule_ids(fires)
    finding = next(
        f for f in fires.findings if f.rule_id == "difficulty.learner_mismatch"
    )
    assert finding.severity == "warning" and finding.stage == "outline"

    one_level = _calibrated(
        _course_with(base, difficulty="intermediate"),
        CalibrationContext(learner_skill_level="advanced"),
    )
    assert "difficulty.learner_mismatch" not in _rule_ids(one_level)

    mixed = _calibrated(
        _course_with(base, difficulty="mixed"),
        CalibrationContext(learner_skill_level="advanced"),
    )
    assert "difficulty.learner_mismatch" not in _rule_ids(mixed)

    unmappable = _calibrated(
        base, CalibrationContext(learner_skill_level="somewhere in the middle")
    )
    assert "difficulty.learner_mismatch" not in _rule_ids(unmappable)

    ambiguous = _calibrated(
        base, CalibrationContext(learner_skill_level="advanced beginner")
    )
    assert "difficulty.learner_mismatch" not in _rule_ids(ambiguous)

    no_snapshot = _calibrated(base, CalibrationContext())
    assert "difficulty.learner_mismatch" not in _rule_ids(no_snapshot)


def test_calibration_findings_reference_presence_never_profile_values() -> None:
    from education_pipeline.guides.validation import CalibrationContext

    skill_value = "advanced (planted SecretOrchard cohort)"
    report = _calibrated(
        guide(),
        CalibrationContext(
            time_budget_minutes=10,
            attention_constraints_present=True,
            learner_skill_level=skill_value,
        ),
        private_values=[skill_value],
    )
    rendered = canonical_report_bytes(report).decode()
    assert "SecretOrchard" not in rendered
    assert skill_value not in rendered
    for finding in report.findings:
        if finding.rule_id in {"time.module_overrun", "difficulty.learner_mismatch"}:
            assert "profile" in finding.message
            assert skill_value not in finding.message


def test_findings_carry_stage_and_report_schema_bumped():
    report = validate_guide('{"schema_version": "1.0"}', phase="draft")
    payload = report.to_dict()
    assert payload["report_schema_version"] == 3
    assert all("stage" in f for f in payload["findings"])
