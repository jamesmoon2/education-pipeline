import { useState } from "react";
import { downloadExport, downloadFinal, postExport } from "../api/client";
import type { ExportFormat } from "../api/types";
import { useAction } from "../hooks/useAction";

export default function ExportControls({ topicId }: { topicId: string }) {
  const [format, setFormat] = useState<ExportFormat>("html");
  const { busy, feedback, isError, run } = useAction();
  return (
    <div className="export-controls">
      <label>
        Format{" "}
        <select
          value={format}
          onChange={(e) => setFormat(e.target.value as ExportFormat)}
        >
          <option value="html">html</option>
          <option value="markdown">markdown</option>
        </select>
      </label>{" "}
      <button
        disabled={busy}
        onClick={() =>
          run(() => postExport(topicId, format), {
            retryWithOverwrite: () => postExport(topicId, format, true),
            successMessage: `Exported ${format}.`,
          })
        }
      >
        Export
      </button>{" "}
      <button
        disabled={busy}
        onClick={() => run(() => downloadFinal(topicId), { successMessage: "Download started." })}
      >
        Download final guide
      </button>{" "}
      <button
        disabled={busy}
        onClick={() =>
          run(() => downloadExport(topicId, "html"), { successMessage: "Download started." })
        }
      >
        Download html export
      </button>{" "}
      <button
        disabled={busy}
        onClick={() =>
          run(() => downloadExport(topicId, "markdown"), { successMessage: "Download started." })
        }
      >
        Download markdown export
      </button>
      {feedback && <p className={isError ? "error" : "success"}>{feedback}</p>}
    </div>
  );
}
