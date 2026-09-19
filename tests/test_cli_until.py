"""Tests for ``run <topic> --until approval`` and ``queue ...`` (T31).

Reuses ``tests/test_cli.py``'s helpers (``_run``, ``_seed_topic_to_draft``,
the in-thread live-daemon pattern) via ``import test_cli`` per
``docs/superpowers/plans/2026-09-18-phase-3-headless.md`` (T31 row).
``test_cli.py`` itself is not edited.
"""

from __future__ import annotations

import re
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

import test_cli
import test_draft_units as tdu
import test_server_chain
from education_pipeline import ContentContract, RunStore
from education_pipeline.client import ensure_daemon
from education_pipeline.daemon import serve
from education_pipeline.providers import Invocation, ProviderResponse, register_runner


# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------


class _ScriptedRunner:
    """A ``fake`` provider runner whose exit code can vary per topic.

    ``calls`` records the topic id of every ``build_invocation`` call, in
    order, so a test can pin exactly which (and how many) draft jobs ran.
    ``exit_codes`` maps a topic id to the ``FAKE_EXIT`` value its job should
    use (default: succeed with ``FAKE_STDOUT``'s canned draft).
    """

    provider_id = "fake"
    executable = True

    def __init__(self, exit_codes: dict[str, str] | None = None) -> None:
        self.exit_codes = exit_codes or {}
        self.calls: list[str] = []

    def is_available(self) -> bool:
        return True

    def build_invocation(self, model, plan, prompt_path):
        # <root>/runs/<topic_id>/prompts/<stage>.prompt.md
        topic_id = Path(prompt_path).parent.parent.name
        self.calls.append(topic_id)
        fake = Path(__file__).parent / "fake_provider.py"
        env = {"FAKE_STDOUT": "# Generated draft\n"}
        exit_code = self.exit_codes.get(topic_id)
        if exit_code is not None:
            env["FAKE_EXIT"] = exit_code
        return Invocation(argv=[sys.executable, str(fake)], env=env)

    def parse_response(self, stdout):
        return ProviderResponse(text=stdout, metadata={})


@pytest.fixture
def live_daemon(monkeypatch):
    """Route the daemon's autostart Popen to an in-thread ``serve()`` call.

    Mirrors ``test_cli.test_run_wait_executes_and_lands_response``: the
    daemon must run in *this* process so the ``fake`` runner registered by a
    test is visible to job execution, while the worker's own subprocess
    calls (the fake provider script) go through unmodified.
    """

    real_popen = subprocess.Popen

    def _thread_popen(argv, **kwargs):
        if len(argv) >= 3 and argv[1:3] == ["-m", "education_pipeline.daemon"]:
            root = argv[-1]
            ready = threading.Event()
            threading.Thread(
                target=serve, args=(root,), kwargs={"ready": ready}, daemon=True
            ).start()
            ready.wait(timeout=5)
            return None
        return real_popen(argv, **kwargs)

    monkeypatch.setattr("education_pipeline.client.subprocess.Popen", _thread_popen)


def _write_fake_plan(ws: Path) -> None:
    cfg = ws / "config"
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "model-catalog.toml").write_text(
        '[[providers]]\nid = "fake"\n[[providers.models]]\nid = "m"\n', encoding="utf-8"
    )
    (cfg / "model-plan.toml").write_text(
        'provider = "fake"\n[stages.draft]\nmodel = "m"\n', encoding="utf-8"
    )


def _write_manual_plan(ws: Path) -> None:
    cfg = ws / "config"
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "model-catalog.toml").write_text('[[providers]]\nid = "manual"\n', encoding="utf-8")
    (cfg / "model-plan.toml").write_text('provider = "manual"\n', encoding="utf-8")


def _seed_topic(ws: Path, topic_id: str) -> None:
    """Like ``test_cli._seed_topic_to_draft`` but for an arbitrary topic id."""

    from education_pipeline.topics import load_topic
    from education_pipeline.workspace import TopicStore

    ws.mkdir(parents=True, exist_ok=True)
    topic_toml = ws / f"_seed-{topic_id}.toml"
    topic_toml.write_text(
        "schema_version = 1\n"
        f'id = "{topic_id}"\n'
        f'title = "{topic_id}"\n'
        'brief = "A public introduction to feedback loops."\n'
        'goals = ["explain feedback loops"]\n',
        encoding="utf-8",
    )
    topic = load_topic(topic_toml)
    TopicStore(ws).import_topic(topic.id, topic_toml, overwrite=True)

    runs = RunStore(ws)
    runs.create_run(topic_id, content_contract=ContentContract.legacy_markdown())
    runs.write_spec_prompt(topic_id, title=topic_id)
    runs.response_path(topic_id, "spec").write_text("# Spec\n", encoding="utf-8")
    runs.approve_stage(topic_id, "spec")
    runs.write_outline_prompt(topic_id)
    runs.response_path(topic_id, "outline").write_text("# Outline\n", encoding="utf-8")
    runs.approve_stage(topic_id, "outline")
    runs.write_draft_prompt(topic_id)


def _nonblank(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# 1. --until parser contract
# ---------------------------------------------------------------------------


def test_run_until_choices_rejects_unknown_value(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as excinfo:
        test_cli._run(tmp_path, "run", "sometopic", "--until", "bogus")
    assert excinfo.value.code == 2


def test_run_until_conflicts_with_stage(tmp_path: Path, capsys) -> None:
    code = test_cli._run(
        tmp_path, "run", "sometopic", "--until", "approval", "--stage", "outline"
    )
    assert code == 2
    assert (
        "error: --until cannot be combined with --stage/--modules"
        in capsys.readouterr().err
    )


def test_run_until_conflicts_with_modules(tmp_path: Path, capsys) -> None:
    code = test_cli._run(
        tmp_path, "run", "sometopic", "--until", "approval", "--modules", "m1"
    )
    assert code == 2
    assert (
        "error: --until cannot be combined with --stage/--modules"
        in capsys.readouterr().err
    )


# ---------------------------------------------------------------------------
# 2-4. Live-daemon: run --until approval
# ---------------------------------------------------------------------------


def test_run_until_approval_lands_draft_and_stops_at_approve(
    tmp_path: Path, live_daemon, capsys
) -> None:
    runner = _ScriptedRunner()
    register_runner(runner)
    _write_fake_plan(tmp_path)
    test_cli._seed_topic_to_draft(tmp_path)
    ensure_daemon(tmp_path, autostart=True)

    code = test_cli._run(tmp_path, "run", "systems-thinking", "--until", "approval")
    lines = _nonblank(capsys.readouterr().out)

    assert code == 0
    assert "  - ran draft with fake" in lines
    assert lines[-1] == "run: draft needs your approval"

    assert (
        RunStore(tmp_path).response_path("systems-thinking", "draft").read_text(
            encoding="utf-8"
        )
        == "# Generated draft\n"
    )
    next_action = RunStore(tmp_path).run_status("systems-thinking").next_action
    assert next_action.action == "approve"
    assert next_action.stage == "draft"

    test_cli._run(tmp_path, "daemon", "stop")


def test_run_until_approval_drives_a_guide_run_from_skeleton_to_approve(
    tmp_path: Path, live_daemon, capsys
) -> None:
    """Decision 6 left the CLI untested on a guide-v1 course; T33's stall-guard
    fix is what makes this work. From nothing drafted, one ``run --until
    approval`` runs the skeleton job, then the module batch the skeleton's
    ingest unlocks, and stops at the draft approval gate with the draft
    assembled -- the same chain the daemon now carries for the cockpit.

    Before the fix (a stall guard comparing only ``(action, stage)``) this
    stopped after the skeleton job with "the job finished but no response was
    saved", because the module batch's next action is ``save_response``/
    ``draft`` again with a different detail.
    """

    register_runner(test_server_chain.ChainFakeRunner())
    _write_fake_plan(tmp_path)
    tdu._run_with_skeleton_prompt(tmp_path)
    ensure_daemon(tmp_path, autostart=True)

    code = test_cli._run(tmp_path, "run", tdu.TID, "--until", "approval")
    lines = _nonblank(capsys.readouterr().out)

    # One skeleton job, then the whole module batch, from a single command.
    assert code == 0
    assert lines == [
        "  - ran draft with fake",
        f"  - ran {len(tdu.MODULE_ORDER)} module jobs for draft with fake",
        "run: draft needs your approval",
    ]

    runs = RunStore(tmp_path)
    assert runs.response_path(tdu.TID, "draft").exists()
    next_action = runs.run_status(tdu.TID).next_action
    assert next_action.action == "approve"
    assert next_action.stage == "draft"

    test_cli._run(tmp_path, "daemon", "stop")


def test_run_until_approval_reports_failed_job(
    tmp_path: Path, live_daemon, capsys
) -> None:
    runner = _ScriptedRunner(exit_codes={"systems-thinking": "1"})
    register_runner(runner)
    _write_fake_plan(tmp_path)
    test_cli._seed_topic_to_draft(tmp_path)
    ensure_daemon(tmp_path, autostart=True)

    code = test_cli._run(tmp_path, "run", "systems-thinking", "--until", "approval")
    lines = _nonblank(capsys.readouterr().out)

    assert code == 1
    assert lines[-1].startswith("run: running draft with fake failed: ")

    test_cli._run(tmp_path, "daemon", "stop")


def test_run_until_approval_stops_for_manual_provider(
    tmp_path: Path, live_daemon, capsys
) -> None:
    _write_manual_plan(tmp_path)
    test_cli._seed_topic_to_draft(tmp_path)
    client = ensure_daemon(tmp_path, autostart=True)

    code = test_cli._run(tmp_path, "run", "systems-thinking", "--until", "approval")
    lines = _nonblank(capsys.readouterr().out)

    assert code == 0
    assert lines[-1] == "run: the draft prompt is ready for you to run"
    assert client.list_jobs("systems-thinking") == []

    test_cli._run(tmp_path, "daemon", "stop")


# ---------------------------------------------------------------------------
# 5-7. queue add / list / remove
# ---------------------------------------------------------------------------


def test_queue_add_topic_without_a_run_fails(tmp_path: Path, capsys) -> None:
    code = test_cli._run(tmp_path, "queue", "add", "no-such-topic")
    assert code == 1
    assert "error:" in capsys.readouterr().err


def test_queue_add_seeded_topic_writes_a_queued_entry(tmp_path: Path, capsys) -> None:
    test_cli._seed_topic_to_draft(tmp_path)

    code = test_cli._run(tmp_path, "queue", "add", "systems-thinking")

    assert code == 0
    assert capsys.readouterr().out.strip() == "queue: added systems-thinking"

    from education_pipeline.course_queue import load_queue

    queue = load_queue(tmp_path)
    assert len(queue.entries) == 1
    assert queue.entries[0].topic_id == "systems-thinking"
    assert queue.entries[0].status == "queued"
    assert (tmp_path / "queue" / "courses.json").exists()


def test_queue_add_again_requeues_the_same_entry(tmp_path: Path, capsys) -> None:
    test_cli._seed_topic_to_draft(tmp_path)
    test_cli._run(tmp_path, "queue", "add", "systems-thinking")
    capsys.readouterr()

    code = test_cli._run(tmp_path, "queue", "add", "systems-thinking")

    assert code == 0
    assert capsys.readouterr().out.strip() == "queue: re-queued systems-thinking"

    from education_pipeline.course_queue import load_queue

    assert len(load_queue(tmp_path).entries) == 1


def test_queue_list_empty_queue(tmp_path: Path, capsys) -> None:
    code = test_cli._run(tmp_path, "queue", "list")
    assert code == 0
    assert capsys.readouterr().out.strip() == "queue: empty"


def test_queue_list_shows_topic_status_and_stop_phrase(tmp_path: Path, capsys) -> None:
    from education_pipeline.course_queue import CourseQueue, add_entry, mark_stopped, save_queue
    from education_pipeline.orchestrate import Stop, describe_stop, stop_payload

    queue = add_entry(CourseQueue(entries=()), "a", now="2026-09-18T00:00:00Z")
    queue = add_entry(queue, "b", now="2026-09-18T00:00:00Z")
    stop = Stop(kind="approve", stage="draft")
    queue = mark_stopped(queue, "b", stop_payload(stop), now="2026-09-18T00:01:00Z")
    save_queue(tmp_path, queue)

    code = test_cli._run(tmp_path, "queue", "list")
    lines = _nonblank(capsys.readouterr().out)

    assert code == 0
    assert len(lines) == 2
    fields = [re.split(r"\s{2,}", line.strip()) for line in lines]
    assert fields[0][0] == "a"
    assert fields[0][1] == "queued"
    assert fields[0][2] == "-"
    assert fields[1][0] == "b"
    assert fields[1][1] == "stopped"
    assert fields[1][2] == describe_stop(stop)


def test_queue_remove_known_topic(tmp_path: Path, capsys) -> None:
    test_cli._seed_topic_to_draft(tmp_path)
    test_cli._run(tmp_path, "queue", "add", "systems-thinking")
    capsys.readouterr()

    code = test_cli._run(tmp_path, "queue", "remove", "systems-thinking")

    assert code == 0
    assert capsys.readouterr().out.strip() == "queue: removed systems-thinking"

    from education_pipeline.course_queue import load_queue

    assert load_queue(tmp_path).entries == ()


def test_queue_remove_unknown_topic_fails(tmp_path: Path, capsys) -> None:
    code = test_cli._run(tmp_path, "queue", "remove", "nope")
    assert code == 1
    assert "error:" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# 8-9. queue run
# ---------------------------------------------------------------------------


def test_queue_run_processes_pending_entries_in_order_skipping_stopped(
    tmp_path: Path, live_daemon, capsys
) -> None:
    from education_pipeline.course_queue import load_queue, mark_stopped, save_queue

    runner = _ScriptedRunner()
    register_runner(runner)
    _write_fake_plan(tmp_path)
    for topic_id in ("topic-a", "topic-b", "topic-c"):
        _seed_topic(tmp_path, topic_id)
    test_cli._run(tmp_path, "queue", "add", "topic-a")
    test_cli._run(tmp_path, "queue", "add", "topic-b")
    test_cli._run(tmp_path, "queue", "add", "topic-c")
    capsys.readouterr()

    queue = load_queue(tmp_path)
    queue = mark_stopped(queue, "topic-c", {"kind": "done"}, now="2026-09-18T00:00:00Z")
    save_queue(tmp_path, queue)
    c_before = next(e for e in load_queue(tmp_path).entries if e.topic_id == "topic-c")

    ensure_daemon(tmp_path, autostart=True)
    code = test_cli._run(tmp_path, "queue", "run")
    lines = _nonblank(capsys.readouterr().out)

    assert code == 0
    assert lines == [
        "queue: topic-a: draft needs your approval",
        "queue: topic-b: draft needs your approval",
    ]
    assert runner.calls == ["topic-a", "topic-b"]

    after = {e.topic_id: e for e in load_queue(tmp_path).entries}
    assert after["topic-a"].status == "stopped"
    assert after["topic-a"].stop["kind"] == "approve"
    assert after["topic-b"].status == "stopped"
    assert after["topic-b"].stop["kind"] == "approve"
    # the already-stopped third entry was left untouched
    assert after["topic-c"].updated_at == c_before.updated_at

    test_cli._run(tmp_path, "daemon", "stop")


def test_queue_run_reruns_an_entry_marked_running(
    tmp_path: Path, live_daemon, capsys
) -> None:
    from education_pipeline.course_queue import CourseQueue, add_entry, load_queue, mark_running, save_queue

    runner = _ScriptedRunner()
    register_runner(runner)
    _write_fake_plan(tmp_path)
    _seed_topic(tmp_path, "topic-a")

    queue = add_entry(CourseQueue(entries=()), "topic-a", now="2026-09-18T00:00:00Z")
    queue = mark_running(queue, "topic-a", now="2026-09-18T00:00:01Z")
    save_queue(tmp_path, queue)

    ensure_daemon(tmp_path, autostart=True)
    code = test_cli._run(tmp_path, "queue", "run")

    assert code == 0
    assert runner.calls == ["topic-a"]

    after = load_queue(tmp_path).entries[0]
    assert after.status == "stopped"
    assert after.stop["kind"] == "approve"

    test_cli._run(tmp_path, "daemon", "stop")


def test_queue_run_exits_1_on_failure_but_lands_earlier_entries(
    tmp_path: Path, live_daemon, capsys
) -> None:
    from education_pipeline.course_queue import load_queue

    runner = _ScriptedRunner(exit_codes={"topic-b": "1"})
    register_runner(runner)
    _write_fake_plan(tmp_path)
    _seed_topic(tmp_path, "topic-a")
    _seed_topic(tmp_path, "topic-b")
    test_cli._run(tmp_path, "queue", "add", "topic-a")
    test_cli._run(tmp_path, "queue", "add", "topic-b")
    capsys.readouterr()

    ensure_daemon(tmp_path, autostart=True)
    code = test_cli._run(tmp_path, "queue", "run")

    assert code == 1

    after = {e.topic_id: e for e in load_queue(tmp_path).entries}
    assert after["topic-a"].status == "stopped"
    assert after["topic-a"].stop["kind"] == "approve"
    assert after["topic-b"].status == "stopped"
    assert after["topic-b"].stop["kind"] == "failed"

    test_cli._run(tmp_path, "daemon", "stop")


def test_queue_run_on_empty_queue(tmp_path: Path, capsys) -> None:
    code = test_cli._run(tmp_path, "queue", "run")
    assert code == 0
    assert capsys.readouterr().out.strip() == "queue: empty"


def test_queue_run_marks_the_entry_running_on_disk_before_driving_it(
    tmp_path: Path, live_daemon, capsys
) -> None:
    """The ``running`` mark is written *before* the course is driven.

    That write is the whole recovery story for an interrupted ``queue run``
    (decision 7): a course killed mid-flight has to be distinguishable on
    disk from one that was never started. Observed from inside the provider
    job, which only runs while the course is being driven.
    """

    from education_pipeline.course_queue import load_queue

    seen: list[str] = []

    class _SnapshotRunner(_ScriptedRunner):
        def build_invocation(self, model, plan, prompt_path):
            seen.append(load_queue(tmp_path).entries[0].status)
            return super().build_invocation(model, plan, prompt_path)

    register_runner(_SnapshotRunner())
    _write_fake_plan(tmp_path)
    _seed_topic(tmp_path, "topic-a")
    test_cli._run(tmp_path, "queue", "add", "topic-a")
    capsys.readouterr()

    ensure_daemon(tmp_path, autostart=True)
    code = test_cli._run(tmp_path, "queue", "run")

    assert code == 0
    assert seen == ["running"]
    assert load_queue(tmp_path).entries[0].status == "stopped"

    test_cli._run(tmp_path, "daemon", "stop")


# ---------------------------------------------------------------------------
# Codex round 1, F2: queue edits made during a pass survive it.
#
# ``_cmd_queue_run`` keeps one in-memory ``CourseQueue`` for the whole pass
# and overwrites the file with it after each course's ``mark_running``/
# ``mark_stopped``, so an edit another client makes to the file *during* the
# course being driven is silently clobbered by that overwrite. Every
# transition should instead reload the file first and apply the transition
# to what it finds there. Observed the same way as the existing
# mark-running test: from inside the provider job.
# ---------------------------------------------------------------------------


def test_queue_run_preserves_an_entry_added_by_another_process_mid_pass(
    tmp_path: Path, live_daemon, capsys
) -> None:
    from education_pipeline.course_queue import add_entry, load_queue, save_queue

    class _AddingRunner(_ScriptedRunner):
        def build_invocation(self, model, plan, prompt_path):
            save_queue(
                tmp_path,
                add_entry(load_queue(tmp_path), "topic-c", now="2026-09-19T00:00:00+00:00"),
            )
            return super().build_invocation(model, plan, prompt_path)

    register_runner(_AddingRunner())
    _write_fake_plan(tmp_path)
    _seed_topic(tmp_path, "topic-a")
    test_cli._run(tmp_path, "queue", "add", "topic-a")
    capsys.readouterr()

    ensure_daemon(tmp_path, autostart=True)
    code = test_cli._run(tmp_path, "queue", "run")

    assert code == 0
    entries = {e.topic_id: e for e in load_queue(tmp_path).entries}
    assert "topic-c" in entries, "an entry added while topic-a was driven must survive the pass"
    assert entries["topic-c"].status == "queued"

    test_cli._run(tmp_path, "daemon", "stop")


def test_queue_run_leaves_a_concurrently_removed_running_entry_absent(
    tmp_path: Path, live_daemon, capsys
) -> None:
    from education_pipeline.course_queue import load_queue, remove_entry, save_queue

    class _RemovingRunner(_ScriptedRunner):
        def build_invocation(self, model, plan, prompt_path):
            save_queue(tmp_path, remove_entry(load_queue(tmp_path), "topic-a"))
            return super().build_invocation(model, plan, prompt_path)

    register_runner(_RemovingRunner())
    _write_fake_plan(tmp_path)
    _seed_topic(tmp_path, "topic-a")
    test_cli._run(tmp_path, "queue", "add", "topic-a")
    capsys.readouterr()

    ensure_daemon(tmp_path, autostart=True)
    code = test_cli._run(tmp_path, "queue", "run")

    assert code == 0
    entries = load_queue(tmp_path).entries
    assert all(e.topic_id != "topic-a" for e in entries), (
        "a course removed from the queue while it was running must not be "
        "written back by the pass that was driving it"
    )

    test_cli._run(tmp_path, "daemon", "stop")


def test_queue_run_skips_driving_a_concurrently_removed_next_entry(
    tmp_path: Path, live_daemon, capsys
) -> None:
    from education_pipeline.course_queue import load_queue, remove_entry, save_queue

    class _RemovingNextRunner(_ScriptedRunner):
        def build_invocation(self, model, plan, prompt_path):
            topic_id = Path(prompt_path).parent.parent.name
            if topic_id == "topic-a":
                save_queue(tmp_path, remove_entry(load_queue(tmp_path), "topic-b"))
            return super().build_invocation(model, plan, prompt_path)

    runner = _RemovingNextRunner()
    register_runner(runner)
    _write_fake_plan(tmp_path)
    _seed_topic(tmp_path, "topic-a")
    _seed_topic(tmp_path, "topic-b")
    test_cli._run(tmp_path, "queue", "add", "topic-a")
    test_cli._run(tmp_path, "queue", "add", "topic-b")
    capsys.readouterr()

    ensure_daemon(tmp_path, autostart=True)
    code = test_cli._run(tmp_path, "queue", "run")

    assert code == 0
    assert runner.calls == ["topic-a"], "topic-b was removed before its turn; it must not be driven"
    entries = load_queue(tmp_path).entries
    assert all(e.topic_id != "topic-b" for e in entries)

    test_cli._run(tmp_path, "daemon", "stop")


# ---------------------------------------------------------------------------
# 10. The blocking job runner on a draft fan-out
# ---------------------------------------------------------------------------


class _BatchClient:
    """A ``DaemonClient`` stand-in whose enqueue answers with one batch."""

    def __init__(self, statuses: list[str]) -> None:
        self.jobs = [
            {"id": f"j{index}", "module_id": f"m{index}", "status": status}
            for index, status in enumerate(statuses, start=1)
        ]

    def enqueue(self, topic_id, **kwargs):
        return {"id": "j1", "stage": "draft", "batch_id": "b1", "jobs": self.jobs}

    def get_batch(self, batch_id):
        assert batch_id == "b1"
        return {"jobs": self.jobs}


def test_blocking_runner_reports_a_whole_batch_success() -> None:
    from education_pipeline import cli

    outcome = cli._blocking_job_runner(_BatchClient(["succeeded", "succeeded"]))(
        "topic-a", "draft"
    )

    assert outcome.waited is True
    assert outcome.ok is True
    assert outcome.count == 2
    assert outcome.message is None


def test_blocking_runner_fails_a_batch_with_one_failed_module() -> None:
    """One dead module is a failed draft: the assembled guide would be short a
    module, so the loop must stop rather than carry on to validation."""

    from education_pipeline import cli

    outcome = cli._blocking_job_runner(_BatchClient(["succeeded", "failed"]))(
        "topic-a", "draft"
    )

    assert outcome.ok is False
    assert outcome.count == 2
    assert "m2" in (outcome.message or "")


# ---------------------------------------------------------------------------
# Codex round 1, F4: the CLI's blocking runner reports the *terminal* job's
# provider, not the one it enqueued with -- a run override or the global
# plan can change while the job sat queued, and ``JobRunner.execute`` already
# re-stamps the job record with whatever actually ran (jobs.py:449-459); the
# blocking runner just never reads that field back.
# ---------------------------------------------------------------------------


class _SingleJobClient:
    """A ``DaemonClient`` stand-in whose terminal job names a different
    provider than the one it was enqueued with."""

    def __init__(self, enqueued_provider: str, terminal_provider: str) -> None:
        self.enqueued_provider = enqueued_provider
        self.terminal_provider = terminal_provider
        self.get_job_calls = 0

    def enqueue(self, topic_id, **kwargs):
        return {"id": "j1", "stage": "draft", "provider": self.enqueued_provider}

    def get_job(self, job_id):
        self.get_job_calls += 1
        return {"id": job_id, "status": "succeeded", "provider": self.terminal_provider}


def test_blocking_runner_reports_the_terminal_jobs_provider_not_the_enqueued_one() -> None:
    from education_pipeline import cli

    client = _SingleJobClient(enqueued_provider="claude-code", terminal_provider="codex")
    outcome = cli._blocking_job_runner(client)("topic-a", "draft")

    assert outcome.ok is True
    assert outcome.provider == "codex"


class _BatchClientWithProvider(_BatchClient):
    def __init__(self, statuses: list[str], provider: str) -> None:
        super().__init__(statuses)
        for job in self.jobs:
            job["provider"] = provider


def test_blocking_runner_batch_reports_the_modules_provider() -> None:
    from education_pipeline import cli

    client = _BatchClientWithProvider(["succeeded", "succeeded"], "codex")
    outcome = cli._blocking_job_runner(client)("topic-a", "draft")

    assert outcome.ok is True
    assert outcome.provider == "codex"


# ---------------------------------------------------------------------------
# Codex round 1, F4 (end to end): a plan edited while a job sits queued
# behind another one governs what actually runs (jobs.py's "re-stamp with
# the effective stage plan" comment) -- but ``run --until`` still names the
# provider it resolved before enqueueing. A second, ordinary job occupies
# the worker's single slot for an ordinary (non-batch) job so "prov-a"'s job
# is still queued when the plan is rewritten underneath it.
# ---------------------------------------------------------------------------


class _TimedRunner:
    """Like ``_ScriptedRunner``, but a topic can be given its own
    ``FAKE_DELAY`` so a test can hold the worker's one ordinary-job slot open
    while it edits the plan file."""

    executable = True

    def __init__(self, provider_id: str, delays: dict[str, float] | None = None) -> None:
        self.provider_id = provider_id
        self.delays = delays or {}
        self.calls: list[str] = []

    def is_available(self) -> bool:
        return True

    def build_invocation(self, model, plan, prompt_path):
        topic_id = Path(prompt_path).parent.parent.name
        self.calls.append(topic_id)
        fake = Path(__file__).parent / "fake_provider.py"
        env = {"FAKE_STDOUT": "# Generated draft\n"}
        delay = self.delays.get(topic_id)
        if delay:
            env["FAKE_DELAY"] = str(delay)
        return Invocation(argv=[sys.executable, str(fake)], env=env)

    def parse_response(self, stdout):
        return ProviderResponse(text=stdout, metadata={})


def _write_two_provider_plan(ws: Path) -> None:
    cfg = ws / "config"
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "model-catalog.toml").write_text(
        '[[providers]]\nid = "fake"\n[[providers.models]]\nid = "m"\n'
        '[[providers]]\nid = "fake2"\n[[providers.models]]\nid = "m"\n',
        encoding="utf-8",
    )
    (cfg / "model-plan.toml").write_text(
        'provider = "fake"\n[stages.draft]\nprovider = "fake"\nmodel = "m"\n',
        encoding="utf-8",
    )


def test_run_until_reports_the_terminal_jobs_provider_after_a_mid_flight_plan_edit(
    tmp_path: Path, live_daemon, capsys
) -> None:
    register_runner(_TimedRunner("fake", delays={"blocker": 1.5}))
    register_runner(_TimedRunner("fake2"))
    _write_two_provider_plan(tmp_path)
    _seed_topic(tmp_path, "blocker")
    _seed_topic(tmp_path, "prov-a")

    from education_pipeline.client import DaemonClient, ensure_daemon as _ensure

    _ensure(tmp_path, autostart=True)
    client: DaemonClient = _ensure(tmp_path, autostart=False)
    # Occupy the worker's one ordinary-job slot so "prov-a"'s job stays
    # queued while the plan is edited underneath it.
    client.enqueue("blocker")

    def _edit_plan_after_a_beat() -> None:
        time.sleep(0.3)
        (tmp_path / "config" / "model-plan.toml").write_text(
            'provider = "fake"\n[stages.draft]\nprovider = "fake2"\nmodel = "m"\n',
            encoding="utf-8",
        )

    editor = threading.Thread(target=_edit_plan_after_a_beat)
    editor.start()
    capsys.readouterr()
    code = test_cli._run(tmp_path, "run", "prov-a", "--until", "approval")
    editor.join()

    assert code == 0
    out = capsys.readouterr().out
    assert "with fake2" in out, (
        f"expected the job's actual provider (fake2, resolved when the "
        f"worker picked it up) in the output, got:\n{out}"
    )

    test_cli._run(tmp_path, "daemon", "stop")
