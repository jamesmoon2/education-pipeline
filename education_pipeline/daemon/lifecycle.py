"""Daemon discovery file: locate, authenticate, and claim the per-workspace daemon."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

_DISCOVERY_DIR = ".education-pipeline"
_DISCOVERY_FILE = "daemon.json"


def discovery_dir(root: str | Path) -> Path:
    return Path(root) / _DISCOVERY_DIR


def discovery_path(root: str | Path) -> Path:
    return discovery_dir(root) / _DISCOVERY_FILE


def write_discovery(root: str | Path, *, pid: int, port: int, token: str, version: str) -> None:
    target = discovery_path(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "pid": pid,
        "port": port,
        "token": token,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "version": version,
    }
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=".tmp-", suffix=".json")
    try:
        os.chmod(tmp, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(record, handle, indent=2)
        os.replace(tmp, target)
        os.chmod(target, 0o600)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def read_discovery(root: str | Path) -> dict | None:
    try:
        return json.loads(discovery_path(root).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
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
