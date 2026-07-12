import { useCallback, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import {
  ApiRequestError,
  getRunStatus,
  getStageContent,
  enqueueJob,
  postApprove,
} from "../api/client";
import DiffView from "../components/DiffView";
import ResponseEditor from "../components/ResponseEditor";
import ResponseForm from "../components/ResponseForm";
import { useAction } from "../hooks/useAction";
import { usePolling } from "../hooks/usePolling";

const TABS = ["prompt", "response", "approved"] as const;
type Tab = (typeof TABS)[number];

export default function StageViewerPage() {
  const { topicId, stage } = useParams<{ topicId: string; stage: string }>();
  const [searchParams] = useSearchParams();
  const findingPath = searchParams.get("json_path");
  const relatedId = searchParams.get("related_id");
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
  const [compare, setCompare] = useState(false);
  const [diffOpen, setDiffOpen] = useState(false);
  const [draftApproved, setDraftApproved] = useState<string | null>(null);
  const approve = useAction(refresh);
  const rerun = useAction(refresh);

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

  const toggleDiff = async () => {
    const next = !diffOpen;
    setDiffOpen(next);
    if (next && draftApproved === null) {
      try {
        const draft = await getStageContent(topicId!, "draft");
        setDraftApproved(draft.approved ?? "");
      } catch {
        setDiffOpen(false);
      }
    }
  };

  return (
    <div>
      <p>
        <Link to={`/topics/${topicId}`}>← back to {topicId}</Link>
      </p>
      <h2>
        {topicId} / {data.stage}
      </h2>
      {findingPath && (
        <p className="finding-location" role="status">
          Finding location: <code>{findingPath}</code>
          {relatedId ? <> · related guide ID <code>{relatedId}</code></> : null}
        </p>
      )}
      <nav className="tabs" role="tablist">
        {TABS.map((t) => (
          <button
            key={t}
            role="tab"
            aria-selected={t === tab}
            className={t === tab ? "tab active" : "tab"}
            disabled={editing}
            onClick={() => setTab(t)}
          >
            {t}
            {data[t] === null ? " (empty)" : ""}
          </button>
        ))}
      </nav>
      <div className="view-toggles">
        <button onClick={() => setCompare((c) => !c)}>
          {compare ? "Single pane" : "Compare prompt ↔ response"}
        </button>
        {data.stage === "repair" && (
          <button onClick={() => void toggleDiff()}>
            {diffOpen ? "Hide diff" : "Diff against draft"}
          </button>
        )}
      </div>
      {showEditor ? (
        <ResponseEditor
          topicId={topicId!}
          stage={data.stage}
          content={data.response ?? ""}
          contentSha256={data.response_sha256 ?? ""}
          contentType={data.content_type}
          onSaved={() => {
            setEditing(false);
            refresh();
          }}
          onClose={() => setEditing(false)}
        />
      ) : compare ? (
        <div className="compare">
          <pre className="content">{data.prompt ?? "(no prompt yet)"}</pre>
          <pre className="content">{data.response ?? "(no response yet)"}</pre>
        </div>
      ) : (
        <pre className="content">{data[tab] ?? `(no ${tab} yet)`}</pre>
      )}
      {diffOpen && draftApproved !== null && (
        <DiffView a={draftApproved} b={data.response ?? ""} />
      )}
      {tab === "response" && canEdit && !editing && (
        <button onClick={() => setEditing(true)}>Edit</button>
      )}
      {data.response !== null && !finalized && (
        <button
          disabled={rerun.busy}
          onClick={() => {
            if (!window.confirm(`Replace the existing ${data.stage} response with a new provider result? The prior hash will remain in the manifest.`)) return;
            void rerun.run(() => enqueueJob(topicId!, data.stage, true), {
              successMessage: `Provider rerun queued for ${data.stage}.`,
            });
          }}
        >
          Rerun with provider…
        </button>
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
        <div>
        {run?.content_contract.kind === "interactive_guide" && data.approved !== null && (
          <p className="warning">Reapproval invalidates downstream validation, finalization, and export until rebuilt.</p>
        )}
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
        </div>
      )}
      {rerun.feedback && <p className={rerun.isError ? "error" : "success"}>{rerun.feedback}</p>}
      {approve.feedback && (
        <p className={approve.isError ? "error" : "success"}>{approve.feedback}</p>
      )}
    </div>
  );
}
