import { Fragment, useCallback, useState } from "react";
import { cancelJob, getJobs } from "../api/client";
import { useAction } from "../hooks/useAction";
import { usePolling } from "../hooks/usePolling";
import JobLogView from "./JobLogView";

const ACTIVE_STATUSES = new Set(["queued", "running"]);

export default function JobsPanel({ topicId }: { topicId: string }) {
  const fetchJobs = useCallback(() => getJobs(topicId), [topicId]);
  const { data, error } = usePolling(fetchJobs, 2_000);
  const [openJobId, setOpenJobId] = useState<string | null>(null);
  const cancel = useAction();

  if (error) return <p className="error">Failed to load jobs: {error.message}</p>;
  if (!data) return <p>Loading jobs…</p>;

  return (
    <section>
      <h3>Jobs</h3>
      {data.jobs.length === 0 ? (
        <p>No jobs yet for this topic.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Job</th>
              <th>Stage</th>
              <th>Provider</th>
              <th>Model / effort</th>
              <th>Status</th>
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
                    <td colSpan={6}>
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
