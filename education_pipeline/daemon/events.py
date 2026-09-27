"""Change notices for ``GET /v1/events``: a stat-only workspace scan and its hub.

The stream tells the cockpit *that* something changed, never *what*
(design note ``docs/superpowers/specs/2026-09-27-events-endpoint-design.md``).
A notice is one of ``{"kind": "topics"}``, ``{"kind": "jobs"}`` or
``{"kind": "run", "topic": t}``; every notice is idempotent, so pending
notices coalesce per subscriber without losing anything.

Locks. ``_lock`` (with its two conditions) is a **leaf**: ``job_saved`` runs
inside ``JobStore.save``, which already runs under ``Worker._lock``, the
workspace lock and ``DaemonContext._chain_lock``, so nothing done under
``_lock`` touches a socket or the filesystem, calls out, or takes another
lock. ``_scan_lock`` is taken only by ``subscribe`` and scan passes (never on
a worker path), always before ``_lock``.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Callable

from education_pipeline.workspace import is_artifact_id

logger = logging.getLogger(__name__)

PROTOCOL = 1
#: Browsers allow 6 HTTP/1.1 connections per host; 4 streams leave 2.
MAX_STREAMS = 4
#: A keepalive comment follows this many seconds with no other write.
HEARTBEAT_SECONDS = 15
#: A stream ends (and the client resyncs) after this long.
LIFETIME_SECONDS = 300
#: The longest single wait before the handler checks whether its peer left.
LIVENESS_SECONDS = 1.0
#: The shortest gap between scan passes (stretched to 10x a slow pass).
SCAN_INTERVAL_SECONDS = 1.0

KEEPALIVE = b": keepalive\n\n"
TOPICS = "topics"
JOBS = "jobs"

#: The workspace directories whose direct children feed the ``topics`` notice.
_TOPIC_DIRS = ("topics", "profiles", "config")


def encode_frame(event: str, payload: dict) -> bytes:
    """One SSE frame; ``ensure_ascii`` keeps the JSON on a single line."""

    data = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return f"event: {event}\ndata: {data}\n\n".encode("utf-8")


# ---------------------------------------------------------------------------
# The fingerprint: directory listings and stats only, never file contents
# ---------------------------------------------------------------------------


def _listing(path: str) -> list[os.DirEntry]:
    try:
        with os.scandir(path) as entries:
            return list(entries)
    except OSError:  # vanished (or unreadable) mid-scan: its absence is the change
        return []


def _record(rel: str, entry: os.DirEntry) -> tuple | None:
    try:
        st = entry.stat(follow_symlinks=False)
    except OSError:
        return None
    return (rel, st.st_mtime_ns, st.st_size, st.st_ino)


def _record_path(rel: str, path: str) -> tuple | None:
    try:
        st = os.stat(path, follow_symlinks=False)
    except OSError:
        return None
    return (rel, st.st_mtime_ns, st.st_size, st.st_ino)


def _is_real_dir(entry: os.DirEntry) -> bool:
    try:
        return entry.is_dir(follow_symlinks=False)
    except OSError:
        return False


def _is_link(entry: os.DirEntry) -> bool:
    try:
        return entry.is_symlink()
    except OSError:
        return False


def _run_keys(fingerprint: dict, topic: str, entry: os.DirEntry) -> None:
    """``run:``, ``jobs:`` and ``attach:`` for one ``runs/<topic>`` entry."""

    top = f"runs/{topic}"
    own = _record(top, entry)
    if own is None:
        return
    run_entries = [own]
    if _is_real_dir(entry):  # a symlinked run is recorded, never followed
        stack = [(entry.path, top)]
        while stack:
            path, rel_dir = stack.pop()
            for child in _listing(path):
                rel = f"{rel_dir}/{child.name}"
                is_dir = _is_real_dir(child)
                if rel_dir == top and child.name == "jobs" and is_dir:
                    _jobs_key(fingerprint, topic, rel, child)
                    continue
                record = _record(rel, child)
                if record is None:
                    continue
                run_entries.append(record)
                if rel == f"{top}/inputs/profile.toml":
                    fingerprint[f"attach:{topic}"] = (record,)
                if is_dir:
                    stack.append((child.path, rel))
    fingerprint[f"run:{topic}"] = tuple(sorted(run_entries))


def _jobs_key(fingerprint: dict, topic: str, rel: str, entry: os.DirEntry) -> None:
    """Each job directory plus its ``job.json``; ``output.log`` is never stat'ed."""

    own = _record(rel, entry)
    if own is None:
        return
    entries = [own]
    for job in _listing(entry.path):
        record = _record(f"{rel}/{job.name}", job)
        if record is None:
            continue
        entries.append(record)
        if _is_real_dir(job):
            job_json = _record_path(
                f"{rel}/{job.name}/job.json", os.path.join(job.path, "job.json")
            )
            if job_json is not None:
                entries.append(job_json)
    fingerprint[f"jobs:{topic}"] = tuple(sorted(entries))


def workspace_fingerprint(root: str | Path) -> dict[str, tuple]:
    """Stat every watched entry under ``root``; pure, and opens no file.

    Keys are ``run:<t>``, ``jobs:<t>``, ``attach:<t>``, ``topics`` and
    ``topic:<t>``; each value is a sorted tuple of
    ``(relpath, st_mtime_ns, st_size, st_ino)``.
    """

    base = os.fspath(root)
    fingerprint: dict[str, tuple] = {}
    topic_entries = []
    for name in _TOPIC_DIRS:
        path = os.path.join(base, name)
        own = _record_path(name, path)
        if own is None:
            continue
        topic_entries.append(own)
        for child in _listing(path):
            record = _record(f"{name}/{child.name}", child)
            if record is None:
                continue
            stem = child.name[: -len(".toml")] if child.name.endswith(".toml") else ""
            if name == "topics" and is_artifact_id(stem):
                fingerprint[f"topic:{stem}"] = (record,)
            else:
                topic_entries.append(record)
    fingerprint[TOPICS] = tuple(sorted(topic_entries))
    for entry in _listing(os.path.join(base, "runs")):
        if not is_artifact_id(entry.name):
            continue
        if _is_real_dir(entry) or _is_link(entry):
            _run_keys(fingerprint, entry.name, entry)
    return fingerprint


def diff_fingerprints(old: dict, new: dict) -> list[dict]:
    """The notices for every key that changed, appeared or vanished.

    Ordered ``topics``, then ``jobs``, then ``run`` by topic id, once each.
    A job change also names its run, and a profile attach or a topic TOML
    change names both ``topics`` and the run (design note §1).
    """

    kinds: set[str] = set()
    runs: set[str] = set()
    for key in old.keys() | new.keys():
        if old.get(key) == new.get(key):
            continue
        kind, _, topic = key.partition(":")
        if kind == TOPICS:
            kinds.add(TOPICS)
        elif kind == "run":
            runs.add(topic)
        elif kind == "jobs":
            kinds.add(JOBS)
            runs.add(topic)
        elif kind in ("attach", "topic"):
            kinds.add(TOPICS)
            runs.add(topic)
    notices = [{"kind": kind} for kind in (TOPICS, JOBS) if kind in kinds]
    notices.extend({"kind": "run", "topic": topic} for topic in sorted(runs))
    return notices


# ---------------------------------------------------------------------------
# The hub
# ---------------------------------------------------------------------------


def _pending_key(notice: dict) -> str:
    return f"run:{notice['topic']}" if notice["kind"] == "run" else notice["kind"]


def _drain_order(key: str) -> tuple[int, str]:
    if key == TOPICS:
        return (0, "")
    if key == JOBS:
        return (1, "")
    return (2, key[len("run:"):])


class _Subscriber:
    """One open stream: its coalescing set of pending notices."""

    __slots__ = ("pending",)

    def __init__(self) -> None:
        self.pending: dict[str, dict] = {}


class EventHub:
    """Daemon-wide change notices, scanned only while a stream is open."""

    def __init__(
        self,
        root: str | Path,
        *,
        max_streams: int = MAX_STREAMS,
        heartbeat_seconds: float = HEARTBEAT_SECONDS,
        lifetime_seconds: float = LIFETIME_SECONDS,
        liveness_seconds: float = LIVENESS_SECONDS,
        scan_interval_seconds: float | None = SCAN_INTERVAL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.root = Path(root)
        self.max_streams = max_streams
        self.heartbeat_seconds = heartbeat_seconds
        self.lifetime_seconds = lifetime_seconds
        self.liveness_seconds = liveness_seconds
        self.scan_interval_seconds = scan_interval_seconds
        self.clock = clock
        self._lock = threading.Lock()  # leaf: see the module docstring
        self._changed = threading.Condition(self._lock)
        self._scan_wake = threading.Condition(self._lock)
        self._scan_lock = threading.Lock()  # always taken before _lock
        self._subscribers: set[_Subscriber] = set()
        self._closed = False
        self._scan_gen = 0
        self._scanner: threading.Thread | None = None
        self._fingerprint: dict | None = None  # guarded by _scan_lock

    # -- read-only state ------------------------------------------------------

    @property
    def stream_count(self) -> int:
        with self._lock:
            return len(self._subscribers)

    @property
    def scanning(self) -> bool:
        with self._lock:
            scanner = self._scanner
        return scanner is not None and scanner.is_alive()

    def hello_payload(self) -> dict:
        return {
            "heartbeat_seconds": self.heartbeat_seconds,
            "lifetime_seconds": self.lifetime_seconds,
            "protocol": PROTOCOL,
        }

    # -- subscribers ----------------------------------------------------------

    def subscribe(self) -> _Subscriber | None:
        """A new stream slot, or ``None`` at the cap or once closed.

        On 0 -> 1 the baseline fingerprint is taken here, before ``hello``,
        and a fresh scanner generation starts.
        """

        with self._scan_lock:
            baseline = None
            while True:
                with self._lock:
                    if self._closed or len(self._subscribers) >= self.max_streams:
                        return None
                    # Only subscribe() adds, and it holds _scan_lock: a set
                    # seen empty stays empty while the baseline is taken.
                    if self._subscribers or baseline is not None:
                        first = not self._subscribers
                        sub = _Subscriber()
                        self._subscribers.add(sub)
                        if first:
                            self._fingerprint = baseline
                            self._scan_gen += 1
                        gen = self._scan_gen
                        break
                baseline = workspace_fingerprint(self.root)
            if first and self.scan_interval_seconds is not None:
                self._start_scanner(gen)
            return sub

    def unsubscribe(self, sub: _Subscriber | None) -> None:
        with self._lock:
            if sub in self._subscribers:
                self._subscribers.discard(sub)
                if not self._subscribers:
                    self._scan_wake.notify_all()  # 1 -> 0: the scanner exits now

    def wait(self, sub: _Subscriber, timeout: float) -> list[dict] | None:
        """Drain ``sub``'s pending notices, waiting at most ``timeout`` once.

        ``[]`` on timeout, ``None`` once the hub is closed.
        """

        with self._lock:
            if not self._closed and not sub.pending and timeout > 0:
                self._changed.wait(timeout)
            if self._closed:
                return None
            pending, sub.pending = sub.pending, {}
        return [pending[key] for key in sorted(pending, key=_drain_order)]

    # -- publishing -----------------------------------------------------------

    def _publish_locked(self, notices: list[dict]) -> None:
        if self._closed or not notices:
            return
        for sub in self._subscribers:
            for notice in notices:
                sub.pending.setdefault(_pending_key(notice), notice)
        self._changed.notify_all()

    def job_saved(self, topic_id: object) -> None:
        """The ``JobStore.save`` nudge: ``jobs`` and ``run{t}`` now, no stat.

        Latency only -- the scan sees every save too. A no-op on a closed hub
        and for an id that is not an artifact id.
        """

        if not is_artifact_id(topic_id):
            return
        notices = [{"kind": JOBS}, {"kind": "run", "topic": topic_id}]
        with self._lock:
            self._publish_locked(notices)

    def close(self) -> None:
        """Release every stream and stop the scanner; later subscribes fail."""

        with self._lock:
            self._closed = True
            self._scan_gen += 1
            self._changed.notify_all()
            self._scan_wake.notify_all()

    # -- scanning -------------------------------------------------------------

    def scan_once(self) -> None:
        """One pass: fingerprint, diff against the last one, publish."""

        with self._scan_lock:
            self._pass_locked()

    def _pass_locked(self) -> None:
        new = workspace_fingerprint(self.root)
        old, self._fingerprint = self._fingerprint, new
        if old is None:
            return
        notices = diff_fingerprints(old, new)
        if notices:
            with self._lock:
                self._publish_locked(notices)

    def _live_locked(self, gen: int) -> bool:
        return not self._closed and gen == self._scan_gen and bool(self._subscribers)

    def _start_scanner(self, gen: int) -> None:
        thread = threading.Thread(
            target=self._scan_loop, args=(gen,), name="ep-events-scan", daemon=True
        )
        with self._lock:
            if gen != self._scan_gen:
                return
            self._scanner = thread
        thread.start()

    def _scan_loop(self, gen: int) -> None:
        delay = self.scan_interval_seconds
        while True:
            with self._lock:
                if not self._live_locked(gen):
                    return
                self._scan_wake.wait(delay)
            started = time.monotonic()
            with self._scan_lock:
                # Re-checked under _scan_lock: a stale generation that got
                # past the check above must not run one more pass.
                with self._lock:
                    if not self._live_locked(gen):
                        return
                try:
                    self._pass_locked()
                except Exception as exc:  # noqa: BLE001 - keep scanning
                    logger.warning("events scan pass failed: %s", type(exc).__name__)
            delay = max(self.scan_interval_seconds, 10 * (time.monotonic() - started))


def pump(
    hub: EventHub,
    sub: _Subscriber,
    write: Callable[[bytes], object],
    peer_gone: Callable[[], bool],
) -> None:
    """Write ``sub``'s notices until lifetime, hub close or a departed peer.

    Waits happen on the hub's condition, never on the socket; after each
    wait (at most ``liveness_seconds``) ``peer_gone`` checks the socket.
    """

    now = hub.clock()
    deadline = now + hub.lifetime_seconds
    beat = now + hub.heartbeat_seconds
    while now < deadline:
        timeout = min(deadline, beat, now + hub.liveness_seconds) - now
        notices = hub.wait(sub, max(0.0, timeout))
        if notices is None:
            return
        now = hub.clock()
        if notices:
            write(b"".join(encode_frame("change", notice) for notice in notices))
            beat = now + hub.heartbeat_seconds
        elif now >= beat:
            write(KEEPALIVE)
            beat = now + hub.heartbeat_seconds
        if peer_gone():
            return
