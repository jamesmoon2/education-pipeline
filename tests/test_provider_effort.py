"""Pin the model-plan `effort` field (low/medium/high) all the way through
to the provider CLIs it is meant to steer.

Research (2026-09-17), sources cited in the T08 report:
  - Claude Code CLI accepts a top-level ``--effort`` flag (values: low,
    medium, high, xhigh, max, ultracode) — https://code.claude.com/docs/en/cli-reference
  - Codex CLI accepts a ``model_reasoning_effort`` config key (values:
    minimal, low, medium, high, xhigh) settable non-interactively via a
    ``-c``/``--config`` TOML override, e.g. ``-c model_reasoning_effort="high"``
    — https://developers.openai.com/codex/config-reference and
    https://developers.openai.com/codex/config-advanced

Both adapters already receive the effective per-stage effort: the worker
(``daemon/jobs.py`` ``JobRunner.execute``) calls
``runner.build_invocation(model, stage_plan, prompt_path)`` where
``stage_plan`` is a :class:`~education_pipeline.config.StageModelPlan`
carrying ``.effort`` directly (config.py:82). No new ``effort=`` keyword is
needed on ``build_invocation`` — the adapters simply never read
``plan.effort``. This file also pins a new ``supports_effort`` capability
flag (assumed name) so the cockpit can hide the effort control for a
provider whose CLI has no such option.
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest

from education_pipeline import (
    ContentContract,
    ModelOption,
    RunStore,
    StageModelPlan,
    parse_model_catalog,
    parse_model_plan,
)
from education_pipeline.daemon.jobs import JobRunner, JobStore
from education_pipeline.providers import Invocation, ProviderResponse, get_runner, register_runner


def _plan(stage: str = "draft", provider: str = "claude-code", effort: str | None = None) -> StageModelPlan:
    return StageModelPlan(
        stage=stage,
        recommendation="x",
        model="premium",
        provider=provider,
        effort=effort,
    )


# ---------------------------------------------------------------------------
# Claude Code adapter: --effort <value>
# ---------------------------------------------------------------------------


def test_claude_code_build_invocation_includes_effort_flag_when_set():
    runner = get_runner("claude-code")
    option = ModelOption(id="premium", label="Premium", argv_model="claude-opus-4-8")
    inv = runner.build_invocation(option, _plan(effort="high"), Path("/ws/prompt.md"))
    assert "--effort" in inv.argv
    assert inv.argv[inv.argv.index("--effort") + 1] == "high"


def test_claude_code_build_invocation_omits_effort_flag_when_none():
    runner = get_runner("claude-code")
    option = ModelOption(id="premium", label="Premium", argv_model="claude-opus-4-8")
    inv = runner.build_invocation(option, _plan(effort=None), Path("/ws/prompt.md"))
    assert "--effort" not in inv.argv


# ---------------------------------------------------------------------------
# Codex adapter: -c model_reasoning_effort="<value>"
# ---------------------------------------------------------------------------


def test_codex_build_invocation_includes_reasoning_effort_override_when_set():
    runner = get_runner("codex")
    option = ModelOption(id="balanced", label="Balanced", argv_model="gpt-5.4-codex")
    inv = runner.build_invocation(
        option, _plan(provider="codex", effort="high"), Path("/ws/prompt.md")
    )
    assert "-c" in inv.argv
    assert inv.argv[inv.argv.index("-c") + 1] == 'model_reasoning_effort="high"'


def test_codex_build_invocation_omits_reasoning_effort_override_when_none():
    runner = get_runner("codex")
    option = ModelOption(id="balanced", label="Balanced", argv_model="gpt-5.4-codex")
    inv = runner.build_invocation(
        option, _plan(provider="codex", effort=None), Path("/ws/prompt.md")
    )
    assert "-c" not in inv.argv
    assert not any("model_reasoning_effort" in arg for arg in inv.argv)


# ---------------------------------------------------------------------------
# Capability flag: does this provider's CLI support effort at all?
#
# Assumed name: `supports_effort: bool` class attribute on the adapter,
# alongside the existing `executable: bool`. Both real CLIs support effort
# per the research above; the non-executable manual provider does not (there
# is no CLI invocation to attach a flag to).
# ---------------------------------------------------------------------------


def test_claude_code_runner_supports_effort_capability_flag():
    assert get_runner("claude-code").supports_effort is True


def test_codex_runner_supports_effort_capability_flag():
    assert get_runner("codex").supports_effort is True


def test_manual_runner_does_not_support_effort_capability_flag():
    assert get_runner("manual").supports_effort is False


# ---------------------------------------------------------------------------
# Worker plumbing: the job's effective (plan-resolved) effort is what
# actually reaches build_invocation.
# ---------------------------------------------------------------------------


class _RecordingRunner:
    provider_id = "fake-effort"
    executable = True
    supports_effort = True

    def __init__(self) -> None:
        self.seen_plan: StageModelPlan | None = None

    def is_available(self) -> bool:
        return True

    def build_invocation(self, model, plan, prompt_path):
        self.seen_plan = plan
        return Invocation(argv=[sys.executable, "-c", "print('OK')"])

    def parse_response(self, stdout):
        return ProviderResponse(text=stdout, metadata={})


def test_worker_passes_the_jobs_effective_effort_into_build_invocation(tmp_path):
    fake = _RecordingRunner()
    register_runner(fake)

    runs = RunStore(tmp_path)
    runs.create_run("t", content_contract=ContentContract.legacy_markdown())
    runs.stage_paths("t", "draft").prompt_path.parent.mkdir(parents=True, exist_ok=True)
    runs.stage_paths("t", "draft").prompt_path.write_text("PROMPT", encoding="utf-8")

    catalog = parse_model_catalog(
        {"providers": [{"id": "fake-effort", "models": [{"id": "m", "argv_model": "x"}]}]}
    )
    plan = parse_model_plan(
        {"provider": "fake-effort", "stages": {"draft": {"model": "m", "effort": "high"}}},
        catalog,
    )
    store = JobStore(tmp_path)
    job = store.create("t", "draft", "fake-effort", "m", None)

    runner = JobRunner(store, runs, catalog, plan, timeout=30)
    done = runner.execute(job, threading.Event())

    assert done.status == "succeeded"
    assert fake.seen_plan is not None
    assert fake.seen_plan.effort == "high"
    assert done.effort == "high"
