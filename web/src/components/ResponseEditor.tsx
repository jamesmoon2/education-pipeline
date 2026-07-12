import { useEffect, useState } from "react";
import {
  ApiRequestError,
  getStageContent,
  postGuidePreview,
  postPreview,
  putResponse,
} from "../api/client";
import { useAction } from "../hooks/useAction";
import GuidePreviewFrame from "./GuidePreviewFrame";

const GUIDE_CONTENT_TYPE =
  "application/vnd.education-pipeline.guide+json;version=1.0";

export default function ResponseEditor({
  topicId,
  stage,
  content,
  contentSha256,
  contentType,
  onSaved,
  onClose,
}: {
  topicId: string;
  stage: string;
  content: string;
  contentSha256: string;
  contentType: "text/markdown" | typeof GUIDE_CONTENT_TYPE;
  onSaved: () => void;
  onClose: () => void;
}) {
  const [buffer, setBuffer] = useState(content);
  // The save precondition: only adopted from the server, never from polling,
  // so an external edit can never be silently overwritten.
  const [baseSha, setBaseSha] = useState(contentSha256);
  const [stale, setStale] = useState(false);
  const [currentOnDisk, setCurrentOnDisk] = useState<string | null>(null);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewHtml, setPreviewHtml] = useState("");
  const save = useAction(onSaved);
  const isGuide = contentType === GUIDE_CONTENT_TYPE;
  let jsonError: string | null = null;
  if (isGuide) {
    try {
      JSON.parse(buffer);
    } catch (error) {
      jsonError = error instanceof SyntaxError ? error.message : "Invalid JSON";
    }
  }

  const requestPreview = () =>
    (isGuide ? postGuidePreview(buffer) : postPreview(buffer))
      .then((r) => setPreviewHtml(r.html))
      .catch(() => {}); // keep the last good preview on transient errors

  useEffect(() => {
    if (!previewOpen) return;
    const timer = window.setTimeout(() => {
      if (jsonError === null) void requestPreview();
    }, 500);
    return () => window.clearTimeout(timer);
  }, [previewOpen, buffer, isGuide, jsonError]);

  const togglePreview = () => {
    const next = !previewOpen;
    setPreviewOpen(next);
    if (next) {
      if (jsonError === null) void requestPreview();
    }
  };

  const doSave = () =>
    save.run(async () => {
      try {
        await putResponse(topicId, stage, buffer, baseSha);
        setStale(false);
      } catch (err) {
        if (
          err instanceof ApiRequestError &&
          err.status === 409 &&
          err.code === "stale_content"
        ) {
          setStale(true);
        }
        throw err;
      }
    });

  const reload = async () => {
    const fresh = await getStageContent(topicId, stage);
    setCurrentOnDisk(fresh.response ?? "(the response was deleted on disk)");
    if (fresh.response_sha256 !== null) setBaseSha(fresh.response_sha256);
    setStale(false);
  };

  const cancel = () => {
    if (buffer !== content && !window.confirm("Discard unsaved changes?")) return;
    onClose();
  };

  return (
    <div className="response-editor">
      <div className="editor-panes">
        <label>
          Edit response for {stage}
          <textarea
            value={buffer}
            onChange={(e) => setBuffer(e.target.value)}
            rows={20}
          />
        </label>
        {previewOpen && isGuide && previewHtml && (
          <GuidePreviewFrame html={previewHtml} />
        )}
        {previewOpen && !isGuide && (
          <div
            className="preview content"
            // Safe: the server renderer escapes all content and emits no
            // scripts, and this page is same-origin authed loopback.
            dangerouslySetInnerHTML={{ __html: previewHtml }}
          />
        )}
        {currentOnDisk !== null && <pre className="content">{currentOnDisk}</pre>}
      </div>
      <div className="editor-controls">
        <button disabled={save.busy || !buffer.trim()} onClick={doSave}>
          Save
        </button>
        <button onClick={togglePreview}>
          {previewOpen ? "Hide preview" : "Preview"}
        </button>
        <button onClick={cancel}>Cancel</button>
        {stale && (
          <button onClick={() => void reload()}>Reload current content</button>
        )}
      </div>
      {jsonError && <p className="error" role="alert">JSON syntax error: {jsonError}</p>}
      {save.feedback && (
        <p className={save.isError ? "error" : "success"}>{save.feedback}</p>
      )}
    </div>
  );
}
