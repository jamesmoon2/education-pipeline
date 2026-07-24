import { useMemo, useState } from "react";
import JsonTreeView from "./JsonTreeView";
import MarkdownView from "./MarkdownView";

/**
 * A stage artifact rendered for review — markdown as formatted prose, JSON
 * (including the guide contract) as a collapsible tree — with a Raw toggle
 * showing the exact bytes on disk.
 */
export default function StageContentView({
  label,
  text,
  contentType,
}: {
  /** The artifact's name in empty/aria text: "prompt", "response", "approved". */
  label: string;
  text: string | null;
  contentType: string;
}) {
  const [raw, setRaw] = useState(false);
  const isJson = contentType.includes("json");
  const parsed = useMemo(() => {
    if (text === null || !isJson) return null;
    try {
      return { value: JSON.parse(text) as unknown };
    } catch {
      return null; // not valid JSON (yet) — fall back to the raw bytes
    }
  }, [text, isJson]);

  if (text === null) return <pre className="content">{`(no ${label} yet)`}</pre>;

  const canRender = !isJson || parsed !== null;
  return (
    <div className="stage-content">
      {canRender && (
        <div className="content-mode" role="group" aria-label={`${label} display mode`}>
          <button aria-pressed={!raw} onClick={() => setRaw(false)}>
            Rendered
          </button>
          <button aria-pressed={raw} onClick={() => setRaw(true)}>
            Raw
          </button>
        </div>
      )}
      {!canRender ? (
        <>
          <p className="content-fallback-note">
            Not valid JSON — showing the raw text.
          </p>
          <pre className="content">{text}</pre>
        </>
      ) : raw ? (
        <pre className="content">{text}</pre>
      ) : isJson ? (
        <JsonTreeView value={parsed!.value} />
      ) : (
        <MarkdownView markdown={text} />
      )}
    </div>
  );
}
