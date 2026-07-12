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
