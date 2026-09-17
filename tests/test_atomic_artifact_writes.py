"""Crash-safety tests for approved/prompt/final/export artifact writes.

``RunStore`` writes run manifests and the model-plan overrides file
atomically (via ``education_pipeline.atomic_io``), but approved stage
artifacts, prompts/stubs, and the deterministic finalize/export outputs are
still written with a plain ``Path.write_text`` (see ``_write_text`` in
``runs.py``). A process that dies mid-write there leaves a truncated file at
the *real* target path -- and downstream stages hash and consume exactly
that file. These tests pin the fix: every one of those rewrite paths must go
through the same temp-file-plus-``os.replace`` primitive the manifest and
plan-overrides writers already use, so a crash during the swap leaves the
previous, complete content in place and no stray temp file behind.

Fault-injection technique: monkeypatch ``os.replace`` to raise partway
through a rewrite, mirroring ``tests/test_atomic_io.py``'s
``test_atomic_write_bytes_cleans_up_temp_file_when_replace_fails``. Today's
``_write_text`` never calls ``os.replace`` at all -- it writes straight to
the target -- so this injection currently does nothing: the write silently
"succeeds" with the *new* content and no exception is raised. That is
exactly why these tests fail now: they expect the write to fail loudly
(propagating the simulated crash) and the previous content to survive.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from education_pipeline import ConfigError, TopicStore
from education_pipeline import runs as runs_module

from test_runs import TOPIC_TOML, _create_legacy_run, _drive_all_stages_to_approved


def _crash_os_replace(monkeypatch: pytest.MonkeyPatch, message: str = "simulated crash mid-write") -> None:
    """Make every ``os.replace`` call raise, as if the process died mid-swap."""

    def failing_replace(source, destination):
        raise OSError(message)

    monkeypatch.setattr(os, "replace", failing_replace)


def _tmp_leftovers(directory: Path) -> list[str]:
    if not directory.exists():
        return []
    return [entry.name for entry in directory.iterdir() if entry.name.startswith(".tmp-")]


# ---------------------------------------------------------------------------
# 1a. approve_stage: re-approving over an existing approved file must be
#     crash-safe.
# ---------------------------------------------------------------------------


def test_reapproving_a_stage_survives_a_crash_mid_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _create_legacy_run(tmp_path)
    result = store.write_spec_prompt("systems-thinking", title="Systems Thinking")
    result.response_path.write_text("# Course Specification\n\nOLD.\n", encoding="utf-8")
    approved_path = store.approve_stage("systems-thinking", "spec")
    original_bytes = approved_path.read_bytes()
    assert original_bytes == b"# Course Specification\n\nOLD.\n"

    # A new (different) response is ingested and re-approved -- this is the
    # rewrite path that must be crash-safe.
    result.response_path.write_text("# Course Specification\n\nNEW.\n", encoding="utf-8")
    _crash_os_replace(monkeypatch)

    with pytest.raises(OSError, match="simulated crash mid-write"):
        store.approve_stage("systems-thinking", "spec", overwrite=True)

    assert approved_path.read_bytes() == original_bytes, (
        "a crash mid-rewrite must never leave the approved artifact "
        "truncated or holding the new, un-committed content"
    )
    assert _tmp_leftovers(approved_path.parent) == []


# ---------------------------------------------------------------------------
# 1b. write_prompt: re-writing a prompt (and its stub) over an existing one
#     must be crash-safe.
# ---------------------------------------------------------------------------


def test_rewriting_a_prompt_survives_a_crash_mid_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _create_legacy_run(tmp_path)
    result = store.write_spec_prompt("systems-thinking", title="Old Title")
    original_bytes = result.prompt_path.read_bytes()
    assert b"Old Title" in original_bytes

    _crash_os_replace(monkeypatch)

    with pytest.raises(OSError, match="simulated crash mid-write"):
        store.write_spec_prompt("systems-thinking", title="New Title", overwrite=True)

    assert result.prompt_path.read_bytes() == original_bytes, (
        "a crash while rewriting the prompt must leave the previous prompt "
        "byte-for-byte intact, not a truncated or half-new file"
    )
    assert _tmp_leftovers(result.prompt_path.parent) == []


# ---------------------------------------------------------------------------
# 1c. finalize_run / export_run: rewriting the deterministic output must be
#     crash-safe.
# ---------------------------------------------------------------------------


def test_refinalizing_a_run_survives_a_crash_mid_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    TopicStore(tmp_path).save_topic_toml("systems-thinking", TOPIC_TOML)
    runs = _create_legacy_run(tmp_path)
    _drive_all_stages_to_approved(
        runs, "systems-thinking", repair_body="# Systems Thinking\n\nOLD.\n"
    )
    final_path = runs.finalize_run("systems-thinking")
    original_bytes = final_path.read_bytes()
    assert original_bytes == b"# Systems Thinking\n\nOLD.\n"

    # Change what finalize would copy next time, so a successful rewrite
    # would be observably different from the original.
    approved_repair = runs.stage_paths("systems-thinking", "repair").approved_path
    approved_repair.write_text("# Systems Thinking\n\nNEW.\n", encoding="utf-8", newline="")

    _crash_os_replace(monkeypatch)

    with pytest.raises(OSError, match="simulated crash mid-write"):
        runs.finalize_run("systems-thinking", overwrite=True)

    assert final_path.read_bytes() == original_bytes, (
        "a crash while re-finalizing must leave the previous final guide "
        "byte-for-byte intact"
    )
    assert _tmp_leftovers(final_path.parent) == []


def test_reexporting_a_run_survives_a_crash_mid_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    TopicStore(tmp_path).save_topic_toml("systems-thinking", TOPIC_TOML)
    runs = _create_legacy_run(tmp_path)
    _drive_all_stages_to_approved(
        runs, "systems-thinking", repair_body="# Systems Thinking\n\nCorrected content.\n"
    )
    runs.finalize_run("systems-thinking")
    export_path = runs.export_run("systems-thinking", format="html")
    original_bytes = export_path.read_bytes()
    assert original_bytes.startswith(b"<!DOCTYPE html>")
    assert b"Corrected content." in original_bytes

    # Change what a re-export would render, so a rewrite that actually
    # happens is observably different from the original -- otherwise a
    # coincidentally-identical re-render would mask the bug. Do this (and the
    # re-finalize) before injecting the crash below.
    approved_repair = runs.stage_paths("systems-thinking", "repair").approved_path
    approved_repair.write_text(
        "# Systems Thinking\n\nReplaced content.\n", encoding="utf-8", newline=""
    )
    runs.finalize_run("systems-thinking", overwrite=True)

    _crash_os_replace(monkeypatch)

    with pytest.raises(OSError, match="simulated crash mid-write"):
        runs.export_run("systems-thinking", format="html", overwrite=True)

    assert export_path.read_bytes() == original_bytes, (
        "a crash while re-exporting must leave the previous export "
        "byte-for-byte intact"
    )
    assert _tmp_leftovers(export_path.parent) == []


# ---------------------------------------------------------------------------
# 2. overwrite=False semantics must be preserved by the change.
# ---------------------------------------------------------------------------


def test_approve_stage_without_overwrite_refuses_and_does_not_touch_the_file(
    tmp_path: Path,
) -> None:
    store = _create_legacy_run(tmp_path)
    result = store.write_spec_prompt("systems-thinking", title="Systems Thinking")
    result.response_path.write_text("# Course Specification\n\nOLD.\n", encoding="utf-8")
    approved_path = store.approve_stage("systems-thinking", "spec")
    original_bytes = approved_path.read_bytes()

    result.response_path.write_text("# Course Specification\n\nNEW.\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="refusing to overwrite"):
        store.approve_stage("systems-thinking", "spec")

    assert approved_path.read_bytes() == original_bytes


def test_export_run_without_overwrite_refuses_and_does_not_touch_the_file(
    tmp_path: Path,
) -> None:
    TopicStore(tmp_path).save_topic_toml("systems-thinking", TOPIC_TOML)
    runs = _create_legacy_run(tmp_path)
    _drive_all_stages_to_approved(
        runs, "systems-thinking", repair_body="# Systems Thinking\n\nCorrected content.\n"
    )
    runs.finalize_run("systems-thinking")
    export_path = runs.export_run("systems-thinking", format="html")
    original_bytes = export_path.read_bytes()

    with pytest.raises(ConfigError, match="refusing to overwrite"):
        runs.export_run("systems-thinking", format="html")

    assert export_path.read_bytes() == original_bytes


# ---------------------------------------------------------------------------
# 3. Structural guard: no direct Path.write_text(...) call sites left in
#    runs.py. This is a source-grep, not a behavioral test -- it exists so a
#    non-atomic write sneaking back in (via a resurrected `_write_text` body
#    or a brand-new call site) fails fast without needing a fault-injection
#    test for every future artifact. If this proves too brittle to live with
#    (e.g. a legitimate direct write is ever needed), the manager should
#    decide whether to relax or drop it rather than have it be silently
#    weakened.
# ---------------------------------------------------------------------------


def test_runs_module_has_no_direct_path_write_text_calls() -> None:
    source = Path(runs_module.__file__).read_text(encoding="utf-8")
    direct_calls = re.findall(r"\.write_text\(", source)
    assert direct_calls == [], (
        "found a direct Path.write_text(...) call in runs.py; route artifact "
        "writes through atomic_io.atomic_write_text/atomic_write_bytes "
        "(or the runs.py helpers backed by them) instead"
    )


# ---------------------------------------------------------------------------
# 5. TopicStore.save_topic_toml: the last plain artifact write in the package.
#    Re-saving a topic over an existing TOML must be crash-safe too.
# ---------------------------------------------------------------------------


def test_resaving_a_topic_toml_survives_a_crash_mid_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    topics = TopicStore(tmp_path)
    topics.save_topic_toml("systems-thinking", TOPIC_TOML)
    path = tmp_path / "topics" / "systems-thinking.toml"
    before = path.read_bytes()
    assert before

    _crash_os_replace(monkeypatch, "simulated crash mid-write")
    with pytest.raises(OSError, match="simulated crash mid-write"):
        topics.save_topic_toml(
            "systems-thinking",
            TOPIC_TOML.replace('title = "Systems Thinking"', 'title = "Systems Thinking, revised"'),
            overwrite=True,
        )

    assert path.read_bytes() == before
    assert _tmp_leftovers(path.parent) == []


def test_save_topic_toml_without_overwrite_refuses_and_does_not_touch_the_file(
    tmp_path: Path,
) -> None:
    topics = TopicStore(tmp_path)
    topics.save_topic_toml("systems-thinking", TOPIC_TOML)
    path = tmp_path / "topics" / "systems-thinking.toml"
    before = path.read_bytes()

    with pytest.raises(ConfigError, match="refusing to overwrite"):
        topics.save_topic_toml("systems-thinking", TOPIC_TOML + "\n# edited\n")

    assert path.read_bytes() == before


def test_workspace_module_has_no_direct_path_write_text_calls() -> None:
    """Structural guard, same shape as the runs.py check above: every
    artifact write in workspace.py must go through atomic_io."""

    import education_pipeline.workspace as workspace_module

    source = Path(workspace_module.__file__).read_text(encoding="utf-8")
    assert not re.search(r"\.write_text\(", source)
