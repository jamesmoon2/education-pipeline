"""Failing (red) tests for the headless orchestrator, T30.

Mirrors ``web/src/lib/continueRun.ts`` / ``continueRun.test.ts`` line for
line: same stop kinds, same branch order, same stall guard and step cap.
``education_pipeline/orchestrate.py`` does not exist yet -- every test in
this file is expected to fail on collection with ``ImportError`` until the
implementer adds it.
"""

from __future__ import annotations

import dataclasses

import pytest

import test_cli  # tests/test_cli.py: _seed_topic_to_draft (tests/test_cli.py:416)

from education_pipeline import AdvanceResult, NextAction, RunStatus, RunStore
from education_pipeline.config import ModelPlan, StageModelPlan, load_model_plan, parse_model_plan
from education_pipeline.orchestrate import (
    MAX_STEPS,
    STOP_KINDS,
    JobOutcome,
    Outcome,
    Step,
    Steps,
    Stop,
    StoreSteps,
    describe_step,
    describe_stop,
    provider_for_stage,
    run_until_judgment,
    step_payload,
    stop_payload,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _status(action: str, stage: str | None = None, *, topic_id: str = "t") -> RunStatus:
    """A minimal RunStatus with empty stages, matching continueRun.test.ts's
    ``makeStatus``."""

    next_action = NextAction(topic_id=topic_id, stage=stage, action=action, detail=f"detail for {action}")
    return RunStatus(topic_id=topic_id, stages=(), finalized=(action == "done"), next_action=next_action)


def _advance_result(status: RunStatus, *, performed: str = "write_prompt") -> AdvanceResult:
    return AdvanceResult(topic_id=status.topic_id, performed=performed, status=status)


def _job(*, waited: bool, ok: bool = True, message: str | None = None, count: int | None = None) -> JobOutcome:
    return JobOutcome(waited=waited, ok=ok, message=message, count=count)


def scripted(*items):
    """A callable yielding ``items`` in order across successive calls.

    An ``Exception`` instance in the sequence is raised instead of returned.
    Calling past the end of the script fails the test loudly rather than
    resolving something the test never described.
    """

    it = iter(items)

    def _call(*_args, **_kwargs):
        try:
            item = next(it)
        except StopIteration:
            raise AssertionError("called more times than scripted") from None
        if isinstance(item, BaseException):
            raise item
        return item

    return _call


def constant(value_or_exc):
    def _call(*_args, **_kwargs):
        if isinstance(value_or_exc, BaseException):
            raise value_or_exc
        return value_or_exc

    return _call


def _unscripted(name: str):
    def _call(*_args, **_kwargs):
        raise AssertionError(f"{name}() was not scripted for this test")

    return _call


class RecordingSteps:
    """Implements the ``Steps`` protocol by delegating each of its five
    members to an injected callable, and records every call made.

    Any attribute access outside those five members raises ``AttributeError``
    -- in particular ``.approve``, ``.finalize`` and ``.export`` -- so the
    loop cannot silently reach a member the protocol does not have, even by
    typo, without a test noticing.
    """

    def __init__(self, *, status=None, advance=None, validate=None, provider_for=None, run_job=None):
        self._status_fn = status or _unscripted("status")
        self._advance_fn = advance or _unscripted("advance")
        self._validate_fn = validate or _unscripted("validate")
        self._provider_for_fn = provider_for or _unscripted("provider_for")
        self._run_job_fn = run_job or _unscripted("run_job")
        self.calls: list[tuple[str, tuple]] = []

    def status(self, topic_id):
        self.calls.append(("status", (topic_id,)))
        return self._status_fn(topic_id)

    def advance(self, topic_id):
        self.calls.append(("advance", (topic_id,)))
        return self._advance_fn(topic_id)

    def validate(self, topic_id, phase):
        self.calls.append(("validate", (topic_id, phase)))
        return self._validate_fn(topic_id, phase)

    def provider_for(self, topic_id, stage):
        self.calls.append(("provider_for", (topic_id, stage)))
        return self._provider_for_fn(topic_id, stage)

    def run_job(self, topic_id, stage):
        self.calls.append(("run_job", (topic_id, stage)))
        return self._run_job_fn(topic_id, stage)

    def kinds_called(self):
        return [kind for kind, _args in self.calls]

    def count(self, kind: str) -> int:
        return sum(1 for k, _ in self.calls if k == kind)

    def __getattr__(self, name):  # noqa: D105 - deliberately hostile
        raise AttributeError(
            f"Steps has no member {name!r}; the loop must never touch it (recording fake forbids it)"
        )


# ---------------------------------------------------------------------------
# 1. run_until_judgment over a fake Steps -- one branch per stop reason
# ---------------------------------------------------------------------------


def test_advance_reuses_returned_status_without_rereading():
    steps = RecordingSteps(
        status=constant(_status("write_prompt", "qa")),
        advance=constant(_advance_result(_status("approve", "qa"))),
    )
    outcome = run_until_judgment("t", steps)
    assert outcome.steps == (Step(kind="advance", stage="qa"),)
    assert outcome.stop == Stop(kind="approve", stage="qa")
    assert steps.count("status") == 1
    assert steps.count("advance") == 1


def test_validate_discards_status_and_rereads():
    steps = RecordingSteps(
        status=scripted(_status("validate", "draft"), _status("approve", "qa")),
        validate=constant(None),
    )
    outcome = run_until_judgment("t", steps)
    assert outcome.steps == (Step(kind="validate", stage="draft", phase="draft"),)
    assert outcome.stop == Stop(kind="approve", stage="qa")
    assert steps.count("status") == 2
    assert steps.calls[1] == ("validate", ("t", "draft"))


def test_validate_phase_is_final_for_a_non_draft_stage():
    steps = RecordingSteps(
        status=scripted(_status("validate", "repair"), _status("finalize", None)),
        validate=constant(None),
    )
    outcome = run_until_judgment("t", steps)
    assert outcome.steps == (Step(kind="validate", stage="repair", phase="final"),)
    assert outcome.stop == Stop(kind="finalize")


def test_assemble_is_treated_as_an_advance_step():
    steps = RecordingSteps(
        status=constant(_status("assemble", "draft")),
        advance=constant(_advance_result(_status("approve", "draft"))),
    )
    outcome = run_until_judgment("t", steps)
    assert outcome.steps == (Step(kind="advance", stage="draft"),)
    assert outcome.stop == Stop(kind="approve", stage="draft")


def test_save_response_started_with_no_count_when_the_job_is_not_batched():
    steps = RecordingSteps(
        status=constant(_status("save_response", "qa")),
        provider_for=constant("claude"),
        run_job=constant(_job(waited=False)),
    )
    outcome = run_until_judgment("t", steps)
    assert outcome.steps == (Step(kind="job", stage="qa", provider="claude", count=None),)
    assert outcome.stop == Stop(kind="started", stage="qa", provider="claude", count=None)


def test_save_response_started_reports_a_batch_count():
    steps = RecordingSteps(
        status=constant(_status("save_response", "draft")),
        provider_for=constant("claude-code"),
        run_job=constant(_job(waited=False, count=3)),
    )
    outcome = run_until_judgment("t", steps)
    assert outcome.steps == (Step(kind="job", stage="draft", provider="claude-code", count=3),)
    assert outcome.stop == Stop(kind="started", stage="draft", provider="claude-code", count=3)


def test_save_response_manual_provider_stops_without_starting_a_job():
    steps = RecordingSteps(
        status=constant(_status("save_response", "qa")),
        provider_for=constant("manual"),
    )
    outcome = run_until_judgment("t", steps)
    assert outcome.steps == ()
    assert outcome.stop == Stop(kind="manual", stage="qa")
    assert steps.count("run_job") == 0


def test_save_response_plan_unreadable_when_provider_for_raises():
    steps = RecordingSteps(
        status=constant(_status("save_response", "draft")),
        provider_for=constant(RuntimeError("plan unreadable")),
    )
    outcome = run_until_judgment("t", steps)
    assert outcome.steps == ()
    assert outcome.stop == Stop(kind="plan_unreadable", stage="draft")
    assert steps.count("run_job") == 0


def test_save_response_with_no_stage_is_unfinished_and_never_reads_the_plan():
    steps = RecordingSteps(status=constant(_status("save_response", None)))
    outcome = run_until_judgment("t", steps)
    assert outcome.steps == ()
    assert outcome.stop == Stop(kind="unfinished")
    assert steps.count("provider_for") == 0


def test_approve_with_a_stage():
    steps = RecordingSteps(status=constant(_status("approve", "qa")))
    outcome = run_until_judgment("t", steps)
    assert outcome.steps == ()
    assert outcome.stop == Stop(kind="approve", stage="qa")


def test_approve_without_a_stage():
    steps = RecordingSteps(status=constant(_status("approve", None)))
    outcome = run_until_judgment("t", steps)
    assert outcome.stop == Stop(kind="approve", stage=None)


def test_resolve_findings():
    steps = RecordingSteps(status=constant(_status("resolve_findings", "repair")))
    outcome = run_until_judgment("t", steps)
    assert outcome.steps == ()
    assert outcome.stop == Stop(kind="resolve_findings")


def test_finalize_stop():
    steps = RecordingSteps(status=constant(_status("finalize", None)))
    outcome = run_until_judgment("t", steps)
    assert outcome.stop == Stop(kind="finalize")


def test_done_stop():
    steps = RecordingSteps(status=constant(_status("done", None)))
    outcome = run_until_judgment("t", steps)
    assert outcome.steps == ()
    assert outcome.stop == Stop(kind="done")


def test_unknown_action_is_unfinished():
    steps = RecordingSteps(status=constant(_status("teleport", None)))
    outcome = run_until_judgment("t", steps)
    assert outcome.stop == Stop(kind="unfinished")


def test_status_exception_reports_failed_with_no_status_and_no_steps():
    steps = RecordingSteps(status=constant(RuntimeError("daemon gone")))
    outcome = run_until_judgment("t", steps)
    assert outcome.steps == ()
    assert outcome.stop == Stop(kind="failed", action="reading the run status", message="daemon gone")
    assert outcome.status is None


def test_advance_exception_keeps_the_steps_taken_before_it():
    steps = RecordingSteps(
        status=scripted(_status("validate", "draft"), _status("write_prompt", "qa")),
        validate=constant(None),
        advance=constant(RuntimeError("job j1 is running")),
    )
    outcome = run_until_judgment("t", steps)
    assert outcome.steps == (Step(kind="validate", stage="draft", phase="draft"),)
    assert outcome.stop == Stop(kind="failed", action="writing the qa prompt", message="job j1 is running")
    assert outcome.status == _status("write_prompt", "qa")


def test_advance_exception_labels_a_missing_stage_as_next():
    steps = RecordingSteps(
        status=constant(_status("write_prompt", None)),
        advance=constant(RuntimeError("boom")),
    )
    outcome = run_until_judgment("t", steps)
    assert outcome.stop == Stop(kind="failed", action="writing the next prompt", message="boom")


def test_validate_exception_reports_failed_draft_validation():
    steps = RecordingSteps(
        status=constant(_status("validate", "draft")),
        validate=constant(RuntimeError("validator crashed")),
    )
    outcome = run_until_judgment("t", steps)
    assert outcome.steps == ()
    assert outcome.stop == Stop(kind="failed", action="draft validation", message="validator crashed")


def test_validate_exception_reports_failed_final_validation():
    steps = RecordingSteps(
        status=constant(_status("validate", "repair")),
        validate=constant(RuntimeError("validator crashed")),
    )
    outcome = run_until_judgment("t", steps)
    assert outcome.stop == Stop(kind="failed", action="final validation", message="validator crashed")


def test_run_job_exception_reports_failed_starting_and_no_job_step():
    steps = RecordingSteps(
        status=constant(_status("save_response", "qa")),
        provider_for=constant("claude"),
        run_job=constant(RuntimeError("provider unavailable")),
    )
    outcome = run_until_judgment("t", steps)
    assert outcome.steps == ()
    assert outcome.stop == Stop(
        kind="failed", action="starting qa with claude", message="provider unavailable"
    )


def test_waited_job_that_succeeds_continues_the_loop():
    steps = RecordingSteps(
        status=scripted(_status("save_response", "qa"), _status("approve", "qa")),
        provider_for=constant("claude"),
        run_job=constant(_job(waited=True, ok=True)),
    )
    outcome = run_until_judgment("t", steps)
    assert outcome.steps == (Step(kind="job", stage="qa", provider="claude", count=None),)
    assert outcome.stop == Stop(kind="approve", stage="qa")
    assert steps.count("run_job") == 1


def test_waited_job_that_fails_reports_failed_and_still_records_the_step():
    steps = RecordingSteps(
        status=constant(_status("save_response", "qa")),
        provider_for=constant("claude"),
        run_job=constant(_job(waited=True, ok=False, message="job crashed")),
    )
    outcome = run_until_judgment("t", steps)
    assert outcome.steps == (Step(kind="job", stage="qa", provider="claude", count=None),)
    assert outcome.stop == Stop(kind="failed", action="running qa with claude", message="job crashed")


def test_stall_guard_stops_without_calling_run_job_again():
    steps = RecordingSteps(
        status=scripted(_status("save_response", "draft"), _status("save_response", "draft")),
        provider_for=constant("claude"),
        run_job=constant(_job(waited=True, ok=True)),
    )
    outcome = run_until_judgment("t", steps)
    assert outcome.stop == Stop(
        kind="failed",
        action="running draft with claude",
        message="the job finished but no response was saved",
    )
    assert steps.count("run_job") == 1


def test_realistic_chain_advance_job_validate_then_approve():
    steps = RecordingSteps(
        status=scripted(
            _status("write_prompt", "qa"),
            # advance's returned status is reused, not re-read here
            _status("validate", "qa"),
            _status("approve", "qa"),
        ),
        advance=constant(_advance_result(_status("save_response", "qa"))),
        provider_for=constant("claude"),
        run_job=constant(_job(waited=True, ok=True)),
        validate=constant(None),
    )
    outcome = run_until_judgment("t", steps)
    assert outcome.steps == (
        Step(kind="advance", stage="qa"),
        Step(kind="job", stage="qa", provider="claude", count=None),
        Step(kind="validate", stage="qa", phase="final"),
    )
    assert outcome.stop == Stop(kind="approve", stage="qa")
    # advance's status was reused (one status() call), then one re-read after
    # the job, then one re-read after validate.
    assert steps.count("status") == 3


def test_max_steps_cap_stops_unfinished():
    always_same = _status("write_prompt", "spec")
    steps = RecordingSteps(
        status=constant(always_same),
        advance=constant(_advance_result(always_same)),
    )
    outcome = run_until_judgment("t", steps, max_steps=4)
    assert steps.count("advance") == 4
    assert len(outcome.steps) == 4
    assert outcome.stop == Stop(kind="unfinished")
    # the loop status() only needs to be read once; advance keeps handing it
    # back unchanged.
    assert steps.count("status") == 1


def test_default_max_steps_is_twelve():
    assert MAX_STEPS == 12
    always_same = _status("write_prompt", "spec")
    steps = RecordingSteps(
        status=constant(always_same),
        advance=constant(_advance_result(always_same)),
    )
    outcome = run_until_judgment("t", steps)
    assert steps.count("advance") == MAX_STEPS
    assert outcome.stop == Stop(kind="unfinished")


def test_stop_kinds_content_and_order():
    assert STOP_KINDS == (
        "started",
        "manual",
        "plan_unreadable",
        "approve",
        "resolve_findings",
        "finalize",
        "done",
        "unfinished",
        "failed",
    )


def test_step_is_frozen():
    step = Step(kind="advance", stage="qa")
    with pytest.raises(dataclasses.FrozenInstanceError):
        step.stage = "draft"  # type: ignore[misc]


def test_stop_is_frozen():
    stop = Stop(kind="approve", stage="qa")
    with pytest.raises(dataclasses.FrozenInstanceError):
        stop.stage = "draft"  # type: ignore[misc]


def test_outcome_is_returned_and_frozen():
    steps = RecordingSteps(status=constant(_status("approve", "qa")))
    outcome = run_until_judgment("t", steps)
    assert isinstance(outcome, Outcome)
    assert outcome.topic_id == "t"
    with pytest.raises(dataclasses.FrozenInstanceError):
        outcome.topic_id = "other"  # type: ignore[misc]


def test_steps_protocol_has_no_approve_finalize_or_export():
    assert not hasattr(Steps, "approve")
    assert not hasattr(Steps, "finalize")
    assert not hasattr(Steps, "export")


def test_recording_fake_raises_for_any_unscripted_member():
    steps = RecordingSteps(status=constant(_status("approve", "qa")))
    with pytest.raises(AttributeError):
        steps.approve("t")  # type: ignore[attr-defined]
    with pytest.raises(AttributeError):
        steps.finalize("t")  # type: ignore[attr-defined]
    with pytest.raises(AttributeError):
        steps.export("t")  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# 2. provider_for_stage over a real ModelPlan
# ---------------------------------------------------------------------------


def test_provider_for_stage_stage_row_wins_over_plan_default():
    plan = parse_model_plan({"provider": "claude-code", "stages": {"qa": {"provider": "codex"}}})
    assert provider_for_stage(plan, "qa") == "codex"


def test_provider_for_stage_falls_back_to_plan_default_when_stage_row_is_none():
    # A stage row with no provider of its own is NOT manual -- decision 5 /
    # continueRun.ts:163-172's INVARIANT. Built directly (like
    # tests/test_profile_draft.py:44) because parse_model_plan always fills
    # in a stage's provider from the plan default when the TOML omits it, so
    # only a directly-constructed StageModelPlan can carry provider=None.
    plan = ModelPlan(
        provider="codex",
        stages={"draft": StageModelPlan(stage="draft", recommendation="x", provider=None)},
    )
    assert provider_for_stage(plan, "draft") == "codex"


def test_provider_for_stage_default_is_not_manual_even_when_default_provider_is_manual():
    plan = ModelPlan(
        provider="manual",
        stages={"draft": StageModelPlan(stage="draft", recommendation="x", provider="codex")},
    )
    assert provider_for_stage(plan, "draft") == "codex"


def test_provider_for_stage_over_a_plan_loaded_from_disk(tmp_path):
    plan_path = tmp_path / "model-plan.toml"
    plan_path.write_text(
        'provider = "claude-code"\n\n[stages.qa]\nprovider = "codex"\n',
        encoding="utf-8",
    )
    plan = load_model_plan(plan_path)
    assert provider_for_stage(plan, "qa") == "codex"
    assert provider_for_stage(plan, "draft") == "claude-code"


# ---------------------------------------------------------------------------
# 3. describe_stop / describe_step / step_payload / stop_payload
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "stop, phrase",
    [
        (Stop(kind="started", stage="qa", provider="claude"), "started qa with claude"),
        (
            Stop(kind="started", stage="draft", provider="claude-code", count=3),
            "3 module jobs started for draft with claude-code",
        ),
        (Stop(kind="manual", stage="qa"), "the qa prompt is ready for you to run"),
        (
            Stop(kind="plan_unreadable", stage="qa"),
            "the qa prompt is ready, but the model plan could not be read, so start the stage yourself",
        ),
        (Stop(kind="approve", stage="qa"), "qa needs your approval"),
        (Stop(kind="approve", stage=None), "the next stage needs your approval"),
        (Stop(kind="resolve_findings"), "findings need review"),
        (Stop(kind="finalize"), "the run is ready to finalize"),
        (Stop(kind="done"), "the run is ready to export"),
        (Stop(kind="unfinished"), "more steps are waiting"),
        (
            Stop(kind="failed", action="running qa with claude", message="boom"),
            "running qa with claude failed: boom",
        ),
    ],
)
def test_describe_stop_phrases(stop: Stop, phrase: str):
    assert describe_stop(stop) == phrase


@pytest.mark.parametrize(
    "step, phrase",
    [
        (Step(kind="advance", stage="qa"), "wrote the qa prompt"),
        (Step(kind="advance", stage=None), "wrote the next prompt"),
        (Step(kind="validate", stage="draft", phase="draft"), "ran draft validation"),
        (Step(kind="validate", stage="repair", phase="final"), "ran final validation"),
        (Step(kind="job", stage="qa", provider="claude", count=None), None),
        (Step(kind="job", stage="draft", provider="claude", count=3), None),
    ],
)
def test_describe_step_phrases(step: Step, phrase: str | None):
    assert describe_step(step) == phrase


def test_step_payload_drops_none_keys_and_keeps_kind_first_class():
    payload = step_payload(Step(kind="job", stage="qa", provider="claude", count=None))
    assert payload == {"kind": "job", "stage": "qa", "provider": "claude"}
    assert next(iter(payload)) == "kind"
    assert "count" not in payload
    assert "phase" not in payload


def test_step_payload_advance_with_no_stage():
    payload = step_payload(Step(kind="advance", stage=None))
    assert payload == {"kind": "advance"}


def test_stop_payload_started_with_count():
    payload = stop_payload(Stop(kind="started", stage="draft", provider="claude-code", count=3))
    assert payload == {"kind": "started", "stage": "draft", "provider": "claude-code", "count": 3}


def test_stop_payload_failed_drops_stage_provider_and_count():
    payload = stop_payload(Stop(kind="failed", action="starting qa with claude", message="boom"))
    assert payload == {"kind": "failed", "action": "starting qa with claude", "message": "boom"}
    assert "stage" not in payload
    assert "provider" not in payload
    assert "count" not in payload


def test_stop_payload_approve_with_no_stage():
    payload = stop_payload(Stop(kind="approve", stage=None))
    assert payload == {"kind": "approve"}


# ---------------------------------------------------------------------------
# 4. StoreSteps over a real RunStore
# ---------------------------------------------------------------------------


class RecordingGuard:
    """A ``mutation_guard`` fake recording that it is entered before, and
    exited after, the delegate call it wraps."""

    def __init__(self):
        self.events: list[str] = []
        self.entered_topics: list[str] = []

    def __call__(self, topic_id: str):
        self.entered_topics.append(topic_id)
        return self

    def __enter__(self):
        self.events.append("enter")
        return self

    def __exit__(self, exc_type, exc, tb):
        self.events.append("exit")
        return False


def test_store_steps_status_matches_the_store(tmp_path):
    ws = tmp_path / "ws"
    test_cli._seed_topic_to_draft(ws)
    runs = RunStore(ws)
    store_steps = StoreSteps(
        runs,
        plan_for=constant(RuntimeError("unused")),
        run_job=constant(RuntimeError("unused")),
    )
    assert store_steps.status("systems-thinking") == runs.run_status("systems-thinking")


def test_store_steps_advance_performs_write_prompt(tmp_path):
    ws = tmp_path / "ws"
    test_cli._seed_topic_to_draft(ws)
    runs = RunStore(ws)
    runs.ingest_response("systems-thinking", "draft", "# Generated draft\n")
    runs.approve_stage("systems-thinking", "draft")
    assert runs.run_status("systems-thinking").next_action.action == "write_prompt"

    store_steps = StoreSteps(
        runs,
        plan_for=constant(RuntimeError("unused")),
        run_job=constant(RuntimeError("unused")),
    )
    result = store_steps.advance("systems-thinking")
    assert isinstance(result, AdvanceResult)
    assert result.performed == "write_prompt"
    assert result.status.next_action.stage == "qa"
    assert result.status.next_action.action == "save_response"


def test_store_steps_validate_delegates_to_validate_and_gate(tmp_path, monkeypatch):
    ws = tmp_path / "ws"
    test_cli._seed_topic_to_draft(ws)
    runs = RunStore(ws)

    calls: list[tuple[str, str]] = []

    def fake_validate_and_gate(topic_id: str, phase: str):
        calls.append((topic_id, phase))
        return object()

    # RunStore is a frozen dataclass (runs.py:265), so an instance attribute
    # is installed the way RunStore installs its own (runs.py:272-275) rather
    # than with monkeypatch.setattr, which raises FrozenInstanceError. The
    # store is built fresh per test, so nothing leaks.
    object.__setattr__(runs, "validate_and_gate", fake_validate_and_gate)
    store_steps = StoreSteps(
        runs,
        plan_for=constant(RuntimeError("unused")),
        run_job=constant(RuntimeError("unused")),
    )
    result = store_steps.validate("systems-thinking", "draft")
    assert calls == [("systems-thinking", "draft")]
    assert result is None  # discarded, per the Steps.validate contract


def test_store_steps_provider_for_uses_plan_for_and_applies_the_rule(tmp_path):
    ws = tmp_path / "ws"
    test_cli._seed_topic_to_draft(ws)
    runs = RunStore(ws)

    plan_calls: list[str] = []

    def plan_for(topic_id: str) -> ModelPlan:
        plan_calls.append(topic_id)
        return parse_model_plan({"provider": "claude-code", "stages": {"draft": {"provider": "codex"}}})

    store_steps = StoreSteps(runs, plan_for=plan_for, run_job=constant(RuntimeError("unused")))
    provider = store_steps.provider_for("systems-thinking", "draft")
    assert provider == "codex"
    assert plan_calls == ["systems-thinking"]


def test_store_steps_run_job_delegates_to_the_injected_callable(tmp_path):
    ws = tmp_path / "ws"
    test_cli._seed_topic_to_draft(ws)
    runs = RunStore(ws)

    calls: list[tuple[str, str]] = []

    def run_job(topic_id: str, stage: str) -> JobOutcome:
        calls.append((topic_id, stage))
        return JobOutcome(waited=False, count=None)

    store_steps = StoreSteps(runs, plan_for=constant(RuntimeError("unused")), run_job=run_job)
    outcome = store_steps.run_job("systems-thinking", "draft")
    assert calls == [("systems-thinking", "draft")]
    assert outcome == JobOutcome(waited=False, count=None)


def test_store_steps_mutation_guard_wraps_advance(tmp_path):
    ws = tmp_path / "ws"
    test_cli._seed_topic_to_draft(ws)
    runs = RunStore(ws)
    runs.ingest_response("systems-thinking", "draft", "# Generated draft\n")
    runs.approve_stage("systems-thinking", "draft")

    guard = RecordingGuard()
    store_steps = StoreSteps(
        runs,
        plan_for=constant(RuntimeError("unused")),
        run_job=constant(RuntimeError("unused")),
        mutation_guard=guard,
    )
    store_steps.advance("systems-thinking")
    assert guard.entered_topics == ["systems-thinking"]
    assert guard.events == ["enter", "exit"]


def test_store_steps_mutation_guard_wraps_validate(tmp_path, monkeypatch):
    ws = tmp_path / "ws"
    test_cli._seed_topic_to_draft(ws)
    runs = RunStore(ws)
    # See test_store_steps_validate_delegates_to_validate_and_gate: RunStore
    # is frozen, so monkeypatch.setattr on the instance raises.
    object.__setattr__(runs, "validate_and_gate", lambda topic_id, phase: object())

    guard = RecordingGuard()
    store_steps = StoreSteps(
        runs,
        plan_for=constant(RuntimeError("unused")),
        run_job=constant(RuntimeError("unused")),
        mutation_guard=guard,
    )
    store_steps.validate("systems-thinking", "draft")
    assert guard.entered_topics == ["systems-thinking"]
    assert guard.events == ["enter", "exit"]


def test_store_steps_mutation_guard_does_not_wrap_status_provider_for_or_run_job(tmp_path):
    ws = tmp_path / "ws"
    test_cli._seed_topic_to_draft(ws)
    runs = RunStore(ws)

    guard = RecordingGuard()
    store_steps = StoreSteps(
        runs,
        plan_for=lambda topic_id: parse_model_plan({"provider": "claude-code", "stages": {}}),
        run_job=lambda topic_id, stage: JobOutcome(waited=False, count=None),
        mutation_guard=guard,
    )
    store_steps.status("systems-thinking")
    store_steps.provider_for("systems-thinking", "draft")
    store_steps.run_job("systems-thinking", "draft")
    assert guard.events == []
    assert guard.entered_topics == []


def test_store_steps_without_a_mutation_guard_works_unwrapped(tmp_path):
    ws = tmp_path / "ws"
    test_cli._seed_topic_to_draft(ws)
    runs = RunStore(ws)
    runs.ingest_response("systems-thinking", "draft", "# Generated draft\n")
    runs.approve_stage("systems-thinking", "draft")

    store_steps = StoreSteps(
        runs,
        plan_for=constant(RuntimeError("unused")),
        run_job=constant(RuntimeError("unused")),
    )
    result = store_steps.advance("systems-thinking")
    assert result.performed == "write_prompt"


# ---------------------------------------------------------------------------
# 5. End-to-end: run_until_judgment over a real StoreSteps
# ---------------------------------------------------------------------------


def test_end_to_end_engine_run_lands_a_draft_response_and_stops_at_approve(tmp_path):
    ws = tmp_path / "ws"
    test_cli._seed_topic_to_draft(ws)
    runs = RunStore(ws)

    # Pinned directly against the store before writing this test:
    #   after _seed_topic_to_draft, next_action is save_response(draft);
    #   after ingesting a draft response (legacy_markdown mode, no draft
    #   validate gate), next_action is approve(draft) -- not validate.
    seeded_next = runs.run_status("systems-thinking").next_action
    assert (seeded_next.action, seeded_next.stage) == ("save_response", "draft")

    run_job_calls: list[tuple[str, str]] = []

    def run_job(topic_id: str, stage: str) -> JobOutcome:
        run_job_calls.append((topic_id, stage))
        runs.ingest_response(topic_id, stage, "# Generated draft\n")
        return JobOutcome(waited=True, ok=True)

    store_steps = StoreSteps(
        runs,
        plan_for=lambda topic_id: parse_model_plan({"provider": "claude-code", "stages": {}}),
        run_job=run_job,
    )

    outcome = run_until_judgment("systems-thinking", store_steps)

    assert outcome.steps == (
        Step(kind="job", stage="draft", provider="claude-code", count=None),
    )
    assert outcome.stop == Stop(kind="approve", stage="draft")
    assert run_job_calls == [("systems-thinking", "draft")]
