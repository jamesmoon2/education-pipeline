import { useEffect, useRef, useState } from "react";
import { getJobLog } from "../api/client";

/** Raw lines of headroom kept above the visible tail count: enough that
 *  filtering blank lines at render time still leaves `n` real lines, without
 *  the retained buffer growing on every poll chunk for the life of a run. */
const TAIL_LINE_HEADROOM = 50;

/** Bounds a growing log buffer to a rolling suffix, for tail mode: the poll
 *  accumulates a chunk every second for as long as the job runs, so without
 *  this the buffer -- and the cost of re-deriving the visible tail from it
 *  every render -- would grow unboundedly for a three-line display. Always
 *  keeps the trailing (possibly partial) line intact, so a line split
 *  across two poll chunks still reassembles correctly on the next tick. */
export function boundLogTail(raw: string, n: number): string {
  const lines = raw.split("\n");
  return lines.slice(-(n + TAIL_LINE_HEADROOM)).join("\n");
}

/** Keeps only the last `n` non-empty lines of a log, for a compact tail
 *  view -- blank lines (a provider's own formatting) don't count toward
 *  the limit and would otherwise waste a line of the small tail on
 *  nothing. */
function tailLines(text: string, n: number): string {
  const lines = text.split("\n").filter((line) => line.trim() !== "");
  return lines.slice(-n).join("\n");
}

export default function JobLogView({
  jobId,
  active,
  tail,
}: {
  jobId: string;
  active: boolean;
  /** When set, render only the last N non-empty lines instead of the full
   *  log -- the same fetch loop, just a smaller view of its result. */
  tail?: number;
}) {
  const [text, setText] = useState("");
  const offsetRef = useRef(0);

  useEffect(() => {
    setText("");
    offsetRef.current = 0;
    let cancelled = false;
    let timer: number | undefined;

    const tick = async () => {
      try {
        const chunk = await getJobLog(jobId, offsetRef.current);
        if (cancelled) return;
        if (chunk.data) {
          setText((t) => {
            const combined = t + chunk.data;
            return tail ? boundLogTail(combined, tail) : combined;
          });
        }
        offsetRef.current = chunk.offset;
      } catch {
        // transient: keep the text we have; retry on the next tick if active
      }
      if (!cancelled && active) timer = window.setTimeout(tick, 1000);
    };

    void tick();
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [jobId, active, tail]);

  const shown = tail ? tailLines(text, tail) : text;
  return (
    <pre className={tail ? "log log-tail" : "log"}>{shown || "(no output yet)"}</pre>
  );
}
