import { useEffect, useMemo, useState } from "react";
import { ApiRequestError, deleteWaiver, getValidation, getWaivers, postValidate, postWaiver } from "../api/client";
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

function findingHref(topicId: string, phase: Phase, finding: ValidationFinding): string {
  const params = new URLSearchParams({ json_path: finding.path });
  const relatedId = finding.related_ids?.[0];
  if (relatedId) params.set("related_id", relatedId);
  // Public projections may identify a safe source stage distinct from the
  // stage that produced the finding. Pre-v2 findings carry neither field.
  const stage =
    finding.source_stage ??
    finding.stage ??
    (phase === "draft" ? "draft" : "repair");
  return `/topics/${encodeURIComponent(topicId)}/stages/${stage}?${params.toString()}`;
}

export default function ValidationFindingsPanel({
  topicId,
  phase,
  state,
  effectiveBlocking,
  supplementalFindings = [],
  onChanged,
}: {
  topicId: string;
  phase: Phase;
  state: ValidationState;
  // Post-waiver blocking count for this phase (RunStatus.validations[phase]
  // .effective_blocking). Optional: callers on older payloads/fixtures that
  // don't carry it fall back to the raw report.summary.blocking count, same
  // as before this field existed.
  effectiveBlocking?: number;
  // Public-safe aggregate findings that are not persisted in the deterministic
  // validation report (currently optional audit findings). Duplicate ids are
  // ignored, and audit findings never participate in waiver or gate controls.
  supplementalFindings?: ValidationFinding[];
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
  const [rerunning, setRerunning] = useState(false);

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
  const combinedFindings = useMemo(() => {
    const merged: ValidationFinding[] = [];
    const seen = new Set<string>();
    for (const finding of [...(report?.findings ?? []), ...supplementalFindings]) {
      if (seen.has(finding.id)) continue;
      seen.add(finding.id);
      merged.push(finding);
    }
    return merged;
  }, [report, supplementalFindings]);
  const findings = combinedFindings.filter((finding) => {
    const auditFinding = finding.stage === "audit";
    if (severity !== "all" && finding.severity !== severity) return false;
    if (status === "blocking" && !finding.blocking) return false;
    if (
      status === "waivable" &&
      (auditFinding || !finding.waivable || waivedIds.has(finding.id))
    ) return false;
    if (status === "waived" && (auditFinding || !waivedIds.has(finding.id))) return false;
    return true;
  });

  const submitWaiver = async (event: React.FormEvent) => {
    event.preventDefault();
    if (
      !waiverFinding ||
      waiverFinding.stage === "audit" ||
      !report ||
      !reason.trim() ||
      waiving
    ) return;
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

  const removeWaiver = async (finding: ValidationFinding) => {
    if (!report || finding.stage === "audit" || waiving) return;
    setWaiving(true);
    setFeedback(null);
    try {
      const result = await deleteWaiver(topicId, phase, finding.id);
      setReport(result.report);
      setWaivers(result.waivers.waivers);
      setWaiverState("current");
      onChanged();
    } catch (error) {
      setFeedback(feedbackFor(error));
    } finally {
      setWaiving(false);
    }
  };

  const rerunValidation = async () => {
    if (rerunning) return;
    setRerunning(true);
    setFeedback(null);
    try {
      const result = await postValidate(topicId, phase);
      setReport(result.report);
      onChanged();
    } catch (error) {
      setFeedback(feedbackFor(error));
    } finally {
      setRerunning(false);
    }
  };

  if (state === "missing") {
    return <section aria-label={`${phase} validation findings`}><p>No {phase} validation report yet.</p></section>;
  }

  // A stale report always offers re-run (its waivers are void by definition
  // -- see report_state). Otherwise, prefer the post-waiver
  // effective_blocking count when the caller has it: a report whose every
  // blocker is waived has an open gate and nothing left to re-run for, even
  // though report.summary.blocking (the raw, pre-waiver count) is still
  // positive. Fall back to the raw count when effectiveBlocking is absent.
  const canRerun =
    state === "stale" ||
    (report !== null &&
      (effectiveBlocking !== undefined ? effectiveBlocking > 0 : report.summary.blocking > 0));

  return (
    <section className="validation-findings" aria-label={`${phase} validation findings`}>
      <p className={state === "stale" ? "error" : "success"}>
        {state === "stale"
          ? `The ${phase} validation report is stale. Findings may not match the current guide.`
          : `The ${phase} validation report is current.`}
      </p>
      {canRerun && (
        <button type="button" disabled={rerunning} onClick={() => void rerunValidation()}>
          {rerunning ? "Re-running validation…" : "Re-run validation"}
        </button>
      )}
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
                const auditFinding = finding.stage === "audit";
                const waived = !auditFinding && waivedIds.has(finding.id);
                return (
                  <li key={finding.id}>
                    <p>
                      <strong>{finding.severity}: {finding.rule_id}</strong>{" "}
                      {finding.blocking && <span>blocking </span>}
                      {waived && <span className="success">waived</span>}
                    </p>
                    <p>{finding.message}</p>
                    <p>Suggested action: {finding.remediation}</p>
                    <a href={findingHref(topicId, phase, finding)}>
                      Open source at {finding.path}
                    </a>
                    {!auditFinding && finding.waivable && !waived && state === "current" && (
                      <button type="button" onClick={() => {
                        setWaiverFinding(finding);
                        setReason("");
                        setFeedback(null);
                      }}>Waive…</button>
                    )}
                    {!auditFinding && waived && state === "current" && (
                      <button
                        type="button"
                        disabled={waiving}
                        onClick={() => void removeWaiver(finding)}
                      >Unwaive</button>
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
