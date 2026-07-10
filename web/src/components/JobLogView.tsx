import { useEffect, useRef, useState } from "react";
import { getJobLog } from "../api/client";

export default function JobLogView({ jobId, active }: { jobId: string; active: boolean }) {
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

  return <pre className="log">{text || "(no output yet)"}</pre>;
}
