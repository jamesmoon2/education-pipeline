export interface DiffLine {
  type: "same" | "added" | "removed";
  text: string;
}

function toLines(text: string): string[] {
  return text === "" ? [] : text.split("\n");
}

/**
 * Line-level diff via longest-common-subsequence. O(n·m) time and space,
 * which is fine for guide-sized inputs (a few thousand lines).
 */
export function diffLines(a: string, b: string): DiffLine[] {
  const left = toLines(a);
  const right = toLines(b);
  const n = left.length;
  const m = right.length;

  // lcs[i][j] = LCS length of left[i:] vs right[j:]
  const lcs: number[][] = Array.from({ length: n + 1 }, () =>
    new Array<number>(m + 1).fill(0),
  );
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      lcs[i][j] =
        left[i] === right[j]
          ? lcs[i + 1][j + 1] + 1
          : Math.max(lcs[i + 1][j], lcs[i][j + 1]);
    }
  }

  const out: DiffLine[] = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (left[i] === right[j]) {
      out.push({ type: "same", text: left[i] });
      i++;
      j++;
    } else if (lcs[i + 1][j] >= lcs[i][j + 1]) {
      out.push({ type: "removed", text: left[i] });
      i++;
    } else {
      out.push({ type: "added", text: right[j] });
      j++;
    }
  }
  while (i < n) out.push({ type: "removed", text: left[i++] });
  while (j < m) out.push({ type: "added", text: right[j++] });
  return out;
}
