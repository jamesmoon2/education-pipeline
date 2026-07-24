import { describe, expect, it } from "vitest";
import { parseInline, parseMarkdown } from "./markdown";

describe("parseMarkdown", () => {
  it("parses headings, paragraphs, and rules", () => {
    const blocks = parseMarkdown("# Title\n\nSome prose\nspanning lines.\n\n---\n");
    expect(blocks).toEqual([
      { kind: "heading", level: 1, children: [{ kind: "text", text: "Title" }] },
      {
        kind: "paragraph",
        children: [{ kind: "text", text: "Some prose spanning lines." }],
      },
      { kind: "hr" },
    ]);
  });

  it("keeps fenced code verbatim, including markdown-like lines", () => {
    const blocks = parseMarkdown("```json\n{\"a\": 1}\n# not a heading\n```\nafter");
    expect(blocks[0]).toEqual({
      kind: "code",
      language: "json",
      text: '{"a": 1}\n# not a heading',
    });
    expect(blocks[1]).toEqual({
      kind: "paragraph",
      children: [{ kind: "text", text: "after" }],
    });
  });

  it("closes an unterminated fence at end of input", () => {
    const blocks = parseMarkdown("```\ndangling");
    expect(blocks).toEqual([{ kind: "code", language: null, text: "dangling" }]);
  });

  it("parses ordered and unordered lists", () => {
    const blocks = parseMarkdown("- one\n- two\n\n1. first\n2. second");
    expect(blocks[0]).toEqual({
      kind: "list",
      ordered: false,
      items: [[{ kind: "text", text: "one" }], [{ kind: "text", text: "two" }]],
    });
    expect(blocks[1]).toMatchObject({ kind: "list", ordered: true });
  });

  it("does not read a horizontal rule as a bullet", () => {
    expect(parseMarkdown("---")).toEqual([{ kind: "hr" }]);
  });

  it("folds indented continuation lines into the previous list item", () => {
    const blocks = parseMarkdown(
      "1. **First** (7 min) — starts here\n   and wraps onto this line.\n2. Second item",
    );
    expect(blocks).toEqual([
      {
        kind: "list",
        ordered: true,
        items: [
          [
            { kind: "strong", children: [{ kind: "text", text: "First" }] },
            { kind: "text", text: " (7 min) — starts here and wraps onto this line." },
          ],
          [{ kind: "text", text: "Second item" }],
        ],
      },
    ]);
  });

  it("parses blockquotes recursively", () => {
    expect(parseMarkdown("> quoted line")).toEqual([
      {
        kind: "blockquote",
        children: [
          { kind: "paragraph", children: [{ kind: "text", text: "quoted line" }] },
        ],
      },
    ]);
  });
});

describe("parseInline", () => {
  it("parses code, strong, em, and links", () => {
    expect(parseInline("a `b` **c** *d* [e](https://example.com)")).toEqual([
      { kind: "text", text: "a " },
      { kind: "code", text: "b" },
      { kind: "text", text: " " },
      { kind: "strong", children: [{ kind: "text", text: "c" }] },
      { kind: "text", text: " " },
      { kind: "em", children: [{ kind: "text", text: "d" }] },
      { kind: "text", text: " " },
      {
        kind: "link",
        href: "https://example.com",
        children: [{ kind: "text", text: "e" }],
      },
    ]);
  });

  it("keeps unsafe link targets as literal text", () => {
    // eslint-disable-next-line no-script-url
    expect(parseInline("[x](javascript:alert(1))")).toEqual([
      { kind: "text", text: "[x](javascript:alert(1)" },
      { kind: "text", text: ")" },
    ]);
  });

  it("treats markdown inside code spans as literal", () => {
    expect(parseInline("`**not bold**`")).toEqual([
      { kind: "code", text: "**not bold**" },
    ]);
  });
});
