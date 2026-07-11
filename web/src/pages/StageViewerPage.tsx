import { useCallback, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiRequestError, getStageContent, postApprove } from "../api/client";
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
  const { data, error, refresh } = usePolling(fetchContent, 5_000);
  const [tab, setTab] = useState<Tab>("prompt");
  const [pasteOpen, setPasteOpen] = useState(false);
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
      <pre className="content">{data[tab] ?? `(no ${tab} yet)`}</pre>
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
      {data.response !== null && data.approved === null && (
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
