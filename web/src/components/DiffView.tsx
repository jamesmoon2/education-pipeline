import { memo, useMemo } from "react";
import { diffLines } from "../lib/diff";

function DiffView({ a, b }: { a: string; b: string }) {
  // Deps are primitive strings, so fresh-but-equal payloads from polling
  // reuse the computed diff instead of re-running the quadratic LCS.
  const rows = useMemo(() => diffLines(a, b), [a, b]);
  return (
    <div className="diff">
      {rows.map((row, i) => (
        <div key={i} className={`diff-line diff-${row.type}`}>
          <span className="diff-marker">
            {row.type === "added" ? "+" : row.type === "removed" ? "-" : " "}
          </span>
          <span>{row.text || " "}</span>
        </div>
      ))}
    </div>
  );
}

// Both props are the raw stage strings, so a parent re-render that changed
// nothing (a poll tick landing an equal payload) stops here rather than
// walking every diff row again.
export default memo(DiffView);
