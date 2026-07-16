"""Stable error-code catalog shared by the daemon API, CLI, and cockpit.

Every daemon error response is ``{"error": {"code", "message", "detail"}}``
where ``code`` is a stable slug from this catalog (spec §7.1). Codes are
**append-only**: renaming or removing a code breaks recovery-action mapping
in shipped cockpits, so retired codes stay retired and new conditions get
new codes. Anything unmapped surfaces as ``internal``.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ErrorCode:
    """A stable error code with its user-directed recovery action."""

    code: str
    summary: str
    remediation: str


def _entry(code: str, summary: str, remediation: str) -> tuple[str, ErrorCode]:
    return code, ErrorCode(code=code, summary=summary, remediation=remediation)


#: The one catalog. Append-only; keep codes lowercase snake_case.
ERROR_CATALOG: dict[str, ErrorCode] = dict(
    [
        # --- spec §7.1 initial catalog -------------------------------------
        _entry(
            "stale_content",
            "The content changed on disk since it was loaded.",
            "Reload the latest version, then re-apply your edits.",
        ),
        _entry(
            "not_found",
            "The requested course, stage, or resource does not exist.",
            "Return to the course library and pick a current course.",
        ),
        _entry(
            "invalid_request",
            "The request was not valid.",
            "Fix the highlighted input and try again.",
        ),
        _entry(
            "workspace_invalid",
            "The workspace failed setup validation.",
            "Run `education-pipeline workspace check --fix` and follow the findings.",
        ),
        _entry(
            "workspace_unselected",
            "No workspace is selected.",
            "Pass --workspace PATH, or run `education-pipeline ui` in a terminal to choose one.",
        ),
        _entry(
            "provider_unavailable",
            "The configured model provider is not available.",
            "Open Settings → providers, or switch the stage to manual mode.",
        ),
        _entry(
            "job_conflict",
            "Another job is already running for this course.",
            "Wait for the running job to finish, or cancel it first.",
        ),
        _entry(
            "archived_course",
            "This course is archived, so write actions are refused.",
            "Unarchive the course first.",
        ),
        _entry(
            "validation_blocked",
            "Deterministic validation is blocking this action.",
            "Open the findings at the responsible stage and resolve or waive them.",
        ),
        _entry(
            "web_assets_missing",
            "The built cockpit assets were not found.",
            "Run `npm run build` in web/, or install a packaged release.",
        ),
        _entry(
            "reveal_unsupported",
            "The system file manager could not be opened.",
            "Copy the shown path and open it manually.",
        ),
        _entry(
            "internal",
            "Something went wrong inside the daemon.",
            "Retry; if it keeps failing, report an issue with the daemon log.",
        ),
        # --- synthesized client-side ---------------------------------------
        _entry(
            "daemon_unreachable",
            "The local daemon is not reachable.",
            "Start it with `education-pipeline ui` (or `daemon start`), then retry.",
        ),
        # --- pre-existing daemon codes kept by the envelope migration ------
        _entry(
            "already_exists",
            "The target already exists.",
            "Retry with overwrite/force if replacing it is intended.",
        ),
        _entry(
            "not_ready",
            "A prerequisite step has not completed yet.",
            "Perform the named prerequisite step first.",
        ),
        _entry(
            "stale_validation",
            "The validation report no longer matches the current guide.",
            "Re-run validation, then retry this action.",
        ),
        _entry(
            "finding_not_waivable",
            "This finding cannot be waived.",
            "Resolve the finding at its stage instead.",
        ),
        _entry(
            "guide_not_renderable",
            "The guide content is not renderable under the guide contract.",
            "Fix the guide JSON at the responsible stage and revalidate.",
        ),
        _entry(
            "invalid_guide_json",
            "The guide text is not valid JSON.",
            "Fix the JSON syntax and try again.",
        ),
        _entry(
            "unauthorized",
            "The request token is missing or invalid.",
            "Reload the cockpit page to refresh the session token.",
        ),
        _entry(
            "bad_host",
            "The request Host header is not allowed.",
            "Access the cockpit via 127.0.0.1 or localhost only.",
        ),
    ]
)


def remediation_for(code: str) -> str | None:
    """Return the recovery-action text for a known code, else ``None``."""

    entry = ERROR_CATALOG.get(code)
    return entry.remediation if entry is not None else None
