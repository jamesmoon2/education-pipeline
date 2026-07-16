"""Pure deterministic validation for Interactive Guide v1."""

from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
import hashlib
import re
from typing import Iterable

from .canonical import guide_sha256
from .model import Callout, Guide, KnowledgeCheck, RichText, Scenario, WorkedReveal
from .parse import ParseDiagnostic, normalize_guide, parse_guide
from .reports import Finding, ValidationReport


@dataclass(frozen=True)
class Rule:
    severity: str
    blocking: bool
    waivable: bool
    remediation: str


@dataclass(frozen=True)
class ValidationContext:
    """Deterministic contract and static-runtime observations for validation."""

    sources_required: bool = False
    render_succeeded: bool = True
    assets_match: bool = True
    controls_have_labels: bool = True
    heading_order_valid: bool = True


RULES = {
    "json.invalid": Rule("blocker", True, False, "Provide one valid UTF-8 JSON object."),
    "json.invalid_utf8": Rule("blocker", True, False, "Encode the guide as UTF-8."),
    "schema.unsupported_version": Rule("blocker", True, False, "Use guide schema version 1.0."),
    "schema.missing_field": Rule("blocker", True, False, "Add the required field."),
    "schema.unknown_field": Rule("error", True, False, "Remove the unregistered field."),
    "schema.invalid_type": Rule("blocker", True, False, "Use the required JSON value type."),
    "schema.invalid_id": Rule("error", True, False, "Use a stable lowercase guide ID."),
    "schema.duplicate_id": Rule("blocker", True, False, "Give every guide object a unique ID."),
    "schema.unknown_reference": Rule("blocker", True, False, "Reference a registered guide ID."),
    "schema.unknown_block_type": Rule("blocker", True, False, "Use a supported guide block type."),
    "schema.size_limit": Rule("blocker", True, False, "Reduce the guide to the supported size."),
    "schema.cardinality": Rule("blocker", True, False, "Provide the required number of items."),
    "schema.invalid_value": Rule("blocker", True, False, "Use a supported value."),
    "schema.duplicate_reference": Rule("error", True, False, "Remove the duplicate reference."),
    "content.raw_html": Rule("blocker", True, False, "Remove raw HTML and use safe Markdown."),
    "link.unsafe_scheme": Rule("blocker", True, False, "Use https, http, or a known guide fragment."),
    "link.unsafe_target": Rule("blocker", True, False, "Use https, http, or a known guide fragment."),
    "link.image_not_supported": Rule("blocker", True, False, "Remove the Markdown image."),
    "link.unknown_internal_target": Rule("error", True, False, "Link to a registered guide ID."),
    "privacy.exact_private_value": Rule("blocker", True, True, "Remove or generalize the private value."),
    "privacy.possible_identifier": Rule("warning", False, True, "Review and remove private identifiers."),
    "content.prompt_leak": Rule("blocker", True, True, "Remove generation instructions from learner content."),
    "content.placeholder": Rule("error", True, True, "Replace placeholder text with complete content."),
    "outcome.unassigned": Rule("error", True, True, "Assign the outcome to a module."),
    "outcome.untaught": Rule("error", True, True, "Teach the outcome in rich text or a callout."),
    "outcome.unassessed": Rule("error", True, True, "Reference the outcome from an interactive block."),
    "module.no_interaction": Rule("error", True, True, "Add an interaction to the module."),
    "interaction.missing_required_type": Rule("error", True, True, "Add the required interaction type."),
    "knowledge_check.invalid_answer_set": Rule("blocker", True, False, "Configure a valid correct-answer set."),
    "scenario.invalid_quality_set": Rule("blocker", True, False, "Configure exactly one best choice."),
    "worked_reveal.too_few_steps": Rule("error", True, True, "Provide at least two reveal steps."),
    "personalization.no_visible_connection": Rule("warning", False, True, "Add an appropriate learner-facing connection."),
    "time.module_total_mismatch": Rule("warning", False, True, "Align course and module time estimates."),
    "content.empty": Rule("blocker", True, False, "Provide non-empty learner content."),
    "content.excessive_length": Rule("warning", False, True, "Split or shorten the content."),
    "source.unknown_reference": Rule("blocker", True, False, "Reference a registered source."),
    "source.missing_for_required_claim": Rule("warning", False, True, "Add a source for the claim."),
    "source.invalid_url": Rule("error", True, False, "Use an absolute http or https source URL."),
    "markdown.invalid_heading_level": Rule("error", True, True, "Use headings below the runtime-owned page structure."),
    "markdown.unclosed_fence": Rule("error", True, True, "Close the fenced code block."),
    "runtime.render_failed": Rule("blocker", True, False, "Correct content that the runtime cannot render."),
    "runtime.asset_mismatch": Rule("blocker", True, False, "Use the matching packaged runtime assets."),
    "a11y.control_label_missing": Rule("blocker", True, False, "Provide a visible control label."),
    "a11y.heading_order": Rule("error", True, True, "Use a logical heading order."),
    "a11y.color_only_instruction": Rule("error", True, True, "Describe the cue without relying on color alone."),
}

_PLACEHOLDER = re.compile(r"\b(?:todo|tbd|lorem ipsum|insert (?:text|content) here)\b", re.I)
_PROMPT_LEAK = re.compile(r"(?:system prompt|ignore (?:all |the )?previous instructions|you are (?:an? )?(?:ai|language model))", re.I)
_POSSIBLE_ID = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
_GENERIC_PRIVATE = {"none", "unknown", "n/a", "na", "user", "learner", "student", "private"}


def _finding(rule_id: str, path: str, message: str, identity: str = "", related_ids: tuple[str, ...] = ()) -> Finding:
    rule = RULES[rule_id]
    suffix = identity or path or "root"
    return Finding(f"{rule_id}:{suffix}", rule_id, rule.severity, rule.blocking, rule.waivable, path, message, rule.remediation, related_ids)


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
        message = re.sub(re.escape(private), "[redacted]", message, flags=re.I)
    stable_id = ""
    match = re.search(r"['\"]([a-z][a-z0-9-]{0,63})['\"]", message)
    if match and rule_id in {
        "outcome.unassigned", "outcome.untaught", "outcome.unassessed",
        "interaction.missing_required_type", "schema.unknown_reference",
    }:
        stable_id = match.group(1)
    return _finding(rule_id, item.path, message, stable_id)


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


def validate_guide(
    value: Guide | str | bytes,
    *,
    phase: str = "final",
    private_values: Iterable[str] = (),
    context: ValidationContext = ValidationContext(),
) -> ValidationReport:
    """Return a canonical, timestamp-free report for a guide or raw guide JSON."""
    supplied_private = tuple(
        " ".join(item.split())
        for item in private_values
        if len(" ".join(item.split())) >= 5
        and " ".join(item.split()).casefold() not in _GENERIC_PRIVATE
    )
    if isinstance(value, Guide):
        guide = value
    else:
        raw = value.encode("utf-8") if isinstance(value, str) else value
        if len(raw) > 2_000_000:
            digest = hashlib.sha256(raw).hexdigest()
            finding = _finding("schema.size_limit", "", "Guide exceeds the 2,000,000-byte validation limit.")
            return ValidationReport("1.0", phase, digest, (finding,))
        parsed = parse_guide(value)
        if not parsed.ok:
            digest = hashlib.sha256(raw).hexdigest()
            return ValidationReport("1.0", phase, digest, tuple(_diagnostic_finding(x, supplied_private) for x in parsed.diagnostics))
        guide = normalize_guide(parsed)

    findings: list[Finding] = []
    texts = tuple(_text_fields(guide))
    denylist = []
    for supplied in supplied_private:
        normalized = " ".join(supplied.split()).casefold()
        if len(normalized) >= 5 and normalized not in _GENERIC_PRIVATE:
            denylist.append((normalized, hashlib.sha256(normalized.encode()).hexdigest()[:12]))
    for path, text in texts:
        folded = " ".join(text.split()).casefold()
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

    if sum(module.estimated_minutes for module in guide.modules) != guide.course.estimated_minutes:
        findings.append(_finding("time.module_total_mismatch", "/course/estimated_minutes", "Course duration does not equal the sum of module durations.", guide.course.id, (guide.course.id,)))
    if not guide.course.learner_summary:
        findings.append(_finding("personalization.no_visible_connection", "/course", "Guide has no explicit learner-facing personalization summary.", guide.course.id, (guide.course.id,)))
    for mi, module in enumerate(guide.modules):
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
    return ValidationReport(guide.schema_version, phase, guide_sha256(guide), tuple(findings))
