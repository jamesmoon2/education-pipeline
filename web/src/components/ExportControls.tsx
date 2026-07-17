import { useState } from "react";
import { downloadExport, downloadFinal, postExport } from "../api/client";
import type { ExportFormat } from "../api/types";
import { useAction } from "../hooks/useAction";
import InfoTip from "./InfoTip";

export default function ExportControls({ topicId, guideV1 = false }: { topicId: string; guideV1?: boolean }) {
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
          {!guideV1 && <option value="markdown">markdown</option>}
        </select>
      </label>{" "}
      <InfoTip
        label="Export"
        text="Export writes the finished guide into the course's folder in the chosen format — html is a single self-contained file you can open or share anywhere. The download buttons save a copy through your browser."
      />{" "}
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
        onClick={() => run(() => downloadFinal(topicId, guideV1), { successMessage: "Download started." })}
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
      </button>
      {!guideV1 && (
        <button
          disabled={busy}
          onClick={() =>
            run(() => downloadExport(topicId, "markdown"), { successMessage: "Download started." })
          }
        >
          Download markdown export
        </button>
      )}
      {feedback && <p className={isError ? "error" : "success"}>{feedback}</p>}
    </div>
  );
}
