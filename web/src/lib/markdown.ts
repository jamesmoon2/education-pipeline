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

export interface MarkdownListItem {
  content: InlineNode[];
  sublist: MarkdownList | null;
}

export interface MarkdownList {
  kind: "list";
  ordered: boolean;
  items: MarkdownListItem[];
}

export type MarkdownBlock =
  | { kind: "heading"; level: 1 | 2 | 3 | 4 | 5 | 6; children: InlineNode[] }
  | { kind: "paragraph"; children: InlineNode[] }
  | { kind: "code"; language: string | null; text: string }
  | MarkdownList
  | { kind: "blockquote"; children: MarkdownBlock[] }
  | { kind: "table"; header: InlineNode[][]; rows: InlineNode[][][] }
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
const TABLE_ROW = /^\s*\|.*\|\s*$/;
const TABLE_SEPARATOR = /^\s*\|(?:\s*:?-+:?\s*\|)+\s*$/;

function parseTableRow(line: string): InlineNode[][] {
  return line
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((cell) => parseInline(cell.trim()));
}

interface RawListItem {
  indent: number;
  ordered: boolean;
  text: string;
}

// Assemble a flat run of indent-annotated items into nested lists: an item
// indented deeper than the current level becomes a sublist of the item
// before it. The cursor is shared across recursion levels so each item is
// consumed exactly once.
function buildList(
  raw: RawListItem[],
  cursor: { index: number },
  indent: number,
): MarkdownList {
  const ordered = raw[cursor.index].ordered;
  const items: MarkdownListItem[] = [];
  while (cursor.index < raw.length) {
    const item = raw[cursor.index];
    if (item.indent < indent) break;
    if (item.indent > indent) {
      const sublist = buildList(raw, cursor, item.indent);
      if (items.length > 0) items[items.length - 1].sublist = sublist;
      else items.push({ content: [], sublist }); // over-indented first item
      continue;
    }
    items.push({ content: parseInline(item.text), sublist: null });
    cursor.index += 1;
  }
  return { kind: "list", ordered, items };
}

function startsBlock(line: string): boolean {
  return (
    line.trim() === "" ||
    FENCE.test(line) ||
    HEADING.test(line) ||
    HR.test(line) ||
    UNORDERED_ITEM.test(line) ||
    ORDERED_ITEM.test(line) ||
    QUOTE.test(line) ||
    TABLE_ROW.test(line)
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
    if (UNORDERED_ITEM.test(line) || ORDERED_ITEM.test(line)) {
      const raw: RawListItem[] = [];
      while (i < lines.length && !HR.test(lines[i])) {
        const current = lines[i];
        const unordered = current.match(UNORDERED_ITEM);
        const item = unordered ?? current.match(ORDERED_ITEM);
        if (item) {
          raw.push({
            indent: /^\s*/.exec(current)![0].length,
            ordered: unordered === null,
            text: item[1],
          });
        } else if (/^\s+\S/.test(current) && raw.length > 0) {
          // Indented continuation of the previous item (hard-wrapped source).
          raw[raw.length - 1].text += ` ${current.trim()}`;
        } else {
          break;
        }
        i += 1;
      }
      blocks.push(buildList(raw, { index: 0 }, raw[0].indent));
      continue;
    }
    // A pipe row is a table only when followed by the |---|---| separator;
    // a lone pipe-bearing line stays a paragraph.
    if (TABLE_ROW.test(line) && i + 1 < lines.length && TABLE_SEPARATOR.test(lines[i + 1])) {
      const header = parseTableRow(line);
      i += 2; // past the header and separator
      const rows: InlineNode[][][] = [];
      while (i < lines.length && TABLE_ROW.test(lines[i]) && !TABLE_SEPARATOR.test(lines[i])) {
        rows.push(parseTableRow(lines[i]));
        i += 1;
      }
      blocks.push({ kind: "table", header, rows });
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
