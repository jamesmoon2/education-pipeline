"""Static checks computed from the assembled export document (stdlib only)."""
from pathlib import Path

import pytest

from education_pipeline.guide_runtime import RuntimeAssets, load_runtime_assets
from education_pipeline.guides import compute_static_checks
from education_pipeline.guides.parse import normalize_guide, parse_guide
from education_pipeline.guides.projection import public_guide_projection

FIXTURE = Path(__file__).parent / "fixtures/guides/feedback-loops.guide.json"
PERSONALIZED_FIXTURE = (
    Path(__file__).parent
    / "fixtures/guides/feedback-loops.personalized.guide.json"
)


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


def test_progress_portability_controls_keep_the_document_checks_green(guide):
    """The download/restore controls add a button pair and a file input to the
    course controls, and the carry-over banner adds two more buttons: every one
    of them has to stay named, and the banner must not introduce a heading that
    breaks the document's h1 -> h2 -> h3 order."""
    result = compute_static_checks(guide)

    assert result.document is not None
    for role in (
        "download-progress",
        "restore-progress",
        "progress-file-input",
        "resume-progress",
        "dismiss-progress",
    ):
        assert f'data-role="{role}"' in result.document
    assert 'aria-label="Progress file to restore"' in result.document
    assert result.context.controls_have_labels is True
    assert result.context.heading_order_valid is True


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


def test_render_failure_keeps_assets_match_computed(guide, monkeypatch):
    # assets_match is input-derived, so it stays real (False here) even when
    # assembly fails; only document-derived checks default to True.
    from education_pipeline.guides import static_checks as mod
    from education_pipeline.guides.document import GuideDocumentError

    def boom(*args, **kwargs):
        raise GuideDocumentError("forced")

    monkeypatch.setattr(mod, "assemble_guide_document", boom)
    packaged = load_runtime_assets()
    tampered = RuntimeAssets(css=packaged.css + "/*x*/", javascript=packaged.javascript)
    result = compute_static_checks(guide, assets=tampered)
    ctx = result.context
    assert (ctx.render_succeeded, ctx.assets_match, ctx.controls_have_labels,
            ctx.heading_order_valid) == (False, False, True, True)
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


def test_textless_label_wrapped_control_fails_controls_check():
    from education_pipeline.guides.static_checks import _analyze_document

    doc = '<label><input type="text"></label><h2>a</h2>'
    assert _analyze_document(doc).controls_have_labels is False


def test_label_text_after_control_passes_controls_check():
    from education_pipeline.guides.static_checks import _analyze_document

    doc = '<label><input type="text">Name</label><h2>a</h2>'
    assert _analyze_document(doc).controls_have_labels is True


def test_previous_heading_skip_is_detected_even_after_a_deeper_heading():
    """The rule the deepest-seen implementation missed: h1,h2,h3 establishes
    depth 3, so a later h2 -> h4 was waved through even though it skips h3."""
    from education_pipeline.guides.static_checks import _analyze_document

    doc = "<h1>a</h1><h2>b</h2><h3>c</h3><h2>d</h2><h4>e</h4>"
    assert _analyze_document(doc).heading_order_valid is False


def test_returning_to_a_shallower_heading_is_never_a_skip():
    from education_pipeline.guides.static_checks import _analyze_document

    doc = "<h1>a</h1><h2>b</h2><h3>c</h3><h2>d</h2><h3>e</h3>"
    assert _analyze_document(doc).heading_order_valid is True


def test_document_whose_first_heading_is_below_h1_is_a_skip():
    """Unreachable through the assembler (the shell always emits <h1> first),
    but the analyzer is a general-purpose checker and must not pass a document
    that opens four levels deep."""
    from education_pipeline.guides.static_checks import _analyze_document

    assert _analyze_document("<h4>a</h4>").heading_order_valid is False
    assert _analyze_document("<h1>a</h1><h2>b</h2>").heading_order_valid is True


def test_rich_text_section_opening_with_a_markdown_heading_passes(guide):
    """A section whose first block is rich_text opening with '##' must not
    skip a heading level: the shell emits <h2> for the section title, so the
    markdown heading must render as <h3>, not <h4>.

    This is the ordinary shape of a written lesson and the exact case the
    tightened rule would otherwise block with no legal remediation ('#' is
    banned by markdown.invalid_heading_level).
    """
    import dataclasses

    from education_pipeline.guides.model import RichText

    section = guide.modules[0].sections[0]
    heading_block = RichText(
        id="blk-md-heading",
        markdown="## Why loops compound\n\nA short explanation.",
    )
    patched_section = dataclasses.replace(section, blocks=(heading_block, *section.blocks))
    patched_module = dataclasses.replace(
        guide.modules[0], sections=(patched_section, *guide.modules[0].sections[1:])
    )
    patched = dataclasses.replace(guide, modules=(patched_module, *guide.modules[1:]))

    result = compute_static_checks(patched)
    assert result.document is not None
    assert "<h3>Why loops compound</h3>" in result.document
    assert result.context.heading_order_valid is True


def test_static_checks_assemble_the_exact_public_projection(monkeypatch):
    from education_pipeline.guides import static_checks as mod

    source = normalize_guide(parse_guide(PERSONALIZED_FIXTURE.read_bytes()))
    expected = public_guide_projection(source)
    assembled = []

    def capture(candidate, *, assets, mode):
        assembled.append(candidate)
        return (
            '<h1>Course</h1><div data-guide-shell></div>'
            '<script id="guide-data"></script><a class="skip-link"></a>'
        )

    monkeypatch.setattr(mod, "assemble_guide_document", capture)

    result = compute_static_checks(source)

    assert assembled == [expected]
    assert result.document is not None
    assert source.course.goal_exclusions
    assert not assembled[0].course.goal_exclusions
