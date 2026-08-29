"""Tests for the user-level workspace registry (consulted only by `ui`)."""

import json
import os
from pathlib import Path

import pytest

from education_pipeline.registry import (
    last_used_workspace,
    load_registry,
    record_workspace,
    registry_path,
)


@pytest.fixture(autouse=True)
def _isolated_config_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config-home"))


def test_registry_path_honors_xdg_config_home(tmp_path: Path) -> None:
    assert registry_path() == (
        tmp_path / "config-home" / "education-pipeline" / "workspaces.json"
    )


def test_registry_path_defaults_to_home_dot_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    assert registry_path() == (
        Path.home() / ".config" / "education-pipeline" / "workspaces.json"
    )


def test_load_registry_missing_file_is_empty(capsys: pytest.CaptureFixture[str]) -> None:
    registry = load_registry()
    assert registry.workspaces == ()
    assert registry.last_used is None
    assert capsys.readouterr().err == ""  # a missing file is normal, no warning


def test_record_workspace_round_trip(tmp_path: Path) -> None:
    ws = tmp_path / "ws-one"
    record_workspace(ws)
    registry = load_registry()
    expected = str(ws.resolve())
    assert registry.workspaces == (expected,)
    assert registry.last_used == expected
    assert last_used_workspace() == Path(expected)

    on_disk = json.loads(registry_path().read_text(encoding="utf-8"))
    assert on_disk == {"workspaces": [expected], "last_used": expected}


def test_record_workspace_appends_and_updates_last_used(tmp_path: Path) -> None:
    first, second = tmp_path / "a", tmp_path / "b"
    record_workspace(first)
    record_workspace(second)
    registry = load_registry()
    assert registry.workspaces == (str(first.resolve()), str(second.resolve()))
    assert registry.last_used == str(second.resolve())


def test_record_workspace_deduplicates_existing_entry(tmp_path: Path) -> None:
    first, second = tmp_path / "a", tmp_path / "b"
    record_workspace(first)
    record_workspace(second)
    record_workspace(first)  # re-recording must not duplicate
    registry = load_registry()
    assert registry.workspaces == (str(first.resolve()), str(second.resolve()))
    assert registry.last_used == str(first.resolve())


def test_record_workspace_stores_absolute_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    record_workspace(Path("relative-ws"))
    registry = load_registry()
    assert registry.workspaces == (str((tmp_path / "relative-ws").resolve()),)


def test_corrupt_registry_reads_as_empty_with_warning(
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = registry_path()
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")
    registry = load_registry()
    assert registry.workspaces == ()
    assert registry.last_used is None
    assert "workspace registry" in capsys.readouterr().err


@pytest.mark.parametrize(
    "payload",
    [
        "[]",  # root must be an object
        '{"workspaces": "nope", "last_used": null}',  # workspaces not a list
        '{"workspaces": [42], "last_used": null}',  # entries must be strings
        '{"workspaces": [], "last_used": 42}',  # last_used must be a string
    ],
)
def test_malformed_registry_shapes_read_as_empty_with_warning(
    payload: str, capsys: pytest.CaptureFixture[str]
) -> None:
    path = registry_path()
    path.parent.mkdir(parents=True)
    path.write_text(payload, encoding="utf-8")
    registry = load_registry()
    assert registry.workspaces == ()
    assert registry.last_used is None
    assert "workspace registry" in capsys.readouterr().err


def test_corrupt_registry_is_recoverable_by_recording(tmp_path: Path) -> None:
    path = registry_path()
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")
    record_workspace(tmp_path / "ws")
    assert load_registry().workspaces == (str((tmp_path / "ws").resolve()),)


def test_record_workspace_leaves_no_temp_files(tmp_path: Path) -> None:
    record_workspace(tmp_path / "ws")
    record_workspace(tmp_path / "ws2")
    leftovers = [
        p.name for p in registry_path().parent.iterdir() if p.name != "workspaces.json"
    ]
    assert leftovers == []


def test_last_used_workspace_none_when_unset() -> None:
    assert last_used_workspace() is None


def test_record_workspace_retries_replace_on_permission_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Windows sharing semantics: os.replace onto a file another process holds
    # open for reading fails with PermissionError. The registry writer shares
    # the package-wide atomic writer, so it polls through it like every other
    # writer instead of losing the recorded workspace.
    from education_pipeline import atomic_io

    real_replace = os.replace
    calls = {"count": 0}

    def flaky_replace(source, target):
        calls["count"] += 1
        if calls["count"] == 1:
            raise PermissionError("sharing violation")
        return real_replace(source, target)

    monkeypatch.setattr(atomic_io.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(os, "replace", flaky_replace)

    record_workspace(tmp_path / "ws")

    assert calls["count"] == 2
    assert load_registry().workspaces == (str((tmp_path / "ws").resolve()),)
    leftovers = [
        p.name for p in registry_path().parent.iterdir() if p.name != "workspaces.json"
    ]
    assert leftovers == []
