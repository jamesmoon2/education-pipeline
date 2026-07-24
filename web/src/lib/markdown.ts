// Dependency-free markdown parser for the stage content views. Covers the
// subset stage artifacts actually use (headings, paragraphs, fenced code,
// flat lists, blockquotes, rules, and inline code/strong/em/links) and
// returns a node tree the renderer maps to React elements — content is never
// injected as HTML, so untrusted model output stays inert. Anything the
// subset can't express still reads fine as literal text, and the viewer's
// Raw toggle shows the exact bytes.

export type InlineNode =
  | { kind: "text"; text: string }
  | { kind: "code"; text: string }
  | { kind: "strong"; children: InlineNode[] }
  | { kind: "em"; children: InlineNode[] }
  | { kind: "link"; href: string; children: InlineNode[] };

export type MarkdownBlock =
  | { kind: "heading"; level: 1 | 2 | 3 | 4 | 5 | 6; children: InlineNode[] }
  | { kind: "paragraph"; children: InlineNode[] }
  | { kind: "code"; language: string | null; text: string }
  | { kind: "list"; ordered: boolean; items: InlineNode[][] }
  | { kind: "blockquote"; children: MarkdownBlock[] }
  | { kind: "hr" };

// Only link targets that cannot execute script; everything else renders as
// literal text.
const SAFE_HREF = /^(https?:|mailto:|#)/i;

interface InlinePattern {
  re: RegExp;
  make: (match: RegExpMatchArray) => InlineNode | null;
}

const INLINE_PATTERNS: InlinePattern[] = [
  { re: /`([^`]+)`/, make: (m) => ({ kind: "code", text: m[1] }) },
  {
    re: /\*\*([^*]+)\*\*/,
    make: (m) => ({ kind: "strong", children: parseInline(m[1]) }),
  },
  { re: /\*([^*]+)\*/, make: (m) => ({ kind: "em", children: parseInline(m[1]) }) },
  { re: /_([^_]+)_/, make: (m) => ({ kind: "em", children: parseInline(m[1]) }) },
  {
    re: /\[([^\]]+)\]\(([^)\s]+)\)/,
    make: (m) =>
      SAFE_HREF.test(m[2])
        ? { kind: "link", href: m[2], children: parseInline(m[1]) }
        : null,
  },
];

export function parseInline(text: string): InlineNode[] {
  const nodes: InlineNode[] = [];
  let rest = text;
  while (rest.length > 0) {
    let earliest: { index: number; match: RegExpMatchArray; pattern: InlinePattern } | null =
      null;
    for (const pattern of INLINE_PATTERNS) {
      const match = rest.match(pattern.re);
      if (match?.index === undefined) continue;
      if (!earliest || match.index < earliest.index) {
        earliest = { index: match.index, match, pattern };
      }
    }
    if (!earliest) {
      nodes.push({ kind: "text", text: rest });
      break;
    }
    const node = earliest.pattern.make(earliest.match);
    const matched = earliest.match[0];
    if (node === null) {
      // Unsafe link target: keep the whole match as literal text.
      const upTo = earliest.index + matched.length;
      nodes.push({ kind: "text", text: rest.slice(0, upTo) });
      rest = rest.slice(upTo);
      continue;
    }
    if (earliest.index > 0) {
      nodes.push({ kind: "text", text: rest.slice(0, earliest.index) });
    }
    nodes.push(node);
    rest = rest.slice(earliest.index + matched.length);
  }
  return nodes;
}

const FENCE = /^```(\S*)\s*$/;
const HEADING = /^(#{1,6})\s+(.*)$/;
const HR = /^(?:-{3,}|\*{3,}|_{3,})\s*$/;
const UNORDERED_ITEM = /^\s*[-*+]\s+(.*)$/;
const ORDERED_ITEM = /^\s*\d+[.)]\s+(.*)$/;
const QUOTE = /^>\s?(.*)$/;

function startsBlock(line: string): boolean {
  return (
    line.trim() === "" ||
    FENCE.test(line) ||
    HEADING.test(line) ||
    HR.test(line) ||
    UNORDERED_ITEM.test(line) ||
    ORDERED_ITEM.test(line) ||
    QUOTE.test(line)
  );
}

export function parseMarkdown(text: string): MarkdownBlock[] {
  const blocks: MarkdownBlock[] = [];
  const lines = text.split("\n");
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (line.trim() === "") {
      i += 1;
      continue;
    }
    const fence = line.match(FENCE);
    if (fence) {
      const body: string[] = [];
      i += 1;
      while (i < lines.length && !FENCE.test(lines[i])) {
        body.push(lines[i]);
        i += 1;
      }
      i += 1; // past the closing fence (or EOF on an unterminated block)
      blocks.push({ kind: "code", language: fence[1] || null, text: body.join("\n") });
      continue;
    }
    const heading = line.match(HEADING);
    if (heading) {
      blocks.push({
        kind: "heading",
        level: heading[1].length as 1 | 2 | 3 | 4 | 5 | 6,
        children: parseInline(heading[2]),
      });
      i += 1;
      continue;
    }
    if (HR.test(line)) {
      blocks.push({ kind: "hr" });
      i += 1;
      continue;
    }
    // HR is checked before lists so "---" never reads as a "-" bullet.
    const itemRe = UNORDERED_ITEM.test(line) ? UNORDERED_ITEM : ORDERED_ITEM.test(line) ? ORDERED_ITEM : null;
    if (itemRe) {
      const items: string[] = [];
      while (i < lines.length && !HR.test(lines[i])) {
        const item = lines[i].match(itemRe);
        if (item) {
          items.push(item[1]);
        } else if (/^\s+\S/.test(lines[i])) {
          // Indented continuation of the previous item (hard-wrapped source).
          items[items.length - 1] += ` ${lines[i].trim()}`;
        } else {
          break;
        }
        i += 1;
      }
      blocks.push({
        kind: "list",
        ordered: itemRe === ORDERED_ITEM,
        items: items.map(parseInline),
      });
      continue;
    }
    if (QUOTE.test(line)) {
      const inner: string[] = [];
      while (i < lines.length) {
        const quoted = lines[i].match(QUOTE);
        if (!quoted) break;
        inner.push(quoted[1]);
        i += 1;
      }
      blocks.push({ kind: "blockquote", children: parseMarkdown(inner.join("\n")) });
      continue;
    }
    const paragraph: string[] = [line];
    i += 1;
    while (i < lines.length && !startsBlock(lines[i])) {
      paragraph.push(lines[i]);
      i += 1;
    }
    blocks.push({ kind: "paragraph", children: parseInline(paragraph.join(" ")) });
  }
  return blocks;
}
