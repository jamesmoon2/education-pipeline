import { memo, type ReactNode } from "react";

function summarize(value: unknown): string {
  if (Array.isArray(value)) {
    return value.length === 1 ? "1 item" : `${value.length} items`;
  }
  const size = Object.keys(value as object).length;
  return size === 1 ? "1 key" : `${size} keys`;
}

function Leaf({ name, value }: { name: string | null; value: unknown }) {
  const cls =
    value === null
      ? "json-null"
      : typeof value === "string"
        ? "json-string"
        : typeof value === "boolean"
          ? "json-boolean"
          : "json-number";
  return (
    <div className="json-leaf">
      {name !== null && <span className="json-key">{name}: </span>}
      <span className={cls}>{JSON.stringify(value)}</span>
    </div>
  );
}

function Node({
  name,
  value,
  depth,
}: {
  name: string | null;
  value: unknown;
  depth: number;
}): ReactNode {
  if (value === null || typeof value !== "object") {
    return <Leaf name={name} value={value} />;
  }
  const entries: [string, unknown][] = Array.isArray(value)
    ? value.map((item, index) => [String(index), item])
    : Object.entries(value);
  const braces = Array.isArray(value) ? "[…]" : "{…}";
  return (
    <details className="json-node" open={depth < 2}>
      <summary>
        {name !== null && <span className="json-key">{name} </span>}
        <span className="json-braces">{braces}</span>{" "}
        <span className="json-size">{summarize(value)}</span>
      </summary>
      <div className="json-children">
        {entries.map(([key, child]) => (
          <Node key={key} name={key} value={child} depth={depth + 1} />
        ))}
      </div>
    </details>
  );
}

/**
 * A collapsible tree over already-parsed JSON. Nesting collapses below two
 * levels via native <details>, so large guide documents open scannable.
 */
function JsonTreeView({ value }: { value: unknown }) {
  return (
    <div className="json-tree">
      <Node name={null} value={value} depth={0} />
    </div>
  );
}

// Walking a guide document builds thousands of nodes. `value` is handed over
// by StageContentView's parse memo, so it only changes when the stage text
// does — every other parent re-render can stop here.
export default memo(JsonTreeView);
