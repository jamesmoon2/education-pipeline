import { useCallback, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiRequestError, getStageContent } from "../api/client";
import { usePolling } from "../hooks/usePolling";

const TABS = ["prompt", "response", "approved"] as const;
type Tab = (typeof TABS)[number];

export default function StageViewerPage() {
  const { topicId, stage } = useParams<{ topicId: string; stage: string }>();
  const fetchContent = useCallback(
    () => getStageContent(topicId!, stage!),
    [topicId, stage],
  );
  const { data, error } = usePolling(fetchContent, 5_000);
  const [tab, setTab] = useState<Tab>("prompt");

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
      <nav className="tabs">
        {TABS.map((t) => (
          <button
            key={t}
            className={t === tab ? "tab active" : "tab"}
            onClick={() => setTab(t)}
          >
            {t}
            {data[t] === null ? " (empty)" : ""}
          </button>
        ))}
      </nav>
      <pre className="content">{data[tab] ?? `(no ${tab} yet)`}</pre>
    </div>
  );
}
