"""Workspace-level advisory file lock shared by every local process.

The engine's in-process locks (``RunStore._manifest_write_lock``) only
serialize threads that share one store object. Nothing stopped a CLI
invocation from interleaving its own manifest read-modify-write with the
daemon's, because the two live in different processes. This module adds the
missing outer guard: one advisory lock file per workspace, taken around
every manifest mutation, so whichever process gets there first completes its
cycle before the other starts.

Design notes:

- **Non-blocking + poll.** The lock is taken with ``LOCK_EX | LOCK_NB``
  (``LK_NBLCK`` on Windows) in a short sleep loop until ``timeout_seconds``,
  never with a blocking ``flock``: a blocked ``flock`` cannot be bounded by
  a timeout, and callers need a refusal they can report rather than a hang.
- **Reentrant per process.** ``flock`` on a *second* descriptor for the same
  file blocks the same process just like any other, so nested critical
  sections (approve -> write prompt) would deadlock. One descriptor per
  workspace path is therefore shared process-wide, guarded by a depth
  counter: the real file lock is taken when the depth goes 0 -> 1 and
  released when it returns to 0. Intra-process correctness stays the job of
  the per-topic thread locks.
- **Platform check at call time.** ``sys.platform`` is read inside
  :func:`workspace_lock`, and the platform module is kept as the
  module-level attribute ``msvcrt`` (``None`` off Windows), so the Windows
  branch stays exercisable on POSIX CI.

Critical sections must stay short: never hold this across a provider job.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from education_pipeline.config import ConfigError
from education_pipeline.errors import ERROR_CATALOG

if sys.platform == "win32":  # pragma: no cover - selected by platform
    import msvcrt

    fcntl = None
else:
    import fcntl

    msvcrt = None


#: Directory (under the workspace root) holding local-only coordination files.
WORKSPACE_STATE_DIRNAME = ".education-pipeline"

#: Name of the advisory lock file inside that directory.
LOCK_FILENAME = "workspace.lock"

#: How long to wait between non-blocking attempts.
_POLL_SECONDS = 0.02


class WorkspaceLockedError(ConfigError):
    """Another process held the workspace lock for longer than the timeout."""

    code = "workspace_locked"

    def __init__(self, path: Path, timeout_seconds: float) -> None:
        entry = ERROR_CATALOG["workspace_locked"]
        super().__init__(
            f"{entry.summary} "
            f"(waited {timeout_seconds:g}s for {path}). {entry.remediation}"
        )
        self.path = path
        self.timeout_seconds = timeout_seconds


@dataclass
class _Holder:
    """The one descriptor this process holds for a given lock file."""

    fd: int
    depth: int


# Guards ``_HELD`` *and* serializes actual acquisition: two threads racing to
# take the file lock on two descriptors would contend with each other instead
# of sharing one, so only one thread at a time runs the poll loop.
_STATE_LOCK = threading.Lock()
_HELD: dict[str, _Holder] = {}


def lock_path(workspace_root: str | Path) -> Path:
    """The advisory lock file for this workspace."""

    return Path(workspace_root) / WORKSPACE_STATE_DIRNAME / LOCK_FILENAME


@contextmanager
def workspace_lock(
    workspace_root: str | Path, *, timeout_seconds: float = 5.0
) -> Iterator[Path]:
    """Hold the workspace's advisory lock for the duration of the block.

    Raises :class:`WorkspaceLockedError` (``code == "workspace_locked"``)
    when another process still holds it after ``timeout_seconds``.
    """

    path = lock_path(workspace_root)
    key = os.path.realpath(path)
    _acquire(key, path, timeout_seconds)
    try:
        yield path
    finally:
        _release(key)


def _acquire(key: str, path: Path, timeout_seconds: float) -> None:
    with _STATE_LOCK:
        holder = _HELD.get(key)
        if holder is not None:
            holder.depth += 1
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            deadline = time.monotonic() + max(timeout_seconds, 0.0)
            while True:
                if _try_lock(fd):
                    _HELD[key] = _Holder(fd=fd, depth=1)
                    return
                if time.monotonic() >= deadline:
                    raise WorkspaceLockedError(path, timeout_seconds)
                time.sleep(_POLL_SECONDS)
        except BaseException:
            os.close(fd)
            raise


def _release(key: str) -> None:
    with _STATE_LOCK:
        holder = _HELD[key]
        holder.depth -= 1
        if holder.depth > 0:
            return
        del _HELD[key]
        try:
            _unlock(holder.fd)
        finally:
            os.close(holder.fd)


def _try_lock(fd: int) -> bool:
    """One non-blocking exclusive-lock attempt. ``False`` means contended."""

    try:
        if sys.platform == "win32":
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def _unlock(fd: int) -> None:
    if sys.platform == "win32":
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:
        fcntl.flock(fd, fcntl.LOCK_UN)
