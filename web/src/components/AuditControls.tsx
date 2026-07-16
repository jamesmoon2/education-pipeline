import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { approveAudit, enqueueAuditJob, prepareAudit } from "../api/client";
import type { PersonalizationPayload } from "../api/types";
import { useAction } from "../hooks/useAction";

type AuditState = PersonalizationPayload["audit"];
type ExportState = PersonalizationPayload["export"]["state"];

export default function AuditControls({
  topicId,
  audit,
  exportState,
  onChanged,
}: {
  topicId: string;
  audit: AuditState;
  exportState: ExportState;
  onChanged: () => void;
}) {
  const action = useAction(onChanged);
  const [readyAfterPrepare, setReadyAfterPrepare] = useState(false);
  const auditHref = `/topics/${encodeURIComponent(topicId)}/stages/audit`;

  useEffect(() => {
    setReadyAfterPrepare(false);
  }, [topicId, audit.stage_state]);

  if (!audit.available) {
    return (
      <section aria-label="Optional personalization audit">
        <h3>Optional personalization audit</h3>
        <p>
          Audit unavailable:{" "}
          {audit.unavailable_reason ?? "Current audit inputs are unavailable."}
        </p>
      </section>
    );
  }

  const hasResponse =
    audit.stage_state === "response_ingested" ||
    audit.stage_state === "approved" ||
    audit.stage_state === "stale";
  const promptReady = audit.stage_state === "prompt_written" || readyAfterPrepare;
  const canPrepare = audit.stage_state === "not_run" || audit.stage_state === "pending";
  const canApprove = audit.stage_state === "response_ingested";
  const canReview = hasResponse;
  const canRerun =
    audit.stage_state === "response_ingested" || audit.stage_state === "approved";

  const runProvider = (force: boolean) =>
    action.run(() => enqueueAuditJob(topicId, force), {
      successMessage: force ? "Audit rerun queued." : "Audit job queued.",
    });

  const confirmRerun = () => {
    if (
      !window.confirm(
        "Replace the existing audit response with a new provider result? The prior hash will remain in the manifest.",
      )
    ) {
      return;
    }
    void runProvider(true);
  };

  return (
    <section className="audit-controls" aria-label="Optional personalization audit">
      <h3>Optional personalization audit</h3>
      {audit.state === "current" ? (
        <p className="success">
          Audit is current with {audit.findings.length} projected{" "}
          {audit.findings.length === 1 ? "finding" : "findings"}. It remains optional
          and does not block the primary workflow.
        </p>
      ) : audit.state === "stale" ? (
        <p className="warning">
          The audit is stale and does not describe the current guide and personalization trace.
        </p>
      ) : (
        <p>No approved personalization audit has been run. The audit is optional.</p>
      )}

      <div role="toolbar" aria-label="Audit actions">
        {canPrepare && (
          <button
            type="button"
            disabled={action.busy}
            onClick={() =>
              void action.run(
                async () => {
                  await prepareAudit(topicId, false);
                  setReadyAfterPrepare(true);
                },
                { successMessage: "Audit prompt prepared." },
              )
            }
          >
            Prepare audit
          </button>
        )}
        {audit.stage_state === "stale" && !readyAfterPrepare && (
          <button
            type="button"
            disabled={action.busy}
            onClick={() =>
              void action.run(
                async () => {
                  await prepareAudit(topicId, true);
                  setReadyAfterPrepare(true);
                },
                { successMessage: "Audit prompt rebuilt." },
              )
            }
          >
            Rebuild audit prompt
          </button>
        )}
        {promptReady && (
          <>
            <button
              type="button"
              disabled={action.busy}
              onClick={() => (hasResponse ? confirmRerun() : void runProvider(false))}
            >
              Run audit with provider
            </button>
            <Link to={`${auditHref}?tab=response&paste=1`}>Paste audit response…</Link>
          </>
        )}
        {canReview && (
          <Link
            to={`${auditHref}?tab=${audit.stage_state === "approved" ? "approved" : "response"}`}
          >
            {audit.stage_state === "approved" ? "Review approved audit" : "Review audit response"}
          </Link>
        )}
        {canApprove && (
          <button
            type="button"
            disabled={action.busy}
            onClick={() =>
              void action.run(() => approveAudit(topicId, false), {
                retryWithOverwrite: () => approveAudit(topicId, true),
                successMessage: "Audit approved.",
              })
            }
          >
            Approve audit
          </button>
        )}
        {canRerun && (
          <button type="button" disabled={action.busy} onClick={confirmRerun}>
            Rerun audit with provider…
          </button>
        )}
      </div>

      {exportState === "stale" && (
        <p className="warning">
          Re-export the guide to publish the current audit projection.
        </p>
      )}
      {action.feedback && (
        <p
          className={action.isError ? "error" : "success"}
          role={action.isError ? "alert" : "status"}
        >
          {action.feedback}
        </p>
      )}
    </section>
  );
}
