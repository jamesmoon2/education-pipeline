"""A workspace-file queue of courses for ``education-pipeline queue ...``.

Decision 7 of the Phase 3 plan: *queue file, not queue stage*. Nothing in the
engine or the extraction manifest knows about this file. It is a convenience
for the CLI -- a list of topics to drive to their next judgment point, one
after another -- and it lives beside the runs it names:

``<workspace>/queue/courses.json``::

    {"version": 1, "entries": [
        {"topic_id": ..., "added_at": ..., "updated_at": ...,
         "status": "queued" | "running" | "stopped", "stop": {...} | null}
    ]}

Every function here is pure: ``load_queue`` / ``save_queue`` touch the disk,
the rest take a :class:`CourseQueue` and hand back a new one. The caller owns
the clock (``now``) and the save points, so ``queue run`` can rewrite the file
after every single transition and an interrupted run is visible on disk as a
``running`` entry rather than being lost.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path

from .atomic_io import atomic_write_text
from .config import ConfigError

__all__ = [
    "QUEUE_FILENAME",
    "QUEUE_STATUSES",
    "QUEUE_VERSION",
    "CourseQueue",
    "QueueEntry",
    "add_entry",
    "load_queue",
    "mark_running",
    "mark_stopped",
    "pending_entries",
    "queue_path",
    "remove_entry",
    "save_queue",
]


#: On-disk schema version. A file claiming any other version is refused
#: rather than guessed at: the queue is user-visible state.
QUEUE_VERSION = 1

QUEUE_DIRNAME = "queue"
QUEUE_FILENAME = "courses.json"

#: ``queued`` was added and not started, ``running`` was started (and, if the
#: process died, never finished -- ``queue run`` picks it up again),
#: ``stopped`` reached a judgment point and carries the stop payload.
QUEUE_STATUSES = ("queued", "running", "stopped")


@dataclass(frozen=True)
class QueueEntry:
    """One queued course."""

    topic_id: str
    added_at: str
    updated_at: str
    status: str
    stop: dict | None = None


@dataclass(frozen=True)
class CourseQueue:
    """The whole queue, in file order."""

    entries: tuple[QueueEntry, ...] = ()


# ---------------------------------------------------------------------------
# Paths and I/O
# ---------------------------------------------------------------------------


def queue_path(root: str | Path) -> Path:
    """Where the queue file lives under ``root`` (the workspace)."""

    return Path(root) / QUEUE_DIRNAME / QUEUE_FILENAME


def load_queue(root: str | Path) -> CourseQueue:
    """Read the queue, or an empty one when no file has been written yet."""

    path = queue_path(root)
    if not path.is_file():
        return CourseQueue(entries=())
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ConfigError(f"queue file {path} is not readable JSON: {exc}") from exc
    return _parse_queue(raw, path)


def save_queue(root: str | Path, queue: CourseQueue) -> Path:
    """Write ``queue`` to disk as one all-or-nothing replacement.

    Returns the path written. The same queue always produces the same bytes
    (sorted keys, two-space indent, trailing newline), so a no-op save leaves
    the file untouched byte for byte and a diff of the file is a diff of the
    queue.
    """

    path = queue_path(root)
    atomic_write_text(path, _dumps(queue))
    return path


def _dumps(queue: CourseQueue) -> str:
    payload = {
        "version": QUEUE_VERSION,
        "entries": [_entry_payload(entry) for entry in queue.entries],
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def _entry_payload(entry: QueueEntry) -> dict:
    return {
        "topic_id": entry.topic_id,
        "added_at": entry.added_at,
        "updated_at": entry.updated_at,
        "status": entry.status,
        "stop": entry.stop,
    }


def _parse_queue(raw: object, path: Path) -> CourseQueue:
    if not isinstance(raw, dict):
        raise ConfigError(f"queue file {path} must hold a JSON object")
    version = raw.get("version")
    if version != QUEUE_VERSION:
        raise ConfigError(
            f"queue file {path} has version {version!r}; "
            f"this build reads version {QUEUE_VERSION}"
        )
    entries_raw = raw.get("entries", [])
    if not isinstance(entries_raw, list):
        raise ConfigError(f"queue file {path} field 'entries' must be a list")
    return CourseQueue(
        entries=tuple(_parse_entry(item, path) for item in entries_raw)
    )


def _parse_entry(raw: object, path: Path) -> QueueEntry:
    if not isinstance(raw, dict):
        raise ConfigError(f"queue file {path} entry must be a JSON object")
    topic_id = raw.get("topic_id")
    if not isinstance(topic_id, str) or not topic_id:
        raise ConfigError(f"queue file {path} entry is missing 'topic_id'")
    status = raw.get("status")
    if status not in QUEUE_STATUSES:
        raise ConfigError(
            f"queue file {path} entry {topic_id!r} has unknown status "
            f"{status!r}; known statuses: {', '.join(QUEUE_STATUSES)}"
        )
    stop = raw.get("stop")
    if stop is not None and not isinstance(stop, dict):
        raise ConfigError(
            f"queue file {path} entry {topic_id!r} field 'stop' must be an "
            "object or null"
        )
    added_at = raw.get("added_at")
    updated_at = raw.get("updated_at")
    if not isinstance(added_at, str) or not isinstance(updated_at, str):
        raise ConfigError(
            f"queue file {path} entry {topic_id!r} needs string 'added_at' "
            "and 'updated_at'"
        )
    return QueueEntry(
        topic_id=topic_id,
        added_at=added_at,
        updated_at=updated_at,
        status=status,
        stop=stop,
    )


# ---------------------------------------------------------------------------
# Pure transitions
# ---------------------------------------------------------------------------


def _index_of(queue: CourseQueue, topic_id: str) -> int | None:
    for index, entry in enumerate(queue.entries):
        if entry.topic_id == topic_id:
            return index
    return None


def _require_index(queue: CourseQueue, topic_id: str) -> int:
    index = _index_of(queue, topic_id)
    if index is None:
        raise ConfigError(f"{topic_id!r} is not in the course queue")
    return index


def _with_entry(queue: CourseQueue, index: int, entry: QueueEntry) -> CourseQueue:
    entries = list(queue.entries)
    entries[index] = entry
    return CourseQueue(entries=tuple(entries))


def add_entry(queue: CourseQueue, topic_id: str, *, now: str) -> CourseQueue:
    """Queue ``topic_id``, or re-queue it where it already stands.

    Re-adding a course that has already run keeps its position and its
    ``added_at`` -- the queue is a work list, and re-queueing is "run this one
    again", not "put it at the back".
    """

    index = _index_of(queue, topic_id)
    if index is None:
        entry = QueueEntry(
            topic_id=topic_id,
            added_at=now,
            updated_at=now,
            status="queued",
            stop=None,
        )
        return CourseQueue(entries=queue.entries + (entry,))
    existing = queue.entries[index]
    return _with_entry(
        queue,
        index,
        replace(existing, updated_at=now, status="queued", stop=None),
    )


def remove_entry(queue: CourseQueue, topic_id: str) -> CourseQueue:
    """Drop ``topic_id`` from the queue; unknown topics are an error."""

    index = _require_index(queue, topic_id)
    entries = list(queue.entries)
    del entries[index]
    return CourseQueue(entries=tuple(entries))


def mark_running(queue: CourseQueue, topic_id: str, *, now: str) -> CourseQueue:
    """Record that ``topic_id`` is being driven right now."""

    index = _require_index(queue, topic_id)
    return _with_entry(
        queue, index, replace(queue.entries[index], status="running", updated_at=now)
    )


def mark_stopped(
    queue: CourseQueue, topic_id: str, stop: dict, *, now: str
) -> CourseQueue:
    """Record where ``topic_id`` stopped (an ``orchestrate.stop_payload``)."""

    index = _require_index(queue, topic_id)
    return _with_entry(
        queue,
        index,
        replace(queue.entries[index], status="stopped", stop=stop, updated_at=now),
    )


def pending_entries(queue: CourseQueue) -> tuple[QueueEntry, ...]:
    """Entries ``queue run`` should drive, in file order.

    ``running`` counts as pending: an entry left in that state is one an
    earlier ``queue run`` was interrupted in the middle of, and the loop it
    drives is safe to re-enter from whatever step the run is now on.
    """

    return tuple(entry for entry in queue.entries if entry.status != "stopped")
