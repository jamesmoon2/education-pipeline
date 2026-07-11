import { diffLines } from "../lib/diff";

export default function DiffView({ a, b }: { a: string; b: string }) {
  const rows = diffLines(a, b);
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
