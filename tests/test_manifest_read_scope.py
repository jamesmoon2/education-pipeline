"""Pins the request-scoped manifest read cache.

``RunStore.read_manifest`` re-reads and re-parses the whole run manifest on
every call, and a single ``run_status_payload`` makes ~47 of them for one
topic (``content_contract`` alone accounts for most, via ``stage_paths``).
The fix is a *request-scoped* cache, not a persistent one: while a read scope
is open on the current thread, each manifest file is read from disk at most
once; when the scope exits, nothing is retained.

These tests pin the three properties that make that safe:

1. inside a scope repeated reads hit disk once, and after the scope exits
   every read hits disk again (nothing persists between requests);
2. a manifest *write* performed inside an open scope drops the cached copy,
   so a read-modify-write never observes a stale manifest;
3. the scope is per-thread -- one thread's cached manifests are never served
   to another thread.
"""

import json
import threading
from pathlib import Path

import test_runs

from education_pipeline.runs import RunStore, _manifest_scope_entries


def _count_manifest_disk_reads(monkeypatch) -> list[int]:
    """Count reads of ``manifest.json`` files, returning a live counter."""

    calls = [0]
    original = Path.read_text

    def counted(self, *args, **kwargs):
        if self.name == "manifest.json":
            calls[0] += 1
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", counted)
    return calls


# ---------------------------------------------------------------------------
# 1. Scoped, and only scoped.
# ---------------------------------------------------------------------------


def test_repeated_reads_inside_one_scope_hit_disk_once(tmp_path, monkeypatch):
    runs = test_runs._create_guide_run(tmp_path)
    topic_id = "systems-thinking"
    calls = _count_manifest_disk_reads(monkeypatch)

    with runs.manifest_read_scope():
        first = runs.read_manifest(topic_id)
        runs.read_manifest(topic_id)
        runs.read_manifest(topic_id)

    assert calls[0] == 1
    assert first["topic_id"] == topic_id


def test_no_scope_is_active_after_the_context_exits(tmp_path, monkeypatch):
    runs = test_runs._create_guide_run(tmp_path)
    topic_id = "systems-thinking"

    with runs.manifest_read_scope():
        assert _manifest_scope_entries() is not None
    assert _manifest_scope_entries() is None

    calls = _count_manifest_disk_reads(monkeypatch)
    runs.read_manifest(topic_id)
    runs.read_manifest(topic_id)
    assert calls[0] == 2


def test_a_later_scope_does_not_reuse_an_earlier_scopes_manifest(
    tmp_path, monkeypatch
):
    """Nothing survives between requests: an on-disk change made after one
    scope closed is visible to the next scope."""

    runs = test_runs._create_guide_run(tmp_path)
    topic_id = "systems-thinking"

    with runs.manifest_read_scope():
        runs.read_manifest(topic_id)

    path = runs.manifest_path(topic_id)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["marker"] = "changed-between-requests"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    with runs.manifest_read_scope():
        assert runs.read_manifest(topic_id)["marker"] == "changed-between-requests"


def test_nested_scopes_are_no_ops_and_do_not_end_the_outer_scope(
    tmp_path, monkeypatch
):
    runs = test_runs._create_guide_run(tmp_path)
    topic_id = "systems-thinking"
    calls = _count_manifest_disk_reads(monkeypatch)

    with runs.manifest_read_scope():
        runs.read_manifest(topic_id)
        with runs.manifest_read_scope():
            runs.read_manifest(topic_id)
        # The inner exit must not discard the outer scope's entries.
        assert _manifest_scope_entries() is not None
        runs.read_manifest(topic_id)

    assert calls[0] == 1
    assert _manifest_scope_entries() is None


# ---------------------------------------------------------------------------
# 2. A write inside a scope drops the cached copy.
# ---------------------------------------------------------------------------


def test_a_manifest_write_inside_a_scope_invalidates_the_cached_copy(tmp_path):
    """Read-modify-write inside one scope must never see a stale manifest."""

    runs = test_runs._create_guide_run(tmp_path)
    topic_id = "systems-thinking"

    with runs.manifest_read_scope():
        event_count = len(runs.read_manifest(topic_id).get("events", []))

        runs.append_manifest_event(topic_id, {"stage": "spec", "action": "noted"})

        after = runs.read_manifest(topic_id)
        assert len(after.get("events", [])) == event_count + 1
        assert after["events"][-1]["action"] == "noted"

        runs.record_stage_provenance(
            topic_id,
            "spec",
            provider="manual",
            model=None,
            effort=None,
            source="cli",
        )
        assert runs.read_manifest(topic_id).get("stage_provenance")


def test_approving_a_stage_inside_a_scope_is_visible_to_the_next_read(tmp_path):
    runs = test_runs._create_guide_run(tmp_path)
    topic_id = "systems-thinking"
    prompt = runs.write_topic_spec_prompt(topic_id)
    prompt.response_path.write_text(
        test_runs._guide_spec_response(), encoding="utf-8"
    )

    with runs.manifest_read_scope():
        before = len(runs.read_manifest(topic_id).get("events", []))
        runs.approve_stage(topic_id, "spec")
        actions = [
            event.get("action")
            for event in runs.read_manifest(topic_id).get("events", [])
        ]

    assert len(actions) > before
    assert "response_approved" in actions


# ---------------------------------------------------------------------------
# 3. Per-thread isolation.
# ---------------------------------------------------------------------------


def test_scopes_are_per_thread(tmp_path):
    """One thread's open scope must never serve another thread's reads, and
    must not be ended by the other thread's scope closing."""

    runs = test_runs._create_guide_run(tmp_path)
    topic_id = "systems-thinking"
    path = runs.manifest_path(topic_id)

    worker_cached = threading.Event()
    disk_changed = threading.Event()
    seen: dict[str, object] = {}

    def worker() -> None:
        with runs.manifest_read_scope():
            seen["worker_first"] = runs.read_manifest(topic_id).get("marker")
            worker_cached.set()
            disk_changed.wait(timeout=10)
            # Still inside the same scope: the worker keeps its own cached
            # copy, untouched by the main thread's scope and write.
            seen["worker_second"] = runs.read_manifest(topic_id).get("marker")
        seen["worker_after_scope"] = runs.read_manifest(topic_id).get("marker")

    thread = threading.Thread(target=worker)
    thread.start()
    assert worker_cached.wait(timeout=10)

    # The main thread has no scope of its own while the worker holds one.
    assert _manifest_scope_entries() is None

    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["marker"] = "main-thread"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    with runs.manifest_read_scope():
        seen["main"] = runs.read_manifest(topic_id).get("marker")
    disk_changed.set()

    thread.join(timeout=10)
    assert not thread.is_alive()

    assert seen["worker_first"] is None
    assert seen["main"] == "main-thread"
    # The worker's scope was neither shared with nor closed by the main thread.
    assert seen["worker_second"] is None
    assert seen["worker_after_scope"] == "main-thread"


def test_two_threads_hold_independent_scope_maps(tmp_path):
    runs = RunStore(tmp_path)
    maps: dict[str, object] = {}
    entered = threading.Barrier(2, timeout=10)

    def capture(label: str) -> None:
        with runs.manifest_read_scope():
            entered.wait()
            maps[label] = _manifest_scope_entries()

    threads = [
        threading.Thread(target=capture, args=("a",)),
        threading.Thread(target=capture, args=("b",)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert maps["a"] is not None
    assert maps["b"] is not None
    assert maps["a"] is not maps["b"]
