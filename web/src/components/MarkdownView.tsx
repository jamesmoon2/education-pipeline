import { createElement, Fragment, memo, type ReactNode } from "react";
import {
  parseMarkdown,
  type InlineNode,
  type MarkdownBlock,
  type MarkdownList,
} from "../lib/markdown";

function renderInline(nodes: InlineNode[]): ReactNode {
  return nodes.map((node, index) => {
    switch (node.kind) {
      case "text":
        return <Fragment key={index}>{node.text}</Fragment>;
      case "code":
        return <code key={index}>{node.text}</code>;
      case "strong":
        return <strong key={index}>{renderInline(node.children)}</strong>;
      case "em":
        return <em key={index}>{renderInline(node.children)}</em>;
      case "link":
        return (
          <a key={index} href={node.href} target="_blank" rel="noreferrer">
            {renderInline(node.children)}
          </a>
        );
    }
  });
}

function renderList(list: MarkdownList, key?: number): ReactNode {
  const items = list.items.map((item, itemIndex) => (
    <li key={itemIndex}>
      {renderInline(item.content)}
      {item.sublist && renderList(item.sublist)}
    </li>
  ));
  return list.ordered ? <ol key={key}>{items}</ol> : <ul key={key}>{items}</ul>;
}

function renderBlock(block: MarkdownBlock, index: number): ReactNode {
  switch (block.kind) {
    case "heading":
      // Artifact content renders beneath the stage page's own <h2> title, so
      // its headings are offset to start at <h3> — a source "# h1" as a real
      // <h1> would invert the document outline for screen readers.
      return createElement(
        `h${Math.min(6, block.level + 2)}`,
        { key: index },
        renderInline(block.children),
      );
    case "paragraph":
      return <p key={index}>{renderInline(block.children)}</p>;
    case "code":
      return (
        <pre key={index} className="content">
          {block.text}
        </pre>
      );
    case "list":
      return renderList(block, index);
    case "blockquote":
      return <blockquote key={index}>{block.children.map(renderBlock)}</blockquote>;
    case "table":
      return (
        <table key={index}>
          <thead>
            <tr>
              {block.header.map((cell, cellIndex) => (
                <th key={cellIndex}>{renderInline(cell)}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {block.rows.map((row, rowIndex) => (
              <tr key={rowIndex}>
                {row.map((cell, cellIndex) => (
                  <td key={cellIndex}>{renderInline(cell)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      );
    case "hr":
      return <hr key={index} />;
  }
}

/** Markdown rendered as React elements — model output never becomes HTML. */
function MarkdownView({ markdown }: { markdown: string }) {
  return <div className="markdown-view">{parseMarkdown(markdown).map(renderBlock)}</div>;
}

// Re-parsing and re-rendering a whole artifact is the most expensive thing a
// stage page does, and its only prop is the artifact text — so a parent
// re-render (a poll tick, a sibling's state) must not reach it unless that
// text actually changed.
export default memo(MarkdownView);
