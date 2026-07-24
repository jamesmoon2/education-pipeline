import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { getJobs } from "../api/client";
import type { Job } from "../api/types";
import { usePolling } from "../hooks/usePolling";
import { ACTIVE_JOB_STATUSES } from "./JobsPanel";

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
}: {
  intervalMs?: number;
  successToastMs?: number;
}) {
  const { data, error } = usePolling(getJobs, intervalMs);
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

  return (
    <>
      {active.length > 0 && (
        <nav className="rail-jobs" aria-label="Active jobs">
          <strong>
            {active.length === 1 ? "1 job running" : `${active.length} jobs running`}
          </strong>
          <ul>
            {active.map((job) => (
              <li key={job.id}>
                <Link to={`/topics/${job.topic_id}`}>
                  {job.stage} · {job.topic_id}
                </Link>
              </li>
            ))}
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
