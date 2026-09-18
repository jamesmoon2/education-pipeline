"""Tests for ``education_pipeline.course_queue`` (T31, decision 7).

Pure, stdlib, workspace-file-backed queue of courses for ``education-pipeline
queue ...``. See ``docs/superpowers/plans/2026-09-18-phase-3-headless.md``
(T31 row, decision 7) for the on-disk contract this module keeps:
``<workspace>/queue/courses.json`` = ``{"version": 1, "entries": [...]}``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from education_pipeline.config import ConfigError
from education_pipeline.course_queue import (
    QUEUE_STATUSES,
    QUEUE_VERSION,
    CourseQueue,
    QueueEntry,
    add_entry,
    load_queue,
    mark_running,
    mark_stopped,
    pending_entries,
    queue_path,
    remove_entry,
    save_queue,
)

NOW_1 = "2026-09-18T10:00:00Z"
NOW_2 = "2026-09-18T10:05:00Z"
NOW_3 = "2026-09-18T10:10:00Z"


# ---------------------------------------------------------------------------
# queue_path / load_queue
# ---------------------------------------------------------------------------


def test_queue_path_is_under_workspace_queue_dir(tmp_path: Path) -> None:
    assert queue_path(tmp_path) == tmp_path / "queue" / "courses.json"


def test_load_queue_missing_file_returns_empty_queue(tmp_path: Path) -> None:
    assert load_queue(tmp_path) == CourseQueue(entries=())


def test_load_queue_malformed_json_raises_config_error(tmp_path: Path) -> None:
    path = queue_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_queue(tmp_path)


def test_load_queue_wrong_version_raises_config_error(tmp_path: Path) -> None:
    path = queue_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"version": 2, "entries": []}), encoding="utf-8")
    with pytest.raises(ConfigError):
        load_queue(tmp_path)


def test_load_queue_unknown_status_raises_config_error(tmp_path: Path) -> None:
    path = queue_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "version": QUEUE_VERSION,
                "entries": [
                    {
                        "topic_id": "abc",
                        "added_at": NOW_1,
                        "updated_at": NOW_1,
                        "status": "bogus",
                        "stop": None,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError):
        load_queue(tmp_path)


def test_queue_statuses_are_queued_running_stopped() -> None:
    assert QUEUE_STATUSES == ("queued", "running", "stopped")


# ---------------------------------------------------------------------------
# add_entry / remove_entry
# ---------------------------------------------------------------------------


def test_add_entry_appends_queued_with_no_stop() -> None:
    queue = add_entry(CourseQueue(entries=()), "abc", now=NOW_1)
    assert queue.entries == (
        QueueEntry(
            topic_id="abc",
            added_at=NOW_1,
            updated_at=NOW_1,
            status="queued",
            stop=None,
        ),
    )


def test_add_entry_existing_topic_resets_in_place_keeping_position_and_added_at() -> None:
    queue = add_entry(CourseQueue(entries=()), "abc", now=NOW_1)
    queue = add_entry(queue, "xyz", now=NOW_1)
    queue = mark_stopped(queue, "abc", {"kind": "approve", "stage": "draft"}, now=NOW_2)

    queue = add_entry(queue, "abc", now=NOW_3)

    assert [e.topic_id for e in queue.entries] == ["abc", "xyz"]
    abc = queue.entries[0]
    assert abc.status == "queued"
    assert abc.added_at == NOW_1
    assert abc.updated_at == NOW_3
    assert abc.stop is None


def test_remove_entry_drops_the_matching_topic() -> None:
    queue = add_entry(CourseQueue(entries=()), "abc", now=NOW_1)
    queue = add_entry(queue, "xyz", now=NOW_1)

    queue = remove_entry(queue, "abc")

    assert [e.topic_id for e in queue.entries] == ["xyz"]


def test_remove_entry_unknown_topic_raises_config_error() -> None:
    with pytest.raises(ConfigError):
        remove_entry(CourseQueue(entries=()), "nope")


# ---------------------------------------------------------------------------
# mark_running / mark_stopped / pending_entries
# ---------------------------------------------------------------------------


def test_mark_running_updates_status_and_updated_at_in_place() -> None:
    queue = add_entry(CourseQueue(entries=()), "abc", now=NOW_1)

    queue = mark_running(queue, "abc", now=NOW_2)

    entry = queue.entries[0]
    assert entry.status == "running"
    assert entry.updated_at == NOW_2
    assert entry.added_at == NOW_1


def test_mark_running_unknown_topic_raises_config_error() -> None:
    with pytest.raises(ConfigError):
        mark_running(CourseQueue(entries=()), "nope", now=NOW_1)


def test_mark_stopped_records_stop_payload_and_status() -> None:
    stop = {"kind": "approve", "stage": "draft"}
    queue = add_entry(CourseQueue(entries=()), "abc", now=NOW_1)

    queue = mark_stopped(queue, "abc", stop, now=NOW_2)

    entry = queue.entries[0]
    assert entry.status == "stopped"
    assert entry.stop == stop
    assert entry.updated_at == NOW_2


def test_mark_stopped_unknown_topic_raises_config_error() -> None:
    with pytest.raises(ConfigError):
        mark_stopped(CourseQueue(entries=()), "nope", {"kind": "done"}, now=NOW_1)


def test_pending_entries_returns_queued_and_running_in_file_order() -> None:
    queue = CourseQueue(entries=())
    queue = add_entry(queue, "a", now=NOW_1)
    queue = add_entry(queue, "b", now=NOW_1)
    queue = add_entry(queue, "c", now=NOW_1)
    queue = mark_running(queue, "b", now=NOW_2)
    queue = mark_stopped(queue, "c", {"kind": "done"}, now=NOW_2)

    assert [e.topic_id for e in pending_entries(queue)] == ["a", "b"]


def test_pending_entries_empty_when_all_stopped() -> None:
    queue = add_entry(CourseQueue(entries=()), "a", now=NOW_1)
    queue = mark_stopped(queue, "a", {"kind": "done"}, now=NOW_2)

    assert pending_entries(queue) == ()


# ---------------------------------------------------------------------------
# save_queue: creation, atomicity, round-trip, on-disk shape
# ---------------------------------------------------------------------------


def test_save_queue_creates_missing_queue_dir(tmp_path: Path) -> None:
    assert not (tmp_path / "queue").exists()
    queue = add_entry(CourseQueue(entries=()), "abc", now=NOW_1)

    save_queue(tmp_path, queue)

    assert (tmp_path / "queue").is_dir()


def test_save_queue_returns_the_queue_path(tmp_path: Path) -> None:
    queue = add_entry(CourseQueue(entries=()), "abc", now=NOW_1)
    assert save_queue(tmp_path, queue) == queue_path(tmp_path)


def test_save_then_load_round_trips(tmp_path: Path) -> None:
    queue = add_entry(CourseQueue(entries=()), "abc", now=NOW_1)
    queue = add_entry(queue, "xyz", now=NOW_1)
    queue = mark_stopped(
        queue, "xyz", {"kind": "failed", "action": "x", "message": "boom"}, now=NOW_2
    )

    save_queue(tmp_path, queue)

    assert load_queue(tmp_path) == queue


def test_save_queue_leaves_no_leftover_tmp_files(tmp_path: Path) -> None:
    queue = add_entry(CourseQueue(entries=()), "abc", now=NOW_1)
    save_queue(tmp_path, queue)

    leftovers = [p for p in queue_path(tmp_path).parent.iterdir() if p.name != "courses.json"]
    assert leftovers == []


def test_second_save_is_byte_identical(tmp_path: Path) -> None:
    queue = add_entry(CourseQueue(entries=()), "abc", now=NOW_1)
    save_queue(tmp_path, queue)
    first = queue_path(tmp_path).read_bytes()

    save_queue(tmp_path, queue)
    second = queue_path(tmp_path).read_bytes()

    assert first == second


def test_save_queue_writes_a_trailing_newline(tmp_path: Path) -> None:
    queue = add_entry(CourseQueue(entries=()), "abc", now=NOW_1)
    save_queue(tmp_path, queue)

    assert queue_path(tmp_path).read_text(encoding="utf-8").endswith("\n")


def test_save_queue_uses_sorted_keys_at_every_level(tmp_path: Path) -> None:
    queue = add_entry(CourseQueue(entries=()), "abc", now=NOW_1)
    queue = mark_stopped(queue, "abc", {"kind": "approve", "stage": "draft"}, now=NOW_2)
    save_queue(tmp_path, queue)
    text = queue_path(tmp_path).read_text(encoding="utf-8")

    # object_pairs_hook applies to every JSON object in the document (however
    # deeply nested), so this recovers each level's on-disk key order.
    top_pairs = json.loads(text, object_pairs_hook=list)
    top_keys = [key for key, _ in top_pairs]
    assert top_keys == sorted(top_keys)
    assert top_keys == ["entries", "version"]

    entries_value = dict(top_pairs)["entries"]
    assert len(entries_value) == 1
    entry_pairs = entries_value[0]
    entry_keys = [key for key, _ in entry_pairs]
    assert entry_keys == sorted(entry_keys)
    assert entry_keys == ["added_at", "status", "stop", "topic_id", "updated_at"]


def test_save_queue_entry_json_shape(tmp_path: Path) -> None:
    queue = add_entry(CourseQueue(entries=()), "abc", now=NOW_1)
    save_queue(tmp_path, queue)

    data = json.loads(queue_path(tmp_path).read_text(encoding="utf-8"))
    assert data == {
        "version": QUEUE_VERSION,
        "entries": [
            {
                "topic_id": "abc",
                "added_at": NOW_1,
                "updated_at": NOW_1,
                "status": "queued",
                "stop": None,
            }
        ],
    }
