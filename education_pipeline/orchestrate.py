"""Headless run-to-judgment loop.

Drive a run through every *mechanical* step it can take on its own -- writing
the next stage prompt, assembling a fanned-out draft, running validation, and
starting (or running) the configured provider -- and stop at the first step
that needs a person.

The product rule this module exists to keep: **the loop never approves,
finalizes or exports.** Those actions have no member on the ``Steps``
protocol at all, so the loop cannot perform them even by mistake; it stops and
reports where the run stands instead. ``finalize`` and ``done`` are stop
kinds, not steps.

The shape mirrors ``web/src/lib/continueRun.ts`` (the cockpit's "Approve &
continue" chain) branch for branch, so the cockpit can become a thin client
over this loop without changing its vocabulary.
"""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass
from typing import Callable, ContextManager, Protocol, TypeVar

from .config import ModelPlan
from .run_core import AdvanceResult, NextAction, RunStatus
from .runs import RunStore

__all__ = [
    "MAX_STEPS",
    "STOP_KINDS",
    "JobOutcome",
    "Outcome",
    "Step",
    "Steps",
    "Stop",
    "StoreSteps",
    "describe_step",
    "describe_stop",
    "provider_for_stage",
    "run_until_judgment",
    "step_payload",
    "stop_payload",
]


MANUAL_PROVIDER = "manual"

# Loop bound (decision 4): twice the longest real chain under per-module
# drafting -- skeleton prompt, skeleton job, module prompts, module batch,
# assemble, validate, approve -- so the loop terminates even if a step never
# clears the action the status keeps reporting.
MAX_STEPS = 12

# Stall guard (decision 3, revised in T33): a waited job that reports success
# must change the next action -- the *whole* next action, detail included. An
# interactive-guide draft goes through several distinct ``save_response``
# states for one stage (run the skeleton prompt; the skeleton response is
# invalid; k of N module responses saved; assembly failed), so comparing only
# ``(action, stage)`` reports a stall the moment the skeleton job's ingest
# writes the module prompts and the run asks for the module batch. Only an
# *identical* next action means the job changed nothing, and then
# re-enqueueing would just burn the cap, so stop and say so.
STALL_MESSAGE = "the job finished but no response was saved"

#: Every reason the loop stops, in the order the cockpit's ``ContinueStop``
#: union lists them (decision 2).
STOP_KINDS = (
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


# ---------------------------------------------------------------------------
# Value types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Step:
    """One mechanical step the loop performed.

    ``kind`` is ``advance`` (a stage prompt written), ``assemble`` (a
    fanned-out draft assembled), ``validate`` (a phase report computed and
    gated), or ``job`` (a provider job started, and possibly waited for).

    ``advance`` and ``assemble`` both go through ``Steps.advance`` -- the
    protocol keeps its five members -- but they are different work and read
    differently, so they are different kinds (Codex round 1, F5).
    """

    kind: str
    stage: str | None = None
    phase: str | None = None
    provider: str | None = None
    count: int | None = None


@dataclass(frozen=True)
class Stop:
    """Where the loop stopped, and why. ``kind`` is one of ``STOP_KINDS``."""

    kind: str
    stage: str | None = None
    provider: str | None = None
    count: int | None = None
    action: str | None = None
    message: str | None = None


@dataclass(frozen=True)
class JobOutcome:
    """What an injected job runner did.

    ``waited`` distinguishes the two runners of decision 1: a runner that only
    enqueues reports ``waited=False`` and the loop stops with ``started``; one
    that blocks until the job reaches a terminal status reports ``waited=True``
    and the loop carries on (or stops with ``failed`` when ``ok`` is false).
    ``count`` is the module-batch size, when the stage fanned out.

    ``provider`` is the provider the job *actually* ran with, when the runner
    knows it (Codex round 1, F4). The plan can be edited while a job sits
    queued, and the worker re-resolves it when it picks the job up, so the
    provider resolved before enqueueing is only a prediction. ``None`` means
    "the runner does not know", and the loop keeps the resolved one.
    """

    waited: bool
    ok: bool = True
    message: str | None = None
    count: int | None = None
    provider: str | None = None


@dataclass(frozen=True)
class Outcome:
    """The loop's report: the steps taken, where it stopped, and the freshest
    status it read (``None`` when the very first read failed)."""

    topic_id: str
    steps: tuple[Step, ...]
    stop: Stop
    status: RunStatus | None


class Steps(Protocol):
    """The engine surface the loop is allowed to touch.

    Injected so tests drive every branch without a workspace, and so the
    absent ``approve`` / ``finalize`` / ``export`` members are visible in one
    place: what is not here cannot be called.
    """

    def status(self, topic_id: str) -> RunStatus: ...

    def advance(self, topic_id: str) -> AdvanceResult: ...

    def validate(self, topic_id: str, phase: str) -> None: ...

    def provider_for(self, topic_id: str, stage: str) -> str: ...

    def run_job(self, topic_id: str, stage: str) -> JobOutcome: ...


# ---------------------------------------------------------------------------
# The loop
# ---------------------------------------------------------------------------


class _StepError(Exception):
    """Carries the plain-language name of the step that raised, so the stop
    can say which follow-up failed."""

    def __init__(self, action: str, cause: BaseException) -> None:
        super().__init__(str(cause))
        self.action = action
        self.cause = cause


_T = TypeVar("_T")


def _step(action: str, call: Callable[[], _T]) -> _T:
    try:
        return call()
    except Exception as exc:  # noqa: BLE001 - re-raised, labelled, below
        raise _StepError(action, exc) from exc


def _stalled(before: NextAction, after: NextAction) -> bool:
    """Whether a job that succeeded left the run exactly where it was.

    Compares the whole next action -- action, stage *and* detail -- because
    one stage can legitimately ask for a response several times running (the
    draft units, ``runs_draft_units.py:1095-1150``), each time with a different
    detail. Progress always changes at least the detail.
    """

    return (
        before.action == after.action
        and before.stage == after.stage
        and before.detail == after.detail
    )


def _validate_phase(stage: str | None) -> str:
    """Only the draft stage gates on the draft report; everything later gates
    on final -- the same mapping the run board and the cockpit use."""

    return "draft" if stage == "draft" else "final"


def run_until_judgment(
    topic_id: str,
    steps: Steps,
    *,
    max_steps: int = MAX_STEPS,
    after_job: tuple[str, str, NextAction] | None = None,
) -> Outcome:
    """Take mechanical steps for ``topic_id`` until one needs judgment.

    ``after_job`` is for a caller resuming the chain *after* a job it waited
    for elsewhere: ``(stage, provider, before)``, where ``before`` is the
    ``NextAction`` that caller read before starting the job. The loop's own
    stall guard cannot see that job, so the guard is applied to the loop's
    first status read instead -- an identical next action means the job
    changed nothing (decision 9; the daemon's completion hook passes the
    action it enqueued against, ``server.py`` ``continue_after_job``).
    """

    taken: list[Step] = []
    status: RunStatus | None = None
    # Consumed by the first read only: later reads are ordinary loop reads.
    pending_after_job = after_job

    def _stop(stop: Stop) -> Outcome:
        return Outcome(topic_id=topic_id, steps=tuple(taken), stop=stop, status=status)

    try:
        for _ in range(max_steps):
            if status is None:
                status = _step("reading the run status", lambda: steps.status(topic_id))
                if pending_after_job is not None:
                    done_stage, done_provider, before = pending_after_job
                    pending_after_job = None
                    if _stalled(before, status.next_action):
                        return _stop(
                            Stop(
                                kind="failed",
                                action=f"running {done_stage} with {done_provider}",
                                message=STALL_MESSAGE,
                            )
                        )
            # The step labels below name the stage, so they are read once here
            # rather than re-derived from a `status` the calls reassign.
            action = status.next_action.action
            stage = status.next_action.stage

            if action in ("write_prompt", "assemble"):
                # `advance` performs whatever machine step the run is on --
                # writing a prompt or assembling a fanned-out draft. Only ever
                # reached from a freshly read status, so it cannot finalize.
                # The two are one call but two kinds of work, so they carry
                # their own label and their own step kind (F5).
                assembling = action == "assemble"
                label = (
                    "assembling the draft"
                    if assembling
                    else f"writing the {stage or 'next'} prompt"
                )
                advanced = _step(label, lambda: steps.advance(topic_id))
                taken.append(
                    Step(kind="assemble" if assembling else "advance", stage=stage)
                )
                # advance hands back a fresh status; no need to re-read it.
                status = advanced.status
            elif action == "validate":
                phase = _validate_phase(stage)
                _step(f"{phase} validation", lambda: steps.validate(topic_id, phase))
                taken.append(Step(kind="validate", stage=stage, phase=phase))
                # validate answers with a report, not a status: re-read.
                status = None
            elif action == "save_response":
                # The engine always names a stage for save_response; without
                # one there is no plan row to consult, so stop rather than
                # guess a provider.
                if stage is None:
                    return _stop(Stop(kind="unfinished"))
                try:
                    provider = steps.provider_for(topic_id, stage)
                except Exception:  # noqa: BLE001 - any unreadable plan
                    # A plan we cannot read is not a failure: the prompt is on
                    # disk either way, so hand the stage back to the user.
                    return _stop(Stop(kind="plan_unreadable", stage=stage))
                if provider == MANUAL_PROVIDER:
                    return _stop(Stop(kind="manual", stage=stage))
                before_job = status.next_action
                job = _step(
                    f"starting {stage} with {provider}",
                    lambda: steps.run_job(topic_id, stage),
                )
                # The runner's own provider wins when it names one: it knows
                # what the job really ran with, `provider` was only the plan's
                # prediction from before the job was enqueued (F4).
                ran_with = job.provider or provider
                taken.append(
                    Step(kind="job", stage=stage, provider=ran_with, count=job.count)
                )
                running = f"running {stage} with {ran_with}"
                if not job.waited:
                    return _stop(
                        Stop(
                            kind="started",
                            stage=stage,
                            provider=ran_with,
                            count=job.count,
                        )
                    )
                if not job.ok:
                    return _stop(
                        Stop(
                            kind="failed",
                            action=running,
                            message=job.message or "the job did not succeed",
                        )
                    )
                status = _step("reading the run status", lambda: steps.status(topic_id))
                if _stalled(before_job, status.next_action):
                    return _stop(
                        Stop(kind="failed", action=running, message=STALL_MESSAGE)
                    )
            elif action == "approve":
                return _stop(Stop(kind="approve", stage=stage))
            elif action == "resolve_findings":
                return _stop(Stop(kind="resolve_findings"))
            elif action == "finalize":
                return _stop(Stop(kind="finalize"))
            elif action == "done":
                return _stop(Stop(kind="done"))
            else:
                # An action from a newer engine than this loop knows about.
                return _stop(Stop(kind="unfinished"))
    except _StepError as err:
        return _stop(Stop(kind="failed", action=err.action, message=str(err.cause)))
    return _stop(Stop(kind="unfinished"))


# ---------------------------------------------------------------------------
# Provider resolution (decision 5: one home for this rule)
# ---------------------------------------------------------------------------


def provider_for_stage(plan: ModelPlan, stage: str) -> str:
    """The provider that will actually execute ``stage`` under ``plan``.

    INVARIANT: the matching stage row's provider, falling back to the plan
    default. A row with no provider of its own is NOT manual -- the run-plan
    panel shows ``null`` as "manual", but that is a display fallback only.
    Every caller (the loop, the CLI, the daemon's enqueue) must resolve the
    provider through here, or a job is started with one provider and reported
    with another.
    """

    # `plan.stage` raises ConfigError on an unknown stage, exactly as the
    # daemon's enqueue path does; the loop maps that to `plan_unreadable`.
    row = plan.stage(stage)
    return row.provider or plan.provider


# ---------------------------------------------------------------------------
# Phrases and payloads
# ---------------------------------------------------------------------------


def describe_step(step: Step) -> str | None:
    """One phrase for a step, or ``None`` when the stop phrase already says
    it (a job is always reported by its ``started``/``failed`` stop)."""

    if step.kind == "advance":
        return f"wrote the {step.stage or 'next'} prompt"
    if step.kind == "assemble":
        return "assembled the draft"
    if step.kind == "validate":
        return f"ran {step.phase} validation"
    return None


def describe_stop(stop: Stop) -> str:
    """One plain-language phrase for where the run now stands."""

    if stop.kind == "started":
        if stop.count:
            return (
                f"{stop.count} module jobs started for {stop.stage} "
                f"with {stop.provider}"
            )
        return f"started {stop.stage} with {stop.provider}"
    if stop.kind == "manual":
        return f"the {stop.stage} prompt is ready for you to run"
    if stop.kind == "plan_unreadable":
        return (
            f"the {stop.stage} prompt is ready, but the model plan could not "
            "be read, so start the stage yourself"
        )
    if stop.kind == "approve":
        if stop.stage:
            return f"{stop.stage} needs your approval"
        return "the next stage needs your approval"
    if stop.kind == "resolve_findings":
        return "findings need review"
    if stop.kind == "finalize":
        return "the run is ready to finalize"
    if stop.kind == "done":
        return "the run is ready to export"
    if stop.kind == "failed":
        return f"{stop.action} failed: {stop.message}"
    return "more steps are waiting"


def _payload(pairs: tuple[tuple[str, object | None], ...]) -> dict[str, object]:
    return {key: value for key, value in pairs if value is not None}


def step_payload(step: Step) -> dict[str, object]:
    """A JSON-ready step: ``kind`` first, unset fields dropped."""

    return _payload(
        (
            ("kind", step.kind),
            ("stage", step.stage),
            ("phase", step.phase),
            ("provider", step.provider),
            ("count", step.count),
        )
    )


def stop_payload(stop: Stop) -> dict[str, object]:
    """A JSON-ready stop: ``kind`` first, unset fields dropped."""

    return _payload(
        (
            ("kind", stop.kind),
            ("stage", stop.stage),
            ("provider", stop.provider),
            ("count", stop.count),
            ("action", stop.action),
            ("message", stop.message),
        )
    )


# ---------------------------------------------------------------------------
# The engine adapter
# ---------------------------------------------------------------------------


class StoreSteps:
    """``Steps`` over a real ``RunStore``.

    The plan loader and the job runner are injected: the CLI hands in a runner
    that blocks until the job is terminal, the daemon one that only enqueues
    (decision 1). ``mutation_guard`` is the caller's lock scope -- the CLI's
    ``_guarded_mutation`` -- wrapped around the two members that mutate the
    workspace, and only those.
    """

    def __init__(
        self,
        runs: RunStore,
        *,
        plan_for: Callable[[str], ModelPlan],
        run_job: Callable[[str, str], JobOutcome],
        mutation_guard: Callable[[str], ContextManager[object]] | None = None,
    ) -> None:
        self._runs = runs
        self._plan_for = plan_for
        self._run_job = run_job
        self._mutation_guard = mutation_guard

    def _guard(self, topic_id: str) -> ContextManager[object]:
        if self._mutation_guard is None:
            return nullcontext()
        return self._mutation_guard(topic_id)

    def status(self, topic_id: str) -> RunStatus:
        return self._runs.run_status(topic_id)

    def advance(self, topic_id: str) -> AdvanceResult:
        with self._guard(topic_id):
            return self._runs.advance(topic_id)

    def validate(self, topic_id: str, phase: str) -> None:
        with self._guard(topic_id):
            self._runs.validate_and_gate(topic_id, phase)
        # The gate result is a report, not a status: the loop re-reads instead.
        return None

    def provider_for(self, topic_id: str, stage: str) -> str:
        return provider_for_stage(self._plan_for(topic_id), stage)

    def run_job(self, topic_id: str, stage: str) -> JobOutcome:
        return self._run_job(topic_id, stage)
