export interface DiffLine {
  type: "same" | "added" | "removed";
  text: string;
}

function toLines(text: string): string[] {
  return text === "" ? [] : text.split("\n");
}

// Upper bound on the LCS matrix (~32MB of numbers). Beyond it the exact
// diff of the changed core would risk freezing or exhausting the browser,
// so the core degrades to removals-then-additions — which is exactly what
// the LCS emits anyway when the sides share nothing.
const MAX_LCS_CELLS = 4_000_000;

/**
 * Line-level diff. The common prefix and suffix are trimmed first so the
 * O(n·m) longest-common-subsequence only sees the changed core — edits are
 * typically local, so guide-sized documents stay cheap even though the full
 * inputs can run to many thousands of lines.
 */
export function diffLines(a: string, b: string): DiffLine[] {
  const left = toLines(a);
  const right = toLines(b);

  let start = 0;
  while (start < left.length && start < right.length && left[start] === right[start]) {
    start++;
  }
  let endLeft = left.length;
  let endRight = right.length;
  while (endLeft > start && endRight > start && left[endLeft - 1] === right[endRight - 1]) {
    endLeft--;
    endRight--;
  }

  const out: DiffLine[] = [];
  for (let k = 0; k < start; k++) out.push({ type: "same", text: left[k] });
  diffCore(left.slice(start, endLeft), right.slice(start, endRight), out);
  for (let k = endLeft; k < left.length; k++) out.push({ type: "same", text: left[k] });
  return out;
}

function diffCore(left: string[], right: string[], out: DiffLine[]): void {
  const n = left.length;
  const m = right.length;
  if (n * m > MAX_LCS_CELLS) {
    for (const text of left) out.push({ type: "removed", text });
    for (const text of right) out.push({ type: "added", text });
    return;
  }

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
}
