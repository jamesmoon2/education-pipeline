import subprocess

import pytest

from education_pipeline import ConfigError
from education_pipeline.config import ModelCatalog, ModelOption, ModelPlan, Provider
from education_pipeline.profile_draft import (
    build_profile_draft_prompt,
    draft_profile_toml,
    extract_toml,
)
from education_pipeline.providers import (
    Invocation,
    ProviderResponse,
    register_runner,
)

VALID_TOML = 'id = "test-learner"\ntarget_learner = "A synthetic learner"\n'


def _catalog(provider_id="fake-draft"):
    option = ModelOption(id="fast", label="Fast", argv_model="fast-1")
    return ModelCatalog(
        providers={
            provider_id: Provider(id=provider_id, label="Fake", models={"fast": option})
        }
    )


def _plan(provider_id="fake-draft"):
    return ModelPlan(provider=provider_id, stages={})


class FakeRunner:
    provider_id = "fake-draft"
    executable = True

    def __init__(self, available=True):
        self.available = available
        self.built_with = None

    def is_available(self):
        return self.available

    def build_invocation(self, model, plan, prompt_path):
        self.built_with = (model, plan)
        return Invocation(argv=["fake-draft-cli"])

    def parse_response(self, stdout):
        return ProviderResponse(text=stdout, metadata={})


def _completed(stdout=VALID_TOML, returncode=0, stderr=b""):
    return subprocess.CompletedProcess(
        args=["fake-draft-cli"],
        returncode=returncode,
        stdout=stdout.encode("utf-8") if isinstance(stdout, str) else stdout,
        stderr=stderr,
    )


class TestPrompt:
    def test_prompt_embeds_description_and_schema(self):
        prompt = build_profile_draft_prompt("A nurse returning to statistics.")
        assert "A nurse returning to statistics." in prompt
        assert "target_learner" in prompt
        assert "[learning_preferences]" in prompt
        assert "Output ONLY the TOML" in prompt

    def test_prompt_rejects_empty_description(self):
        with pytest.raises(ConfigError):
            build_profile_draft_prompt("   \n")


class TestExtractToml:
    def test_bare_toml_passes_through(self):
        assert extract_toml(VALID_TOML) == VALID_TOML

    def test_fenced_block_is_unwrapped(self):
        text = "Here is the profile:\n```toml\n" + VALID_TOML + "```\nDone."
        assert extract_toml(text) == VALID_TOML

    def test_unlabeled_fence_is_unwrapped(self):
        text = "```\n" + VALID_TOML + "```"
        assert extract_toml(text) == VALID_TOML

    def test_empty_response_raises(self):
        with pytest.raises(ConfigError):
            extract_toml("   \n")


class TestDraftProfileToml:
    def test_happy_path_returns_validated_toml_and_id(self):
        runner = FakeRunner()
        register_runner(runner)
        calls = {}

        def run_process(argv, **kwargs):
            calls["argv"] = argv
            calls["input"] = kwargs["input"]
            return _completed()

        result = draft_profile_toml(
            _catalog(),
            _plan(),
            "A synthetic learner description.",
            model="fast",
            run_process=run_process,
        )
        assert result["profile_id"] == "test-learner"
        assert result["toml"] == VALID_TOML
        assert result["provider"] == "fake-draft"
        assert calls["argv"] == ["fake-draft-cli"]
        assert b"A synthetic learner description." in calls["input"]
        model_option, stage_plan = runner.built_with
        assert model_option.id == "fast"
        assert stage_plan.provider == "fake-draft"

    def test_defaults_to_plan_provider_and_default_model(self):
        runner = FakeRunner()
        register_runner(runner)
        result = draft_profile_toml(
            _catalog(), _plan(), "desc", run_process=lambda *a, **k: _completed()
        )
        assert result["provider"] == "fake-draft"
        assert result["model"] is None
        model_option, _ = runner.built_with
        assert model_option.id == ""

    def test_unavailable_provider_raises(self):
        register_runner(FakeRunner(available=False))
        with pytest.raises(ConfigError, match="not available"):
            draft_profile_toml(
                _catalog(), _plan(), "desc", run_process=lambda *a, **k: _completed()
            )

    def test_manual_provider_is_rejected(self):
        with pytest.raises(ConfigError, match="not executable"):
            draft_profile_toml(
                _catalog(),
                _plan(),
                "desc",
                provider="manual",
                run_process=lambda *a, **k: _completed(),
            )

    def test_unknown_model_raises(self):
        register_runner(FakeRunner())
        with pytest.raises(ConfigError, match="unknown model"):
            draft_profile_toml(
                _catalog(),
                _plan(),
                "desc",
                model="nope",
                run_process=lambda *a, **k: _completed(),
            )

    def test_nonzero_exit_raises_with_stderr_tail(self):
        register_runner(FakeRunner())
        with pytest.raises(ConfigError, match="exited with code 3.*boom"):
            draft_profile_toml(
                _catalog(),
                _plan(),
                "desc",
                run_process=lambda *a, **k: _completed(returncode=3, stderr=b"boom"),
            )

    def test_timeout_raises_config_error(self):
        register_runner(FakeRunner())

        def run_process(argv, **kwargs):
            raise subprocess.TimeoutExpired(cmd=argv, timeout=kwargs["timeout"])

        with pytest.raises(ConfigError, match="timed out"):
            draft_profile_toml(
                _catalog(), _plan(), "desc", timeout=1, run_process=run_process
            )

    def test_invalid_toml_from_model_raises(self):
        register_runner(FakeRunner())
        with pytest.raises(ConfigError, match="invalid TOML"):
            draft_profile_toml(
                _catalog(),
                _plan(),
                "desc",
                run_process=lambda *a, **k: _completed(stdout="= not toml ="),
            )

    def test_toml_missing_required_fields_raises(self):
        register_runner(FakeRunner())
        with pytest.raises(ConfigError):
            draft_profile_toml(
                _catalog(),
                _plan(),
                "desc",
                run_process=lambda *a, **k: _completed(stdout='id = "only-an-id"\n'),
            )

    def test_fenced_response_is_accepted(self):
        register_runner(FakeRunner())
        fenced = "```toml\n" + VALID_TOML + "```"
        result = draft_profile_toml(
            _catalog(),
            _plan(),
            "desc",
            run_process=lambda *a, **k: _completed(stdout=fenced),
        )
        assert result["toml"] == VALID_TOML


class FakeConfig:
    def load(self):
        return _catalog(), _plan()


class TestWriteApiDraftProfile:
    def test_drafts_from_body_fields(self):
        from education_pipeline.daemon.write_api import draft_profile

        register_runner(FakeRunner())
        result = draft_profile(
            FakeConfig(),
            {"text": "A learner description.", "model": "fast"},
            run_process=lambda *a, **k: _completed(),
        )
        assert result["profile_id"] == "test-learner"
        assert result["model"] == "fast"

    def test_rejects_unknown_body_fields(self):
        from education_pipeline.daemon.write_api import draft_profile

        with pytest.raises(ConfigError, match="unknown profile request field"):
            draft_profile(
                FakeConfig(),
                {"text": "x", "surprise": True},
                run_process=lambda *a, **k: _completed(),
            )

    def test_requires_text(self):
        from education_pipeline.daemon.write_api import draft_profile

        with pytest.raises(ConfigError, match="text"):
            draft_profile(FakeConfig(), {}, run_process=lambda *a, **k: _completed())
