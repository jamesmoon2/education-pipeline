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
      return createElement(`h${block.level}`, { key: index }, renderInline(block.children));
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
    case "hr":
      return <hr key={index} />;
  }
}

/** Markdown rendered as React elements — model output never becomes HTML. */
export default function MarkdownView({ markdown }: { markdown: string }) {
  return <div className="markdown-view">{parseMarkdown(markdown).map(renderBlock)}</div>;
}
