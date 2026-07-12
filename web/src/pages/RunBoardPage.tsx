import { useCallback } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiRequestError, getRunStatus, postAdvance } from "../api/client";
import JobsPanel from "../components/JobsPanel";
import PrimaryAction from "../components/PrimaryAction";
import ValidationFindingsPanel from "../components/ValidationFindingsPanel";
import { useAction } from "../hooks/useAction";
import { usePolling } from "../hooks/usePolling";

export default function RunBoardPage() {
  const { topicId } = useParams<{ topicId: string }>();
  const fetchStatus = useCallback(() => getRunStatus(topicId!), [topicId]);
  const { data: status, error, refresh } = usePolling(fetchStatus, 5_000);
  const start = useAction(refresh);

  if (error instanceof ApiRequestError && error.status === 404) {
    return (
      <div>
        <p>
          No run started for <strong>{topicId}</strong> yet.
        </p>
        <button
          disabled={start.busy}
          onClick={() =>
            start.run(() => postAdvance(topicId!), { successMessage: "Run started." })
          }
        >
          Advance
        </button>
        {start.feedback && (
          <p className={start.isError ? "error" : "success"}>{start.feedback}</p>
        )}
      </div>
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
      <PrimaryAction status={status} onChanged={refresh} />
      {status.content_contract.kind === "interactive_guide" && (
        <section aria-labelledby="validation-heading">
          <h3 id="validation-heading">Validation milestones</h3>
          <table>
            <thead><tr><th>Phase</th><th>State</th><th>Blocking</th><th>Errors</th><th>Warnings</th></tr></thead>
            <tbody>
              {(["draft", "final"] as const).map((phase) => {
                const validation = status.validations[phase];
                return <tr key={phase}>
                  <td>{phase}</td><td>{validation.state}</td><td>{validation.blocking}</td>
                  <td>{validation.errors}</td><td>{validation.warnings}</td>
                </tr>;
              })}
            </tbody>
          </table>
          {(["draft", "final"] as const).map((phase) => (
            <ValidationFindingsPanel
              key={phase}
              topicId={status.topic_id}
              phase={phase}
              state={status.validations[phase].state}
              onChanged={refresh}
            />
          ))}
        </section>
      )}
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
