"""Authoritative structural parser and normalizer for guide schema v1."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any, Mapping
from urllib.parse import urlsplit

from .model import (
    Callout,
    Choice,
    Course,
    GlossaryEntry,
    Guide,
    KnowledgeCheck,
    Module,
    Outcome,
    Reflection,
    RevealStep,
    RichText,
    Scenario,
    ScenarioChoice,
    Section,
    Source,
    WorkedReveal,
)

ID_RE = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
LANGUAGE_RE = re.compile(r"^[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*$")
LINK_RE = re.compile(r"(?<!!)\[[^\]\n]+\]\(([^)\s]+)(?:\s+[\"'][^\"']*[\"'])?\)")
RAW_HTML_RE = re.compile(r"</?[A-Za-z][^>]*>")
MAX_TEXT = 20_000
BLOCK_TYPES = {
    "rich_text",
    "callout",
    "knowledge_check",
    "worked_reveal",
    "scenario",
    "reflection",
}


@dataclass(frozen=True)
class ParseDiagnostic:
    code: str
    path: str
    message: str


@dataclass(frozen=True)
class ParseResult:
    parsed: Mapping[str, Any] | None
    diagnostics: tuple[ParseDiagnostic, ...]

    @property
    def ok(self) -> bool:
        return self.parsed is not None and not self.diagnostics


class GuideParseError(ValueError):
    """Raised when normalization is attempted for structurally invalid input."""

    def __init__(self, diagnostics: tuple[ParseDiagnostic, ...]):
        self.diagnostics = diagnostics
        super().__init__(
            "; ".join(f"{item.path}: {item.message}" for item in diagnostics)
        )


class _Checker:
    def __init__(self) -> None:
        self.errors: list[ParseDiagnostic] = []
        self.ids: dict[str, str] = {}
        self.outcome_refs: list[tuple[str, str]] = []
        self.source_refs: list[tuple[str, str]] = []
        self.internal_refs: list[tuple[str, str]] = []

    def error(self, code: str, path: str, message: str) -> None:
        self.errors.append(ParseDiagnostic(code, path, message))

    def obj(
        self, value: Any, path: str, required: set[str], optional: set[str] = set()
    ) -> dict[str, Any] | None:
        if not isinstance(value, dict):
            self.error("schema.invalid_type", path, "must be an object")
            return None
        for key in sorted(required - value.keys()):
            self.error("schema.missing_field", path, f"missing required field {key!r}")
        for key in sorted(value.keys() - required - optional):
            self.error(
                "schema.unknown_field", f"{path}/{key}", f"unknown field {key!r}"
            )
        return value

    def array(
        self, value: Any, path: str, minimum: int = 0, maximum: int | None = None
    ) -> list[Any] | None:
        if not isinstance(value, list):
            self.error("schema.invalid_type", path, "must be an array")
            return None
        if len(value) < minimum or maximum is not None and len(value) > maximum:
            bound = (
                f"{minimum}–{maximum}" if maximum is not None else f"at least {minimum}"
            )
            self.error("schema.cardinality", path, f"must contain {bound} items")
        return value

    def text(self, value: Any, path: str, *, markdown: bool = False) -> str | None:
        if not isinstance(value, str):
            self.error("schema.invalid_type", path, "must be a string")
            return None
        normalized = value.strip()
        if not normalized:
            self.error("content.empty", path, "must not be empty")
        if len(normalized) > MAX_TEXT:
            self.error(
                "content.excessive_length",
                path,
                f"must not exceed {MAX_TEXT} code points",
            )
        if RAW_HTML_RE.search(normalized):
            self.error("content.raw_html", path, "raw HTML is not allowed")
        if markdown:
            if re.search(r"!\[[^\]]*\]\(", normalized):
                self.error(
                    "link.image_not_supported",
                    path,
                    "Markdown images are not supported",
                )
            for match in LINK_RE.finditer(normalized):
                target = match.group(1)
                if not self.safe_target(target):
                    self.error(
                        "link.unsafe_target",
                        path,
                        f"unsafe Markdown link target {target!r}",
                    )
                elif target.startswith("#"):
                    self.internal_refs.append((target[1:], path))
        return normalized

    @staticmethod
    def safe_target(target: str) -> bool:
        if target.startswith("#"):
            return bool(ID_RE.fullmatch(target[1:]))
        parts = urlsplit(target)
        return (
            parts.scheme in {"http", "https"}
            and bool(parts.netloc)
            and not target.startswith("//")
        )

    def identifier(self, value: Any, path: str) -> str | None:
        identifier = self.text(value, path)
        if identifier is None:
            return None
        if not ID_RE.fullmatch(identifier):
            self.error("schema.invalid_id", path, "must match ^[a-z][a-z0-9-]{0,63}$")
        previous = self.ids.get(identifier)
        if previous is not None:
            self.error(
                "schema.duplicate_id",
                path,
                f"duplicates ID first declared at {previous}",
            )
        else:
            self.ids[identifier] = path
        return identifier


def parse_guide(text: str | bytes) -> ParseResult:
    """Parse JSON and return all practical render-blocking structural diagnostics."""
    checker = _Checker()
    if isinstance(text, bytes):
        try:
            text = text.decode("utf-8")
        except UnicodeDecodeError as exc:
            checker.error("json.invalid_utf8", "", f"input is not valid UTF-8: {exc}")
            return ParseResult(None, tuple(checker.errors))
    if not isinstance(text, str):
        checker.error(
            "schema.invalid_type", "", "guide input must be text or UTF-8 bytes"
        )
        return ParseResult(None, tuple(checker.errors))
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        checker.error(
            "json.invalid",
            "",
            f"malformed JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}",
        )
        return ParseResult(None, tuple(checker.errors))
    root = checker.obj(
        data,
        "",
        {"schema_version", "course", "outcomes", "modules", "glossary", "sources"},
    )
    if root is None:
        return ParseResult(None, tuple(checker.errors))
    if root.get("schema_version") != "1.0":
        checker.error(
            "schema.unsupported_version",
            "/schema_version",
            "supported schema version is exactly '1.0'",
        )
    _check_course(checker, root.get("course"), "/course")
    _check_outcomes(checker, root.get("outcomes"), "/outcomes")
    _check_modules(checker, root.get("modules"), "/modules")
    _check_glossary(checker, root.get("glossary"), "/glossary")
    _check_sources(checker, root.get("sources"), "/sources")
    _check_references_and_coverage(checker, root)
    return ParseResult(root if not checker.errors else None, tuple(checker.errors))


def normalize_guide(parsed: ParseResult | Mapping[str, Any]) -> Guide:
    """Convert a successful parse result into immutable normalized guide data."""
    if isinstance(parsed, ParseResult):
        if not parsed.ok or parsed.parsed is None:
            raise GuideParseError(parsed.diagnostics)
        data = parsed.parsed
    else:
        reparsed = parse_guide(json.dumps(parsed, ensure_ascii=False))
        if not reparsed.ok or reparsed.parsed is None:
            raise GuideParseError(reparsed.diagnostics)
        data = reparsed.parsed
    course = data["course"]
    return Guide(
        schema_version="1.0",
        course=Course(
            **{
                key: course.get(key)
                for key in (
                    "id",
                    "title",
                    "description",
                    "language",
                    "blueprint",
                    "estimated_minutes",
                    "difficulty",
                    "subtitle",
                    "learner_summary",
                )
            }
        ),
        outcomes=tuple(Outcome(**item) for item in data["outcomes"]),
        modules=tuple(_normalize_module(item) for item in data["modules"]),
        glossary=tuple(GlossaryEntry(**item) for item in data["glossary"]),
        sources=tuple(
            Source(
                id=item["id"],
                title=item["title"],
                authors=tuple(item.get("authors", ())),
                url=item.get("url"),
                published=item.get("published"),
                note=item.get("note"),
            )
            for item in data["sources"]
        ),
    )


def _check_course(c: _Checker, value: Any, path: str) -> None:
    required = {
        "id",
        "title",
        "description",
        "language",
        "blueprint",
        "estimated_minutes",
        "difficulty",
    }
    obj = c.obj(value, path, required, {"subtitle", "learner_summary"})
    if obj is None:
        return
    c.identifier(obj.get("id"), f"{path}/id")
    for field in ("title", "description", "blueprint", "subtitle", "learner_summary"):
        if field in obj:
            c.text(obj[field], f"{path}/{field}", markdown=field == "description")
    language = c.text(obj.get("language"), f"{path}/language")
    if language is not None and not LANGUAGE_RE.fullmatch(language):
        c.error(
            "schema.invalid_value",
            f"{path}/language",
            "must be a valid v1 BCP 47 language tag",
        )
    _integer(c, obj.get("estimated_minutes"), f"{path}/estimated_minutes", 5, 10_000)
    if obj.get("difficulty") not in {
        "introductory",
        "intermediate",
        "advanced",
        "mixed",
    }:
        c.error(
            "schema.invalid_value",
            f"{path}/difficulty",
            "must be introductory, intermediate, advanced, or mixed",
        )


def _check_outcomes(c: _Checker, value: Any, path: str) -> None:
    items = c.array(value, path, 1, 20)
    if items is None:
        return
    for i, value in enumerate(items):
        item = c.obj(value, f"{path}/{i}", {"id", "text"})
        if item:
            c.identifier(item.get("id"), f"{path}/{i}/id")
            c.text(item.get("text"), f"{path}/{i}/text")


def _check_modules(c: _Checker, value: Any, path: str) -> None:
    modules = c.array(value, path, 1)
    if modules is None:
        return
    for i, value in enumerate(modules):
        p = f"{path}/{i}"
        module = c.obj(
            value,
            p,
            {"id", "title", "summary", "outcome_ids", "estimated_minutes", "sections"},
        )
        if not module:
            continue
        c.identifier(module.get("id"), f"{p}/id")
        c.text(module.get("title"), f"{p}/title")
        c.text(module.get("summary"), f"{p}/summary", markdown=True)
        _refs(c, module.get("outcome_ids"), f"{p}/outcome_ids", "outcome", 1)
        _integer(c, module.get("estimated_minutes"), f"{p}/estimated_minutes", 1, 1_000)
        sections = c.array(module.get("sections"), f"{p}/sections", 1)
        if sections is None:
            continue
        for j, raw_section in enumerate(sections):
            sp = f"{p}/sections/{j}"
            section = c.obj(raw_section, sp, {"id", "title", "blocks"})
            if not section:
                continue
            c.identifier(section.get("id"), f"{sp}/id")
            c.text(section.get("title"), f"{sp}/title")
            blocks = c.array(section.get("blocks"), f"{sp}/blocks", 1)
            if blocks is not None:
                for k, block in enumerate(blocks):
                    _check_block(c, block, f"{sp}/blocks/{k}")


def _check_block(c: _Checker, value: Any, path: str) -> None:
    if not isinstance(value, dict):
        c.error("schema.invalid_type", path, "must be an object")
        return
    block_type = value.get("type")
    if block_type not in BLOCK_TYPES:
        c.error(
            "schema.unknown_block_type",
            f"{path}/type",
            f"unknown block type {block_type!r}",
        )
        return
    common_optional = {"outcome_ids", "source_ids"}
    specs = {
        "rich_text": ({"id", "type", "markdown"}, set()),
        "callout": ({"id", "type", "kind", "markdown"}, {"title"}),
        "knowledge_check": (
            {
                "id",
                "type",
                "outcome_ids",
                "mode",
                "prompt",
                "choices",
                "explanation",
                "retry",
            },
            set(),
        ),
        "worked_reveal": (
            {"id", "type", "outcome_ids", "prompt", "steps", "conclusion"},
            set(),
        ),
        "scenario": (
            {"id", "type", "outcome_ids", "prompt", "choices", "debrief"},
            set(),
        ),
        "reflection": (
            {"id", "type", "outcome_ids", "prompt"},
            {"guidance", "placeholder"},
        ),
    }
    required, optional = specs[block_type]
    block = c.obj(value, path, required, optional | common_optional)
    if not block:
        return
    c.identifier(block.get("id"), f"{path}/id")
    if "outcome_ids" in block:
        _refs(
            c,
            block["outcome_ids"],
            f"{path}/outcome_ids",
            "outcome",
            1
            if block_type
            in {"knowledge_check", "worked_reveal", "scenario", "reflection"}
            else 0,
        )
    if "source_ids" in block:
        _refs(c, block["source_ids"], f"{path}/source_ids", "source")
    for field in (
        "markdown",
        "feedback",
        "explanation",
        "conclusion",
        "debrief",
        "guidance",
    ):
        if field in block:
            c.text(block[field], f"{path}/{field}", markdown=True)
    for field in ("title", "prompt", "placeholder"):
        if field in block:
            c.text(block[field], f"{path}/{field}", markdown=field == "prompt")
    if block_type == "callout" and block.get("kind") not in {
        "key-idea",
        "connection",
        "example",
        "warning",
        "misconception",
        "source-note",
    }:
        c.error("schema.invalid_value", f"{path}/kind", "invalid callout kind")
    if block_type == "knowledge_check":
        _check_knowledge(c, block, path)
    elif block_type == "worked_reveal":
        _check_steps(c, block.get("steps"), f"{path}/steps")
    elif block_type == "scenario":
        _check_scenario(c, block, path)


def _check_knowledge(c: _Checker, block: dict[str, Any], path: str) -> None:
    mode = block.get("mode")
    if mode not in {"single", "multiple"}:
        c.error("schema.invalid_value", f"{path}/mode", "must be single or multiple")
    if not isinstance(block.get("retry"), bool):
        c.error("schema.invalid_type", f"{path}/retry", "must be a Boolean")
    choices = c.array(block.get("choices"), f"{path}/choices", 2, 8)
    correct = []
    if choices is None:
        return
    for i, value in enumerate(choices):
        p = f"{path}/choices/{i}"
        item = c.obj(value, p, {"id", "label", "correct"})
        if item:
            c.identifier(item.get("id"), f"{p}/id")
            c.text(item.get("label"), f"{p}/label")
        if item and not isinstance(item.get("correct"), bool):
            c.error("schema.invalid_type", f"{p}/correct", "must be a Boolean")
        elif item:
            correct.append(item["correct"])
    if mode == "single" and sum(correct) != 1:
        c.error(
            "knowledge_check.invalid_answer_set",
            f"{path}/choices",
            "single mode requires exactly one correct choice",
        )
    if mode == "multiple" and (not any(correct) or all(correct)):
        c.error(
            "knowledge_check.invalid_answer_set",
            f"{path}/choices",
            "multiple mode requires correct and incorrect choices",
        )


def _check_steps(c: _Checker, value: Any, path: str) -> None:
    steps = c.array(value, path, 2, 12)
    if steps is None:
        return
    for i, value in enumerate(steps):
        p = f"{path}/{i}"
        item = c.obj(value, p, {"id", "markdown"}, {"title"})
        if item:
            c.identifier(item.get("id"), f"{p}/id")
            c.text(item.get("markdown"), f"{p}/markdown", markdown=True)
        if item and "title" in item:
            c.text(item["title"], f"{p}/title")


def _check_scenario(c: _Checker, block: dict[str, Any], path: str) -> None:
    choices = c.array(block.get("choices"), f"{path}/choices", 2, 6)
    best = 0
    if choices is None:
        return
    for i, value in enumerate(choices):
        p = f"{path}/choices/{i}"
        item = c.obj(value, p, {"id", "label", "quality", "feedback"})
        if not item:
            continue
        c.identifier(item.get("id"), f"{p}/id")
        c.text(item.get("label"), f"{p}/label")
        c.text(item.get("feedback"), f"{p}/feedback", markdown=True)
        if item.get("quality") not in {"best", "reasonable", "weak", "harmful"}:
            c.error("schema.invalid_value", f"{p}/quality", "invalid scenario quality")
        best += item.get("quality") == "best"
    if best != 1:
        c.error(
            "scenario.invalid_quality_set",
            f"{path}/choices",
            "scenario requires exactly one best choice",
        )


def _check_glossary(c: _Checker, value: Any, path: str) -> None:
    items = c.array(value, path)
    if items is None:
        return
    for i, value in enumerate(items):
        p = f"{path}/{i}"
        item = c.obj(value, p, {"id", "term", "definition"})
        if item:
            c.identifier(item.get("id"), f"{p}/id")
            c.text(item.get("term"), f"{p}/term")
            c.text(item.get("definition"), f"{p}/definition", markdown=True)


def _check_sources(c: _Checker, value: Any, path: str) -> None:
    items = c.array(value, path)
    if items is None:
        return
    for i, value in enumerate(items):
        p = f"{path}/{i}"
        item = c.obj(value, p, {"id", "title"}, {"authors", "url", "published", "note"})
        if not item:
            continue
        c.identifier(item.get("id"), f"{p}/id")
        c.text(item.get("title"), f"{p}/title")
        if "authors" in item:
            authors = c.array(item["authors"], f"{p}/authors", 1)
            if authors is not None:
                for j, author in enumerate(authors):
                    c.text(author, f"{p}/authors/{j}")
        for field in ("published", "note"):
            if field in item:
                c.text(item[field], f"{p}/{field}", markdown=field == "note")
        if "url" in item:
            url = c.text(item["url"], f"{p}/url")
            if url is not None and (
                urlsplit(url).scheme not in {"http", "https"}
                or not urlsplit(url).netloc
            ):
                c.error(
                    "source.invalid_url",
                    f"{p}/url",
                    "source URL must use http or https",
                )


def _refs(c: _Checker, value: Any, path: str, kind: str, minimum: int = 0) -> None:
    values = c.array(value, path, minimum)
    if values is None:
        return
    seen = set()
    for i, value in enumerate(values):
        ref = c.text(value, f"{path}/{i}")
        if ref is None:
            continue
        if ref in seen:
            c.error(
                "schema.duplicate_reference",
                f"{path}/{i}",
                f"duplicate {kind} reference {ref!r}",
            )
        seen.add(ref)
        (c.outcome_refs if kind == "outcome" else c.source_refs).append(
            (ref, f"{path}/{i}")
        )


def _integer(c: _Checker, value: Any, path: str, minimum: int, maximum: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        c.error("schema.invalid_type", path, "must be an integer")
        return
    if not minimum <= value <= maximum:
        c.error(
            "schema.invalid_value", path, f"must be between {minimum} and {maximum}"
        )


def _check_references_and_coverage(c: _Checker, root: dict[str, Any]) -> None:
    outcomes = {
        item.get("id")
        for item in root.get("outcomes", [])
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    sources = {
        item.get("id")
        for item in root.get("sources", [])
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    for ref, path in c.outcome_refs:
        if ref not in outcomes:
            c.error("schema.unknown_reference", path, f"unknown outcome ID {ref!r}")
    for ref, path in c.source_refs:
        if ref not in sources:
            c.error("schema.unknown_reference", path, f"unknown source ID {ref!r}")
    for ref, path in c.internal_refs:
        if ref not in c.ids:
            c.error(
                "link.unknown_internal_target", path, f"unknown internal target {ref!r}"
            )
    assigned = set()
    taught = set()
    practiced = set()
    present_types = set()
    interactive = {"knowledge_check", "worked_reveal", "scenario", "reflection"}
    for mi, module in enumerate(
        root.get("modules", []) if isinstance(root.get("modules"), list) else []
    ):
        if not isinstance(module, dict):
            continue
        assigned.update(x for x in module.get("outcome_ids", []) if isinstance(x, str))
        has_interaction = False
        for section in (
            module.get("sections", [])
            if isinstance(module.get("sections"), list)
            else []
        ):
            if not isinstance(section, dict):
                continue
            for block in (
                section.get("blocks", [])
                if isinstance(section.get("blocks"), list)
                else []
            ):
                if not isinstance(block, dict):
                    continue
                refs = {x for x in block.get("outcome_ids", []) if isinstance(x, str)}
                kind = block.get("type")
                present_types.add(kind)
                if kind in {"rich_text", "callout"}:
                    taught.update(refs)
                if kind in interactive:
                    practiced.update(refs)
                    has_interaction = True
        if not has_interaction:
            c.error(
                "module.no_interaction",
                f"/modules/{mi}",
                "module must contain at least one interactive block",
            )
    for missing_type in sorted(interactive - present_types):
        c.error(
            "interaction.missing_required_type",
            "/modules",
            f"guide must contain a {missing_type!r} block",
        )
    for outcome in sorted(outcomes):
        if outcome not in assigned:
            c.error(
                "outcome.unassigned",
                "/outcomes",
                f"outcome {outcome!r} is not assigned to a module",
            )
        if outcome not in taught:
            c.error(
                "outcome.untaught",
                "/outcomes",
                f"outcome {outcome!r} is not taught by rich text or a callout",
            )
        if outcome not in practiced:
            c.error(
                "outcome.unassessed",
                "/outcomes",
                f"outcome {outcome!r} is not assessed or practiced",
            )


def _normalize_module(item: Mapping[str, Any]) -> Module:
    return Module(
        id=item["id"],
        title=item["title"],
        summary=item["summary"],
        outcome_ids=tuple(item["outcome_ids"]),
        estimated_minutes=item["estimated_minutes"],
        sections=tuple(
            Section(
                id=s["id"],
                title=s["title"],
                blocks=tuple(_normalize_block(b) for b in s["blocks"]),
            )
            for s in item["sections"]
        ),
    )


def _normalize_block(item: Mapping[str, Any]):
    common = {
        "id": item["id"],
        "outcome_ids": tuple(item.get("outcome_ids", ())),
        "source_ids": tuple(item.get("source_ids", ())),
    }
    kind = item["type"]
    if kind == "rich_text":
        return RichText(markdown=item["markdown"], **common)
    if kind == "callout":
        return Callout(
            kind=item["kind"],
            markdown=item["markdown"],
            title=item.get("title"),
            **common,
        )
    if kind == "knowledge_check":
        return KnowledgeCheck(
            mode=item["mode"],
            prompt=item["prompt"],
            choices=tuple(Choice(**x) for x in item["choices"]),
            explanation=item["explanation"],
            retry=item["retry"],
            **common,
        )
    if kind == "worked_reveal":
        return WorkedReveal(
            prompt=item["prompt"],
            steps=tuple(
                RevealStep(id=x["id"], markdown=x["markdown"], title=x.get("title"))
                for x in item["steps"]
            ),
            conclusion=item["conclusion"],
            **common,
        )
    if kind == "scenario":
        return Scenario(
            prompt=item["prompt"],
            choices=tuple(ScenarioChoice(**x) for x in item["choices"]),
            debrief=item["debrief"],
            **common,
        )
    return Reflection(
        prompt=item["prompt"],
        guidance=item.get("guidance"),
        placeholder=item.get("placeholder"),
        **common,
    )
