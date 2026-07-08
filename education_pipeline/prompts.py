"""Prompt compilation helpers for education pipeline stages."""

from __future__ import annotations

from dataclasses import dataclass

from education_pipeline.config import ConfigError
from education_pipeline.profiles import LearnerProfile, render_profile_prompt_context
from education_pipeline.topics import Topic
from education_pipeline.workspace import ProfileStore


@dataclass(frozen=True)
class PromptArtifact:
    """A compiled prompt artifact ready for preview or file output."""

    stage: str
    topic_id: str
    text: str


@dataclass(frozen=True)
class SpecPromptInput:
    """Inputs needed to compile the spec-stage prompt."""

    topic_id: str
    title: str
    topic_brief: str | None = None
    profile: LearnerProfile | None = None


_SPEC_HEADER_LINES = (
    "# Spec Stage Prompt",
    "",
    "You are designing the course contract for a local-first education pipeline.",
    "Create a durable specification for the topic below.",
    "This is not the lesson draft. It is the planning contract that will guide outline, drafting, QA, repair, and export stages.",
    "",
    "Follow this priority order:",
    "1. System, safety, schema, and runtime instructions.",
    "2. The authoring contract in this prompt.",
    "3. Topic requirements.",
    "4. Learner profile context.",
)

_SPEC_OUTPUT_AND_QUALITY_LINES = (
    "## Output Format",
    "Return markdown with exactly these sections:",
    "1. `# Course Specification: <title>`",
    "2. `## Audience And Context`",
    "3. `## Learning Outcomes`",
    "4. `## Scope`",
    "5. `## Prerequisites`",
    "6. `## Teaching Approach`",
    "7. `## Visual Aid Plan`",
    "8. `## Practice And Assessment Plan`",
    "9. `## Misconceptions And Failure Modes`",
    "10. `## Privacy And Publication Notes`",
    "11. `## Downstream Prompt Notes`",
    "",
    "## Quality Bar",
    "- Write a clear learning contract, not lesson prose.",
    "- Make outcomes observable: use verbs like explain, compare, diagnose, construct, evaluate, or apply.",
    "- Separate in-scope material from exclusions so later stages do not drift.",
    "- Identify prerequisite knowledge and what to briefly remediate.",
    "- Name likely misconceptions, not generic difficulty.",
    "- For visual learners, specify concrete flowcharts, concept maps, timelines, tables, diagrams, or annotated examples when useful.",
    "- Place worked examples, practice, assessment, recap, and review deliberately.",
    "- Keep private learner details out of publishable course text unless explicitly allowed.",
    "- If the learner profile conflicts with safety, schema, runtime, or authoring requirements, follow the higher-priority requirement and note the conflict briefly.",
)

_OUTLINE_HEADER_LINES = (
    "# Outline Stage Prompt",
    "",
    "You are turning an approved course specification into a teachable module outline.",
    "Design the sequence of modules that will be drafted, reviewed, and exported downstream.",
    "This is not the lesson draft. It is the structural plan derived from the approved specification.",
    "",
    "Follow this priority order:",
    "1. System, safety, schema, and runtime instructions.",
    "2. The authoring contract in this prompt.",
    "3. The approved specification.",
    "4. Topic requirements.",
    "5. Learner profile context.",
)

_OUTLINE_OUTPUT_AND_QUALITY_LINES = (
    "## Output Format",
    "Return markdown with exactly these sections:",
    "1. `# Course Outline: <title>`",
    "2. `## Sequence Rationale`",
    "3. `## Modules`",
    "4. `## Coverage Check`",
    "5. `## Downstream Prompt Notes`",
    "",
    "Under `## Modules`, number each module and for each give: outcomes covered, key concepts, planned visual aids, worked examples, and a practice or checkpoint.",
    "",
    "## Quality Bar",
    "- Cover every learning outcome from the approved specification; introduce no out-of-scope material.",
    "- Order modules so prerequisites precede the modules that depend on them.",
    "- Keep each module small enough to draft independently.",
    "- Place visual aids and worked examples where the specification's visual aid plan calls for them.",
    "- In `## Coverage Check`, map each specification outcome to the module that delivers it.",
    "- Flag any gaps or contradictions in the specification instead of silently inventing scope.",
    "- Keep private learner details out of publishable outline text unless explicitly allowed.",
)


def compile_spec_prompt(spec_input: SpecPromptInput) -> PromptArtifact:
    """Compile a deterministic spec-stage prompt from loose topic fields."""

    topic_id = _required_text(spec_input.topic_id, "topic_id")
    title = _required_text(spec_input.title, "title")

    topic_lines = [
        "## Topic",
        f"- Topic id: {topic_id}",
        f"- Title: {title}",
    ]
    if spec_input.topic_brief is not None:
        topic_lines.append(f"- Topic brief: {_required_text(spec_input.topic_brief, 'topic_brief')}")

    lines = [*_SPEC_HEADER_LINES, "", *topic_lines, "", *_SPEC_OUTPUT_AND_QUALITY_LINES]
    return _finalize("spec", topic_id, lines, spec_input.profile)


def compile_topic_spec_prompt(
    topic: Topic,
    profile: LearnerProfile | None = None,
) -> PromptArtifact:
    """Compile a spec-stage prompt from a structured :class:`Topic`."""

    topic_id, topic_lines = _topic_section_lines(topic)
    lines = [*_SPEC_HEADER_LINES, "", *topic_lines, "", *_SPEC_OUTPUT_AND_QUALITY_LINES]
    return _finalize("spec", topic_id, lines, profile)


def compile_outline_prompt(
    topic: Topic,
    approved_spec: str,
    profile: LearnerProfile | None = None,
) -> PromptArtifact:
    """Compile the outline-stage prompt from a topic and its approved spec."""

    spec_text = _required_block(approved_spec, "approved specification")
    topic_id, topic_lines = _topic_section_lines(topic)
    lines = [
        *_OUTLINE_HEADER_LINES,
        "",
        *topic_lines,
        "",
        "## Approved Specification",
        "The following specification was approved upstream. Treat it as the binding contract for scope and outcomes.",
        "",
        spec_text.rstrip(),
        "",
        *_OUTLINE_OUTPUT_AND_QUALITY_LINES,
    ]
    return _finalize("outline", topic_id, lines, profile)


def compile_attached_spec_prompt(
    store: ProfileStore,
    topic_id: str,
    *,
    title: str,
    topic_brief: str | None = None,
) -> PromptArtifact:
    """Compile a spec prompt using the topic's attached profile snapshot."""

    profile = store.load_topic_profile_snapshot(topic_id)
    return compile_spec_prompt(
        SpecPromptInput(
            topic_id=topic_id,
            title=title,
            topic_brief=topic_brief,
            profile=profile,
        )
    )


def _topic_section_lines(topic: Topic) -> tuple[str, list[str]]:
    topic_id = _required_text(topic.id, "topic id")
    title = _required_text(topic.title, "title")
    lines = [
        "## Topic",
        f"- Topic id: {topic_id}",
        f"- Title: {title}",
    ]
    _append_value(lines, "Topic brief", topic.brief)
    _append_value(lines, "Audience", topic.audience)
    _append_list(lines, "Goals", topic.goals)
    _append_list(lines, "In scope", topic.scope_includes)
    _append_list(lines, "Out of scope", topic.scope_excludes)
    _append_list(lines, "Key questions", topic.key_questions)
    _append_list(lines, "Prerequisites", topic.prerequisites)
    _append_list(lines, "Constraints", topic.constraints)
    _append_value(lines, "Notes", topic.notes)
    return topic_id, lines


def _finalize(
    stage: str,
    topic_id: str,
    lines: list[str],
    profile: LearnerProfile | None,
) -> PromptArtifact:
    if profile is not None:
        lines = [*lines, "", render_profile_prompt_context(profile).rstrip()]
    else:
        lines = [
            *lines,
            "",
            "## Learner Profile Context",
            "",
            "No learner profile is attached. Use broadly accessible defaults and avoid assuming private learner context.",
        ]
    return PromptArtifact(stage=stage, topic_id=topic_id, text="\n".join(lines).strip() + "\n")


def _append_value(lines: list[str], label: str, value: str | None) -> None:
    if value is not None:
        lines.append(f"- {label}: {value}")


def _append_list(lines: list[str], label: str, values: tuple[str, ...]) -> None:
    if values:
        lines.append(f"- {label}: {', '.join(values)}")


def _required_text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"spec prompt {field_name} must be a non-empty string")
    return value.strip()


def _required_block(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"prompt {field_name} must be a non-empty string")
    return value
