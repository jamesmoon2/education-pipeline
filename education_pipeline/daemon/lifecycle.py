"""Daemon discovery file: locate, authenticate, and claim the per-workspace daemon."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from education_pipeline.atomic_io import atomic_write_text

_DISCOVERY_DIR = ".education-pipeline"
_DISCOVERY_FILE = "daemon.json"


def discovery_dir(root: str | Path) -> Path:
    return Path(root) / _DISCOVERY_DIR


def discovery_path(root: str | Path) -> Path:
    return discovery_dir(root) / _DISCOVERY_FILE


def write_discovery(root: str | Path, *, pid: int, port: int, token: str, version: str) -> None:
    record = {
        "pid": pid,
        "port": port,
        "token": token,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "version": version,
    }
    # mode=0o600 lands on the temp file before the token is written to it, and
    # again on the replaced discovery file.
    atomic_write_text(
        discovery_path(root), json.dumps(record, indent=2), mode=0o600
    )


def read_discovery(root: str | Path) -> dict | None:
    # PermissionError: Windows raises it for a read that races the daemon's
    # os.replace of this file; treat it like "not ready yet", same as absent.
    try:
        return json.loads(discovery_path(root).read_text(encoding="utf-8"))
    except (FileNotFoundError, PermissionError, json.JSONDecodeError):
        return None


def remove_discovery(root: str | Path) -> None:
    try:
        discovery_path(root).unlink()
    except FileNotFoundError:
        pass


def is_pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":  # pragma: no cover - Windows CI
        import ctypes

        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def is_stale(record: dict) -> bool:
    if not isinstance(record, dict):
        return True
    pid = record.get("pid")
    return not isinstance(pid, int) or not is_pid_alive(pid)


def claim_discovery(root: str | Path) -> bool:
    """Try to become the workspace daemon via an exclusive create.

    Returns True if this caller now owns the discovery slot, False if a live
    daemon (or an in-flight claimant) already owns it. A confirmed-stale file
    (dead pid) is removed first so it can be reclaimed.
    """
    record = read_discovery(root)
    if record is not None and not is_stale(record):
        return False
    if record is not None:  # parseable but stale (dead pid) — safe to reclaim
        remove_discovery(root)
    path = discovery_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return False
    try:
        os.write(fd, json.dumps({"pid": os.getpid()}).encode("utf-8"))
    finally:
        os.close(fd)
    return True
