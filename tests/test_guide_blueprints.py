"""Registry-integrity and recommendation tests for pedagogical blueprints."""

import re

import pytest

from education_pipeline.config import ConfigError
from education_pipeline.guides.blueprints import (
    Blueprint,
    RECOMMENDATION_RULES,
    get_blueprint,
    list_blueprints,
    recommend_blueprint,
)
from education_pipeline.guides.contract import REQUIRED_INTERACTION_TYPES
from education_pipeline.topics import Topic


PRD_BLUEPRINT_IDS = (
    "conceptual-foundations",
    "procedural-skill",
    "casebook",
    "quantitative-scientific",
    "exam-preparation",
    "project-based",
)

_ID_RE = re.compile(r"^[a-z][a-z0-9-]{0,63}$")

_VALID_DIFFICULTIES = {"introductory", "intermediate", "advanced", "mixed"}


def test_registry_contains_exactly_the_six_prd_blueprints_in_stable_order() -> None:
    assert tuple(blueprint.id for blueprint in list_blueprints()) == PRD_BLUEPRINT_IDS


def test_registry_integrity() -> None:
    blueprints = list_blueprints()
    ids = [blueprint.id for blueprint in blueprints]
    assert len(ids) == len(set(ids))
    for blueprint in blueprints:
        assert isinstance(blueprint, Blueprint)
        assert _ID_RE.match(blueprint.id)
        assert blueprint.title.strip()
        assert blueprint.summary.strip()
        assert blueprint.when_to_use.strip()
        assert blueprint.required_interactions
        assert blueprint.required_interactions <= REQUIRED_INTERACTION_TYPES
        assert blueprint.default_difficulty in _VALID_DIFFICULTIES
        assert blueprint.source_policy.strip()
        for lines in (
            blueprint.spec_lines,
            blueprint.outline_lines,
            blueprint.draft_lines,
            blueprint.qa_rubric_lines,
            blueprint.repair_lines,
        ):
            assert lines, f"{blueprint.id} has an empty prompt-line tuple"
            assert all(isinstance(line, str) and line.strip() for line in lines)


def test_blueprint_minimum_interactions_match_the_spec_table() -> None:
    expected = {
        "conceptual-foundations": {"knowledge_check", "reflection"},
        "procedural-skill": {"worked_reveal", "knowledge_check"},
        "casebook": {"scenario", "reflection"},
        "quantitative-scientific": {"worked_reveal", "knowledge_check"},
        "exam-preparation": {"knowledge_check", "worked_reveal"},
        "project-based": {"scenario", "reflection"},
    }
    for blueprint_id, minimum in expected.items():
        assert get_blueprint(blueprint_id).required_interactions == frozenset(minimum)


def test_get_blueprint_rejects_unregistered_id() -> None:
    with pytest.raises(ConfigError, match="unregistered blueprint"):
        get_blueprint("socratic-method")


def test_source_policy_split_matches_prd_open_question_six() -> None:
    required = {"casebook", "quantitative-scientific", "exam-preparation"}
    for blueprint in list_blueprints():
        policy = blueprint.source_policy.lower()
        if blueprint.id in required:
            assert "required" in policy
        else:
            assert "recommended" in policy


def test_recommendation_keyword_table_is_pinned() -> None:
    """Recommendations only change deliberately: the full table is pinned."""

    assert RECOMMENDATION_RULES == (
        (
            "exam-preparation",
            (
                "exam",
                "certification",
                "certificate",
                "licensure",
                "practice test",
                "multiple-choice",
            ),
        ),
        (
            "quantitative-scientific",
            (
                "compute",
                "calculate",
                "calculation",
                "derive",
                "derivation",
                "equation",
                "units",
                "formula",
                "quantitative",
                "laboratory",
            ),
        ),
        (
            "project-based",
            (
                "deliverable",
                "capstone",
                "prototype",
                "portfolio",
                "build a",
                "hands-on project",
            ),
        ),
        (
            "casebook",
            (
                "case study",
                "case-based",
                "casebook",
                "issue-spotting",
                "fact pattern",
                "precedent",
                "dispute",
            ),
        ),
        (
            "procedural-skill",
            (
                "procedure",
                "step-by-step",
                "workflow",
                "checklist",
                "operate",
                "installation",
                "how-to",
            ),
        ),
    )


def _topic(**kwargs) -> Topic:
    defaults = {"id": "sample-topic", "title": "Sample Topic"}
    defaults.update(kwargs)
    return Topic(**defaults)


def test_recommend_falls_back_to_conceptual_foundations() -> None:
    blueprint_id, rationale = recommend_blueprint(
        _topic(title="Systems Thinking", brief="A public introduction to feedback loops.")
    )
    assert blueprint_id == "conceptual-foundations"
    assert "general conceptual topic" in rationale


@pytest.mark.parametrize(
    ("field", "text", "expected"),
    [
        ("title", "Certification exam readiness", "exam-preparation"),
        ("brief", "Learn to derive the governing equation.", "quantitative-scientific"),
        ("goals", "build a working prototype", "project-based"),
        ("key_questions", "How is a fact pattern analyzed?", "casebook"),
        ("constraints", "follow the installation checklist", "procedural-skill"),
    ],
)
def test_recommend_matches_signals_in_each_scanned_field(
    field: str, text: str, expected: str
) -> None:
    value: object = (text,) if field in {"goals", "key_questions", "constraints"} else text
    blueprint_id, rationale = recommend_blueprint(_topic(**{field: value}))
    assert blueprint_id == expected
    assert rationale.strip()


def test_recommend_is_case_insensitive() -> None:
    blueprint_id, _ = recommend_blueprint(_topic(brief="Preparing for the EXAM season."))
    assert blueprint_id == "exam-preparation"


def test_recommend_priority_follows_table_order() -> None:
    blueprint_id, _ = recommend_blueprint(
        _topic(brief="Build a study plan for the certification exam.")
    )
    assert blueprint_id == "exam-preparation"


def test_recommend_ignores_unscanned_fields() -> None:
    """Only title, brief, goals, key_questions, and constraints are scanned."""

    blueprint_id, _ = recommend_blueprint(_topic(notes="exam", audience="exam takers"))
    assert blueprint_id == "conceptual-foundations"


def test_recommend_matches_whole_words_only() -> None:
    """"example" must not trigger the "exam" signal."""

    blueprint_id, _ = recommend_blueprint(
        _topic(brief="Uses concrete examples throughout.")
    )
    assert blueprint_id == "conceptual-foundations"


def test_recommend_rationale_is_one_sentence_and_names_the_signal() -> None:
    _, rationale = recommend_blueprint(_topic(brief="certification exam"))
    assert rationale.count(".") == 1
    assert rationale.endswith(".")
    assert "exam" in rationale
