# Provider Run Daemon Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give `education-pipeline` a headless, resumable way to execute a stage's compiled prompt through a model provider (Claude Code or Codex) via a long-lived local daemon and a token-authenticated loopback JSON API, driven from the CLI.

**Architecture:** A long-lived per-workspace daemon owns a single-worker job queue and is the only component that spawns provider CLIs. It calls the existing synchronous `RunStore` to land executed responses in each stage's normal `response_path`, so an executed response is byte-for-byte indistinguishable from a hand-saved one. Clients (the CLI now, a browser GUI in Spec 2) are thin: they hit a loopback HTTP JSON API and otherwise read workspace files directly. Provider-specific logic lives behind a pluggable `ProviderRunner` interface; adapters only *describe* how to invoke and how to parse output — the worker owns `subprocess`, log streaming, and response capture.

**Tech Stack:** Python 3.11+, standard library only (`http.server`, `http.client`, `subprocess`, `socket`, `threading`, `queue`, `json`, `tomllib`, `secrets`, `shutil`, `os`, `signal`). `pytest` is the only dev dependency.

## Global Constraints

- **Standard library only.** No new runtime dependencies. Dev dependency stays `pytest>=8`. (Copied from spec "Constraints Preserved".)
- **`requires-python = ">=3.11"`.** Code must run on 3.11 and 3.12; use `tomllib`, `from __future__ import annotations`.
- **Operating System :: OS Independent.** No `socket.AF_UNIX`, no assumption of POSIX signals in shared code. Process termination is isolated behind one cross-platform helper.
- **Bind strictly to `127.0.0.1` on an ephemeral port (port `0`). Never `0.0.0.0`.**
- **Every request must present the token** in the `X-EP-Token` header, compared with `secrets.compare_digest` (never `==`). Reject otherwise.
- **`daemon.json` lives at `<workspace>/.education-pipeline/daemon.json`, mode `0600`, written atomically** (temp file + `os.replace`).
- **One daemon per workspace.** Every `topic_id`/`stage` in a request is validated against the existing safe-id / supported-stage logic so a request can never address paths outside the workspace.
- **Human quality gate intact.** One stage per invocation; the runner never auto-approves. `run` enqueues only when the run's `next_action.action == "save_response"`.
- **Content-only generation.** Claude runs with tools disabled; Codex runs `--sandbox read-only`.
- **Never write an empty/whitespace response, and never clobber an already-ingested response unless `force`.** Response writes are atomic and gated on a clean provider exit.
- **Follow existing house style:** frozen dataclasses for value objects, `ConfigError` for user-facing validation failures, `from __future__ import annotations`, module docstrings, tests under `tests/` using `tmp_path` and importing from the `education_pipeline` package. Add new public symbols to `education_pipeline/__init__.py` `__all__`.

---

## File Structure

| Path | Responsibility |
|------|----------------|
| `education_pipeline/config.py` (modify) | Add typed `argv_model` / `extra_args` fields to `ModelOption` and parse them. |
| `education_pipeline/runs.py` (modify) | Public `ingest_response()` (atomic, no-clobber, non-empty) and `append_manifest_event()`. |
| `education_pipeline/providers/__init__.py` (create) | `Invocation`, `ProviderResponse`, `ProviderRunner` protocol, registry (`get_runner`/`register_runner`), `ManualRunner`. |
| `education_pipeline/providers/claude_code.py` (create) | Claude Code adapter: `build_invocation` + JSON `parse_response`. |
| `education_pipeline/providers/codex.py` (create) | Codex adapter: `build_invocation` + raw `parse_response`. |
| `education_pipeline/daemon/__init__.py` (create) | `serve()` entrypoint assembling worker + server + lifecycle; `python -m education_pipeline.daemon`. |
| `education_pipeline/daemon/jobs.py` (create) | `Job` model, on-disk `JobStore`, `new_job_id`, `terminate_process`, `JobRunner` (executes one job), `Worker` (queue + loop + reconciliation). |
| `education_pipeline/daemon/server.py` (create) | Loopback `ThreadingHTTPServer`, routing, token auth, Origin/Host allowlist, topic validation. |
| `education_pipeline/daemon/lifecycle.py` (create) | Discovery file read/write/claim, PID liveness, stale detection, status. |
| `education_pipeline/client.py` (create) | CLI-side `DaemonClient` over `http.client`; `ensure_daemon()` autostart. |
| `education_pipeline/cli.py` (modify) | New `run`, `jobs`, `job`, `logs`, `cancel`, `daemon` commands. |
| `config/model-catalog.example.toml` (modify) | Fill in real `argv_model` / `extra_args`. |
| `tests/fake_provider.py` (create) | Deterministic stub provider script used by daemon/worker tests. |
| `tests/test_*.py` (create) | One test module per task. |

---

## Task 1: Typed provider fields on `ModelOption`

**Files:**
- Modify: `education_pipeline/config.py:41-51` (`ModelOption`), `education_pipeline/config.py:212-247` (`_parse_models`)
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `ModelOption(id, label, description, quality, default_effort, argv_model: str | None = None, extra_args: tuple[str, ...] = (), metadata)`. Adapters read `option.argv_model` and `option.extra_args`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_config.py`:

```python
from education_pipeline import parse_model_catalog


def test_model_option_parses_argv_model_and_extra_args():
    catalog = parse_model_catalog(
        {
            "providers": [
                {
                    "id": "claude-code",
                    "models": [
                        {
                            "id": "premium",
                            "argv_model": "claude-opus-4-8",
                            "extra_args": ["--reasoning", "high"],
                            "note": "kept in metadata",
                        }
                    ],
                }
            ]
        }
    )
    option = catalog.providers["claude-code"].models["premium"]
    assert option.argv_model == "claude-opus-4-8"
    assert option.extra_args == ("--reasoning", "high")
    assert option.metadata == {"note": "kept in metadata"}


def test_model_option_argv_defaults_and_extra_args_type_checked():
    catalog = parse_model_catalog(
        {"providers": [{"id": "codex", "models": [{"id": "balanced"}]}]}
    )
    option = catalog.providers["codex"].models["balanced"]
    assert option.argv_model is None
    assert option.extra_args == ()

    import pytest

    from education_pipeline import ConfigError

    with pytest.raises(ConfigError):
        parse_model_catalog(
            {
                "providers": [
                    {"id": "codex", "models": [{"id": "x", "extra_args": "not-a-list"}]}
                ]
            }
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_config.py -k argv -v`
Expected: FAIL — `ModelOption` has no `argv_model`/`extra_args`, so the attributes are missing (AttributeError / assertion).

- [ ] **Step 3: Add the fields to `ModelOption`**

In `education_pipeline/config.py`, replace the `ModelOption` dataclass body (lines 41-51) with:

```python
@dataclass(frozen=True)
class ModelOption:
    """A model/runtime option exposed by a provider catalog."""

    id: str
    label: str
    description: str = ""
    quality: str | None = None
    default_effort: str | None = None
    argv_model: str | None = None
    extra_args: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)
```

- [ ] **Step 4: Parse the new fields**

In `_parse_models`, replace the block that builds `metadata` and constructs `ModelOption` (lines 231-245) with:

```python
        quality = _optional_string(raw_model, "quality", None, context)
        default_effort = _optional_string(raw_model, "default_effort", None, context)
        argv_model = _optional_string(raw_model, "argv_model", None, context)
        extra_args = _parse_extra_args(raw_model, context)
        reserved = {
            "id",
            "label",
            "description",
            "quality",
            "default_effort",
            "argv_model",
            "extra_args",
        }
        metadata = {key: value for key, value in raw_model.items() if key not in reserved}
        models[model_id] = ModelOption(
            id=model_id,
            label=label,
            description=description,
            quality=quality,
            default_effort=default_effort,
            argv_model=argv_model,
            extra_args=extra_args,
            metadata=metadata,
        )
```

Then add this helper next to `_optional_string` at the end of `config.py`:

```python
def _parse_extra_args(data: Mapping[str, Any], context: str) -> tuple[str, ...]:
    value = data.get("extra_args")
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ConfigError(f"{context} field 'extra_args' must be a list of strings")
    return tuple(value)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_config.py -v`
Expected: PASS (all config tests, including the two new ones).

- [ ] **Step 6: Commit**

```bash
git add education_pipeline/config.py tests/test_config.py
git commit -m "feat(config): add typed argv_model/extra_args to ModelOption"
```

---

## Task 2: Provider adapter interface, registry, and manual adapter

**Files:**
- Create: `education_pipeline/providers/__init__.py`
- Test: `tests/test_providers.py`

**Interfaces:**
- Consumes: `ModelOption` (Task 1), `StageModelPlan` (config).
- Produces:
  - `Invocation(argv: list[str], stdin: bytes | None = None, env: Mapping[str, str] = {})` — frozen value object.
  - `ProviderResponse(text: str, metadata: dict)` — frozen value object.
  - `ProviderRunner` Protocol: attrs `provider_id: str`, `executable: bool`; methods `is_available() -> bool`, `build_invocation(model: ModelOption, plan: StageModelPlan, prompt_path: Path) -> Invocation`, `parse_response(stdout: str) -> ProviderResponse`.
  - `register_runner(runner) -> None`, `get_runner(provider_id: str) -> ProviderRunner` (raises `ConfigError` on unknown id).
  - `ManualRunner` instance registered under `"manual"` with `executable = False`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_providers.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_providers.py -v`
Expected: FAIL — `education_pipeline.providers` module does not exist (ImportError).

- [ ] **Step 3: Create the module**

Create `education_pipeline/providers/__init__.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_providers.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add education_pipeline/providers/__init__.py tests/test_providers.py
git commit -m "feat(providers): adapter protocol, registry, and manual runner"
```

---

## Task 3: Claude Code and Codex adapters

**Files:**
- Create: `education_pipeline/providers/claude_code.py`, `education_pipeline/providers/codex.py`
- Modify: `education_pipeline/providers/__init__.py` (register both at import)
- Test: `tests/test_providers.py`

**Interfaces:**
- Consumes: `Invocation`, `ProviderResponse`, `register_runner` (Task 2), `ModelOption`, `StageModelPlan`.
- Produces: `ClaudeCodeRunner` (`provider_id = "claude-code"`, `executable = True`) and `CodexRunner` (`provider_id = "codex"`, `executable = True`), both registered on import of `education_pipeline.providers`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_providers.py`:

```python
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
    assert "--reasoning" in inv.argv and "high" in inv.argv
    assert inv.stdin is None  # worker pipes the prompt file itself


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_providers.py -k "claude or codex" -v`
Expected: FAIL — `get_runner("claude-code")` raises `ConfigError` (not registered yet).

- [ ] **Step 3: Implement the Claude Code adapter**

Create `education_pipeline/providers/claude_code.py`:

```python
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
```

- [ ] **Step 4: Implement the Codex adapter**

Create `education_pipeline/providers/codex.py`:

```python
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
```

- [ ] **Step 5: Register both adapters on package import**

At the end of `education_pipeline/providers/__init__.py`, below `register_runner(ManualRunner())`, add:

```python
def _register_builtin_runners() -> None:
    from education_pipeline.providers.claude_code import ClaudeCodeRunner
    from education_pipeline.providers.codex import CodexRunner

    register_runner(ClaudeCodeRunner())
    register_runner(CodexRunner())


_register_builtin_runners()
```

(The deferred import avoids a circular import, since the adapter modules import `Invocation`/`ProviderResponse` from this package.)

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_providers.py -v`
Expected: PASS (all provider tests).

- [ ] **Step 7: Commit**

```bash
git add education_pipeline/providers/ tests/test_providers.py
git commit -m "feat(providers): claude-code and codex adapters"
```

---

## Task 4: Atomic response ingestion and manifest events on `RunStore`

**Files:**
- Modify: `education_pipeline/runs.py` (add two public methods + an atomic write helper)
- Modify: `education_pipeline/__init__.py` (no new symbols required — methods hang off `RunStore`)
- Test: `tests/test_runs.py`

**Interfaces:**
- Consumes: existing `RunStore.stage_paths`, `_supported_stage`, `_artifact_id`, `_append_event`.
- Produces:
  - `RunStore.ingest_response(self, topic_id: str, stage: str, text: str, *, force: bool = False) -> Path` — writes `response_path` atomically; raises `ConfigError` on empty/whitespace text or on an existing response when `not force`.
  - `RunStore.append_manifest_event(self, topic_id: str, event: dict) -> None` — appends an arbitrary event (adds `recorded_at`) to the run manifest.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_runs.py`:

```python
def test_ingest_response_writes_response_atomically(tmp_path):
    runs = RunStore(tmp_path)
    runs.create_run("systems-thinking")
    path = runs.ingest_response("systems-thinking", "draft", "# Draft body\n")
    assert path == runs.response_path("systems-thinking", "draft")
    assert path.read_text(encoding="utf-8") == "# Draft body\n"
    assert runs.has_ingested_response("systems-thinking", "draft")


def test_ingest_response_rejects_empty(tmp_path):
    runs = RunStore(tmp_path)
    runs.create_run("systems-thinking")
    with pytest.raises(ConfigError):
        runs.ingest_response("systems-thinking", "draft", "   \n\t ")


def test_ingest_response_refuses_clobber_unless_forced(tmp_path):
    runs = RunStore(tmp_path)
    runs.create_run("systems-thinking")
    runs.ingest_response("systems-thinking", "draft", "first\n")
    with pytest.raises(ConfigError):
        runs.ingest_response("systems-thinking", "draft", "second\n")
    path = runs.ingest_response("systems-thinking", "draft", "second\n", force=True)
    assert path.read_text(encoding="utf-8") == "second\n"


def test_append_manifest_event_records_event(tmp_path):
    runs = RunStore(tmp_path)
    runs.create_run("systems-thinking")
    runs.append_manifest_event(
        "systems-thinking", {"stage": "draft", "action": "job", "job_id": "j1"}
    )
    events = runs.read_manifest("systems-thinking")["events"]
    assert events[-1]["action"] == "job"
    assert events[-1]["job_id"] == "j1"
    assert "recorded_at" in events[-1]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_runs.py -k "ingest or manifest_event" -v`
Expected: FAIL — `RunStore` has no `ingest_response` / `append_manifest_event` (AttributeError).

- [ ] **Step 3: Implement the methods**

In `education_pipeline/runs.py`, add these methods to `RunStore` (place after `approve_stage`, before `final_path`):

```python
    def ingest_response(
        self, topic_id: str, stage: str, text: str, *, force: bool = False
    ) -> Path:
        """Atomically land an executed provider response as the stage response.

        The written file is byte-for-byte a hand-saved response. Empty or
        whitespace-only output is rejected, and an existing response is never
        clobbered unless ``force`` is set.
        """

        paths = self.stage_paths(topic_id, stage)
        if not text.strip():
            raise ConfigError(f"refusing to ingest empty response for stage {paths.stage!r}")
        if paths.response_path.exists() and not force:
            raise ConfigError(
                f"response already ingested for stage {paths.stage!r}: {paths.response_path}"
            )
        _write_text_atomic(paths.response_path, text)
        if paths.stub_path.exists():
            paths.stub_path.unlink()
        return paths.response_path

    def append_manifest_event(self, topic_id: str, event: dict) -> None:
        """Append an arbitrary event (with ``recorded_at``) to the run manifest."""

        safe_id = _artifact_id(topic_id, "topic id")
        run = self.run_dir(safe_id)
        manifest = self.read_manifest(safe_id)
        entry = dict(event)
        entry.setdefault("recorded_at", datetime.now(timezone.utc).isoformat())
        manifest.setdefault("events", []).append(entry)
        _write_manifest(run / "manifest.json", manifest)
```

Then add this module-level helper next to `_write_text` at the bottom of `runs.py`:

```python
def _write_text_atomic(path: Path, text: str) -> None:
    import os
    import tempfile

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=path.suffix)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_runs.py -v`
Expected: PASS (all run tests, including the four new ones).

- [ ] **Step 5: Commit**

```bash
git add education_pipeline/runs.py tests/test_runs.py
git commit -m "feat(runs): atomic ingest_response and append_manifest_event"
```

---

## Task 5: `Job` model, `new_job_id`, and on-disk `JobStore`

**Files:**
- Create: `education_pipeline/daemon/__init__.py` (empty package marker for now — a one-line docstring)
- Create: `education_pipeline/daemon/jobs.py`
- Test: `tests/test_jobs.py`

**Interfaces:**
- Consumes: `RunStore` conventions (`root/runs/<topic_id>/`), `_is_artifact_id` behavior (reused via `RunStore`).
- Produces:
  - Constants `JOB_STATUSES`, `TERMINAL_STATUSES` (`{"succeeded","failed","canceled","interrupted"}`).
  - `new_job_id(now: datetime | None = None) -> str` → e.g. `20260709T183042Z-a3f9`.
  - `Job` mutable dataclass: `id, topic_id, stage, provider, model, effort, status, pid, created_at, started_at, ended_at, exit_code, response_path, error, metadata`, plus `to_dict()` / `Job.from_dict(d)`.
  - `JobStore(root)` with: `job_dir(topic_id, job_id)`, `log_path(topic_id, job_id)`, `create(topic_id, stage, provider, model, effort) -> Job`, `save(job)`, `load(topic_id, job_id) -> Job`, `find(job_id) -> Job | None`, `list(topic_id=None) -> list[Job]` (newest first), `all_jobs() -> list[Job]`, `active_for(topic_id, stage) -> Job | None`, `read_log(job, offset) -> tuple[bytes, int]`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_jobs.py`:

```python
from datetime import datetime, timezone

import pytest

from education_pipeline.daemon.jobs import (
    TERMINAL_STATUSES,
    Job,
    JobStore,
    new_job_id,
)


def test_new_job_id_is_sortable_and_suffixed():
    a = new_job_id(datetime(2026, 7, 9, 18, 30, 42, tzinfo=timezone.utc))
    assert a.startswith("20260709T183042Z-")
    assert len(a.split("-")[-1]) == 4
    # different calls differ in the random suffix
    b = new_job_id(datetime(2026, 7, 9, 18, 30, 42, tzinfo=timezone.utc))
    assert a != b


def test_jobstore_create_save_load_roundtrip(tmp_path):
    store = JobStore(tmp_path)
    job = store.create("systems-thinking", "draft", "claude-code", "premium", "high")
    assert job.status == "queued"
    assert job.topic_id == "systems-thinking"
    store.save(job)
    loaded = store.load("systems-thinking", job.id)
    assert loaded.id == job.id
    assert loaded.stage == "draft"
    assert loaded.provider == "claude-code"
    assert loaded.effort == "high"


def test_jobstore_find_and_list_newest_first(tmp_path):
    store = JobStore(tmp_path)
    j1 = store.create("t", "spec", "codex", "balanced", None)
    store.save(j1)
    j2 = store.create("t", "draft", "codex", "balanced", None)
    store.save(j2)
    assert store.find(j2.id).id == j2.id
    ids = [j.id for j in store.list("t")]
    assert ids == sorted(ids, reverse=True)
    assert store.find("nope") is None


def test_active_for_finds_only_non_terminal(tmp_path):
    store = JobStore(tmp_path)
    job = store.create("t", "draft", "codex", "balanced", None)
    store.save(job)
    assert store.active_for("t", "draft").id == job.id
    job.status = "succeeded"
    store.save(job)
    assert store.active_for("t", "draft") is None
    assert "succeeded" in TERMINAL_STATUSES


def test_read_log_returns_bytes_from_offset(tmp_path):
    store = JobStore(tmp_path)
    job = store.create("t", "draft", "codex", "balanced", None)
    store.log_path(job.topic_id, job.id).write_bytes(b"hello world")
    data, offset = store.read_log(job, 6)
    assert data == b"world"
    assert offset == 11
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_jobs.py -v`
Expected: FAIL — `education_pipeline.daemon.jobs` does not exist (ImportError).

- [ ] **Step 3: Create the daemon package marker**

Create `education_pipeline/daemon/__init__.py`:

```python
"""Long-lived local run daemon: job queue, worker, and loopback JSON API."""
```

- [ ] **Step 4: Implement `jobs.py` (model + store only)**

Create `education_pipeline/daemon/jobs.py`:

```python
"""Durable job records and their on-disk store.

A Job is the durable record of one stage execution. Job state and logs live
under ``runs/<topic_id>/jobs/<job_id>/`` so history survives daemon restarts and
a fresh client can read past runs without the daemon running.
"""

from __future__ import annotations

import json
import os
import secrets
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

JOB_STATUSES = (
    "queued",
    "running",
    "succeeded",
    "failed",
    "canceled",
    "interrupted",
)
TERMINAL_STATUSES = frozenset({"succeeded", "failed", "canceled", "interrupted"})


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_job_id(now: datetime | None = None) -> str:
    """A sortable, collision-safe, filesystem-safe job id."""

    stamp = (now or _utcnow()).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{secrets.token_hex(2)}"


@dataclass
class Job:
    id: str
    topic_id: str
    stage: str
    provider: str
    model: str | None
    effort: str | None
    status: str = "queued"
    pid: int | None = None
    created_at: str = ""
    started_at: str | None = None
    ended_at: str | None = None
    exit_code: int | None = None
    response_path: str | None = None
    error: str | None = None
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Job":
        fields = {f: data.get(f) for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        fields["metadata"] = data.get("metadata") or {}
        return cls(**fields)


class JobStore:
    """Read and write job records under a workspace's ``runs`` tree."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    @property
    def runs_dir(self) -> Path:
        return self.root / "runs"

    def job_dir(self, topic_id: str, job_id: str) -> Path:
        return self.runs_dir / topic_id / "jobs" / job_id

    def _job_json(self, topic_id: str, job_id: str) -> Path:
        return self.job_dir(topic_id, job_id) / "job.json"

    def log_path(self, topic_id: str, job_id: str) -> Path:
        path = self.job_dir(topic_id, job_id) / "output.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def create(
        self,
        topic_id: str,
        stage: str,
        provider: str,
        model: str | None,
        effort: str | None,
    ) -> Job:
        job = Job(
            id=new_job_id(),
            topic_id=topic_id,
            stage=stage,
            provider=provider,
            model=model,
            effort=effort,
            created_at=_utcnow().isoformat(),
        )
        self.job_dir(topic_id, job.id).mkdir(parents=True, exist_ok=True)
        return job

    def save(self, job: Job) -> None:
        target = self._job_json(job.topic_id, job.id)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=".tmp-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(job.to_dict(), handle, indent=2)
            os.replace(tmp, target)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    def load(self, topic_id: str, job_id: str) -> Job:
        data = json.loads(self._job_json(topic_id, job_id).read_text(encoding="utf-8"))
        return Job.from_dict(data)

    def all_jobs(self) -> list[Job]:
        jobs: list[Job] = []
        if not self.runs_dir.exists():
            return jobs
        for jobs_dir in self.runs_dir.glob("*/jobs"):
            for job_dir in jobs_dir.iterdir():
                record = job_dir / "job.json"
                if record.is_file():
                    jobs.append(Job.from_dict(json.loads(record.read_text(encoding="utf-8"))))
        return jobs

    def list(self, topic_id: str | None = None) -> list[Job]:
        jobs = [j for j in self.all_jobs() if topic_id is None or j.topic_id == topic_id]
        return sorted(jobs, key=lambda j: j.id, reverse=True)

    def find(self, job_id: str) -> Job | None:
        for job in self.all_jobs():
            if job.id == job_id:
                return job
        return None

    def active_for(self, topic_id: str, stage: str) -> Job | None:
        for job in self.list(topic_id):
            if job.stage == stage and job.status not in TERMINAL_STATUSES:
                return job
        return None

    def read_log(self, job: Job, offset: int = 0) -> tuple[bytes, int]:
        path = self.job_dir(job.topic_id, job.id) / "output.log"
        if not path.exists():
            return b"", offset
        with path.open("rb") as handle:
            handle.seek(offset)
            data = handle.read()
        return data, offset + len(data)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_jobs.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add education_pipeline/daemon/__init__.py education_pipeline/daemon/jobs.py tests/test_jobs.py
git commit -m "feat(daemon): Job model and on-disk JobStore"
```

---

## Task 6: Cross-platform process termination helper

**Files:**
- Modify: `education_pipeline/daemon/jobs.py` (add `terminate_process`)
- Test: `tests/test_jobs.py`

**Interfaces:**
- Consumes: `subprocess.Popen`.
- Produces: `terminate_process(popen: subprocess.Popen, *, grace: float = 5.0) -> None` — TERM then KILL after `grace`, using process groups on POSIX and `CREATE_NEW_PROCESS_GROUP`/`terminate()`/`kill()` on Windows. Also `popen_kwargs() -> dict` returning the platform spawn flags (`start_new_session=True` on POSIX; `creationflags=CREATE_NEW_PROCESS_GROUP` on Windows) so the worker spawns with the matching group semantics.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_jobs.py`:

```python
import subprocess
import sys
import time

from education_pipeline.daemon.jobs import popen_kwargs, terminate_process


def test_terminate_process_kills_a_running_child():
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"], **popen_kwargs()
    )
    assert proc.poll() is None
    terminate_process(proc, grace=2.0)
    # after termination the process must be reaped with a non-None returncode
    assert proc.poll() is not None


def test_popen_kwargs_has_platform_group_flag():
    kwargs = popen_kwargs()
    if sys.platform == "win32":
        assert "creationflags" in kwargs
    else:
        assert kwargs.get("start_new_session") is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_jobs.py -k terminate -v`
Expected: FAIL — `popen_kwargs` / `terminate_process` do not exist (ImportError).

- [ ] **Step 3: Implement the helper**

Add to the top of `education_pipeline/daemon/jobs.py` (after the existing imports add `import signal`, `import subprocess`, `import sys`), then add near the bottom of the module:

```python
def popen_kwargs() -> dict:
    """Spawn flags that put the child in its own killable group, per platform."""

    if sys.platform == "win32":  # pragma: no cover - exercised on Windows CI
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def terminate_process(proc: subprocess.Popen, *, grace: float = 5.0) -> None:
    """Terminate a spawned provider process portably: TERM then KILL.

    On POSIX the whole session/process-group is signalled (the child was spawned
    with ``start_new_session=True``); on Windows ``Popen.terminate()`` /
    ``kill()`` are used (no SIGTERM semantics).
    """

    if proc.poll() is not None:
        return
    try:
        if sys.platform == "win32":  # pragma: no cover - exercised on Windows CI
            proc.terminate()
        else:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        pass
    try:
        proc.wait(timeout=grace)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        if sys.platform == "win32":  # pragma: no cover - exercised on Windows CI
            proc.kill()
        else:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        pass
    try:
        proc.wait(timeout=grace)
    except subprocess.TimeoutExpired:  # pragma: no cover - defensive
        pass
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_jobs.py -k "terminate or popen" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add education_pipeline/daemon/jobs.py tests/test_jobs.py
git commit -m "feat(daemon): portable process-termination helper"
```

---

## Task 7: `JobRunner` — execute one job end-to-end

**Files:**
- Modify: `education_pipeline/daemon/jobs.py` (add `JobRunner`, output cap constant)
- Create: `tests/fake_provider.py`
- Test: `tests/test_job_runner.py`

**Interfaces:**
- Consumes: `JobStore`, `Job`, `terminate_process`, `popen_kwargs` (Tasks 5-6); `RunStore.ingest_response`/`append_manifest_event` (Task 4); `get_runner`, `ProviderResponse`, `Invocation` (Tasks 2-3); `ModelOption`, `StageModelPlan`, `ModelCatalog`, `ModelPlan` (config).
- Produces:
  - `MAX_LOG_BYTES = 10 * 1024 * 1024`, `DEFAULT_TIMEOUT_SECONDS = 1800`.
  - `JobRunner(store: JobStore, runs: RunStore, catalog: ModelCatalog, plan: ModelPlan, *, timeout: float = DEFAULT_TIMEOUT_SECONDS, force: bool = False)`.
  - `JobRunner.execute(job: Job, cancel: threading.Event) -> Job` — resolves runner + model, checks availability, spawns the subprocess (prompt piped to stdin, combined stdout+stderr streamed to `output.log` capped at `MAX_LOG_BYTES`), enforces `timeout` and `cancel`, parses on clean exit, ingests the response, and sets the terminal status. Mutates and saves `job` at every transition and returns it.

- [ ] **Step 1: Create the deterministic fake provider script**

Create `tests/fake_provider.py`:

```python
"""A deterministic stand-in for a provider CLI, used in daemon tests.

Reads the prompt from stdin and echoes a canned response. Behaviour is driven by
environment variables so a test can exercise success, failure, empty output,
slow/timeout, and JSON-shaped output without any network access.
"""

import os
import sys
import time


def main() -> int:
    sys.stdin.buffer.read()  # consume the piped prompt
    delay = float(os.environ.get("FAKE_DELAY", "0"))
    if delay:
        time.sleep(delay)
    if os.environ.get("FAKE_STDERR"):
        sys.stderr.write(os.environ["FAKE_STDERR"])
    sys.stdout.write(os.environ.get("FAKE_STDOUT", "fake response body\n"))
    return int(os.environ.get("FAKE_EXIT", "0"))


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_job_runner.py`:

```python
import sys
import threading
from pathlib import Path

import pytest

from education_pipeline import RunStore, parse_model_catalog, parse_model_plan
from education_pipeline.daemon.jobs import JobRunner, JobStore
from education_pipeline.providers import (
    Invocation,
    ProviderResponse,
    register_runner,
)

FAKE = Path(__file__).parent / "fake_provider.py"


class FakeRunner:
    provider_id = "fake"
    executable = True

    def is_available(self) -> bool:
        return True

    def build_invocation(self, model, plan, prompt_path):
        return Invocation(argv=[sys.executable, str(FAKE)])

    def parse_response(self, stdout):
        return ProviderResponse(text=stdout, metadata={"echo": True})


class UnavailableRunner(FakeRunner):
    provider_id = "gone"

    def is_available(self) -> bool:
        return False


def _setup(tmp_path, provider="fake"):
    register_runner(FakeRunner())
    register_runner(UnavailableRunner())
    runs = RunStore(tmp_path)
    runs.create_run("t")
    # a prompt must exist for the stage the job runs
    runs.stage_paths("t", "draft").prompt_path.parent.mkdir(parents=True, exist_ok=True)
    runs.stage_paths("t", "draft").prompt_path.write_text("PROMPT", encoding="utf-8")
    catalog = parse_model_catalog(
        {"providers": [{"id": provider, "models": [{"id": "m", "argv_model": "x"}]}]}
    )
    plan = parse_model_plan({"provider": provider, "stages": {"draft": {"model": "m"}}}, catalog)
    store = JobStore(tmp_path)
    return runs, catalog, plan, store


def test_execute_success_ingests_response(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_STDOUT", "GENERATED\n")
    runs, catalog, plan, store = _setup(tmp_path)
    job = store.create("t", "draft", "fake", "m", None)
    runner = JobRunner(store, runs, catalog, plan, timeout=30)
    done = runner.execute(job, threading.Event())
    assert done.status == "succeeded"
    assert done.exit_code == 0
    assert runs.response_path("t", "draft").read_text(encoding="utf-8") == "GENERATED\n"
    # manifest carries a job event
    actions = [e["action"] for e in runs.read_manifest("t")["events"]]
    assert "job" in actions


def test_execute_nonzero_exit_fails_without_response(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_EXIT", "3")
    runs, catalog, plan, store = _setup(tmp_path)
    job = store.create("t", "draft", "fake", "m", None)
    done = JobRunner(store, runs, catalog, plan, timeout=30).execute(job, threading.Event())
    assert done.status == "failed"
    assert done.exit_code == 3
    assert not runs.has_ingested_response("t", "draft")


def test_execute_empty_output_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_STDOUT", "   \n")
    runs, catalog, plan, store = _setup(tmp_path)
    job = store.create("t", "draft", "fake", "m", None)
    done = JobRunner(store, runs, catalog, plan, timeout=30).execute(job, threading.Event())
    assert done.status == "failed"
    assert not runs.has_ingested_response("t", "draft")


def test_execute_timeout_marks_failed(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_DELAY", "10")
    runs, catalog, plan, store = _setup(tmp_path)
    job = store.create("t", "draft", "fake", "m", None)
    done = JobRunner(store, runs, catalog, plan, timeout=0.5).execute(job, threading.Event())
    assert done.status == "failed"
    assert done.error == "timeout"


def test_execute_provider_unavailable_fails_before_spawn(tmp_path):
    runs, catalog, plan, store = _setup(tmp_path, provider="gone")
    job = store.create("t", "draft", "gone", "m", None)
    done = JobRunner(store, runs, catalog, plan, timeout=30).execute(job, threading.Event())
    assert done.status == "failed"
    assert "gone" in (done.error or "")
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest tests/test_job_runner.py -v`
Expected: FAIL — `JobRunner` does not exist (ImportError).

- [ ] **Step 4: Implement `JobRunner`**

Add to `education_pipeline/daemon/jobs.py` (add `import threading` and `import time` to the imports; import `RunStore`, config and provider types at the top):

```python
import threading
import time

from education_pipeline.config import ConfigError, ModelCatalog, ModelPlan
from education_pipeline.providers import get_runner
from education_pipeline.runs import RunStore
```

Then add these constants and class to the module:

```python
MAX_LOG_BYTES = 10 * 1024 * 1024
DEFAULT_TIMEOUT_SECONDS = 1800


class JobRunner:
    """Executes exactly one job: spawn provider, capture output, ingest response."""

    def __init__(
        self,
        store: JobStore,
        runs: RunStore,
        catalog: ModelCatalog,
        plan: ModelPlan,
        *,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        force: bool = False,
    ) -> None:
        self.store = store
        self.runs = runs
        self.catalog = catalog
        self.plan = plan
        self.timeout = timeout
        self.force = force

    def execute(self, job: Job, cancel: threading.Event) -> Job:
        job.status = "running"
        job.started_at = _utcnow().isoformat()
        self.store.save(job)
        try:
            runner = get_runner(job.provider)
            if not runner.is_available():
                return self._fail(job, f"provider {job.provider!r} is not available on PATH")

            model = self._resolve_model(job)
            plan = self.plan.stage(job.stage)
            prompt_path = self.runs.stage_paths(job.topic_id, job.stage).prompt_path
            if not prompt_path.exists():
                return self._fail(job, f"prompt not written for stage {job.stage!r}")
            invocation = runner.build_invocation(model, plan, prompt_path)
            stdout, exit_code, timed_out, canceled = self._spawn(job, invocation, prompt_path, cancel)
            job.exit_code = exit_code
            if canceled:
                return self._terminal(job, "canceled", error="canceled")
            if timed_out:
                return self._fail(job, "timeout")
            if exit_code != 0:
                return self._fail(job, f"provider exited with code {exit_code}")

            parsed = runner.parse_response(stdout)
            job.metadata.update(parsed.metadata)
            response_path = self.runs.ingest_response(
                job.topic_id, job.stage, parsed.text, force=self.force
            )
            job.response_path = str(response_path)
            self.runs.append_manifest_event(
                job.topic_id,
                {
                    "stage": job.stage,
                    "action": "job",
                    "job_id": job.id,
                    "provider": job.provider,
                    "model": job.model,
                },
            )
            return self._terminal(job, "succeeded")
        except ConfigError as exc:
            return self._fail(job, str(exc))

    def _resolve_model(self, job: Job):
        provider = self.catalog.require_provider(job.provider)
        if job.model is None:
            from education_pipeline.config import ModelOption

            return ModelOption(id="", label="")
        try:
            return provider.models[job.model]
        except KeyError as exc:
            raise ConfigError(
                f"unknown model {job.model!r} for provider {job.provider!r}"
            ) from exc

    def _spawn(self, job, invocation, prompt_path, cancel):
        log = self.store.log_path(job.topic_id, job.id)
        env = dict(os.environ)
        env.update(invocation.env)
        with prompt_path.open("rb") as prompt_handle:
            proc = subprocess.Popen(
                invocation.argv,
                stdin=prompt_handle,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=env,
                **popen_kwargs(),
            )
        job.pid = proc.pid
        self.store.save(job)

        captured = bytearray()
        written = 0
        truncated = False
        deadline = time.monotonic() + self.timeout
        timed_out = False
        canceled = False
        with log.open("wb") as log_handle:
            assert proc.stdout is not None
            for chunk in iter(lambda: proc.stdout.read(4096), b""):
                if written < MAX_LOG_BYTES:
                    room = MAX_LOG_BYTES - written
                    log_handle.write(chunk[:room])
                    written += min(len(chunk), room)
                    if len(chunk) > room and not truncated:
                        log_handle.write(b"\n...[output truncated]...\n")
                        truncated = True
                if len(captured) < MAX_LOG_BYTES:
                    captured.extend(chunk[: MAX_LOG_BYTES - len(captured)])
                if cancel.is_set():
                    canceled = True
                    break
                if time.monotonic() > deadline:
                    timed_out = True
                    break
        if timed_out or canceled or proc.poll() is None:
            terminate_process(proc)
        exit_code = proc.wait()
        return captured.decode("utf-8", errors="replace"), exit_code, timed_out, canceled

    def _fail(self, job: Job, error: str) -> Job:
        return self._terminal(job, "failed", error=error)

    def _terminal(self, job: Job, status: str, *, error: str | None = None) -> Job:
        job.status = status
        job.error = error
        job.ended_at = _utcnow().isoformat()
        job.pid = None
        self.store.save(job)
        return job
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_job_runner.py -v`
Expected: PASS (all five scenarios).

- [ ] **Step 6: Commit**

```bash
git add education_pipeline/daemon/jobs.py tests/fake_provider.py tests/test_job_runner.py
git commit -m "feat(daemon): JobRunner executes one job with capture, timeout, cancel"
```

---

## Task 8: `Worker` — queue, single-worker loop, guards, and orphan reconciliation

**Files:**
- Modify: `education_pipeline/daemon/jobs.py` (add `Worker`)
- Test: `tests/test_worker.py`

**Interfaces:**
- Consumes: `JobStore`, `Job`, `JobRunner`, `TERMINAL_STATUSES` (Tasks 5-7).
- Produces:
  - `Worker(store: JobStore, runner_factory: Callable[[Job], JobRunner])` — single background thread.
  - `Worker.reconcile() -> None` — on startup: leftover `queued` jobs re-enqueued FIFO; leftover `running` jobs → `interrupted` (no partial response), best-effort kill of a still-alive recorded pid only after a plausibility check.
  - `Worker.enqueue(job: Job) -> None` — raises `ConfigError` if a non-terminal job already exists for the same `topic_id`+`stage`.
  - `Worker.cancel(job_id: str) -> Job | None` — cancels a `queued` job (mark `canceled`) or signals a `running` job's cancel event; no-op on terminal.
  - `Worker.start()`, `Worker.stop(finish_inflight: bool = True)`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_worker.py`:

```python
import sys
import threading
import time
from pathlib import Path

import pytest

from education_pipeline import RunStore, parse_model_catalog, parse_model_plan
from education_pipeline.config import ConfigError
from education_pipeline.daemon.jobs import Job, JobRunner, JobStore, Worker
from education_pipeline.providers import Invocation, ProviderResponse, register_runner

FAKE = Path(__file__).parent / "fake_provider.py"


class FakeRunner:
    provider_id = "fake"
    executable = True

    def is_available(self):
        return True

    def build_invocation(self, model, plan, prompt_path):
        return Invocation(argv=[sys.executable, str(FAKE)])

    def parse_response(self, stdout):
        return ProviderResponse(text=stdout, metadata={})


def _factory(tmp_path):
    register_runner(FakeRunner())
    runs = RunStore(tmp_path)
    runs.create_run("t")
    p = runs.stage_paths("t", "draft").prompt_path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("PROMPT", encoding="utf-8")
    catalog = parse_model_catalog({"providers": [{"id": "fake", "models": [{"id": "m"}]}]})
    plan = parse_model_plan({"provider": "fake", "stages": {"draft": {"model": "m"}}}, catalog)
    store = JobStore(tmp_path)

    def make(job):
        return JobRunner(store, runs, catalog, plan, timeout=30)

    return store, runs, make


def _wait_terminal(store, job_id, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        job = store.find(job_id)
        if job and job.status in {"succeeded", "failed", "canceled", "interrupted"}:
            return job
        time.sleep(0.02)
    raise AssertionError("job did not reach a terminal state")


def test_worker_runs_enqueued_job_to_success(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_STDOUT", "OK\n")
    store, runs, make = _factory(tmp_path)
    worker = Worker(store, make)
    worker.start()
    try:
        job = store.create("t", "draft", "fake", "m", None)
        store.save(job)
        worker.enqueue(job)
        done = _wait_terminal(store, job.id)
        assert done.status == "succeeded"
    finally:
        worker.stop()


def test_worker_refuses_duplicate_active_job(tmp_path):
    store, runs, make = _factory(tmp_path)
    worker = Worker(store, make)
    a = store.create("t", "draft", "fake", "m", None)
    a.status = "queued"
    store.save(a)
    b = store.create("t", "draft", "fake", "m", None)
    with pytest.raises(ConfigError):
        worker.enqueue(b)


def test_reconcile_reenqueues_queued_and_interrupts_running(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_STDOUT", "OK\n")
    store, runs, make = _factory(tmp_path)
    # a leftover running job from a previous life, with a dead pid
    running = store.create("t", "draft", "fake", "m", None)
    running.status = "running"
    running.pid = 999999
    store.save(running)
    # a leftover queued job (different stage to dodge the duplicate guard)
    queued = store.create("t", "spec", "fake", "m", None)
    store.stage = "spec"
    p = runs.stage_paths("t", "spec").prompt_path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("PROMPT", encoding="utf-8")
    queued.status = "queued"
    store.save(queued)

    worker = Worker(store, make)
    worker.reconcile()
    assert store.find(running.id).status == "interrupted"
    assert not runs.has_ingested_response("t", "draft")
    worker.start()
    try:
        done = _wait_terminal(store, queued.id)
        assert done.status == "succeeded"
    finally:
        worker.stop()


def test_cancel_queued_job_marks_canceled(tmp_path):
    store, runs, make = _factory(tmp_path)
    worker = Worker(store, make)  # not started, so the job stays queued
    job = store.create("t", "draft", "fake", "m", None)
    store.save(job)
    worker.enqueue(job)
    result = worker.cancel(job.id)
    assert result.status == "canceled"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_worker.py -v`
Expected: FAIL — `Worker` does not exist (ImportError).

- [ ] **Step 3: Implement `Worker`**

Add to `education_pipeline/daemon/jobs.py` (add `import queue` and `from typing import Callable` to imports):

```python
class Worker:
    """A single-worker job queue with FIFO ordering and crash recovery."""

    def __init__(self, store: JobStore, runner_factory: Callable[[Job], JobRunner]) -> None:
        self.store = store
        self.runner_factory = runner_factory
        self._queue: "queue.Queue[str | None]" = queue.Queue()
        self._cancels: dict[str, threading.Event] = {}
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stopping = False

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="ep-worker", daemon=True)
        self._thread.start()

    def stop(self, finish_inflight: bool = True) -> None:
        self._stopping = True
        if not finish_inflight:
            with self._lock:
                for event in self._cancels.values():
                    event.set()
        self._queue.put(None)  # sentinel to wake the loop
        if self._thread is not None:
            self._thread.join(timeout=30)

    def enqueue(self, job: Job) -> None:
        existing = self.store.active_for(job.topic_id, job.stage)
        if existing is not None and existing.id != job.id:
            raise ConfigError(
                f"a {existing.status} job already exists for {job.topic_id}/{job.stage}"
            )
        with self._lock:
            self._cancels[job.id] = threading.Event()
        self._queue.put(job.id)

    def cancel(self, job_id: str) -> Job | None:
        job = self.store.find(job_id)
        if job is None or job.status in TERMINAL_STATUSES:
            return job
        with self._lock:
            event = self._cancels.get(job_id)
        if job.status == "queued":
            job.status = "canceled"
            job.ended_at = _utcnow().isoformat()
            self.store.save(job)
            if event is not None:
                event.set()
            return job
        if event is not None:
            event.set()
        return self.store.find(job_id)

    def reconcile(self) -> None:
        for job in self.store.all_jobs():
            if job.status == "running":
                if job.pid and _pid_plausibly_alive(job.pid):
                    _best_effort_kill(job.pid)
                job.status = "interrupted"
                job.error = "daemon restarted while job was running"
                job.ended_at = _utcnow().isoformat()
                job.pid = None
                self.store.save(job)
        for job in sorted(
            (j for j in self.store.all_jobs() if j.status == "queued"), key=lambda j: j.id
        ):
            with self._lock:
                self._cancels.setdefault(job.id, threading.Event())
            self._queue.put(job.id)

    def _loop(self) -> None:
        while True:
            job_id = self._queue.get()
            if job_id is None:
                return
            job = self.store.find(job_id)
            if job is None or job.status != "queued":
                continue
            with self._lock:
                cancel = self._cancels.get(job_id, threading.Event())
            if cancel.is_set():
                job.status = "canceled"
                job.ended_at = _utcnow().isoformat()
                self.store.save(job)
                continue
            runner = self.runner_factory(job)
            runner.execute(job, cancel)


def _pid_plausibly_alive(pid: int) -> bool:
    if sys.platform == "win32":  # pragma: no cover - Windows CI
        return True
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False
    except OSError:
        return False


def _best_effort_kill(pid: int) -> None:
    try:
        if sys.platform == "win32":  # pragma: no cover - Windows CI
            os.kill(pid, signal.SIGTERM)
        else:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
    except OSError:
        pass
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_worker.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add education_pipeline/daemon/jobs.py tests/test_worker.py
git commit -m "feat(daemon): Worker queue, duplicate guard, and orphan reconciliation"
```

---

## Task 9: Daemon discovery file and lifecycle helpers

**Files:**
- Create: `education_pipeline/daemon/lifecycle.py`
- Test: `tests/test_lifecycle.py`

**Interfaces:**
- Consumes: standard library only.
- Produces (all take `root: str | Path` = workspace):
  - `discovery_path(root) -> Path` → `<root>/.education-pipeline/daemon.json`.
  - `write_discovery(root, *, pid, port, token, version) -> None` — atomic, mode `0600`, fields `{pid, port, token, started_at, version}`.
  - `read_discovery(root) -> dict | None` — `None` if absent or unreadable.
  - `remove_discovery(root) -> None`.
  - `is_pid_alive(pid: int) -> bool`.
  - `claim_discovery(root) -> bool` — removes a stale file (dead pid), then `O_EXCL`-creates a placeholder; returns `True` if this caller claimed it, `False` if a live daemon already owns it.
  - `is_stale(record: dict) -> bool`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_lifecycle.py`:

```python
import os
import stat

import pytest

from education_pipeline.daemon import lifecycle


def test_write_read_remove_discovery_roundtrip(tmp_path):
    lifecycle.write_discovery(tmp_path, pid=1234, port=5555, token="tok", version="0.1.0")
    record = lifecycle.read_discovery(tmp_path)
    assert record["pid"] == 1234
    assert record["port"] == 5555
    assert record["token"] == "tok"
    assert record["version"] == "0.1.0"
    assert "started_at" in record
    lifecycle.remove_discovery(tmp_path)
    assert lifecycle.read_discovery(tmp_path) is None


@pytest.mark.skipif(os.name == "nt", reason="POSIX file mode")
def test_discovery_file_is_0600(tmp_path):
    lifecycle.write_discovery(tmp_path, pid=1, port=1, token="t", version="0.1.0")
    mode = stat.S_IMODE(os.stat(lifecycle.discovery_path(tmp_path)).st_mode)
    assert mode == 0o600


def test_read_discovery_absent_is_none(tmp_path):
    assert lifecycle.read_discovery(tmp_path) is None


def test_is_pid_alive_for_self_and_dead():
    assert lifecycle.is_pid_alive(os.getpid()) is True
    assert lifecycle.is_pid_alive(999999) is False


def test_claim_discovery_replaces_stale_and_blocks_live(tmp_path):
    # stale: dead pid → claimable
    lifecycle.write_discovery(tmp_path, pid=999999, port=1, token="t", version="0.1.0")
    assert lifecycle.claim_discovery(tmp_path) is True
    # live: our own pid → not claimable by a second caller
    lifecycle.write_discovery(tmp_path, pid=os.getpid(), port=1, token="t", version="0.1.0")
    assert lifecycle.claim_discovery(tmp_path) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_lifecycle.py -v`
Expected: FAIL — `education_pipeline.daemon.lifecycle` does not exist (ImportError).

- [ ] **Step 3: Implement `lifecycle.py`**

Create `education_pipeline/daemon/lifecycle.py`:

```python
"""Daemon discovery file: locate, authenticate, and claim the per-workspace daemon."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

_DISCOVERY_DIR = ".education-pipeline"
_DISCOVERY_FILE = "daemon.json"


def discovery_dir(root: str | Path) -> Path:
    return Path(root) / _DISCOVERY_DIR


def discovery_path(root: str | Path) -> Path:
    return discovery_dir(root) / _DISCOVERY_FILE


def write_discovery(root: str | Path, *, pid: int, port: int, token: str, version: str) -> None:
    target = discovery_path(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "pid": pid,
        "port": port,
        "token": token,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "version": version,
    }
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=".tmp-", suffix=".json")
    try:
        os.chmod(tmp, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(record, handle, indent=2)
        os.replace(tmp, target)
        os.chmod(target, 0o600)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def read_discovery(root: str | Path) -> dict | None:
    try:
        return json.loads(discovery_path(root).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def remove_discovery(root: str | Path) -> None:
    try:
        discovery_path(root).unlink()
    except FileNotFoundError:
        pass


def is_pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":  # pragma: no cover - Windows CI
        import ctypes

        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def is_stale(record: dict) -> bool:
    pid = record.get("pid")
    return not isinstance(pid, int) or not is_pid_alive(pid)


def claim_discovery(root: str | Path) -> bool:
    """Try to become the workspace daemon. Remove a stale file first.

    Returns True if this caller now owns the discovery slot (via an exclusive
    create), False if a live daemon already owns it.
    """

    record = read_discovery(root)
    if record is not None and not is_stale(record):
        return False
    remove_discovery(root)
    path = discovery_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return False
    os.close(fd)
    return True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_lifecycle.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add education_pipeline/daemon/lifecycle.py tests/test_lifecycle.py
git commit -m "feat(daemon): discovery file and lifecycle helpers"
```

---

## Task 10: Loopback HTTP JSON API server

**Files:**
- Create: `education_pipeline/daemon/server.py`
- Test: `tests/test_server.py`

**Interfaces:**
- Consumes: `JobStore`, `Worker` (Tasks 5-8), `RunStore` (for topic validation via `run_status`/safe-id), `__version__`.
- Produces:
  - `DaemonContext` dataclass: `root: Path`, `store: JobStore`, `worker: Worker`, `runs: RunStore`, `token: str`, `version: str`, `catalog: ModelCatalog`, `plan: ModelPlan`, `on_shutdown: Callable[[], None]`, plus `enqueue_stage(topic_id, stage, force) -> Job` (validates topic/stage, resolves provider/model from the plan, refuses when the run's next action is not `save_response` unless `force`).
  - `build_server(context) -> ThreadingHTTPServer` bound to `127.0.0.1:0`; `server.server_port` gives the ephemeral port.
  - Routes exactly the v1 API in the spec, with `X-EP-Token` auth (constant-time), `Host` allowlist (`127.0.0.1`/`localhost` only), and JSON error envelopes.

- [ ] **Step 1: Write the failing test**

Create `tests/test_server.py`:

```python
import http.client
import json
import sys
from pathlib import Path

import pytest

from education_pipeline import RunStore, parse_model_catalog, parse_model_plan
from education_pipeline.daemon.jobs import JobRunner, JobStore, Worker
from education_pipeline.daemon.server import DaemonContext, build_server
from education_pipeline.providers import Invocation, ProviderResponse, register_runner

FAKE = Path(__file__).parent / "fake_provider.py"


class FakeRunner:
    provider_id = "fake"
    executable = True

    def is_available(self):
        return True

    def build_invocation(self, model, plan, prompt_path):
        return Invocation(argv=[sys.executable, str(FAKE)])

    def parse_response(self, stdout):
        return ProviderResponse(text=stdout, metadata={})


@pytest.fixture
def server(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_STDOUT", "GENERATED\n")
    register_runner(FakeRunner())
    runs = RunStore(tmp_path)
    runs.create_run("t")
    # drive to the point where draft is the "save_response" next action:
    # write the draft prompt so next_action == save_response for draft
    p = runs.stage_paths("t", "draft").prompt_path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("PROMPT", encoding="utf-8")
    catalog = parse_model_catalog({"providers": [{"id": "fake", "models": [{"id": "m"}]}]})
    plan = parse_model_plan({"provider": "fake", "stages": {"draft": {"model": "m"}}}, catalog)
    store = JobStore(tmp_path)
    worker = Worker(store, lambda job: JobRunner(store, runs, catalog, plan, timeout=30))
    context = DaemonContext(
        root=tmp_path,
        store=store,
        worker=worker,
        runs=runs,
        token="secret-token",
        version="0.1.0",
        catalog=catalog,
        plan=plan,
        on_shutdown=lambda: None,
    )
    srv = build_server(context)
    port = srv.server_port
    import threading

    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    worker.start()
    yield port
    worker.stop()
    srv.shutdown()


def _req(port, method, path, token="secret-token", body=None):
    conn = http.client.HTTPConnection("127.0.0.1", port)
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["X-EP-Token"] = token
    conn.request(method, path, body=json.dumps(body) if body else None, headers=headers)
    resp = conn.getresponse()
    payload = json.loads(resp.read() or b"{}")
    conn.close()
    return resp.status, payload


def test_health_requires_token(server):
    status, _ = _req(server, "GET", "/v1/health", token=None)
    assert status == 401


def test_health_ok(server):
    status, body = _req(server, "GET", "/v1/health")
    assert status == 200
    assert body["version"] == "0.1.0"


def test_enqueue_runs_job_and_lands_response(server):
    status, body = _req(server, "POST", "/v1/jobs", body={"topic_id": "t", "stage": "draft"})
    assert status == 200
    job_id = body["id"]
    # poll until terminal
    import time

    for _ in range(200):
        status, job = _req(server, "GET", f"/v1/jobs/{job_id}")
        if job["status"] in {"succeeded", "failed", "canceled", "interrupted"}:
            break
        time.sleep(0.02)
    assert job["status"] == "succeeded"


def test_enqueue_rejects_unknown_topic(server):
    status, body = _req(server, "POST", "/v1/jobs", body={"topic_id": "../evil", "stage": "draft"})
    assert status == 400
    assert "error" in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_server.py -v`
Expected: FAIL — `education_pipeline.daemon.server` does not exist (ImportError).

- [ ] **Step 3: Implement `server.py`**

Create `education_pipeline/daemon/server.py`:

```python
"""Loopback JSON API for the run daemon (v1).

Binds strictly to 127.0.0.1 on an ephemeral port. Every request must present the
``X-EP-Token`` header (constant-time compared). The Host header is restricted to
localhost to blunt DNS-rebinding from a future browser client.
"""

from __future__ import annotations

import json
import re
import secrets
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable

from education_pipeline.config import ConfigError, ModelCatalog, ModelPlan
from education_pipeline.daemon.jobs import Job, JobStore, Worker
from education_pipeline.runs import RunStore, SUPPORTED_STAGES

_ALLOWED_HOSTS = {"127.0.0.1", "localhost"}


@dataclass
class DaemonContext:
    root: Path
    store: JobStore
    worker: Worker
    runs: RunStore
    token: str
    version: str
    catalog: ModelCatalog
    plan: ModelPlan
    on_shutdown: Callable[[], None]

    def enqueue_stage(self, topic_id: str, stage: str | None, force: bool) -> Job:
        # Validate topic against the workspace (reuses safe-id logic in RunStore).
        status = self.runs.run_status(topic_id)
        target_stage = stage or status.next_action.stage
        if target_stage is None or target_stage not in SUPPORTED_STAGES:
            raise ConfigError(
                f"stage {target_stage!r} is not an executable stage; "
                f"executable stages: {', '.join(SUPPORTED_STAGES)}"
            )
        # Structural approval gate: only enqueue when the next action is to run a prompt.
        action = status.next_action
        if stage is None and action.action != "save_response":
            raise ConfigError(
                f"nothing to run: next action is {action.action!r} — {action.detail}"
            )
        if self.store.active_for(topic_id, target_stage) is not None:
            raise ConfigError(
                f"a job is already active for {topic_id}/{target_stage}"
            )
        stage_plan = self.plan.stage(target_stage)
        provider = stage_plan.provider or self.plan.provider
        job = self.store.create(topic_id, target_stage, provider, stage_plan.model, stage_plan.effort)
        job.metadata["force"] = force
        self.store.save(job)
        self.worker.enqueue(job)
        return job


def build_server(context: DaemonContext) -> ThreadingHTTPServer:
    handler = _make_handler(context)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    return server


def _make_handler(context: DaemonContext):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):  # silence default stderr logging
            pass

        def _host_ok(self) -> bool:
            host = (self.headers.get("Host") or "").split(":")[0]
            return host in _ALLOWED_HOSTS

        def _authed(self) -> bool:
            presented = self.headers.get("X-EP-Token", "")
            return secrets.compare_digest(presented, context.token)

        def _send(self, status: int, payload: dict) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _error(self, status: int, code: str, message: str) -> None:
            self._send(status, {"error": {"code": code, "message": message}})

        def _guard(self) -> bool:
            if not self._host_ok():
                self._error(400, "bad_host", "host not allowed")
                return False
            if not self._authed():
                self._error(401, "unauthorized", "missing or invalid token")
                return False
            return True

        def _read_body(self) -> dict:
            length = int(self.headers.get("Content-Length", 0))
            if not length:
                return {}
            return json.loads(self.rfile.read(length) or b"{}")

        def do_GET(self):
            if not self._guard():
                return
            if self.path.startswith("/v1/health"):
                self._send(200, {"version": context.version, "started_at": None, "ok": True})
                return
            m = re.match(r"^/v1/jobs/([^/]+)/log(?:\?offset=(\d+))?$", self.path)
            if m:
                job = context.store.find(m.group(1))
                if job is None:
                    return self._error(404, "not_found", "no such job")
                offset = int(m.group(2) or 0)
                data, next_offset = context.store.read_log(job, offset)
                return self._send(200, {"data": data.decode("utf-8", "replace"), "offset": next_offset})
            m = re.match(r"^/v1/jobs/([^/]+)$", self.path)
            if m:
                job = context.store.find(m.group(1))
                if job is None:
                    return self._error(404, "not_found", "no such job")
                return self._send(200, job.to_dict())
            m = re.match(r"^/v1/jobs(?:\?topic=([^&]+))?$", self.path)
            if m:
                jobs = context.store.list(m.group(1))
                return self._send(200, {"jobs": [j.to_dict() for j in jobs]})
            self._error(404, "not_found", "unknown path")

        def do_POST(self):
            if not self._guard():
                return
            try:
                if self.path == "/v1/jobs":
                    body = self._read_body()
                    job = context.enqueue_stage(
                        body.get("topic_id", ""), body.get("stage"), bool(body.get("force"))
                    )
                    return self._send(200, job.to_dict())
                m = re.match(r"^/v1/jobs/([^/]+)/cancel$", self.path)
                if m:
                    job = context.worker.cancel(m.group(1))
                    if job is None:
                        return self._error(404, "not_found", "no such job")
                    return self._send(200, job.to_dict())
                if self.path == "/v1/shutdown":
                    self._send(200, {"ok": True})
                    context.on_shutdown()
                    return
            except ConfigError as exc:
                return self._error(400, "bad_request", str(exc))
            self._error(404, "not_found", "unknown path")

    return Handler
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_server.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add education_pipeline/daemon/server.py tests/test_server.py
git commit -m "feat(daemon): loopback JSON API server with token auth"
```

---

## Task 11: Daemon entrypoint (`serve`) and `python -m education_pipeline.daemon`

**Files:**
- Modify: `education_pipeline/daemon/__init__.py` (add `serve`, `load_workspace_config`)
- Create: `education_pipeline/daemon/__main__.py`
- Test: `tests/test_daemon_serve.py`

**Interfaces:**
- Consumes: `JobStore`, `Worker`, `JobRunner`, `build_server`, `DaemonContext`, lifecycle helpers, `RunStore`, config loaders, `education_pipeline.__version__`.
- Produces:
  - `education_pipeline.__version__` string (add to `education_pipeline/__init__.py`).
  - `load_workspace_config(root) -> tuple[ModelCatalog, ModelPlan]` — loads `<root>/config/model-catalog.toml` + `<root>/config/model-plan.toml`, falling back to the packaged `config/*.example.toml` when absent.
  - `serve(root, *, timeout=DEFAULT_TIMEOUT_SECONDS, ready: threading.Event | None = None) -> None` — reconciles orphans, writes the discovery file, starts the worker and server, blocks until shutdown, then removes the discovery file.
  - `python -m education_pipeline.daemon <workspace>` runs `serve`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_daemon_serve.py`:

```python
import http.client
import json
import threading
import time
from pathlib import Path

from education_pipeline import RunStore
from education_pipeline.daemon import serve
from education_pipeline.daemon import lifecycle


def _health(port, token):
    conn = http.client.HTTPConnection("127.0.0.1", port)
    conn.request("GET", "/v1/health", headers={"X-EP-Token": token})
    resp = conn.getresponse()
    body = json.loads(resp.read())
    conn.close()
    return resp.status, body


def test_serve_writes_discovery_and_serves_health(tmp_path):
    RunStore(tmp_path).create_run("t")
    ready = threading.Event()
    thread = threading.Thread(target=serve, args=(tmp_path,), kwargs={"ready": ready}, daemon=True)
    thread.start()
    assert ready.wait(timeout=10)
    record = lifecycle.read_discovery(tmp_path)
    assert record is not None
    status, body = _health(record["port"], record["token"])
    assert status == 200
    # graceful shutdown via the API
    conn = http.client.HTTPConnection("127.0.0.1", record["port"])
    conn.request("POST", "/v1/shutdown", headers={"X-EP-Token": record["token"]})
    conn.getresponse().read()
    conn.close()
    thread.join(timeout=10)
    assert lifecycle.read_discovery(tmp_path) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_daemon_serve.py -v`
Expected: FAIL — `serve` is not importable from `education_pipeline.daemon` (ImportError).

- [ ] **Step 3: Add a package version**

In `education_pipeline/__init__.py`, add near the top (after the module docstring):

```python
__version__ = "0.1.0"
```

and add `"__version__"` to `__all__`.

- [ ] **Step 4: Implement `serve` and config loading**

Replace `education_pipeline/daemon/__init__.py` with:

```python
"""Long-lived local run daemon: job queue, worker, and loopback JSON API."""

from __future__ import annotations

import os
import secrets
import threading
from pathlib import Path

from education_pipeline import __version__
from education_pipeline.config import (
    ModelCatalog,
    ModelPlan,
    load_model_catalog,
    load_model_plan,
)
from education_pipeline.daemon import lifecycle
from education_pipeline.daemon.jobs import (
    DEFAULT_TIMEOUT_SECONDS,
    JobRunner,
    JobStore,
    Worker,
)
from education_pipeline.daemon.server import DaemonContext, build_server
from education_pipeline.runs import RunStore

_PACKAGE_CONFIG = Path(__file__).resolve().parents[2] / "config"


def load_workspace_config(root: str | Path) -> tuple[ModelCatalog, ModelPlan]:
    """Load the workspace model catalog + plan, falling back to packaged examples."""

    root = Path(root)
    catalog_path = root / "config" / "model-catalog.toml"
    plan_path = root / "config" / "model-plan.toml"
    if not catalog_path.exists():
        catalog_path = _PACKAGE_CONFIG / "model-catalog.example.toml"
    if not plan_path.exists():
        plan_path = _PACKAGE_CONFIG / "model-plan.example.toml"
    catalog = load_model_catalog(catalog_path)
    plan = load_model_plan(plan_path, catalog)
    return catalog, plan


def serve(
    root: str | Path,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ready: threading.Event | None = None,
) -> None:
    """Run the daemon until shutdown, owning the workspace discovery file."""

    root = Path(root)
    catalog, plan = load_workspace_config(root)
    store = JobStore(root)
    runs = RunStore(root)
    worker = Worker(store, lambda job: JobRunner(store, runs, catalog, plan, timeout=timeout,
                                                 force=bool(job.metadata.get("force"))))
    worker.reconcile()
    worker.start()

    token = secrets.token_urlsafe(32)
    shutdown = threading.Event()
    context = DaemonContext(
        root=root,
        store=store,
        worker=worker,
        runs=runs,
        token=token,
        version=__version__,
        catalog=catalog,
        plan=plan,
        on_shutdown=shutdown.set,
    )
    server = build_server(context)
    lifecycle.write_discovery(root, pid=os.getpid(), port=server.server_port, token=token,
                              version=__version__)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    if ready is not None:
        ready.set()
    try:
        shutdown.wait()
    finally:
        server.shutdown()
        worker.stop()
        lifecycle.remove_discovery(root)
```

- [ ] **Step 5: Add the module entrypoint**

Create `education_pipeline/daemon/__main__.py`:

```python
"""``python -m education_pipeline.daemon <workspace>`` runs the run daemon."""

from __future__ import annotations

import sys

from education_pipeline.daemon import serve


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    root = args[0] if args else "."
    serve(root)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_daemon_serve.py tests/test_providers.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add education_pipeline/daemon/__init__.py education_pipeline/daemon/__main__.py education_pipeline/__init__.py tests/test_daemon_serve.py
git commit -m "feat(daemon): serve entrypoint, config loading, and __main__"
```

---

## Task 12: CLI-side daemon client with autostart

**Files:**
- Create: `education_pipeline/client.py`
- Test: `tests/test_client.py`

**Interfaces:**
- Consumes: `lifecycle.read_discovery` / `is_stale` / `is_pid_alive`, `education_pipeline.__version__`.
- Produces:
  - `DaemonError(RuntimeError)`.
  - `DaemonClient(root, record)` with methods `health()`, `enqueue(topic_id, stage=None, force=False) -> dict`, `list_jobs(topic=None) -> list[dict]`, `get_job(job_id) -> dict`, `get_log(job_id, offset=0) -> tuple[str, int]`, `cancel(job_id) -> dict`, `shutdown() -> None`. Each raises `DaemonError` on non-2xx (surfacing the JSON `error.message`).
  - `ensure_daemon(root, *, autostart=True, timeout=15.0) -> DaemonClient` — returns a client for a live daemon, spawning one (detached) if none is live and `autostart`.
  - `daemon_status(root) -> dict` — `{running, pid, port, version, version_mismatch}`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_client.py`:

```python
import threading

import pytest

from education_pipeline import RunStore
from education_pipeline.client import DaemonError, ensure_daemon, daemon_status
from education_pipeline.daemon import lifecycle


def test_ensure_daemon_autostarts_and_reports_status(tmp_path):
    RunStore(tmp_path).create_run("t")
    client = ensure_daemon(tmp_path, autostart=True, timeout=15)
    try:
        health = client.health()
        assert health["ok"] is True
        status = daemon_status(tmp_path)
        assert status["running"] is True
        assert status["port"] == lifecycle.read_discovery(tmp_path)["port"]
    finally:
        client.shutdown()


def test_ensure_daemon_no_autostart_raises_when_absent(tmp_path):
    with pytest.raises(DaemonError):
        ensure_daemon(tmp_path, autostart=False)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_client.py -v`
Expected: FAIL — `education_pipeline.client` does not exist (ImportError).

- [ ] **Step 3: Implement `client.py`**

Create `education_pipeline/client.py`:

```python
"""Thin CLI-side HTTP client for the run daemon, with autostart."""

from __future__ import annotations

import http.client
import json
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import quote

from education_pipeline import __version__
from education_pipeline.daemon import lifecycle


class DaemonError(RuntimeError):
    """Raised when the daemon is unreachable or returns an error envelope."""


class DaemonClient:
    def __init__(self, root: str | Path, record: dict) -> None:
        self.root = Path(root)
        self.port = record["port"]
        self.token = record["token"]

    def _call(self, method: str, path: str, body: dict | None = None) -> dict:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        headers = {"X-EP-Token": self.token, "Content-Type": "application/json"}
        payload = json.dumps(body).encode("utf-8") if body is not None else None
        try:
            conn.request(method, path, body=payload, headers=headers)
            resp = conn.getresponse()
            raw = resp.read()
        except OSError as exc:
            raise DaemonError(f"daemon unreachable: {exc}") from exc
        finally:
            conn.close()
        data = json.loads(raw or b"{}")
        if resp.status >= 300:
            message = data.get("error", {}).get("message", f"HTTP {resp.status}")
            raise DaemonError(message)
        return data

    def health(self) -> dict:
        return self._call("GET", "/v1/health")

    def enqueue(self, topic_id: str, stage: str | None = None, force: bool = False) -> dict:
        body = {"topic_id": topic_id, "force": force}
        if stage is not None:
            body["stage"] = stage
        return self._call("POST", "/v1/jobs", body)

    def list_jobs(self, topic: str | None = None) -> list[dict]:
        path = "/v1/jobs" if topic is None else f"/v1/jobs?topic={quote(topic)}"
        return self._call("GET", path).get("jobs", [])

    def get_job(self, job_id: str) -> dict:
        return self._call("GET", f"/v1/jobs/{quote(job_id)}")

    def get_log(self, job_id: str, offset: int = 0) -> tuple[str, int]:
        data = self._call("GET", f"/v1/jobs/{quote(job_id)}/log?offset={offset}")
        return data.get("data", ""), data.get("offset", offset)

    def cancel(self, job_id: str) -> dict:
        return self._call("POST", f"/v1/jobs/{quote(job_id)}/cancel")

    def shutdown(self) -> None:
        self._call("POST", "/v1/shutdown")


def _live_record(root: str | Path) -> dict | None:
    record = lifecycle.read_discovery(root)
    if record is None or lifecycle.is_stale(record):
        return None
    return record


def ensure_daemon(root: str | Path, *, autostart: bool = True, timeout: float = 15.0) -> DaemonClient:
    record = _live_record(root)
    if record is not None:
        return DaemonClient(root, record)
    if not autostart:
        raise DaemonError("no daemon running; start one with 'daemon start'")
    subprocess.Popen(
        [sys.executable, "-m", "education_pipeline.daemon", str(root)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        record = _live_record(root)
        if record is not None:
            client = DaemonClient(root, record)
            try:
                client.health()
                return client
            except DaemonError:
                pass
        time.sleep(0.1)
    raise DaemonError("daemon did not become ready in time")


def daemon_status(root: str | Path) -> dict:
    record = lifecycle.read_discovery(root)
    if record is None:
        return {"running": False, "pid": None, "port": None, "version": None,
                "version_mismatch": False}
    running = not lifecycle.is_stale(record)
    return {
        "running": running,
        "pid": record.get("pid"),
        "port": record.get("port"),
        "version": record.get("version"),
        "version_mismatch": record.get("version") != __version__,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_client.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add education_pipeline/client.py tests/test_client.py
git commit -m "feat(client): daemon HTTP client with autostart and status"
```

---

## Task 13: CLI commands — `run`, `jobs`, `job`, `logs`, `cancel`, `daemon`

**Files:**
- Modify: `education_pipeline/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `ensure_daemon`, `daemon_status`, `DaemonError`, `DaemonClient` (Task 12); `lifecycle` (for `daemon stop`).
- Produces: new subcommands wired into `_build_parser`, each a thin client of the daemon API:
  - `run <topic> [--stage S] [--wait] [--force] [--no-autostart]`
  - `jobs [<topic>]`, `job <job-id>`, `logs <job-id> [-f]`, `cancel <job-id>`
  - `daemon start|stop|status`
  - Exit codes: enqueue-only `run` exits 0 once accepted; `run --wait` exits 0 only on `succeeded`; `cancel` of a terminal job exits 0.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_cli.py`:

```python
def _seed_topic_to_draft(ws: Path):
    """Advance a run so the next action is 'save_response' for the draft stage."""
    from education_pipeline import RunStore

    runs = RunStore(ws)
    runs.create_run("systems-thinking")
    # spec -> approved
    runs.write_spec_prompt("systems-thinking", title="Systems Thinking")
    runs.response_path("systems-thinking", "spec").write_text("# Spec\n", encoding="utf-8")
    runs.approve_stage("systems-thinking", "spec")
    # outline -> approved
    runs.write_outline_prompt("systems-thinking")
    runs.response_path("systems-thinking", "outline").write_text("# Outline\n", encoding="utf-8")
    runs.approve_stage("systems-thinking", "outline")
    # draft prompt written, no response yet -> next action is save_response(draft)
    runs.write_draft_prompt("systems-thinking")


def test_daemon_status_reports_stopped(tmp_path, capsys):
    assert _run(tmp_path, "daemon", "status") == 0
    assert "stopped" in capsys.readouterr().out.lower()


def test_run_wait_executes_and_lands_response(tmp_path, monkeypatch):
    import sys

    from education_pipeline.providers import Invocation, ProviderResponse, register_runner

    class FakeRunner:
        provider_id = "fake"
        executable = True

        def is_available(self):
            return True

        def build_invocation(self, model, plan, prompt_path):
            fake = Path(__file__).parent / "fake_provider.py"
            return Invocation(argv=[sys.executable, str(fake)])

        def parse_response(self, stdout):
            return ProviderResponse(text=stdout, metadata={})

    register_runner(FakeRunner())
    monkeypatch.setenv("FAKE_STDOUT", "# Generated draft\n")
    # workspace config points the plan's draft stage at the fake provider
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "model-catalog.toml").write_text(
        '[[providers]]\nid = "fake"\n[[providers.models]]\nid = "m"\n', encoding="utf-8"
    )
    (cfg / "model-plan.toml").write_text(
        'provider = "fake"\n[stages.draft]\nmodel = "m"\n', encoding="utf-8"
    )
    _seed_topic_to_draft(tmp_path)
    code = _run(tmp_path, "run", "systems-thinking", "--wait")
    assert code == 0
    from education_pipeline import RunStore

    assert RunStore(tmp_path).response_path("systems-thinking", "draft").read_text(
        encoding="utf-8"
    ) == "# Generated draft\n"
    _run(tmp_path, "daemon", "stop")


def test_run_refuses_when_next_action_is_approval(tmp_path, capsys):
    from education_pipeline import RunStore

    runs = RunStore(tmp_path)
    runs.create_run("systems-thinking")
    runs.write_spec_prompt("systems-thinking", title="Systems Thinking")
    runs.response_path("systems-thinking", "spec").write_text("# Spec\n", encoding="utf-8")
    runs.approve_stage("systems-thinking", "spec")
    runs.write_outline_prompt("systems-thinking")
    runs.response_path("systems-thinking", "outline").write_text("# Outline\n", encoding="utf-8")
    # next action is 'approve' outline, not 'save_response'
    code = _run(tmp_path, "run", "systems-thinking")
    assert code == 1
    _run(tmp_path, "daemon", "stop")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_cli.py -k "daemon_status or run_wait or run_refuses" -v`
Expected: FAIL — `run` / `daemon` subcommands are not defined (argparse `SystemExit`).

- [ ] **Step 3: Wire the new commands into the parser**

In `education_pipeline/cli.py`, add imports at the top:

```python
import time

from education_pipeline.client import DaemonClient, DaemonError, daemon_status, ensure_daemon
from education_pipeline.daemon import lifecycle
```

Then, inside `_build_parser`, before `return parser`, add:

```python
    p = sub.add_parser("run", help="enqueue the next-stage provider run for a topic")
    p.add_argument("topic_id")
    p.add_argument("--stage", default=None, help="override the stage to run")
    p.add_argument("--wait", action="store_true", help="block until the job is terminal")
    p.add_argument("--force", action="store_true", help="override the no-clobber refusal")
    p.add_argument("--no-autostart", dest="autostart", action="store_false")
    p.set_defaults(func=_cmd_run, autostart=True)

    p = sub.add_parser("jobs", help="list jobs (optionally for one topic)")
    p.add_argument("topic_id", nargs="?", default=None)
    p.set_defaults(func=_cmd_jobs)

    p = sub.add_parser("job", help="show one job's full record")
    p.add_argument("job_id")
    p.set_defaults(func=_cmd_job)

    p = sub.add_parser("logs", help="print or follow a job's output log")
    p.add_argument("job_id")
    p.add_argument("-f", "--follow", action="store_true")
    p.set_defaults(func=_cmd_logs)

    p = sub.add_parser("cancel", help="cancel a queued or running job")
    p.add_argument("job_id")
    p.set_defaults(func=_cmd_cancel)

    daemon = sub.add_parser("daemon", help="manage the run daemon").add_subparsers(
        dest="daemon_command", required=True
    )
    daemon.add_parser("start", help="start the run daemon").set_defaults(func=_cmd_daemon_start)
    daemon.add_parser("stop", help="stop the run daemon").set_defaults(func=_cmd_daemon_stop)
    daemon.add_parser("status", help="show daemon status").set_defaults(func=_cmd_daemon_status)
```

- [ ] **Step 4: Add the command handlers**

Also add `from education_pipeline.daemon.jobs import TERMINAL_STATUSES` to the imports, then add these handlers to `cli.py` (before `_print_next`):

```python
def _cmd_run(args: argparse.Namespace) -> int:
    root = _root(args)
    try:
        client = ensure_daemon(root, autostart=args.autostart)
        job = client.enqueue(args.topic_id, stage=args.stage, force=args.force)
    except DaemonError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"enqueued job {job['id']} ({job['stage']})")
    if not args.wait:
        return 0
    while True:
        job = client.get_job(job["id"])
        if job["status"] in TERMINAL_STATUSES:
            break
        time.sleep(0.25)
    log_path = job.get("response_path") or "(see logs)"
    print(f"job {job['id']} {job['status']}")
    if job["status"] == "succeeded":
        print(f"response: {log_path}")
        return 0
    if job.get("error"):
        print(f"error: {job['error']}", file=sys.stderr)
    print(f"log: education-pipeline -C {args.workspace} logs {job['id']}", file=sys.stderr)
    return 1


def _cmd_jobs(args: argparse.Namespace) -> int:
    client = ensure_daemon(_root(args), autostart=False)
    jobs = client.list_jobs(args.topic_id)
    if not jobs:
        print("(no jobs)")
        return 0
    for job in jobs:
        print(f"{job['id']}  {job['status']:11s}  {job['topic_id']}/{job['stage']}")
    return 0


def _cmd_job(args: argparse.Namespace) -> int:
    import json

    client = ensure_daemon(_root(args), autostart=False)
    print(json.dumps(client.get_job(args.job_id), indent=2))
    return 0


def _cmd_logs(args: argparse.Namespace) -> int:
    client = ensure_daemon(_root(args), autostart=False)
    offset = 0
    while True:
        chunk, offset = client.get_log(args.job_id, offset)
        if chunk:
            print(chunk, end="")
        if not args.follow:
            break
        if client.get_job(args.job_id)["status"] in TERMINAL_STATUSES and not chunk:
            break
        time.sleep(0.25)
    return 0


def _cmd_cancel(args: argparse.Namespace) -> int:
    client = ensure_daemon(_root(args), autostart=False)
    job = client.cancel(args.job_id)
    print(f"job {job['id']} {job['status']}")
    return 0


def _cmd_daemon_start(args: argparse.Namespace) -> int:
    root = _root(args)
    status = daemon_status(root)
    if status["running"]:
        print(f"daemon already running (pid {status['pid']}, port {status['port']})")
        return 0
    client = ensure_daemon(root, autostart=True)
    health = client.health()
    print(f"daemon started (version {health['version']})")
    return 0


def _cmd_daemon_stop(args: argparse.Namespace) -> int:
    root = _root(args)
    status = daemon_status(root)
    if not status["running"]:
        print("daemon not running")
        lifecycle.remove_discovery(root)
        return 0
    try:
        ensure_daemon(root, autostart=False).shutdown()
    except DaemonError:
        pass
    print("daemon stopped")
    return 0


def _cmd_daemon_status(args: argparse.Namespace) -> int:
    status = daemon_status(_root(args))
    if not status["running"]:
        print("daemon: stopped")
        return 0
    warn = "  [version mismatch: restart the daemon]" if status["version_mismatch"] else ""
    print(f"daemon: running  pid={status['pid']}  port={status['port']}  "
          f"version={status['version']}{warn}")
    return 0
```

Finally, wrap the `DaemonError` from `main` so client failures print cleanly. In `main`, change the `except` block (lines 36-38) to:

```python
    try:
        return args.func(args)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except DaemonError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_cli.py -v`
Expected: PASS (existing CLI tests plus the three new ones).

- [ ] **Step 6: Commit**

```bash
git add education_pipeline/cli.py tests/test_cli.py
git commit -m "feat(cli): run/jobs/job/logs/cancel/daemon commands"
```

---

## Task 14: Example catalog values, auth hardening test, and full-stack e2e

**Files:**
- Modify: `config/model-catalog.example.toml`
- Test: `tests/test_server.py` (auth allowlist), `tests/test_e2e.py`
- Modify: `README.md` (document the `run`/`daemon` commands)

**Interfaces:**
- Consumes: everything built above.
- Produces: filled-in `argv_model`/`extra_args` in the example catalog; an end-to-end test proving a CLI `run --wait` lands a response and appends a manifest event; an auth test proving a bad token and a disallowed Host are rejected.

- [ ] **Step 1: Write the failing auth + e2e tests**

Add to `tests/test_server.py`:

```python
def test_bad_token_rejected(server):
    status, body = _req(server, "GET", "/v1/health", token="wrong")
    assert status == 401
    assert body["error"]["code"] == "unauthorized"


def test_bad_host_rejected(server):
    import http.client

    conn = http.client.HTTPConnection("127.0.0.1", server)
    conn.putrequest("GET", "/v1/health", skip_host=True)
    conn.putheader("Host", "evil.example.com")
    conn.putheader("X-EP-Token", "secret-token")
    conn.endheaders()
    resp = conn.getresponse()
    conn.close()
    assert resp.status == 400
```

Create `tests/test_e2e.py`:

```python
import sys
from pathlib import Path

from education_pipeline import RunStore
from education_pipeline.cli import main
from education_pipeline.providers import Invocation, ProviderResponse, register_runner

FAKE = Path(__file__).parent / "fake_provider.py"


class FakeRunner:
    provider_id = "fake"
    executable = True

    def is_available(self):
        return True

    def build_invocation(self, model, plan, prompt_path):
        return Invocation(argv=[sys.executable, str(FAKE)])

    def parse_response(self, stdout):
        return ProviderResponse(text=stdout, metadata={"echo": True})


def _write_config(ws: Path):
    cfg = ws / "config"
    cfg.mkdir()
    (cfg / "model-catalog.toml").write_text(
        '[[providers]]\nid = "fake"\n[[providers.models]]\nid = "m"\n', encoding="utf-8"
    )
    (cfg / "model-plan.toml").write_text(
        'provider = "fake"\n[stages.spec]\nmodel = "m"\n', encoding="utf-8"
    )


def test_full_run_via_cli_lands_response_and_manifest_event(tmp_path, monkeypatch):
    register_runner(FakeRunner())
    monkeypatch.setenv("FAKE_STDOUT", "# Executed spec\n")
    _write_config(tmp_path)
    runs = RunStore(tmp_path)
    runs.write_spec_prompt("systems-thinking", title="Systems Thinking")  # next action: save_response(spec)

    code = main(["-C", str(tmp_path), "run", "systems-thinking", "--wait"])
    assert code == 0
    assert runs.response_path("systems-thinking", "spec").read_text(encoding="utf-8") == "# Executed spec\n"
    actions = [e["action"] for e in runs.read_manifest("systems-thinking")["events"]]
    assert "job" in actions
    main(["-C", str(tmp_path), "daemon", "stop"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_server.py -k "bad_token or bad_host" tests/test_e2e.py -v`
Expected: `test_bad_token_rejected` may already pass (auth exists); `test_bad_host_rejected` must pass given Task 10's Host guard — if it fails, fix the Host check. `test_e2e` should PASS end-to-end. Any failure here is a real integration gap to fix before continuing.

- [ ] **Step 3: Fill in the example catalog**

Edit `config/model-catalog.example.toml` to add concrete `argv_model` values (and an `extra_args` example) under the executable providers. Under the `claude-code` `premium-reasoning` model add:

```toml
argv_model = "claude-opus-4-8"
extra_args = ["--reasoning", "high"]
```

Under the `claude-code` `balanced` model add:

```toml
argv_model = "claude-sonnet-5"
```

Under the `codex` `balanced` model add:

```toml
argv_model = "gpt-5.4-codex"
```

Under the `codex` `fast-check` model add:

```toml
argv_model = "gpt-5.4-codex-mini"
```

- [ ] **Step 4: Document the commands in the README**

In `README.md`, add a short section after the existing CLI walkthrough:

```markdown
### Executing a stage through a provider

Instead of copying a prompt into a model UI, run it through a configured
provider (Claude Code or Codex):

    education-pipeline -C ./ws run systems-thinking --wait   # runs the next stage
    education-pipeline -C ./ws jobs systems-thinking          # list jobs
    education-pipeline -C ./ws logs <job-id> -f               # follow output
    education-pipeline -C ./ws daemon status                  # daemon health

`run` executes exactly the run's next stage and stops for your approval; it
never auto-approves. The first `run` auto-starts a local, loopback-only daemon
(opt out with `--no-autostart`); stop it with `daemon stop`.
```

- [ ] **Step 5: Run the whole suite**

Run: `python -m pytest -q`
Expected: PASS — all pre-existing tests plus every test added in Tasks 1-14.

- [ ] **Step 6: Commit**

```bash
git add config/model-catalog.example.toml README.md tests/test_server.py tests/test_e2e.py
git commit -m "feat: example catalog argv values, auth hardening test, e2e run"
```

---

## Self-Review

**Spec coverage:**

- Run daemon owning a job queue + worker → Tasks 5-8, 11.
- JSON API over loopback HTTP, token-authenticated → Task 10 (all seven endpoints), Task 12 client.
- Pluggable adapters for claude-code/codex; manual non-executable → Tasks 2-3.
- Durable, resumable jobs persisted under the workspace → Task 5 (`JobStore`), reconciliation in Task 8.
- New CLI commands run/jobs/job/logs/cancel/daemon → Task 13.
- Transport & security: 127.0.0.1 + ephemeral port (Task 10), token `secrets.token_urlsafe` + `compare_digest` (Tasks 10-11), atomic `0600` `daemon.json` (Task 9), Host allowlist (Tasks 10, 14), token not in child env (Task 7 `_spawn` uses `os.environ` + only `invocation.env`, never the daemon token), version mismatch warning (Task 12 `daemon_status`, Task 13 `daemon status`), one-daemon-per-workspace + topic validation (Tasks 9-10).
- Job model & persistence: fields, id format, status lifecycle, no-duplicate-active, timeout, output caps, atomic gated response write, manifest `job` event, no empty/whitespace, no clobber unless force → Tasks 4, 5, 7, 8, 10.
- Provider adapters: `ProviderRunner`, `Invocation`, Claude JSON `.result` + cost/session, tools disabled, Codex read-only + stdin `-`, typed `ModelOption` fields, effort-as-provenance (recorded on job, not mapped to a flag) → Tasks 1-3, 7.
- Daemon lifecycle & crash recovery: discovery file, start/stop/status, autostart with `O_EXCL` race guard, stale detection, orphan reconciliation, concurrency 1 → Tasks 8-9, 11-13.
- CLI surface & exit codes → Task 13.
- Error handling (all cases) → Task 7 (unavailable, non-zero, empty, malformed JSON, timeout), Task 8 (orphan→interrupted, cancel), Task 6 (portable termination), Task 10 (already-ingested via `force`/`active_for`). No automatic retries: nothing re-enqueues a failed job — consistent with spec.
- Testing strategy: fake provider (Task 7), adapter unit tests (Task 3), daemon API test (Tasks 10-11), lifecycle/recovery (Tasks 8-9), job guards (Tasks 7-8, 10), CLI (Task 13), auth (Tasks 10, 14), cross-platform termination (Task 6), real CLIs stay out of CI (all tests use the fake or unit-level `build_invocation`).
- Constraints preserved: stdlib-only (no imports outside the stdlib were introduced), local-first/resumable, human gate (Task 10 `enqueue_stage` structural refusal), content/runtime separation (Task 3).

**Note on effort resolution:** consistent with the spec, `StageModelPlan.effort` is recorded on the `Job` (Task 5 field, Task 10 passes `stage_plan.effort` into `store.create`) but never translated to a CLI flag — reasoning flags live in `ModelOption.extra_args` (Task 3 composition).

**Type consistency:** `Invocation(argv, stdin, env)` and `ProviderResponse(text, metadata)` are defined in Task 2 and used unchanged in Tasks 3/7. `ProviderRunner` methods (`is_available`, `build_invocation`, `parse_response`) match across Tasks 2-3-7. `JobStore` method names (`create/save/load/find/list/all_jobs/active_for/read_log/log_path/job_dir`) are introduced in Task 5 and used identically in Tasks 7-8, 10. `Worker` (`start/stop/enqueue/cancel/reconcile`) is consistent Tasks 8, 10-11. `DaemonContext` fields match between Tasks 10 and 11. `DaemonClient` methods match between Tasks 12 and 13. `daemon_status` keys (`running/pid/port/version/version_mismatch`) match Tasks 12-13.

**Placeholder scan:** no TBD/TODO/"add error handling"/"similar to Task N" left in the plan; every code step contains complete code.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-09-provider-run-daemon.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
