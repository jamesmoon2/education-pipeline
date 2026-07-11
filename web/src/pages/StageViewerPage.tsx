import { useCallback, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  ApiRequestError,
  getRunStatus,
  getStageContent,
  postApprove,
} from "../api/client";
import ResponseEditor from "../components/ResponseEditor";
import ResponseForm from "../components/ResponseForm";
import { useAction } from "../hooks/useAction";
import { usePolling } from "../hooks/usePolling";

const TABS = ["prompt", "response", "approved"] as const;
type Tab = (typeof TABS)[number];

export default function StageViewerPage() {
  const { topicId, stage } = useParams<{ topicId: string; stage: string }>();
  const fetchContent = useCallback(
    () => getStageContent(topicId!, stage!),
    [topicId, stage],
  );
  const fetchRun = useCallback(() => getRunStatus(topicId!), [topicId]);
  const { data, error, refresh } = usePolling(fetchContent, 5_000);
  const { data: run } = usePolling(fetchRun, 5_000);
  const [tab, setTab] = useState<Tab>("prompt");
  const [pasteOpen, setPasteOpen] = useState(false);
  const [editing, setEditing] = useState(false);
  const approve = useAction(refresh);

  if (error instanceof ApiRequestError && error.status === 404) {
    return (
      <p>
        No run started for <strong>{topicId}</strong>.
      </p>
    );
  }
  if (error) return <p className="error">{error.message}</p>;
  if (!data) return <p>Loading…</p>;

  const finalized = run ? run.finalized : true; // hide Edit until status loads
  const canEdit = data.response !== null && !finalized;
  const needsApproval =
    data.response !== null &&
    (data.approved === null || data.approved !== data.response);
  const showEditor = editing && canEdit && tab === "response";

  return (
    <div>
      <p>
        <Link to={`/topics/${topicId}`}>← back to {topicId}</Link>
      </p>
      <h2>
        {topicId} / {data.stage}
      </h2>
      <nav className="tabs" role="tablist">
        {TABS.map((t) => (
          <button
            key={t}
            role="tab"
            aria-selected={t === tab}
            className={t === tab ? "tab active" : "tab"}
            onClick={() => setTab(t)}
          >
            {t}
            {data[t] === null ? " (empty)" : ""}
          </button>
        ))}
      </nav>
      {showEditor ? (
        <ResponseEditor
          topicId={topicId!}
          stage={data.stage}
          content={data.response ?? ""}
          contentSha256={data.response_sha256 ?? ""}
          onSaved={() => {
            setEditing(false);
            refresh();
          }}
          onClose={() => setEditing(false)}
        />
      ) : (
        <pre className="content">{data[tab] ?? `(no ${tab} yet)`}</pre>
      )}
      {tab === "response" && canEdit && !editing && (
        <button onClick={() => setEditing(true)}>Edit</button>
      )}
      {data.response === null && (
        <div>
          <button onClick={() => setPasteOpen((open) => !open)}>Paste response…</button>
          {pasteOpen && (
            <ResponseForm
              topicId={topicId!}
              stage={data.stage}
              onDone={() => {
                setPasteOpen(false);
                refresh();
              }}
            />
          )}
        </div>
      )}
      {needsApproval && (
        <button
          disabled={approve.busy}
          onClick={() =>
            approve.run(() => postApprove(topicId!, data.stage), {
              retryWithOverwrite: () => postApprove(topicId!, data.stage, true),
              successMessage: `Approved ${data.stage}.`,
            })
          }
        >
          Approve {data.stage}
        </button>
      )}
      {approve.feedback && (
        <p className={approve.isError ? "error" : "success"}>{approve.feedback}</p>
      )}
    </div>
  );
}
