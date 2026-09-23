from __future__ import annotations

import base64
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import re

import pytest

from education_pipeline.guide_runtime import (
    RUNTIME_VERSION,
    SUPPORTED_SCHEMA_VERSIONS,
    RuntimeAssets,
    load_runtime_assets,
)
from education_pipeline.guides import normalize_guide, parse_guide
from education_pipeline.guides.model import (
    Diagram,
    DiagramEdge,
    DiagramNode,
    TimelineEvent,
)
from education_pipeline.guides.document import (
    GuideDocumentError,
    assemble_guide_document,
    render_guide_markdown,
)

FIXTURE = Path(__file__).parent / "fixtures/guides/feedback-loops.guide.json"
PERSONALIZED_FIXTURE = (
    Path(__file__).parent
    / "fixtures/guides/feedback-loops.personalized.guide.json"
)

DIAGRAMS_FIXTURE = (
    Path(__file__).parent / "fixtures/guides/feedback-loops.diagrams.guide.json"
)


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
    # Progress portability controls sit with the other course controls.
    assert 'data-role="download-progress"' in document and 'data-role="restore-progress"' in document
    assert 'data-role="progress-file-input"' in document and 'data-role="progress-file-status"' in document
    # Carry-over offer for progress stored by a previous export.
    assert 'data-role="progress-migration"' in document and 'data-role="progress-migration-detail"' in document
    assert 'data-role="resume-progress"' in document and 'data-role="dismiss-progress"' in document
    for block_type in ("knowledge_check", "worked_reveal", "scenario", "reflection"):
        assert f'class="block {block_type}" id=' in document
    assert len(re.findall(r'class="block \w+" id="[a-z0-9-]+" data-interactive="true"', document)) == 5


def test_progress_migration_banner_is_present_and_hidden_until_the_runtime_offers_it() -> None:
    """The banner ships in every document but must never show itself: the
    runtime reveals it only when it actually found a previous export's
    progress, so a no-JS reader is never told about an offer it cannot make."""
    document = assemble_guide_document(guide())

    banner = re.search(
        r'<div class="progress-migration".*?</div></div>', document, re.DOTALL
    ).group(0)
    assert 'data-role="progress-migration"' in banner
    assert 'role="status"' in banner and 'aria-live="polite"' in banner
    assert 'aria-live="polite" hidden>' in banner
    assert "You have progress from a previous version of this course." in banner
    assert '<span data-role="progress-migration-detail"></span>' in banner
    assert '<button type="button" data-role="resume-progress">Resume that progress</button>' in banner
    assert '<button type="button" data-role="dismiss-progress">Start fresh</button>' in banner
    # It is part of the shell, so it can never precede the loading status.
    assert document.index("data-guide-shell hidden") < document.index(
        '<div class="progress-migration"'
    )


def test_progress_file_controls_are_named_and_the_picker_is_hidden() -> None:
    document = assemble_guide_document(guide())

    controls = re.search(
        r'<div class="course-controls".*?</div>', document, re.DOTALL
    ).group(0)
    assert '<button type="button" data-role="download-progress">Download progress</button>' in controls
    assert '<button type="button" data-role="restore-progress">Restore progress…</button>' in controls
    # The picker itself is opened by the button, so it stays out of the tab
    # order and the accessibility tree -- but it is still named for anything
    # that surfaces it anyway.
    picker = re.search(r'<input class="progress-file-input"[^>]*>', controls).group(0)
    assert 'type="file"' in picker and 'accept="application/json"' in picker
    assert 'aria-label="Progress file to restore"' in picker and picker.endswith("hidden>")
    assert 'data-role="progress-file-status"' in controls and 'role="status"' in controls


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


def test_markdown_headings_nest_one_level_under_the_section_heading() -> None:
    """The shell owns <h1> (course title) and <h2> (section title). '##' is the
    shallowest heading a learner-Markdown author may write (markdown.invalid_
    heading_level bans '#'), so it must render as <h3> -- directly under the
    section heading, skipping nothing."""
    assert render_guide_markdown("## Foo", {"known"}) == "<h3>Foo</h3>"
    assert render_guide_markdown("### Bar", {"known"}) == "<h4>Bar</h4>"
    assert render_guide_markdown("###### Deep", {"known"}) == "<h6>Deep</h6>"


def test_unknown_schema_runtime_and_mode_fail_closed() -> None:
    value = guide()
    with pytest.raises(GuideDocumentError, match="schema"):
        assemble_guide_document(value.__class__("2.0", value.course, value.outcomes, value.modules, value.glossary, value.sources))
    with pytest.raises(GuideDocumentError, match="runtime"):
        assemble_guide_document(value, RuntimeAssets("x", "y", "2.0"))
    with pytest.raises(GuideDocumentError, match="mode"):
        assemble_guide_document(value, mode="other")


def test_document_accepts_1_1_but_embeds_only_the_public_projection() -> None:
    source = normalize_guide(parse_guide(PERSONALIZED_FIXTURE.read_bytes()))

    document = assemble_guide_document(source)
    payload_text = re.search(
        r'<script id="guide-data" type="application/json">(.*?)</script>', document
    ).group(1)
    payload = json.loads(payload_text)

    assert source.course.goal_exclusions[0].reason == "Synthetic deferred objective."
    assert source.outcomes[0].serves_goals == ("goal-001",)
    assert 'data-guide-schema="1.1"' in document
    assert payload["schema_version"] == "1.1"
    assert "serves_goals" not in payload_text
    assert "goal_exclusions" not in payload_text
    assert "Synthetic deferred objective." not in document


def test_runtime_version_is_1_2_for_phase_5_diagrams() -> None:
    assets = load_runtime_assets()
    assert assets.version == "1.2"
    assert RUNTIME_VERSION == "1.2"
    assert SUPPORTED_SCHEMA_VERSIONS == frozenset({"1.0", "1.1", "1.2"})
    document = assemble_guide_document(guide(), assets)
    assert 'data-guide-runtime="1.2"' in document


# --- Diagram block (schema 1.2, T53) --------------------------------------


def diagrams_guide():
    return normalize_guide(parse_guide(DIAGRAMS_FIXTURE.read_bytes()))


def _figure(document: str, block_id: str) -> str:
    match = re.search(
        rf'<figure class="block diagram" id="{re.escape(block_id)}".*?</figure>',
        document,
        re.DOTALL,
    )
    assert match, f"no diagram figure for {block_id!r}"
    return match.group(0)


def _with_blocks(value, *blocks):
    """Return ``value`` with the first section's blocks replaced by ``blocks``."""
    module = value.modules[0]
    section = replace(module.sections[0], blocks=tuple(blocks))
    module = replace(module, sections=(section,) + module.sections[1:])
    return replace(value, modules=(module,) + value.modules[1:])


FLOW_FIGURE = (
    '<figure class="block diagram" id="growth-loop-flow" data-diagram-kind="flow">'
    '<figcaption class="diagram-caption">'
    '<strong class="diagram-title">How plant growth reinforces itself</strong>'
    ' <span class="diagram-caption-text">The last connection closes a '
    "<strong>reinforcing</strong> loop.</span>"
    "</figcaption>"
    '<div class="diagram-text" data-role="diagram-text">'
    '<ol class="diagram-steps">'
    '<li><span class="diagram-label">Plant biomass</span></li>'
    '<li><span class="diagram-label">Leaf area</span>: '
    '<span class="diagram-detail">More biomass usually means more leaves.</span></li>'
    '<li><span class="diagram-label">Sunlight captured</span></li>'
    '<li><span class="diagram-label">New growth</span></li>'
    "</ol>"
    '<p class="diagram-list-label">Connections</p>'
    '<ul class="diagram-connections">'
    "<li>Plant biomass → Leaf area — increases</li>"
    "<li>Leaf area → Sunlight captured — increases</li>"
    "<li>Sunlight captured → New growth — fuels</li>"
    "<li>New growth → Plant biomass — adds to (loops back)</li>"
    "</ul>"
    "</div>"
    "</figure>"
)

TIMELINE_FIGURE = (
    '<figure class="block diagram" id="watering-delay-timeline" data-diagram-kind="timeline">'
    '<figcaption class="diagram-caption">'
    '<strong class="diagram-title">Why watering again too soon overcorrects</strong>'
    "</figcaption>"
    '<div class="diagram-text" data-role="diagram-text">'
    '<ol class="diagram-events">'
    '<li><span class="diagram-when">Day 1, morning</span> — '
    '<span class="diagram-label">Water the bed</span></li>'
    '<li><span class="diagram-when">Day 1, evening</span> — '
    '<span class="diagram-label">Surface still looks dry</span></li>'
    '<li><span class="diagram-when">Day 3</span> — '
    '<span class="diagram-label">Moisture reaches the roots</span>: '
    '<span class="diagram-detail">The delay hides the effect of the first watering.</span></li>'
    '<li><span class="diagram-when">Day 4</span> — '
    '<span class="diagram-label">Leaves recover</span></li>'
    "</ol>"
    "</div>"
    "</figure>"
)


def test_diagrams_fixture_assembles_as_schema_1_2() -> None:
    document = assemble_guide_document(diagrams_guide())
    assert 'data-guide-schema="1.2"' in document
    assert 'data-guide-runtime="1.2"' in document
    assert document.count('<figure class="block diagram"') == 4
    for block_id, kind in (
        ("growth-loop-flow", "flow"),
        ("loop-kinds-map", "concept_map"),
        ("loop-types-comparison", "comparison"),
        ("watering-delay-timeline", "timeline"),
    ):
        assert f'id="{block_id}" data-diagram-kind="{kind}"' in document


def test_flow_diagram_figure_markup_is_exact() -> None:
    document = assemble_guide_document(diagrams_guide())
    assert _figure(document, "growth-loop-flow") == FLOW_FIGURE


def test_timeline_diagram_figure_markup_is_exact() -> None:
    document = assemble_guide_document(diagrams_guide())
    assert _figure(document, "watering-delay-timeline") == TIMELINE_FIGURE


def test_diagram_is_a_figure_block_not_an_article() -> None:
    document = assemble_guide_document(diagrams_guide())
    for block_id in ("growth-loop-flow", "watering-delay-timeline"):
        assert '<article class="block diagram"' not in document
        figure = _figure(document, block_id)
        assert "data-interactive" not in figure


def test_diagram_figure_has_no_heading_control_extra_id_or_runtime_state() -> None:
    document = assemble_guide_document(diagrams_guide())
    for block_id in (
        "growth-loop-flow",
        "loop-kinds-map",
        "loop-types-comparison",
        "watering-delay-timeline",
    ):
        figure = _figure(document, block_id)
        assert not re.search(r"<h[1-6][\s>]", figure), block_id
        assert not re.search(r"<(input|button|select|textarea)[\s>]", figure), block_id
        assert re.findall(r'\sid="([^"]*)"', figure) == [block_id]
        assert "data-diagram-state" not in figure
        assert "<svg" not in figure and "<details" not in figure
        assert "style=" not in figure


def test_diagram_local_ids_are_not_rendered_or_link_targets() -> None:
    document = assemble_guide_document(diagrams_guide())
    for local_id in ("biomass", "leaf-area", "sunlight", "growth", "water", "surface", "roots", "recover"):
        assert f'id="{local_id}"' not in document
    with pytest.raises(GuideDocumentError):
        render_guide_markdown("[node](#biomass)", {"growth-loop-flow"})


def test_flow_without_caption_or_edge_labels_escapes_every_plain_string() -> None:
    block = Diagram(
        id="escape-flow",
        kind="flow",
        title='Tags <b> & "quotes"',
        nodes=(
            DiagramNode("a", "A <start>"),
            DiagramNode("b", "B & C", detail="See `code` and *care* <here>"),
        ),
        edges=(DiagramEdge("a", "b"), DiagramEdge("b", "a", label="<back>")),
    )
    document = assemble_guide_document(_with_blocks(diagrams_guide(), block))
    assert _figure(document, "escape-flow") == (
        '<figure class="block diagram" id="escape-flow" data-diagram-kind="flow">'
        '<figcaption class="diagram-caption">'
        '<strong class="diagram-title">Tags &lt;b&gt; &amp; &quot;quotes&quot;</strong>'
        "</figcaption>"
        '<div class="diagram-text" data-role="diagram-text">'
        '<ol class="diagram-steps">'
        '<li><span class="diagram-label">A &lt;start&gt;</span></li>'
        '<li><span class="diagram-label">B &amp; C</span>: '
        '<span class="diagram-detail">See <code>code</code> and <em>care</em> &lt;here&gt;</span></li>'
        "</ol>"
        '<p class="diagram-list-label">Connections</p>'
        '<ul class="diagram-connections">'
        "<li>A &lt;start&gt; → B &amp; C</li>"
        "<li>B &amp; C → A &lt;start&gt; — &lt;back&gt; (loops back)</li>"
        "</ul>"
        "</div>"
        "</figure>"
    )


def test_timeline_caption_and_detail_render_the_inline_subset() -> None:
    block = Diagram(
        id="inline-timeline",
        kind="timeline",
        title="Inline timeline",
        caption="See [the outcome](#map-loop) & **why**",
        events=(
            TimelineEvent("one", "T < 1", "First"),
            TimelineEvent("two", "Later", "Second", detail="*Slow* change"),
        ),
    )
    document = assemble_guide_document(_with_blocks(diagrams_guide(), block))
    assert _figure(document, "inline-timeline") == (
        '<figure class="block diagram" id="inline-timeline" data-diagram-kind="timeline">'
        '<figcaption class="diagram-caption">'
        '<strong class="diagram-title">Inline timeline</strong>'
        ' <span class="diagram-caption-text">See <a href="#map-loop">the outcome</a>'
        " &amp; <strong>why</strong></span>"
        "</figcaption>"
        '<div class="diagram-text" data-role="diagram-text">'
        '<ol class="diagram-events">'
        '<li><span class="diagram-when">T &lt; 1</span> — '
        '<span class="diagram-label">First</span></li>'
        '<li><span class="diagram-when">Later</span> — '
        '<span class="diagram-label">Second</span>: '
        '<span class="diagram-detail"><em>Slow</em> change</span></li>'
        "</ol>"
        "</div>"
        "</figure>"
    )


def test_diagram_caption_with_unknown_internal_link_fails_closed() -> None:
    block = Diagram(
        id="bad-link-flow",
        kind="flow",
        title="Bad link",
        caption="[node](#biomass)",
        nodes=(DiagramNode("a", "A"), DiagramNode("b", "B")),
        edges=(DiagramEdge("a", "b"),),
    )
    with pytest.raises(GuideDocumentError, match="unsafe or unknown Markdown link target"):
        assemble_guide_document(_with_blocks(diagrams_guide(), block))


@pytest.mark.parametrize("version", ["1.0", "1.1"])
def test_diagram_in_a_pre_1_2_guide_raises(version: str) -> None:
    value = replace(diagrams_guide(), schema_version=version)
    with pytest.raises(
        GuideDocumentError, match=re.escape("unsupported block type: 'diagram'")
    ):
        assemble_guide_document(value)


def test_guide_data_embeds_each_diagram_as_its_canonical_dict() -> None:
    document = assemble_guide_document(diagrams_guide())
    payload = json.loads(
        re.search(
            r'<script id="guide-data" type="application/json">(.*?)</script>', document
        ).group(1)
    )
    assert payload["schema_version"] == "1.2"
    blocks = {
        b["id"]: b
        for m in payload["modules"]
        for s in m["sections"]
        for b in s["blocks"]
        if b["type"] == "diagram"
    }
    assert set(blocks) == {
        "growth-loop-flow",
        "loop-kinds-map",
        "loop-types-comparison",
        "watering-delay-timeline",
    }
    assert blocks["growth-loop-flow"] == {
        "caption": "The last connection closes a **reinforcing** loop.",
        "edges": [
            {"from": "biomass", "label": "increases", "to": "leaf-area"},
            {"from": "leaf-area", "label": "increases", "to": "sunlight"},
            {"from": "sunlight", "label": "fuels", "to": "growth"},
            {"from": "growth", "label": "adds to", "to": "biomass"},
        ],
        "id": "growth-loop-flow",
        "kind": "flow",
        "nodes": [
            {"id": "biomass", "label": "Plant biomass"},
            {"detail": "More biomass usually means more leaves.", "id": "leaf-area", "label": "Leaf area"},
            {"id": "sunlight", "label": "Sunlight captured"},
            {"id": "growth", "label": "New growth"},
        ],
        "outcome_ids": ["map-loop"],
        "source_ids": [],
        "title": "How plant growth reinforces itself",
        "type": "diagram",
    }
    assert blocks["watering-delay-timeline"] == {
        "events": [
            {"id": "water", "label": "Water the bed", "when": "Day 1, morning"},
            {"id": "surface", "label": "Surface still looks dry", "when": "Day 1, evening"},
            {
                "detail": "The delay hides the effect of the first watering.",
                "id": "roots",
                "label": "Moisture reaches the roots",
                "when": "Day 3",
            },
            {"id": "recover", "label": "Leaves recover", "when": "Day 4"},
        ],
        "id": "watering-delay-timeline",
        "kind": "timeline",
        "outcome_ids": ["choose-intervention"],
        "source_ids": [],
        "title": "Why watering again too soon overcorrects",
        "type": "diagram",
    }
    raw = re.search(
        r'<script id="guide-data" type="application/json">(.*?)</script>', document
    ).group(1)
    assert '"from_id"' not in raw and '"to_id"' not in raw


@pytest.mark.parametrize("fixture", [FIXTURE, DIAGRAMS_FIXTURE], ids=["1.0", "1.2"])
def test_content_security_policy_string_is_pinned(fixture: Path) -> None:
    """Diagrams add no CSP directive: the SVG is built by the hashed runtime."""
    assets = load_runtime_assets()
    document = assemble_guide_document(
        normalize_guide(parse_guide(fixture.read_bytes())), assets
    )
    csp = re.search(
        r'<meta http-equiv="Content-Security-Policy" content="([^"]*)">', document
    ).group(1)
    assert csp == (
        "default-src 'none'; img-src 'none'; "
        f"style-src 'sha256-{sha(assets.css)}'; "
        f"script-src 'sha256-{sha(assets.javascript)}'; "
        "connect-src 'none'; font-src 'none'; media-src 'none'; "
        "object-src 'none'; frame-src 'none'; base-uri 'none'; form-action 'none'"
    )
