from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pytest

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
        "diagram": 30,
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


# --- schema 1.2 diagrams (spec §3.1, §5) -----------------------------------

DIAGRAMS_FIXTURE = (
    Path(__file__).parent / "fixtures/guides/feedback-loops.diagrams.guide.json"
)
FLOW = "/modules/0/sections/0/blocks/1"
CONCEPT_MAP = "/modules/0/sections/0/blocks/3"
COMPARISON = "/modules/0/sections/1/blocks/0"
TIMELINE = "/modules/1/sections/0/blocks/1"

DIAGRAM_RULES = {
    "diagram.duplicate_id": (
        "blocker",
        "Give every node, event, item and criterion a unique ID within its diagram.",
    ),
    "diagram.unknown_node": ("blocker", "Reference a node declared in the same diagram."),
    "diagram.text_too_long": ("error", "Shorten the diagram text to its limit."),
    "diagram.multiline_text": ("error", "Keep every diagram string on one line."),
    "diagram.self_edge": ("error", "Connect two different nodes."),
    "diagram.duplicate_edge": ("error", "Remove the repeated edge."),
    "diagram.isolated_node": ("error", "Connect the node or remove it."),
    "diagram.disconnected": ("error", "Connect every node to the hub through edges."),
    "diagram.missing_value": ("error", "Give the criterion a value for every item."),
    "diagram.unknown_value_key": (
        "error",
        "Key comparison values by the diagram's item IDs.",
    ),
}


def diagrams_guide():
    return normalize_guide(parse_guide(DIAGRAMS_FIXTURE.read_bytes()))


def _with_block(guide_value, block_id: str, change):
    """Return ``guide_value`` with block ``block_id`` replaced by ``change(block)``."""

    modules = []
    for module in guide_value.modules:
        sections = []
        for section in module.sections:
            blocks = tuple(
                change(block) if block.id == block_id else block
                for block in section.blocks
            )
            sections.append(replace(section, blocks=blocks))
        modules.append(replace(module, sections=tuple(sections)))
    return replace(guide_value, modules=tuple(modules))


def _finding_messages(report) -> dict[tuple[str, str], str]:
    return {(item.rule_id, item.path): item.message for item in report.findings}


def test_diagram_rule_catalog_entries_are_exact() -> None:
    assert {
        rule_id: (
            RULES[rule_id].severity,
            RULES[rule_id].blocking,
            RULES[rule_id].waivable,
            RULES[rule_id].remediation,
            RULES[rule_id].stage,
        )
        for rule_id in DIAGRAM_RULES
    } == {
        rule_id: (severity, True, False, remediation, "draft")
        for rule_id, (severity, remediation) in DIAGRAM_RULES.items()
    }


def test_diagrams_fixture_validates_with_no_findings() -> None:
    report = validate_guide(diagrams_guide(), phase="final")
    from_text = validate_guide(DIAGRAMS_FIXTURE.read_text(encoding="utf-8"))

    assert report.findings == ()
    assert from_text.findings == ()
    assert report.guide_schema_version == "1.2"


def test_parse_time_diagram_diagnostics_keep_their_own_rule_ids() -> None:
    data = json.loads(DIAGRAMS_FIXTURE.read_text(encoding="utf-8"))
    flow = data["modules"][0]["sections"][0]["blocks"][1]
    flow["edges"][3] = {"from": "growth", "to": "growth"}
    comparison = data["modules"][0]["sections"][1]["blocks"][0]
    comparison["criteria"][0]["values"]["ghost"] = "Boo"

    report = validate_guide(json.dumps(data))

    assert _finding_messages(report) == {
        ("diagram.self_edge", f"{FLOW}/edges/3"): "an edge must connect two different nodes",
        (
            "diagram.unknown_value_key",
            f"{COMPARISON}/criteria/0/values/ghost",
        ): "unknown item ID 'ghost'",
    }
    self_edge = next(x for x in report.findings if x.rule_id == "diagram.self_edge")
    assert self_edge.id == f"diagram.self_edge:{FLOW}/edges/3"
    assert self_edge.severity == "error" and self_edge.blocking and not self_edge.waivable


def _chain_nodes(count: int):
    from education_pipeline.guides.model import DiagramEdge, DiagramNode

    nodes = tuple(DiagramNode(f"n{i}", f"Node {i}") for i in range(count))
    edges = tuple(DiagramEdge(f"n{i}", f"n{i + 1}") for i in range(count - 1))
    return nodes, edges


def _in_memory_cases():
    from education_pipeline.guides.model import (
        ComparisonCriterion,
        ComparisonValue,
        DiagramEdge,
        DiagramNode,
        TimelineEvent,
    )

    def rename_first_node(block):
        nodes = (replace(block.nodes[0], id="Bad_Id"),) + block.nodes[1:]
        edges = tuple(
            replace(
                edge,
                from_id="Bad_Id" if edge.from_id == "biomass" else edge.from_id,
                to_id="Bad_Id" if edge.to_id == "biomass" else edge.to_id,
            )
            for edge in block.edges
        )
        return replace(block, nodes=nodes, edges=edges)

    def drop_value(block):
        first = block.criteria[0]
        return replace(
            block,
            criteria=(replace(first, values=first.values[:1]),) + block.criteria[1:],
        )

    def extra_value(block):
        first = block.criteria[0]
        values = first.values + (ComparisonValue("ghost", "Boo"),)
        return replace(block, criteria=(replace(first, values=values),) + block.criteria[1:])

    return {
        "cardinality": (
            "growth-loop-flow",
            lambda b: replace(b, **dict(zip(("nodes", "edges"), _chain_nodes(13)))),
            {("schema.cardinality", f"{FLOW}/nodes"): "must contain 2–12 items"},
        ),
        "invalid-id": (
            "growth-loop-flow",
            rename_first_node,
            {("schema.invalid_id", f"{FLOW}/nodes/0/id"): "must match ^[a-z][a-z0-9-]{0,63}$"},
        ),
        "duplicate-id": (
            "watering-delay-timeline",
            lambda b: replace(
                b, events=b.events[:2] + (replace(b.events[2], id="water"),) + b.events[3:]
            ),
            {
                ("diagram.duplicate_id", f"{TIMELINE}/events/2/id"):
                    f"duplicates diagram ID first declared at {TIMELINE}/events/0/id"
            },
        ),
        "text-too-long": (
            "growth-loop-flow",
            lambda b: replace(b, nodes=(replace(b.nodes[0], label="x" * 49),) + b.nodes[1:]),
            {("diagram.text_too_long", f"{FLOW}/nodes/0/label"): "must not exceed 48 characters"},
        ),
        "multiline": (
            "loop-kinds-map",
            lambda b: replace(b, title="Kinds of\nfeedback"),
            {("diagram.multiline_text", f"{CONCEPT_MAP}/title"): "must be a single line"},
        ),
        "unknown-node": (
            "growth-loop-flow",
            lambda b: replace(b, edges=b.edges[:3] + (DiagramEdge("growth", "nowhere"),)),
            {("diagram.unknown_node", f"{FLOW}/edges/3/to"): "unknown node ID 'nowhere'"},
        ),
        "unknown-hub": (
            "loop-kinds-map",
            lambda b: replace(b, hub="nowhere"),
            {("diagram.unknown_node", f"{CONCEPT_MAP}/hub"): "unknown node ID 'nowhere'"},
        ),
        "self-edge": (
            "growth-loop-flow",
            lambda b: replace(b, edges=b.edges[:3] + (DiagramEdge("growth", "growth"),)),
            {("diagram.self_edge", f"{FLOW}/edges/3"): "an edge must connect two different nodes"},
        ),
        "duplicate-edge": (
            "loop-kinds-map",
            lambda b: replace(b, edges=b.edges + (DiagramEdge("delay", "balancing"),)),
            {
                ("diagram.duplicate_edge", f"{CONCEPT_MAP}/edges/3"):
                    f"duplicates the edge at {CONCEPT_MAP}/edges/2"
            },
        ),
        "isolated-node": (
            "growth-loop-flow",
            lambda b: replace(b, nodes=b.nodes + (DiagramNode("weather", "Weather"),)),
            {("diagram.isolated_node", f"{FLOW}/nodes/4"): "node 'weather' has no edges"},
        ),
        "disconnected": (
            "loop-kinds-map",
            lambda b: replace(b, nodes=b.nodes + (DiagramNode("orphan", "Orphan"),)),
            {
                ("diagram.disconnected", f"{CONCEPT_MAP}/nodes/4"):
                    "node 'orphan' is not connected to the hub 'feedback-loop'"
            },
        ),
        "missing-value": (
            "loop-types-comparison",
            drop_value,
            {
                ("diagram.missing_value", f"{COMPARISON}/criteria/0/values"):
                    "missing a value for item 'balancing'"
            },
        ),
        "unknown-value-key": (
            "loop-types-comparison",
            extra_value,
            {
                ("diagram.unknown_value_key", f"{COMPARISON}/criteria/0/values/ghost"):
                    "unknown item ID 'ghost'"
            },
        ),
        "foreign-events-on-flow": (
            "growth-loop-flow",
            lambda b: replace(b, events=(TimelineEvent("e", "Day 1", "Event"),)),
            {("schema.unknown_field", f"{FLOW}/events"): "unknown field 'events'"},
        ),
        "foreign-hub-on-flow": (
            "growth-loop-flow",
            lambda b: replace(b, hub="biomass"),
            {("schema.unknown_field", f"{FLOW}/hub"): "unknown field 'hub'"},
        ),
        "foreign-criteria-on-timeline": (
            "watering-delay-timeline",
            lambda b: replace(
                b,
                criteria=(ComparisonCriterion("c", "Criterion", ()),),
            ),
            {("schema.unknown_field", f"{TIMELINE}/criteria"): "unknown field 'criteria'"},
        ),
    }


IN_MEMORY_CASE_NAMES = (
    "cardinality",
    "invalid-id",
    "duplicate-id",
    "text-too-long",
    "multiline",
    "unknown-node",
    "unknown-hub",
    "self-edge",
    "duplicate-edge",
    "isolated-node",
    "disconnected",
    "missing-value",
    "unknown-value-key",
    "foreign-events-on-flow",
    "foreign-hub-on-flow",
    "foreign-criteria-on-timeline",
)



@pytest.mark.parametrize("case", IN_MEMORY_CASE_NAMES)
def test_in_memory_guide_triggers_each_dataclass_diagram_rule(case) -> None:
    block_id, change, expected = _in_memory_cases()[case]
    changed = _with_block(diagrams_guide(), block_id, change)

    report = validate_guide(changed)

    assert _finding_messages(report) == expected
    for finding in report.findings:
        assert finding.id == f"{finding.rule_id}:{finding.path}"
        assert finding.related_ids == (block_id,)
        assert finding.blocking


@pytest.mark.parametrize("version", ["1.0", "1.1"])
def test_in_memory_diagram_under_an_older_schema_is_an_unknown_block_type(version) -> None:
    changed = replace(diagrams_guide(), schema_version=version)

    report = validate_guide(changed)

    assert _finding_messages(report) == {
        ("schema.unknown_block_type", f"{path}/type"): "unknown block type 'diagram'"
        for path in (FLOW, CONCEPT_MAP, COMPARISON, TIMELINE)
    }


def test_diagram_finding_ids_are_distinct_per_path() -> None:
    from education_pipeline.guides.model import DiagramNode

    changed = _with_block(
        diagrams_guide(),
        "growth-loop-flow",
        lambda b: replace(
            b,
            nodes=b.nodes + (DiagramNode("rain", "Rain"), DiagramNode("wind", "Wind")),
        ),
    )

    findings = [
        item for item in validate_guide(changed).findings
        if item.rule_id == "diagram.isolated_node"
    ]

    assert [item.id for item in findings] == [
        f"diagram.isolated_node:{FLOW}/nodes/4",
        f"diagram.isolated_node:{FLOW}/nodes/5",
    ]


def test_diagrams_never_raise_source_missing_for_required_claim() -> None:
    report = validate_guide(
        diagrams_guide(), context=ValidationContext(sources_required=True)
    )
    paths = {
        item.path
        for item in report.findings
        if item.rule_id == "source.missing_for_required_claim"
    }

    assert paths  # the rule still runs for rich text and callouts
    assert not paths & {FLOW, CONCEPT_MAP, COMPARISON, TIMELINE}


def test_text_fields_use_json_names_and_keyed_value_paths() -> None:
    from education_pipeline.guides.validation import _text_fields

    fields_by_path = dict(_text_fields(diagrams_guide()))

    assert fields_by_path[f"{FLOW}/edges/0/from"] == "biomass"
    assert fields_by_path[f"{FLOW}/edges/0/to"] == "leaf-area"
    assert fields_by_path[f"{COMPARISON}/criteria/0/values/reinforcing"] == (
        "Amplifies change in one direction"
    )
    assert fields_by_path[f"{COMPARISON}/criteria/2/values/balancing"] == (
        "*Overcorrection* when feedback is delayed"
    )
    assert not [
        path
        for path in fields_by_path
        if "from_id" in path or "to_id" in path or "item_id" in path
        or "/values/0" in path
    ]


def test_content_scans_reach_every_diagram_string() -> None:
    changed = _with_block(
        diagrams_guide(),
        "loop-types-comparison",
        lambda b: replace(
            b,
            criteria=(
                replace(
                    b.criteria[0],
                    values=(
                        replace(b.criteria[0].values[0], text="Ask Secret Orchard"),
                        replace(b.criteria[0].values[1], text="TODO"),
                    ),
                ),
            )
            + b.criteria[1:],
        ),
    )

    report = validate_guide(changed, private_values=["Secret Orchard"])
    pairs = {(item.rule_id, item.path) for item in report.findings}

    assert (
        "privacy.exact_private_value",
        f"{COMPARISON}/criteria/0/values/reinforcing",
    ) in pairs
    assert ("content.placeholder", f"{COMPARISON}/criteria/0/values/balancing") in pairs
    assert "Secret Orchard" not in canonical_report_bytes(report).decode()
