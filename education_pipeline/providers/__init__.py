"""Pluggable provider adapters that describe how to invoke a model CLI.

Adapters never spawn processes. They translate a resolved :class:`ModelOption`
and stage plan into an :class:`Invocation` (argv + stdin + env overrides) and
parse a provider's stdout into a :class:`ProviderResponse`. The daemon worker
owns subprocess execution, log streaming, and response capture.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Protocol, runtime_checkable

from education_pipeline.config import ConfigError, ModelOption, StageModelPlan


@dataclass(frozen=True)
class Invocation:
    """A fully-resolved command the worker can spawn."""

    argv: list[str]
    stdin: bytes | None = None
    env: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderResponse:
    """Parsed provider output: the assistant text plus optional provenance."""

    text: str
    metadata: dict = field(default_factory=dict)


@runtime_checkable
class ProviderRunner(Protocol):
    provider_id: str
    executable: bool

    def is_available(self) -> bool:
        """Whether this provider's CLI is usable on this machine."""

    def build_invocation(
        self, model: ModelOption, plan: StageModelPlan, prompt_path: Path
    ) -> Invocation:
        """Describe how to invoke the provider for one stage prompt."""

    def parse_response(self, stdout: str) -> ProviderResponse:
        """Turn captured stdout into the assistant's final text + metadata."""


class ManualRunner:
    """A non-executable provider: the human runs the prompt themselves."""

    provider_id = "manual"
    executable = False

    def is_available(self) -> bool:
        return True

    def build_invocation(
        self, model: ModelOption | None, plan: StageModelPlan | None, prompt_path: Path
    ) -> Invocation:
        raise ConfigError(
            "manual provider is not executable — run the prompt yourself and save the response"
        )

    def parse_response(self, stdout: str) -> ProviderResponse:  # pragma: no cover - never called
        raise ConfigError("manual provider produces no output to parse")


_REGISTRY: dict[str, ProviderRunner] = {}


def register_runner(runner: ProviderRunner) -> None:
    """Register (or replace) a provider runner by its ``provider_id``."""

    _REGISTRY[runner.provider_id] = runner


def get_runner(provider_id: str) -> ProviderRunner:
    """Return the runner for ``provider_id`` or raise :class:`ConfigError`."""

    try:
        return _REGISTRY[provider_id]
    except KeyError as exc:
        known = ", ".join(sorted(_REGISTRY)) or "none"
        raise ConfigError(
            f"unknown provider {provider_id!r}; registered providers: {known}"
        ) from exc


register_runner(ManualRunner())


def _register_builtin_runners() -> None:
    from education_pipeline.providers.claude_code import ClaudeCodeRunner
    from education_pipeline.providers.codex import CodexRunner

    register_runner(ClaudeCodeRunner())
    register_runner(CodexRunner())


_register_builtin_runners()
