import pytest

from education_pipeline import ConfigError
from education_pipeline.providers import (
    Invocation,
    ManualRunner,
    ProviderResponse,
    get_runner,
    register_runner,
)


def test_manual_runner_is_registered_and_not_executable():
    runner = get_runner("manual")
    assert runner.provider_id == "manual"
    assert runner.executable is False
    assert runner.is_available() is True


def test_manual_runner_refuses_to_build_invocation():
    from pathlib import Path

    runner = get_runner("manual")
    with pytest.raises(ConfigError):
        runner.build_invocation(None, None, Path("prompt.md"))


def test_get_runner_unknown_provider_raises():
    with pytest.raises(ConfigError):
        get_runner("does-not-exist")


def test_register_and_get_custom_runner():
    class Fake:
        provider_id = "fake-x"
        executable = True

        def is_available(self):
            return True

        def build_invocation(self, model, plan, prompt_path):
            return Invocation(argv=["fake"], stdin=b"hi")

        def parse_response(self, stdout):
            return ProviderResponse(text=stdout.strip(), metadata={})

    register_runner(Fake())
    assert get_runner("fake-x").provider_id == "fake-x"


from pathlib import Path

from education_pipeline import ModelOption, StageModelPlan


def _plan(stage="draft", provider="claude-code"):
    return StageModelPlan(stage=stage, recommendation="x", model="premium", provider=provider)


def test_claude_build_invocation_composes_model_and_extra_args():
    runner = get_runner("claude-code")
    option = ModelOption(
        id="premium",
        label="Premium",
        argv_model="claude-opus-4-8",
        extra_args=("--reasoning", "high"),
    )
    inv = runner.build_invocation(option, _plan(), Path("/ws/prompt.md"))
    assert inv.argv[0] == "claude"
    assert "-p" in inv.argv
    assert "--output-format" in inv.argv and "json" in inv.argv
    assert inv.argv[inv.argv.index("--model") + 1] == "claude-opus-4-8"
    # tools disabled and prompt fed via stdin
    assert inv.argv[inv.argv.index("--tools") + 1] == ""
    # --tools only governs built-ins; strict MCP mode (with no --mcp-config)
    # keeps user-configured MCP servers out of the session as well.
    assert "--strict-mcp-config" in inv.argv
    assert "--reasoning" in inv.argv and "high" in inv.argv
    assert inv.stdin is None  # worker pipes the prompt file itself


def test_claude_build_invocation_never_uses_plan_mode():
    """Plan mode makes headless Claude emit a plan (or write it to a file)
    instead of the stage content itself — the run then stalls with an
    unusable response. Pure generation must disable tools via --tools,
    never via --permission-mode plan."""

    runner = get_runner("claude-code")
    option = ModelOption(id="premium", label="Premium", argv_model="claude-opus-4-8")
    inv = runner.build_invocation(option, _plan(), Path("/ws/prompt.md"))
    assert "plan" not in inv.argv
    assert "--permission-mode" not in inv.argv


def test_claude_parse_response_extracts_result_field():
    runner = get_runner("claude-code")
    stdout = '{"result": "final text", "total_cost_usd": 0.01, "session_id": "abc"}'
    parsed = runner.parse_response(stdout)
    assert parsed.text == "final text"
    assert parsed.metadata["total_cost_usd"] == 0.01
    assert parsed.metadata["session_id"] == "abc"


def test_claude_parse_response_rejects_malformed_json():
    import pytest

    from education_pipeline import ConfigError

    runner = get_runner("claude-code")
    with pytest.raises(ConfigError):
        runner.parse_response("not json at all")


def test_codex_build_invocation_read_only_sandbox_and_stdin_dash():
    runner = get_runner("codex")
    option = ModelOption(id="balanced", label="Balanced", argv_model="gpt-5.4-codex")
    inv = runner.build_invocation(option, _plan(provider="codex"), Path("/ws/prompt.md"))
    assert inv.argv[:2] == ["codex", "exec"]
    assert "--sandbox" in inv.argv and "read-only" in inv.argv
    assert "--skip-git-repo-check" in inv.argv
    assert inv.argv[-1] == "-"  # read instructions from stdin
    assert inv.argv[inv.argv.index("--model") + 1] == "gpt-5.4-codex"


def test_codex_parse_response_returns_raw_stdout():
    runner = get_runner("codex")
    parsed = runner.parse_response("  the final message\n")
    assert parsed.text == "the final message"
    assert parsed.metadata == {}
