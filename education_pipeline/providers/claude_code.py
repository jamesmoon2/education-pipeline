"""Claude Code headless provider adapter.

Invokes ``claude -p --output-format json`` with tools disabled (pure text
generation) and the prompt fed via stdin. See
https://code.claude.com/docs/en/headless.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from education_pipeline.config import ConfigError, ModelOption, StageModelPlan
from education_pipeline.providers import Invocation, ProviderResponse


class ClaudeCodeRunner:
    provider_id = "claude-code"
    executable = True

    def is_available(self) -> bool:
        return shutil.which("claude") is not None

    def build_invocation(
        self, model: ModelOption, plan: StageModelPlan, prompt_path: Path
    ) -> Invocation:
        argv = [
            "claude",
            "-p",
            "--output-format",
            "json",
            # Content-only generation: the model must not edit files.
            "--permission-mode",
            "plan",
            "--allowedTools",
            "",
        ]
        if model.argv_model:
            argv += ["--model", model.argv_model]
        argv += list(model.extra_args)
        # The worker pipes prompt_path into stdin, so stdin stays None here.
        return Invocation(argv=argv, stdin=None)

    def parse_response(self, stdout: str) -> ProviderResponse:
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise ConfigError(f"claude-code returned malformed JSON: {exc}") from exc
        text = payload.get("result")
        if not isinstance(text, str):
            raise ConfigError("claude-code JSON missing string 'result' field")
        metadata: dict = {}
        for key in ("total_cost_usd", "session_id"):
            if key in payload:
                metadata[key] = payload[key]
        return ProviderResponse(text=text, metadata=metadata)
