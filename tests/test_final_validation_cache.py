"""Pins the final-validation cache: a status read on a topic whose final
report is current must not re-parse/re-validate the whole guide on every
poll.

Problem: ``RunStore._next_action`` (runs.py) unconditionally calls
``_validated_final`` -- a full parse + normalize + static-checks + validate
pass -- every time it needs to recheck the finalize gate, even when
``report_state`` already says the on-disk report is "current" for the exact
same approved source. ``run_status_payload`` (daemon/read_api.py) calls
``run_status`` (and therefore ``_next_action``) for every topic on every
library/board poll, making this O(topics) full validations per poll tick.

These tests pin the fix's exit criteria by counting calls to the four
functions ``_validated_final`` (and its sibling ``gate_result``) call under
the hood: ``parse_guide``, ``normalize_guide``, ``compute_static_checks`` and
``validate_guide`` (all bound as module-level names in ``education_pipeline
.runs``, per its import block).
"""

import json
import os
import time
from pathlib import Path

import test_runs

from education_pipeline import runs_reports as runs_module
from education_pipeline.daemon import read_api
from education_pipeline.runs import ContentContract, RunStore
from education_pipeline.workspace import TopicStore

_COUNTED_NAMES = (
    "parse_guide",
    "normalize_guide",
    "compute_static_checks",
    "validate_guide",
)


def _count_validation_calls(monkeypatch) -> dict:
    """Wrap the guide parse/validate entry points ``_validated_final`` (and
    ``gate_result``, via ``_compute_phase_report``) call, and return a live
    counter dict updated as each wrapped function is invoked."""

    counts = {name: 0 for name in _COUNTED_NAMES}

    def _make_wrapper(name, original):
        def _wrapper(*args, **kwargs):
            counts[name] += 1
            return original(*args, **kwargs)

        return _wrapper

    for name in _COUNTED_NAMES:
        original = getattr(runs_module, name)
        monkeypatch.setattr(runs_module, name, _make_wrapper(name, original))
    return counts


def _reset(counts: dict) -> None:
    for name in counts:
        counts[name] = 0


def _finalize_ready_run(tmp_path: Path, topic_id: str = "systems-thinking") -> RunStore:
    """A guide run driven to finalize-ready with no findings and no waivers:
    ``report_state(final)`` is "current" and ``next_action`` is "finalize"."""

    runs = test_runs._create_guide_run(tmp_path, topic_id)
    test_runs._drive_guide_to_finalize_ready(runs, topic_id)
    return runs


def _finalize_ready_run_with_waivable_finding(
    tmp_path: Path, topic_id: str = "systems-thinking"
) -> tuple[RunStore, str]:
    """A guide run driven to finalize-ready with a real, waivable blocking
    finding left un-waived: ``report_state(final)`` is "current" but the
    gate is closed (``next_action`` is "resolve_findings")."""

    runs = test_runs._create_guide_run(tmp_path, topic_id)
    leak_json = test_runs._prompt_leak_guide_json()
    test_runs._drive_guide_to_finalize_ready(
        runs, topic_id, draft_body=leak_json, repair_body=leak_json
    )
    finding_id = test_runs._first_waivable_blocking_finding_id(runs, topic_id, "final")
    return runs, finding_id


def _add_todo_marker(guide_json: str) -> str:
    """Return guide JSON with a trailing " TODO" appended to the first
    section block's markdown -- the same technique test_server.py uses to
    produce a real, waivable blocking finding."""

    data = json.loads(guide_json)
    data["modules"][0]["sections"][0]["blocks"][0]["markdown"] += " TODO"
    return json.dumps(data)


# ---------------------------------------------------------------------------
# 1. Zero validation calls on a warm read.
# ---------------------------------------------------------------------------


def test_status_read_performs_no_validation_after_warm_read(tmp_path, monkeypatch):
    runs = _finalize_ready_run(tmp_path)
    topic_id = "systems-thinking"
    counts = _count_validation_calls(monkeypatch)

    warm = read_api.run_status_payload(runs, topic_id)
    assert warm["next_action"]["action"] == "finalize"

    _reset(counts)

    again = read_api.run_status_payload(runs, topic_id)

    assert again == warm
    assert all(count == 0 for count in counts.values()), counts


def test_status_read_stays_zero_across_several_repeated_reads(tmp_path, monkeypatch):
    """Not just the second read: any number of subsequent reads of an
    unchanged, current topic must stay free of guide parse/validate calls."""

    runs = _finalize_ready_run(tmp_path)
    topic_id = "systems-thinking"
    counts = _count_validation_calls(monkeypatch)

    read_api.run_status_payload(runs, topic_id)
    _reset(counts)

    for _ in range(5):
        read_api.run_status_payload(runs, topic_id)

    assert all(count == 0 for count in counts.values()), counts


# ---------------------------------------------------------------------------
# 2. Cache invalidation on the observable triggers.
# ---------------------------------------------------------------------------


def test_reapproving_a_stage_with_a_changed_response_invalidates_the_cache(
    tmp_path, monkeypatch
):
    """(a) Re-approving repair with different content, then revalidating,
    must not serve the old cached finalize-ready result."""

    runs = _finalize_ready_run(tmp_path)
    topic_id = "systems-thinking"
    counts = _count_validation_calls(monkeypatch)

    warm = read_api.run_status_payload(runs, topic_id)
    assert warm["next_action"]["action"] == "finalize"

    new_body = _add_todo_marker(test_runs.GUIDE_FIXTURE)
    repair_paths = runs.stage_paths(topic_id, "repair")
    repair_paths.response_path.write_text(new_body, encoding="utf-8")
    runs.approve_stage(topic_id, "repair", overwrite=True)
    runs.validate_run(topic_id, "final")

    _reset(counts)

    after = read_api.run_status_payload(runs, topic_id)

    assert after["next_action"]["action"] != "finalize"
    assert after["next_action"]["action"] == "resolve_findings"
    assert any(count > 0 for count in counts.values()), counts


def test_adding_and_removing_a_waiver_invalidates_the_cache(tmp_path, monkeypatch):
    """(b) Recording, then removing, a waiver for the sole blocker must each
    flip the reported gate on the very next read -- never a cached stale
    verdict."""

    runs, finding_id = _finalize_ready_run_with_waivable_finding(tmp_path)
    topic_id = "systems-thinking"
    counts = _count_validation_calls(monkeypatch)

    warm = read_api.run_status_payload(runs, topic_id)
    assert warm["next_action"]["action"] == "resolve_findings"

    _reset(counts)
    runs.record_waiver(topic_id, "final", finding_id, "Intentional example text.")

    after_waive = read_api.run_status_payload(runs, topic_id)
    assert after_waive["next_action"]["action"] == "finalize"
    assert any(count > 0 for count in counts.values()), counts

    _reset(counts)
    runs.remove_waiver(topic_id, "final", finding_id)

    after_unwaive = read_api.run_status_payload(runs, topic_id)
    assert after_unwaive["next_action"]["action"] == "resolve_findings"
    assert any(count > 0 for count in counts.values()), counts


def test_editing_the_approved_artifact_on_disk_invalidates_the_cache(
    tmp_path, monkeypatch
):
    """(c) Editing the approved repair text directly on disk (bypassing
    approve_stage entirely, so only the content bytes change) and
    revalidating must not serve the prior cached result -- proving the cache
    keys on real content, not on approval bookkeeping."""

    runs = _finalize_ready_run(tmp_path)
    topic_id = "systems-thinking"
    counts = _count_validation_calls(monkeypatch)

    warm = read_api.run_status_payload(runs, topic_id)
    assert warm["next_action"]["action"] == "finalize"

    approved_path = runs.stage_paths(topic_id, "repair").approved_path
    approved_path.write_text(
        _add_todo_marker(approved_path.read_text(encoding="utf-8")), encoding="utf-8"
    )
    assert runs.report_state(topic_id, "final") == "stale"
    runs.validate_run(topic_id, "final")
    assert runs.report_state(topic_id, "final") == "current"

    _reset(counts)

    after = read_api.run_status_payload(runs, topic_id)

    assert after["next_action"]["action"] != "finalize"
    assert after["next_action"]["action"] == "resolve_findings"
    assert any(count > 0 for count in counts.values()), counts


# ---------------------------------------------------------------------------
# 3. Timing harness: 20 topics polled repeatedly, fastest warm pass under 50ms.
# ---------------------------------------------------------------------------


def test_polling_twenty_current_topics_is_fast_on_the_second_pass(tmp_path):
    """One RunStore serving 20 topics (as the daemon does), each with a
    current final report -- matching a library/board poll tick. Not flaky:
    warms the cache first, then times five further passes and asserts on the
    fastest. The minimum is still one real, unmodified pass -- it just drops
    the passes that lost the CPU to something else."""

    topic_ids = [f"topic-{i:02d}" for i in range(20)]
    topics = TopicStore(tmp_path)
    runs = RunStore(tmp_path)
    for topic_id in topic_ids:
        topic_toml = test_runs.TOPIC_TOML.replace(
            'id = "systems-thinking"', f'id = "{topic_id}"'
        )
        topics.save_topic_toml(topic_id, topic_toml)
        runs.create_run(topic_id, content_contract=ContentContract.interactive_guide_v1())
        test_runs._drive_guide_to_finalize_ready(runs, topic_id)

    # Warm pass: whatever caching exists gets populated here.
    for topic_id in topic_ids:
        payload = read_api.run_status_payload(runs, topic_id)
        assert payload["next_action"]["action"] == "finalize"

    passes = []
    for _ in range(5):
        start = time.perf_counter()
        for topic_id in topic_ids:
            read_api.run_status_payload(runs, topic_id)
        passes.append(time.perf_counter() - start)
    fastest = min(passes)

    # Shared CI runners are noisy and their filesystems/pathlib are slower
    # (Windows especially), so the budget is relaxed there rather than tuned
    # down for everyone locally. The local budget was raised from 50ms to 70ms
    # when the payload gained ``draft_progress`` (per-module drafting, T24):
    # that costs a further ~0.2 ms per guide topic in stats and path building,
    # which is ~8% on top of a poll tick and is measured, not pathological.
    # The precise guard against the regression this file exists for is the
    # call-count assertions above (zero re-validations per poll), not this
    # wall-clock smoke check.
    budget = 0.2 if os.environ.get("CI") else 0.07

    assert fastest < budget, (
        f"fastest of {len(passes)} warm passes over {len(topic_ids)} current "
        f"topics took {fastest * 1000:.1f} ms "
        f"(budget: {budget * 1000:.0f} ms); all passes: "
        + ", ".join(f"{value * 1000:.1f}" for value in passes)
    )


# ---------------------------------------------------------------------------
# 4. The cache must be per-RunStore-instance (or content-keyed), never a
#    module-level global that leaks between unrelated workspaces.
# ---------------------------------------------------------------------------


def test_cache_does_not_leak_across_runstore_instances(tmp_path):
    """Two independent workspaces, sharing the same topic_id, must never
    have one's cached verdict served for the other's read -- ruling out a
    module-global (or process-global) cache keyed only on topic_id."""

    topic_id = "systems-thinking"
    workspace_a = tmp_path / "a"
    workspace_b = tmp_path / "b"
    workspace_a.mkdir()
    workspace_b.mkdir()

    runs_a = _finalize_ready_run(workspace_a, topic_id)
    payload_a = read_api.run_status_payload(runs_a, topic_id)
    assert payload_a["next_action"]["action"] == "finalize"

    # A second workspace, same topic id, but with a real un-waived blocking
    # finding -- if runs_b's read were served from a cache shared with
    # runs_a (or a global keyed only on topic_id), it would wrongly inherit
    # "finalize" instead of correctly gating.
    runs_b, _finding_id = _finalize_ready_run_with_waivable_finding(workspace_b, topic_id)

    payload_b = read_api.run_status_payload(runs_b, topic_id)
    assert payload_b["next_action"]["action"] == "resolve_findings"

    # And the reverse read on runs_a must still be unaffected by runs_b's
    # read having just happened.
    payload_a_again = read_api.run_status_payload(runs_a, topic_id)
    assert payload_a_again["next_action"]["action"] == "finalize"
