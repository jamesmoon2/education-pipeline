"""Deterministic readable Markdown projection of normalized guides."""

from __future__ import annotations

from dataclasses import replace

from .diagrams import KIND_LABELS, back_edge_indices
from .model import (
    Callout,
    Diagram,
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
    if isinstance(block, Diagram):
        return _project_diagram(block)
    assert isinstance(block, Reflection)
    lines = ["", "#### Reflection", "", block.prompt]
    if block.guidance:
        lines += ["", f"**Guidance:** {block.guidance}"]
    if block.placeholder:
        lines += [f"**Note prompt:** {block.placeholder}"]
    return lines


def _project_diagram(block: Diagram) -> list[str]:
    """The diagram's text version: title, kind label, the kind's body, caption."""

    lines = ["", f"#### {block.title}", "", f"*{KIND_LABELS[block.kind]}*", ""]
    body = {
        "flow": _project_flow,
        "concept_map": _project_concept_map,
        "timeline": _project_timeline,
        "comparison": _project_comparison,
    }[block.kind]
    lines += body(block)
    if block.caption:
        lines += ["", block.caption]
    return lines


def _with_detail(text: str, detail: str | None) -> str:
    return f"{text}: {detail}" if detail else text


def _node_labels(block: Diagram) -> dict[str, str]:
    return {node.id: node.label for node in block.nodes}


def _project_flow(block: Diagram) -> list[str]:
    labels = _node_labels(block)
    back = back_edge_indices(block)
    lines = [
        _with_detail(f"{n}. {node.label}", node.detail)
        for n, node in enumerate(block.nodes, 1)
    ]
    lines += ["", "Connections:", ""]
    for index, edge in enumerate(block.edges):
        line = f"- {labels.get(edge.from_id, edge.from_id)} → {labels.get(edge.to_id, edge.to_id)}"
        if edge.label:
            line += f" — {edge.label}"
        if index in back:
            line += " (loops back)"
        lines.append(line)
    return lines


def _project_concept_map(block: Diagram) -> list[str]:
    labels = _node_labels(block)
    ordered = [node for node in block.nodes if node.id == block.hub] + [
        node for node in block.nodes if node.id != block.hub
    ]
    lines = []
    for node in ordered:
        text = f"- {node.label}" + (" (central idea)" if node.id == block.hub else "")
        lines.append(_with_detail(text, node.detail))
        for edge in block.edges:
            if edge.from_id == node.id:
                prefix = f"{edge.label} " if edge.label else ""
                lines.append(f"  - {prefix}→ {labels.get(edge.to_id, edge.to_id)}")
    return lines


def _project_timeline(block: Diagram) -> list[str]:
    return [
        _with_detail(f"{n}. {event.when} — {event.label}", event.detail)
        for n, event in enumerate(block.events, 1)
    ]


def _cell(text: str) -> str:
    return text.replace("|", "\\|")


def _project_comparison(block: Diagram) -> list[str]:
    lines = [
        "| Criterion | " + " | ".join(_cell(item.label) for item in block.items) + " |",
        "| --- |" + " --- |" * len(block.items),
    ]
    for criterion in block.criteria:
        cells = {value.item_id: value.text for value in criterion.values}
        row = [_cell(cells.get(item.id, "")) for item in block.items]
        lines.append(f"| {_cell(criterion.label)} | " + " | ".join(row) + " |")
    return lines
