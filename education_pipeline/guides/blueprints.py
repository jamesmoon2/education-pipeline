"""Application-owned pedagogical blueprint registry and recommender.

Six blueprints (PRD section 7.3) ship in maintained source code. A blueprint
is configuration for one engine — parameterized prompt lines, a minimum
required-interaction set, a default difficulty, and a source policy — never a
forked runtime. All prompt-line content is domain-neutral: lines describe
pedagogy, never subject matter (see ``docs/extraction-manifest.md``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from education_pipeline.config import ConfigError
from education_pipeline.topics import Topic


@dataclass(frozen=True)
class Blueprint:
    id: str
    title: str
    summary: str
    when_to_use: str
    required_interactions: frozenset[str]
    default_difficulty: str
    source_policy: str
    spec_lines: tuple[str, ...]
    outline_lines: tuple[str, ...]
    draft_lines: tuple[str, ...]
    qa_rubric_lines: tuple[str, ...]
    repair_lines: tuple[str, ...]


_BLUEPRINTS: tuple[Blueprint, ...] = (
    Blueprint(
        id="conceptual-foundations",
        title="Conceptual foundations",
        summary="Builds a mental model of core concepts and how they relate.",
        when_to_use=(
            "Choose when the goal is understanding ideas, theories, or systems "
            "rather than performing a task."
        ),
        required_interactions=frozenset({"knowledge_check", "reflection"}),
        default_difficulty="introductory",
        source_policy=(
            "Sources are recommended for factual claims that are not common "
            "knowledge, but not required."
        ),
        spec_lines=(
            "Anchor the specification in a small set of core concepts and the "
            "relationships between them.",
            "Plan to surface and correct common misconceptions explicitly.",
            "Plan reflection points that ask the learner to connect concepts to "
            "their own context.",
        ),
        outline_lines=(
            "Order modules from foundational concepts to their combinations; "
            "never use a concept before the module that teaches it.",
            "Give every module at least one knowledge check and one reflection "
            "point.",
        ),
        draft_lines=(
            "Introduce each concept with a definition, a contrast with what it "
            "is not, and a concrete example.",
            "Write knowledge checks that test understanding of the concept, not "
            "recall of its wording.",
            "Close modules with a reflection prompt that connects the concepts "
            "to the learner's context.",
        ),
        qa_rubric_lines=(
            "Each core concept is defined, contrasted, and exemplified before "
            "it is used.",
            "Knowledge checks test conceptual understanding rather than "
            "verbatim recall.",
            "Reflection prompts ask the learner to connect concepts to their "
            "own context.",
        ),
        repair_lines=(
            "Preserve the concept sequencing; a repaired module must not use a "
            "concept before the module that teaches it.",
        ),
    ),
    Blueprint(
        id="procedural-skill",
        title="Procedural skill",
        summary="Teaches repeatable procedures through worked, replayable sequences.",
        when_to_use="Choose when the learner must reliably perform a multi-step task.",
        required_interactions=frozenset({"worked_reveal", "knowledge_check"}),
        default_difficulty="intermediate",
        source_policy=(
            "Sources are recommended for factual claims that are not common "
            "knowledge, but not required."
        ),
        spec_lines=(
            "Design the course around procedures the learner will perform, not "
            "descriptions of them.",
            "Every procedure must be presented as a complete, numbered worked "
            "sequence the learner can replay.",
        ),
        outline_lines=(
            "Sequence modules so each procedure's prerequisites are practiced "
            "before the procedures that depend on them.",
            "Give every module at least one worked, replayable procedure and a "
            "knowledge check on when to apply it.",
        ),
        draft_lines=(
            "Present every procedure as a complete, ordered, replayable "
            "sequence of steps with the expected result of each step.",
            "State when to use each procedure and the observable signs that a "
            "step went wrong.",
        ),
        qa_rubric_lines=(
            "Procedures are complete, ordered, and replayable without missing "
            "steps.",
            "Each procedure states when to apply it and how to recognize "
            "failure.",
            "Worked reveals walk the full procedure step by step, not a summary "
            "of it.",
        ),
        repair_lines=(
            "Repaired procedures must remain complete, ordered, and replayable; "
            "never compress steps away.",
        ),
    ),
    Blueprint(
        id="casebook",
        title="Casebook",
        summary="Develops judgment by analyzing realistic decision situations.",
        when_to_use=(
            "Choose when the goal is applying rules or judgment to varied fact "
            "patterns."
        ),
        required_interactions=frozenset({"scenario", "reflection"}),
        default_difficulty="intermediate",
        source_policy=(
            "Sources are required for factual claims that are not common "
            "knowledge."
        ),
        spec_lines=(
            "Design the course around realistic decision situations the learner "
            "must analyze.",
            "Plan decision points with defensible alternatives, not obviously "
            "wrong distractors.",
        ),
        outline_lines=(
            "Give every module at least one scenario with a realistic fact "
            "pattern and a debriefed decision point.",
            "Sequence cases from single-issue to multi-issue analysis.",
        ),
        draft_lines=(
            "Write scenario fact patterns that are realistic and "
            "self-contained, including the facts needed to decide.",
            "Make every scenario choice defensible enough that a careless "
            "reader could pick it, and explain in the debrief why the best "
            "choice wins.",
            "End each case with a reflection on how the reasoning transfers to "
            "new facts.",
        ),
        qa_rubric_lines=(
            "Fact patterns are realistic and contain the facts needed to "
            "decide.",
            "Decision points have defensible distractors, and debriefs explain "
            "why the best choice wins.",
            "Reflections ask the learner to transfer the reasoning to new "
            "situations.",
        ),
        repair_lines=(
            "Repaired scenarios must keep realistic fact patterns and "
            "defensible distractors.",
        ),
    ),
    Blueprint(
        id="quantitative-scientific",
        title="Quantitative and scientific practice",
        summary="Builds quantitative skill through fully worked computations.",
        when_to_use=(
            "Choose when the learner must set up, compute, and interpret "
            "quantitative results."
        ),
        required_interactions=frozenset({"worked_reveal", "knowledge_check"}),
        default_difficulty="intermediate",
        source_policy=(
            "Sources are required for factual claims that are not common "
            "knowledge."
        ),
        spec_lines=(
            "Design the course around quantitative reasoning: setting up, "
            "computing, and interpreting results.",
            "Every computation must be worked step by step with units carried "
            "through.",
        ),
        outline_lines=(
            "Give every module at least one fully worked computation and a "
            "knowledge check on interpreting the result.",
            "Sequence modules so required mathematical tools are practiced "
            "before they are combined.",
        ),
        draft_lines=(
            "Work every computation step by step, carrying units through each "
            "step and stating the final result with units.",
            "Show the setup (what is known, what is asked) before the "
            "computation, and interpret the result after it.",
            "Include practice items with worked answers, not answer keys "
            "alone.",
        ),
        qa_rubric_lines=(
            "Every computation is worked step by step with units carried "
            "through.",
            "Setups state what is known and what is asked before computing.",
            "Results are interpreted, and practice items include worked "
            "answers.",
        ),
        repair_lines=(
            "Repaired computations must stay fully worked with units carried "
            "through every step.",
        ),
    ),
    Blueprint(
        id="exam-preparation",
        title="Exam preparation",
        summary="Prepares for a specific assessment with format-matched practice.",
        when_to_use="Choose when success is measured by an exam or certification.",
        required_interactions=frozenset({"knowledge_check", "worked_reveal"}),
        default_difficulty="intermediate",
        source_policy="Sources are required for the rules and facts being tested.",
        spec_lines=(
            "Design the course around the assessment: what is tested, in what "
            "format, and how it is scored.",
            "Practice items must match the assessment format, and every answer "
            "needs a rationale.",
        ),
        outline_lines=(
            "Give every module practice items in the assessment's format with "
            "rationales for right and wrong answers.",
            "Allocate module time in proportion to how heavily each area is "
            "tested.",
        ),
        draft_lines=(
            "Write practice items that match the assessment format, and give "
            "every answer choice a rationale.",
            "Teach recognition of common traps and time-management tactics "
            "alongside the content.",
            "Include a worked walkthrough of at least one representative item "
            "per module.",
        ),
        qa_rubric_lines=(
            "Practice items match the assessment format.",
            "Every answer choice has a rationale, including the wrong ones.",
            "Common traps and pacing guidance are covered where relevant.",
        ),
        repair_lines=(
            "Repaired practice items must keep the assessment format and "
            "per-answer rationales.",
        ),
    ),
    Blueprint(
        id="project-based",
        title="Project-based learning",
        summary="Builds skill by shipping one concrete deliverable step by step.",
        when_to_use=(
            "Choose when the goal is producing a tangible artifact or portfolio "
            "piece."
        ),
        required_interactions=frozenset({"scenario", "reflection"}),
        default_difficulty="intermediate",
        source_policy=(
            "Sources are recommended for factual claims that are not common "
            "knowledge, but not required."
        ),
        spec_lines=(
            "Design the course around one concrete deliverable the learner "
            "builds across the modules.",
            "Every module must advance the deliverable with a checkable "
            "milestone.",
        ),
        outline_lines=(
            "Order modules as milestones of the deliverable; each module ends "
            "with a checkable increment.",
            "Give every module a scenario or decision point drawn from building "
            "the deliverable.",
        ),
        draft_lines=(
            "Advance the deliverable in every module and end with a milestone "
            "the learner can check.",
            "Frame scenarios around real decisions that arise while building "
            "the deliverable.",
            "Close modules with a reflection on how the milestone fits the "
            "finished deliverable.",
        ),
        qa_rubric_lines=(
            "Modules advance a concrete deliverable with checkable milestones.",
            "Scenarios reflect real decisions from building the deliverable.",
            "The finished deliverable is fully assembled by the final module.",
        ),
        repair_lines=(
            "A repaired module must still advance the deliverable and end with "
            "its checkable milestone.",
        ),
    ),
)

_BLUEPRINTS_BY_ID = {blueprint.id: blueprint for blueprint in _BLUEPRINTS}

#: Deterministic recommendation signals, scanned in priority order over a
#: topic's title, brief, goals, key_questions, and constraints. Keywords match
#: whole words/phrases only. Pinned by a test so recommendations change only
#: deliberately.
RECOMMENDATION_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
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

_FALLBACK_RATIONALE = (
    "Recommended Conceptual foundations for a general conceptual topic."
)


def get_blueprint(blueprint_id: str) -> Blueprint:
    """Return the registered blueprint for ``blueprint_id``.

    Raises :class:`ConfigError` for an unregistered id.
    """

    blueprint = _BLUEPRINTS_BY_ID.get(blueprint_id)
    if blueprint is None:
        known = ", ".join(sorted(_BLUEPRINTS_BY_ID))
        raise ConfigError(
            f"unregistered blueprint {blueprint_id!r}; registered blueprints: {known}"
        )
    return blueprint


def list_blueprints() -> tuple[Blueprint, ...]:
    """Return the registered blueprints in stable PRD order."""

    return _BLUEPRINTS


def recommend_blueprint(topic: Topic) -> tuple[str, str]:
    """Deterministically recommend a blueprint id for ``topic`` with a rationale.

    Pure keyword/field heuristics over the topic's title, brief, goals,
    key_questions, and constraints; falls back to ``conceptual-foundations``
    when nothing matches.
    """

    scanned = " ".join(
        (
            topic.title,
            topic.brief or "",
            " ".join(topic.goals),
            " ".join(topic.key_questions),
            " ".join(topic.constraints),
        )
    ).lower()
    for blueprint_id, keywords in RECOMMENDATION_RULES:
        for keyword in keywords:
            if re.search(rf"\b{re.escape(keyword)}\b", scanned):
                title = _BLUEPRINTS_BY_ID[blueprint_id].title
                return blueprint_id, (
                    f"Recommended {title} because the topic mentions {keyword!r}."
                )
    return "conceptual-foundations", _FALLBACK_RATIONALE
