"""One shared atomic file replacement for every writer in the package.

Six call sites had grown their own copy of the same five steps -- ``mkstemp``
beside the target, write, ``os.replace``, ``chmod``, unlink-on-exception -- and
the copies had drifted. Only three of them retried the Windows sharing
violation (:class:`PermissionError` from ``os.replace`` onto a file a
concurrent reader holds open), so the run manifest was safe but the workspace
registry, learner profiles, and the model plan were not. This module owns the
single implementation they now share, which means all six retry.

The module deliberately imports nothing from the package: ``runs`` imports
``workspace``, ``daemon`` imports both, and ``registry`` imports neither, so a
helper living in any of them would close a cycle or invert a dependency for at
least one caller. Same leaf-module pattern as ``text_scalars``.

Text is always encoded as UTF-8 and written in binary mode, so a ``\\n`` in the
payload reaches disk as ``\\n`` on every platform. Artifacts here are sha-keyed
and byte-compared (see ``_write_text``'s ``newline=""`` in ``runs`` and
``workspace``), so Windows text-mode ``\\n`` -> ``\\r\\n`` translation must
never rewrite them.
"""

from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, TypeVar

#: How many ``os.replace`` attempts a transient sharing violation gets.
REPLACE_ATTEMPTS = 10

#: How long to wait between those attempts.
REPLACE_RETRY_SECONDS = 0.05

#: Temp-file prefix used unless a caller asks for another one.
DEFAULT_TMP_PREFIX = ".tmp-"

_T = TypeVar("_T")


def atomic_write_bytes(
    path: str | os.PathLike[str],
    data: bytes,
    *,
    mode: int | None = None,
    fsync: bool = False,
    tmp_prefix: str = DEFAULT_TMP_PREFIX,
    tmp_suffix: str | None = None,
    retry_on_permission_error: bool = True,
) -> None:
    """Write ``data`` to ``path`` as one all-or-nothing replacement.

    Missing parent directories are created. The temp file is created by
    ``mkstemp`` in the target's own directory -- same filesystem, so the
    ``os.replace`` is atomic -- and is removed again if anything raises before
    the replace lands.

    ``mode`` is applied to the temp file *before* any content is written and
    to the target again after the replace: the payload may be a secret, and
    ``mkstemp``'s file is already linked into a directory the caller does not
    necessarily control.

    ``tmp_suffix`` defaults to the target's own suffix. ``fsync`` forces the
    content to durable storage before the replace.

    ``retry_on_permission_error`` (the default) polls ``os.replace`` through a
    transient Windows sharing violation and re-raises the last
    :class:`PermissionError` once the attempts are exhausted.
    """

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    suffix = target.suffix if tmp_suffix is None else tmp_suffix
    descriptor, temporary_name = tempfile.mkstemp(
        dir=target.parent, prefix=tmp_prefix, suffix=suffix
    )
    try:
        if mode is not None:
            os.chmod(temporary_name, mode)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            if fsync:
                handle.flush()
                os.fsync(handle.fileno())
        _replace(temporary_name, target, retry=retry_on_permission_error)
        if mode is not None:
            os.chmod(target, mode)
    except BaseException:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)
        raise


def atomic_write_text(
    path: str | os.PathLike[str], text: str, **options: Any
) -> None:
    """UTF-8 encode ``text`` and hand it to :func:`atomic_write_bytes`.

    No newline translation: the bytes on disk are exactly ``text``'s bytes.
    Keyword options are forwarded unchanged.
    """

    atomic_write_bytes(path, text.encode("utf-8"), **options)


def read_bytes_retrying(
    path: str | os.PathLike[str], *, retry: bool = True
) -> bytes:
    """Read ``path`` whole, polling through a transient sharing violation.

    The mirror image of the retry :func:`atomic_write_bytes` already does. On
    Windows, *opening* a file another thread is replacing via ``os.replace``
    fails with :class:`PermissionError` just as the replace itself does
    against an open reader, so a reader that hashes a run artifact while a
    writer swaps it needs the same brief poll -- same attempt count, same
    backoff, same opt-out flag. Every other :class:`OSError` (a missing file
    above all) propagates on the first attempt.
    """

    target = Path(path)
    return _retrying_on_permission_error(target.read_bytes, retry=retry)


def _replace(source: str, target: Path, *, retry: bool) -> None:
    # Windows sharing semantics: replacing a file another process or thread
    # holds open for reading fails with PermissionError. Readers here are
    # transient (manifest polls, API reads, discovery-file polls), so retry
    # briefly instead of surfacing the failure.
    _retrying_on_permission_error(
        lambda: os.replace(source, target), retry=retry
    )


def _retrying_on_permission_error(
    operation: Callable[[], _T], *, retry: bool
) -> _T:
    """Run ``operation``, polling it through transient sharing violations.

    One retry policy shared by both sides of the race, so the read side can
    never drift from the write side's attempt count or backoff.
    """

    if not retry:
        return operation()
    for attempt in range(REPLACE_ATTEMPTS):
        try:
            return operation()
        except PermissionError:
            if attempt == REPLACE_ATTEMPTS - 1:
                raise
            time.sleep(REPLACE_RETRY_SECONDS)
    raise AssertionError("unreachable: the loop returns or raises")  # pragma: no cover


__all__ = [
    "DEFAULT_TMP_PREFIX",
    "REPLACE_ATTEMPTS",
    "REPLACE_RETRY_SECONDS",
    "atomic_write_bytes",
    "atomic_write_text",
    "read_bytes_retrying",
]
