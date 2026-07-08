from pathlib import Path

import pytest

from education_pipeline import RunStore
from education_pipeline.cli import main


TOPIC_TOML = """\
schema_version = 1
id = "systems-thinking"
title = "Systems Thinking"
brief = "A public introduction to feedback loops."
goals = ["explain feedback loops"]
"""


PROFILE_TOML = """\
schema_version = 1
id = "visual-profile"
target_learner = "team cohort"
professional_experience = "early-career analysts"
learning_goals = ["understand systems thinking"]

[privacy]
private_by_default = true
include_in_published_output = false
publishable_summary = "Early-career team learning systems thinking."
"""


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def _run(ws: Path, *args: str) -> int:
    return main(["--workspace", str(ws), *args])


def test_topic_import_and_list(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ws = tmp_path / "ws"
    topic_file = _write(tmp_path / "topic.toml", TOPIC_TOML)

    assert _run(ws, "topic", "import", str(topic_file)) == 0
    assert "systems-thinking" in capsys.readouterr().out

    assert _run(ws, "topic", "list") == 0
    assert "systems-thinking" in capsys.readouterr().out


def test_status_reports_next_action(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ws = tmp_path / "ws"
    _run(ws, "topic", "import", str(_write(tmp_path / "topic.toml", TOPIC_TOML)))
    capsys.readouterr()

    assert _run(ws, "status", "systems-thinking") == 0
    out = capsys.readouterr().out
    assert "spec" in out
    assert "write_prompt" in out


def test_advance_writes_prompt(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ws = tmp_path / "ws"
    _run(ws, "topic", "import", str(_write(tmp_path / "topic.toml", TOPIC_TOML)))
    capsys.readouterr()

    assert _run(ws, "advance", "systems-thinking") == 0
    assert "write_prompt" in capsys.readouterr().out
    assert (ws / "runs" / "systems-thinking" / "prompts" / "spec.prompt.md").exists()


def test_full_flow_drives_run_to_export(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    _run(ws, "topic", "import", str(_write(tmp_path / "topic.toml", TOPIC_TOML)))
    runs = RunStore(ws)

    for _ in range(50):
        assert _run(ws, "advance", "systems-thinking") == 0
        action = runs.run_status("systems-thinking").next_action
        if action.action == "done":
            break
        if action.action == "save_response":
            runs.stage_paths("systems-thinking", action.stage).response_path.write_text(
                f"# {action.stage}\n", encoding="utf-8"
            )
        elif action.action == "approve":
            assert _run(ws, "approve", "systems-thinking", action.stage) == 0
    else:  # pragma: no cover
        raise AssertionError("CLI advance did not reach done")

    assert runs.is_finalized("systems-thinking")
    assert _run(ws, "export", "systems-thinking", "--format", "html") == 0
    assert _run(ws, "export", "systems-thinking", "--format", "markdown") == 0
    assert (ws / "runs" / "systems-thinking" / "final" / "guide.html").exists()
    assert (ws / "runs" / "systems-thinking" / "final" / "guide.bundle.md").exists()


def test_export_before_finalize_errors(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ws = tmp_path / "ws"
    _run(ws, "topic", "import", str(_write(tmp_path / "topic.toml", TOPIC_TOML)))
    capsys.readouterr()

    assert _run(ws, "export", "systems-thinking") == 1
    assert "not finalized" in capsys.readouterr().err


def test_unknown_topic_errors(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert _run(tmp_path / "ws", "advance", "missing-topic") == 1
    assert "error:" in capsys.readouterr().err


def test_profile_attach_threads_into_spec_prompt(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    _run(ws, "profile", "import", str(_write(tmp_path / "profile.toml", PROFILE_TOML)))
    _run(ws, "topic", "import", str(_write(tmp_path / "topic.toml", TOPIC_TOML)))
    assert _run(ws, "profile", "attach", "visual-profile", "systems-thinking") == 0

    assert _run(ws, "advance", "systems-thinking") == 0
    prompt = (ws / "runs" / "systems-thinking" / "prompts" / "spec.prompt.md").read_text()
    assert "# Learner Profile Context" in prompt
    assert "- Professional experience: early-career analysts" in prompt
