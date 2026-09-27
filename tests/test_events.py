"""T62a red: the events hub and its stat-only workspace fingerprint.

Pins the public surface of ``education_pipeline/daemon/events.py`` as the
reviewed design note describes it
(``docs/superpowers/specs/2026-09-27-events-endpoint-design.md`` §1, §3, §4):

- ``workspace_fingerprint(root) -> dict[str, tuple]`` and
  ``diff_fingerprints(old, new)``, both pure. The diff yields notice dicts
  (``{"kind": "topics"}``, ``{"kind": "jobs"}``,
  ``{"kind": "run", "topic": t}``), once each, ordered topics, then jobs, then
  run by topic id.
- ``EventHub(root, *, max_streams, heartbeat_seconds, lifetime_seconds,
  liveness_seconds, scan_interval_seconds, clock=time.monotonic)`` with
  ``subscribe``, ``unsubscribe``, ``wait``, ``job_saved``, ``scan_once``,
  ``close``, ``hello_payload`` and the ``stream_count`` / ``scanning``
  properties. ``scan_interval_seconds=None`` starts no scanner.
- ``JobStore.on_saved``: the latency-only nudge.

CI runs this on Windows and macOS too, where ``st_ino`` can be 0 and mtimes
can repeat within a tick, so every change a test expects to be noticed
changes the entry's size or sets its mtime explicitly with ``os.utime``.
"""

from __future__ import annotations

import inspect
import io
import json
import logging
import os
import pathlib
import shutil
import threading
import time
from pathlib import Path

import pytest

from conftest import symlink_or_skip
from education_pipeline.atomic_io import atomic_write_bytes, atomic_write_text
from education_pipeline.daemon.jobs import Job, JobStore
from test_server import _raw_get, server_with_context  # noqa: F401 (fixture)

TOKEN = "secret-token"
TOPICS = {"kind": "topics"}
JOBS = {"kind": "jobs"}


def RUN(topic: str) -> dict:
    return {"kind": "run", "topic": topic}


def _events():
    """The module under test, imported per test so each test fails on its own."""

    from education_pipeline.daemon import events

    return events


def _fp(root: Path) -> dict:
    return _events().workspace_fingerprint(root)


def _diff(old: dict, new: dict) -> list[dict]:
    return list(_events().diff_fingerprints(old, new))


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _append(path: Path, text: str) -> None:
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(text)


def _set_mtime(path: Path, mtime_ns: int) -> None:
    st = os.stat(path, follow_symlinks=False)
    os.utime(path, ns=(st.st_atime_ns, mtime_ns))


def _replace_same_size_with_new_mtime(path: Path) -> None:
    """An atomic replace that keeps the size, with an explicitly moved mtime.

    Bytes in, bytes out: ``_write`` / ``_append`` write in text mode, so on
    Windows each line ends in CRLF on disk, and a text round-trip (``read_text``
    folds CRLF to LF, ``atomic_write_text`` writes LF verbatim) would shrink
    the file by a byte a line.
    """

    old = os.stat(path)
    atomic_write_bytes(path, path.read_bytes())
    assert os.stat(path).st_size == old.st_size
    _set_mtime(path, old.st_mtime_ns + 3_000_000_000)


def _workspace(root: Path) -> Path:
    """Two runs, a topic TOML, a profile and a plan -- plain files only."""

    for name in ("runs", "topics", "profiles", "config"):
        (root / name).mkdir(parents=True, exist_ok=True)
    _write(root / "runs" / "a" / "manifest.json", '{"topic_id": "a"}\n')
    _write(root / "runs" / "a" / "responses" / "draft.response.md", "draft a\n")
    _write(root / "runs" / "a" / "inputs" / "topic.toml", 'id = "a"\n')
    _write(root / "runs" / "b" / "manifest.json", '{"topic_id": "b"}\n')
    _write(root / "topics" / "a.toml", 'schema_version = 1\nid = "a"\n')
    _write(root / "profiles" / "p.toml", 'schema_version = 1\nid = "p"\n')
    _write(root / "config" / "model-plan.toml", 'provider = "manual"\n')
    return root


def _until(predicate, timeout: float = 3.0, interval: float = 0.01) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return bool(predicate())


def _next_notices(hub, sub, timeout: float = 3.0):
    """The first non-empty drain within ``timeout`` ([] if none, None if closed)."""

    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return []
        got = hub.wait(sub, min(remaining, 0.1))
        if got is None or got:
            return got


def _scanner_threads(exclude=()) -> list[threading.Thread]:
    return [
        thread
        for thread in threading.enumerate()
        if thread.name == "ep-events-scan" and thread not in exclude and thread.is_alive()
    ]


@pytest.fixture
def make_hub(tmp_path):
    """Builds hubs (no scanner unless asked) and closes every one in teardown."""

    made = []

    def make(root: Path | None = None, **kwargs):
        kwargs.setdefault("scan_interval_seconds", None)
        hub = _events().EventHub(tmp_path if root is None else root, **kwargs)
        made.append(hub)
        return hub

    yield make
    for hub in made:
        hub.close()


# ---------------------------------------------------------------------------
# Surface: constants, constructor, hello payload
# ---------------------------------------------------------------------------


def test_constants_and_constructor_hooks_match_the_note(tmp_path):
    events = _events()

    assert events.MAX_STREAMS == 4
    assert events.HEARTBEAT_SECONDS == 15
    assert events.LIFETIME_SECONDS == 300
    assert events.LIVENESS_SECONDS == 1.0
    assert events.SCAN_INTERVAL_SECONDS == 1.0

    params = inspect.signature(events.EventHub).parameters
    assert list(params)[0] == "root"
    defaults = {
        "max_streams": events.MAX_STREAMS,
        "heartbeat_seconds": events.HEARTBEAT_SECONDS,
        "lifetime_seconds": events.LIFETIME_SECONDS,
        "liveness_seconds": events.LIVENESS_SECONDS,
        "scan_interval_seconds": events.SCAN_INTERVAL_SECONDS,
        "clock": time.monotonic,
    }
    for name, default in defaults.items():
        assert params[name].kind is inspect.Parameter.KEYWORD_ONLY, name
        assert params[name].default == default, name
    assert params["clock"].default is time.monotonic


def test_hello_payload_carries_protocol_and_the_hub_timings(make_hub, tmp_path):
    default = make_hub(tmp_path)
    assert default.hello_payload() == {
        "heartbeat_seconds": 15,
        "lifetime_seconds": 300,
        "protocol": 1,
    }
    # The wire form (§1): sorted keys, compact separators, integers stay integers.
    assert (
        json.dumps(default.hello_payload(), sort_keys=True, separators=(",", ":"))
        == '{"heartbeat_seconds":15,"lifetime_seconds":300,"protocol":1}'
    )

    small = make_hub(tmp_path, heartbeat_seconds=0.05, lifetime_seconds=0.4)
    assert small.hello_payload() == {
        "heartbeat_seconds": 0.05,
        "lifetime_seconds": 0.4,
        "protocol": 1,
    }


# ---------------------------------------------------------------------------
# The fingerprint (§3) and its diff (§1)
# ---------------------------------------------------------------------------


def test_fingerprint_opens_no_files(tmp_path, monkeypatch):
    root = _workspace(tmp_path)
    store = JobStore(root)
    job = store.create("a", "draft", "manual", None, None)
    store.save(job)
    store.log_path("a", job.id).write_text("log line\n", encoding="utf-8")
    _write(root / "runs" / "a" / "inputs" / "profile.toml", 'id = "p"\n')
    events = _events()

    def _no_open(*args, **kwargs):
        raise AssertionError("the fingerprint must never open a file")

    with monkeypatch.context() as patch:
        patch.setattr("builtins.open", _no_open)
        patch.setattr(io, "open", _no_open)
        patch.setattr(os, "open", _no_open)
        patch.setattr(pathlib.Path, "open", _no_open)
        patch.setattr(pathlib.Path, "read_text", _no_open)
        patch.setattr(pathlib.Path, "read_bytes", _no_open)
        fingerprint = events.workspace_fingerprint(root)

    assert isinstance(fingerprint, dict)
    assert fingerprint  # it did stat something


def test_fingerprint_shape_matches_the_note(tmp_path):
    root = _workspace(tmp_path)
    store = JobStore(root)
    job = store.create("a", "draft", "manual", None, None)
    store.save(job)
    store.log_path("a", job.id).write_text("log line\n", encoding="utf-8")
    _write(root / "runs" / "a" / "inputs" / "profile.toml", 'id = "p"\n')

    fingerprint = _fp(root)

    for key in ("run:a", "run:b", "jobs:a", "attach:a", "topics", "topic:a"):
        assert key in fingerprint, key
    for key, value in fingerprint.items():
        assert isinstance(key, str)
        assert isinstance(value, tuple), key
        assert list(value) == sorted(value), key
        for entry in value:
            relpath, mtime_ns, size, ino = entry
            assert isinstance(relpath, str)
            assert not os.path.isabs(relpath)
            assert all(isinstance(n, int) for n in (mtime_ns, size, ino))
            # The 1 s log tail must never become a notice: output.log is never stat'ed.
            assert not relpath.endswith("output.log"), (key, relpath)
    # Pure: an unchanged workspace fingerprints the same and diffs to nothing.
    again = _fp(root)
    assert again == fingerprint
    snapshot = dict(fingerprint)
    assert _diff(fingerprint, again) == []
    assert fingerprint == snapshot


def test_atomic_replace_in_run_tree_notices_that_topic_only(tmp_path):
    root = _workspace(tmp_path)
    target = root / "runs" / "a" / "responses" / "draft.response.md"

    before = _fp(root)
    atomic_write_text(target, "a longer draft for a\n")
    assert _diff(before, _fp(root)) == [RUN("a")]

    before = _fp(root)
    atomic_write_text(root / "runs" / "a" / "responses" / "new.response.md", "new\n")
    assert _diff(before, _fp(root)) == [RUN("a")]

    before = _fp(root)
    _replace_same_size_with_new_mtime(target)
    assert _diff(before, _fp(root)) == [RUN("a")]


def test_in_place_edit_of_response_file_is_noticed(tmp_path):
    root = _workspace(tmp_path)
    target = root / "runs" / "a" / "responses" / "draft.response.md"
    parent = os.stat(target.parent)

    # Size-changing edit in place: the directory entry is untouched.
    before = _fp(root)
    with open(target, "r+b") as handle:
        handle.seek(0, os.SEEK_END)
        handle.write(b"and a human edit\n")
    _set_mtime(target.parent, parent.st_mtime_ns)
    assert _diff(before, _fp(root)) == [RUN("a")]

    # Same-size edit in place: only the (explicitly moved) mtime differs.
    old = os.stat(target)
    before = _fp(root)
    with open(target, "r+b") as handle:
        handle.write(b"D")
    _set_mtime(target, old.st_mtime_ns + 2_000_000_000)
    assert os.stat(target).st_size == old.st_size
    assert _diff(before, _fp(root)) == [RUN("a")]


def test_job_record_save_notices_jobs_and_its_run(tmp_path):
    root = _workspace(tmp_path)
    store = JobStore(root)

    before = _fp(root)
    job = store.create("a", "draft", "manual", None, None)
    store.save(job)
    after_create = _fp(root)
    assert _diff(before, after_create) == [JOBS, RUN("a")]

    job.status = "running"  # the record grows by one byte
    store.save(job)
    after_save = _fp(root)
    assert _diff(after_create, after_save) == [JOBS, RUN("a")]

    # A pruned or hand-deleted job directory is a jobs change too.
    shutil.rmtree(store.job_dir("a", job.id))
    assert _diff(after_save, _fp(root)) == [JOBS, RUN("a")]


def test_job_record_rewrite_within_one_dir_mtime_tick_is_noticed(tmp_path):
    root = _workspace(tmp_path)
    store = JobStore(root)
    job = store.create("a", "draft", "manual", None, None)
    store.save(job)
    job_dir = store.job_dir("a", job.id)
    dir_stat = os.stat(job_dir)

    before = _fp(root)
    job.status = "running"
    store.save(job)
    # Two saves inside one mtime tick leave the job directory's stat as it
    # was; only job.json itself (a new size here) tells them apart.
    _set_mtime(job_dir, dir_stat.st_mtime_ns)
    assert os.stat(job_dir).st_mtime_ns == dir_stat.st_mtime_ns

    assert _diff(before, _fp(root)) == [JOBS, RUN("a")]


def test_job_log_append_is_not_noticed(tmp_path):
    root = _workspace(tmp_path)
    store = JobStore(root)
    job = store.create("a", "draft", "manual", None, None)
    store.save(job)
    log = store.log_path("a", job.id)
    log.write_text("first line\n", encoding="utf-8")

    before = _fp(root)
    _append(log, "second line, and a much longer third one\n")
    _set_mtime(log, os.stat(log).st_mtime_ns + 5_000_000_000)
    assert _diff(before, _fp(root)) == []


def test_topics_profiles_and_plan_changes_notice_topics(tmp_path):
    root = _workspace(tmp_path)
    plan = root / "config" / "model-plan.toml"
    steps = [
        ("profile added", lambda: _write(root / "profiles" / "q.toml", 'id = "q"\n')),
        ("profile edited in place", lambda: _append(root / "profiles" / "q.toml", "# note\n")),
        ("profile removed", lambda: (root / "profiles" / "q.toml").unlink()),
        ("plan edited in place", lambda: _append(plan, "parallelism = 2\n")),
        ("plan replaced, same size", lambda: _replace_same_size_with_new_mtime(plan)),
        (
            "catalog added",
            lambda: _write(root / "config" / "model-catalog.toml", '[[providers]]\nid = "m"\n'),
        ),
        ("other child of topics/", lambda: _write(root / "topics" / "README.txt", "notes\n")),
    ]
    for label, act in steps:
        before = _fp(root)
        act()
        assert _diff(before, _fp(root)) == [TOPICS], label


def test_topic_toml_change_notices_topics_and_that_run(tmp_path):
    root = _workspace(tmp_path)
    topic_a = root / "topics" / "a.toml"
    steps = [
        ("edited in place", lambda: _append(topic_a, 'title = "A"\n'), [TOPICS, RUN("a")]),
        ("replaced, same size", lambda: _replace_same_size_with_new_mtime(topic_a), [TOPICS, RUN("a")]),
        ("added for a run", lambda: _write(root / "topics" / "b.toml", 'id = "b"\n'), [TOPICS, RUN("b")]),
        ("removed", lambda: (root / "topics" / "b.toml").unlink(), [TOPICS, RUN("b")]),
        (
            "added with no run yet",
            lambda: _write(root / "topics" / "fresh-topic.toml", 'id = "fresh-topic"\n'),
            [TOPICS, RUN("fresh-topic")],
        ),
        # The stem must pass is_artifact_id to name a run.
        ("hidden stem", lambda: _write(root / "topics" / ".hidden.toml", "x = 1\n"), [TOPICS]),
        ("bad stem", lambda: _write(root / "topics" / "bad name.toml", "x = 1\n"), [TOPICS]),
    ]
    for label, act, expected in steps:
        before = _fp(root)
        act()
        assert _diff(before, _fp(root)) == expected, label


def test_profile_snapshot_attach_notices_run_and_topics(tmp_path):
    root = _workspace(tmp_path)
    snapshot = root / "runs" / "a" / "inputs" / "profile.toml"

    before = _fp(root)
    atomic_write_text(snapshot, 'schema_version = 1\nid = "p"\n')
    assert _diff(before, _fp(root)) == [TOPICS, RUN("a")]

    before = _fp(root)
    _append(snapshot, 'target_learner = "cohort"\n')
    assert _diff(before, _fp(root)) == [TOPICS, RUN("a")]

    before = _fp(root)
    snapshot.unlink()
    assert _diff(before, _fp(root)) == [TOPICS, RUN("a")]


def test_run_directory_created_or_removed_notices_run(tmp_path):
    root = _workspace(tmp_path)

    before = _fp(root)
    (root / "runs" / "c").mkdir()
    assert _diff(before, _fp(root)) == [RUN("c")]

    before = _fp(root)
    _write(root / "runs" / "c" / "manifest.json", '{"topic_id": "c"}\n')
    assert _diff(before, _fp(root)) == [RUN("c")]

    before = _fp(root)
    shutil.rmtree(root / "runs" / "c")
    assert _diff(before, _fp(root)) == [RUN("c")]

    # Archive is a manifest flag flip: an ordinary run change.
    before = _fp(root)
    atomic_write_text(root / "runs" / "b" / "manifest.json", '{"topic_id": "b", "archived": true}\n')
    assert _diff(before, _fp(root)) == [RUN("b")]


def test_non_artifact_names_under_runs_are_ignored(tmp_path):
    root = _workspace(tmp_path)

    before = _fp(root)
    _write(root / "runs" / ".staging" / "manifest.json", "{}\n")
    _write(root / "runs" / "bad name" / "manifest.json", "{}\n")
    _write(root / "runs" / "-dash" / "manifest.json", "{}\n")
    _write(root / "runs" / "notes.txt", "a file, not a run directory\n")
    after = _fp(root)

    assert _diff(before, after) == []
    for key in after:
        for bad in (".staging", "bad name", "-dash", "notes.txt"):
            assert bad not in key, key


def test_symlinks_are_recorded_not_followed(tmp_path):
    root = _workspace(tmp_path / "ws")
    outside = tmp_path / "outside"
    _write(outside / "secret.md", "outside the workspace\n")
    symlink_or_skip(root / "runs" / "a" / "linked", outside, target_is_directory=True)

    before = _fp(root)
    _append(outside / "secret.md", "a change behind the link\n")
    _write(outside / "more.md", "and a new file there\n")
    assert _diff(before, _fp(root)) == []

    before = _fp(root)
    os.unlink(root / "runs" / "a" / "linked")
    assert _diff(before, _fp(root)) == [RUN("a")]


def test_notice_order_topics_jobs_then_runs(tmp_path, make_hub):
    root = _workspace(tmp_path)
    store = JobStore(root)

    # One diff that spans every kind comes out in the canonical order.
    before = _fp(root)
    _write(root / "runs" / "b" / "z.md", "z\n")
    _write(root / "runs" / "a" / "z.md", "z\n")
    job = store.create("b", "draft", "manual", None, None)
    store.save(job)
    _write(root / "profiles" / "r.toml", 'id = "r"\n')
    assert _diff(before, _fp(root)) == [TOPICS, JOBS, RUN("a"), RUN("b")]

    # A drain orders the same way, whatever order the notices were published in.
    hub = make_hub(root)
    sub = hub.subscribe()
    hub.job_saved("b")  # jobs, run b
    _write(root / "runs" / "a" / "late.md", "late\n")
    hub.scan_once()  # run a
    _write(root / "profiles" / "q.toml", 'id = "q"\n')
    hub.scan_once()  # topics
    assert hub.wait(sub, 0) == [TOPICS, JOBS, RUN("a"), RUN("b")]


class _ListingCopyEntry:
    """A ``DirEntry`` whose ``stat()`` is the directory listing's copy, as on Windows.

    There ``os.scandir`` fills each entry's lstat from FindFirstFileW /
    FindNextFileW data -- the copy of the metadata kept in the *parent's*
    index, which NTFS updates lazily -- with ``st_ino`` 0. This copy lags: the
    first read of a path predates its last write (mtime 2 s earlier, a file's
    size 0) and later reads are current. Everything else is the real entry's.
    """

    def __init__(self, entry: os.DirEntry, seen: set[str]) -> None:
        self._entry = entry
        self._seen = seen

    def __getattr__(self, name):
        return getattr(self._entry, name)

    def __fspath__(self):
        return os.fspath(self._entry)

    def stat(self, *, follow_symlinks: bool = True) -> os.stat_result:
        st = self._entry.stat(follow_symlinks=follow_symlinks)
        if follow_symlinks and self._entry.is_symlink():
            return st  # the one case where Windows does make a system call
        fields = {name: getattr(st, name) for name in dir(st) if name.startswith("st_")}
        fields["st_ino"] = 0
        if self._entry.path not in self._seen:
            self._seen.add(self._entry.path)
            fields["st_mtime_ns"] = st.st_mtime_ns - 2_000_000_000
            fields["st_mtime"] = fields["st_mtime_ns"] / 1e9
            if not self._entry.is_dir(follow_symlinks=False):
                fields["st_size"] = 0
        # The tuple view: mode, ino, dev, nlink, uid, gid, size, then whole-second
        # atime, mtime, ctime; the dict fills the named-only fields.
        head = [fields[name] for name in ("st_mode", "st_ino", "st_dev", "st_nlink")]
        head += [fields[name] for name in ("st_uid", "st_gid", "st_size")]
        head += [st[7], int(fields["st_mtime"]), st[9]]
        return os.stat_result(head, fields)


def test_fingerprint_does_not_trust_the_listings_stat_copy(tmp_path, monkeypatch):
    """Windows CI: untouched runs came up as changes between two scans.

    ``DirEntry.stat()`` there is the parent listing's lazily updated copy
    (``_ListingCopyEntry``), so the fingerprint must stat each entry itself.
    """

    root = _workspace(tmp_path)
    _write(root / "runs" / "a" / "inputs" / "profile.toml", 'id = "p"\n')
    _write(root / "runs" / "g" / "draft" / "module-1.prompt.md", "module one\n")
    store = JobStore(root)
    job = store.create("a", "draft", "manual", None, None)
    store.save(job)
    store.log_path("a", job.id).write_text("log line\n", encoding="utf-8")

    events = _events()
    real_scandir = os.scandir
    seen: set[str] = set()

    class _Listing(list):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

        def close(self):
            return None

    def listing_copy_scandir(path="."):
        if not os.path.abspath(os.fspath(path)).startswith(os.path.abspath(root)):
            return real_scandir(path)
        with real_scandir(path) as entries:
            return _Listing(_ListingCopyEntry(entry, seen) for entry in entries)

    monkeypatch.setattr(events.os, "scandir", listing_copy_scandir)

    # Nothing changed on disk, so nothing is noticed.
    before = _fp(root)
    after = _fp(root)
    assert _diff(before, after) == []

    # Control: real changes still come through, and only those.
    before = after
    job.status = "running"  # the record grows by one byte
    store.save(job)
    manifest_b = root / "runs" / "b" / "manifest.json"
    _set_mtime(manifest_b, os.stat(manifest_b).st_mtime_ns + 3_000_000_000)
    _append(root / "runs" / "g" / "draft" / "module-1.prompt.md", "and a longer line\n")
    assert _diff(before, _fp(root)) == [JOBS, RUN("a"), RUN("b"), RUN("g")]


# ---------------------------------------------------------------------------
# The hub (§4)
# ---------------------------------------------------------------------------


def test_pending_notices_coalesce_per_subscriber(tmp_path, make_hub):
    root = _workspace(tmp_path)
    hub = make_hub(root)
    first = hub.subscribe()
    second = hub.subscribe()

    for _ in range(5):
        hub.job_saved("a")
    _write(root / "runs" / "a" / "x.md", "1\n")
    hub.scan_once()
    _write(root / "runs" / "a" / "x.md", "22\n")
    hub.scan_once()

    assert hub.wait(first, 0) == [JOBS, RUN("a")]
    assert hub.wait(first, 0) == []
    # Each subscriber holds its own pending set.
    assert hub.wait(second, 0) == [JOBS, RUN("a")]
    assert hub.wait(second, 0) == []
    # A late subscriber is not handed notices from before it arrived.
    late = hub.subscribe()
    assert hub.wait(late, 0) == []


def test_wait_times_out_empty_and_wakes_on_publish(tmp_path, make_hub):
    root = _workspace(tmp_path)
    hub = make_hub(root)
    sub = hub.subscribe()

    assert hub.wait(sub, 0.05) == []

    result = {}
    waiter = threading.Thread(
        target=lambda: result.setdefault("got", hub.wait(sub, 10)), daemon=True
    )
    waiter.start()
    time.sleep(0.05)
    hub.job_saved("a")
    waiter.join(2.0)
    assert not waiter.is_alive(), "a publish must wake a waiting subscriber"
    assert result["got"] == [JOBS, RUN("a")]


def test_subscribe_past_cap_returns_none(tmp_path, make_hub):
    root = _workspace(tmp_path)
    hub = make_hub(root)  # the default cap, MAX_STREAMS

    subs = [hub.subscribe() for _ in range(4)]
    assert all(sub is not None for sub in subs)
    assert hub.stream_count == 4
    assert hub.subscribe() is None
    assert hub.stream_count == 4

    hub.unsubscribe(subs[0])
    assert hub.stream_count == 3
    assert hub.subscribe() is not None
    assert hub.stream_count == 4

    single = make_hub(root, max_streams=1)
    only = single.subscribe()
    assert only is not None
    assert single.subscribe() is None
    single.unsubscribe(only)
    assert single.stream_count == 0
    assert single.subscribe() is not None


def test_scanner_runs_only_while_subscribed(tmp_path, make_hub, monkeypatch):
    events = _events()
    root = _workspace(tmp_path)
    calls: list[str] = []
    real = events.workspace_fingerprint

    def counting(path):
        calls.append(threading.current_thread().name)
        return real(path)

    monkeypatch.setattr(events, "workspace_fingerprint", counting)
    preexisting = set(threading.enumerate())
    hub = make_hub(root, scan_interval_seconds=0.02)

    # No subscriber: no thread, no pass.
    constructed = len(calls)
    time.sleep(0.1)
    assert len(calls) == constructed
    assert hub.scanning is False
    assert _scanner_threads(exclude=preexisting) == []

    sub = hub.subscribe()
    assert hub.scanning is True
    _write(root / "runs" / "a" / "scanned.md", "seen by the scanner\n")
    assert _next_notices(hub, sub) == [RUN("a")]
    assert "ep-events-scan" in calls

    # 1 -> 0: the scanner stops, and no pass runs while nobody listens.
    hub.unsubscribe(sub)
    assert _until(lambda: hub.scanning is False)
    time.sleep(0.05)  # let a pass already in flight finish
    settled = len(calls)
    time.sleep(0.15)
    assert len(calls) == settled

    # A change while nobody listens is part of the next baseline, not a notice.
    _write(root / "runs" / "b" / "offline.md", "made while unsubscribed\n")
    sub = hub.subscribe()
    assert hub.scanning is True
    _write(root / "runs" / "a" / "after.md", "made after resubscribing\n")
    assert _next_notices(hub, sub) == [RUN("a")]
    assert _next_notices(hub, sub, timeout=0.15) == []

    # A quick 1 -> 0 -> 1 settles on exactly one scanner thread.
    hub.unsubscribe(sub)
    assert _until(lambda: hub.scanning is False)
    sub = hub.subscribe()
    hub.unsubscribe(sub)
    sub = hub.subscribe()
    assert _until(lambda: len(_scanner_threads(exclude=preexisting)) == 1)
    time.sleep(0.1)
    assert len(_scanner_threads(exclude=preexisting)) == 1
    _write(root / "runs" / "b" / "again.md", "after the quick cycle\n")
    assert _next_notices(hub, sub) == [RUN("b")]


def test_job_saved_publishes_now(tmp_path, make_hub, monkeypatch):
    root = _workspace(tmp_path)
    hub = make_hub(root)
    sub = hub.subscribe()

    def _no_fs(*args, **kwargs):
        raise AssertionError("job_saved must not touch the filesystem")

    # Immediately, under the hub's own lock, with no stat and no scan pass.
    with monkeypatch.context() as patch:
        for name in ("stat", "lstat", "scandir", "listdir"):
            patch.setattr(os, name, _no_fs)
        hub.job_saved("a")
    assert hub.wait(sub, 0) == [JOBS, RUN("a")]

    # The nudge is latency only: the scan still reports the save it announced.
    store = JobStore(root)
    job = store.create("a", "draft", "manual", None, None)
    store.save(job)
    hub.job_saved("a")
    assert hub.wait(sub, 0) == [JOBS, RUN("a")]
    hub.scan_once()
    assert hub.wait(sub, 0) == [JOBS, RUN("a")]


def test_job_saved_does_not_wait_for_a_scan_pass(tmp_path, make_hub, monkeypatch):
    events = _events()
    root = _workspace(tmp_path)
    hub = make_hub(root)
    sub = hub.subscribe()

    entered = threading.Event()
    release = threading.Event()
    real = events.workspace_fingerprint

    def slow(path):
        entered.set()
        release.wait(5)
        return real(path)

    monkeypatch.setattr(events, "workspace_fingerprint", slow)
    scan = threading.Thread(target=hub.scan_once, daemon=True)
    scan.start()
    try:
        assert entered.wait(2), "scan_once must fingerprint the workspace"
        done = threading.Event()
        nudger = threading.Thread(
            target=lambda: (hub.job_saved("a"), done.set()), daemon=True
        )
        nudger.start()
        # Worker threads call job_saved under their own locks: it must never
        # queue behind a scan pass.
        assert done.wait(1.0), "job_saved blocked behind a running scan pass"
        assert hub.wait(sub, 0) == [JOBS, RUN("a")]
    finally:
        release.set()
        scan.join(5)


def test_job_saved_on_closed_hub_or_bad_id_is_a_no_op(tmp_path, make_hub):
    root = _workspace(tmp_path)

    idle = make_hub(root)
    idle.job_saved("a")  # no subscriber: nothing to do, and no error

    hub = make_hub(root)
    sub = hub.subscribe()
    for bad in ("", ".hidden", "a/b", "a\\b", "../a", "a\nb", "a b", "a:b", None, 42):
        hub.job_saved(bad)
    assert hub.wait(sub, 0) == []

    hub.close()
    hub.job_saved("a")  # worker.stop() can still save after events.close()
    assert hub.wait(sub, 0) is None


def test_job_store_save_calls_on_saved_and_survives_a_failing_hook(tmp_path, capsys, caplog):
    caplog.set_level(logging.DEBUG)
    store = JobStore(tmp_path)
    assert store.on_saved is None

    seen = []

    def hook(job):
        # Called after the replace: the record on disk is already the new one.
        seen.append((job.id, store.load(job.topic_id, job.id).status))

    store.on_saved = hook
    job = store.create("a", "draft", "manual", None, None)
    job.status = "running"
    store.save(job)
    assert seen == [(job.id, "running")]

    def broken(job):
        raise RuntimeError("hook-secret-detail")

    store.on_saved = broken
    job.status = "succeeded"
    store.save(job)  # a hook can never fail a save
    assert store.load("a", job.id).status == "succeeded"

    logged = capsys.readouterr().err + caplog.text
    assert "RuntimeError" in logged
    assert "hook-secret-detail" not in logged


def test_close_wakes_waiters_and_refuses_new_subscribers(tmp_path, make_hub):
    root = _workspace(tmp_path)
    hub = make_hub(root, scan_interval_seconds=30)
    before = set(threading.enumerate())
    sub = hub.subscribe()
    scanners = _scanner_threads(exclude=before)
    assert len(scanners) == 1

    result = {}
    waiter = threading.Thread(
        target=lambda: result.setdefault("got", hub.wait(sub, 30)), daemon=True
    )
    waiter.start()
    time.sleep(0.05)

    hub.close()
    waiter.join(2.0)
    assert not waiter.is_alive(), "close() must wake every waiting stream"
    assert result["got"] is None
    # The scanner sleeps on something close() signals, not in time.sleep.
    scanners[0].join(2.0)
    assert not scanners[0].is_alive()
    assert hub.scanning is False

    assert hub.subscribe() is None
    assert hub.wait(sub, 0) is None
    hub.unsubscribe(sub)
    hub.close()  # idempotent


def test_polled_reads_produce_no_notices(server_with_context, make_hub):  # noqa: F811
    """Risk 5's loop guard: no polled GET may write into a watched tree."""

    port, context = server_with_context
    root = context.root
    job = context.store.create("t", "draft", "fake", "m", None)
    context.store.save(job)
    context.store.log_path("t", job.id).write_text("line\n", encoding="utf-8")

    paths = [
        "/v1/topics",
        "/v1/profiles",
        "/v1/jobs",
        f"/v1/jobs/{job.id}",
        f"/v1/jobs/{job.id}/log?offset=0",
    ]
    for topic in ("t", "g"):
        paths += [
            f"/v1/runs/{topic}",
            f"/v1/jobs?topic={topic}",
            f"/v1/runs/{topic}/personalization",
            f"/v1/runs/{topic}/repair/modules",
        ]
        paths += [
            f"/v1/runs/{topic}/stages/{stage}"
            for stage in ("spec", "outline", "draft", "qa", "factcheck", "repair")
        ]

    hub = make_hub(root)
    sub = hub.subscribe()
    for _ in range(2):
        for path in paths:
            status, _body, _headers = _raw_get(port, path, token=TOKEN)
            assert status < 500, path
    hub.scan_once()
    assert hub.wait(sub, 0) == []

    # Control: the same pass does see a real write.
    _write(root / "runs" / "g" / "control.txt", "a real change\n")
    hub.scan_once()
    assert hub.wait(sub, 0) == [RUN("g")]


def test_scan_error_does_not_kill_the_scanner(tmp_path, make_hub, monkeypatch):
    events = _events()
    root = _workspace(tmp_path)
    real = events.workspace_fingerprint
    state = {"calls": 0}

    def flaky(path):
        state["calls"] += 1
        if state["calls"] == 2:  # the first scanner pass after the baseline
            raise RuntimeError("scan blew up")
        return real(path)

    monkeypatch.setattr(events, "workspace_fingerprint", flaky)
    hub = make_hub(root, scan_interval_seconds=0.02)
    sub = hub.subscribe()

    assert _until(lambda: state["calls"] >= 3), "the scanner died on a failing pass"
    assert hub.scanning is True
    _write(root / "runs" / "a" / "after-error.md", "still watched\n")
    assert _next_notices(hub, sub) == [RUN("a")]


def test_job_record_type_is_what_on_saved_receives(tmp_path):
    """The hook gets the saved ``Job`` itself (serve() reads ``job.topic_id``)."""

    store = JobStore(tmp_path)
    received = []
    store.on_saved = received.append
    job = store.create("a", "draft", "manual", None, None)
    store.save(job)
    assert len(received) == 1
    assert isinstance(received[0], Job)
    assert received[0].topic_id == "a"
    assert received[0].id == job.id
