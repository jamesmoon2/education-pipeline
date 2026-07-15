"""Pure deterministic personalization goal, annotation, and trace helpers.

The private trace deliberately contains learner-authored goal text and exclusion
reasons.  Callers must use :func:`safe_personalization_trace_projection` for
any public report or export surface.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
import hashlib
import json
import re
from typing import Any

from education_pipeline.profiles import LearnerProfile

from .model import GoalExclusion, Guide
from .parse import GOAL_ID_RE, ID_RE


PERSONALIZATION_TRACE_SCHEMA_VERSION = 1
ACTIVE_FACET_IDS = (
    "prior_knowledge",
    "interests_examples",
    "pacing",
    "assessment_preferences",
    "accessibility",
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}\Z")
SAFE_PERSONALIZATION_FINDING_IDS = (
    "personalization.goal_uncovered",
    "personalization.no_annotations",
    "personalization.dangling_goal_ref",
    "personalization.duplicate_goal_ref",
    "personalization.unexpected_annotations",
    "personalization.no_profile",
)
_SAFE_PERSONALIZATION_FINDING_ID_SET = frozenset(SAFE_PERSONALIZATION_FINDING_IDS)
_TRACE_KEYS = {
    "schema_version",
    "guide_sha256",
    "profile_snapshot_sha256",
    "goals",
    "active_facets",
}
_GOAL_TRACE_KEYS = {
    "goal_id",
    "goal_text",
    "serving_module_ids",
    "serving_outcome_ids",
    "exclusions",
}
_EXCLUSION_KEYS = {"goal_id", "reason"}


class PersonalizationTraceError(ValueError):
    """Raised when a private personalization trace is structurally invalid."""


@dataclass(frozen=True)
class AuthoritativeGoal:
    goal_id: str
    goal_text: str


@dataclass(frozen=True)
class PersonalizationGoalTrace:
    goal_id: str
    goal_text: str
    serving_module_ids: tuple[str, ...] = ()
    serving_outcome_ids: tuple[str, ...] = ()
    exclusions: tuple[GoalExclusion, ...] = ()

    @property
    def covered(self) -> bool:
        """Whether service or a valid explicit exclusion accounts for the goal."""

        return bool(
            self.serving_module_ids or self.serving_outcome_ids or self.exclusions
        )


@dataclass(frozen=True)
class AnnotationViolation:
    code: str
    element_kind: str
    element_id: str
    goal_id: str


@dataclass(frozen=True)
class PersonalizationAnnotationIndex:
    goals: tuple[PersonalizationGoalTrace, ...]
    violations: tuple[AnnotationViolation, ...] = ()


@dataclass(frozen=True)
class PersonalizationTrace:
    schema_version: int
    guide_sha256: str
    profile_snapshot_sha256: str
    goals: tuple[PersonalizationGoalTrace, ...]
    active_facets: tuple[str, ...] = ()


def authoritative_goals(
    profile_or_goals: LearnerProfile | Sequence[str],
) -> tuple[AuthoritativeGoal, ...]:
    """Assign stable opaque ids to immutable profile goals by position."""

    values = (
        profile_or_goals.learning_goals
        if isinstance(profile_or_goals, LearnerProfile)
        else profile_or_goals
    )
    return tuple(
        AuthoritativeGoal(goal_id=f"goal-{position:03d}", goal_text=text)
        for position, text in enumerate(values, start=1)
    )


def active_personalization_facets(profile: LearnerProfile) -> tuple[str, ...]:
    """Return active non-goal audit facets in the frozen display order."""

    preferences = profile.learning_preferences
    active = {
        "prior_knowledge": any(
            (
                profile.prior_education,
                profile.prior_experience,
                profile.professional_experience,
                profile.current_skill_level,
                profile.adjacent_domains,
                profile.math_comfort,
                preferences.common_sticking_points,
            )
        ),
        "interests_examples": any(
            (
                profile.adjacent_domains,
                profile.preferred_examples,
                profile.examples_to_avoid,
            )
        ),
        "pacing": any(
            (
                profile.pace,
                profile.reading_level,
                profile.desired_depth,
                profile.time_budget,
                profile.tone_preference,
                preferences.preferred_modalities,
                preferences.explanation_style,
                preferences.preferred_visual_aids,
                preferences.diagram_frequency,
                preferences.interaction_style,
                preferences.attention_constraints,
            )
        ),
        "assessment_preferences": any(
            (
                profile.assessment_styles,
                preferences.practice_style,
                preferences.feedback_style,
                preferences.worked_example_preference,
                preferences.review_style,
            )
        ),
        "accessibility": bool(profile.accessibility_constraints),
    }
    return tuple(facet_id for facet_id in ACTIVE_FACET_IDS if active[facet_id])


def index_personalization_annotations(
    guide: Guide,
    goals: Sequence[AuthoritativeGoal],
) -> PersonalizationAnnotationIndex:
    """Index source annotations and report only deterministic integrity faults.

    Service from different elements is legal. Repetition inside one element is
    a duplicate, as is more than one exclusion record for the same goal id.
    Dangling references are retained as violations but never added to a goal.
    """

    goal_by_id = {goal.goal_id: goal for goal in goals}
    module_ids: dict[str, set[str]] = {goal_id: set() for goal_id in goal_by_id}
    outcome_ids: dict[str, set[str]] = {goal_id: set() for goal_id in goal_by_id}
    exclusions: dict[str, list[GoalExclusion]] = {
        goal_id: [] for goal_id in goal_by_id
    }
    violations: list[AnnotationViolation] = []

    for outcome in guide.outcomes:
        _index_service_field(
            outcome.serves_goals,
            kind="outcome",
            element_id=outcome.id,
            known_goals=goal_by_id,
            destinations=outcome_ids,
            violations=violations,
        )
    for module in guide.modules:
        _index_service_field(
            module.serves_goals,
            kind="module",
            element_id=module.id,
            known_goals=goal_by_id,
            destinations=module_ids,
            violations=violations,
        )

    exclusion_counts: dict[str, int] = {}
    exclusion_order: list[str] = []
    for exclusion in guide.course.goal_exclusions:
        if exclusion.goal_id not in exclusion_counts:
            exclusion_order.append(exclusion.goal_id)
        exclusion_counts[exclusion.goal_id] = exclusion_counts.get(exclusion.goal_id, 0) + 1
        if exclusion.goal_id in goal_by_id:
            exclusions[exclusion.goal_id].append(exclusion)
    for goal_id in exclusion_order:
        if exclusion_counts[goal_id] > 1:
            violations.append(
                AnnotationViolation("duplicate_goal_ref", "exclusion", "course", goal_id)
            )
    for goal_id in exclusion_order:
        if goal_id not in goal_by_id:
            violations.append(
                AnnotationViolation("dangling_goal_ref", "exclusion", "course", goal_id)
            )

    indexed_goals = tuple(
        PersonalizationGoalTrace(
            goal_id=goal.goal_id,
            goal_text=goal.goal_text,
            serving_module_ids=tuple(sorted(module_ids[goal.goal_id])),
            serving_outcome_ids=tuple(sorted(outcome_ids[goal.goal_id])),
            exclusions=tuple(
                sorted(
                    exclusions[goal.goal_id],
                    key=lambda item: (item.goal_id, item.reason),
                )
            ),
        )
        for goal in goals
    )
    return PersonalizationAnnotationIndex(indexed_goals, tuple(violations))


def build_personalization_trace(
    guide: Guide,
    profile: LearnerProfile,
    *,
    guide_sha256: str,
    profile_snapshot_sha256: str,
) -> PersonalizationTrace:
    """Construct the canonical private trace model without I/O."""

    _require_sha256(guide_sha256, "guide_sha256")
    _require_sha256(profile_snapshot_sha256, "profile_snapshot_sha256")
    indexed = index_personalization_annotations(guide, authoritative_goals(profile))
    return PersonalizationTrace(
        schema_version=PERSONALIZATION_TRACE_SCHEMA_VERSION,
        guide_sha256=guide_sha256,
        profile_snapshot_sha256=profile_snapshot_sha256,
        goals=indexed.goals,
        active_facets=active_personalization_facets(profile),
    )


def parse_personalization_trace(
    source: bytes | str | Mapping[str, Any] | PersonalizationTrace,
) -> PersonalizationTrace:
    """Strictly parse and normalize a private trace without echoing values."""

    if isinstance(source, PersonalizationTrace):
        value: Any = asdict(source)
    elif isinstance(source, (bytes, str)):
        try:
            value = json.loads(source)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PersonalizationTraceError("invalid personalization trace JSON") from exc
    else:
        value = source
    root = _object(value, "trace", _TRACE_KEYS)

    schema_version = root.get("schema_version")
    if type(schema_version) is not int or schema_version != PERSONALIZATION_TRACE_SCHEMA_VERSION:
        raise PersonalizationTraceError("unsupported personalization trace schema_version")
    guide_hash = _sha256(root.get("guide_sha256"), "guide_sha256")
    profile_hash = _sha256(
        root.get("profile_snapshot_sha256"), "profile_snapshot_sha256"
    )

    raw_facets = _array(root.get("active_facets"), "active_facets")
    facets: set[str] = set()
    for item in raw_facets:
        if not isinstance(item, str) or item not in ACTIVE_FACET_IDS:
            raise PersonalizationTraceError("active_facets contains an invalid facet id")
        if item in facets:
            raise PersonalizationTraceError("active_facets contains a duplicate facet id")
        facets.add(item)

    raw_goals = _array(root.get("goals"), "goals")
    parsed_goals: list[PersonalizationGoalTrace] = []
    for position, item in enumerate(raw_goals, start=1):
        goal = _object(item, f"goals[{position - 1}]", _GOAL_TRACE_KEYS)
        goal_id = _goal_id(goal.get("goal_id"), f"goals[{position - 1}].goal_id")
        if goal_id != f"goal-{position:03d}":
            raise PersonalizationTraceError("goals must use authoritative positional ids")
        goal_text = _nonempty_text(goal.get("goal_text"), "goal_text")
        modules = _element_ids(goal.get("serving_module_ids"), "serving_module_ids")
        outcomes = _element_ids(goal.get("serving_outcome_ids"), "serving_outcome_ids")
        parsed_exclusions: list[GoalExclusion] = []
        for raw_exclusion in _array(goal.get("exclusions"), "exclusions"):
            exclusion = _object(raw_exclusion, "exclusion", _EXCLUSION_KEYS)
            exclusion_goal_id = _goal_id(exclusion.get("goal_id"), "exclusion.goal_id")
            if exclusion_goal_id != goal_id:
                raise PersonalizationTraceError("exclusion goal_id must match its goal")
            parsed_exclusions.append(
                GoalExclusion(
                    goal_id=goal_id,
                    reason=_nonempty_text(exclusion.get("reason"), "exclusion.reason"),
                )
            )
        parsed_goals.append(
            PersonalizationGoalTrace(
                goal_id=goal_id,
                goal_text=goal_text,
                serving_module_ids=modules,
                serving_outcome_ids=outcomes,
                exclusions=tuple(
                    sorted(parsed_exclusions, key=lambda item: (item.goal_id, item.reason))
                ),
            )
        )

    return PersonalizationTrace(
        schema_version=schema_version,
        guide_sha256=guide_hash,
        profile_snapshot_sha256=profile_hash,
        goals=tuple(parsed_goals),
        active_facets=tuple(facet for facet in ACTIVE_FACET_IDS if facet in facets),
    )


def personalization_trace_to_dict(trace: PersonalizationTrace) -> dict[str, Any]:
    """Return the private trace JSON value. Keep it on local-only surfaces."""

    return {
        "schema_version": trace.schema_version,
        "guide_sha256": trace.guide_sha256,
        "profile_snapshot_sha256": trace.profile_snapshot_sha256,
        "goals": [
            {
                "goal_id": goal.goal_id,
                "goal_text": goal.goal_text,
                "serving_module_ids": list(goal.serving_module_ids),
                "serving_outcome_ids": list(goal.serving_outcome_ids),
                "exclusions": [
                    {"goal_id": exclusion.goal_id, "reason": exclusion.reason}
                    for exclusion in goal.exclusions
                ],
            }
            for goal in trace.goals
        ],
        "active_facets": list(trace.active_facets),
    }


def canonical_personalization_trace_bytes(trace: PersonalizationTrace) -> bytes:
    """Serialize a private trace to stable canonical UTF-8 JSON bytes."""

    normalized = parse_personalization_trace(personalization_trace_to_dict(trace))
    text = json.dumps(
        personalization_trace_to_dict(normalized),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        separators=(",", ": "),
    )
    return (text + "\n").encode("utf-8")


def personalization_trace_sha256(trace: PersonalizationTrace) -> str:
    """Hash private trace bytes; this value must remain local."""

    return hashlib.sha256(canonical_personalization_trace_bytes(trace)).hexdigest()


def safe_personalization_trace_projection(
    trace: PersonalizationTrace,
    *,
    safe_finding_ids: Sequence[str] = (),
) -> dict[str, Any]:
    """Return the public-safe trace subset, excluding all private text/hashes."""

    normalized = parse_personalization_trace(trace)
    safe_ids: set[str] = set()
    for finding_id in safe_finding_ids:
        if (
            not isinstance(finding_id, str)
            or finding_id not in _SAFE_PERSONALIZATION_FINDING_ID_SET
        ):
            raise PersonalizationTraceError(
                "safe_finding_ids contains an invalid personalization finding id"
            )
        safe_ids.add(finding_id)
    goals = [
        {
            "goal_id": goal.goal_id,
            "serving_module_ids": list(goal.serving_module_ids),
            "serving_outcome_ids": list(goal.serving_outcome_ids),
            "excluded": bool(goal.exclusions),
        }
        for goal in normalized.goals
    ]
    return {
        "schema_version": normalized.schema_version,
        "goal_count": len(goals),
        "covered_goal_count": sum(
            bool(
                goal["serving_module_ids"]
                or goal["serving_outcome_ids"]
                or goal["excluded"]
            )
            for goal in goals
        ),
        "goals": goals,
        "safe_finding_ids": sorted(safe_ids),
    }


def canonical_safe_personalization_trace_bytes(
    trace: PersonalizationTrace,
    *,
    safe_finding_ids: Sequence[str] = (),
) -> bytes:
    """Serialize the public-safe trace projection for hashing/reporting."""

    text = json.dumps(
        safe_personalization_trace_projection(
            trace,
            safe_finding_ids=safe_finding_ids,
        ),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        separators=(",", ": "),
    )
    return (text + "\n").encode("utf-8")


def safe_personalization_trace_sha256(
    trace: PersonalizationTrace,
    *,
    safe_finding_ids: Sequence[str] = (),
) -> str:
    """Hash only the public-safe projection, never the private trace bytes."""

    return hashlib.sha256(
        canonical_safe_personalization_trace_bytes(
            trace,
            safe_finding_ids=safe_finding_ids,
        )
    ).hexdigest()


def personalization_trace_is_fresh(
    trace: bytes | str | Mapping[str, Any] | PersonalizationTrace,
    *,
    expected_trace: bytes | str | Mapping[str, Any] | PersonalizationTrace,
) -> bool:
    """Compare a current trace with the exact deterministically rebuilt trace."""

    try:
        current = parse_personalization_trace(trace)
        expected = parse_personalization_trace(expected_trace)
        return canonical_personalization_trace_bytes(
            current
        ) == canonical_personalization_trace_bytes(expected)
    except PersonalizationTraceError:
        return False


def _index_service_field(
    references: Sequence[str],
    *,
    kind: str,
    element_id: str,
    known_goals: Mapping[str, AuthoritativeGoal],
    destinations: dict[str, set[str]],
    violations: list[AnnotationViolation],
) -> None:
    counts: dict[str, int] = {}
    order: list[str] = []
    for goal_id in references:
        if goal_id not in counts:
            order.append(goal_id)
        counts[goal_id] = counts.get(goal_id, 0) + 1
        if goal_id in known_goals:
            destinations[goal_id].add(element_id)
    for goal_id in order:
        if counts[goal_id] > 1:
            violations.append(
                AnnotationViolation("duplicate_goal_ref", kind, element_id, goal_id)
            )
    for goal_id in order:
        if goal_id not in known_goals:
            violations.append(
                AnnotationViolation("dangling_goal_ref", kind, element_id, goal_id)
            )


def _object(value: Any, path: str, keys: set[str]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PersonalizationTraceError(f"{path} must be an object")
    if any(not isinstance(key, str) for key in value):
        raise PersonalizationTraceError(f"{path} keys must be strings")
    missing = keys - value.keys()
    unknown = value.keys() - keys
    if missing:
        raise PersonalizationTraceError(f"{path} is missing required fields")
    if unknown:
        raise PersonalizationTraceError(f"{path} contains unknown fields")
    return value


def _array(value: Any, path: str) -> Sequence[Any]:
    if not isinstance(value, (list, tuple)):
        raise PersonalizationTraceError(f"{path} must be an array")
    return value


def _nonempty_text(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PersonalizationTraceError(f"{path} must be a non-empty string")
    if value != value.strip():
        raise PersonalizationTraceError(f"{path} must not have surrounding whitespace")
    return value


def _goal_id(value: Any, path: str) -> str:
    if not isinstance(value, str) or GOAL_ID_RE.fullmatch(value) is None:
        raise PersonalizationTraceError(f"{path} must be a valid goal id")
    return value


def _element_ids(value: Any, path: str) -> tuple[str, ...]:
    items = _array(value, path)
    normalized: set[str] = set()
    for item in items:
        if not isinstance(item, str) or ID_RE.fullmatch(item) is None:
            raise PersonalizationTraceError(f"{path} contains an invalid element id")
        if item in normalized:
            raise PersonalizationTraceError(f"{path} contains a duplicate element id")
        normalized.add(item)
    return tuple(sorted(normalized))


def _sha256(value: Any, path: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise PersonalizationTraceError(f"{path} must be a lowercase SHA-256 hex digest")
    return value


def _require_sha256(value: str, path: str) -> None:
    _sha256(value, path)
