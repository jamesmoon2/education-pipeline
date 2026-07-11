"""Deterministic, safe HTML assembly for normalized Interactive Guide v1."""

from __future__ import annotations

from dataclasses import asdict
import base64
import hashlib
import html
import json
import re
from typing import Iterable, Literal
from urllib.parse import urlsplit

from education_pipeline.guide_runtime import (
    RUNTIME_VERSION,
    SUPPORTED_SCHEMA_VERSION,
    RuntimeAssets,
    load_runtime_assets,
)

from .model import Guide

DocumentMode = Literal["export", "preview"]


class GuideDocumentError(ValueError):
    """The guide or runtime cannot be assembled safely."""


def _escape_json(value: object) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return (text.replace("&", "\\u0026").replace("<", "\\u003c")
            .replace(">", "\\u003e").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))


def _hash(source: str) -> str:
    digest = hashlib.sha256(source.encode("utf-8")).digest()
    return "sha256-" + base64.b64encode(digest).decode("ascii")


def _safe_href(target: str, known_ids: frozenset[str]) -> tuple[str, bool]:
    if target.startswith("#") and target[1:] in known_ids:
        return target, False
    parsed = urlsplit(target)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return target, True
    raise GuideDocumentError(f"unsafe or unknown Markdown link target: {target!r}")


_TOKEN = re.compile(r"(`[^`\n]+`|\[([^\]\n]+)\]\(([^\s()]+)\)|\*\*([^*\n]+)\*\*|(?<!\*)\*([^*\n]+)\*(?!\*))")


def _inline(text: str, known_ids: frozenset[str]) -> str:
    out: list[str] = []
    cursor = 0
    for match in _TOKEN.finditer(text):
        out.append(html.escape(text[cursor:match.start()]))
        token = match.group(0)
        if token.startswith("`"):
            out.append(f"<code>{html.escape(token[1:-1])}</code>")
        elif token.startswith("["):
            href, external = _safe_href(match.group(3), known_ids)
            attrs = ' rel="noopener noreferrer" aria-label="External link"' if external else ""
            out.append(f'<a href="{html.escape(href, quote=True)}"{attrs}>{html.escape(match.group(2))}</a>')
        elif token.startswith("**"):
            out.append(f"<strong>{html.escape(match.group(4))}</strong>")
        else:
            out.append(f"<em>{html.escape(match.group(5))}</em>")
        cursor = match.end()
    out.append(html.escape(text[cursor:]))
    return "".join(out)


def render_guide_markdown(markdown: str, known_ids: Iterable[str]) -> str:
    """Render the guide-v1 subset without interpreting raw HTML."""
    ids = frozenset(known_ids)
    lines = markdown.splitlines()
    rendered: list[str] = []
    paragraph: list[str] = []
    in_code = False
    code: list[str] = []

    def flush() -> None:
        if paragraph:
            rendered.append("<p>" + _inline(" ".join(paragraph), ids) + "</p>")
            paragraph.clear()

    for line in lines:
        if line.startswith("```"):
            if in_code:
                rendered.append("<pre><code>" + html.escape("\n".join(code)) + "</code></pre>")
                code.clear()
            else:
                flush()
            in_code = not in_code
        elif in_code:
            code.append(line)
        elif not line.strip():
            flush()
        elif match := re.match(r"^(#{1,6})\s+(.+)$", line):
            flush(); level = min(6, len(match.group(1)) + 2)
            rendered.append(f"<h{level}>{_inline(match.group(2), ids)}</h{level}>")
        elif match := re.match(r"^>\s?(.*)$", line):
            flush(); rendered.append(f"<blockquote><p>{_inline(match.group(1), ids)}</p></blockquote>")
        elif match := re.match(r"^[-*]\s+(.+)$", line):
            flush(); rendered.append(f"<ul><li>{_inline(match.group(1), ids)}</li></ul>")
        elif match := re.match(r"^\d+[.)]\s+(.+)$", line):
            flush(); rendered.append(f"<ol><li>{_inline(match.group(1), ids)}</li></ol>")
        else:
            paragraph.append(line.strip())
    if in_code:
        raise GuideDocumentError("unclosed fenced code block")
    flush()
    return "".join(rendered)


def _all_ids(guide: Guide) -> frozenset[str]:
    ids = {guide.course.id, *(x.id for x in guide.outcomes), *(x.id for x in guide.glossary), *(x.id for x in guide.sources)}
    for module in guide.modules:
        ids.add(module.id)
        for section in module.sections:
            ids.add(section.id)
            for block in section.blocks:
                ids.add(block.id)
                ids.update(x.id for x in getattr(block, "choices", ()))
                ids.update(x.id for x in getattr(block, "steps", ()))
    return frozenset(ids)


def _kc_block(b: object, ids: frozenset[str]) -> str:
    input_type = "radio" if b.mode == "single" else "checkbox"
    name = f'kc-input-{html.escape(b.id, quote=True)}'
    choices = "".join(
        f'<li class="choice-item" id="{html.escape(c.id)}">'
        f'<label class="choice-label-wrap">'
        f'<input type="{input_type}" name="{name}" value="{html.escape(c.id, quote=True)}" '
        f'data-choice-id="{html.escape(c.id, quote=True)}" data-correct="{"true" if c.correct else "false"}" '
        f'data-role="kc-choice">'
        f'<span class="choice-label">{html.escape(c.label)}</span>'
        f'</label>'
        f'<span class="choice-feedback" data-role="answer-marker">Answer: {"correct" if c.correct else "incorrect"}</span>'
        f'</li>'
        for c in b.choices
    )
    return (
        f'<h4>{html.escape(b.prompt)}</h4>'
        f'<div class="choice-group" role="group" aria-label="Answer choices">'
        f'<ul class="choices">{choices}</ul>'
        f'</div>'
        f'<div class="kc-controls">'
        f'<button type="button" class="kc-submit" data-role="kc-submit" disabled>Submit answer</button>'
        f'<button type="button" class="kc-retry" data-role="kc-retry" hidden>Try again</button>'
        f'</div>'
        f'<div class="live-region" data-role="kc-result" role="status" aria-live="polite"></div>'
        f'<p class="explanation" data-role="kc-explanation"><strong>Explanation:</strong> {html.escape(b.explanation)}</p>'
    )


def _wr_block(b: object, ids: frozenset[str]) -> str:
    steps = "".join(
        f'<li class="reveal-step" id="{html.escape(s.id)}" data-role="reveal-step" data-step-index="{i}">'
        f'<strong>{html.escape(s.title or f"Step {i}")}</strong>{render_guide_markdown(s.markdown, ids)}'
        f'</li>'
        for i, s in enumerate(b.steps, 1)
    )
    return (
        f'<h4>{html.escape(b.prompt)}</h4>'
        f'<div class="wr-controls">'
        f'<button type="button" class="wr-reveal" data-role="wr-reveal-next">Reveal first step</button>'
        f'<button type="button" class="wr-show-all" data-role="wr-show-all">Show all</button>'
        f'<button type="button" class="wr-reset" data-role="wr-reset" hidden>Reset steps</button>'
        f'</div>'
        f'<div class="live-region" data-role="wr-live" role="status" aria-live="polite"></div>'
        f'<ol class="reveal-steps" data-role="reveal-steps" data-total-steps="{len(b.steps)}">{steps}</ol>'
        f'<p class="conclusion" data-role="wr-conclusion">{html.escape(b.conclusion)}</p>'
    )


def _sc_block(b: object, ids: frozenset[str]) -> str:
    name = f'sc-input-{html.escape(b.id, quote=True)}'
    choices = "".join(
        f'<li class="choice-item" id="{html.escape(c.id)}">'
        f'<label class="choice-label-wrap">'
        f'<input type="radio" name="{name}" value="{html.escape(c.id, quote=True)}" '
        f'data-choice-id="{html.escape(c.id, quote=True)}" data-quality="{html.escape(c.quality, quote=True)}" '
        f'data-role="sc-choice">'
        f'<span class="choice-label">{html.escape(c.label)}</span>'
        f'</label>'
        f'<span class="choice-feedback" data-role="sc-feedback">{html.escape(c.quality)}: {html.escape(c.feedback)}</span>'
        f'</li>'
        for c in b.choices
    )
    return (
        f'<h4>{html.escape(b.prompt)}</h4>'
        f'<div class="choice-group" role="group" aria-label="Scenario choices">'
        f'<ul class="scenario-choices">{choices}</ul>'
        f'</div>'
        f'<div class="sc-controls">'
        f'<button type="button" class="sc-submit" data-role="sc-submit" disabled>Submit choice</button>'
        f'<button type="button" class="sc-retry" data-role="sc-retry" hidden>Try again</button>'
        f'</div>'
        f'<div class="live-region" data-role="sc-result" role="status" aria-live="polite"></div>'
        f'<p class="debrief" data-role="sc-debrief"><strong>Debrief:</strong> {html.escape(b.debrief)}</p>'
    )


def _rf_block(b: object, ids: frozenset[str]) -> str:
    label_id = f'{html.escape(b.id, quote=True)}-prompt'
    guidance = f'<p class="guidance">{html.escape(b.guidance)}</p>' if b.guidance else ""
    placeholder = f' placeholder="{html.escape(b.placeholder, quote=True)}"' if b.placeholder else ""
    return (
        f'<h4 id="{label_id}">{html.escape(b.prompt)}</h4>'
        f'{guidance}'
        f'<p class="local-data-note">Notes are stored only in this browser, for this file, and are never included in print or export.</p>'
        f'<textarea class="reflection-input" data-role="reflection-input" aria-labelledby="{label_id}"{placeholder} rows="4"></textarea>'
        f'<div class="rf-controls">'
        f'<button type="button" class="rf-skip" data-role="rf-skip">Skip this reflection</button>'
        f'<button type="button" class="rf-reset" data-role="rf-reset" hidden>Clear my note</button>'
        f'</div>'
        f'<p class="rf-status" data-role="rf-status" role="status" aria-live="polite"></p>'
    )


_INTERACTIVE_TYPES = frozenset({"knowledge_check", "worked_reveal", "scenario", "reflection"})


def _block(block: object, ids: frozenset[str]) -> str:
    b = block
    extra = ""
    if b.type == "rich_text": body = render_guide_markdown(b.markdown, ids)
    elif b.type == "callout": body = (f"<h4>{html.escape(b.title or b.kind.title())}</h4>" + render_guide_markdown(b.markdown, ids))
    elif b.type == "knowledge_check":
        extra = f' data-mode="{html.escape(b.mode, quote=True)}" data-retry="{"true" if b.retry else "false"}"'
        body = _kc_block(b, ids)
    elif b.type == "worked_reveal": body = _wr_block(b, ids)
    elif b.type == "scenario": body = _sc_block(b, ids)
    elif b.type == "reflection": body = _rf_block(b, ids)
    else: raise GuideDocumentError(f"unsupported block type: {b.type!r}")
    interactive = f' data-interactive="true"' if b.type in _INTERACTIVE_TYPES else ""
    lead = f'<article class="block {html.escape(b.type)}" id="{html.escape(b.id)}"{interactive}{extra}>'
    return lead + body + "</article>"


def assemble_guide_document(guide: Guide, assets: RuntimeAssets | None = None, mode: DocumentMode = "export") -> str:
    """Return a full deterministic document from a normalized guide and assets."""
    if guide.schema_version != SUPPORTED_SCHEMA_VERSION:
        raise GuideDocumentError(f"unsupported guide schema version: {guide.schema_version!r}")
    if mode not in {"export", "preview"}: raise GuideDocumentError(f"unsupported document mode: {mode!r}")
    assets = assets or load_runtime_assets()
    if assets.version != RUNTIME_VERSION: raise GuideDocumentError(f"unsupported runtime version: {assets.version!r}")
    ids = _all_ids(guide)
    nav = "".join(
        f'<li><a href="#{html.escape(s.id)}" data-role="nav-link" data-section-id="{html.escape(s.id, quote=True)}">'
        f'{html.escape(m.title)} — {html.escape(s.title)}</a></li>'
        for m in guide.modules for s in m.sections
    )
    sections = "".join(
        f'<section id="{html.escape(s.id)}" data-role="guide-section" data-module-id="{html.escape(m.id, quote=True)}" '
        f'data-module-title="{html.escape(m.title, quote=True)}" data-section-title="{html.escape(s.title, quote=True)}">'
        f'<p class="module-context">{html.escape(m.title)}</p><h2>{html.escape(s.title)}</h2>'
        f'{"".join(_block(b, ids) for b in s.blocks)}'
        f'<div class="section-nav-controls" data-role="section-nav-controls">'
        f'<button type="button" data-role="prev-section">Previous section</button>'
        f'<span class="section-position" data-role="section-position"></span>'
        f'<button type="button" data-role="next-section">Next section</button>'
        f'</div>'
        f'<div class="section-complete-controls">'
        f'<button type="button" class="mark-complete" data-role="mark-complete">Mark section complete</button>'
        f'<p class="section-status" data-role="section-status" role="status" aria-live="polite"></p>'
        f'</div>'
        f'</section>'
        for m in guide.modules for s in m.sections
    )
    glossary = "".join(f'<dt id="{html.escape(x.id)}">{html.escape(x.term)}</dt><dd>{render_guide_markdown(x.definition, ids)}</dd>' for x in guide.glossary)
    sources = "".join(f'<li id="{html.escape(x.id)}"><strong>{html.escape(x.title)}</strong>{": " + html.escape(", ".join(x.authors)) if x.authors else ""}{" (" + html.escape(x.published) + ")" if x.published else ""}{" — " + render_guide_markdown(x.note, ids) if x.note else ""}{" " + _inline("[Source](" + x.url + ")", ids) if x.url else ""}</li>' for x in guide.sources)
    csp = "; ".join(["default-src 'none'", "img-src 'none'", f"style-src '{_hash(assets.css)}'", f"script-src '{_hash(assets.javascript)}'", "connect-src 'none'", "font-src 'none'", "media-src 'none'", "object-src 'none'", "frame-src 'none'", "base-uri 'none'", "form-action 'none'"])
    payload = _escape_json(asdict(guide))
    course_controls = (
        f'<div class="course-controls" aria-label="Course controls">'
        f'<h2 class="sr-only">Course controls</h2>'
        f'<label class="theme-control">Theme'
        f'<select data-role="theme-select"><option value="system">Match system</option>'
        f'<option value="light">Light</option><option value="dark">Dark</option></select>'
        f'</label>'
        f'<button type="button" data-role="reset-progress">Reset progress…</button>'
        f'<p class="local-data-note">Your progress and reflection notes are stored only in this browser, '
        f'for this exported file, and never leave your device.</p>'
        f'<p class="storage-notice" data-role="storage-notice" role="status" aria-live="polite" hidden></p>'
        f'</div>'
    )
    header = (
        f'<header class="course-header"><h1>{html.escape(guide.course.title)}</h1>'
        f'{f"<p>{html.escape(guide.course.subtitle)}</p>" if guide.course.subtitle else ""}'
        f'<p>{html.escape(guide.course.description)}</p>'
        f'<p>{guide.course.estimated_minutes} minutes · {html.escape(guide.course.difficulty)}</p>'
        f'<div class="progress-summary" data-role="progress-summary" role="status" aria-live="polite"></div>'
        f'</header>'
    )
    nav_block = (
        f'<nav class="guide-nav" aria-label="Course sections">'
        f'<button type="button" class="nav-toggle" data-role="nav-toggle" aria-expanded="false" aria-controls="guide-nav-list">'
        f'Sections</button>'
        f'<h2>Course navigation</h2><ol id="guide-nav-list">{nav}</ol></nav>'
    )
    return f'''<!doctype html>\n<html lang="{html.escape(guide.course.language, quote=True)}" data-guide-schema="{guide.schema_version}" data-guide-runtime="{assets.version}" data-guide-mode="{mode}" data-guide-course="{html.escape(guide.course.id, quote=True)}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="{csp}"><meta name="generator" content="Education Pipeline"><title>{html.escape(guide.course.title)}</title><style>{assets.css}</style></head><body><a class="skip-link" href="#guide-main">Skip to course content</a><div class="live-region visually-hidden" data-role="nav-announcement" role="status" aria-live="polite"></div><div class="error-shell" data-guide-status role="alert">Loading course…</div><div data-guide-shell hidden>{header}{course_controls}<div class="layout">{nav_block}<main id="guide-main">{sections}</main></div><aside class="course-info"><h2>Learning outcomes</h2><ul>{''.join(f'<li id="{html.escape(x.id)}">{html.escape(x.text)}</li>' for x in guide.outcomes)}</ul><h2>Glossary</h2><dl>{glossary}</dl><h2>Sources</h2><ol>{sources}</ol></aside></div><script id="guide-data" type="application/json">{payload}</script><script>{assets.javascript}</script></body></html>\n'''


__all__ = ["DocumentMode", "GuideDocumentError", "assemble_guide_document", "render_guide_markdown"]
