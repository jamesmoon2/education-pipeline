import { useCallback } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiRequestError, getRunStatus } from "../api/client";
import JobsPanel from "../components/JobsPanel";
import { usePolling } from "../hooks/usePolling";

export default function RunBoardPage() {
  const { topicId } = useParams<{ topicId: string }>();
  const fetchStatus = useCallback(() => getRunStatus(topicId!), [topicId]);
  const { data: status, error } = usePolling(fetchStatus, 5_000);

  if (error instanceof ApiRequestError && error.status === 404) {
    return (
      <p>
        No run started for <strong>{topicId}</strong> yet. Start one with{" "}
        <code>edu advance {topicId}</code>.
      </p>
    );
  }
  if (error) return <p className="error">Failed to load run: {error.message}</p>;
  if (!status) return <p>Loading…</p>;

  return (
    <div>
      <h2>{status.topic_id}</h2>
      <p className="next-action">
        <strong>Next:</strong> {status.next_action.detail}
      </p>
      <table>
        <thead>
          <tr>
            <th>Stage</th>
            <th>State</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {status.stages.map((s) => (
            <tr key={s.stage}>
              <td>{s.stage}</td>
              <td>
                <span className={`state state-${s.state}`}>{s.state}</span>
              </td>
              <td>
                <Link to={`/topics/${status.topic_id}/stages/${s.stage}`}>view</Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p>Finalized: {status.finalized ? "yes" : "no"}</p>
      <JobsPanel topicId={status.topic_id} />
    </div>
  );
}
