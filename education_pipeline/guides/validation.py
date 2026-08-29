"""Pure deterministic validation for Interactive Guide v1."""

from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass, replace
import hashlib
import json
import re
from typing import Iterable

from education_pipeline.privacy import normalize_private_value, private_value_fingerprint
from education_pipeline.text_scalars import (
    SURROGATE_REPLACEMENT,
    has_surrogates,
    replace_surrogates,
)

from .canonical import guide_sha256
from .model import Callout, Guide, KnowledgeCheck, RichText, Scenario, WorkedReveal
from .parse import ParseDiagnostic, normalize_guide, parse_guide
from .personalization import AuthoritativeGoal, index_personalization_annotations
from .projection import public_guide_projection
from .reports import Finding, ValidationReport

#: Raw-source validation size cap, applied before any parsing. Shared with
#: ``runs.py`` (``_guide_source_sha`` and ``_validated_final``) so the cap
#: cannot drift between sites.
MAX_GUIDE_SOURCE_BYTES = 2_000_000


@dataclass(frozen=True)
class Rule:
    severity: str
    blocking: bool
    waivable: bool
    remediation: str
    stage: str


@dataclass(frozen=True)
class ValidationContext:
    """Deterministic contract and static-runtime observations for validation."""

    sources_required: bool = False
    render_succeeded: bool = True
    assets_match: bool = True
    controls_have_labels: bool = True
    heading_order_valid: bool = True


@dataclass(frozen=True)
class PersonalizationValidationContext:
    """Run-owned personalization state supplied to deterministic validation.

    Standalone validation omits this context. Wave 2 consumes the frozen
    authoritative-goal shape when guide-source goal annotations are added.
    """

    profile_present: bool
    authoritative_goal_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class CalibrationContext:
    """Run-owned blueprint/time/difficulty inputs for calibration checks.

    Standalone validation omits this context and produces no calibration
    findings, so old workspaces and direct library use are unchanged. All
    fields reference declared run configuration or profile-field *presence*;
    finding messages never echo profile values.
    """

    configured_blueprint: str | None = None
    time_budget_minutes: int | None = None
    attention_constraints_present: bool = False
    learner_skill_level: str | None = None


#: Deterministic reading-time model constants, pinned by tests so calibration
#: only changes deliberately.
READING_TIME_WPM = 200
READING_TIME_BLOCK_SECONDS = {
    "rich_text": 0,
    "callout": 0,
    "knowledge_check": 45,
    "worked_reveal": 90,
    "scenario": 60,
    "reflection": 60,
}

#: Mechanical mapping between declared course difficulty and the free-text
#: profile skill level. ``mixed`` difficulty and unmappable or ambiguous
#: skill text never fire the mismatch rule.
DIFFICULTY_LEVELS = {"introductory": 0, "intermediate": 1, "advanced": 2}
SKILL_LEVEL_KEYWORDS = {
    "beginner": 0,
    "novice": 0,
    "introductory": 0,
    "intermediate": 1,
    "advanced": 2,
    "expert": 2,
    "experienced": 2,
}


RULES = {
    "json.invalid": Rule("blocker", True, False, "Provide one valid UTF-8 JSON object.", "draft"),
    "json.invalid_utf8": Rule("blocker", True, False, "Encode the guide as UTF-8.", "draft"),
    "schema.unsupported_version": Rule("blocker", True, False, "Use guide schema version 1.0.", "draft"),
    "schema.missing_field": Rule("blocker", True, False, "Add the required field.", "draft"),
    "schema.unknown_field": Rule("error", True, False, "Remove the unregistered field.", "draft"),
    "schema.invalid_type": Rule("blocker", True, False, "Use the required JSON value type.", "draft"),
    "schema.invalid_id": Rule("error", True, False, "Use a stable lowercase guide ID.", "draft"),
    "schema.duplicate_id": Rule("blocker", True, False, "Give every guide object a unique ID.", "draft"),
    "schema.unknown_reference": Rule("blocker", True, False, "Reference a registered guide ID.", "draft"),
    "schema.unknown_block_type": Rule("blocker", True, False, "Use a supported guide block type.", "draft"),
    "schema.size_limit": Rule("blocker", True, False, "Reduce the guide to the supported size.", "draft"),
    "schema.cardinality": Rule("blocker", True, False, "Provide the required number of items.", "draft"),
    "schema.invalid_value": Rule("blocker", True, False, "Use a supported value.", "draft"),
    "schema.duplicate_reference": Rule("error", True, False, "Remove the duplicate reference.", "draft"),
    "content.raw_html": Rule("blocker", True, False, "Remove raw HTML and use safe Markdown.", "draft"),
    "link.unsafe_scheme": Rule("blocker", True, False, "Use https, http, or a known guide fragment.", "draft"),
    "link.unsafe_target": Rule("blocker", True, False, "Use https, http, or a known guide fragment.", "draft"),
    "link.image_not_supported": Rule("blocker", True, False, "Remove the Markdown image.", "draft"),
    "link.unknown_internal_target": Rule("error", True, False, "Link to a registered guide ID.", "draft"),
    "privacy.exact_private_value": Rule("blocker", True, True, "Remove or generalize the private value.", "draft"),
    "privacy.possible_identifier": Rule("warning", False, True, "Review and remove private identifiers.", "draft"),
    "content.prompt_leak": Rule("blocker", True, True, "Remove generation instructions from learner content.", "draft"),
    "content.placeholder": Rule("error", True, True, "Replace placeholder text with complete content.", "draft"),
    "outcome.unassigned": Rule("error", True, True, "Assign the outcome to a module.", "outline"),
    "outcome.untaught": Rule("error", True, True, "Teach the outcome in rich text or a callout.", "outline"),
    "outcome.unassessed": Rule("error", True, True, "Reference the outcome from an interactive block.", "outline"),
    "module.no_interaction": Rule("error", True, True, "Add an interaction to the module.", "outline"),
    "interaction.missing_required_type": Rule("error", True, True, "Add the required interaction type.", "outline"),
    "knowledge_check.invalid_answer_set": Rule("blocker", True, False, "Configure a valid correct-answer set.", "draft"),
    "scenario.invalid_quality_set": Rule("blocker", True, False, "Configure exactly one best choice.", "draft"),
    "worked_reveal.too_few_steps": Rule("error", True, True, "Provide at least two reveal steps.", "draft"),
    "personalization.no_visible_connection": Rule("warning", False, True, "Add an appropriate learner-facing connection.", "draft"),
    "personalization.goal_uncovered": Rule("warning", False, True, "Serve the goal from a module or outcome, or add a valid exclusion.", "draft"),
    "personalization.no_annotations": Rule("warning", False, True, "Add opaque goal references or valid exclusions for the attached profile goals.", "draft"),
    "personalization.dangling_goal_ref": Rule("error", True, False, "Use only authoritative goal ids from the attached profile snapshot.", "draft"),
    "personalization.duplicate_goal_ref": Rule("error", True, False, "Remove the repeated goal id from this annotation.", "draft"),
    "personalization.unexpected_annotations": Rule("warning", False, True, "Remove personalization annotations or attach the intended profile snapshot.", "draft"),
    "personalization.trace_integrity": Rule("error", True, False, "Correct the source annotations and rebuild the personalization trace.", "draft"),
    "personalization.no_profile": Rule("info", False, False, "Attach a learner profile to enable personalization checks.", "draft"),
    "time.module_total_mismatch": Rule("warning", False, True, "Align course and module time estimates.", "outline"),
    "content.empty": Rule("blocker", True, False, "Provide non-empty learner content.", "draft"),
    "content.excessive_length": Rule("warning", False, True, "Split or shorten the content.", "draft"),
    "source.unknown_reference": Rule("blocker", True, False, "Reference a registered source.", "draft"),
    "source.missing_for_required_claim": Rule("warning", False, True, "Add a source for the claim.", "draft"),
    "source.invalid_url": Rule("error", True, False, "Use an absolute http or https source URL.", "draft"),
    "markdown.invalid_heading_level": Rule("error", True, True, "Use headings below the runtime-owned page structure.", "draft"),
    "markdown.unclosed_fence": Rule("error", True, True, "Close the fenced code block.", "draft"),
    "runtime.render_failed": Rule("blocker", True, False, "Correct content that the runtime cannot render.", "repair"),
    "runtime.asset_mismatch": Rule("blocker", True, False, "Use the matching packaged runtime assets.", "repair"),
    "a11y.control_label_missing": Rule("blocker", True, False, "Provide a visible control label.", "repair"),
    "a11y.heading_order": Rule("error", True, True, "Use a logical heading order.", "repair"),
    "a11y.color_only_instruction": Rule("error", True, True, "Describe the cue without relying on color alone.", "repair"),
    "blueprint.unknown": Rule("warning", False, False, "Use a registered blueprint id.", "draft"),
    "blueprint.contract_mismatch": Rule("error", True, True, "Match the run's configured blueprint.", "draft"),
    "time.budget_exceeded": Rule("warning", False, False, "Trim the course toward the stated time budget.", "outline"),
    "time.budget_underrun": Rule("info", False, False, "Consider whether the course fills the stated time budget.", "outline"),
    "time.estimate_implausible": Rule("warning", False, False, "Align the declared estimate with the actual content volume.", "draft"),
    "time.module_overrun": Rule("warning", False, False, "Split the module into shorter sittings.", "outline"),
    "difficulty.learner_mismatch": Rule("warning", False, False, "Align the declared difficulty with the learner's level.", "outline"),
}

_PLACEHOLDER = re.compile(r"\b(?:todo|tbd|lorem ipsum|insert (?:text|content) here)\b", re.I)
_PROMPT_LEAK = re.compile(r"(?:system prompt|ignore (?:all |the )?previous instructions|you are (?:an? )?(?:ai|language model))", re.I)
_POSSIBLE_ID = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
_GENERIC_PRIVATE = {"none", "unknown", "n/a", "na", "user", "learner", "student", "private"}


def _finding(rule_id: str, path: str, message: str, identity: str = "", related_ids: tuple[str, ...] = ()) -> Finding:
    rule = RULES[rule_id]
    suffix = identity or path or "root"
    return Finding(f"{rule_id}:{suffix}", rule_id, rule.severity, rule.blocking, rule.waivable, path, message, rule.remediation, related_ids, rule.stage)


def _diagnostic_finding(item: ParseDiagnostic, private_values: tuple[str, ...]) -> Finding:
    rule_id = item.code
    if rule_id == "schema.unknown_reference" and "/source_ids/" in item.path:
        rule_id = "source.unknown_reference"
    elif rule_id == "schema.cardinality" and item.path.endswith("/steps"):
        rule_id = "worked_reveal.too_few_steps"
    elif rule_id == "link.unsafe_target":
        rule_id = "link.unsafe_scheme"
    if rule_id == "source.invalid_url":
        pass
    elif rule_id not in RULES:
        rule_id = "schema.invalid_value"
    message = item.message
    for private in private_values:
        flexible_whitespace = re.escape(private).replace(r"\ ", r"\s+")
        message = re.sub(flexible_whitespace, "[redacted]", message, flags=re.I)
    stable_id = ""
    match = re.search(r"['\"]([a-z][a-z0-9-]{0,63})['\"]", message)
    if match and rule_id in {
        "outcome.unassigned", "outcome.untaught", "outcome.unassessed",
        "interaction.missing_required_type", "schema.unknown_reference",
    }:
        stable_id = match.group(1)
    return _finding(rule_id, item.path, message, stable_id)


def _replace_invalid_scalar_codepoints(value: str) -> str:
    return "".join(
        "\N{REPLACEMENT CHARACTER}" if 0xD800 <= ord(character) <= 0xDFFF else character
        for character in value
    )


def _has_invalid_scalar_codepoints(value: str) -> bool:
    return any(0xD800 <= ord(character) <= 0xDFFF for character in value)


def _normalize_validation_text(value: str) -> str:
    """Normalize untrusted guide/report text without weakening profile parsing."""

    return normalize_private_value(_replace_invalid_scalar_codepoints(value))


def _sanitize_guide_value(value: object) -> object:
    if isinstance(value, str):
        return _replace_invalid_scalar_codepoints(value)
    if isinstance(value, tuple):
        return tuple(_sanitize_guide_value(child) for child in value)
    if is_dataclass(value):
        return replace(
            value,
            **{
                field.name: _sanitize_guide_value(getattr(value, field.name))
                for field in fields(value)
            },
        )
    return value


def _value_has_invalid_scalar_codepoints(value: object) -> bool:
    if isinstance(value, str):
        return _has_invalid_scalar_codepoints(value)
    if isinstance(value, dict):
        return any(
            _value_has_invalid_scalar_codepoints(key)
            or _value_has_invalid_scalar_codepoints(child)
            for key, child in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(_value_has_invalid_scalar_codepoints(child) for child in value)
    if is_dataclass(value):
        return any(
            _value_has_invalid_scalar_codepoints(getattr(value, field.name))
            for field in fields(value)
        )
    return False


def _json_input_has_invalid_scalar_codepoints(value: str | bytes) -> bool:
    try:
        decoded = value.decode("utf-8") if isinstance(value, bytes) else value
        return _value_has_invalid_scalar_codepoints(json.loads(decoded))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False


def _invalid_scalar_finding() -> Finding:
    return _finding(
        "schema.invalid_value",
        "",
        "Guide contains an invalid Unicode scalar value.",
        "invalid-unicode-scalar",
    )


def _contains_private_value(value: str, private_values: tuple[str, ...]) -> bool:
    normalized = _normalize_validation_text(value)
    return any(private in normalized for private in private_values)


def _sanitize_finding(item: Finding, private_values: tuple[str, ...]) -> Finding:
    """Remove protected values from every source-derived finding surface."""

    item = replace(
        item,
        id=_replace_invalid_scalar_codepoints(item.id),
        path=_replace_invalid_scalar_codepoints(item.path),
        message=_replace_invalid_scalar_codepoints(item.message),
        remediation=_replace_invalid_scalar_codepoints(item.remediation),
        related_ids=tuple(
            _replace_invalid_scalar_codepoints(value) for value in item.related_ids
        ),
    )
    if not private_values:
        return item

    exact_private_finding = item.rule_id == "privacy.exact_private_value"
    finding_id = item.id
    if not exact_private_finding and _contains_private_value(finding_id, private_values):
        safe_identity = hashlib.sha256(
            _normalize_validation_text(finding_id).encode("utf-8")
        ).hexdigest()[:12]
        finding_id = f"{item.rule_id}:[redacted-{safe_identity}]"
    path = (
        "/[redacted]"
        if _contains_private_value(item.path, private_values)
        else item.path
    )
    message = item.message
    if not exact_private_finding and _contains_private_value(message, private_values):
        message = "[redacted]"
    remediation = (
        "[redacted]"
        if _contains_private_value(item.remediation, private_values)
        else item.remediation
    )
    related_ids = tuple(
        "[redacted]" if _contains_private_value(value, private_values) else value
        for value in item.related_ids
    )
    return replace(
        item,
        id=finding_id,
        path=path,
        message=message,
        remediation=remediation,
        related_ids=related_ids,
    )


def _validation_report(
    guide_schema_version: str,
    phase: str,
    guide_digest: str,
    findings: Iterable[Finding],
    private_values: tuple[str, ...],
) -> ValidationReport:
    return ValidationReport(
        guide_schema_version,
        phase,
        guide_digest,
        tuple(_sanitize_finding(item, private_values) for item in findings),
    )


def _text_fields(value: object, path: str = "") -> Iterable[tuple[str, str]]:
    if is_dataclass(value):
        for field in fields(value):
            child = getattr(value, field.name)
            yield from _text_fields(child, f"{path}/{field.name}")
    elif isinstance(value, tuple):
        for index, child in enumerate(value):
            yield from _text_fields(child, f"{path}/{index}")
    elif isinstance(value, str):
        yield path, value


def _guide_has_personalization_annotations(guide: Guide) -> bool:
    return bool(
        guide.course.goal_exclusions
        or any(outcome.serves_goals for outcome in guide.outcomes)
        or any(module.serves_goals for module in guide.modules)
    )


def _personalization_findings(
    guide: Guide,
    context: PersonalizationValidationContext,
) -> tuple[Finding, ...]:
    annotations_present = _guide_has_personalization_annotations(guide)
    if not context.profile_present:
        findings = [
            _finding(
                "personalization.no_profile",
                "",
                "No learner profile snapshot is attached; personalization checks were skipped.",
            )
        ]
        if annotations_present:
            findings.append(
                _finding(
                    "personalization.unexpected_annotations",
                    "",
                    "Guide source contains personalization annotations without an attached profile snapshot.",
                    "unprofiled-annotations",
                )
            )
        return tuple(findings)

    goals = tuple(
        AuthoritativeGoal(goal_id=goal_id, goal_text="")
        for goal_id in context.authoritative_goal_ids
    )
    indexed = index_personalization_annotations(guide, goals)
    findings: list[Finding] = []
    if goals and not annotations_present:
        findings.append(
            _finding(
                "personalization.no_annotations",
                "",
                "The attached profile declares goals but the guide source has no goal annotations.",
                "profile-goals",
            )
        )
    for violation in indexed.violations:
        rule_id = f"personalization.{violation.code}"
        if violation.element_kind == "exclusion":
            path = "/course/goal_exclusions"
        elif violation.element_kind == "outcome":
            index = next(
                index
                for index, outcome in enumerate(guide.outcomes)
                if outcome.id == violation.element_id
            )
            path = f"/outcomes/{index}/serves_goals"
        else:
            index = next(
                index
                for index, module in enumerate(guide.modules)
                if module.id == violation.element_id
            )
            path = f"/modules/{index}/serves_goals"
        findings.append(
            _finding(
                rule_id,
                path,
                "A personalization annotation contains an invalid goal reference.",
                f"{violation.element_kind}-{violation.element_id}-{violation.goal_id}",
                (violation.element_id, violation.goal_id),
            )
        )
    for goal in indexed.goals:
        covered = bool(
            goal.serving_module_ids
            or goal.serving_outcome_ids
            or any(exclusion.reason.strip() for exclusion in goal.exclusions)
        )
        if not covered:
            findings.append(
                _finding(
                    "personalization.goal_uncovered",
                    "",
                    "An authoritative learner goal is not served or validly excluded.",
                    goal.goal_id,
                    (goal.goal_id,),
                )
            )
    return tuple(findings)


def estimated_reading_minutes(guide: Guide) -> float:
    """Deterministic reading-time estimate over the public guide projection.

    Words per minute over every learner-facing text field plus fixed
    per-interaction constants; see the pinned tables above.
    """

    checked = public_guide_projection(guide)
    words = sum(len(text.split()) for _, text in _text_fields(checked))
    seconds = words / READING_TIME_WPM * 60
    for module in checked.modules:
        for section in module.sections:
            for block in section.blocks:
                seconds += READING_TIME_BLOCK_SECONDS.get(block.type, 0)
    return seconds / 60


def _mapped_skill_level(value: str) -> int | None:
    """Map free-text profile skill wording to a difficulty level, or None.

    Ambiguous text (keywords from more than one level) and text with no
    known keyword are unmappable and never fire the mismatch rule.
    """

    words = re.findall(r"[a-z]+", value.casefold())
    levels = {SKILL_LEVEL_KEYWORDS[word] for word in words if word in SKILL_LEVEL_KEYWORDS}
    if len(levels) != 1:
        return None
    return next(iter(levels))


def _calibration_findings(
    guide: Guide, context: CalibrationContext
) -> tuple[Finding, ...]:
    """Blueprint/time/difficulty calibration checks over declared intent.

    Heuristics, not structural defects: everything except
    ``blueprint.contract_mismatch`` is nonblocking and non-waivable. Messages
    reference profile-field presence only, never profile values.
    """

    from .blueprints import list_blueprints

    registered_ids = {blueprint.id for blueprint in list_blueprints()}
    course = guide.course
    findings: list[Finding] = []

    if context.configured_blueprint is None:
        if course.blueprint not in registered_ids:
            findings.append(
                _finding(
                    "blueprint.unknown",
                    "/course/blueprint",
                    f"Course blueprint {course.blueprint!r} is not a registered blueprint.",
                    course.id,
                    (course.id,),
                )
            )
    elif course.blueprint != context.configured_blueprint:
        findings.append(
            _finding(
                "blueprint.contract_mismatch",
                "/course/blueprint",
                f"Course blueprint {course.blueprint!r} does not match the run's "
                f"configured blueprint {context.configured_blueprint!r}.",
                course.id,
                (course.id,),
            )
        )

    estimate = course.estimated_minutes
    budget = context.time_budget_minutes
    if budget is not None:
        if estimate > budget * 1.1:
            findings.append(
                _finding(
                    "time.budget_exceeded",
                    "/course/estimated_minutes",
                    f"Course estimate of {estimate} minutes exceeds the stated time "
                    f"budget of {budget} minutes by more than 10%.",
                    course.id,
                    (course.id,),
                )
            )
        elif estimate < budget * 0.5:
            findings.append(
                _finding(
                    "time.budget_underrun",
                    "/course/estimated_minutes",
                    f"Course estimate of {estimate} minutes is under half the stated "
                    f"time budget of {budget} minutes.",
                    course.id,
                    (course.id,),
                )
            )

    model_minutes = estimated_reading_minutes(guide)
    if model_minutes > 0 and (
        estimate > 2 * model_minutes or estimate < model_minutes / 2
    ):
        findings.append(
            _finding(
                "time.estimate_implausible",
                "/course/estimated_minutes",
                f"Declared course estimate of {estimate} minutes disagrees with the "
                f"deterministic reading-time estimate of about "
                f"{max(1, round(model_minutes))} minutes by more than a factor of two.",
                course.id,
                (course.id,),
            )
        )

    if context.attention_constraints_present:
        for index, module in enumerate(guide.modules):
            if module.estimated_minutes > 45:
                findings.append(
                    _finding(
                        "time.module_overrun",
                        f"/modules/{index}/estimated_minutes",
                        f"Module runs {module.estimated_minutes} minutes while the "
                        "attached learner profile declares attention constraints.",
                        module.id,
                        (module.id,),
                    )
                )

    if context.learner_skill_level is not None:
        skill = _mapped_skill_level(context.learner_skill_level)
        declared = DIFFICULTY_LEVELS.get(course.difficulty)
        if skill is not None and declared is not None and abs(declared - skill) >= 2:
            findings.append(
                _finding(
                    "difficulty.learner_mismatch",
                    "/course/difficulty",
                    f"Declared course difficulty {course.difficulty!r} is two or more "
                    "levels away from the skill level declared in the attached "
                    "learner profile.",
                    course.id,
                    (course.id,),
                )
            )

    return tuple(findings)


def validation_guide_sha256(value: Guide | str | bytes) -> str:
    """Hash the exact fail-closed guide projection used by validation."""

    if isinstance(value, Guide):
        sanitized = _sanitize_guide_value(value)
        assert isinstance(sanitized, Guide)
        return guide_sha256(sanitized)

    parse_input = (
        _replace_invalid_scalar_codepoints(value)
        if isinstance(value, str)
        else value
    )
    raw = parse_input.encode("utf-8") if isinstance(parse_input, str) else parse_input
    if len(raw) > MAX_GUIDE_SOURCE_BYTES:
        return hashlib.sha256(raw).hexdigest()
    parsed = parse_guide(parse_input)
    if not parsed.ok:
        return hashlib.sha256(raw).hexdigest()
    guide = _sanitize_guide_value(normalize_guide(parsed))
    assert isinstance(guide, Guide)
    return guide_sha256(guide)


def validate_guide(
    value: Guide | str | bytes,
    *,
    phase: str = "final",
    private_values: Iterable[str] = (),
    context: ValidationContext = ValidationContext(),
    personalization_context: PersonalizationValidationContext | None = None,
    calibration_context: CalibrationContext | None = None,
) -> ValidationReport:
    """Return a canonical, timestamp-free report for a guide or raw guide JSON."""
    normalized_private = tuple(_normalize_validation_text(item) for item in private_values)
    supplied_private = tuple(
        item
        for item in normalized_private
        if len(item) >= 5 and item not in _GENERIC_PRIVATE
    )
    personalization_findings: tuple[Finding, ...] = ()
    if personalization_context is not None and not personalization_context.profile_present:
        personalization_findings = (
            _finding(
                "personalization.no_profile",
                "",
                "No learner profile snapshot is attached; personalization checks were skipped.",
            ),
        )
    invalid_scalar_replaced = False
    if isinstance(value, Guide):
        invalid_scalar_replaced = _value_has_invalid_scalar_codepoints(value)
        guide = _sanitize_guide_value(value)
        assert isinstance(guide, Guide)
    else:
        invalid_scalar_replaced = (
            isinstance(value, str) and _has_invalid_scalar_codepoints(value)
        )
        parse_input = (
            _replace_invalid_scalar_codepoints(value)
            if isinstance(value, str)
            else value
        )
        raw = parse_input.encode("utf-8") if isinstance(parse_input, str) else parse_input
        if len(raw) > MAX_GUIDE_SOURCE_BYTES:
            digest = hashlib.sha256(raw).hexdigest()
            finding = _finding("schema.size_limit", "", "Guide exceeds the 2,000,000-byte validation limit.")
            invalid_findings = (
                (_invalid_scalar_finding(),) if invalid_scalar_replaced else ()
            )
            return _validation_report(
                "1.0",
                phase,
                digest,
                (finding,) + invalid_findings + personalization_findings,
                supplied_private,
            )
        parsed = parse_guide(parse_input)
        if not parsed.ok:
            digest = hashlib.sha256(raw).hexdigest()
            invalid_scalar_replaced = (
                invalid_scalar_replaced
                or _json_input_has_invalid_scalar_codepoints(parse_input)
            )
            invalid_findings = (
                (_invalid_scalar_finding(),) if invalid_scalar_replaced else ()
            )
            return _validation_report(
                "1.0",
                phase,
                digest,
                tuple(_diagnostic_finding(x, supplied_private) for x in parsed.diagnostics)
                + invalid_findings
                + personalization_findings,
                supplied_private,
            )
        normalized_guide = normalize_guide(parsed)
        invalid_scalar_replaced = (
            invalid_scalar_replaced
            or _value_has_invalid_scalar_codepoints(normalized_guide)
        )
        guide = _sanitize_guide_value(normalized_guide)
        assert isinstance(guide, Guide)

    if personalization_context is not None:
        personalization_findings = _personalization_findings(
            guide,
            personalization_context,
        )
    findings: list[Finding] = list(personalization_findings)
    if invalid_scalar_replaced:
        findings.append(_invalid_scalar_finding())
    checked_guide = public_guide_projection(guide)
    texts = tuple(_text_fields(checked_guide))
    denylist = []
    for supplied in supplied_private:
        denylist.append((supplied, private_value_fingerprint(supplied)))
    for path, text in texts:
        folded = _normalize_validation_text(text)
        for private, fingerprint in denylist:
            if private in folded:
                findings.append(_finding("privacy.exact_private_value", path, f"Content matches a private denylist value (fingerprint {fingerprint}).", fingerprint))
        if _POSSIBLE_ID.search(text):
            findings.append(_finding("privacy.possible_identifier", path, "Content may contain a private identifier; the suspected value is redacted."))
        if _PROMPT_LEAK.search(text):
            findings.append(_finding("content.prompt_leak", path, "Content appears to include model or prompt instructions."))
        if _PLACEHOLDER.search(text):
            findings.append(_finding("content.placeholder", path, "Content contains placeholder language."))
        if path.endswith(("/markdown", "/summary", "/description", "/definition", "/note", "/prompt")):
            fences = len(re.findall(r"(?m)^\s*```", text))
            if fences % 2:
                findings.append(_finding("markdown.unclosed_fence", path, "Markdown contains an unclosed fenced code block."))
            headings = [len(x) for x in re.findall(r"(?m)^(#{1,6})\s", text)]
            if any(level == 1 for level in headings):
                findings.append(_finding("markdown.invalid_heading_level", path, "Learner Markdown must not contain a level-one heading."))
            if re.search(r"\b(?:red|green|blue|yellow)\s+(?:button|choice|text|area)\b", text, re.I):
                findings.append(_finding("a11y.color_only_instruction", path, "Instruction may rely on color alone."))

    if sum(module.estimated_minutes for module in checked_guide.modules) != checked_guide.course.estimated_minutes:
        findings.append(_finding("time.module_total_mismatch", "/course/estimated_minutes", "Course duration does not equal the sum of module durations.", checked_guide.course.id, (checked_guide.course.id,)))
    if not checked_guide.course.learner_summary:
        findings.append(_finding("personalization.no_visible_connection", "/course", "Guide has no explicit learner-facing personalization summary.", checked_guide.course.id, (checked_guide.course.id,)))
    for mi, module in enumerate(checked_guide.modules):
        for si, section in enumerate(module.sections):
            for bi, block in enumerate(section.blocks):
                path = f"/modules/{mi}/sections/{si}/blocks/{bi}"
                if isinstance(block, KnowledgeCheck):
                    correct = sum(choice.correct for choice in block.choices)
                    invalid = correct != 1 if block.mode == "single" else correct in {0, len(block.choices)}
                    if invalid:
                        findings.append(_finding("knowledge_check.invalid_answer_set", path, "Knowledge check has an invalid answer set.", block.id, (block.id,)))
                elif isinstance(block, Scenario) and sum(choice.quality == "best" for choice in block.choices) != 1:
                    findings.append(_finding("scenario.invalid_quality_set", path, "Scenario must contain exactly one best choice.", block.id, (block.id,)))
                elif isinstance(block, WorkedReveal) and len(block.steps) < 2:
                    findings.append(_finding("worked_reveal.too_few_steps", path, "Worked reveal has fewer than two steps.", block.id, (block.id,)))
                if context.sources_required and isinstance(block, (RichText, Callout)) and not block.source_ids:
                    findings.append(_finding("source.missing_for_required_claim", path, "Source-required content has no source reference.", block.id, (block.id,)))
    static_checks = (
        (context.render_succeeded, "runtime.render_failed", "Static guide rendering failed."),
        (context.assets_match, "runtime.asset_mismatch", "Packaged runtime assets do not match the expected assets."),
        (context.controls_have_labels, "a11y.control_label_missing", "A static interactive control has no accessible label."),
        (context.heading_order_valid, "a11y.heading_order", "The rendered static heading order is not logical."),
    )
    for passed, rule_id, message in static_checks:
        if not passed:
            findings.append(_finding(rule_id, "/modules", message))
    if calibration_context is not None:
        findings.extend(_calibration_findings(checked_guide, calibration_context))
    return _validation_report(
        guide.schema_version,
        phase,
        validation_guide_sha256(guide),
        findings,
        supplied_private,
    )
