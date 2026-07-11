from __future__ import annotations

import base64
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import re

import pytest

from education_pipeline.guide_runtime import RuntimeAssets, load_runtime_assets
from education_pipeline.guides import normalize_guide, parse_guide
from education_pipeline.guides.document import (
    GuideDocumentError,
    assemble_guide_document,
    render_guide_markdown,
)

FIXTURE = Path(__file__).parent / "fixtures/guides/feedback-loops.guide.json"


def guide():
    return normalize_guide(parse_guide(FIXTURE.read_bytes()))


def sha(source: str) -> str:
    return base64.b64encode(hashlib.sha256(source.encode()).digest()).decode()


def test_document_is_deterministic_and_contains_exact_hashed_assets() -> None:
    assets = load_runtime_assets()
    first = assemble_guide_document(guide(), assets)
    assert first == assemble_guide_document(guide(), assets)
    assert f"style-src 'sha256-{sha(assets.css)}'" in first
    assert f"script-src 'sha256-{sha(assets.javascript)}'" in first
    assert f"<style>{assets.css}</style>" in first
    assert f"<script>{assets.javascript}</script>" in first
    for directive in ("default-src 'none'", "connect-src 'none'", "object-src 'none'", "frame-src 'none'", "base-uri 'none'", "form-action 'none'"):
        assert directive in first


def test_packaged_assets_are_nonblank_and_loaded_through_resources() -> None:
    assets = load_runtime_assets()
    assert "JSON.parse" in assets.javascript
    assert "@media print" in assets.css


def test_embedded_json_cannot_close_script_or_recontextualize_it() -> None:
    dangerous = "</script><script>alert('&  ')</script>"
    original = guide()
    value = replace(original, course=replace(original.course, description=dangerous))
    document = assemble_guide_document(value)
    payload = re.search(r'<script id="guide-data" type="application/json">(.*?)</script>', document).group(1)
    assert "</script" not in payload and "<" not in payload and ">" not in payload and "&" not in payload
    assert "\\u003c/script\\u003e" in payload
    assert "\\u0026" in payload and "\\u2028" in payload and "\\u2029" in payload
    assert json.loads(payload)["course"]["description"] == dangerous


def test_safe_markdown_escapes_html_links_and_fenced_code() -> None:
    rendered = render_guide_markdown('<img src=x> **safe** [site](https://example.com)\n```html\n</script>\n```', {"known"})
    assert "<img" not in rendered and "&lt;img src=x&gt;" in rendered
    assert '<strong>safe</strong>' in rendered
    assert 'rel="noopener noreferrer"' in rendered
    assert "&lt;/script&gt;" in rendered
    assert render_guide_markdown("[section](#known)", {"known"}) == '<p><a href="#known">section</a></p>'
    for target in ("javascript:alert", "//evil.test/x", "../secret", "file:///tmp/x", "#missing"):
        with pytest.raises(GuideDocumentError):
            render_guide_markdown(f"[bad]({target})", {"known"})


def test_fixture_renders_every_educational_field_and_block_type() -> None:
    document = assemble_guide_document(guide())
    for block_type in ("rich_text", "callout", "knowledge_check", "worked_reveal", "scenario", "reflection"):
        assert f'class="block {block_type}"' in document
    expected = ["Thinking in Feedback Loops", "How loops behave", "From events to loops", "Reinforcing", "Success increases learning", "Choose the quantity", "Start with <strong>plant biomass</strong>", "Which actions help", "Pest damage rises", "This treats visible damage", "A thoughtful intervention", "Where might a delayed feedback loop", "Draft a private loop map", "Feedback loop", "Thinking in Systems: A Primer"]
    for text in expected:
        assert text in document
    assert "Loading course…" in document and "data-guide-shell hidden" in document


def test_interactive_scaffolding_present_for_each_block_type() -> None:
    document = assemble_guide_document(guide())
    # Knowledge check: native inputs, submit/retry controls, live region, explanation hook.
    assert 'data-role="kc-choice"' in document and 'data-correct="true"' in document
    assert 'data-role="kc-submit"' in document and 'data-role="kc-retry"' in document
    assert 'data-role="kc-result"' in document and 'data-role="kc-explanation"' in document
    assert 'data-mode="single"' in document and 'data-mode="multiple"' in document
    assert 'data-retry="true"' in document
    # Worked reveal: step-by-step reveal controls plus a live region.
    assert 'data-role="reveal-step"' in document and 'data-role="wr-reveal-next"' in document
    assert 'data-role="wr-show-all"' in document and 'data-role="wr-reset"' in document
    assert 'data-role="wr-live"' in document and 'data-role="wr-conclusion"' in document
    # Scenario: single-decision radios, submit/retry, feedback and debrief hooks.
    assert 'data-role="sc-choice"' in document and 'data-quality="best"' in document
    assert 'data-role="sc-submit"' in document and 'data-role="sc-result"' in document
    assert 'data-role="sc-debrief"' in document
    # Reflection: textarea, skip/reset controls, status live region, local-only note.
    assert 'data-role="reflection-input"' in document
    assert 'data-role="rf-skip"' in document and 'data-role="rf-reset"' in document
    assert 'data-role="rf-status"' in document
    assert "stored only in this browser" in document
    # Navigation, progress, and course controls scaffolding.
    assert 'data-role="nav-link"' in document and 'data-role="progress-summary"' in document
    assert 'data-role="prev-section"' in document and 'data-role="next-section"' in document
    assert 'data-role="mark-complete"' in document and 'data-role="section-status"' in document
    assert 'data-role="theme-select"' in document and 'data-role="reset-progress"' in document
    assert 'data-role="storage-notice"' in document and 'data-role="nav-announcement"' in document
    for block_type in ("knowledge_check", "worked_reveal", "scenario", "reflection"):
        assert f'class="block {block_type}" id=' in document
    assert len(re.findall(r'class="block \w+" id="[a-z0-9-]+" data-interactive="true"', document)) == 5


def test_print_visible_content_survives_progressive_disclosure_markup() -> None:
    """Every educational field must appear as literal text regardless of the
    runtime's later CSS-driven hiding, since print/no-JS must show everything."""
    document = assemble_guide_document(guide())
    assert "Answer: correct" in document and "Answer: incorrect" in document
    assert "Explanation:" in document and "Success increases learning" in document
    assert "Choose the quantity" in document and "The loop reinforces growth" in document
    assert "weak: This treats visible damage" in document and "best: This exposes both reinforcing" in document
    assert "Debrief:" in document and "A thoughtful intervention begins" in document
    assert "Draft a private loop map" in document  # reflection placeholder attribute


def test_unknown_schema_runtime_and_mode_fail_closed() -> None:
    value = guide()
    with pytest.raises(GuideDocumentError, match="schema"):
        assemble_guide_document(value.__class__("2.0", value.course, value.outcomes, value.modules, value.glossary, value.sources))
    with pytest.raises(GuideDocumentError, match="runtime"):
        assemble_guide_document(value, RuntimeAssets("x", "y", "2.0"))
    with pytest.raises(GuideDocumentError, match="mode"):
        assemble_guide_document(value, mode="other")
