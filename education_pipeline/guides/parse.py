"""Authoritative structural parser and normalizer for guide schema v1."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit

from .diagrams import KIND_FIELDS, diagram_findings
from .model import (
    ANNOTATION_SCHEMA_VERSIONS,
    DIAGRAM_SCHEMA_VERSIONS,
    SUPPORTED_GUIDE_SCHEMA_VERSIONS,
    Callout,
    Choice,
    ComparisonCriterion,
    ComparisonItem,
    ComparisonValue,
    Diagram,
    DiagramEdge,
    DiagramNode,
    TimelineEvent,
    Course,
    GoalExclusion,
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
GOAL_ID_RE = re.compile(r"^goal-(?:00[1-9]|0[1-9][0-9]|[1-9][0-9]{2,})\Z")
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
#: Not in ``BLOCK_TYPES``: that set is also the outline's plannable
#: ``interaction_types``, and a diagram is not an interaction to plan.
DIAGRAM_BLOCK_TYPE = "diagram"

#: Required and optional keys of each diagram kind-array element.
DIAGRAM_ELEMENT_SPECS: dict[str, tuple[set[str], set[str]]] = {
    "nodes": ({"id", "label"}, {"detail"}),
    "edges": ({"from", "to"}, {"label"}),
    "events": ({"id", "when", "label"}, {"detail"}),
    "items": ({"id", "label"}, set()),
    "criteria": ({"id", "label", "values"}, set()),
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


ROOT_GUIDE_KEYS = {
    "schema_version",
    "course",
    "outcomes",
    "modules",
    "glossary",
    "sources",
}


def _decode_root(
    c: _Checker, value: Any, *, allow_mapping: bool = False
) -> dict[str, Any] | None:
    """Decode guide input to the checked root object, or record why it cannot be."""

    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8")
        except UnicodeDecodeError as exc:
            c.error("json.invalid_utf8", "", f"input is not valid UTF-8: {exc}")
            return None
    if isinstance(value, str):
        try:
            data: Any = json.loads(value)
        except json.JSONDecodeError as exc:
            c.error(
                "json.invalid",
                "",
                f"malformed JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}",
            )
            return None
    elif allow_mapping and isinstance(value, Mapping):
        data = dict(value)
    else:
        c.error("schema.invalid_type", "", "guide input must be text or UTF-8 bytes")
        return None
    return c.obj(data, "", ROOT_GUIDE_KEYS)


def _check_root(c: _Checker, root: dict[str, Any], *, skeleton: bool = False) -> None:
    """Run every root-level structural arm over an already-decoded guide object."""

    schema_version = root.get("schema_version")
    if (
        not isinstance(schema_version, str)
        or schema_version not in SUPPORTED_GUIDE_SCHEMA_VERSIONS
    ):
        c.error(
            "schema.unsupported_version",
            "/schema_version",
            "supported schema versions are exactly '1.0', '1.1' and '1.2'",
        )
    annotations_allowed = (
        isinstance(schema_version, str) and schema_version in ANNOTATION_SCHEMA_VERSIONS
    )
    diagrams_allowed = (
        isinstance(schema_version, str) and schema_version in DIAGRAM_SCHEMA_VERSIONS
    )
    _check_course(c, root.get("course"), "/course", annotations_allowed)
    _check_outcomes(c, root.get("outcomes"), "/outcomes", annotations_allowed)
    _check_modules(
        c,
        root.get("modules"),
        "/modules",
        annotations_allowed,
        skeleton=skeleton,
        diagrams_allowed=diagrams_allowed,
    )
    _check_glossary(c, root.get("glossary"), "/glossary")
    _check_sources(c, root.get("sources"), "/sources")
    _check_references_and_coverage(c, root, skeleton=skeleton)


def parse_guide(text: str | bytes) -> ParseResult:
    """Parse JSON and return all practical render-blocking structural diagnostics."""
    checker = _Checker()
    root = _decode_root(checker, text)
    if root is None:
        return ParseResult(None, tuple(checker.errors))
    _check_root(checker, root)
    return ParseResult(root if not checker.errors else None, tuple(checker.errors))


def check_skeleton(
    value: str | bytes | Mapping[str, Any], *, module_order: Sequence[str]
) -> ParseResult:
    """Validate a course *skeleton*: a guide whose modules are sectionless stubs.

    A skeleton can never pass :func:`parse_guide` -- ``sections`` has
    cardinality at least one, every module needs an interactive block, and
    every outcome must be taught and assessed -- so it gets its own check.
    The root shape, one shared id namespace, and every per-element rule are
    the parser's own; only the completeness arms that a sectionless document
    cannot satisfy are skipped, and each module must carry ``sections: []``.

    ``module_order`` is the authored outline order: the stub ids must be
    exactly those ids, in exactly that order. Malformed input yields
    diagnostics, never an exception.
    """

    checker = _Checker()
    root = _decode_root(checker, value, allow_mapping=True)
    if root is None:
        return ParseResult(None, tuple(checker.errors))
    _check_root(checker, root, skeleton=True)
    _check_skeleton_module_order(checker, root, tuple(module_order))
    return ParseResult(root if not checker.errors else None, tuple(checker.errors))


def _check_skeleton_module_order(
    c: _Checker, root: dict[str, Any], module_order: tuple[str, ...]
) -> None:
    modules = root.get("modules")
    if not isinstance(modules, list):
        return
    stub_ids = [
        module["id"]
        for module in modules
        if isinstance(module, dict) and isinstance(module.get("id"), str)
    ]
    expected = list(module_order)
    for position, module_id in enumerate(expected):
        if module_id not in stub_ids:
            c.error(
                "skeleton.missing_module",
                f"/modules/{position}",
                f"skeleton is missing module {module_id!r} from the outline order",
            )
    for position, module_id in enumerate(stub_ids):
        if module_id not in expected:
            c.error(
                "skeleton.extra_module",
                f"/modules/{position}",
                f"module {module_id!r} is not in the outline's module order",
            )
    if sorted(stub_ids) == sorted(expected) and stub_ids != expected:
        c.error(
            "skeleton.module_order",
            "/modules",
            "module stubs must appear in the outline's authored order: "
            + ", ".join(expected),
        )


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
        schema_version=data["schema_version"],
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
            },
            goal_exclusions=tuple(
                GoalExclusion(**item) for item in course.get("goal_exclusions", ())
            ),
        ),
        outcomes=tuple(
            Outcome(
                id=item["id"],
                text=item["text"],
                serves_goals=tuple(item.get("serves_goals", ())),
            )
            for item in data["outcomes"]
        ),
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


def _check_course(
    c: _Checker, value: Any, path: str, annotations_allowed: bool
) -> None:
    required = {
        "id",
        "title",
        "description",
        "language",
        "blueprint",
        "estimated_minutes",
        "difficulty",
    }
    optional = {"subtitle", "learner_summary"}
    if annotations_allowed:
        optional.add("goal_exclusions")
    obj = c.obj(value, path, required, optional)
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
    if "goal_exclusions" in obj and annotations_allowed:
        _check_goal_exclusions(c, obj["goal_exclusions"], f"{path}/goal_exclusions")


def _check_outcomes(
    c: _Checker, value: Any, path: str, annotations_allowed: bool
) -> None:
    items = c.array(value, path, 1, 20)
    if items is None:
        return
    for i, value in enumerate(items):
        optional = {"serves_goals"} if annotations_allowed else set()
        item = c.obj(value, f"{path}/{i}", {"id", "text"}, optional)
        if item:
            c.identifier(item.get("id"), f"{path}/{i}/id")
            c.text(item.get("text"), f"{path}/{i}/text")
            if "serves_goals" in item and annotations_allowed:
                _goal_refs(c, item["serves_goals"], f"{path}/{i}/serves_goals")


def _check_modules(
    c: _Checker,
    value: Any,
    path: str,
    annotations_allowed: bool,
    *,
    skeleton: bool = False,
    diagrams_allowed: bool = False,
) -> None:
    modules = c.array(value, path, 1)
    if modules is None:
        return
    for i, value in enumerate(modules):
        p = f"{path}/{i}"
        optional = {"serves_goals"} if annotations_allowed else set()
        module = c.obj(
            value,
            p,
            {"id", "title", "summary", "outcome_ids", "estimated_minutes", "sections"},
            optional,
        )
        if not module:
            continue
        c.identifier(module.get("id"), f"{p}/id")
        c.text(module.get("title"), f"{p}/title")
        c.text(module.get("summary"), f"{p}/summary", markdown=True)
        _refs(c, module.get("outcome_ids"), f"{p}/outcome_ids", "outcome", 1)
        if "serves_goals" in module and annotations_allowed:
            _goal_refs(c, module["serves_goals"], f"{p}/serves_goals")
        _integer(c, module.get("estimated_minutes"), f"{p}/estimated_minutes", 1, 1_000)
        if skeleton:
            stub_sections = module.get("sections")
            if not isinstance(stub_sections, list):
                c.error("schema.invalid_type", f"{p}/sections", "must be an array")
            elif stub_sections:
                c.error(
                    "skeleton.sections_not_empty",
                    f"{p}/sections",
                    "a skeleton module stub must carry an empty `sections` array; "
                    "section content is drafted one module at a time",
                )
            continue
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
                    _check_block(
                        c,
                        block,
                        f"{sp}/blocks/{k}",
                        diagrams_allowed=diagrams_allowed,
                    )


def _check_block(
    c: _Checker, value: Any, path: str, *, diagrams_allowed: bool = False
) -> None:
    if not isinstance(value, dict):
        c.error("schema.invalid_type", path, "must be an object")
        return
    errors_before = len(c.errors)
    block_type = value.get("type")
    known = block_type in BLOCK_TYPES or (
        diagrams_allowed and block_type == DIAGRAM_BLOCK_TYPE
    )
    if not known:
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
    required, optional = (
        _diagram_spec(value.get("kind"))
        if block_type == DIAGRAM_BLOCK_TYPE
        else specs[block_type]
    )
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
    elif block_type == DIAGRAM_BLOCK_TYPE:
        _check_diagram(c, block, path, errors_before)


def _valid_diagram_kind(kind: Any) -> bool:
    return isinstance(kind, str) and kind in KIND_FIELDS


def _diagram_spec(kind: Any) -> tuple[set[str], set[str]]:
    """Required and optional keys of a diagram block of ``kind``.

    A bad ``kind`` makes every kind field optional so it yields exactly one
    ``invalid diagram kind`` diagnostic and no cascade.
    """

    common = {"id", "type", "kind", "title"}
    if _valid_diagram_kind(kind):
        return common | set(KIND_FIELDS[kind]), {"caption"}
    all_kind_fields = {name for names in KIND_FIELDS.values() for name in names}
    return common, {"caption"} | all_kind_fields


def _check_diagram(
    c: _Checker, block: dict[str, Any], path: str, errors_before: int
) -> None:
    """Shape-check a diagram's raw dict, then apply the pure diagram rules."""

    kind = block.get("kind")
    if not _valid_diagram_kind(kind):
        if "kind" in block:
            c.error("schema.invalid_value", f"{path}/kind", "invalid diagram kind")
        return
    if "caption" in block:
        c.text(block["caption"], f"{path}/caption", markdown=True)
    if "hub" in block:
        c.text(block["hub"], f"{path}/hub")
    for name in KIND_FIELDS[kind]:
        if name == "hub" or name not in block:
            continue
        elements = c.array(block[name], f"{path}/{name}")
        if elements is None:
            continue
        required, optional = DIAGRAM_ELEMENT_SPECS[name]
        for i, raw in enumerate(elements):
            _check_diagram_element(c, raw, f"{path}/{name}/{i}", required, optional)
    if "criteria" in block and isinstance(block["criteria"], list):
        item_ids = _raw_item_ids(block.get("items"))
        for i, criterion in enumerate(block["criteria"]):
            if isinstance(criterion, dict) and "values" in criterion:
                _check_diagram_values(
                    c, criterion["values"], f"{path}/criteria/{i}/values", item_ids
                )
    if len(c.errors) == errors_before:
        for code, finding_path, message in diagram_findings(
            _normalize_block(block), path
        ):
            c.error(code, finding_path, message)


def _check_diagram_element(
    c: _Checker, value: Any, path: str, required: set[str], optional: set[str]
) -> None:
    element = c.obj(value, path, required, optional)
    if element is None:
        return
    for key in sorted((required | optional) - {"values"}):
        if key in element:
            c.text(element[key], f"{path}/{key}", markdown=key == "detail")


def _raw_item_ids(items: Any) -> list[str]:
    if not isinstance(items, list):
        return []
    return list(
        dict.fromkeys(
            item["id"]
            for item in items
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        )
    )


def _check_diagram_values(
    c: _Checker, values: Any, path: str, item_ids: list[str]
) -> None:
    if not isinstance(values, dict):
        c.error("schema.invalid_type", path, "must be an object")
        return
    for key, value in values.items():
        if key not in item_ids:
            c.error("diagram.unknown_value_key", f"{path}/{key}", f"unknown item ID {key!r}")
        c.text(value, f"{path}/{key}", markdown=True)
    for item_id in item_ids:
        if item_id not in values:
            c.error("diagram.missing_value", path, f"missing a value for item {item_id!r}")


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


def _goal_refs(c: _Checker, value: Any, path: str) -> None:
    values = c.array(value, path)
    if values is None:
        return
    for i, value in enumerate(values):
        _check_goal_id(c, value, f"{path}/{i}")


def _check_goal_id(c: _Checker, value: Any, path: str) -> None:
    goal_id = c.text(value, path)
    if goal_id is not None and not GOAL_ID_RE.fullmatch(value):
        c.error(
            "schema.invalid_goal_id",
            path,
            "must be an exact positive positional ID like 'goal-001'",
        )


def _check_goal_exclusions(c: _Checker, value: Any, path: str) -> None:
    exclusions = c.array(value, path)
    if exclusions is None:
        return
    for i, value in enumerate(exclusions):
        item_path = f"{path}/{i}"
        item = c.obj(value, item_path, {"goal_id", "reason"})
        if item is None:
            continue
        _check_goal_id(c, item.get("goal_id"), f"{item_path}/goal_id")
        c.text(item.get("reason"), f"{item_path}/reason")


def _integer(c: _Checker, value: Any, path: str, minimum: int, maximum: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        c.error("schema.invalid_type", path, "must be an integer")
        return
    if not minimum <= value <= maximum:
        c.error(
            "schema.invalid_value", path, f"must be between {minimum} and {maximum}"
        )


def _check_references_and_coverage(
    c: _Checker, root: dict[str, Any], *, skeleton: bool = False
) -> None:
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
    if not skeleton:
        # A skeleton's internal link targets mostly live inside sections that do
        # not exist yet; assembly re-parses the merged guide strictly, which is
        # where a genuinely dangling target is caught.
        for ref, path in c.internal_refs:
            if ref not in c.ids:
                c.error(
                    "link.unknown_internal_target",
                    path,
                    f"unknown internal target {ref!r}",
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
                if kind in {"rich_text", "callout", DIAGRAM_BLOCK_TYPE}:
                    taught.update(refs)
                if kind in interactive:
                    practiced.update(refs)
                    has_interaction = True
        if not has_interaction and not skeleton:
            c.error(
                "module.no_interaction",
                f"/modules/{mi}",
                "module must contain at least one interactive block",
            )
    for missing_type in sorted(() if skeleton else interactive - present_types):
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
        if skeleton:
            # `taught` and `practiced` are properties of block content, which a
            # skeleton has none of by construction.
            continue
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
        serves_goals=tuple(item.get("serves_goals", ())),
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
    if kind == DIAGRAM_BLOCK_TYPE:
        return _normalize_diagram(item, common)
    return Reflection(
        prompt=item["prompt"],
        guidance=item.get("guidance"),
        placeholder=item.get("placeholder"),
        **common,
    )


def _normalize_diagram(item: Mapping[str, Any], common: dict[str, Any]) -> Diagram:
    """Build a ``Diagram`` from a shape-checked raw dict; strings stay raw."""

    items = tuple(ComparisonItem(id=x["id"], label=x["label"]) for x in item.get("items", ()))
    return Diagram(
        kind=item["kind"],
        title=item["title"],
        caption=item.get("caption"),
        hub=item.get("hub"),
        nodes=tuple(
            DiagramNode(id=x["id"], label=x["label"], detail=x.get("detail"))
            for x in item.get("nodes", ())
        ),
        edges=tuple(
            DiagramEdge(from_id=x["from"], to_id=x["to"], label=x.get("label"))
            for x in item.get("edges", ())
        ),
        events=tuple(
            TimelineEvent(
                id=x["id"], when=x["when"], label=x["label"], detail=x.get("detail")
            )
            for x in item.get("events", ())
        ),
        items=items,
        criteria=tuple(
            ComparisonCriterion(
                id=x["id"],
                label=x["label"],
                values=tuple(
                    ComparisonValue(item_id=entry.id, text=x["values"][entry.id])
                    for entry in items
                    if entry.id in x["values"]
                ),
            )
            for x in item.get("criteria", ())
        ),
        **common,
    )
