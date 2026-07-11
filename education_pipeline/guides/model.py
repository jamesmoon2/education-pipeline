"""Typed, normalized data model for Interactive Guide schema v1."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias


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


@dataclass(frozen=True)
class Outcome:
    id: str
    text: str


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


Block: TypeAlias = (
    RichText | Callout | KnowledgeCheck | WorkedReveal | Scenario | Reflection
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
