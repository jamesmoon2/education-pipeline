import type {
  PersonalizationEvidence,
  PersonalizationPayload,
} from "../api/types";

function traceMessage(state: PersonalizationPayload["trace"]["state"]): string {
  if (state === "missing") return "Personalization trace is not available yet.";
  if (state === "stale") return "Personalization trace is stale.";
  if (state === "invalid") return "Personalization trace is invalid.";
  return "Personalization trace is current.";
}

function auditMessage(state: PersonalizationPayload["audit"]["state"]): string {
  if (state === "current") return "Optional audit is current.";
  if (state === "stale") return "Optional audit is stale.";
  return "Optional audit has not been run.";
}

function exportMessage(state: PersonalizationPayload["export"]["state"]): string {
  if (state === "current") return "Export is current.";
  if (state === "stale") {
    return "Re-export to publish the current personalization evidence.";
  }
  return "No guide export is available yet.";
}

export default function PersonalizationPanel({
  personalization,
  onEvidence,
}: {
  personalization: PersonalizationPayload;
  onEvidence: (evidence: PersonalizationEvidence) => void;
}) {
  const noProfile = personalization.profile.state === "not_attached";
  const traceCurrent = personalization.trace.state === "current";

  return (
    <section className="personalization-panel" aria-labelledby="personalization-fit-heading">
      <h3 id="personalization-fit-heading">Personalization fit</h3>
      {noProfile ? (
        <p>No learner profile is attached.</p>
      ) : (
        <p>Profile: {personalization.profile.id}</p>
      )}

      {!noProfile && (
        <>
          <p className={traceCurrent ? "success" : "warning"}>
            {traceMessage(personalization.trace.state)}
          </p>
          {traceCurrent && (
            <>
              <div>
                <h4>Active facets</h4>
                {personalization.trace.facets.length === 0 ? (
                  <p>No active profile facets.</p>
                ) : (
                  <ul>
                    {personalization.trace.facets.map((facet) => <li key={facet}>{facet}</li>)}
                  </ul>
                )}
              </div>
              <div>
                <h4>Goals</h4>
                {personalization.trace.goals.length === 0 ? (
                  <p>No learner goals are available.</p>
                ) : (
                  <ul className="personalization-goals">
                    {personalization.trace.goals.map((goal) => (
                      <li key={goal.goal_id}>
                        <p><strong>{goal.goal_text}</strong> — {goal.status}</p>
                        {goal.exclusions.map((exclusion, index) => (
                          <p key={`${goal.goal_id}-exclusion-${index}`}>
                            Exclusion: {exclusion.reason}
                          </p>
                        ))}
                        {goal.evidence.length > 0 && (
                          <ul aria-label={`Evidence for ${goal.goal_text}`}>
                            {goal.evidence.map((evidence) => (
                              <li key={`${evidence.kind}-${evidence.id}`}>
                                <button type="button" onClick={() => onEvidence(evidence)}>
                                  Open {evidence.kind} {evidence.id}
                                </button>
                              </li>
                            ))}
                          </ul>
                        )}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </>
          )}
        </>
      )}

      <div>
        <h4>Optional audit</h4>
        <p className={personalization.audit.state === "current" ? "success" : "warning"}>
          {auditMessage(personalization.audit.state)}
        </p>
        {!personalization.audit.available && personalization.audit.unavailable_reason && !noProfile && (
          <p>{personalization.audit.unavailable_reason}</p>
        )}
      </div>
      <p className={personalization.export.state === "stale" ? "warning" : undefined}>
        {exportMessage(personalization.export.state)}
      </p>
    </section>
  );
}
