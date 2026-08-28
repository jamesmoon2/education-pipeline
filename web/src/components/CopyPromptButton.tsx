import { useEffect, useRef, useState } from "react";

const COPIED_VISIBLE_MS = 3000;

export default function CopyPromptButton({
  getText,
}: {
  /** Resolves to the exact text to place on the clipboard; reject to
   *  surface the manual-copy fallback message instead. */
  getText: () => Promise<string>;
}) {
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(
    () => () => {
      if (timer.current !== null) clearTimeout(timer.current);
    },
    [],
  );

  const copy = async () => {
    if (timer.current !== null) clearTimeout(timer.current);
    setState("idle");
    try {
      const text = await getText();
      const clipboard = navigator.clipboard;
      if (!clipboard?.writeText) throw new Error("clipboard unavailable");
      await clipboard.writeText(text);
      setState("copied");
      timer.current = setTimeout(() => setState("idle"), COPIED_VISIBLE_MS);
    } catch {
      setState("failed");
    }
  };

  return (
    <span className="copy-prompt">
      <button onClick={() => void copy()}>Copy prompt</button>
      {state === "copied" && (
        <span className="success copy-prompt-feedback" role="status">
          Copied ✓
        </span>
      )}
      {state === "failed" && (
        <span className="error copy-prompt-feedback" role="alert">
          Copy failed — select the prompt text and copy it manually.
        </span>
      )}
    </span>
  );
}
