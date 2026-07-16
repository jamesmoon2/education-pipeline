"""Reveal-in-files: resolve an enum target inside the workspace and open it.

This is the first daemon surface that spawns an OS process on request (spec
§5.5), so it is deliberately narrow:

- the target is an **enum of known locations** (``run``/``export``/``topic``)
  -- user input never becomes a free path and never reaches the command line
  beyond the daemon-resolved, workspace-confined filesystem path;
- the resolved path is ``realpath``-checked to be inside the workspace, so a
  symlinked run dir or topic file pointing elsewhere is rejected;
- opener failure or an unsupported platform raises :class:`RevealError`, and
  the API returns ``reveal_unsupported`` with the resolved path so the UI can
  fall back to showing a copyable path.

``EP_REVEAL_OPENER`` overrides the opener executable (invoked as
``$EP_REVEAL_OPENER <path>``); it exists for tests and headless setups.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Mapping

from education_pipeline.config import ConfigError
from education_pipeline.daemon.read_api import NotFoundError, require_run
from education_pipeline.runs import RunStore
from education_pipeline.workspace import TopicStore

REVEAL_TARGETS = ("run", "export", "topic")

_OPENER_TIMEOUT_SECONDS = 15


class RevealError(Exception):
    """The platform opener failed or is unavailable."""


def resolve_reveal_target(
    runs: RunStore, topics: TopicStore, target: str, topic_id: str
) -> Path:
    """Map an enum target to its real path, confined to the workspace."""

    if target not in REVEAL_TARGETS:
        allowed = ", ".join(REVEAL_TARGETS)
        raise ConfigError(f"reveal target must be one of: {allowed}")
    if target == "run":
        require_run(runs, topic_id)  # also validates the artifact id
        path = runs.run_dir(topic_id)
    elif target == "export":
        path = runs.export_path(topic_id, "html")
        if not path.is_file():
            raise NotFoundError(f"no html export produced for topic {topic_id!r}")
    else:
        path = topics.topic_path(topic_id)
        if not path.is_file():
            raise NotFoundError(f"no such topic: {topic_id}")

    root = Path(runs.root).resolve()
    resolved = path.resolve()
    if resolved != root and root not in resolved.parents:
        raise ConfigError("reveal target resolves outside the workspace")
    return resolved


def opener_argv(
    path: Path,
    *,
    platform: str | None = None,
    env: Mapping[str, str] | None = None,
) -> list[str]:
    """The argv for the platform file manager; RevealError when unsupported."""

    env = os.environ if env is None else env
    override = env.get("EP_REVEAL_OPENER")
    if override:
        return [override, str(path)]
    platform = platform or sys.platform
    if platform == "darwin":
        return ["open", "-R", str(path)] if path.is_file() else ["open", str(path)]
    if platform.startswith("linux"):
        # xdg-open cannot select a file; open its containing directory.
        directory = path.parent if path.is_file() else path
        return ["xdg-open", str(directory)]
    if platform in ("win32", "cygwin"):
        if path.is_file():
            return ["explorer", f"/select,{path}"]
        return ["explorer", str(path)]
    raise RevealError(f"no file-manager opener known for platform {platform!r}")


def open_in_file_manager(path: Path) -> None:
    """Spawn the platform opener for ``path``; RevealError on any failure."""

    argv = opener_argv(path)
    try:
        completed = subprocess.run(
            argv,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=_OPENER_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RevealError(f"file-manager opener failed: {type(exc).__name__}") from exc
    if completed.returncode != 0:
        raise RevealError(
            f"file-manager opener exited with status {completed.returncode}"
        )
