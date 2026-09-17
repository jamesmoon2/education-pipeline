"""Characterization ("golden") tests for legacy Markdown ``RunStore`` behavior.

These tests exist to PIN the current, observed behavior of ``RunStore`` for
runs created with ``ContentContract.legacy_markdown()`` ahead of two planned
refactors:

1. The stage dependency chain (currently ``_next_action_legacy`` /
   ``_next_action_guide_v1`` in ``education_pipeline/runs.py``) will be
   rewritten as a data-driven graph.
2. The legacy Markdown mode will be moved behind a strategy object, out of
   the guide-v1-centric ``RunStore`` methods it currently shares.

Every assertion below reflects OBSERVED behavior of the current source, not
a specification of "correct" behavior. Where the current behavior is
surprising (e.g. ``factcheck`` appearing as a stage entry for legacy runs
that never use it, or stage staleness never being computed for legacy
stages), that is called out in a comment and in the accompanying report.

Do not modify anything under ``education_pipeline/`` to make these pass:
if a test fails, the fix is to correct the pinned expectation to match
observed behavior, not to change production code.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from education_pipeline import (
    ConfigError,
    ContentContract,
    RunStore,
    TopicStore,
)

TOPIC_TOML = """\
schema_version = 1
id = "systems-thinking"
title = "Systems Thinking"
brief = "A public introduction to feedback loops."
audience = "early-career analysts"
goals = ["explain feedback loops"]
"""


# --- small builders, copied from tests/test_runs.py (tests/ has no __init__.py,
# so `from tests.test_runs import ...` is not reliably importable) -----------


def _save_topic(tmp_path: Path, topic_id: str = "systems-thinking") -> None:
    toml = TOPIC_TOML.replace('id = "systems-thinking"', f'id = "{topic_id}"')
    TopicStore(tmp_path).save_topic_toml(topic_id, toml)


def _create_legacy_run(tmp_path: Path, topic_id: str = "systems-thinking") -> RunStore:
    """Create an explicit legacy Markdown run and its backing topic file."""

    _save_topic(tmp_path, topic_id)
    runs = RunStore(tmp_path)
    runs.create_run(topic_id, content_contract=ContentContract.legacy_markdown())
    return runs


def _drive_spec_to_approved(runs: RunStore, topic_id: str) -> None:
    result = runs.write_spec_prompt(topic_id, title="Systems Thinking")
    result.response_path.write_text("# Course Specification\n", encoding="utf-8")
    runs.approve_stage(topic_id, "spec")


def _drive_outline_to_approved(runs: RunStore, topic_id: str) -> None:
    result = runs.write_outline_prompt(topic_id)
    result.response_path.write_text("# Course Outline\n", encoding="utf-8")
    runs.approve_stage(topic_id, "outline")


def _drive_draft_to_approved(runs: RunStore, topic_id: str) -> None:
    result = runs.write_draft_prompt(topic_id)
    result.response_path.write_text("# Systems Thinking\n", encoding="utf-8")
    runs.approve_stage(topic_id, "draft")


def _drive_qa_to_approved(runs: RunStore, topic_id: str) -> None:
    result = runs.write_qa_prompt(topic_id)
    result.response_path.write_text("# QA Report\n", encoding="utf-8")
    runs.approve_stage(topic_id, "qa")


def _drive_repair_to_approved(runs: RunStore, topic_id: str, body: str = "# Systems Thinking\n") -> None:
    result = runs.write_repair_prompt(topic_id)
    result.response_path.write_text(body, encoding="utf-8")
    runs.approve_stage(topic_id, "repair")


def _drive_all_stages_to_approved(runs: RunStore, topic_id: str, repair_body: str = "# Systems Thinking\n") -> None:
    _drive_spec_to_approved(runs, topic_id)
    _drive_outline_to_approved(runs, topic_id)
    _drive_draft_to_approved(runs, topic_id)
    _drive_qa_to_approved(runs, topic_id)
    _drive_repair_to_approved(runs, topic_id, repair_body)


# All SUPPORTED_STAGES as reported by run_status().stages, in order, for a
# legacy run. Pinned here rather than imported so this file stands alone
# against a data-driven rewrite of the stage list.
_ALL_STATUS_STAGE_NAMES = ("spec", "outline", "draft", "qa", "factcheck", "repair", "audit")


# ---------------------------------------------------------------------------
# 1. next_action across states (via RunStore.run_status(topic_id).next_action
#    -- there is no bare RunStore.next_action method in current source).
# ---------------------------------------------------------------------------

_NEXT_ACTION_STATE_BUILDERS = {
    "fresh": lambda runs, tid: None,
    "spec_prompt_written": lambda runs, tid: runs.write_spec_prompt(tid, title="Systems Thinking"),
    "spec_ingested": lambda runs, tid: _ingest_only(runs, tid, "spec"),
    "spec_approved": lambda runs, tid: _drive_spec_to_approved(runs, tid),
    "outline_prompt_written": lambda runs, tid: (_drive_spec_to_approved(runs, tid), runs.write_outline_prompt(tid)),
    "outline_ingested": lambda runs, tid: (_drive_spec_to_approved(runs, tid), _ingest_only(runs, tid, "outline")),
    "outline_approved": lambda runs, tid: (_drive_spec_to_approved(runs, tid), _drive_outline_to_approved(runs, tid)),
    "draft_prompt_written": lambda runs, tid: (
        _drive_spec_to_approved(runs, tid),
        _drive_outline_to_approved(runs, tid),
        runs.write_draft_prompt(tid),
    ),
    "draft_ingested": lambda runs, tid: (
        _drive_spec_to_approved(runs, tid),
        _drive_outline_to_approved(runs, tid),
        _ingest_only(runs, tid, "draft"),
    ),
    "draft_approved": lambda runs, tid: (
        _drive_spec_to_approved(runs, tid),
        _drive_outline_to_approved(runs, tid),
        _drive_draft_to_approved(runs, tid),
    ),
    "qa_prompt_written": lambda runs, tid: (
        _drive_spec_to_approved(runs, tid),
        _drive_outline_to_approved(runs, tid),
        _drive_draft_to_approved(runs, tid),
        runs.write_qa_prompt(tid),
    ),
    "qa_ingested": lambda runs, tid: (
        _drive_spec_to_approved(runs, tid),
        _drive_outline_to_approved(runs, tid),
        _drive_draft_to_approved(runs, tid),
        _ingest_only(runs, tid, "qa"),
    ),
    "qa_approved": lambda runs, tid: (
        _drive_spec_to_approved(runs, tid),
        _drive_outline_to_approved(runs, tid),
        _drive_draft_to_approved(runs, tid),
        _drive_qa_to_approved(runs, tid),
    ),
    "repair_prompt_written": lambda runs, tid: (
        _drive_spec_to_approved(runs, tid),
        _drive_outline_to_approved(runs, tid),
        _drive_draft_to_approved(runs, tid),
        _drive_qa_to_approved(runs, tid),
        runs.write_repair_prompt(tid),
    ),
    "repair_ingested": lambda runs, tid: (
        _drive_spec_to_approved(runs, tid),
        _drive_outline_to_approved(runs, tid),
        _drive_draft_to_approved(runs, tid),
        _drive_qa_to_approved(runs, tid),
        _ingest_only(runs, tid, "repair"),
    ),
    "repair_approved_not_finalized": lambda runs, tid: _drive_all_stages_to_approved(runs, tid),
    "finalized": lambda runs, tid: (_drive_all_stages_to_approved(runs, tid), runs.finalize_run(tid)),
}


def _ingest_only(runs: RunStore, topic_id: str, stage: str) -> None:
    """Write a stage's prompt and save a response, but do not approve it."""

    writer = {
        "spec": lambda: runs.write_spec_prompt(topic_id, title="Systems Thinking"),
        "outline": lambda: runs.write_outline_prompt(topic_id),
        "draft": lambda: runs.write_draft_prompt(topic_id),
        "qa": lambda: runs.write_qa_prompt(topic_id),
        "repair": lambda: runs.write_repair_prompt(topic_id),
    }[stage]
    result = writer()
    result.response_path.write_text(f"# {stage} response\n", encoding="utf-8")


# (state name, expected stage, expected action)
_NEXT_ACTION_EXPECTATIONS = [
    ("fresh", "spec", "write_prompt"),
    ("spec_prompt_written", "spec", "save_response"),
    ("spec_ingested", "spec", "approve"),
    ("spec_approved", "outline", "write_prompt"),
    ("outline_prompt_written", "outline", "save_response"),
    ("outline_ingested", "outline", "approve"),
    ("outline_approved", "draft", "write_prompt"),
    ("draft_prompt_written", "draft", "save_response"),
    ("draft_ingested", "draft", "approve"),
    ("draft_approved", "qa", "write_prompt"),
    ("qa_prompt_written", "qa", "save_response"),
    ("qa_ingested", "qa", "approve"),
    ("qa_approved", "repair", "write_prompt"),
    ("repair_prompt_written", "repair", "save_response"),
    ("repair_ingested", "repair", "approve"),
    ("repair_approved_not_finalized", None, "finalize"),
    ("finalized", None, "done"),
]


@pytest.mark.parametrize("state, expected_stage, expected_action", _NEXT_ACTION_EXPECTATIONS)
def test_next_action_across_legacy_states(
    tmp_path: Path, state: str, expected_stage: str | None, expected_action: str
) -> None:
    topic_id = "systems-thinking"
    runs = _create_legacy_run(tmp_path, topic_id)
    _NEXT_ACTION_STATE_BUILDERS[state](runs, topic_id)

    next_action = runs.run_status(topic_id).next_action

    assert next_action.stage == expected_stage
    assert next_action.action == expected_action
    assert next_action.topic_id == topic_id


# ---------------------------------------------------------------------------
# 2. run_status(topic_id).stages -- which stages appear, and their fields.
# ---------------------------------------------------------------------------


def test_legacy_run_status_reports_all_supported_stages_including_factcheck(tmp_path: Path) -> None:
    """PIN: factcheck appears as a StageStatus entry even for legacy runs.

    education_pipeline/config.py defines SUPPORTED_STAGES as
    GUIDE_V1_REQUIRED_STAGES + OPTIONAL_STAGES, which always includes
    "factcheck" and "audit". RunStatus.stages iterates SUPPORTED_STAGES
    regardless of content contract kind, so a legacy run reports a
    (never-progressing) factcheck stage entry rather than omitting it.
    """

    runs = _create_legacy_run(tmp_path)
    status = runs.run_status("systems-thinking")

    assert tuple(s.stage for s in status.stages) == _ALL_STATUS_STAGE_NAMES


def test_legacy_run_status_fresh_stage_flags_all_false(tmp_path: Path) -> None:
    runs = _create_legacy_run(tmp_path)
    status = runs.run_status("systems-thinking")

    for stage_status in status.stages:
        assert stage_status.approved is False
        assert stage_status.stale is False
        assert stage_status.prompt_written is False
        assert stage_status.response_ingested is False


_STAGE_STATUS_STATES = [
    "spec_prompt_written",
    "spec_ingested",
    "spec_approved",
    "outline_approved",
    "draft_approved",
    "qa_approved",
    "repair_approved_not_finalized",
]

# For each state, the expected (prompt_written, response_ingested, approved)
# tuple for each of the 7 status stages, in _ALL_STATUS_STAGE_NAMES order.
_STAGE_FLAGS_BY_STATE = {
    "spec_prompt_written": {
        "spec": (True, False, False),
        "outline": (False, False, False),
        "draft": (False, False, False),
        "qa": (False, False, False),
        "factcheck": (False, False, False),
        "repair": (False, False, False),
        "audit": (False, False, False),
    },
    "spec_ingested": {
        "spec": (True, True, False),
        "outline": (False, False, False),
        "draft": (False, False, False),
        "qa": (False, False, False),
        "factcheck": (False, False, False),
        "repair": (False, False, False),
        "audit": (False, False, False),
    },
    "spec_approved": {
        "spec": (True, True, True),
        "outline": (False, False, False),
        "draft": (False, False, False),
        "qa": (False, False, False),
        "factcheck": (False, False, False),
        "repair": (False, False, False),
        "audit": (False, False, False),
    },
    "outline_approved": {
        "spec": (True, True, True),
        "outline": (True, True, True),
        "draft": (False, False, False),
        "qa": (False, False, False),
        "factcheck": (False, False, False),
        "repair": (False, False, False),
        "audit": (False, False, False),
    },
    "draft_approved": {
        "spec": (True, True, True),
        "outline": (True, True, True),
        "draft": (True, True, True),
        "qa": (False, False, False),
        "factcheck": (False, False, False),
        "repair": (False, False, False),
        "audit": (False, False, False),
    },
    "qa_approved": {
        "spec": (True, True, True),
        "outline": (True, True, True),
        "draft": (True, True, True),
        "qa": (True, True, True),
        "factcheck": (False, False, False),
        "repair": (False, False, False),
        "audit": (False, False, False),
    },
    "repair_approved_not_finalized": {
        "spec": (True, True, True),
        "outline": (True, True, True),
        "draft": (True, True, True),
        "qa": (True, True, True),
        "factcheck": (False, False, False),
        "repair": (True, True, True),
        "audit": (False, False, False),
    },
}


@pytest.mark.parametrize("state", _STAGE_STATUS_STATES)
def test_legacy_run_status_stage_flags(tmp_path: Path, state: str) -> None:
    topic_id = "systems-thinking"
    runs = _create_legacy_run(tmp_path, topic_id)
    _NEXT_ACTION_STATE_BUILDERS[state](runs, topic_id)

    status = runs.run_status(topic_id)
    expected = _STAGE_FLAGS_BY_STATE[state]

    for stage_status in status.stages:
        prompt_written, response_ingested, approved = expected[stage_status.stage]
        assert stage_status.prompt_written is prompt_written, stage_status.stage
        assert stage_status.response_ingested is response_ingested, stage_status.stage
        assert stage_status.approved is approved, stage_status.stage
        # PIN: legacy stages never report stale, regardless of state (see
        # test_legacy_stage_never_reports_stale_after_upstream_reapproval).
        assert stage_status.stale is False, stage_status.stage


def test_legacy_stage_never_reports_stale_after_upstream_reapproval(tmp_path: Path) -> None:
    """PIN: re-approving an upstream stage with different bytes never marks a
    downstream legacy stage stale.

    stage_status() only calls self._stage_upstream_stale(...) when
    self._is_guide_v1(topic_id) is true (runs.py, stage_status, guarded on
    "qa", "factcheck", "repair"). For a legacy run that branch is never
    taken, so `stale` stays False even though qa/repair were approved
    against an outline that has since changed underneath them.
    """

    topic_id = "systems-thinking"
    runs = _create_legacy_run(tmp_path, topic_id)
    _drive_spec_to_approved(runs, topic_id)
    _drive_outline_to_approved(runs, topic_id)
    _drive_draft_to_approved(runs, topic_id)
    _drive_qa_to_approved(runs, topic_id)

    # Re-approve outline (an upstream stage of qa/repair) with different bytes.
    result = runs.write_outline_prompt(topic_id, overwrite=True)
    result.response_path.write_text("# Course Outline (materially different)\n", encoding="utf-8")
    runs.approve_stage(topic_id, "outline", overwrite=True)

    status = runs.run_status(topic_id)
    by_stage = {s.stage: s for s in status.stages}

    assert by_stage["outline"].stale is False
    assert by_stage["qa"].stale is False
    assert by_stage["repair"].stale is False
    assert by_stage["factcheck"].stale is False


def test_legacy_next_action_ignores_upstream_changes_after_repair_is_approved(
    tmp_path: Path,
) -> None:
    """PIN: staleness plays no part in the legacy next action.

    _next_action_legacy walks REQUIRED_STAGES through _pending_stage_action
    only -- it never consults StageStatus.stale and has no
    _stale_stage_rebuild_action arm. So re-approving the draft with different
    bytes under an already-approved repair leaves the run sitting on
    "finalize", where a guide-v1 run would be routed back to rebuild qa.
    """

    topic_id = "systems-thinking"
    runs = _create_legacy_run(tmp_path, topic_id)
    _drive_all_stages_to_approved(runs, topic_id)
    assert runs.run_status(topic_id).next_action.action == "finalize"

    result = runs.write_draft_prompt(topic_id, overwrite=True)
    result.response_path.write_text("# Systems Thinking (rewritten)\n", encoding="utf-8")
    runs.approve_stage(topic_id, "draft", overwrite=True)

    next_action = runs.run_status(topic_id).next_action
    assert (next_action.stage, next_action.action) == (None, "finalize")


def test_legacy_write_repair_prompt_accepts_a_changed_upstream(tmp_path: Path) -> None:
    """PIN: _require_current_upstream is inside write_repair_prompt's
    _is_guide_v1 branch, so a legacy run can recompile the repair prompt after
    the draft moved underneath the approved qa -- no ConfigError, unlike the
    guide-v1 path."""

    topic_id = "systems-thinking"
    runs = _create_legacy_run(tmp_path, topic_id)
    _drive_all_stages_to_approved(runs, topic_id)
    result = runs.write_draft_prompt(topic_id, overwrite=True)
    result.response_path.write_text("# Systems Thinking (rewritten)\n", encoding="utf-8")
    runs.approve_stage(topic_id, "draft", overwrite=True)

    prompt = runs.write_repair_prompt(topic_id, overwrite=True)

    assert prompt.stage == "repair"


def test_legacy_next_action_reports_the_first_pending_required_stage(
    tmp_path: Path,
) -> None:
    """PIN: the REQUIRED_STAGES walk short-circuits on the first pending stage.

    An approved-looking downstream stage planted out of order (draft approved
    while outline is untouched) does not pull the run forward: the loop still
    stops at outline.
    """

    topic_id = "systems-thinking"
    runs = _create_legacy_run(tmp_path, topic_id)
    _drive_spec_to_approved(runs, topic_id)
    draft_paths = runs.stage_paths(topic_id, "draft")
    draft_paths.prompt_path.parent.mkdir(parents=True, exist_ok=True)
    draft_paths.prompt_path.write_text("# planted draft prompt\n", encoding="utf-8")
    draft_paths.response_path.write_text("# draft\n", encoding="utf-8")
    draft_paths.approved_path.write_text("# draft\n", encoding="utf-8")

    next_action = runs.run_status(topic_id).next_action

    assert (next_action.stage, next_action.action) == ("outline", "write_prompt")
    by_stage = {s.stage: s for s in runs.run_status(topic_id).stages}
    assert by_stage["draft"].approved is True


# ---------------------------------------------------------------------------
# 3. Approve-time source binding: qa/repair response_approved events on a
#    legacy run carry no source_*_file_sha256 keys.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("stage", ["qa", "repair"])
def test_legacy_approve_stage_event_has_no_source_file_hashes(tmp_path: Path, stage: str) -> None:
    """PIN: guide-v1-only source binding never fires for legacy runs.

    approve_stage() only populates files["source_draft_file"] /
    ["source_qa_file"] / ["source_factcheck_file"] (and computes
    file_hashes via _prompt_bound_source_hashes) when
    self._is_guide_v1(topic_id) is true (runs.py, approve_stage, ~1310-1335).
    For legacy runs the files dict for qa/repair only ever contains
    "prompt_file" and "approved_file", so no source_*_file_sha256 key is
    ever written to the response_approved event.
    """

    topic_id = "systems-thinking"
    runs = _create_legacy_run(tmp_path, topic_id)
    _drive_spec_to_approved(runs, topic_id)
    _drive_outline_to_approved(runs, topic_id)
    _drive_draft_to_approved(runs, topic_id)
    _drive_qa_to_approved(runs, topic_id)
    if stage == "repair":
        _drive_repair_to_approved(runs, topic_id)

    manifest = runs.read_manifest(topic_id)
    events = [
        event
        for event in manifest["events"]
        if event.get("stage") == stage and event.get("action") == "response_approved"
    ]
    assert events, f"expected a response_approved event for stage {stage!r}"
    latest = events[-1]

    source_keys = {key for key in latest if key.startswith("source_") and key.endswith("_sha256")}
    assert source_keys == set()
    # And the ordinary (non-guide-v1) keys are still present.
    assert "prompt_file_sha256" in latest
    assert "approved_file_sha256" in latest


# ---------------------------------------------------------------------------
# 4. Legacy-only refusals.
# ---------------------------------------------------------------------------


def test_write_factcheck_prompt_on_legacy_run_raises_config_error(tmp_path: Path) -> None:
    topic_id = "systems-thinking"
    runs = _create_legacy_run(tmp_path, topic_id)

    with pytest.raises(ConfigError, match="legacy Markdown run"):
        runs.write_factcheck_prompt(topic_id)


def test_write_module_repair_prompt_on_legacy_run_raises_config_error(
    tmp_path: Path,
) -> None:
    """PIN: the module-scoped repair writer refuses legacy runs on its own
    _is_guide_v1 check, before any module id is validated."""

    topic_id = "systems-thinking"
    runs = _create_legacy_run(tmp_path, topic_id)

    with pytest.raises(ConfigError, match="legacy Markdown run"):
        runs.write_module_repair_prompt(topic_id, "loop-basics")


@pytest.mark.parametrize("phase", ["draft", "final"])
def test_validate_run_on_legacy_run_raises_config_error(tmp_path: Path, phase: str) -> None:
    """PIN: validate_run() refuses legacy runs outright.

    Observed message: "validation applies only to guide runs". Legacy
    Markdown runs have no structured guide document for validate_guide()
    to parse, so validate_run() (via validate_and_gate ->
    _compute_phase_report) raises ConfigError rather than attempting to
    validate Markdown prose.
    """

    topic_id = "systems-thinking"
    runs = _create_legacy_run(tmp_path, topic_id)
    _drive_all_stages_to_approved(runs, topic_id)

    with pytest.raises(ConfigError, match="validation applies only to guide runs"):
        runs.validate_run(topic_id, phase)


def test_content_contract_returns_legacy_markdown(tmp_path: Path) -> None:
    topic_id = "systems-thinking"
    runs = _create_legacy_run(tmp_path, topic_id)

    assert runs.content_contract(topic_id) == ContentContract.legacy_markdown()


def test_create_run_with_blueprint_on_legacy_run_raises(tmp_path: Path) -> None:
    """One representative case; the general rule is already covered elsewhere
    in tests/test_runs.py (test_legacy_markdown_runs_never_record_a_blueprint)."""

    topic_id = "systems-thinking"
    runs = _create_legacy_run(tmp_path, topic_id)

    with pytest.raises(ConfigError, match="legacy"):
        runs.create_run(topic_id, blueprint="conceptual-foundations")


# ---------------------------------------------------------------------------
# 5. finalize + export for a legacy run.
# ---------------------------------------------------------------------------


def test_legacy_finalize_writes_final_guide_md_and_flips_is_finalized(tmp_path: Path) -> None:
    topic_id = "systems-thinking"
    runs = _create_legacy_run(tmp_path, topic_id)
    _drive_all_stages_to_approved(runs, topic_id, repair_body="# Systems Thinking\n\nFinal body.\n")

    assert runs.is_finalized(topic_id) is False

    final_path = runs.finalize_run(topic_id)

    assert final_path == runs.final_path(topic_id)
    assert final_path.is_file()
    assert final_path.read_text(encoding="utf-8") == "# Systems Thinking\n\nFinal body.\n"
    assert runs.is_finalized(topic_id) is True
    assert runs.run_status(topic_id).next_action.action == "done"
    assert runs.run_status(topic_id).next_action.stage is None


def test_legacy_export_html_writes_export_file_referencing_final(tmp_path: Path) -> None:
    topic_id = "systems-thinking"
    runs = _create_legacy_run(tmp_path, topic_id)
    _drive_all_stages_to_approved(runs, topic_id)
    runs.finalize_run(topic_id)

    export_path = runs.export_run(topic_id, format="html")

    assert export_path.is_file()
    assert export_path == runs.export_path(topic_id, "html")
    manifest = runs.read_manifest(topic_id)
    exported_events = [
        event for event in manifest["events"] if event.get("stage") == "export" and event.get("action") == "exported"
    ]
    assert len(exported_events) == 1
    assert exported_events[0]["source_file"] == "final/guide.md"


def test_legacy_export_markdown_writes_export_file(tmp_path: Path) -> None:
    topic_id = "systems-thinking"
    runs = _create_legacy_run(tmp_path, topic_id)
    _drive_all_stages_to_approved(runs, topic_id)
    runs.finalize_run(topic_id)

    export_path = runs.export_run(topic_id, format="markdown")

    assert export_path.is_file()
    assert export_path.suffix == ".md"
    assert export_path != runs.final_path(topic_id)
