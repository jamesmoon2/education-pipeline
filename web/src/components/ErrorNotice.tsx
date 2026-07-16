import { useState } from "react";
import { Link } from "react-router-dom";
import { ApiRequestError } from "../api/client";

interface ErrorNoticeProps {
  error: unknown;
  /** Caller context, e.g. "Failed to load topics". */
  prefix?: string;
  /** Re-run the failed request (Retry / Reload latest). */
  onRetry?: () => void;
  /** Unarchive the course this action was refused for. */
  onUnarchive?: () => void;
}

interface Recovery {
  explanation: string;
  action?: JSX.Element;
}

function recoveryFor(
  error: ApiRequestError,
  { onRetry, onUnarchive }: Pick<ErrorNoticeProps, "onRetry" | "onUnarchive">,
): Recovery {
  const retryButton = (label: string) =>
    onRetry ? <button onClick={onRetry}>{label}</button> : undefined;
  switch (error.code) {
    case "stale_content":
      return {
        explanation:
          "This content changed since you loaded it. Reload the latest version, then re-apply your edits.",
        action: retryButton("Reload latest"),
      };
    case "stale_validation":
      return {
        explanation:
          "The validation report no longer matches the current guide. Re-run validation, then retry.",
        action: retryButton("Retry"),
      };
    case "not_found":
      return {
        explanation: "That course or resource does not exist any more.",
        action: <Link to="/">Back to the course library</Link>,
      };
    case "invalid_request":
      return {
        explanation: "The request was not valid. Fix the highlighted input and try again.",
      };
    case "daemon_unreachable":
      return {
        explanation:
          "The local daemon is not reachable. Start it with `education-pipeline ui` in a terminal, then retry.",
        action: retryButton("Retry"),
      };
    case "provider_unavailable":
      return {
        explanation:
          "The configured model provider is not available. Check providers in Settings, or use manual mode.",
        action: <Link to="/settings">Open Settings</Link>,
      };
    case "job_conflict":
      return {
        explanation:
          "Another job is already running for this course. Wait for it to finish or cancel it first.",
        action: retryButton("Retry"),
      };
    case "archived_course":
      return {
        explanation: "This course is archived, so changes are refused.",
        action: onUnarchive ? (
          <button onClick={onUnarchive}>Unarchive</button>
        ) : undefined,
      };
    case "validation_blocked":
      return {
        explanation:
          "Validation findings are blocking this action. Resolve or waive them at the responsible stage.",
      };
    case "reveal_unsupported": {
      const path =
        typeof error.detail?.path === "string" ? error.detail.path : null;
      return {
        explanation:
          "The system file manager could not be opened. Copy the path and open it manually:",
        action: path ? (
          <span className="reveal-fallback">
            <code>{path}</code>{" "}
            <button onClick={() => void navigator.clipboard.writeText(path)}>
              Copy path
            </button>
          </span>
        ) : undefined,
      };
    }
    case "workspace_invalid":
      return {
        explanation:
          "The workspace failed setup validation. Run `education-pipeline workspace check --fix` in a terminal.",
      };
    case "unauthorized":
      return {
        explanation: "The session expired. Reload the page to refresh it.",
      };
    default:
      return {
        explanation: "Something went wrong. Retry; if it keeps failing, report an issue.",
        action: retryButton("Retry"),
      };
  }
}

/**
 * One shared rendering for API failures: a plain-language explanation with a
 * recovery action mapped from the stable error-code catalog, and the raw
 * message/code/detail behind a "details" disclosure. Unknown codes fall back
 * to the generic explanation.
 */
export default function ErrorNotice({ error, prefix, onRetry, onUnarchive }: ErrorNoticeProps) {
  const [open, setOpen] = useState(false);
  const apiError =
    error instanceof ApiRequestError
      ? error
      : new ApiRequestError(
          0,
          "unknown",
          error instanceof Error ? error.message : String(error),
        );
  const { explanation, action } = recoveryFor(apiError, { onRetry, onUnarchive });
  return (
    <div className="error-notice error" role="alert">
      <p>
        {prefix ? `${prefix}: ` : ""}
        {explanation}
      </p>
      {action && <p className="error-notice-action">{action}</p>}
      <p>
        <button
          className="error-notice-details-toggle"
          aria-expanded={open}
          onClick={() => setOpen((current) => !current)}
        >
          {open ? "Hide details" : "Show details"}
        </button>
      </p>
      {open && (
        <dl className="error-notice-details">
          <dt>Code</dt>
          <dd>
            <code>{apiError.code}</code>
          </dd>
          <dt>Message</dt>
          <dd>{apiError.message}</dd>
          {apiError.detail && (
            <>
              <dt>Detail</dt>
              <dd>
                <code>{JSON.stringify(apiError.detail)}</code>
              </dd>
            </>
          )}
        </dl>
      )}
    </div>
  );
}
