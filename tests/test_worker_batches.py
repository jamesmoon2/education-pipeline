"""Failing-first tests for job batches and a bounded worker pool (thread T23).

Written strictly TDD: none of the API exercised here exists yet
(``Job.batch_id``/``Job.part``, ``JobStore.active_for_part``/``batch``,
``new_batch_id``, ``Worker(..., parallelism=…)``/``enqueue_batch``/
``cancel_batch``, ``DaemonContext.enqueue_draft_batch``/``cancel_batch``).
Every test therefore fails today with ``ImportError`` / ``AttributeError`` /
``TypeError`` while the rest of the suite is untouched -- the new names are
reached through helper functions rather than module-scope imports, so this
file still collects cleanly.

The modular-run builders are copied (not imported -- ``tests/`` has no
``__init__.py``) from ``tests/test_modular_draft.py``, widened to three
contract modules so a three-job batch can be run against a pool of two.

Contract: ``docs/superpowers/specs/2026-09-18-per-module-drafting-design.md``
decision D6, plus the T23 interface contract.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

from education_pipeline import (
    ConfigError,
    ContentContract,
    RunStore,
    parse_model_catalog,
    parse_model_plan,
)
from education_pipeline.daemon import StaticConfigSource, write_api
from education_pipeline.daemon.jobs import (
    TERMINAL_STATUSES,
    Job,
    JobRunner,
    JobStore,
    Worker,
)
from education_pipeline.daemon.server import DaemonContext
from education_pipeline.draft_parts import FRAME, DraftPart
from education_pipeline.providers import Invocation, ProviderResponse, register_runner
from education_pipeline.workspace import ProfileStore, TopicStore

FAKE = Path(__file__).parent / "fake_provider.py"
FIXTURES_DIR = Path(__file__).parent / "fixtures" / "guides"

TID = "systems-thinking"

# A delay long enough that a two-thread pool is unambiguously observable by a
# 10ms poll, and short enough to keep the suite quick.
SLOW_SECONDS = "1.5"


# ---------------------------------------------------------------------------
# Deferred access to the not-yet-written API (keeps collection green).
# ---------------------------------------------------------------------------


def _jobs_module():
    from education_pipeline.daemon import jobs as jobs_module

    return jobs_module


def _new_batch_id() -> str:
    return _jobs_module().new_batch_id()


def _pool(store, factory, parallelism):
    """``Worker`` with the new ``parallelism`` keyword."""

    return Worker(store, factory, parallelism=parallelism)


def _create_part_job(store, topic_id, part, *, batch_id=None, stage="draft"):
    """``JobStore.create`` with the new ``batch_id``/``part`` keywords."""

    return store.create(
        topic_id,
        stage,
        "fake",
        "m",
        None,
        batch_id=batch_id,
        part=part.to_manifest(),
    )


# ---------------------------------------------------------------------------
# Guide fixture, widened to three modules.
# ---------------------------------------------------------------------------

TOPIC_TOML = """\
schema_version = 1
id = "systems-thinking"
title = "Systems Thinking"
brief = "A public introduction to feedback loops."
audience = "early-career analysts"
goals = ["explain feedback loops"]
"""

GUIDE = json.loads((FIXTURES_DIR / "feedback-loops.guide.json").read_text(encoding="utf-8"))
MODULES_BY_ID = {module["id"]: module for module in GUIDE["modules"]}

def _reid(value, suffix: str):
    """Deep-copy a guide fragment, suffixing every ``id`` below the top level.

    Guide ids are workspace-unique, so a cloned module needs fresh section /
    block / choice / step ids or assembly fails validation on duplicates.
    """

    if isinstance(value, dict):
        return {
            key: (f"{item}{suffix}" if key == "id" and isinstance(item, str) else _reid(item, suffix))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_reid(item, suffix) for item in value]
    return value


# A third contract module, cloned from the first so its shape stays valid, so
# that a batch of three module jobs can be run against a pool of two.
_THIRD = _reid(MODULES_BY_ID["loop-basics"], "-x")
_THIRD["id"] = "extra-practice"
_THIRD["title"] = "More practice with loops"
_THIRD["outcome_ids"] = ["choose-intervention"]
MODULES_BY_ID["extra-practice"] = _THIRD

VALID_SPEC_CONTRACT = {
    "contract_version": 1,
    "guide_schema_version": "1.0",
    "blueprint": "conceptual-foundations",
    "estimated_minutes": 30,
    "outcomes": [dict(outcome) for outcome in GUIDE["outcomes"]],
    "required_interactions": ["knowledge_check", "worked_reveal", "scenario", "reflection"],
    "personalization_requirements": ["Use gardening examples where they clarify the concept."],
    "source_policy": "Sources required for factual claims that are not common knowledge.",
}

VALID_OUTLINE_CONTRACT = {
    "contract_version": 1,
    "modules": {
        "loop-basics": {
            "outcome_ids": ["identify-loop", "map-loop"],
            "estimated_minutes": 14,
            "interaction_types": ["knowledge_check", "worked_reveal"],
        },
        "intervention-practice": {
            "outcome_ids": ["map-loop", "choose-intervention"],
            "estimated_minutes": 16,
            "interaction_types": ["knowledge_check", "scenario", "reflection"],
        },
        "extra-practice": {
            "outcome_ids": ["choose-intervention"],
            "estimated_minutes": 10,
            "interaction_types": ["knowledge_check"],
        },
    },
}


def _spec_response() -> str:
    return (
        "# Course Specification: Systems Thinking\n\n"
        "```education-pipeline-contract+json\n"
        f"{json.dumps(VALID_SPEC_CONTRACT)}\n"
        "```\n"
    )


def _outline_response() -> str:
    return (
        "# Course Outline: Systems Thinking\n\n"
        "```education-pipeline-outline+json\n"
        f"{json.dumps(VALID_OUTLINE_CONTRACT)}\n"
        "```\n"
    )


def _contract_module_ids(runs: RunStore, topic_id: str = TID) -> tuple[str, ...]:
    path = runs.run_dir(topic_id) / "inputs" / "guide-contract.json"
    return tuple(json.loads(path.read_text(encoding="utf-8"))["modules"])


def _frame_text(module_ids) -> str:
    frame = dict(GUIDE)
    frame["modules"] = [
        {
            **{k: v for k, v in MODULES_BY_ID[module_id].items() if k != "sections"},
            "sections": [],
        }
        for module_id in module_ids
    ]
    return json.dumps(frame, indent=2, sort_keys=True) + "\n"


def _module_text(module_id: str) -> str:
    return json.dumps(MODULES_BY_ID[module_id], indent=2, sort_keys=True) + "\n"


# ---------------------------------------------------------------------------
# Run builders.
# ---------------------------------------------------------------------------


def _modular_run(tmp_path: Path) -> RunStore:
    TopicStore(tmp_path).save_topic_toml(TID, TOPIC_TOML)
    runs = RunStore(tmp_path)
    runs.create_run(
        TID,
        content_contract=ContentContract.interactive_guide_v1(),
        draft_strategy="modular",
    )
    result = runs.write_topic_spec_prompt(TID)
    result.response_path.write_text(_spec_response(), encoding="utf-8")
    runs.approve_stage(TID, "spec")
    result = runs.write_outline_prompt(TID)
    result.response_path.write_text(_outline_response(), encoding="utf-8")
    runs.approve_stage(TID, "outline")
    return runs


def _frame_prompted(tmp_path: Path) -> RunStore:
    runs = _modular_run(tmp_path)
    runs.write_draft_part_prompts(TID)
    return runs


def _modules_prompted(tmp_path: Path) -> RunStore:
    runs = _frame_prompted(tmp_path)
    runs.ingest_part_response(TID, FRAME, _frame_text(_contract_module_ids(runs)))
    runs.write_draft_part_prompts(TID)
    return runs


def _all_parts_responded(tmp_path: Path) -> RunStore:
    runs = _modules_prompted(tmp_path)
    for module_id in _contract_module_ids(runs):
        runs.ingest_part_response(TID, DraftPart("module", module_id), _module_text(module_id))
    return runs


# ---------------------------------------------------------------------------
# Fake provider: one canned response per part, driven off the prompt path.
# ---------------------------------------------------------------------------


class PartFakeRunner:
    """A fake provider whose canned stdout/exit code varies per draft part.

    ``Invocation.env`` is merged over ``os.environ`` by ``JobRunner._spawn``,
    so a per-job environment is the supported way to make one part's job
    behave differently from its siblings'.
    """

    provider_id = "fake"
    executable = True
    supports_effort = False

    def __init__(self, texts=None, *, delay="0", failing_parts=(), default_text="OK\n"):
        self.texts = dict(texts or {})
        self.delay = delay
        self.failing_parts = set(failing_parts)
        self.default_text = default_text

    def is_available(self):
        return True

    @staticmethod
    def part_name(prompt_path: Path) -> str:
        name = prompt_path.name
        for suffix in (".prompt.md", ".md"):
            if name.endswith(suffix):
                return name[: -len(suffix)]
        return name

    def build_invocation(self, model, plan, prompt_path):
        name = self.part_name(Path(prompt_path))
        env = {
            "FAKE_STDOUT": self.texts.get(name, self.default_text),
            "FAKE_DELAY": self.delay,
            "FAKE_EXIT": "1" if name in self.failing_parts else "0",
        }
        return Invocation(argv=[sys.executable, str(FAKE)], env=env)

    def parse_response(self, stdout):
        return ProviderResponse(text=stdout, metadata={})


def _catalog_and_plan():
    catalog = parse_model_catalog({"providers": [{"id": "fake", "models": [{"id": "m"}]}]})
    plan = parse_model_plan({"provider": "fake", "stages": {"draft": {"model": "m"}}}, catalog)
    return catalog, plan


def _factory(store, runs, *, force=False, timeout=60):
    catalog, plan = _catalog_and_plan()

    def make(job):
        return JobRunner(store, runs, catalog, plan, timeout=timeout, force=force)

    return make


def _module_texts(runs: RunStore) -> dict:
    texts = {module_id: _module_text(module_id) for module_id in _contract_module_ids(runs)}
    texts["frame"] = _frame_text(_contract_module_ids(runs))
    return texts


# ---------------------------------------------------------------------------
# Waiting helpers.
# ---------------------------------------------------------------------------


def _wait_terminal(store, job_id, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        job = store.find(job_id)
        if job is not None and job.status in TERMINAL_STATUSES:
            return job
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} did not reach a terminal state")


def _wait_all_terminal(store, job_ids, timeout=60):
    return {job_id: _wait_terminal(store, job_id, timeout=timeout) for job_id in job_ids}


def _max_concurrent_running(store, topic_id, job_ids, timeout=60):
    """Highest number of simultaneously-``running`` records, sampled to the end.

    Bounded polling: the loop ends when every watched job is terminal, or the
    timeout fires (an assertion, never a hang).
    """

    wanted = set(job_ids)
    high_water = 0
    end = time.time() + timeout
    while time.time() < end:
        records = [job for job in store.list(topic_id) if job.id in wanted]
        high_water = max(high_water, sum(1 for job in records if job.status == "running"))
        if len(records) == len(wanted) and all(
            job.status in TERMINAL_STATUSES for job in records
        ):
            return high_water
        time.sleep(0.01)
    raise AssertionError("batch did not finish within the timeout")


# ---------------------------------------------------------------------------
# Daemon context.
# ---------------------------------------------------------------------------


def _daemon_context(tmp_path: Path, runs: RunStore, *, worker=None):
    catalog, plan = _catalog_and_plan()
    store = JobStore(tmp_path)
    if worker is None:
        worker = Worker(store, _factory(store, runs))
    return (
        DaemonContext(
            root=tmp_path,
            store=store,
            worker=worker,
            runs=runs,
            token="secret-token",
            version="0.1.0",
            config=StaticConfigSource(catalog, plan),
            topics=TopicStore(tmp_path),
            profiles=ProfileStore(tmp_path),
            on_shutdown=lambda: None,
        ),
        store,
        worker,
    )


# ===========================================================================
# new_batch_id
# ===========================================================================


def test_new_batch_id_is_a_single_path_segment_and_unique():
    first = _new_batch_id()
    second = _new_batch_id()
    assert first != second
    for value in (first, second):
        assert value
        assert "/" not in value and "\\" not in value
        assert value not in (".", "..")
        assert Path(value).name == value


# ===========================================================================
# Worker construction and the pool
# ===========================================================================


def test_worker_defaults_to_a_single_pool_thread(tmp_path):
    store = JobStore(tmp_path)
    worker = Worker(store, lambda job: None)
    assert worker.parallelism == 1


@pytest.mark.parametrize("parallelism", [1, 2, 3, 4])
def test_worker_accepts_parallelism_in_range(tmp_path, parallelism):
    store = JobStore(tmp_path)
    worker = _pool(store, lambda job: None, parallelism)
    assert worker.parallelism == parallelism


@pytest.mark.parametrize("parallelism", [0, -1, 5, 99])
def test_worker_rejects_parallelism_outside_one_to_four(tmp_path, parallelism):
    store = JobStore(tmp_path)
    with pytest.raises(ConfigError):
        _pool(store, lambda job: None, parallelism)


def test_stop_with_parallelism_three_joins_every_thread(tmp_path):
    runs = _modules_prompted(tmp_path)
    register_runner(PartFakeRunner(_module_texts(runs)))
    store = JobStore(tmp_path)
    worker = _pool(store, _factory(store, runs), 3)
    worker.start()
    worker.stop()
    # Every pool thread got a sentinel and was joined: none is left alive.
    import threading as _threading

    leftover = [t for t in _threading.enumerate() if t.name.startswith("ep-worker")]
    assert leftover == []


def test_pool_never_runs_more_module_jobs_than_parallelism(tmp_path):
    runs = _modules_prompted(tmp_path)
    module_ids = _contract_module_ids(runs)
    assert len(module_ids) == 3
    register_runner(PartFakeRunner(_module_texts(runs), delay=SLOW_SECONDS))
    store = JobStore(tmp_path)
    worker = _pool(store, _factory(store, runs), 2)
    batch_id = _new_batch_id()
    jobs = [
        _create_part_job(store, TID, DraftPart("module", module_id), batch_id=batch_id)
        for module_id in module_ids
    ]
    worker.start()
    try:
        worker.enqueue_batch(jobs)
        high_water = _max_concurrent_running(store, TID, [job.id for job in jobs])
    finally:
        worker.stop()
    assert high_water == 2, f"expected the pool to saturate at 2, saw {high_water}"
    assert all(_wait_terminal(store, job.id).status == "succeeded" for job in jobs)


def test_one_failing_module_job_leaves_its_siblings_succeeded(tmp_path):
    runs = _modules_prompted(tmp_path)
    module_ids = _contract_module_ids(runs)
    doomed = module_ids[0]
    register_runner(PartFakeRunner(_module_texts(runs), failing_parts=[doomed]))
    store = JobStore(tmp_path)
    worker = _pool(store, _factory(store, runs), 2)
    batch_id = _new_batch_id()
    jobs = {
        module_id: _create_part_job(
            store, TID, DraftPart("module", module_id), batch_id=batch_id
        )
        for module_id in module_ids
    }
    worker.start()
    try:
        worker.enqueue_batch(list(jobs.values()))
        done = _wait_all_terminal(store, [job.id for job in jobs.values()])
    finally:
        worker.stop()
    assert done[jobs[doomed].id].status == "failed"
    for module_id in module_ids[1:]:
        assert done[jobs[module_id].id].status == "succeeded"
        assert runs.draft_part_paths(TID, DraftPart("module", module_id)).response_path.is_file()
    # The failed sibling left no response behind.
    assert not runs.draft_part_paths(TID, DraftPart("module", doomed)).response_path.is_file()


# ===========================================================================
# Admission key (topic, stage, part_key)
# ===========================================================================


def test_two_different_module_parts_are_both_admitted(tmp_path):
    runs = _modules_prompted(tmp_path)
    module_ids = _contract_module_ids(runs)
    store = JobStore(tmp_path)
    worker = Worker(store, _factory(store, runs))
    first = _create_part_job(store, TID, DraftPart("module", module_ids[0]))
    second = _create_part_job(store, TID, DraftPart("module", module_ids[1]))
    worker.enqueue(first)
    worker.enqueue(second)
    ids = {job.id for job in store.list(TID)}
    assert {first.id, second.id} <= ids


def test_a_second_job_for_the_same_module_part_is_refused(tmp_path):
    runs = _modules_prompted(tmp_path)
    module_id = _contract_module_ids(runs)[0]
    store = JobStore(tmp_path)
    worker = Worker(store, _factory(store, runs))
    first = _create_part_job(store, TID, DraftPart("module", module_id))
    worker.enqueue(first)
    second = _create_part_job(store, TID, DraftPart("module", module_id))
    with pytest.raises(ConfigError):
        worker.enqueue(second)
    assert second.id not in {job.id for job in store.list(TID)}


def test_a_part_job_is_refused_while_a_whole_draft_job_is_active(tmp_path):
    runs = _modules_prompted(tmp_path)
    module_id = _contract_module_ids(runs)[0]
    store = JobStore(tmp_path)
    worker = Worker(store, _factory(store, runs))
    whole = store.create(TID, "draft", "fake", "m", None)
    worker.enqueue(whole)
    part_job = _create_part_job(store, TID, DraftPart("module", module_id))
    with pytest.raises(ConfigError):
        worker.enqueue(part_job)


def test_a_whole_draft_job_is_refused_while_a_part_job_is_active(tmp_path):
    runs = _modules_prompted(tmp_path)
    module_id = _contract_module_ids(runs)[0]
    store = JobStore(tmp_path)
    worker = Worker(store, _factory(store, runs))
    part_job = _create_part_job(store, TID, DraftPart("module", module_id))
    worker.enqueue(part_job)
    whole = store.create(TID, "draft", "fake", "m", None)
    with pytest.raises(ConfigError):
        worker.enqueue(whole)


def test_the_frame_part_and_a_module_part_do_not_conflict(tmp_path):
    runs = _modules_prompted(tmp_path)
    module_id = _contract_module_ids(runs)[0]
    store = JobStore(tmp_path)
    worker = Worker(store, _factory(store, runs))
    frame_job = _create_part_job(store, TID, FRAME)
    module_job = _create_part_job(store, TID, DraftPart("module", module_id))
    worker.enqueue(frame_job)
    worker.enqueue(module_job)
    assert {frame_job.id, module_job.id} <= {job.id for job in store.list(TID)}


# ===========================================================================
# enqueue_batch / cancel_batch
# ===========================================================================


def test_enqueue_batch_saves_and_queues_every_member(tmp_path):
    runs = _modules_prompted(tmp_path)
    module_ids = _contract_module_ids(runs)
    store = JobStore(tmp_path)
    worker = Worker(store, _factory(store, runs))
    batch_id = _new_batch_id()
    jobs = [
        _create_part_job(store, TID, DraftPart("module", module_id), batch_id=batch_id)
        for module_id in module_ids
    ]
    worker.enqueue_batch(jobs)
    stored = {job.id: job for job in store.list(TID)}
    assert set(stored) == {job.id for job in jobs}
    assert all(stored[job.id].status == "queued" for job in jobs)
    assert all(stored[job.id].batch_id == batch_id for job in jobs)


def test_enqueue_batch_is_all_or_nothing_and_leaves_no_job_json(tmp_path):
    runs = _modules_prompted(tmp_path)
    module_ids = _contract_module_ids(runs)
    store = JobStore(tmp_path)
    worker = Worker(store, _factory(store, runs))
    # A job for module[1] is already active, so a batch containing it must be
    # refused whole -- including its (otherwise fine) first member.
    blocker = _create_part_job(store, TID, DraftPart("module", module_ids[1]))
    worker.enqueue(blocker)
    batch_id = _new_batch_id()
    jobs = [
        _create_part_job(store, TID, DraftPart("module", module_ids[0]), batch_id=batch_id),
        _create_part_job(store, TID, DraftPart("module", module_ids[1]), batch_id=batch_id),
    ]
    with pytest.raises(ConfigError) as exc:
        worker.enqueue_batch(jobs)
    assert module_ids[1] in str(exc.value)
    stored = {job.id for job in store.list(TID)}
    assert stored == {blocker.id}
    for job in jobs:
        assert not (store.job_dir(TID, job.id) / "job.json").exists()


def test_enqueue_batch_requires_one_shared_batch_id(tmp_path):
    runs = _modules_prompted(tmp_path)
    module_ids = _contract_module_ids(runs)
    store = JobStore(tmp_path)
    worker = Worker(store, _factory(store, runs))
    jobs = [
        _create_part_job(
            store, TID, DraftPart("module", module_id), batch_id=_new_batch_id()
        )
        for module_id in module_ids[:2]
    ]
    with pytest.raises(ConfigError):
        worker.enqueue_batch(jobs)
    assert store.list(TID) == []


def test_enqueue_batch_requires_one_shared_topic_id(tmp_path):
    runs = _modules_prompted(tmp_path)
    module_ids = _contract_module_ids(runs)
    store = JobStore(tmp_path)
    worker = Worker(store, _factory(store, runs))
    batch_id = _new_batch_id()
    mine = _create_part_job(store, TID, DraftPart("module", module_ids[0]), batch_id=batch_id)
    theirs = store.create(
        "other-topic",
        "draft",
        "fake",
        "m",
        None,
        batch_id=batch_id,
        part=DraftPart("module", module_ids[1]).to_manifest(),
    )
    with pytest.raises(ConfigError):
        worker.enqueue_batch([mine, theirs])
    assert store.list(TID) == []


def test_cancel_batch_cancels_every_non_terminal_member(tmp_path):
    runs = _modules_prompted(tmp_path)
    module_ids = _contract_module_ids(runs)
    store = JobStore(tmp_path)
    worker = Worker(store, _factory(store, runs))  # never started: all stay queued
    batch_id = _new_batch_id()
    jobs = [
        _create_part_job(store, TID, DraftPart("module", module_id), batch_id=batch_id)
        for module_id in module_ids
    ]
    worker.enqueue_batch(jobs)
    updated = worker.cancel_batch(TID, batch_id)
    assert {job.id for job in updated} == {job.id for job in jobs}
    assert all(job.status == "canceled" for job in updated)
    assert all(store.find(job.id).status == "canceled" for job in jobs)


def test_cancel_batch_leaves_already_terminal_members_untouched(tmp_path):
    runs = _modules_prompted(tmp_path)
    module_ids = _contract_module_ids(runs)
    store = JobStore(tmp_path)
    worker = Worker(store, _factory(store, runs))
    batch_id = _new_batch_id()
    jobs = [
        _create_part_job(store, TID, DraftPart("module", module_id), batch_id=batch_id)
        for module_id in module_ids[:2]
    ]
    worker.enqueue_batch(jobs)
    finished = jobs[0]
    finished.status = "succeeded"
    store.save(finished)
    worker.cancel_batch(TID, batch_id)
    assert store.find(jobs[0].id).status == "succeeded"
    assert store.find(jobs[1].id).status == "canceled"


def test_cancel_batch_ignores_jobs_from_another_batch(tmp_path):
    runs = _modules_prompted(tmp_path)
    module_ids = _contract_module_ids(runs)
    store = JobStore(tmp_path)
    worker = Worker(store, _factory(store, runs))
    mine = _create_part_job(
        store, TID, DraftPart("module", module_ids[0]), batch_id=_new_batch_id()
    )
    other_batch = _new_batch_id()
    theirs = _create_part_job(
        store, TID, DraftPart("module", module_ids[1]), batch_id=other_batch
    )
    worker.enqueue(mine)
    worker.enqueue(theirs)
    worker.cancel_batch(TID, other_batch)
    assert store.find(mine.id).status == "queued"
    assert store.find(theirs.id).status == "canceled"


def test_reconcile_requeues_batch_members_in_id_order(tmp_path):
    runs = _modules_prompted(tmp_path)
    module_ids = _contract_module_ids(runs)
    register_runner(PartFakeRunner(_module_texts(runs)))
    store = JobStore(tmp_path)
    batch_id = _new_batch_id()
    jobs = []
    for module_id in module_ids:
        job = _create_part_job(store, TID, DraftPart("module", module_id), batch_id=batch_id)
        job.status = "queued"
        store.save(job)
        jobs.append(job)
    worker = _pool(store, _factory(store, runs), 2)
    worker.reconcile()
    worker.start()
    try:
        done = _wait_all_terminal(store, [job.id for job in jobs])
    finally:
        worker.stop()
    assert all(job.status == "succeeded" for job in done.values())


# ===========================================================================
# JobRunner: part prompts, part ingest, part salvage
# ===========================================================================


def test_part_job_ingests_through_ingest_part_response(tmp_path):
    runs = _modules_prompted(tmp_path)
    module_id = _contract_module_ids(runs)[0]
    register_runner(PartFakeRunner(_module_texts(runs)))
    store = JobStore(tmp_path)
    worker = Worker(store, _factory(store, runs))
    job = _create_part_job(store, TID, DraftPart("module", module_id))
    worker.start()
    try:
        worker.enqueue(job)
        done = _wait_terminal(store, job.id)
    finally:
        worker.stop()
    assert done.status == "succeeded", done.error
    expected = runs.run_dir(TID) / "responses" / "draft" / "modules" / f"{module_id}.response.json"
    assert expected.is_file()
    assert Path(done.response_path) == expected
    # The whole-stage draft response is untouched: a part job never writes it.
    assert not runs.stage_paths(TID, "draft").response_path.exists()


def test_part_job_manifest_event_carries_the_part(tmp_path):
    runs = _modules_prompted(tmp_path)
    module_id = _contract_module_ids(runs)[0]
    register_runner(PartFakeRunner(_module_texts(runs)))
    store = JobStore(tmp_path)
    worker = Worker(store, _factory(store, runs))
    job = _create_part_job(store, TID, DraftPart("module", module_id))
    worker.start()
    try:
        worker.enqueue(job)
        assert _wait_terminal(store, job.id).status == "succeeded"
    finally:
        worker.stop()
    events = [
        event
        for event in runs.read_manifest(TID)["events"]
        if isinstance(event, dict) and event.get("action") == "job"
    ]
    assert events, "no job event appended for the part job"
    assert events[-1]["part"] == {"kind": "module", "module_id": module_id}
    assert events[-1]["job_id"] == job.id


def test_frame_part_job_runs_the_frame_prompt(tmp_path):
    runs = _frame_prompted(tmp_path)
    module_ids = _contract_module_ids(runs)
    register_runner(PartFakeRunner({"frame": _frame_text(module_ids)}))
    store = JobStore(tmp_path)
    worker = Worker(store, _factory(store, runs))
    job = _create_part_job(store, TID, FRAME)
    worker.start()
    try:
        worker.enqueue(job)
        done = _wait_terminal(store, job.id)
    finally:
        worker.stop()
    assert done.status == "succeeded", done.error
    assert (runs.run_dir(TID) / "responses" / "draft" / "frame.response.json").is_file()


def test_part_job_salvage_writes_beside_the_part(tmp_path):
    runs = _modules_prompted(tmp_path)
    module_id = _contract_module_ids(runs)[0]
    # Output that ingest_part_response must refuse, so salvage kicks in.
    register_runner(PartFakeRunner({module_id: "this is not a module object\n"}))
    store = JobStore(tmp_path)
    worker = Worker(store, _factory(store, runs))
    job = _create_part_job(store, TID, DraftPart("module", module_id))
    worker.start()
    try:
        worker.enqueue(job)
        done = _wait_terminal(store, job.id)
    finally:
        worker.stop()
    assert done.status == "failed"
    modules_dir = runs.run_dir(TID) / "responses" / "draft" / "modules"
    salvaged = sorted(modules_dir.glob(f"{module_id}.failed.*.txt"))
    assert len(salvaged) == 1, sorted(p.name for p in modules_dir.iterdir())
    assert salvaged[0].read_text(encoding="utf-8") == "this is not a module object\n"
    assert done.metadata.get("salvaged_output") == salvaged[0].name
    # Never beside the whole stage.
    assert list((runs.run_dir(TID) / "responses").glob("draft.failed.*.txt")) == []


# ===========================================================================
# DaemonContext.enqueue_stage / enqueue_draft_batch / cancel_batch
# ===========================================================================


def test_enqueue_stage_refuses_a_modular_draft_and_points_at_the_batch_route(tmp_path):
    runs = _modules_prompted(tmp_path)
    context, _store, _worker = _daemon_context(tmp_path, runs)
    with pytest.raises(ConfigError) as exc:
        context.enqueue_stage(TID, "draft", False)
    assert str(exc.value).startswith("draft_is_modular:")


def test_enqueue_stage_refuses_a_modular_draft_reached_through_next_action(tmp_path):
    runs = _modules_prompted(tmp_path)
    context, _store, _worker = _daemon_context(tmp_path, runs)
    with pytest.raises(ConfigError) as exc:
        context.enqueue_stage(TID, None, False)
    assert str(exc.value).startswith("draft_is_modular:")


def test_enqueue_draft_batch_frame_wave_creates_exactly_one_frame_job(tmp_path):
    runs = _frame_prompted(tmp_path)
    context, store, _worker = _daemon_context(tmp_path, runs)
    jobs = context.enqueue_draft_batch(TID)
    assert len(jobs) == 1
    assert jobs[0].part == {"kind": "frame"}
    assert jobs[0].stage == "draft"
    assert jobs[0].batch_id
    assert store.find(jobs[0].id).status == "queued"


def test_enqueue_draft_batch_refuses_when_the_frame_prompt_is_not_written(tmp_path):
    runs = _modular_run(tmp_path)  # outline approved, no part prompts yet
    context, store, _worker = _daemon_context(tmp_path, runs)
    with pytest.raises(ConfigError) as exc:
        context.enqueue_draft_batch(TID)
    assert "frame prompt" in str(exc.value)
    assert store.list(TID) == []


def test_enqueue_draft_batch_modules_wave_creates_one_job_per_prompted_module(tmp_path):
    runs = _modules_prompted(tmp_path)
    module_ids = _contract_module_ids(runs)
    context, _store, _worker = _daemon_context(tmp_path, runs)
    jobs = context.enqueue_draft_batch(TID)
    assert len(jobs) == len(module_ids)
    assert {job.part["module_id"] for job in jobs} == set(module_ids)
    assert len({job.batch_id for job in jobs}) == 1
    assert all(job.metadata.get("force") is False for job in jobs)
    assert all(job.metadata.get("plan_source") == "default" for job in jobs)


def test_enqueue_draft_batch_honours_a_parts_subset(tmp_path):
    runs = _modules_prompted(tmp_path)
    wanted = _contract_module_ids(runs)[1]
    context, _store, _worker = _daemon_context(tmp_path, runs)
    jobs = context.enqueue_draft_batch(TID, parts=[wanted])
    assert [job.part for job in jobs] == [{"kind": "module", "module_id": wanted}]


def test_enqueue_draft_batch_rejects_frame_inside_parts(tmp_path):
    runs = _modules_prompted(tmp_path)
    context, store, _worker = _daemon_context(tmp_path, runs)
    with pytest.raises(ConfigError):
        context.enqueue_draft_batch(TID, parts=["frame"])
    assert store.list(TID) == []


def test_enqueue_draft_batch_rejects_an_unknown_module_in_parts(tmp_path):
    runs = _modules_prompted(tmp_path)
    context, store, _worker = _daemon_context(tmp_path, runs)
    with pytest.raises(ConfigError):
        context.enqueue_draft_batch(TID, parts=["no-such-module"])
    assert store.list(TID) == []


def test_enqueue_draft_batch_refuses_once_the_draft_is_assembled(tmp_path):
    runs = _all_parts_responded(tmp_path)
    runs.assemble_draft(TID)
    context, store, _worker = _daemon_context(tmp_path, runs)
    with pytest.raises(ConfigError) as exc:
        context.enqueue_draft_batch(TID)
    assert "nothing to run" in str(exc.value)
    assert store.list(TID) == []


def test_enqueue_draft_batch_refuses_while_a_draft_job_is_active(tmp_path):
    runs = _modules_prompted(tmp_path)
    context, store, _worker = _daemon_context(tmp_path, runs)
    first = context.enqueue_draft_batch(TID)
    assert first
    with pytest.raises(ConfigError):
        context.enqueue_draft_batch(TID)


def test_enqueue_draft_batch_refuses_an_archived_course(tmp_path):
    runs = _modules_prompted(tmp_path)
    runs.archive_run(TID)
    context, store, _worker = _daemon_context(tmp_path, runs)
    with pytest.raises(write_api.ConflictError) as exc:
        context.enqueue_draft_batch(TID)
    assert exc.value.code == "archived_course"
    assert store.list(TID) == []


def test_enqueue_draft_batch_with_force_stamps_the_jobs(tmp_path):
    runs = _modules_prompted(tmp_path)
    context, _store, _worker = _daemon_context(tmp_path, runs)
    jobs = context.enqueue_draft_batch(TID, force=True)
    assert jobs
    assert all(job.metadata.get("force") is True for job in jobs)


def test_context_cancel_batch_cancels_the_whole_batch(tmp_path):
    runs = _modules_prompted(tmp_path)
    context, store, _worker = _daemon_context(tmp_path, runs)
    jobs = context.enqueue_draft_batch(TID)
    canceled = context.cancel_batch(TID, jobs[0].batch_id)
    assert {job.id for job in canceled} == {job.id for job in jobs}
    assert all(store.find(job.id).status == "canceled" for job in jobs)
