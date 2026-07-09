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
