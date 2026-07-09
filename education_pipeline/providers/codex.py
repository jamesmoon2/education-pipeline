"""Codex non-interactive provider adapter.

Invokes ``codex exec ... -`` which reads instructions from stdin and writes
exactly the agent's final message to stdout (activity goes to stderr). See
https://developers.openai.com/codex/noninteractive.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from education_pipeline.config import ModelOption, StageModelPlan
from education_pipeline.providers import Invocation, ProviderResponse


class CodexRunner:
    provider_id = "codex"
    executable = True

    def is_available(self) -> bool:
        return shutil.which("codex") is not None

    def build_invocation(
        self, model: ModelOption, plan: StageModelPlan, prompt_path: Path
    ) -> Invocation:
        argv = ["codex", "exec"]
        if model.argv_model:
            argv += ["--model", model.argv_model]
        argv += ["--sandbox", "read-only", "--skip-git-repo-check"]
        argv += list(model.extra_args)
        argv.append("-")  # read instructions from stdin
        return Invocation(argv=argv, stdin=None)

    def parse_response(self, stdout: str) -> ProviderResponse:
        return ProviderResponse(text=stdout.strip(), metadata={})
