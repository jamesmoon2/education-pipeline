"""Deterministic readable Markdown projection of normalized guides."""

from __future__ import annotations

from dataclasses import replace

from .model import (
    Callout,
    Guide,
    KnowledgeCheck,
    Reflection,
    RichText,
    Scenario,
    WorkedReveal,
)


def public_guide_projection(guide: Guide) -> Guide:
    """Return the runtime-safe guide with local personalization data removed."""
    return replace(
        guide,
        course=replace(guide.course, goal_exclusions=()),
        outcomes=tuple(
            replace(outcome, serves_goals=()) for outcome in guide.outcomes
        ),
        modules=tuple(
            replace(module, serves_goals=()) for module in guide.modules
        ),
    )


def project_guide_markdown(guide: Guide) -> str:
    c = guide.course
    lines = [f"# {c.title}"]
    if c.subtitle:
        lines += ["", f"*{c.subtitle}*"]
    lines += [
        "",
        c.description,
        "",
        f"- Language: {c.language}",
        f"- Blueprint: {c.blueprint}",
        f"- Difficulty: {c.difficulty}",
        f"- Estimated time: {c.estimated_minutes} minutes",
    ]
    if c.learner_summary:
        lines += [f"- Learner fit: {c.learner_summary}"]
    lines += ["", "## Learning outcomes"] + [
        f"- {outcome.text} (`{outcome.id}`)" for outcome in guide.outcomes
    ]
    for module in guide.modules:
        lines += [
            "",
            f"## {module.title}",
            "",
            module.summary,
            "",
            f"Estimated time: {module.estimated_minutes} minutes",
            f"Outcomes: {', '.join(module.outcome_ids)}",
        ]
        for section in module.sections:
            lines += ["", f"### {section.title}"]
            for block in section.blocks:
                lines += _project_block(block)
    lines += ["", "## Glossary"]
    for entry in guide.glossary:
        lines += ["", f"### {entry.term}", "", entry.definition]
    lines += ["", "## Sources"]
    for source in guide.sources:
        citation = source.title
        if source.authors:
            citation += f" — {', '.join(source.authors)}"
        if source.published:
            citation += f" ({source.published})"
        if source.url:
            citation += f" — {source.url}"
        lines += ["", f"- {citation}"]
        if source.note:
            lines += [f"  {source.note}"]
    return "\n".join(lines).rstrip() + "\n"


def _project_block(block) -> list[str]:
    if isinstance(block, RichText):
        return ["", block.markdown]
    if isinstance(block, Callout):
        title = block.title or block.kind.replace("-", " ").title()
        return ["", f"#### {title} ({block.kind})", "", block.markdown]
    if isinstance(block, KnowledgeCheck):
        lines = ["", "#### Knowledge check", "", block.prompt]
        for choice in block.choices:
            lines.append(f"- [{'x' if choice.correct else ' '}] {choice.label}")
        return lines + [
            "",
            f"**Explanation:** {block.explanation}",
            f"**Retry allowed:** {'Yes' if block.retry else 'No'}",
        ]
    if isinstance(block, WorkedReveal):
        lines = ["", "#### Worked reveal", "", block.prompt]
        for index, step in enumerate(block.steps, 1):
            lines += [
                "",
                f"**Step {index}{': ' + step.title if step.title else ''}**",
                "",
                step.markdown,
            ]
        return lines + ["", f"**Conclusion:** {block.conclusion}"]
    if isinstance(block, Scenario):
        lines = ["", "#### Scenario", "", block.prompt]
        for choice in block.choices:
            lines += ["", f"- **{choice.label}** ({choice.quality}): {choice.feedback}"]
        return lines + ["", f"**Debrief:** {block.debrief}"]
    assert isinstance(block, Reflection)
    lines = ["", "#### Reflection", "", block.prompt]
    if block.guidance:
        lines += ["", f"**Guidance:** {block.guidance}"]
    if block.placeholder:
        lines += [f"**Note prompt:** {block.placeholder}"]
    return lines
