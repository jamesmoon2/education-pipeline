"""Deterministic export of a finalized guide to distributable formats.

The HTML renderer supports the Markdown subset the pipeline's guides use:
ATX headings, paragraphs, unordered and ordered lists, fenced code blocks,
pipe tables, and inline code/bold/italic/links. It is intentionally
dependency-free rather than a complete CommonMark implementation.
"""

from __future__ import annotations

import html as _html
import re
from typing import Mapping


EXPORT_FORMATS = ("markdown", "html")

_HEADING_RE = re.compile(r"(#{1,6})\s+(.*)$")
_ULIST_RE = re.compile(r"\s*[-*]\s+(.*)$")
_OLIST_RE = re.compile(r"\s*\d+\.\s+(.*)$")
_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_BOLD_RE = re.compile(r"\*\*([^*]+)\*\*")
_ITALIC_RE = re.compile(r"\*([^*]+)\*")
_CODESPAN_RE = re.compile(r"(`[^`]+`)")
_SEP_CELL_RE = re.compile(r":?-+:?")

_CSS = (
    "body{max-width:44rem;margin:2rem auto;padding:0 1rem;"
    "font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;"
    "line-height:1.6;color:#1a1a1a;}"
    "h1,h2,h3,h4,h5,h6{line-height:1.25;margin-top:1.6em;}"
    "code{background:#f2f2f2;padding:0.1em 0.3em;border-radius:3px;"
    "font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:0.9em;}"
    "pre{background:#f2f2f2;padding:0.8em 1em;border-radius:6px;overflow-x:auto;}"
    "pre code{background:none;padding:0;}"
    "table{border-collapse:collapse;width:100%;margin:1em 0;}"
    "th,td{border:1px solid #ccc;padding:0.4em 0.6em;text-align:left;}"
    "th{background:#f2f2f2;}"
)


def build_markdown_bundle(markdown_text: str, *, front_matter: Mapping[str, str]) -> str:
    """Prepend a front-matter block to guide markdown for distribution."""

    lines = ["---"]
    for key, value in front_matter.items():
        lines.append(f"{key}: {value}")
    lines.append("---")
    lines.append("")
    body = markdown_text if markdown_text.endswith("\n") else markdown_text + "\n"
    return "\n".join(lines) + "\n" + body


def render_markdown_to_html(markdown_text: str, *, title: str) -> str:
    """Render a Markdown subset into a self-contained HTML document."""

    body = render_html_body(markdown_text)
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{_html.escape(title)}</title>\n"
        f"<style>{_CSS}</style>\n"
        "</head>\n"
        "<body>\n"
        f"{body}\n"
        "</body>\n"
        "</html>\n"
    )


def render_html_body(markdown_text: str) -> str:
    """Render a Markdown subset into body-only HTML markup.

    All content is HTML-escaped by the inline renderers and no scripts are
    ever emitted, so the output is safe to inject into an authed same-origin
    page (the cockpit preview) as well as the full export document.
    """

    lines = markdown_text.replace("\r\n", "\n").split("\n")
    parts: list[str] = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        if not line.strip():
            i += 1
            continue

        if line.startswith("```"):
            i += 1
            code: list[str] = []
            while i < n and not lines[i].startswith("```"):
                code.append(lines[i])
                i += 1
            i += 1  # skip the closing fence
            parts.append(f"<pre><code>{_html.escape(chr(10).join(code))}</code></pre>")
            continue

        heading = _HEADING_RE.match(line)
        if heading:
            level = len(heading.group(1))
            parts.append(f"<h{level}>{_render_inline(heading.group(2).strip())}</h{level}>")
            i += 1
            continue

        if "|" in line and i + 1 < n and _is_table_separator(lines[i + 1]):
            table_lines = [line, lines[i + 1]]
            i += 2
            while i < n and lines[i].strip() and "|" in lines[i]:
                table_lines.append(lines[i])
                i += 1
            parts.append(_render_table(table_lines))
            continue

        if _ULIST_RE.match(line):
            items, i = _collect_list_items(lines, i, _ULIST_RE)
            parts.append("<ul>" + "".join(f"<li>{it}</li>" for it in items) + "</ul>")
            continue

        if _OLIST_RE.match(line):
            items, i = _collect_list_items(lines, i, _OLIST_RE)
            parts.append("<ol>" + "".join(f"<li>{it}</li>" for it in items) + "</ol>")
            continue

        para = [line]
        i += 1
        while i < n and lines[i].strip() and not _starts_block(lines[i]):
            para.append(lines[i])
            i += 1
        parts.append(f"<p>{_render_inline(' '.join(p.strip() for p in para))}</p>")

    return "\n".join(parts)


def _collect_list_items(lines: list[str], start: int, pattern: re.Pattern[str]) -> tuple[list[str], int]:
    items: list[str] = []
    i = start
    while i < len(lines):
        match = pattern.match(lines[i])
        if not match:
            break
        items.append(_render_inline(match.group(1).strip()))
        i += 1
    return items, i


def _starts_block(line: str) -> bool:
    return (
        line.startswith("```")
        or _HEADING_RE.match(line) is not None
        or _ULIST_RE.match(line) is not None
        or _OLIST_RE.match(line) is not None
        or line.lstrip().startswith("|")
    )


def _is_table_separator(line: str) -> bool:
    if "|" not in line:
        return False
    cells = _split_table_row(line)
    return bool(cells) and all(_SEP_CELL_RE.fullmatch(cell.strip()) for cell in cells)


def _split_table_row(line: str) -> list[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return stripped.split("|")


def _render_table(table_lines: list[str]) -> str:
    header = _split_table_row(table_lines[0])
    thead = "<tr>" + "".join(f"<th>{_render_inline(c.strip())}</th>" for c in header) + "</tr>"
    body_rows = []
    for row_line in table_lines[2:]:
        cells = _split_table_row(row_line)
        body_rows.append("<tr>" + "".join(f"<td>{_render_inline(c.strip())}</td>" for c in cells) + "</tr>")
    return f"<table><thead>{thead}</thead><tbody>{''.join(body_rows)}</tbody></table>"


def _render_inline(text: str) -> str:
    rendered: list[str] = []
    for part in _CODESPAN_RE.split(text):
        if len(part) >= 2 and part.startswith("`") and part.endswith("`"):
            rendered.append(f"<code>{_html.escape(part[1:-1])}</code>")
        else:
            rendered.append(_render_inline_text(part))
    return "".join(rendered)


_SAFE_LINK_SCHEMES = ("http:", "https:", "mailto:")


def _href_is_safe(href: str) -> bool:
    compact = "".join(href.split()).lower()
    if compact.startswith(_SAFE_LINK_SCHEMES):
        return True
    head = compact.split("#", 1)[0].split("?", 1)[0]
    return ":" not in head  # relative URL: no scheme at all


def _render_link(match: "re.Match[str]") -> str:
    label, href = match.group(1), match.group(2)
    if not _href_is_safe(href):
        return label
    return f'<a href="{href}">{label}</a>'


def _render_inline_text(text: str) -> str:
    escaped = _html.escape(text)
    escaped = _LINK_RE.sub(_render_link, escaped)
    escaped = _BOLD_RE.sub(r"<strong>\1</strong>", escaped)
    escaped = _ITALIC_RE.sub(r"<em>\1</em>", escaped)
    return escaped
