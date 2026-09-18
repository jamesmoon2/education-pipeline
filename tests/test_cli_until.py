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
from pathlib import Path

import pytest

import test_cli
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
