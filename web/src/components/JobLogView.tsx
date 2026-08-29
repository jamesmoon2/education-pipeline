import { useEffect, useRef, useState } from "react";
import { getJobLog } from "../api/client";

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
        if (chunk.data) setText((t) => t + chunk.data);
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
  }, [jobId, active]);

  const shown = tail ? tailLines(text, tail) : text;
  return (
    <pre className={tail ? "log log-tail" : "log"}>{shown || "(no output yet)"}</pre>
  );
}
