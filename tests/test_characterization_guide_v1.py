"""Characterization (golden) tests for ``RunStore`` on interactive-guide-v1 runs.

These tests pin CURRENT, OBSERVED behavior of the stage pipeline
(``spec -> outline -> draft -> qa -> factcheck -> repair``, then deterministic
``finalize``) ahead of a planned refactor that rewrites the stage dependency
chain as a data-driven graph walk. They exist purely as a regression net: the
refactor should reproduce every value pinned here bit-for-bit. They assert
what the code *does*, not what it "should" do -- several of the pinned facts
(noted inline) are subtle enough to be worth flagging in review.

``tests/`` has no ``__init__.py``, so this file cannot `from tests.test_runs
import ...`; the small set of fixtures/helpers it needs are copied here
verbatim from ``tests/test_runs.py`` instead of imported, to keep this file
self-contained and importable as a bare top-level test module.

Three things are pinned, across a matrix of run states:

1. ``RunStore.next_action(topic_id)`` -> ``(stage, action)`` (and, for a few
   states where the wording itself is load-bearing, ``detail``).
2. ``RunStore.run_status(topic_id).stages`` -> each stage's
   ``(prompt_written, response_ingested, approved, stale)``.
3. Approve-time and prompt-time source binding: which ``source_*_file_sha256``
   keys land on the manifest's ``prompt_written`` / ``response_approved``
   events for qa/factcheck/repair.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import pytest

from education_pipeline import (
    ConfigError,
    ContentContract,
    NextAction,
    RunStore,
    StageStatus,
    TopicStore,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "guides"

# --------------------------------------------------------------------------
# Fixtures and helpers copied from tests/test_runs.py (see module docstring
# for why this is a copy rather than an import).
# --------------------------------------------------------------------------

TOPIC_TOML = """\
schema_version = 1
id = "systems-thinking"
title = "Systems Thinking"
brief = "A public introduction to feedback loops."
audience = "early-career analysts"
goals = ["explain feedback loops"]
"""

VALID_SPEC_CONTRACT = {
    "contract_version": 1,
    "guide_schema_version": "1.0",
    "blueprint": "conceptual-foundations",
    "estimated_minutes": 30,
    "outcomes": [{"id": "identify-loop", "text": "Identify reinforcing and balancing feedback."}],
    "required_interactions": ["knowledge_check", "worked_reveal", "scenario", "reflection"],
    "personalization_requirements": ["Use gardening examples where they clarify the concept."],
    "source_policy": "Sources required for factual claims that are not common knowledge.",
}

VALID_OUTLINE_CONTRACT = {
    "contract_version": 1,
    "modules": {
        "feedback-loops": {
            "outcome_ids": ["identify-loop"],
            "estimated_minutes": 30,
            "interaction_types": ["knowledge_check", "worked_reveal"],
        },
    },
}


def _guide_spec_response(contract: dict | None = None) -> str:
    body = contract if contract is not None else VALID_SPEC_CONTRACT
    return (
        "# Course Specification: Systems Thinking\n\n"
        "## Learning Outcomes\n"
        "- Identify reinforcing and balancing feedback.\n\n"
        "```education-pipeline-contract+json\n"
        f"{json.dumps(body)}\n"
        "```\n"
    )


def _guide_outline_response(contract: dict | None = None) -> str:
    body = contract if contract is not None else VALID_OUTLINE_CONTRACT
    return (
        "# Course Outline: Systems Thinking\n\n"
        "## Modules\n"
        "1. Feedback loops\n\n"
        "```education-pipeline-outline+json\n"
        f"{json.dumps(body)}\n"
        "```\n"
    )


def _create_guide_run(tmp_path: Path, topic_id: str = "systems-thinking") -> RunStore:
    TopicStore(tmp_path).save_topic_toml(topic_id, TOPIC_TOML)
    runs = RunStore(tmp_path)
    runs.create_run(topic_id, content_contract=ContentContract.interactive_guide_v1())
    return runs


def _drive_guide_spec_to_approved(runs: RunStore, topic_id: str) -> None:
    result = runs.write_topic_spec_prompt(topic_id)
    result.response_path.write_text(_guide_spec_response(), encoding="utf-8")
    runs.approve_stage(topic_id, "spec")


def _drive_guide_outline_to_approved(runs: RunStore, topic_id: str) -> None:
    result = runs.write_outline_prompt(topic_id)
    result.response_path.write_text(_guide_outline_response(), encoding="utf-8")
    runs.approve_stage(topic_id, "outline")


GUIDE_FIXTURE = (FIXTURES_DIR / "feedback-loops.guide.json").read_text(encoding="utf-8")

FACTCHECK_FIXTURE = """# Fact-Check Report: Systems Thinking

## Verdict
pass — no material factual errors.

## Claim Inventory
1. "Feedback loops couple stocks and flows" — module feedback-loops, type: definition

## Findings
(none)

## Unsupported Or Uncertain Claims
(none)

## Repair Instructions
(none)
"""


def _drive_guide_to_draft_approved(
    runs: RunStore, topic_id: str, draft_body: str | None = None
) -> None:
    _drive_guide_spec_to_approved(runs, topic_id)
    _drive_guide_outline_to_approved(runs, topic_id)
    draft = runs.write_draft_prompt(topic_id)
    draft.response_path.write_text(
        draft_body if draft_body is not None else GUIDE_FIXTURE, encoding="utf-8"
    )
    runs.approve_stage(topic_id, "draft")


def _drive_guide_through_qa(
    runs: RunStore, topic_id: str, *, draft_body: str | None = None
) -> None:
    _drive_guide_to_draft_approved(runs, topic_id, draft_body)
    runs.validate_run(topic_id, "draft")
    qa = runs.write_qa_prompt(topic_id)
    qa.response_path.write_text("# QA findings\n\nNo major issues.\n", encoding="utf-8")
    runs.approve_stage(topic_id, "qa")


def _drive_guide_through_factcheck(
    runs: RunStore, topic_id: str, *, draft_body: str | None = None
) -> None:
    _drive_guide_through_qa(runs, topic_id, draft_body=draft_body)
    fc = runs.write_factcheck_prompt(topic_id)
    fc.response_path.write_text(FACTCHECK_FIXTURE, encoding="utf-8")
    runs.approve_stage(topic_id, "factcheck")


def _drive_guide_to_finalize_ready(
    runs: RunStore,
    topic_id: str,
    *,
    draft_body: str | None = None,
    repair_body: str | None = None,
) -> None:
    _drive_guide_through_factcheck(runs, topic_id, draft_body=draft_body)
    repair = runs.write_repair_prompt(topic_id)
    body = repair_body if repair_body is not None else (
        draft_body if draft_body is not None else GUIDE_FIXTURE
    )
    repair.response_path.write_text(body, encoding="utf-8")
    runs.approve_stage(topic_id, "repair")
    runs.validate_run(topic_id, "final")


def _plant_pre_feature_repair(runs: RunStore, topic_id: str) -> None:
    """Plant a pre-feature approved repair: no factcheck artifacts anywhere.

    Copied from ``tests/test_runs.py``'s helper of the same name -- the
    lowest-level way to reproduce a run created before the factcheck stage
    existed (QA approved, repair approved, nothing factcheck-shaped on disk).
    """

    repair_paths = runs.stage_paths(topic_id, "repair")
    repair_paths.prompt_path.parent.mkdir(parents=True, exist_ok=True)
    repair_paths.prompt_path.write_text("# planted repair prompt\n", encoding="utf-8")
    repair_paths.response_path.write_text(GUIDE_FIXTURE, encoding="utf-8")
    repair_paths.approved_path.write_text(GUIDE_FIXTURE, encoding="utf-8")
    runs._append_event(
        topic_id,
        stage="repair",
        action="response_approved",
        files={
            "prompt_file": repair_paths.prompt_path,
            "approved_file": repair_paths.approved_path,
            "source_draft_file": runs.stage_paths(topic_id, "draft").approved_path,
            "source_qa_file": runs.stage_paths(topic_id, "qa").approved_path,
        },
    )


def _edit_course_description(guide_json: str, new_description: str) -> str:
    data = json.loads(guide_json)
    data["course"]["description"] = new_description
    return json.dumps(data)


TID = "systems-thinking"

STAGE_ORDER = ("spec", "outline", "draft", "qa", "factcheck", "repair", "audit")


def _stage_map(runs: RunStore, topic_id: str) -> dict[str, StageStatus]:
    return {status.stage: status for status in runs.run_status(topic_id).stages}


def _latest_event(runs: RunStore, topic_id: str, stage: str, action: str) -> dict | None:
    manifest = runs.read_manifest(topic_id)
    for event in reversed(manifest["events"]):
        if event.get("stage") == stage and event.get("action") == action:
            return event
    return None


def _source_keys(event: dict) -> set[str]:
    return {k for k in event if k.startswith("source_") and k.endswith("_sha256")}


# --------------------------------------------------------------------------
# Part 1: the full linear happy-path walk, asserting NextAction and every
# stage's StageStatus at each milestone. Written as one continuous test
# (rather than parametrized) because each step depends on workspace state
# left behind by the previous one.
# --------------------------------------------------------------------------


def test_linear_progression_next_action_and_stage_status(tmp_path: Path) -> None:
    runs = _create_guide_run(tmp_path, TID)

    def assert_state(
        expected_stage: str | None,
        expected_action: str,
        expected_flags: dict[str, tuple[bool, bool, bool, bool]],
    ) -> None:
        """expected_flags: stage -> (prompt_written, response_ingested, approved, stale)."""

        status = runs.run_status(TID)
        assert (status.next_action.stage, status.next_action.action) == (
            expected_stage,
            expected_action,
        )
        by_stage = {s.stage: s for s in status.stages}
        for stage, (pw, ri, ap, st) in expected_flags.items():
            actual = by_stage[stage]
            assert (
                actual.prompt_written,
                actual.response_ingested,
                actual.approved,
                actual.stale,
            ) == (pw, ri, ap, st), f"stage {stage!r} mismatch: {actual}"

    NONE4 = (False, False, False, False)

    # Fresh run: nothing written anywhere.
    assert_state(
        "spec",
        "write_prompt",
        {s: NONE4 for s in STAGE_ORDER},
    )

    spec = runs.write_topic_spec_prompt(TID)
    assert_state(
        "spec",
        "save_response",
        {"spec": (True, False, False, False), "outline": NONE4, "draft": NONE4},
    )

    spec.response_path.write_text(_guide_spec_response(), encoding="utf-8")
    assert_state(
        "spec",
        "approve",
        {"spec": (True, True, False, False)},
    )

    runs.approve_stage(TID, "spec")
    assert_state(
        "outline",
        "write_prompt",
        {"spec": (True, True, True, False), "outline": NONE4},
    )

    outline = runs.write_outline_prompt(TID)
    assert_state("outline", "save_response", {"outline": (True, False, False, False)})

    outline.response_path.write_text(_guide_outline_response(), encoding="utf-8")
    assert_state("outline", "approve", {"outline": (True, True, False, False)})

    runs.approve_stage(TID, "outline")
    assert_state(
        "draft",
        "write_prompt",
        {"outline": (True, True, True, False), "draft": NONE4},
    )

    draft = runs.write_draft_prompt(TID)
    assert_state("draft", "save_response", {"draft": (True, False, False, False)})

    draft.response_path.write_text(GUIDE_FIXTURE, encoding="utf-8")
    assert_state("draft", "approve", {"draft": (True, True, False, False)})

    runs.approve_stage(TID, "draft")
    # Draft approved but not yet validated -> "validate" (not "write_prompt"
    # for qa), even though draft's own StageStatus already reads approved.
    assert_state("draft", "validate", {"draft": (True, True, True, False)})

    runs.validate_run(TID, "draft")
    assert_state(
        "qa",
        "write_prompt",
        {"draft": (True, True, True, False), "qa": NONE4},
    )

    qa = runs.write_qa_prompt(TID)
    assert_state("qa", "save_response", {"qa": (True, False, False, False)})

    qa.response_path.write_text("# QA findings\n\nNo major issues.\n", encoding="utf-8")
    assert_state("qa", "approve", {"qa": (True, True, False, False)})

    runs.approve_stage(TID, "qa")
    assert_state(
        "factcheck",
        "write_prompt",
        {"qa": (True, True, True, False), "factcheck": NONE4},
    )

    fc = runs.write_factcheck_prompt(TID)
    assert_state("factcheck", "save_response", {"factcheck": (True, False, False, False)})

    fc.response_path.write_text(FACTCHECK_FIXTURE, encoding="utf-8")
    assert_state("factcheck", "approve", {"factcheck": (True, True, False, False)})

    runs.approve_stage(TID, "factcheck")
    assert_state(
        "repair",
        "write_prompt",
        {"factcheck": (True, True, True, False), "repair": NONE4},
    )

    repair = runs.write_repair_prompt(TID)
    assert_state("repair", "save_response", {"repair": (True, False, False, False)})

    repair.response_path.write_text(GUIDE_FIXTURE, encoding="utf-8")
    assert_state("repair", "approve", {"repair": (True, True, False, False)})

    runs.approve_stage(TID, "repair")
    assert_state("repair", "validate", {"repair": (True, True, True, False)})

    runs.validate_run(TID, "final")
    assert_state(None, "finalize", {"repair": (True, True, True, False)})

    runs.finalize_run(TID)
    assert_state(None, "done", {"repair": (True, True, True, False)})

    # The audit (optional) stage is never touched by any of the above and
    # reads as fully untouched throughout the entire guide-v1 pipeline.
    final_status = _stage_map(runs, TID)
    assert (
        final_status["audit"].prompt_written,
        final_status["audit"].response_ingested,
        final_status["audit"].approved,
        final_status["audit"].stale,
    ) == NONE4


# --------------------------------------------------------------------------
# Part 2: next_action for standalone/branch states, table-driven.
# --------------------------------------------------------------------------


def _build_malformed_draft(runs: RunStore, topic_id: str) -> None:
    _drive_guide_to_draft_approved(runs, topic_id, draft_body="not json")
    runs.validate_run(topic_id, "draft")


def _build_grandfathered_repair_no_factcheck(runs: RunStore, topic_id: str) -> None:
    _drive_guide_through_qa(runs, topic_id)
    _plant_pre_feature_repair(runs, topic_id)


def _build_grandfathered_stale_routes_through_factcheck(runs: RunStore, topic_id: str) -> None:
    _build_grandfathered_repair_no_factcheck(runs, topic_id)
    qa_paths = runs.stage_paths(topic_id, "qa")
    qa_paths.response_path.write_text("# QA findings\n\nChanged.\n", encoding="utf-8")
    runs.approve_stage(topic_id, "qa", overwrite=True)


def _build_full_chain_stale_after_draft_reapprove(runs: RunStore, topic_id: str) -> None:
    _drive_guide_to_finalize_ready(runs, topic_id)
    draft_paths = runs.stage_paths(topic_id, "draft")
    draft_paths.response_path.write_text(GUIDE_FIXTURE + "\n", encoding="utf-8")
    runs.approve_stage(topic_id, "draft", overwrite=True)


def _build_stale_after_qa_rebuild(runs: RunStore, topic_id: str) -> None:
    _build_full_chain_stale_after_draft_reapprove(runs, topic_id)
    qa = runs.write_qa_prompt(topic_id, overwrite=True)
    qa.response_path.write_text("# QA findings\n\nRebuilt.\n", encoding="utf-8")
    runs.approve_stage(topic_id, "qa", overwrite=True)


def _build_stale_after_factcheck_rebuild(runs: RunStore, topic_id: str) -> None:
    _build_stale_after_qa_rebuild(runs, topic_id)
    fc = runs.write_factcheck_prompt(topic_id, overwrite=True)
    fc.response_path.write_text(FACTCHECK_FIXTURE + "\n", encoding="utf-8")
    runs.approve_stage(topic_id, "factcheck", overwrite=True)


def _build_stale_after_repair_rebuild(runs: RunStore, topic_id: str) -> None:
    _build_stale_after_factcheck_rebuild(runs, topic_id)
    repair = runs.write_repair_prompt(topic_id, overwrite=True)
    repair.response_path.write_text(GUIDE_FIXTURE + "\n", encoding="utf-8")
    runs.approve_stage(topic_id, "repair", overwrite=True)


def _build_reapprove_only_qa(runs: RunStore, topic_id: str) -> None:
    _drive_guide_to_finalize_ready(runs, topic_id)
    qa_paths = runs.stage_paths(topic_id, "qa")
    qa_paths.response_path.write_text("# QA findings\n\nChanged only qa.\n", encoding="utf-8")
    runs.approve_stage(topic_id, "qa", overwrite=True)


def _build_reapprove_only_factcheck(runs: RunStore, topic_id: str) -> None:
    _drive_guide_to_finalize_ready(runs, topic_id)
    fc_paths = runs.stage_paths(topic_id, "factcheck")
    fc_paths.response_path.write_text(FACTCHECK_FIXTURE + "\n# touch\n", encoding="utf-8")
    runs.approve_stage(topic_id, "factcheck", overwrite=True)


def _build_stale_qa_prompt_rebuilt(runs: RunStore, topic_id: str) -> None:
    """Stale qa whose prompt has already been rewritten against the new draft."""

    _build_full_chain_stale_after_draft_reapprove(runs, topic_id)
    runs.write_qa_prompt(topic_id, overwrite=True)


def _build_stale_factcheck_prompt_rebuilt(runs: RunStore, topic_id: str) -> None:
    _build_stale_after_qa_rebuild(runs, topic_id)
    runs.write_factcheck_prompt(topic_id, overwrite=True)


def _build_stale_repair_prompt_rebuilt(runs: RunStore, topic_id: str) -> None:
    _build_stale_after_factcheck_rebuild(runs, topic_id)
    runs.write_repair_prompt(topic_id, overwrite=True)


def _build_qa_changed_then_factcheck_rebuilt(runs: RunStore, topic_id: str) -> None:
    """Only qa changed, and factcheck was rebuilt against it -- so repair is the
    one stale stage, and its prompt event still carries the *old* qa hash while
    its draft hash is current."""

    _build_reapprove_only_qa(runs, topic_id)
    fc = runs.write_factcheck_prompt(topic_id, overwrite=True)
    fc.response_path.write_text(FACTCHECK_FIXTURE + "\n", encoding="utf-8")
    runs.approve_stage(topic_id, "factcheck", overwrite=True)


def _build_grandfathered_then_factcheck_approved(runs: RunStore, topic_id: str) -> None:
    """A pre-feature (planted) repair, with a factcheck approved afterwards."""

    _build_grandfathered_repair_no_factcheck(runs, topic_id)
    fc = runs.write_factcheck_prompt(topic_id)
    fc.response_path.write_text(FACTCHECK_FIXTURE, encoding="utf-8")
    runs.approve_stage(topic_id, "factcheck")


def _plant_repair_approval_event(
    runs: RunStore, topic_id: str, *, source_labels: tuple[str, ...]
) -> None:
    """Plant an approved repair whose event records only ``source_labels``.

    ``_plant_pre_feature_repair`` records draft+qa; this lower-level variant
    lets a case record *fewer* source hashes, which is how a genuinely older
    manifest (written before a given source was bound) reads on disk.
    """

    paths = runs.stage_paths(topic_id, "repair")
    paths.prompt_path.parent.mkdir(parents=True, exist_ok=True)
    paths.prompt_path.write_text("# planted repair prompt\n", encoding="utf-8")
    paths.response_path.write_text(GUIDE_FIXTURE, encoding="utf-8")
    paths.approved_path.write_text(GUIDE_FIXTURE, encoding="utf-8")
    files: dict[str, Path] = {
        "prompt_file": paths.prompt_path,
        "approved_file": paths.approved_path,
    }
    for label in source_labels:
        files[f"source_{label}_file"] = runs.stage_paths(topic_id, label).approved_path
    runs._append_event(
        topic_id, stage="repair", action="response_approved", files=files
    )


def _reapprove_draft_with_new_bytes(runs: RunStore, topic_id: str) -> None:
    paths = runs.stage_paths(topic_id, "draft")
    paths.response_path.write_text(GUIDE_FIXTURE + "\n", encoding="utf-8")
    runs.approve_stage(topic_id, "draft", overwrite=True)


def _reapprove_qa_with_new_bytes(runs: RunStore, topic_id: str) -> None:
    paths = runs.stage_paths(topic_id, "qa")
    paths.response_path.write_text("# QA findings\n\nChanged.\n", encoding="utf-8")
    runs.approve_stage(topic_id, "qa", overwrite=True)


def _build_planted_repair_no_sources_then_draft_change(
    runs: RunStore, topic_id: str
) -> None:
    _drive_guide_through_qa(runs, topic_id)
    _plant_repair_approval_event(runs, topic_id, source_labels=())
    _reapprove_draft_with_new_bytes(runs, topic_id)


def _build_planted_repair_draft_source_only_then_qa_change(
    runs: RunStore, topic_id: str
) -> None:
    _drive_guide_through_qa(runs, topic_id)
    _plant_repair_approval_event(runs, topic_id, source_labels=("draft",))
    _reapprove_qa_with_new_bytes(runs, topic_id)


def _build_approved_draft_deleted(runs: RunStore, topic_id: str) -> None:
    _drive_guide_to_finalize_ready(runs, topic_id)
    runs.stage_paths(topic_id, "draft").approved_path.unlink()


def _build_approved_qa_deleted(runs: RunStore, topic_id: str) -> None:
    _drive_guide_to_finalize_ready(runs, topic_id)
    runs.stage_paths(topic_id, "qa").approved_path.unlink()


def _build_approved_factcheck_deleted(runs: RunStore, topic_id: str) -> None:
    _drive_guide_to_finalize_ready(runs, topic_id)
    runs.stage_paths(topic_id, "factcheck").approved_path.unlink()


@dataclass(frozen=True)
class NextActionCase:
    name: str
    build: Callable[[RunStore, str], None]
    stage: str | None
    action: str


NEXT_ACTION_CASES = [
    NextActionCase(
        "malformed_draft_resolve_findings",
        _build_malformed_draft,
        "draft",
        "resolve_findings",
    ),
    NextActionCase(
        "grandfathered_repair_skips_factcheck",
        _build_grandfathered_repair_no_factcheck,
        "repair",
        "validate",
    ),
    NextActionCase(
        "grandfathered_stale_repair_routes_through_factcheck",
        _build_grandfathered_stale_routes_through_factcheck,
        "factcheck",
        "write_prompt",
    ),
    NextActionCase(
        "full_chain_stale_after_draft_reapprove_routes_to_qa",
        _build_full_chain_stale_after_draft_reapprove,
        "qa",
        "write_prompt",
    ),
    NextActionCase(
        "stale_after_qa_rebuild_routes_to_factcheck",
        _build_stale_after_qa_rebuild,
        "factcheck",
        "write_prompt",
    ),
    NextActionCase(
        "stale_after_factcheck_rebuild_routes_to_repair",
        _build_stale_after_factcheck_rebuild,
        "repair",
        "write_prompt",
    ),
    NextActionCase(
        # Surprising: rebuilding repair with only a trailing-newline byte
        # diff leaves the *final* validation report "current" (report_state
        # keys off a semantic guide hash, not raw bytes -- see
        # education_pipeline/runs.py:2526-2596's report_state), even though
        # the qa/factcheck/repair StageStatus.stale check keys off raw file
        # bytes (runs.py:4027-4065). So the run reads as ready to finalize
        # immediately, with no further "validate" step demanded.
        "stale_after_repair_rebuild_goes_straight_to_finalize",
        _build_stale_after_repair_rebuild,
        None,
        "finalize",
    ),
    NextActionCase(
        "reapprove_only_qa_routes_to_factcheck",
        _build_reapprove_only_qa,
        "factcheck",
        "write_prompt",
    ),
    NextActionCase(
        "reapprove_only_factcheck_routes_to_repair",
        _build_reapprove_only_factcheck,
        "repair",
        "write_prompt",
    ),
    # --- _stale_stage_rebuild_action's needs_prompt=False arm -------------
    # Once the stale stage's prompt has been rewritten (so its prompt_written
    # event records the *current* upstream hashes), the advertised rebuild
    # action drops from "write_prompt" to "save_response" -- separately for
    # each stage, because each checks a different depth of sources (qa:
    # draft; factcheck: draft+qa; repair: draft+qa+factcheck).
    #
    # Surprising: "save_response" is advertised even though the stage's
    # previous response file is still on disk (StageStatus.response_ingested
    # is True in all three states) -- rewriting the prompt does not clear it,
    # and _stale_stage_rebuild_action has no "approve" arm at all.
    NextActionCase(
        "stale_qa_with_rebuilt_prompt_wants_save_response",
        _build_stale_qa_prompt_rebuilt,
        "qa",
        "save_response",
    ),
    NextActionCase(
        "stale_factcheck_with_rebuilt_prompt_wants_save_response",
        _build_stale_factcheck_prompt_rebuilt,
        "factcheck",
        "save_response",
    ),
    NextActionCase(
        "stale_repair_with_rebuilt_prompt_wants_save_response",
        _build_stale_repair_prompt_rebuilt,
        "repair",
        "save_response",
    ),
    NextActionCase(
        # repair's *qa*-depth check in isolation: the draft never moved, and
        # factcheck was rebuilt, so only repair's recorded qa hash is stale.
        # Reaching "write_prompt" here means the qa arm of the rebuild
        # decision fired (the draft arm cannot have).
        "stale_repair_from_qa_only_change_wants_write_prompt",
        _build_qa_changed_then_factcheck_rebuilt,
        "repair",
        "write_prompt",
    ),
    NextActionCase(
        # The grandfather skip stops applying once factcheck is approved, but
        # nothing changes: the planted repair event records no factcheck
        # source, so repair never goes stale and still routes to "validate".
        "grandfathered_repair_unchanged_after_factcheck_approved",
        _build_grandfathered_then_factcheck_approved,
        "repair",
        "validate",
    ),
]


@pytest.mark.parametrize("case", NEXT_ACTION_CASES, ids=lambda c: c.name)
def test_next_action_branch_states(tmp_path: Path, case: NextActionCase) -> None:
    runs = _create_guide_run(tmp_path, TID)
    case.build(runs, TID)
    next_action = runs.run_status(TID).next_action
    assert (next_action.stage, next_action.action) == (case.stage, case.action)


def test_grandfathered_stale_rebuild_action_is_actually_performable(tmp_path: Path) -> None:
    """The routed-to action for the grandfathered-stale case must not dead-end."""

    runs = _create_guide_run(tmp_path, TID)
    _build_grandfathered_stale_routes_through_factcheck(runs, TID)
    # This must not raise: write_repair_prompt requires an approved
    # factcheck, so the advertised "write the factcheck prompt" action has to
    # be real, not just advertised.
    runs.write_factcheck_prompt(TID)


# --------------------------------------------------------------------------
# Part 3: stale flags across the branch states, table-driven.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class StaleCase:
    name: str
    build: Callable[[RunStore, str], None]
    stale: dict[str, bool]  # only the stages worth asserting for this case


STALE_CASES = [
    StaleCase(
        "grandfathered_repair_not_stale_before_qa_change",
        _build_grandfathered_repair_no_factcheck,
        {"qa": False, "repair": False},
    ),
    StaleCase(
        "grandfathered_repair_stale_after_qa_change",
        _build_grandfathered_stale_routes_through_factcheck,
        {"qa": False, "repair": True},
    ),
    StaleCase(
        "full_chain_stale_after_draft_reapprove",
        _build_full_chain_stale_after_draft_reapprove,
        {"draft": False, "qa": True, "factcheck": True, "repair": True},
    ),
    StaleCase(
        "stale_after_qa_rebuild_clears_qa_only",
        _build_stale_after_qa_rebuild,
        {"draft": False, "qa": False, "factcheck": True, "repair": True},
    ),
    StaleCase(
        "stale_after_factcheck_rebuild_clears_factcheck_too",
        _build_stale_after_factcheck_rebuild,
        {"draft": False, "qa": False, "factcheck": False, "repair": True},
    ),
    StaleCase(
        "stale_after_repair_rebuild_clears_everything",
        _build_stale_after_repair_rebuild,
        {"draft": False, "qa": False, "factcheck": False, "repair": False},
    ),
    StaleCase(
        "reapprove_only_qa_leaves_draft_current",
        _build_reapprove_only_qa,
        {"draft": False, "qa": False, "factcheck": True, "repair": True},
    ),
    StaleCase(
        "reapprove_only_factcheck_only_repair_goes_stale",
        _build_reapprove_only_factcheck,
        {"draft": False, "qa": False, "factcheck": False, "repair": True},
    ),
    StaleCase(
        "qa_changed_then_factcheck_rebuilt_leaves_only_repair_stale",
        _build_qa_changed_then_factcheck_rebuilt,
        {"draft": False, "qa": False, "factcheck": False, "repair": True},
    ),
    StaleCase(
        "grandfathered_repair_stays_current_after_factcheck_approved",
        _build_grandfathered_then_factcheck_approved,
        {"qa": False, "factcheck": False, "repair": False},
    ),
    # --- a recorded source file that has vanished from disk reads as stale --
    # (_stage_upstream_stale's `if not <source>_path.is_file(): return True`
    # arms, one per depth). The deleted stage itself reports approved=False,
    # so its own `stale` flag drops back to False.
    StaleCase(
        "deleting_the_approved_draft_makes_the_whole_chain_stale",
        _build_approved_draft_deleted,
        {"draft": False, "qa": True, "factcheck": True, "repair": True},
    ),
    StaleCase(
        "deleting_the_approved_qa_makes_factcheck_and_repair_stale",
        _build_approved_qa_deleted,
        {"draft": False, "qa": False, "factcheck": True, "repair": True},
    ),
    StaleCase(
        "deleting_the_approved_factcheck_makes_only_repair_stale",
        _build_approved_factcheck_deleted,
        {"draft": False, "qa": False, "factcheck": False, "repair": True},
    ),
    # --- absent recorded hashes are grandfathered, never stale -------------
    StaleCase(
        # An approval event with no source_* hashes at all: the draft changes
        # underneath it and it still reads current, while qa -- which did
        # record the draft hash -- goes stale off the same edit.
        "planted_repair_without_source_hashes_never_goes_stale",
        _build_planted_repair_no_sources_then_draft_change,
        {"qa": True, "repair": False},
    ),
    StaleCase(
        # Records the draft source but not qa: a qa change is invisible to it
        # (the first absent hash short-circuits the whole check).
        "planted_repair_without_qa_hash_ignores_a_qa_change",
        _build_planted_repair_draft_source_only_then_qa_change,
        {"qa": False, "repair": False},
    ),
]


@pytest.mark.parametrize("case", STALE_CASES, ids=lambda c: c.name)
def test_stale_flags_across_branch_states(tmp_path: Path, case: StaleCase) -> None:
    runs = _create_guide_run(tmp_path, TID)
    case.build(runs, TID)
    by_stage = _stage_map(runs, TID)
    for stage, expected in case.stale.items():
        assert by_stage[stage].stale is expected, f"stage {stage!r} stale mismatch"


def test_an_absent_earlier_hash_hides_a_recorded_later_one(tmp_path: Path) -> None:
    """The first absent recorded hash abandons the *whole* walk, so a hash
    recorded for a later source is never compared at all.

    ``planted_repair_without_qa_hash_ignores_a_qa_change`` above pins the
    common shape (an absent hash with nothing recorded behind it); this pins
    the ordering itself. The planted repair records qa but not draft -- the
    draft hash is checked first, is absent, and the check returns "current"
    before it ever reaches the recorded qa hash, even though the approved qa
    has since changed underneath it.
    """

    runs = _create_guide_run(tmp_path, TID)
    _drive_guide_through_qa(runs, TID)
    _plant_repair_approval_event(runs, TID, source_labels=("qa",))
    _reapprove_qa_with_new_bytes(runs, TID)
    assert _stage_map(runs, TID)["repair"].stale is False


# --------------------------------------------------------------------------
# Part 4: approve-time and prompt-time source binding on the manifest.
# --------------------------------------------------------------------------


def test_qa_prompt_written_binds_only_draft_source(tmp_path: Path) -> None:
    runs = _create_guide_run(tmp_path, TID)
    _drive_guide_through_qa(runs, TID)
    event = _latest_event(runs, TID, "qa", "prompt_written")
    assert event is not None
    assert _source_keys(event) == {"source_draft_file_sha256"}


def test_qa_response_approved_binds_only_draft_source(tmp_path: Path) -> None:
    runs = _create_guide_run(tmp_path, TID)
    _drive_guide_through_qa(runs, TID)
    event = _latest_event(runs, TID, "qa", "response_approved")
    assert event is not None
    assert _source_keys(event) == {"source_draft_file_sha256"}


def test_factcheck_prompt_written_binds_draft_and_qa_sources(tmp_path: Path) -> None:
    runs = _create_guide_run(tmp_path, TID)
    _drive_guide_through_qa(runs, TID)
    runs.write_factcheck_prompt(TID)
    event = _latest_event(runs, TID, "factcheck", "prompt_written")
    assert event is not None
    assert _source_keys(event) == {"source_draft_file_sha256", "source_qa_file_sha256"}


def test_factcheck_response_approved_binds_draft_and_qa_sources(tmp_path: Path) -> None:
    runs = _create_guide_run(tmp_path, TID)
    _drive_guide_through_factcheck(runs, TID)
    event = _latest_event(runs, TID, "factcheck", "response_approved")
    assert event is not None
    assert _source_keys(event) == {"source_draft_file_sha256", "source_qa_file_sha256"}


def test_repair_prompt_written_binds_draft_qa_and_factcheck_sources(tmp_path: Path) -> None:
    runs = _create_guide_run(tmp_path, TID)
    _drive_guide_through_factcheck(runs, TID)
    runs.write_repair_prompt(TID)
    event = _latest_event(runs, TID, "repair", "prompt_written")
    assert event is not None
    assert _source_keys(event) == {
        "source_draft_file_sha256",
        "source_qa_file_sha256",
        "source_factcheck_file_sha256",
    }


def test_repair_response_approved_binds_all_three_sources_when_factcheck_exists(
    tmp_path: Path,
) -> None:
    runs = _create_guide_run(tmp_path, TID)
    _drive_guide_to_finalize_ready(runs, TID)
    event = _latest_event(runs, TID, "repair", "response_approved")
    assert event is not None
    assert _source_keys(event) == {
        "source_draft_file_sha256",
        "source_qa_file_sha256",
        "source_factcheck_file_sha256",
    }


def test_repair_response_approved_omits_factcheck_source_when_absent(tmp_path: Path) -> None:
    """A repair approved through the live API (not manifest-planted) with no
    approved factcheck on disk never gets a source_factcheck_file key at
    all -- not a null/None value, the key is simply not written."""

    runs = _create_guide_run(tmp_path, TID)
    _drive_guide_through_qa(runs, TID)
    repair_paths = runs.stage_paths(TID, "repair")
    repair_paths.prompt_path.parent.mkdir(parents=True, exist_ok=True)
    repair_paths.prompt_path.write_text("# planted prompt\n", encoding="utf-8")
    repair_paths.response_path.write_text(GUIDE_FIXTURE, encoding="utf-8")
    runs.approve_stage(TID, "repair")
    event = _latest_event(runs, TID, "repair", "response_approved")
    assert event is not None
    assert _source_keys(event) == {"source_draft_file_sha256", "source_qa_file_sha256"}
    assert "source_factcheck_file_sha256" not in event


def test_repair_response_approved_omits_the_factcheck_path_key_too(tmp_path: Path) -> None:
    """The absent-factcheck rule drops the entire binding, not just its hash.

    ``_append_event`` writes a ``<label>`` path key for every bound file but a
    ``<label>_sha256`` key only when the file exists, so binding an absent
    factcheck would still leave a dangling ``source_factcheck_file`` path on
    the event. It does not: neither key is written.
    """

    runs = _create_guide_run(tmp_path, TID)
    _drive_guide_through_qa(runs, TID)
    repair_paths = runs.stage_paths(TID, "repair")
    repair_paths.prompt_path.parent.mkdir(parents=True, exist_ok=True)
    repair_paths.prompt_path.write_text("# planted prompt\n", encoding="utf-8")
    repair_paths.response_path.write_text(GUIDE_FIXTURE, encoding="utf-8")
    runs.approve_stage(TID, "repair")
    event = _latest_event(runs, TID, "repair", "response_approved")
    assert event is not None
    assert {
        key for key in event if key.startswith("source_") and not key.endswith("_sha256")
    } == {"source_draft_file", "source_qa_file"}


def test_grandfathered_planted_repair_event_has_no_factcheck_source(tmp_path: Path) -> None:
    """Pin the shape of the ``_plant_pre_feature_repair`` fixture itself: the
    manifest event it writes carries draft+qa sources and no factcheck
    source, matching a genuine pre-feature run."""

    runs = _create_guide_run(tmp_path, TID)
    _build_grandfathered_repair_no_factcheck(runs, TID)
    event = _latest_event(runs, TID, "repair", "response_approved")
    assert event is not None
    assert _source_keys(event) == {"source_draft_file_sha256", "source_qa_file_sha256"}


def test_module_repair_prompt_written_binds_draft_qa_and_factcheck_sources(
    tmp_path: Path,
) -> None:
    """The module-scoped repair prompt binds the same three sources as the
    whole-guide repair prompt (plus the module scope itself)."""

    runs = _create_guide_run(tmp_path, TID)
    _drive_guide_through_factcheck(runs, TID)
    runs.write_module_repair_prompt(TID, "loop-basics")
    event = _latest_event(runs, TID, "repair", "prompt_written")
    assert event is not None
    assert _source_keys(event) == {
        "source_draft_file_sha256",
        "source_qa_file_sha256",
        "source_factcheck_file_sha256",
    }
    assert event["repair_module"] == "loop-basics"


def test_approval_records_the_prompt_time_upstream_hash_not_the_current_one(
    tmp_path: Path,
) -> None:
    """An upstream stage reapproved *after* a prompt was written never reaches
    the model, so the approval keys itself to the prompt's (older) upstream
    bytes -- and the stage therefore reads stale the instant it is approved."""

    runs = _create_guide_run(tmp_path, TID)
    _drive_guide_through_qa(runs, TID)
    qa = runs.write_qa_prompt(TID, overwrite=True)
    draft_paths = runs.stage_paths(TID, "draft")
    prompt_time_draft_sha = hashlib.sha256(
        draft_paths.approved_path.read_bytes()
    ).hexdigest()

    draft_paths.response_path.write_text(GUIDE_FIXTURE + "\n", encoding="utf-8")
    runs.approve_stage(TID, "draft", overwrite=True)
    current_draft_sha = hashlib.sha256(draft_paths.approved_path.read_bytes()).hexdigest()
    assert current_draft_sha != prompt_time_draft_sha

    qa.response_path.write_text("# QA findings\n\nSecond pass.\n", encoding="utf-8")
    runs.approve_stage(TID, "qa", overwrite=True)

    event = _latest_event(runs, TID, "qa", "response_approved")
    assert event is not None
    assert event["source_draft_file_sha256"] == prompt_time_draft_sha
    assert _stage_map(runs, TID)["qa"].stale is True


def test_approval_without_a_prompt_event_falls_back_to_current_file_hashes(
    tmp_path: Path,
) -> None:
    """With no prompt_written event to bind to (a planted prompt file), the
    approval hashes whatever is on disk -- so the stage reads current."""

    runs = _create_guide_run(tmp_path, TID)
    _drive_guide_through_qa(runs, TID)
    repair_paths = runs.stage_paths(TID, "repair")
    repair_paths.prompt_path.parent.mkdir(parents=True, exist_ok=True)
    repair_paths.prompt_path.write_text("# planted prompt\n", encoding="utf-8")
    repair_paths.response_path.write_text(GUIDE_FIXTURE, encoding="utf-8")
    runs.approve_stage(TID, "repair")

    event = _latest_event(runs, TID, "repair", "response_approved")
    assert event is not None
    draft_sha = hashlib.sha256(
        runs.stage_paths(TID, "draft").approved_path.read_bytes()
    ).hexdigest()
    assert event["source_draft_file_sha256"] == draft_sha
    assert _stage_map(runs, TID)["repair"].stale is False


# --------------------------------------------------------------------------
# Part 5: the public prompt writers refuse to compile against a stale
# upstream stage (the guard _next_action_* already routes callers around).
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class StaleUpstreamRefusalCase:
    name: str
    build: Callable[[RunStore, str], None]
    call: Callable[[RunStore, str], object]
    message: str


STALE_UPSTREAM_REFUSAL_CASES = [
    StaleUpstreamRefusalCase(
        "factcheck_prompt_refuses_stale_qa",
        _build_full_chain_stale_after_draft_reapprove,
        lambda runs, tid: runs.write_factcheck_prompt(tid, overwrite=True),
        "the approved qa for 'systems-thinking' is stale; rebuild the qa prompt "
        "and reapprove it before factcheck",
    ),
    StaleUpstreamRefusalCase(
        "repair_prompt_refuses_stale_qa",
        _build_full_chain_stale_after_draft_reapprove,
        lambda runs, tid: runs.write_repair_prompt(tid, overwrite=True),
        "the approved qa for 'systems-thinking' is stale; rebuild the qa prompt "
        "and reapprove it before repair",
    ),
    StaleUpstreamRefusalCase(
        "module_repair_prompt_refuses_stale_qa",
        _build_full_chain_stale_after_draft_reapprove,
        lambda runs, tid: runs.write_module_repair_prompt(
            tid, "loop-basics", overwrite=True
        ),
        "the approved qa for 'systems-thinking' is stale; rebuild the qa prompt "
        "and reapprove it before repair",
    ),
    StaleUpstreamRefusalCase(
        # qa is current here (it was reapproved), factcheck is not.
        "repair_prompt_refuses_stale_factcheck",
        _build_reapprove_only_qa,
        lambda runs, tid: runs.write_repair_prompt(tid, overwrite=True),
        "the approved factcheck for 'systems-thinking' is stale; rebuild the "
        "factcheck prompt and reapprove it before repair",
    ),
    StaleUpstreamRefusalCase(
        "module_repair_prompt_refuses_stale_factcheck",
        _build_reapprove_only_qa,
        lambda runs, tid: runs.write_module_repair_prompt(
            tid, "loop-basics", overwrite=True
        ),
        "the approved factcheck for 'systems-thinking' is stale; rebuild the "
        "factcheck prompt and reapprove it before repair",
    ),
]


@pytest.mark.parametrize(
    "case", STALE_UPSTREAM_REFUSAL_CASES, ids=lambda c: c.name
)
def test_prompt_writers_refuse_a_stale_upstream_stage(
    tmp_path: Path, case: StaleUpstreamRefusalCase
) -> None:
    runs = _create_guide_run(tmp_path, TID)
    case.build(runs, TID)

    with pytest.raises(ConfigError) as excinfo:
        case.call(runs, TID)
    assert str(excinfo.value) == case.message
