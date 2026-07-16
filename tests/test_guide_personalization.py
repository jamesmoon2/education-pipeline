from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from education_pipeline.guides.model import GoalExclusion
from education_pipeline.guides.parse import normalize_guide, parse_guide
from education_pipeline.guides.personalization import (
    ACTIVE_FACET_IDS,
    PERSONALIZATION_TRACE_SCHEMA_VERSION,
    PersonalizationGoalTrace,
    PersonalizationTrace,
    PersonalizationTraceError,
    active_personalization_facets,
    authoritative_goals,
    build_personalization_trace,
    canonical_personalization_trace_bytes,
    canonical_safe_personalization_trace_bytes,
    index_personalization_annotations,
    parse_personalization_trace,
    personalization_trace_is_fresh,
    safe_personalization_trace_projection,
    safe_personalization_trace_sha256,
)
from education_pipeline.profiles import LearnerPreferences, LearnerProfile


FIXTURE = (
    Path(__file__).parent
    / "fixtures/guides/feedback-loops.personalized.guide.json"
)


def guide():
    return normalize_guide(parse_guide(FIXTURE.read_bytes()))


def profile(**changes: object) -> LearnerProfile:
    return replace(
        LearnerProfile(id="synthetic-profile", target_learner="Synthetic cohort"),
        **changes,
    )


def test_authoritative_goals_are_positional_and_duplicate_text_stays_distinct() -> None:
    goals = authoritative_goals(
        profile(learning_goals=("Repeat this synthetic goal", "Repeat this synthetic goal"))
    )

    assert [(goal.goal_id, goal.goal_text) for goal in goals] == [
        ("goal-001", "Repeat this synthetic goal"),
        ("goal-002", "Repeat this synthetic goal"),
    ]


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({}, ()),
        ({"current_skill_level": "novice"}, ("prior_knowledge",)),
        ({"preferred_examples": ("synthetic gardens",)}, ("interests_examples",)),
        ({"pace": "deliberate"}, ("pacing",)),
        ({"assessment_styles": ("short answer",)}, ("assessment_preferences",)),
        ({"accessibility_constraints": ("synthetic captions",)}, ("accessibility",)),
        (
            {
                "prior_experience": "synthetic experience",
                "examples_to_avoid": ("synthetic finance",),
                "time_budget": "30 minutes",
                "learning_preferences": LearnerPreferences(
                    review_style=("spaced",),
                    attention_constraints=("short sections",),
                ),
                "accessibility_constraints": ("captions",),
            },
            ACTIVE_FACET_IDS,
        ),
    ],
)
def test_active_facets_are_exact_and_in_frozen_order(
    changes: dict[str, object], expected: tuple[str, ...]
) -> None:
    assert active_personalization_facets(profile(**changes)) == expected


@pytest.mark.parametrize(
    ("facet_id", "changes"),
    [
        ("prior_knowledge", {"prior_education": "synthetic education"}),
        ("prior_knowledge", {"prior_experience": "synthetic experience"}),
        ("prior_knowledge", {"professional_experience": "synthetic profession"}),
        ("prior_knowledge", {"current_skill_level": "novice"}),
        ("prior_knowledge", {"adjacent_domains": ("synthetic domain",)}),
        ("prior_knowledge", {"math_comfort": "algebra"}),
        (
            "prior_knowledge",
            {"learning_preferences": LearnerPreferences(common_sticking_points=("loops",))},
        ),
        ("interests_examples", {"adjacent_domains": ("synthetic domain",)}),
        ("interests_examples", {"preferred_examples": ("synthetic garden",)}),
        ("interests_examples", {"examples_to_avoid": ("synthetic finance",)}),
        ("pacing", {"reading_level": "technical"}),
        ("pacing", {"pace": "deliberate"}),
        ("pacing", {"desired_depth": "deep"}),
        ("pacing", {"time_budget": "30 minutes"}),
        ("pacing", {"tone_preference": "concise"}),
        (
            "pacing",
            {"learning_preferences": LearnerPreferences(preferred_modalities=("visual",))},
        ),
        (
            "pacing",
            {"learning_preferences": LearnerPreferences(explanation_style="Socratic")},
        ),
        (
            "pacing",
            {"learning_preferences": LearnerPreferences(preferred_visual_aids=("diagram",))},
        ),
        (
            "pacing",
            {"learning_preferences": LearnerPreferences(diagram_frequency="often")},
        ),
        (
            "pacing",
            {"learning_preferences": LearnerPreferences(interaction_style="guided")},
        ),
        (
            "pacing",
            {"learning_preferences": LearnerPreferences(attention_constraints=("short",))},
        ),
        ("assessment_preferences", {"assessment_styles": ("short answer",)}),
        (
            "assessment_preferences",
            {"learning_preferences": LearnerPreferences(practice_style=("retrieval",))},
        ),
        (
            "assessment_preferences",
            {"learning_preferences": LearnerPreferences(feedback_style="immediate")},
        ),
        (
            "assessment_preferences",
            {"learning_preferences": LearnerPreferences(worked_example_preference="faded")},
        ),
        (
            "assessment_preferences",
            {"learning_preferences": LearnerPreferences(review_style=("spaced",))},
        ),
        ("accessibility", {"accessibility_constraints": ("captions",)}),
    ],
)
def test_every_facet_contributing_field_activates_its_exact_facet(
    facet_id: str, changes: dict[str, object]
) -> None:
    active = active_personalization_facets(profile(**changes))

    if changes.keys() == {"adjacent_domains"}:
        assert active == ("prior_knowledge", "interests_examples")
    else:
        assert active == (facet_id,)


def test_annotation_index_preserves_legal_service_exclusions_and_flags_only_duplicates() -> None:
    source = guide()
    first_module = source.modules[0]
    second_module = source.modules[1]
    source = replace(
        source,
        outcomes=(
            replace(source.outcomes[0], serves_goals=("goal-001", "goal-001", "goal-999")),
            replace(source.outcomes[1], serves_goals=("goal-001",)),
        ),
        modules=(
            replace(first_module, serves_goals=("goal-001", "goal-002")),
            replace(second_module, serves_goals=("goal-001",)),
        ),
        course=replace(
            source.course,
            goal_exclusions=(
                GoalExclusion("goal-001", "Synthetic service and exclusion coexist."),
                GoalExclusion("goal-002", "Synthetic first reason."),
                GoalExclusion("goal-002", "Synthetic duplicate record."),
                GoalExclusion("goal-998", "Synthetic dangling exclusion."),
            ),
        ),
    )

    indexed = index_personalization_annotations(
        source,
        authoritative_goals(profile(learning_goals=("One", "Two"))),
    )

    goal_one = indexed.goals[0]
    assert goal_one.serving_module_ids == tuple(sorted((first_module.id, second_module.id)))
    assert goal_one.serving_outcome_ids == tuple(
        sorted((source.outcomes[0].id, source.outcomes[1].id))
    )
    assert goal_one.exclusions == (
        GoalExclusion("goal-001", "Synthetic service and exclusion coexist."),
    )
    assert [(item.code, item.element_kind, item.element_id, item.goal_id) for item in indexed.violations] == [
        ("duplicate_goal_ref", "outcome", source.outcomes[0].id, "goal-001"),
        ("dangling_goal_ref", "outcome", source.outcomes[0].id, "goal-999"),
        ("duplicate_goal_ref", "exclusion", "course", "goal-002"),
        ("dangling_goal_ref", "exclusion", "course", "goal-998"),
    ]


def test_trace_bytes_are_deterministic_across_semantically_irrelevant_orders() -> None:
    source = guide()
    learner = profile(
        learning_goals=("Synthetic goal one", "Synthetic goal two", "Synthetic goal three"),
        current_skill_level="novice",
        preferred_examples=("gardens",),
    )
    expected = build_personalization_trace(
        source,
        learner,
        guide_sha256="a" * 64,
        profile_snapshot_sha256="b" * 64,
    )
    reordered = replace(
        source,
        outcomes=tuple(reversed(source.outcomes)),
        modules=tuple(
            replace(module, serves_goals=tuple(reversed(module.serves_goals)))
            for module in reversed(source.modules)
        ),
        course=replace(
            source.course,
            goal_exclusions=tuple(reversed(source.course.goal_exclusions)),
        ),
    )
    actual = build_personalization_trace(
        reordered,
        learner,
        guide_sha256="a" * 64,
        profile_snapshot_sha256="b" * 64,
    )

    assert canonical_personalization_trace_bytes(actual) == canonical_personalization_trace_bytes(expected)
    payload = json.loads(canonical_personalization_trace_bytes(expected))
    reparsed = parse_personalization_trace(dict(reversed(tuple(payload.items()))))
    assert canonical_personalization_trace_bytes(reparsed) == canonical_personalization_trace_bytes(expected)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: {**value, "private_extra": "must reject"},
        lambda value: {**value, "schema_version": 99},
        lambda value: {**value, "guide_sha256": "not-a-hash"},
        lambda value: {**value, "active_facets": ["invented"]},
        lambda value: {**value, "goals": [{**value["goals"][0], "goal_id": "goal-002"}] + value["goals"][1:]},
        lambda value: {**value, "goals": [{**value["goals"][0], "serving_module_ids": ["bad id"]}] + value["goals"][1:]},
        lambda value: {**value, "goals": [{**value["goals"][0], "unknown": True}] + value["goals"][1:]},
    ],
)
def test_trace_parser_strictly_rejects_malformed_or_unknown_content(mutation) -> None:
    trace = build_personalization_trace(
        guide(),
        profile(learning_goals=("Private synthetic goal",)),
        guide_sha256="a" * 64,
        profile_snapshot_sha256="b" * 64,
    )
    value = json.loads(canonical_personalization_trace_bytes(trace))

    with pytest.raises(PersonalizationTraceError):
        parse_personalization_trace(mutation(value))

    with pytest.raises(PersonalizationTraceError, match="invalid personalization trace JSON"):
        parse_personalization_trace(b'{"goals": [PRIVATE SECRET}')


def test_safe_projection_excludes_goal_text_reasons_and_private_trace_hash() -> None:
    private_goal = "PLANTED PRIVATE GOAL DELTA"
    private_reason = "PLANTED PRIVATE EXCLUSION REASON EPSILON"
    source = guide()
    source = replace(
        source,
        course=replace(
            source.course,
            goal_exclusions=(GoalExclusion("goal-001", private_reason),),
        ),
    )
    trace = build_personalization_trace(
        source,
        profile(learning_goals=(private_goal,)),
        guide_sha256="a" * 64,
        profile_snapshot_sha256="b" * 64,
    )
    private_hash = hashlib.sha256(canonical_personalization_trace_bytes(trace)).hexdigest()

    projected = safe_personalization_trace_projection(
        trace,
        safe_finding_ids=("personalization.goal_uncovered", "personalization.goal_uncovered"),
    )
    rendered = json.dumps(projected, sort_keys=True)

    assert projected["schema_version"] == PERSONALIZATION_TRACE_SCHEMA_VERSION
    assert projected["goal_count"] == 1
    assert projected["covered_goal_count"] == 1
    assert projected["goals"][0] == {
        "goal_id": "goal-001",
        "serving_module_ids": list(trace.goals[0].serving_module_ids),
        "serving_outcome_ids": list(trace.goals[0].serving_outcome_ids),
        "excluded": True,
    }
    assert projected["safe_finding_ids"] == ["personalization.goal_uncovered"]
    assert private_goal not in rendered
    assert private_reason not in rendered
    assert private_hash not in rendered
    assert "profile_snapshot_sha256" not in rendered
    assert "guide_sha256" not in rendered
    assert "active_facets" not in rendered
    assert safe_personalization_trace_sha256(trace) == safe_personalization_trace_sha256(trace)

    with pytest.raises(PersonalizationTraceError, match="safe_finding_ids"):
        safe_personalization_trace_projection(
            trace,
            safe_finding_ids=("PLANTED PRIVATE FINDING PAYLOAD",),
        )

    with pytest.raises(PersonalizationTraceError, match="safe_finding_ids"):
        safe_personalization_trace_projection(
            trace,
            safe_finding_ids=("personalization.planted_private_payload",),
        )

    with pytest.raises(PersonalizationTraceError, match="safe_finding_ids"):
        safe_personalization_trace_projection(
            trace,
            safe_finding_ids=([],),  # type: ignore[arg-type]
        )


def test_safe_projection_fully_validates_caller_constructed_trace_before_emitting() -> None:
    planted_private_id = "PLANTED PRIVATE ELEMENT ID"
    trace = PersonalizationTrace(
        schema_version=PERSONALIZATION_TRACE_SCHEMA_VERSION,
        guide_sha256="a" * 64,
        profile_snapshot_sha256="b" * 64,
        goals=(
            PersonalizationGoalTrace(
                goal_id="goal-001",
                goal_text="Private synthetic goal",
                serving_module_ids=(planted_private_id,),
            ),
        ),
    )

    with pytest.raises(PersonalizationTraceError):
        safe_personalization_trace_projection(trace)


def test_safe_canonical_bytes_and_hash_bind_exact_safe_finding_ids() -> None:
    trace = build_personalization_trace(
        guide(),
        profile(learning_goals=("Private synthetic goal",)),
        guide_sha256="a" * 64,
        profile_snapshot_sha256="b" * 64,
    )
    first_ids = ("personalization.goal_uncovered",)
    second_ids = ("personalization.no_annotations",)

    first_bytes = canonical_safe_personalization_trace_bytes(
        trace, safe_finding_ids=first_ids
    )
    second_bytes = canonical_safe_personalization_trace_bytes(
        trace, safe_finding_ids=second_ids
    )

    assert first_bytes != second_bytes
    assert safe_personalization_trace_sha256(
        trace, safe_finding_ids=first_ids
    ) == hashlib.sha256(first_bytes).hexdigest()
    assert safe_personalization_trace_sha256(
        trace, safe_finding_ids=second_ids
    ) == hashlib.sha256(second_bytes).hexdigest()


def test_trace_integrity_rule_id_is_safe_projectable() -> None:
    trace = build_personalization_trace(
        guide(),
        profile(learning_goals=("Private synthetic goal",)),
        guide_sha256="a" * 64,
        profile_snapshot_sha256="b" * 64,
    )
    projected = safe_personalization_trace_projection(
        trace,
        safe_finding_ids=("personalization.trace_integrity",),
    )
    assert projected["safe_finding_ids"] == ["personalization.trace_integrity"]


def test_trace_freshness_requires_exact_rebuilt_canonical_content() -> None:
    trace = build_personalization_trace(
        guide(),
        profile(learning_goals=("Synthetic goal",)),
        guide_sha256="a" * 64,
        profile_snapshot_sha256="b" * 64,
    )

    assert personalization_trace_is_fresh(trace, expected_trace=trace)
    assert personalization_trace_is_fresh(
        canonical_personalization_trace_bytes(trace), expected_trace=trace
    )

    changed_bindings = replace(trace, guide_sha256="c" * 64)
    changed_content = replace(
        trace,
        goals=(replace(trace.goals[0], serving_module_ids=("different-module",)),),
    )
    changed_private_text = replace(
        trace,
        goals=(replace(trace.goals[0], goal_text="Different private goal"),),
    )
    assert not personalization_trace_is_fresh(changed_bindings, expected_trace=trace)
    assert not personalization_trace_is_fresh(changed_content, expected_trace=trace)
    assert not personalization_trace_is_fresh(changed_private_text, expected_trace=trace)


def test_canonical_bytes_match_in_independent_workspaces(tmp_path: Path) -> None:
    payload = {
        "schema_version": PERSONALIZATION_TRACE_SCHEMA_VERSION,
        "guide_sha256": "a" * 64,
        "profile_snapshot_sha256": "b" * 64,
        "active_facets": ["assessment_preferences", "prior_knowledge"],
        "goals": [
            {
                "goal_id": "goal-001",
                "goal_text": "Private synthetic goal",
                "serving_module_ids": ["module-z", "module-a"],
                "serving_outcome_ids": ["outcome-z", "outcome-a"],
                "exclusions": [
                    {"goal_id": "goal-001", "reason": "Private synthetic reason"}
                ],
            }
        ],
    }
    script = (
        "import json,sys; "
        "from education_pipeline.guides.personalization import "
        "parse_personalization_trace,canonical_personalization_trace_bytes; "
        "sys.stdout.buffer.write(canonical_personalization_trace_bytes("
        "parse_personalization_trace(json.loads(sys.stdin.read()))))"
    )
    outputs = []
    root = Path(__file__).parents[1]
    for seed in ("11", "97"):
        workspace = tmp_path / seed
        workspace.mkdir()
        env = {**os.environ, "PYTHONHASHSEED": seed, "PYTHONPATH": str(root)}
        result = subprocess.run(
            [sys.executable, "-c", script],
            input=json.dumps(payload).encode(),
            cwd=workspace,
            env=env,
            capture_output=True,
            check=True,
        )
        outputs.append(result.stdout)

    assert outputs[0] == outputs[1]
    assert outputs[0].endswith(b"\n") and not outputs[0].endswith(b"\n\n")
