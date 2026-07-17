"""Tests for the reveal-in-files resolution and opener (spec §5.5).

The enum-target and realpath-containment tests here are non-negotiable: this
is the first daemon surface that spawns an OS process on request, and user
input must never reach the spawned command line.
"""

import os
import sys
from pathlib import Path

import pytest

from conftest import symlink_or_skip

from education_pipeline.config import ConfigError
from education_pipeline.daemon import reveal
from education_pipeline.daemon.read_api import NotFoundError
from education_pipeline.runs import ContentContract, RunStore
from education_pipeline.workspace import TopicStore


def _workspace(tmp_path: Path) -> tuple[RunStore, TopicStore]:
    (tmp_path / "topics").mkdir()
    (tmp_path / "topics" / "t.toml").write_text(
        'schema_version = 1\nid = "t"\ntitle = "Test Topic"\n', encoding="utf-8"
    )
    runs = RunStore(tmp_path)
    runs.create_run("t", content_contract=ContentContract.legacy_markdown())
    return runs, TopicStore(tmp_path)


class TestResolveRevealTarget:
    def test_run_target_resolves_to_run_dir(self, tmp_path: Path) -> None:
        runs, topics = _workspace(tmp_path)
        path = reveal.resolve_reveal_target(runs, topics, "run", "t")
        assert path == runs.run_dir("t").resolve()

    def test_topic_target_resolves_to_topic_file(self, tmp_path: Path) -> None:
        runs, topics = _workspace(tmp_path)
        path = reveal.resolve_reveal_target(runs, topics, "topic", "t")
        assert path == topics.topic_path("t").resolve()

    def test_export_target_requires_an_export(self, tmp_path: Path) -> None:
        runs, topics = _workspace(tmp_path)
        with pytest.raises(NotFoundError):
            reveal.resolve_reveal_target(runs, topics, "export", "t")
        export = runs.export_path("t", "html")
        export.parent.mkdir(parents=True, exist_ok=True)
        export.write_text("<!doctype html>", encoding="utf-8")
        assert reveal.resolve_reveal_target(runs, topics, "export", "t") == export.resolve()

    def test_unknown_target_is_rejected(self, tmp_path: Path) -> None:
        runs, topics = _workspace(tmp_path)
        for target in ("responses", "../topics", "prompt", "", "/etc"):
            with pytest.raises(ConfigError):
                reveal.resolve_reveal_target(runs, topics, target, "t")

    def test_missing_run_is_not_found(self, tmp_path: Path) -> None:
        runs, topics = _workspace(tmp_path)
        with pytest.raises(NotFoundError):
            reveal.resolve_reveal_target(runs, topics, "run", "ghost")

    def test_malicious_topic_id_is_rejected(self, tmp_path: Path) -> None:
        runs, topics = _workspace(tmp_path)
        for topic_id in ("../../etc", "a/b", ".."):
            with pytest.raises(ConfigError):
                reveal.resolve_reveal_target(runs, topics, "run", topic_id)

    def test_symlinked_run_dir_escaping_workspace_is_rejected(
        self, tmp_path: Path
    ) -> None:
        outside = tmp_path / "outside"
        outside.mkdir()
        ws = tmp_path / "ws"
        (ws / "topics").mkdir(parents=True)
        (ws / "topics" / "esc.toml").write_text(
            'schema_version = 1\nid = "esc"\ntitle = "Escape"\n', encoding="utf-8"
        )
        runs = RunStore(ws)
        topics = TopicStore(ws)
        (ws / "runs").mkdir(exist_ok=True)
        symlink_or_skip(ws / "runs" / "esc", outside, target_is_directory=True)
        (outside / "manifest.json").write_text("{}", encoding="utf-8")
        with pytest.raises(ConfigError, match="outside the workspace"):
            reveal.resolve_reveal_target(runs, topics, "run", "esc")

    def test_symlinked_topic_file_escaping_workspace_is_rejected(
        self, tmp_path: Path
    ) -> None:
        secret = tmp_path / "secret.toml"
        secret.write_text('schema_version = 1\nid = "esc"\n', encoding="utf-8")
        ws = tmp_path / "ws"
        (ws / "topics").mkdir(parents=True)
        symlink_or_skip(ws / "topics" / "esc.toml", secret)
        runs = RunStore(ws)
        topics = TopicStore(ws)
        with pytest.raises(ConfigError, match="outside the workspace"):
            reveal.resolve_reveal_target(runs, topics, "topic", "esc")


class TestOpenerArgv:
    def test_macos_reveals_files_and_opens_dirs(self, tmp_path: Path) -> None:
        file_path = tmp_path / "guide.html"
        file_path.write_text("x", encoding="utf-8")
        assert reveal.opener_argv(file_path, platform="darwin", env={}) == [
            "open",
            "-R",
            str(file_path),
        ]
        assert reveal.opener_argv(tmp_path, platform="darwin", env={}) == [
            "open",
            str(tmp_path),
        ]

    def test_linux_opens_the_containing_directory(self, tmp_path: Path) -> None:
        file_path = tmp_path / "guide.html"
        file_path.write_text("x", encoding="utf-8")
        assert reveal.opener_argv(file_path, platform="linux", env={}) == [
            "xdg-open",
            str(tmp_path),
        ]
        assert reveal.opener_argv(tmp_path, platform="linux", env={}) == [
            "xdg-open",
            str(tmp_path),
        ]

    def test_windows_selects_files_in_explorer(self, tmp_path: Path) -> None:
        file_path = tmp_path / "guide.html"
        file_path.write_text("x", encoding="utf-8")
        assert reveal.opener_argv(file_path, platform="win32", env={}) == [
            "explorer",
            f"/select,{file_path}",
        ]
        assert reveal.opener_argv(tmp_path, platform="win32", env={}) == [
            "explorer",
            str(tmp_path),
        ]

    def test_unsupported_platform_raises_reveal_error(self, tmp_path: Path) -> None:
        with pytest.raises(reveal.RevealError):
            reveal.opener_argv(tmp_path, platform="plan9", env={})

    def test_env_override_wins_for_tests(self, tmp_path: Path) -> None:
        argv = reveal.opener_argv(
            tmp_path, platform="linux", env={"EP_REVEAL_OPENER": "/bin/true"}
        )
        assert argv == ["/bin/true", str(tmp_path)]


class TestOpenInFileManager:
    # The opener is invoked as ``$EP_REVEAL_OPENER <path>``, so the Python
    # interpreter doubles as a portable opener: handed a script path it runs
    # it, and its exit status is the script's — no /bin/true|false needed.
    def test_failing_opener_raises_reveal_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        target = tmp_path / "fail.py"
        target.write_text("raise SystemExit(3)\n", encoding="utf-8")
        monkeypatch.setenv("EP_REVEAL_OPENER", sys.executable)
        with pytest.raises(reveal.RevealError):
            reveal.open_in_file_manager(target)

    def test_missing_opener_raises_reveal_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("EP_REVEAL_OPENER", str(tmp_path / "no-such-opener"))
        with pytest.raises(reveal.RevealError):
            reveal.open_in_file_manager(tmp_path)

    def test_successful_opener_returns_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        target = tmp_path / "ok.py"
        target.write_text("", encoding="utf-8")
        monkeypatch.setenv("EP_REVEAL_OPENER", sys.executable)
        assert reveal.open_in_file_manager(target) is None
