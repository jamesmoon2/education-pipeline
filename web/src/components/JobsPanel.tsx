import { Fragment, useCallback, useState } from "react";
import { cancelJob, getJobs } from "../api/client";
import type { Job } from "../api/types";
import { useAction } from "../hooks/useAction";
import { useNow } from "../hooks/useNow";
import { usePolling } from "../hooks/usePolling";
import { formatDurationMs, jobElapsedMs } from "../lib/time";
import JobLogView from "./JobLogView";
import ErrorNotice from "./ErrorNotice";
import InfoTip from "./InfoTip";

export const ACTIVE_JOB_STATUSES = new Set(["queued", "running"]);
const ACTIVE_STATUSES = ACTIVE_JOB_STATUSES;

/** Elapsed-time cell for a job row. A terminal job's span never changes, so
 *  it's a plain snapshot; an active job's is split into its own component
 *  so `useNow`'s tick applies only to rows that are actually still moving,
 *  not to every row in the table. */
function JobTiming({ job }: { job: Job }) {
  if (!ACTIVE_STATUSES.has(job.status)) {
    const ms = jobElapsedMs(job, Date.now());
    return <>{ms === null ? "—" : formatDurationMs(ms)}</>;
  }
  return <TickingJobTiming job={job} />;
}

function TickingJobTiming({ job }: { job: Job }) {
  const now = useNow();
  const ms = jobElapsedMs(job, now);
  return <>{ms === null ? "—" : formatDurationMs(ms)}</>;
}

export default function JobsPanel({ topicId }: { topicId: string }) {
  const fetchJobs = useCallback(() => getJobs(topicId), [topicId]);
  const { data, error } = usePolling(fetchJobs, 2_000);
  const [openJobId, setOpenJobId] = useState<string | null>(null);
  const cancel = useAction();

  if (error) return <ErrorNotice prefix="Failed to load jobs" error={error} />;
  if (!data) return <p>Loading jobs…</p>;

  return (
    <section>
      <h3>Jobs</h3>
      <InfoTip
        label="Jobs"
        text="Background runs of stage prompts through a provider CLI. Each job's log captures the provider's live output (audit jobs redact their log to protect learner privacy)."
      />
      {data.jobs.length === 0 ? (
        <p>
          No jobs yet — the next action is shown above; run it with a configured
          provider, or copy the prompt into any model and paste the response back.
        </p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Job</th>
              <th>Stage</th>
              <th>Provider</th>
              <th>Model / effort</th>
              <th>Status</th>
              <th>Time</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {data.jobs.map((job) => (
              <Fragment key={job.id}>
                <tr>
                  <td>{job.id}</td>
                  <td>{job.stage}</td>
                  <td>{job.provider}</td>
                  <td>{job.model ?? "default"}{job.effort ? ` / ${job.effort}` : ""}</td>
                  <td>
                    {job.status}
                    {job.error ? <span className="error"> — {job.error}</span> : null}
                  </td>
                  <td>
                    <JobTiming job={job} />
                  </td>
                  <td>
                    <button
                      onClick={() => setOpenJobId(openJobId === job.id ? null : job.id)}
                    >
                      {openJobId === job.id ? "hide log" : "log"}
                    </button>
                    {ACTIVE_STATUSES.has(job.status) && (
                      <button
                        disabled={cancel.busy}
                        onClick={() =>
                          cancel.run(() => cancelJob(job.id), {
                            successMessage: `Canceling ${job.id}.`,
                          })
                        }
                      >
                        cancel
                      </button>
                    )}
                  </td>
                </tr>
                {openJobId === job.id ? (
                  <tr>
                    <td colSpan={7}>
                      <JobLogView jobId={job.id} active={ACTIVE_STATUSES.has(job.status)} />
                    </td>
                  </tr>
                ) : null}
              </Fragment>
            ))}
          </tbody>
        </table>
      )}
      {cancel.feedback && (
        <p className={cancel.isError ? "error" : "success"}>{cancel.feedback}</p>
      )}
    </section>
  );
}
