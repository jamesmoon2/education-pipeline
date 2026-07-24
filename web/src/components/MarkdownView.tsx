import { createElement, Fragment, type ReactNode } from "react";
import { parseMarkdown, type InlineNode, type MarkdownBlock } from "../lib/markdown";

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
    case "list": {
      const items = block.items.map((item, itemIndex) => (
        <li key={itemIndex}>{renderInline(item)}</li>
      ));
      return block.ordered ? <ol key={index}>{items}</ol> : <ul key={index}>{items}</ul>;
    }
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
export default function MarkdownView({ markdown }: { markdown: string }) {
  return <div className="markdown-view">{parseMarkdown(markdown).map(renderBlock)}</div>;
}
