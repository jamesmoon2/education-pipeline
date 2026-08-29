import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { getJobs, getTopics } from "../api/client";
import type { Job, TopicSummary } from "../api/types";
import { useNow } from "../hooks/useNow";
import { usePolling } from "../hooks/usePolling";
import { formatDurationMs, jobElapsedMs } from "../lib/time";
import { ACTIVE_JOB_STATUSES } from "./JobsPanel";

interface ReadyTopic {
  topic: TopicSummary;
  stage: string;
}

/** Every job in `jobs` is already known active, so ticking it is
 *  unconditional here -- the row only exists while its job is active, and
 *  disappears (taking `useNow`'s interval with it) the moment it isn't. */
function ActiveJobRow({ job }: { job: Job }) {
  const now = useNow();
  const elapsedMs = jobElapsedMs(job, now);
  return (
    <li>
      <Link to={`/topics/${job.topic_id}`}>
        {job.stage} · {job.topic_id}
      </Link>
      {elapsedMs !== null && (
        <span className="rail-jobs-elapsed">{formatDurationMs(elapsedMs)}</span>
      )}
    </li>
  );
}

interface JobToast {
  key: number;
  job: Job;
}

/**
 * App-rail job awareness: provider jobs run for minutes, and without this
 * they are only visible on their own run board. Polls the workspace-wide
 * jobs endpoint to show a live "running" list on every page, and raises a
 * toast when a job observed active reaches a terminal state — success
 * auto-dismisses, failure stays until dismissed. Jobs first seen already
 * terminal never toast (history isn't news).
 */
export default function GlobalJobActivity({
  intervalMs = 5_000,
  successToastMs = 8_000,
  topicsIntervalMs = 10_000,
}: {
  intervalMs?: number;
  successToastMs?: number;
  topicsIntervalMs?: number;
}) {
  const { data, error } = usePolling(getJobs, intervalMs);
  const { data: topicsData, error: topicsError } = usePolling(getTopics, topicsIntervalMs);
  const [toasts, setToasts] = useState<JobToast[]>([]);
  const seenStatus = useRef<Map<string, Job["status"]>>(new Map());
  const nextKey = useRef(0);
  const dismissTimers = useRef<number[]>([]);
  useEffect(() => {
    const timers = dismissTimers.current;
    return () => {
      for (const timer of timers) window.clearTimeout(timer);
    };
  }, []);

  useEffect(() => {
    if (!data) return;
    const finished: JobToast[] = [];
    for (const job of data.jobs) {
      const previous = seenStatus.current.get(job.id);
      seenStatus.current.set(job.id, job.status);
      if (
        previous &&
        ACTIVE_JOB_STATUSES.has(previous) &&
        !ACTIVE_JOB_STATUSES.has(job.status)
      ) {
        finished.push({ key: nextKey.current++, job });
      }
    }
    if (finished.length === 0) return;
    setToasts((current) => [...current, ...finished]);
    for (const toast of finished) {
      if (toast.job.status !== "succeeded") continue;
      dismissTimers.current.push(
        window.setTimeout(() => {
          setToasts((current) => current.filter((t) => t.key !== toast.key));
        }, successToastMs),
      );
    }
  }, [data, successToastMs]);

  const dismiss = (key: number) =>
    setToasts((current) => current.filter((t) => t.key !== key));

  // While the poll is failing, usePolling keeps its last successful payload;
  // presenting that snapshot as live would leave terminated jobs labeled
  // "running" through a daemon outage. Suppress the rail until a fresh poll
  // succeeds (error clears on the next successful tick).
  const active = error
    ? []
    : (data?.jobs.filter((job) => ACTIVE_JOB_STATUSES.has(job.status)) ?? []);

  // Same rule as the jobs poll above: while this poll is failing,
  // usePolling keeps its last successful topics payload, and presenting
  // that as live could still list a topic as "ready to review" after a
  // reviewer approved it during the outage (or hide one newly ready).
  // Suppress the section until a fresh poll succeeds.
  const readyToReview: ReadyTopic[] = topicsError
    ? []
    : (topicsData?.topics
        .filter((topic): topic is TopicSummary & { run: NonNullable<TopicSummary["run"]> } =>
          !topic.archived && topic.run?.next_action.action === "approve",
        )
        .flatMap((topic) => {
          const stage = topic.run.next_action.stage;
          return stage ? [{ topic, stage }] : [];
        }) ?? []);
  const readyShown = readyToReview.slice(0, 5);
  const readyOverflow = readyToReview.length - readyShown.length;

  return (
    <>
      {active.length > 0 && (
        <nav className="rail-jobs" aria-label="Active jobs">
          <strong>
            {active.length === 1 ? "1 job running" : `${active.length} jobs running`}
          </strong>
          <ul>
            {active.map((job) => (
              <ActiveJobRow key={job.id} job={job} />
            ))}
          </ul>
        </nav>
      )}
      {readyToReview.length > 0 && (
        <nav className="rail-ready" aria-label="Ready to review">
          <strong>Ready to review</strong>
          <ul>
            {readyShown.map(({ topic, stage }) => (
              <li key={topic.id}>
                <Link to={`/topics/${topic.id}/stages/${stage}?tab=response`}>
                  {topic.title ?? topic.id}
                </Link>
              </li>
            ))}
            {readyOverflow > 0 && (
              <li>
                <Link to="/">+{readyOverflow} more</Link>
              </li>
            )}
          </ul>
        </nav>
      )}
      {toasts.length > 0 && (
        <div className="toast-region" aria-label="Job notifications">
          {toasts.map(({ key, job }) => (
            <div
              key={key}
              className={`toast ${job.status === "succeeded" ? "toast-success" : "toast-error"}`}
              role={job.status === "succeeded" ? "status" : "alert"}
            >
              {job.status === "succeeded" ? (
                <p>
                  The {job.stage} stage finished on{" "}
                  <Link to={`/topics/${job.topic_id}/stages/${job.stage}?tab=response`}>
                    {job.topic_id}
                  </Link>{" "}
                  — ready to review.
                </p>
              ) : (
                <p>
                  The {job.stage} stage {job.status} on{" "}
                  <Link to={`/topics/${job.topic_id}`}>{job.topic_id}</Link>
                  {job.error ? ` — ${job.error}` : "."}
                </p>
              )}
              <button aria-label="Dismiss notification" onClick={() => dismiss(key)}>
                ×
              </button>
            </div>
          ))}
        </div>
      )}
    </>
  );
}
