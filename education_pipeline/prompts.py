"""Prompt compilation helpers for education pipeline stages."""

from __future__ import annotations

from dataclasses import dataclass

from education_pipeline.config import ConfigError
from education_pipeline.profiles import LearnerProfile, render_profile_prompt_context
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


def compile_spec_prompt(spec_input: SpecPromptInput) -> PromptArtifact:
    """Compile a deterministic spec-stage prompt."""

    topic_id = _required_text(spec_input.topic_id, "topic_id")
    title = _required_text(spec_input.title, "title")

    lines = [
        "# Spec Stage Prompt",
        "",
        "Create a durable course specification for the topic below.",
        "The specification will guide outline, drafting, QA, repair, and export stages.",
        "",
        "## Topic",
        f"- Topic id: {topic_id}",
        f"- Title: {title}",
    ]
    if spec_input.topic_brief is not None:
        topic_brief = _required_text(spec_input.topic_brief, "topic_brief")
        lines.append(f"- Topic brief: {topic_brief}")

    lines.extend(
        [
            "",
            "## Requirements",
            "- Produce a clear learning contract, not lesson prose.",
            "- Define intended learner outcomes, scope boundaries, prerequisites, and exclusions.",
            "- Identify likely misconceptions and assessment checkpoints.",
            "- Recommend where visual aids, worked examples, practice, and review should appear.",
            "- Keep private learner details out of publishable course text unless explicitly allowed.",
        ]
    )

    if spec_input.profile is not None:
        lines.extend(["", render_profile_prompt_context(spec_input.profile).rstrip()])
    else:
        lines.extend(
            [
                "",
                "## Learner Profile Context",
                "",
                "No learner profile is attached. Use broadly accessible defaults and avoid assuming private learner context.",
            ]
        )

    return PromptArtifact(stage="spec", topic_id=topic_id, text="\n".join(lines).strip() + "\n")


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


def _required_text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"spec prompt {field_name} must be a non-empty string")
    return value
