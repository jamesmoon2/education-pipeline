import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  archiveRun,
  duplicateTopic,
  getProfiles,
  getTopics,
  revealTarget,
  unarchiveRun,
} from "../api/client";
import AttachProfileControl from "../components/AttachProfileControl";
import ErrorNotice from "../components/ErrorNotice";
import InfoTip from "../components/InfoTip";
import WelcomePanel from "../components/WelcomePanel";
import ImportForm from "../components/ImportForm";
import { useAction } from "../hooks/useAction";
import { usePolling } from "../hooks/usePolling";
import { nextActionLabel } from "../lib/labels";
import type { ProfileSummary, TopicSummary } from "../api/types";

type StatusFilter = "all" | "no_run" | "in_progress" | "finalized";
type SortKey = "last_activity" | "title" | "completion";

function statusOf(topic: TopicSummary): Exclude<StatusFilter, "all"> {
  if (!topic.run) return "no_run";
  return topic.run.finalized ? "finalized" : "in_progress";
}

function completionScore(topic: TopicSummary): number {
  if (!topic.completion) return -1;
  const ratio =
    topic.completion.stages_total > 0
      ? topic.completion.stages_approved / topic.completion.stages_total
      : 0;
  return ratio + (topic.completion.exported ? 1 : 0);
}

export function filterAndSortTopics(
  topics: TopicSummary[],
  options: {
    query: string;
    status: StatusFilter;
    learner: string;
    showArchived: boolean;
    sort: SortKey;
  },
): TopicSummary[] {
  const query = options.query.trim().toLowerCase();
  const visible = topics.filter((topic) => {
    if (topic.archived && !options.showArchived) return false;
    if (options.status !== "all" && statusOf(topic) !== options.status) return false;
    if (options.learner !== "any" && topic.profile_id !== options.learner) return false;
    if (
      query &&
      !topic.id.toLowerCase().includes(query) &&
      !(topic.title ?? "").toLowerCase().includes(query)
    ) {
      return false;
    }
    return true;
  });
  const sorted = [...visible];
  if (options.sort === "title") {
    sorted.sort((a, b) => (a.title ?? a.id).localeCompare(b.title ?? b.id));
  } else if (options.sort === "completion") {
    sorted.sort((a, b) => completionScore(b) - completionScore(a));
  } else {
    sorted.sort((a, b) => {
      const left = a.last_activity ?? "";
      const right = b.last_activity ?? "";
      if (left === right) return a.id.localeCompare(b.id);
      if (!left) return 1;
      if (!right) return -1;
      return right.localeCompare(left);
    });
  }
  return sorted;
}

// Where the "Next action" cell takes you. An approval is the one action that
// needs the pending response in front of the reviewer; every other action —
// and a topic with no run yet — starts from the board's action area.
function nextActionHref(topic: TopicSummary): string {
  const next = topic.run?.next_action;
  if (next?.action === "approve" && next.stage) {
    return `/topics/${topic.id}/stages/${next.stage}?tab=response`;
  }
  return `/topics/${topic.id}`;
}

function formatActivity(stamp: string | null): string {
  if (!stamp) return "—";
  const parsed = new Date(stamp);
  return Number.isNaN(parsed.getTime()) ? "—" : parsed.toLocaleString();
}

export default function TopicListPage() {
  const { data, error, refresh } = usePolling(getTopics, 10_000);
  const { data: profileData } = usePolling(getProfiles, 30_000);
  const [importKind, setImportKind] = useState<"topic" | "profile" | null>(null);
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<StatusFilter>("all");
  const [learner, setLearner] = useState("any");
  const [showArchived, setShowArchived] = useState(false);
  const [sort, setSort] = useState<SortKey>("last_activity");
  const [revealedPath, setRevealedPath] = useState<string | null>(null);
  const [actionError, setActionError] = useState<{ error: unknown; topicId: string } | null>(null);
  const action = useAction(refresh);

  const topics = useMemo(() => data?.topics ?? [], [data]);
  const learners = useMemo(
    () =>
      Array.from(
        new Set(topics.map((topic) => topic.profile_id).filter((id): id is string => !!id)),
      ).sort(),
    [topics],
  );
  // Filtering and sorting the whole library on every render is wasted work:
  // most re-renders here come from a poll tick or an unrelated control, not
  // from one of these inputs.
  const rows = useMemo(
    () => filterAndSortTopics(topics, { query, status, learner, showArchived, sort }),
    [topics, query, status, learner, showArchived, sort],
  );

  if (error) return <ErrorNotice prefix="Failed to load topics" error={error} onRetry={refresh} />;
  if (!data) return <p>Loading…</p>;

  const runAction = (topicId: string, fn: () => Promise<unknown>) => {
    setActionError(null);
    setRevealedPath(null);
    void action.run(async () => {
      try {
        await fn();
      } catch (err) {
        setActionError({ error: err, topicId });
        throw err;
      }
    });
  };

  const reveal = (topic: TopicSummary) => {
    runAction(topic.id, async () => {
      const result = await revealTarget(topic.run ? "run" : "topic", topic.id);
      setRevealedPath(result.path);
    });
  };

  const profiles: ProfileSummary[] = profileData?.profiles ?? [];

  return (
    <div>
      <WelcomePanel />
      {topics.length === 0 ? (
        <div className="empty-state">
          <p>No topics yet.</p>
          <p>
            <Link to="/new" className="primary-cta">
              Create your first course →
            </Link>
          </p>
          <p className="toolbar">
            <button onClick={() => setImportKind(importKind === "topic" ? null : "topic")}>
              Import topic…
            </button>
          </p>
          {importKind === "topic" && (
            <ImportForm
              kind="topic"
              onDone={() => {
                setImportKind(null);
                refresh();
              }}
            />
          )}
        </div>
      ) : (
        <>
          <p className="toolbar">
            <button onClick={() => setImportKind(importKind === "topic" ? null : "topic")}>
              Import topic…
            </button>{" "}
            <button onClick={() => setImportKind(importKind === "profile" ? null : "profile")}>
              Import profile…
            </button>
          </p>
          {importKind && (
            <ImportForm
              kind={importKind}
              onDone={() => {
                setImportKind(null);
                refresh();
              }}
            />
          )}
          <div className="library-filters toolbar" role="group" aria-label="Library filters">
            <label>
              Filter courses
              <input
                type="search"
                aria-label="Filter courses"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
            </label>{" "}
            <label>
              Status
              <select value={status} onChange={(e) => setStatus(e.target.value as StatusFilter)}>
                <option value="all">All</option>
                <option value="no_run">No run yet</option>
                <option value="in_progress">In progress</option>
                <option value="finalized">Finalized</option>
              </select>
            </label>{" "}
            <label>
              Learner
              <select value={learner} onChange={(e) => setLearner(e.target.value)}>
                <option value="any">any</option>
                {learners.map((id) => (
                  <option key={id} value={id}>
                    {id}
                  </option>
                ))}
              </select>
            </label>{" "}
            <label>
              Sort by
              <select value={sort} onChange={(e) => setSort(e.target.value as SortKey)}>
                <option value="last_activity">Last activity</option>
                <option value="title">Title</option>
                <option value="completion">Completion</option>
              </select>
            </label>{" "}
            <label>
              <input
                type="checkbox"
                aria-label="Show archived"
                checked={showArchived}
                onChange={(e) => setShowArchived(e.target.checked)}
              />
              Show archived
            </label>
          </div>
          {actionError && (
            <ErrorNotice
              error={actionError.error}
              onRetry={() => setActionError(null)}
              onUnarchive={() => {
                const topicId = actionError.topicId;
                setActionError(null);
                void action.run(() => unarchiveRun(topicId));
              }}
            />
          )}
          {revealedPath && (
            <p className="reveal-result">
              Revealed: <code>{revealedPath}</code>
            </p>
          )}
          <table>
            <thead>
              <tr>
                <th>Topic</th>
                <th>Title</th>
                <th>Next action</th>
                <th>Last activity</th>
                <th>Completion</th>
                <th>Profile</th>
                <th>
                  Actions{" "}
                  <InfoTip
                    label="Actions"
                    text="Reveal opens the course's folder on this computer — every prompt, response, and export lives there as a plain file. Duplicate copies a course so you can take it in a new direction. Archive tucks a finished course out of the list without deleting anything."
                  />
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((t) => (
                <tr key={t.id} className={t.archived ? "archived-row" : undefined}>
                  <td>
                    <Link to={`/topics/${t.id}`}>{t.id}</Link>
                    {t.archived && (
                      <>
                        {" "}
                        <span className="badge">Archived</span>
                      </>
                    )}
                  </td>
                  <td>{t.error ? <span className="error">{t.error}</span> : (t.title ?? "—")}</td>
                  <td>
                    <Link to={nextActionHref(t)}>
                      {t.run ? nextActionLabel(t.run.next_action.action) : "No run yet"}
                    </Link>
                  </td>
                  <td>{formatActivity(t.last_activity)}</td>
                  <td>
                    {t.completion
                      ? `${t.completion.stages_approved}/${t.completion.stages_total}` +
                        (t.completion.exported ? " · exported" : "")
                      : "—"}
                  </td>
                  <td>
                    {t.profile_id && (
                      <>
                        <span className="attached-profile">{t.profile_id}</span>{" "}
                      </>
                    )}
                    <AttachProfileControl topicId={t.id} profiles={profiles} onDone={refresh} />
                  </td>
                  <td className="library-actions">
                    {t.run &&
                      (t.archived ? (
                        <button
                          aria-label={`Unarchive ${t.id}`}
                          disabled={action.busy}
                          onClick={() => runAction(t.id, () => unarchiveRun(t.id))}
                        >
                          Unarchive
                        </button>
                      ) : (
                        <button
                          aria-label={`Archive ${t.id}`}
                          disabled={action.busy}
                          onClick={() => runAction(t.id, () => archiveRun(t.id))}
                        >
                          Archive
                        </button>
                      ))}{" "}
                    <button
                      aria-label={`Duplicate ${t.id}`}
                      disabled={action.busy}
                      onClick={() => runAction(t.id, () => duplicateTopic(t.id))}
                    >
                      Duplicate
                    </button>{" "}
                    <button
                      aria-label={`Reveal ${t.id}`}
                      disabled={action.busy}
                      onClick={() => reveal(t)}
                    >
                      Reveal
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}
