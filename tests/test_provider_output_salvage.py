"""Thread T04 -- never lose model output.

Pins three related defects:

(a) The audit stage's job log deliberately suppresses raw provider
    stdout/stderr (private values never appear in logs, per the
    personalization design spec), so before this thread a parse failure on
    that stage left the model's output nowhere on disk. The log suppression
    stays; the salvage file in (b) is what preserves the output, as a raw
    response artifact that remains private in the workspace.

(b) On a parse failure for *any* stage, the raw provider stdout must be
    salvaged to ``<stage>.failed.<timestamp>.txt`` next to the stage's
    response path, and the run status / a write endpoint must let a human
    copy that salvage file into the response path so it can be inspected,
    edited and approved as usual. Nothing auto-approves.

    ASSUMED NAMES (not yet implemented -- stated here for the implementer):
      - ``education_pipeline.daemon.read_api.run_status_payload`` gains a
        ``failed_outputs: list[str]`` key (basenames, may be empty) on each
        stage entry.
      - ``education_pipeline.daemon.write_api.salvage_stage_output(runs,
        jobs, topic_id, stage, file, *, overwrite=False) -> dict`` copies a
        named failed-output file into the stage's response path, refusing
        (``ConflictError("already_exists", ...)``) if a response already
        exists unless ``overwrite=True``, and records a manifest event
        (action ``"response_salvaged"``).
      - This is wired to ``POST /v1/runs/{topic}/stages/{stage}/salvage``
        with body ``{"file": "<name>", "overwrite": <bool>}`` (see
        ``education_pipeline/daemon/server.py`` for the existing
        ``.../stages/{stage}/response`` route this mirrors).

(c) ``CodexRunner.parse_response`` returns stdout unvalidated, unlike
    ``ClaudeCodeRunner.parse_response`` which fails on malformed JSON /
    a missing ``result`` field. Codex must reject empty or whitespace-only
    output the same way (no JSON envelope of its own to validate).
"""

import os
import stat
import sys
import threading
from pathlib import Path

import pytest

from education_pipeline import ConfigError, ContentContract, RunStore, parse_model_catalog, parse_model_plan
from education_pipeline.daemon import read_api, write_api
from education_pipeline.daemon.jobs import JobRunner, JobStore
from education_pipeline.providers import get_runner

# --- (c): Codex adapter must gain Claude's "non-empty text" shape check ----


def test_codex_parse_response_rejects_empty_stdout():
    runner = get_runner("codex")
    with pytest.raises(ConfigError):
        runner.parse_response("")


def test_codex_parse_response_rejects_whitespace_only_stdout():
    runner = get_runner("codex")
    with pytest.raises(ConfigError):
        runner.parse_response("   \n\t  ")


# --- (b)+(c): end-to-end salvage through JobRunner.execute -----------------
#
# These drive the *real* ClaudeCodeRunner / CodexRunner adapters (registered
# under "claude-code" / "codex") through JobRunner.execute(), substituting a
# fake executable on PATH for the real "claude"/"codex" CLI -- no real
# provider CLI is ever spawned. POSIX-only: relies on a shebang line to make
# the fake script directly executable, which Windows argv[0] lookup does not
# support the same way.

_FAKE_CLI_BODY = """#!/usr/bin/env python3
import os, sys
sys.stdin.buffer.read()
sys.stdout.buffer.write(os.environ.get("FAKE_STDOUT", "").encode("utf-8"))
sys.exit(int(os.environ.get("FAKE_EXIT", "0")))
"""


def _install_fake_cli(tmp_path: Path, name: str) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    script = bin_dir / name
    script.write_text(_FAKE_CLI_BODY, encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return bin_dir


def _setup_run(tmp_path: Path, provider: str, stage: str = "draft"):
    ws = tmp_path / "ws"
    runs = RunStore(ws)
    runs.create_run("t", content_contract=ContentContract.legacy_markdown())
    prompt_path = runs.stage_paths("t", stage).prompt_path
    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path.write_text("PROMPT", encoding="utf-8")
    catalog = parse_model_catalog(
        {"providers": [{"id": provider, "models": [{"id": "m", "argv_model": "x"}]}]}
    )
    plan = parse_model_plan({"provider": provider, "stages": {stage: {"model": "m"}}}, catalog)
    store = JobStore(tmp_path / "jobs")
    return runs, catalog, plan, store


def _failed_output_files(runs: RunStore, topic_id: str, stage: str) -> list[Path]:
    paths = runs.stage_paths(topic_id, stage)
    return sorted(paths.response_path.parent.glob(f"{stage}.failed.*.txt"))


@pytest.mark.skipif(sys.platform == "win32", reason="fake CLI relies on a POSIX shebang")
def test_claude_adapter_malformed_json_fails_and_salvages_raw_stdout(tmp_path, monkeypatch):
    bin_dir = _install_fake_cli(tmp_path, "claude")
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    raw = "not json at all, and no 'result' field either"
    monkeypatch.setenv("FAKE_STDOUT", raw)

    runs, catalog, plan, store = _setup_run(tmp_path, "claude-code")
    job = store.create("t", "draft", "claude-code", "m", None)
    done = JobRunner(store, runs, catalog, plan, timeout=30).execute(job, threading.Event())

    assert done.status == "failed"
    assert not runs.has_ingested_response("t", "draft")

    failed_files = _failed_output_files(runs, "t", "draft")
    assert len(failed_files) == 1
    assert failed_files[0].read_text(encoding="utf-8") == raw


@pytest.mark.skipif(sys.platform == "win32", reason="fake CLI relies on a POSIX shebang")
def test_codex_adapter_empty_stdout_fails_and_salvages_raw_stdout(tmp_path, monkeypatch):
    bin_dir = _install_fake_cli(tmp_path, "codex")
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setenv("FAKE_STDOUT", "")

    runs, catalog, plan, store = _setup_run(tmp_path, "codex")
    job = store.create("t", "draft", "codex", "m", None)
    done = JobRunner(store, runs, catalog, plan, timeout=30).execute(job, threading.Event())

    assert done.status == "failed"
    assert not runs.has_ingested_response("t", "draft")

    failed_files = _failed_output_files(runs, "t", "draft")
    assert len(failed_files) == 1
    assert failed_files[0].read_text(encoding="utf-8") == ""


@pytest.mark.skipif(sys.platform == "win32", reason="fake CLI relies on a POSIX shebang")
def test_audit_parse_failure_salvages_raw_output_without_logging_it(tmp_path, monkeypatch):
    """Audit is the stage that most needs salvage and least tolerates logging.

    A failed audit parse still leaves its raw output on disk as
    ``audit.failed.<ts>.txt`` -- a raw audit-response artifact, which
    docs/superpowers/specs/2026-07-12-personalization-design.md allows to hold
    private values inside the workspace. The job log, which the same spec line
    forbids private values from reaching, stays empty.
    """
    bin_dir = _install_fake_cli(tmp_path, "claude")
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    raw = "PLANTED PRIVATE AUDIT NARRATIVE (and not JSON)"
    monkeypatch.setenv("FAKE_STDOUT", raw)

    runs, catalog, plan, store = _setup_run(tmp_path, "claude-code", stage="audit")
    prompt_path = runs.stage_paths("t", "audit").prompt_path
    monkeypatch.setattr(
        RunStore,
        "require_provider_ready_prompt",
        lambda self, topic_id, stage: prompt_path,
    )

    job = store.create("t", "audit", "claude-code", "m", None)
    done = JobRunner(store, runs, catalog, plan, timeout=30).execute(job, threading.Event())

    assert done.status == "failed"
    assert not runs.has_ingested_response("t", "audit")

    failed_files = _failed_output_files(runs, "t", "audit")
    assert len(failed_files) == 1
    assert failed_files[0].read_text(encoding="utf-8") == raw
    assert raw not in store.log_path("t", job.id).read_text(encoding="utf-8")


# --- (b): read_api / write_api salvage surface -----------------------------


def _workspace_with_response_dir(tmp_path, stage="draft"):
    (tmp_path / "topics").mkdir()
    (tmp_path / "topics" / "t.toml").write_text(
        'schema_version = 1\nid = "t"\ntitle = "Test Topic"\n', encoding="utf-8"
    )
    runs = RunStore(tmp_path)
    runs.create_run("t", content_contract=ContentContract.legacy_markdown())
    paths = runs.stage_paths("t", stage)
    paths.response_path.parent.mkdir(parents=True, exist_ok=True)
    return runs, JobStore(tmp_path), paths


def test_run_status_lists_failed_output_files_per_stage(tmp_path):
    runs, _jobs, paths = _workspace_with_response_dir(tmp_path)
    failed = paths.response_path.parent / "draft.failed.20260917T000000Z.txt"
    failed.write_text("raw salvageable text", encoding="utf-8")

    status = read_api.run_status_payload(runs, "t")
    by_stage = {s["stage"]: s for s in status["stages"]}

    assert by_stage["draft"]["failed_outputs"] == ["draft.failed.20260917T000000Z.txt"]
    # a stage with no failed-output file reports an empty list, not absence
    assert by_stage["spec"]["failed_outputs"] == []


def test_salvage_stage_output_copies_failed_file_into_response(tmp_path):
    runs, jobs, paths = _workspace_with_response_dir(tmp_path)
    failed = paths.response_path.parent / "draft.failed.20260917T000000Z.txt"
    failed.write_text("raw salvageable text", encoding="utf-8")

    result = write_api.salvage_stage_output(runs, jobs, "t", "draft", failed.name)

    assert paths.response_path.read_text(encoding="utf-8") == "raw salvageable text"
    assert result["stage"] == "draft"
    assert result["response_path"] == "responses/draft.response.md"
    # a manifest event records the salvage so provenance is auditable
    actions = [e["action"] for e in runs.read_manifest("t")["events"]]
    assert "response_salvaged" in actions


def test_salvage_stage_output_refuses_existing_response_without_overwrite(tmp_path):
    runs, jobs, paths = _workspace_with_response_dir(tmp_path)
    failed = paths.response_path.parent / "draft.failed.20260917T000000Z.txt"
    failed.write_text("raw salvageable text", encoding="utf-8")
    write_api.ingest_response(runs, jobs, "t", "draft", "already here")

    with pytest.raises(write_api.ConflictError) as exc:
        write_api.salvage_stage_output(runs, jobs, "t", "draft", failed.name)
    assert exc.value.code == "already_exists"
    assert paths.response_path.read_text(encoding="utf-8") == "already here"

    write_api.salvage_stage_output(runs, jobs, "t", "draft", failed.name, overwrite=True)
    assert paths.response_path.read_text(encoding="utf-8") == "raw salvageable text"


def test_salvage_stage_output_rejects_unknown_file_name(tmp_path):
    runs, jobs, paths = _workspace_with_response_dir(tmp_path)
    with pytest.raises(ConfigError):
        write_api.salvage_stage_output(runs, jobs, "t", "draft", "does-not-exist.txt")


def test_salvage_stage_output_rejects_path_traversal(tmp_path):
    runs, jobs, paths = _workspace_with_response_dir(tmp_path)
    outside = tmp_path / "secret.txt"
    outside.write_text("not yours", encoding="utf-8")
    with pytest.raises(ConfigError):
        write_api.salvage_stage_output(runs, jobs, "t", "draft", "../../secret.txt")
