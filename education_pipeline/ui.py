"""The `education-pipeline ui` launcher: one command to a running cockpit.

Orchestration only (spec §2): resolve the workspace (flag → registry →
first-run selection), validate/scaffold it, ensure a daemon, then print the
cockpit URL and open a browser. Every side-effecting collaborator is an
injectable ``UiDeps`` seam so the whole flow is testable with fakes.

This is the only surface that consults the user-level workspace registry
(spec §3.1); every other CLI command keeps its cwd/-C behavior.
"""

from __future__ import annotations

import sys
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from education_pipeline import registry
from education_pipeline.client import ensure_daemon
from education_pipeline.daemon import lifecycle
from education_pipeline.daemon.static import default_web_dist
from education_pipeline.errors import ERROR_CATALOG
from education_pipeline.workspace import fix_workspace, validate_workspace


def _default_is_interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def _default_open_browser(url: str) -> bool:
    return webbrowser.open(url)


@dataclass(frozen=True)
class UiDeps:
    """Injectable collaborators for :func:`run_ui`."""

    ensure_daemon: Callable = ensure_daemon
    read_discovery: Callable = lifecycle.read_discovery
    web_dist: Callable = default_web_dist
    open_browser: Callable = _default_open_browser
    is_interactive: Callable = _default_is_interactive
    prompt: Callable[[str], str] = input
    home: Callable[[], Path] = Path.home


def run_ui(
    workspace: str | None,
    *,
    no_browser: bool = False,
    deps: UiDeps | None = None,
) -> int:
    """Launch the cockpit; returns a process exit code."""

    deps = deps or UiDeps()

    root = _resolve_workspace(workspace, deps)
    if root is None:
        return 2  # workspace_unselected already reported

    findings = validate_workspace(root)
    if findings and all(f.auto_fixable for f in findings):
        findings = fix_workspace(root)
    if findings and any(f.severity == "blocking" for f in findings):
        _print_error("workspace_invalid")
        for finding in findings:
            print(
                f"  {finding.severity}\t{finding.code}\t{finding.message}\t"
                f"fix: {finding.remediation}",
                file=sys.stderr,
            )
        return 1

    if deps.web_dist() is None:
        _print_error("web_assets_missing")
        return 1

    registry.record_workspace(root)

    deps.ensure_daemon(root, autostart=True)
    record = deps.read_discovery(root) or {}
    port = record.get("port")
    if not isinstance(port, int):
        print("error: the daemon did not publish a usable port", file=sys.stderr)
        return 1
    url = f"http://127.0.0.1:{port}/"
    print(f"cockpit: {url}")
    if not no_browser:
        deps.open_browser(url)
    return 0


def _resolve_workspace(workspace: str | None, deps: UiDeps) -> Path | None:
    """Flag → registry last-used → first-run selection; None means reported failure."""

    if workspace is not None:
        return Path(workspace).expanduser().resolve(strict=False)

    last_used = registry.last_used_workspace()
    if last_used is not None:
        return last_used.resolve(strict=False)

    if not deps.is_interactive():
        _print_error("workspace_unselected")
        return None

    default = deps.home() / "EducationPipeline"
    print("No workspace is set up yet. Courses are stored locally in one folder.")
    answer = deps.prompt(f"Workspace directory [{default}]: ").strip()
    chosen = Path(answer).expanduser() if answer else default
    return chosen.resolve(strict=False)


def _print_error(code: str) -> None:
    entry = ERROR_CATALOG[code]
    print(f"error [{code}]: {entry.summary}", file=sys.stderr)
    print(f"fix: {entry.remediation}", file=sys.stderr)
