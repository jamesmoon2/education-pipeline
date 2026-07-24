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
      items: [
        { content: [{ kind: "text", text: "one" }], sublist: null },
        { content: [{ kind: "text", text: "two" }], sublist: null },
      ],
    });
    expect(blocks[1]).toMatchObject({ kind: "list", ordered: true });
  });

  it("nests indented items as a sublist of the item above", () => {
    const blocks = parseMarkdown(
      "1. Top level\n   - nested one\n   - nested two\n2. Second top",
    );
    expect(blocks).toEqual([
      {
        kind: "list",
        ordered: true,
        items: [
          {
            content: [{ kind: "text", text: "Top level" }],
            sublist: {
              kind: "list",
              ordered: false,
              items: [
                { content: [{ kind: "text", text: "nested one" }], sublist: null },
                { content: [{ kind: "text", text: "nested two" }], sublist: null },
              ],
            },
          },
          { content: [{ kind: "text", text: "Second top" }], sublist: null },
        ],
      },
    ]);
  });

  it("returns from a sublist to the parent level and nests multiple levels", () => {
    const blocks = parseMarkdown(
      "- a\n  - a1\n    - a1x\n- b",
    );
    expect(blocks[0]).toEqual({
      kind: "list",
      ordered: false,
      items: [
        {
          content: [{ kind: "text", text: "a" }],
          sublist: {
            kind: "list",
            ordered: false,
            items: [
              {
                content: [{ kind: "text", text: "a1" }],
                sublist: {
                  kind: "list",
                  ordered: false,
                  items: [{ content: [{ kind: "text", text: "a1x" }], sublist: null }],
                },
              },
            ],
          },
        },
        { content: [{ kind: "text", text: "b" }], sublist: null },
      ],
    });
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
          {
            content: [
              { kind: "strong", children: [{ kind: "text", text: "First" }] },
              { kind: "text", text: " (7 min) — starts here and wraps onto this line." },
            ],
            sublist: null,
          },
          { content: [{ kind: "text", text: "Second item" }], sublist: null },
        ],
      },
    ]);
  });

  it("parses a pipe table with a separator row", () => {
    const blocks = parseMarkdown(
      "| Loop | Effect |\n|------|--------|\n| Reinforcing | amplifies |\n| Balancing | steadies |",
    );
    expect(blocks).toEqual([
      {
        kind: "table",
        header: [
          [{ kind: "text", text: "Loop" }],
          [{ kind: "text", text: "Effect" }],
        ],
        rows: [
          [[{ kind: "text", text: "Reinforcing" }], [{ kind: "text", text: "amplifies" }]],
          [[{ kind: "text", text: "Balancing" }], [{ kind: "text", text: "steadies" }]],
        ],
      },
    ]);
  });

  it("keeps a lone pipe-bearing line as a paragraph", () => {
    expect(parseMarkdown("a | b | c")).toEqual([
      { kind: "paragraph", children: [{ kind: "text", text: "a | b | c" }] },
    ]);
  });

  it("ends a paragraph where a table starts", () => {
    const blocks = parseMarkdown("intro line\n| A | B |\n|---|---|\n| 1 | 2 |");
    expect(blocks[0]).toEqual({
      kind: "paragraph",
      children: [{ kind: "text", text: "intro line" }],
    });
    expect(blocks[1]).toMatchObject({ kind: "table" });
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
