"""Typed, normalized data model for Interactive Guide schema v1."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TypeAlias

#: Every Interactive Guide schema version this codebase reads and writes. One
#: definition, so a new version is added in one place instead of in each
#: parser, contract check, prompt compiler and run-content contract.
SUPPORTED_GUIDE_SCHEMA_VERSIONS = frozenset({"1.0", "1.1", "1.2"})

#: Schema versions that allow the source-only goal annotations
#: (``serves_goals`` / ``goal_exclusions``).
ANNOTATION_SCHEMA_VERSIONS = frozenset({"1.1", "1.2"})

#: Schema versions that allow the ``diagram`` block.
DIAGRAM_SCHEMA_VERSIONS = frozenset({"1.2"})

#: The newest schema version this codebase writes.
LATEST_GUIDE_SCHEMA_VERSION = "1.2"

#: Diagram kinds, in the order used everywhere a kind list is printed.
DIAGRAM_KINDS = ("flow", "concept_map", "comparison", "timeline")

#: The schema version assumed when a run, a prompt or an unparseable source
#: does not name one.
DEFAULT_GUIDE_SCHEMA_VERSION = "1.0"


@dataclass(frozen=True)
class GoalExclusion:
    goal_id: str
    reason: str


@dataclass(frozen=True)
class Course:
    id: str
    title: str
    description: str
    language: str
    blueprint: str
    estimated_minutes: int
    difficulty: str
    subtitle: str | None = None
    learner_summary: str | None = None
    goal_exclusions: tuple[GoalExclusion, ...] = ()


@dataclass(frozen=True)
class Outcome:
    id: str
    text: str
    serves_goals: tuple[str, ...] = ()


@dataclass(frozen=True)
class Choice:
    id: str
    label: str
    correct: bool


@dataclass(frozen=True)
class ScenarioChoice:
    id: str
    label: str
    quality: str
    feedback: str


@dataclass(frozen=True)
class RevealStep:
    id: str
    markdown: str
    title: str | None = None


@dataclass(frozen=True)
class RichText:
    id: str
    markdown: str
    type: str = "rich_text"
    outcome_ids: tuple[str, ...] = ()
    source_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class Callout:
    id: str
    kind: str
    markdown: str
    type: str = "callout"
    title: str | None = None
    outcome_ids: tuple[str, ...] = ()
    source_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class KnowledgeCheck:
    id: str
    outcome_ids: tuple[str, ...]
    mode: str
    prompt: str
    choices: tuple[Choice, ...]
    explanation: str
    retry: bool
    type: str = "knowledge_check"
    source_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class WorkedReveal:
    id: str
    outcome_ids: tuple[str, ...]
    prompt: str
    steps: tuple[RevealStep, ...]
    conclusion: str
    type: str = "worked_reveal"
    source_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class Scenario:
    id: str
    outcome_ids: tuple[str, ...]
    prompt: str
    choices: tuple[ScenarioChoice, ...]
    debrief: str
    type: str = "scenario"
    source_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class Reflection:
    id: str
    outcome_ids: tuple[str, ...]
    prompt: str
    type: str = "reflection"
    guidance: str | None = None
    placeholder: str | None = None
    source_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class DiagramNode:
    id: str
    label: str
    detail: str | None = None


@dataclass(frozen=True)
class DiagramEdge:
    from_id: str = field(metadata={"json": "from"})
    to_id: str = field(metadata={"json": "to"})
    label: str | None = None


@dataclass(frozen=True)
class TimelineEvent:
    id: str
    when: str
    label: str
    detail: str | None = None


@dataclass(frozen=True)
class ComparisonItem:
    id: str
    label: str


@dataclass(frozen=True)
class ComparisonValue:
    item_id: str
    text: str


@dataclass(frozen=True)
class ComparisonCriterion:
    id: str
    label: str
    #: Stored in the diagram's ``items`` order; serialized as an object keyed
    #: by item id.
    values: tuple[ComparisonValue, ...] = field(
        default=(), metadata={"json_keyed": ("item_id", "text")}
    )


@dataclass(frozen=True)
class Diagram:
    id: str
    kind: str
    title: str
    type: str = "diagram"
    caption: str | None = None
    hub: str | None = None
    nodes: tuple[DiagramNode, ...] = field(default=(), metadata={"omit_empty": True})
    edges: tuple[DiagramEdge, ...] = field(default=(), metadata={"omit_empty": True})
    events: tuple[TimelineEvent, ...] = field(
        default=(), metadata={"omit_empty": True}
    )
    items: tuple[ComparisonItem, ...] = field(
        default=(), metadata={"omit_empty": True}
    )
    criteria: tuple[ComparisonCriterion, ...] = field(
        default=(), metadata={"omit_empty": True}
    )
    outcome_ids: tuple[str, ...] = ()
    source_ids: tuple[str, ...] = ()


Block: TypeAlias = (
    RichText
    | Callout
    | KnowledgeCheck
    | WorkedReveal
    | Scenario
    | Reflection
    | Diagram
)


@dataclass(frozen=True)
class Section:
    id: str
    title: str
    blocks: tuple[Block, ...]


@dataclass(frozen=True)
class Module:
    id: str
    title: str
    summary: str
    outcome_ids: tuple[str, ...]
    estimated_minutes: int
    sections: tuple[Section, ...]
    serves_goals: tuple[str, ...] = ()


@dataclass(frozen=True)
class GlossaryEntry:
    id: str
    term: str
    definition: str


@dataclass(frozen=True)
class Source:
    id: str
    title: str
    authors: tuple[str, ...] = ()
    url: str | None = None
    published: str | None = None
    note: str | None = None


@dataclass(frozen=True)
class Guide:
    schema_version: str
    course: Course
    outcomes: tuple[Outcome, ...]
    modules: tuple[Module, ...]
    glossary: tuple[GlossaryEntry, ...]
    sources: tuple[Source, ...]
