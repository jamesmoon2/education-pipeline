"""User-level registry of known workspaces.

Consulted only by ``education-pipeline ui`` (spec §3.1): every other CLI
command keeps its ``-C/--workspace`` = cwd behavior. One stdlib path
convention on every platform: ``$XDG_CONFIG_HOME/education-pipeline/
workspaces.json``, defaulting to ``~/.config/education-pipeline/
workspaces.json``.

A corrupt or unreadable registry is treated as empty with a printed warning
-- never a crash -- so the worst possible failure is re-selecting a
workspace once.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

_REGISTRY_DIR = "education-pipeline"
_REGISTRY_FILE = "workspaces.json"


@dataclass(frozen=True)
class WorkspaceRegistry:
    """Known workspace paths and the most recently used one."""

    workspaces: tuple[str, ...] = ()
    last_used: str | None = None


def registry_path() -> Path:
    """Return the registry file path, honoring ``$XDG_CONFIG_HOME``."""

    base = os.environ.get("XDG_CONFIG_HOME")
    config_home = Path(base) if base else Path.home() / ".config"
    return config_home / _REGISTRY_DIR / _REGISTRY_FILE


def load_registry() -> WorkspaceRegistry:
    """Read the registry, treating a corrupt or unreadable file as empty."""

    path = registry_path()
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return WorkspaceRegistry()
    except OSError as exc:
        _warn(f"unreadable workspace registry {path}: {exc}")
        return WorkspaceRegistry()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        _warn(f"corrupt workspace registry {path}; treating it as empty")
        return WorkspaceRegistry()
    parsed = _parse_registry(data)
    if parsed is None:
        _warn(f"malformed workspace registry {path}; treating it as empty")
        return WorkspaceRegistry()
    return parsed


def record_workspace(workspace: str | Path) -> WorkspaceRegistry:
    """Add a workspace (absolute path) and set it as ``last_used``."""

    absolute = str(Path(workspace).expanduser().resolve(strict=False))
    registry = load_registry()
    workspaces = registry.workspaces
    if absolute not in workspaces:
        workspaces = workspaces + (absolute,)
    updated = WorkspaceRegistry(workspaces=workspaces, last_used=absolute)
    _save_registry(updated)
    return updated


def last_used_workspace() -> Path | None:
    """Return the most recently used workspace path, if any is recorded."""

    last_used = load_registry().last_used
    return Path(last_used) if last_used else None


def _parse_registry(data: object) -> WorkspaceRegistry | None:
    if not isinstance(data, dict):
        return None
    raw_workspaces = data.get("workspaces", [])
    if not isinstance(raw_workspaces, list) or not all(
        isinstance(item, str) for item in raw_workspaces
    ):
        return None
    last_used = data.get("last_used")
    if last_used is not None and not isinstance(last_used, str):
        return None
    return WorkspaceRegistry(workspaces=tuple(raw_workspaces), last_used=last_used)


def _save_registry(registry: WorkspaceRegistry) -> None:
    path = registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "workspaces": list(registry.workspaces),
        "last_used": registry.last_used,
    }
    content = json.dumps(payload, indent=2) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.replace(temporary_path, path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def _warn(message: str) -> None:
    print(f"warning: {message}", file=sys.stderr)
