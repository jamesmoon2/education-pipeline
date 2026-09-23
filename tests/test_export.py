import base64
import hashlib
import json
from pathlib import Path
import re

import test_runs

from education_pipeline.guide_runtime import load_runtime_assets

from education_pipeline import (
    build_markdown_bundle,
    render_html_body,
    render_markdown_to_html,
)


def test_render_headings_and_paragraph() -> None:
    html = render_markdown_to_html("# Title\n\n## Sub\n\nHello world.\n", title="Doc")

    assert "<h1>Title</h1>" in html
    assert "<h2>Sub</h2>" in html
    assert "<p>Hello world.</p>" in html


def test_render_unordered_and_ordered_lists() -> None:
    html = render_markdown_to_html("- a\n- b\n\n1. one\n2. two\n", title="Doc")

    assert "<ul><li>a</li><li>b</li></ul>" in html
    assert "<ol><li>one</li><li>two</li></ol>" in html


def test_render_code_fence_escapes_content() -> None:
    html = render_markdown_to_html("```\n<tag> & stuff\n```\n", title="Doc")

    assert "<pre><code>&lt;tag&gt; &amp; stuff</code></pre>" in html


def test_render_inline_formatting_and_escaping() -> None:
    html = render_markdown_to_html(
        "Use `x < y` with **bold** and [Anthropic](https://example.com).\n",
        title="Doc",
    )

    assert "<code>x &lt; y</code>" in html
    assert "<strong>bold</strong>" in html
    assert '<a href="https://example.com">Anthropic</a>' in html


def test_render_pipe_table() -> None:
    md = "| A | B |\n| --- | --- |\n| 1 | 2 |\n"

    html = render_markdown_to_html(md, title="Doc")

    assert "<table>" in html
    assert "<th>A</th>" in html
    assert "<td>1</td>" in html
    assert "<td>2</td>" in html


def test_render_produces_self_contained_document() -> None:
    html = render_markdown_to_html("# Title\n", title="My Guide")

    assert html.startswith("<!DOCTYPE html>")
    assert "<title>My Guide</title>" in html
    assert "<style>" in html
    # No external assets: strict local-first, no CDN/script/link dependencies.
    assert "<link" not in html
    assert "<script" not in html


def test_render_escapes_document_title() -> None:
    html = render_markdown_to_html("# x\n", title="A & B <c>")

    assert "<title>A &amp; B &lt;c&gt;</title>" in html


def test_legacy_export_document_carries_csp() -> None:
    html = render_markdown_to_html("# T", title="T")
    assert 'http-equiv="Content-Security-Policy"' in html
    assert "default-src 'none'" in html


def test_build_markdown_bundle_prepends_front_matter() -> None:
    bundle = build_markdown_bundle(
        "# Guide\n\nBody.\n",
        front_matter={"title": "Systems Thinking", "topic_id": "systems-thinking"},
    )

    assert bundle.startswith("---\n")
    assert "title: Systems Thinking\n" in bundle
    assert "topic_id: systems-thinking\n" in bundle
    assert bundle.rstrip().endswith("Body.")
    # Front matter is closed before the body begins.
    assert bundle.index("---\n", 3) < bundle.index("# Guide")


def test_render_html_body_renders_body_only_markup() -> None:
    html = render_html_body("# Title\n\nSome **bold** text.")

    assert "<h1>Title</h1>" in html
    assert "<strong>bold</strong>" in html
    assert "<!DOCTYPE" not in html
    assert "<body>" not in html
    assert "<style>" not in html


def test_render_html_body_escapes_script_input() -> None:
    html = render_html_body("<script>alert(1)</script>")

    assert "<script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_javascript_links_are_neutralized() -> None:
    html = render_html_body("[x](javascript:alert(1))")
    assert "javascript:" not in html.lower()
    assert "<a " not in html
    assert "x" in html


def test_scheme_check_defeats_case_and_whitespace_tricks() -> None:
    for href in ("JaVaScRiPt:alert(1)", "java\tscript:alert(1)", " javascript:alert(1)", "data:text/html,x", "vbscript:x"):
        html = render_html_body(f"[x]({href})")
        assert "<a " not in html, href


def test_safe_links_still_render() -> None:
    html = render_html_body("[docs](https://example.com/a) and [rel](./page.md) and [mail](mailto:a@b.c)")
    assert '<a href="https://example.com/a">docs</a>' in html
    assert '<a href="./page.md">rel</a>' in html
    assert '<a href="mailto:a@b.c">mail</a>' in html


def test_personalized_source_stays_local_while_export_and_sidecar_are_stripped(
    tmp_path,
) -> None:
    topic_id = "systems-thinking"
    store = test_runs._create_profiled_guide_run(tmp_path)
    test_runs._drive_profiled_guide_to_finalize_ready(store, topic_id)
    final_source = store.finalize_run(topic_id)
    exported = store.export_run(topic_id)
    sidecar = store.export_report_path(topic_id)

    source_text = final_source.read_text(encoding="utf-8")
    assert '"serves_goals"' in source_text
    assert '"goal_exclusions"' in source_text
    assert "Synthetic deferred objective." in source_text

    public_text = exported.read_text(encoding="utf-8")
    report_text = sidecar.read_text(encoding="utf-8")
    for private_or_local in (
        '"serves_goals"',
        '"goal_exclusions"',
        "Synthetic deferred objective.",
        "Synthetic private goal alpha",
        "Synthetic private goal beta",
        "Synthetic private goal gamma",
        "Synthetic learner cohort",
        "personalization-trace.json",
    ):
        assert private_or_local not in public_text
        assert private_or_local not in report_text

    embedded = public_text.split(
        '<script id="guide-data" type="application/json">', 1
    )[1].split("</script>", 1)[0]
    payload = json.loads(embedded)
    assert payload["schema_version"] == "1.1"


# --- Diagram block (T55): a 1.2 export --------------------------------------

DIAGRAMS_FIXTURE = Path(__file__).parent / "fixtures/guides/feedback-loops.diagrams.guide.json"


def _export_diagrams_run(tmp_path: Path):
    topic_id = "systems-thinking"
    body = DIAGRAMS_FIXTURE.read_text(encoding="utf-8")
    runs = test_runs._create_versioned_guide_run(tmp_path, "1.2")
    test_runs._drive_versioned_guide_to_draft_prompt(runs, "1.2").write_text(
        body, encoding="utf-8"
    )
    runs.approve_stage(topic_id, "draft")
    runs.validate_run(topic_id, "draft")
    qa = runs.write_qa_prompt(topic_id)
    qa.response_path.write_text("# QA findings\n\nNo major issues.\n", encoding="utf-8")
    runs.approve_stage(topic_id, "qa")
    fc = runs.write_factcheck_prompt(topic_id)
    fc.response_path.write_text(test_runs.FACTCHECK_FIXTURE, encoding="utf-8")
    runs.approve_stage(topic_id, "factcheck")
    repair = runs.write_repair_prompt(topic_id)
    repair.response_path.write_text(body, encoding="utf-8")
    runs.approve_stage(topic_id, "repair")
    runs.validate_run(topic_id, "final")
    runs.finalize_run(topic_id)
    return runs, runs.export_run(topic_id), topic_id


def test_diagram_export_sidecar_records_runtime_1_2(tmp_path: Path) -> None:
    runs, exported, topic_id = _export_diagrams_run(tmp_path)
    sidecar = json.loads(runs.export_report_path(topic_id).read_text(encoding="utf-8"))
    assert sidecar["export"]["runtime_version"] == "1.2"
    assert 'data-diagram-kind="flow"' in exported.read_text(encoding="utf-8")


def test_diagram_export_content_security_policy_is_unchanged(tmp_path: Path) -> None:
    """Diagrams are drawn by the hashed runtime: the exported CSP gains no
    directive (no img-src, no style/script relaxation)."""
    _runs, exported, _topic_id = _export_diagrams_run(tmp_path)
    assets = load_runtime_assets()

    def sha(text: str) -> str:
        return base64.b64encode(hashlib.sha256(text.encode("utf-8")).digest()).decode()

    csp = re.search(
        r'<meta http-equiv="Content-Security-Policy" content="([^"]*)">',
        exported.read_text(encoding="utf-8"),
    ).group(1)
    assert csp == (
        "default-src 'none'; img-src 'none'; "
        f"style-src 'sha256-{sha(assets.css)}'; "
        f"script-src 'sha256-{sha(assets.javascript)}'; "
        "connect-src 'none'; font-src 'none'; media-src 'none'; "
        "object-src 'none'; frame-src 'none'; base-uri 'none'; form-action 'none'"
    )
