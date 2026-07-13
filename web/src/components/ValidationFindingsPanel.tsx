import { useEffect, useMemo, useState } from "react";
import { ApiRequestError, getValidation, getWaivers, postWaiver } from "../api/client";
import type {
  ValidationFinding,
  ValidationReport,
  Waiver,
} from "../api/types";

type Phase = "draft" | "final";
type ValidationState = "missing" | "current" | "stale";
type SeverityFilter = "all" | ValidationFinding["severity"];
type StatusFilter = "all" | "blocking" | "waivable" | "waived";

function feedbackFor(error: unknown): string {
  if (error instanceof ApiRequestError) return error.message;
  return error instanceof Error ? error.message : "Validation request failed.";
}

function findingHref(topicId: string, finding: ValidationFinding): string {
  const params = new URLSearchParams({ json_path: finding.path });
  const relatedId = finding.related_ids?.[0];
  if (relatedId) params.set("related_id", relatedId);
  return `/topics/${encodeURIComponent(topicId)}/stages/${finding.stage}?${params.toString()}`;
}

export default function ValidationFindingsPanel({
  topicId,
  phase,
  state,
  onChanged,
}: {
  topicId: string;
  phase: Phase;
  state: ValidationState;
  onChanged: () => void;
}) {
  const [report, setReport] = useState<ValidationReport | null>(null);
  const [waivers, setWaivers] = useState<Waiver[]>([]);
  const [waiverState, setWaiverState] = useState<ValidationState>("missing");
  const [loading, setLoading] = useState(false);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [severity, setSeverity] = useState<SeverityFilter>("all");
  const [status, setStatus] = useState<StatusFilter>("all");
  const [waiverFinding, setWaiverFinding] = useState<ValidationFinding | null>(null);
  const [reason, setReason] = useState("");
  const [waiving, setWaiving] = useState(false);

  useEffect(() => {
    setReport(null);
    setWaivers([]);
    setWaiverState("missing");
    setFeedback(null);
    setWaiverFinding(null);
    setReason("");
    if (state === "missing") return;

    let disposed = false;
    setLoading(true);
    Promise.all([getValidation(topicId, phase), getWaivers(topicId, phase)])
      .then(([result, waiverResult]) => {
        if (!disposed) {
          setReport(result.report);
          setWaiverState(waiverResult.state);
          setWaivers(waiverResult.state === "current" ? waiverResult.waivers.waivers : []);
        }
      })
      .catch((error: unknown) => {
        if (!disposed) setFeedback(feedbackFor(error));
      })
      .finally(() => {
        if (!disposed) setLoading(false);
      });
    return () => {
      disposed = true;
    };
  }, [topicId, phase, state]);

  const waivedIds = useMemo(
    () => new Set(waivers.map((waiver) => waiver.finding_id)),
    [waivers],
  );
  const findings = (report?.findings ?? []).filter((finding) => {
    if (severity !== "all" && finding.severity !== severity) return false;
    if (status === "blocking" && !finding.blocking) return false;
    if (status === "waivable" && (!finding.waivable || waivedIds.has(finding.id))) return false;
    if (status === "waived" && !waivedIds.has(finding.id)) return false;
    return true;
  });

  const submitWaiver = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!waiverFinding || !report || !reason.trim() || waiving) return;
    setWaiving(true);
    setFeedback(null);
    try {
      const result = await postWaiver(
        topicId,
        phase,
        waiverFinding.id,
        report.guide_sha256,
        reason,
      );
      setReport(result.report);
      setWaivers(result.waivers.waivers);
      setWaiverState("current");
      setWaiverFinding(null);
      setReason("");
      onChanged();
    } catch (error) {
      // Keep the finding and reason available for correction/retry on 409/422.
      setFeedback(feedbackFor(error));
    } finally {
      setWaiving(false);
    }
  };

  if (state === "missing") {
    return <section aria-label={`${phase} validation findings`}><p>No {phase} validation report yet.</p></section>;
  }

  return (
    <section className="validation-findings" aria-label={`${phase} validation findings`}>
      <p className={state === "stale" ? "error" : "success"}>
        {state === "stale"
          ? `The ${phase} validation report is stale. Findings may not match the current guide.`
          : `The ${phase} validation report is current.`}
      </p>
      {loading && <p>Loading findings…</p>}
      {waiverState === "stale" && (
        <p className="error">Saved waivers are stale and do not apply to this guide hash.</p>
      )}
      {feedback && <p className="error" role="alert">{feedback}</p>}
      {report && (
        <>
          <p>
            {report.summary.blocking} blocking · {report.summary.errors} errors ·{" "}
            {report.summary.warnings} warnings · {waivedIds.size} waived
          </p>
          <div className="validation-filters">
            <label>
              Severity
              <select value={severity} onChange={(event) => setSeverity(event.target.value as SeverityFilter)}>
                <option value="all">All severities</option>
                <option value="blocker">Blocker</option>
                <option value="error">Error</option>
                <option value="warning">Warning</option>
                <option value="info">Info</option>
              </select>
            </label>
            <label>
              Status
              <select value={status} onChange={(event) => setStatus(event.target.value as StatusFilter)}>
                <option value="all">All statuses</option>
                <option value="blocking">Blocking</option>
                <option value="waivable">Waivable</option>
                <option value="waived">Waived</option>
              </select>
            </label>
          </div>
          {findings.length === 0 ? <p>No findings match these filters.</p> : (
            <ul className="validation-finding-list">
              {findings.map((finding) => {
                const waived = waivedIds.has(finding.id);
                return (
                  <li key={finding.id}>
                    <p>
                      <strong>{finding.severity}: {finding.rule_id}</strong>{" "}
                      {finding.blocking && <span>blocking </span>}
                      {waived && <span className="success">waived</span>}
                    </p>
                    <p>{finding.message}</p>
                    <p>Suggested action: {finding.remediation}</p>
                    <a href={findingHref(topicId, finding)}>
                      Open source at {finding.path}
                    </a>
                    {finding.waivable && !waived && state === "current" && (
                      <button type="button" onClick={() => {
                        setWaiverFinding(finding);
                        setReason("");
                        setFeedback(null);
                      }}>Waive…</button>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </>
      )}
      {waiverFinding && report && (
        <div role="dialog" aria-modal="true" aria-labelledby="waiver-title">
          <form onSubmit={(event) => void submitWaiver(event)}>
            <h3 id="waiver-title">Waive {waiverFinding.rule_id}</h3>
            <p>Guide hash: <code>{report.guide_sha256}</code></p>
            <label>
              Reason
              <textarea required value={reason} onChange={(event) => setReason(event.target.value)} />
            </label>
            <button type="submit" disabled={waiving || !reason.trim() || !report.guide_sha256}>
              {waiving ? "Waiving…" : "Confirm waiver"}
            </button>
            <button type="button" disabled={waiving} onClick={() => {
              setWaiverFinding(null);
              setReason("");
            }}>Cancel</button>
          </form>
        </div>
      )}
    </section>
  );
}
