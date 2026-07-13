"""Static checks computed from the assembled export document (stdlib only)."""
import dataclasses
import json
from pathlib import Path

import pytest

from education_pipeline.guide_runtime import RuntimeAssets, load_runtime_assets
from education_pipeline.guides import compute_static_checks
from education_pipeline.guides.parse import normalize_guide, parse_guide

FIXTURE = Path(__file__).parent / "fixtures/guides/feedback-loops.guide.json"


@pytest.fixture()
def guide():
    parsed = parse_guide(FIXTURE.read_text(encoding="utf-8"))
    assert parsed.ok
    return normalize_guide(parsed)


def test_canonical_fixture_passes_every_static_check(guide):
    result = compute_static_checks(guide)
    ctx = result.context
    assert (ctx.render_succeeded, ctx.assets_match, ctx.controls_have_labels,
            ctx.heading_order_valid) == (True, True, True, True)
    assert result.document is not None and "data-guide-shell" in result.document


def test_static_checks_are_deterministic(guide):
    assert compute_static_checks(guide).document == compute_static_checks(guide).document


def test_tampered_assets_fail_assets_match(guide):
    packaged = load_runtime_assets()
    tampered = RuntimeAssets(css=packaged.css + "/*x*/", javascript=packaged.javascript)
    result = compute_static_checks(guide, assets=tampered)
    assert result.context.assets_match is False
    assert result.context.render_succeeded is True


def test_render_failure_is_reported_and_document_is_none(guide, monkeypatch):
    from education_pipeline.guides import static_checks as mod
    from education_pipeline.guides.document import GuideDocumentError

    def boom(*args, **kwargs):
        raise GuideDocumentError("forced")

    monkeypatch.setattr(mod, "assemble_guide_document", boom)
    result = compute_static_checks(guide)
    assert result.context.render_succeeded is False
    assert result.document is None


def test_unlabeled_button_fails_controls_check(guide):
    # Exercise the HTML analyzer directly: the assembled document is trusted
    # input, so the analyzer is what needs adversarial coverage.
    from education_pipeline.guides.static_checks import _analyze_document

    ok_doc = "<html><body><button>Go</button><h2>a</h2></body></html>"
    bad_doc = "<html><body><button></button><h2>a</h2></body></html>"
    assert _analyze_document(ok_doc).controls_have_labels is True
    assert _analyze_document(bad_doc).controls_have_labels is False


def test_skipped_heading_level_fails_heading_order():
    from education_pipeline.guides.static_checks import _analyze_document

    assert _analyze_document("<h1>a</h1><h2>b</h2><h3>c</h3>").heading_order_valid is True
    assert _analyze_document("<h1>a</h1><h4>b</h4>").heading_order_valid is False


def test_aria_labeled_and_label_wrapped_controls_pass():
    from education_pipeline.guides.static_checks import _analyze_document

    doc = ('<select aria-label="Theme"><option>x</option></select>'
           '<label>Name<input type="text"></label>'
           '<button aria-label="Close"></button><h2>a</h2>')
    assert _analyze_document(doc).controls_have_labels is True
