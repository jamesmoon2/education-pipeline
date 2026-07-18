"""Tests for the `education-pipeline ui` launcher orchestration (spec §2).

Every collaborator (daemon ensurer, discovery reader, browser opener, TTY
prompt, web-dist lookup) is injected through ``UiDeps`` so the whole
orchestration runs under pytest with fakes -- no sockets, subprocesses, or
real browser.
"""

from pathlib import Path

import pytest

from education_pipeline import ui as ui_module
from education_pipeline.registry import load_registry, record_workspace
from education_pipeline.ui import UiDeps, run_ui


@pytest.fixture(autouse=True)
def _isolated_config_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config-home"))


class FakeClient:
    def health(self):
        return {"version": "test", "ok": True}


def make_deps(tmp_path: Path, **overrides) -> tuple[UiDeps, dict]:
    calls: dict = {"ensure": [], "opened": [], "prompts": []}
    web_dist = tmp_path / "web-dist"
    web_dist.mkdir(exist_ok=True)
    (web_dist / "index.html").write_text("<!doctype html>", encoding="utf-8")

    def ensure_daemon(root, *, autostart=True):
        calls["ensure"].append((Path(root), autostart))
        return FakeClient()

    def read_discovery(root):
        return {"pid": 4242, "port": 45_678, "token": "tok", "version": "test"}

    def open_browser(url):
        calls["opened"].append(url)
        return True

    defaults = dict(
        ensure_daemon=ensure_daemon,
        read_discovery=read_discovery,
        web_dist=lambda: web_dist,
        open_browser=open_browser,
        is_interactive=lambda: False,
        prompt=lambda text: (_ for _ in ()).throw(AssertionError("prompt not expected")),
        home=lambda: tmp_path / "home",
    )
    defaults.update(overrides)
    return UiDeps(**defaults), calls


def test_explicit_workspace_scaffolds_and_launches(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    deps, calls = make_deps(tmp_path)
    ws = tmp_path / "fresh-ws"
    code = run_ui(str(ws), no_browser=False, deps=deps)
    out = capsys.readouterr().out

    assert code == 0
    for subdir in ("runs", "topics", "profiles"):
        assert (ws / subdir).is_dir()
    assert calls["ensure"] == [(ws.resolve(), True)]
    assert "http://127.0.0.1:45678/" in out
    assert calls["opened"] == ["http://127.0.0.1:45678/"]


def test_ui_records_workspace_in_registry(tmp_path: Path) -> None:
    deps, _ = make_deps(tmp_path)
    ws = tmp_path / "fresh-ws"
    assert run_ui(str(ws), deps=deps) == 0
    registry = load_registry()
    assert registry.last_used == str(ws.resolve())
    assert str(ws.resolve()) in registry.workspaces


def test_no_browser_still_prints_url(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    deps, calls = make_deps(tmp_path)
    code = run_ui(str(tmp_path / "ws"), no_browser=True, deps=deps)
    out = capsys.readouterr().out
    assert code == 0
    assert "http://127.0.0.1:45678/" in out
    assert calls["opened"] == []


def test_registry_last_used_supplies_workspace(tmp_path: Path) -> None:
    ws = tmp_path / "known-ws"
    for subdir in ("runs", "topics", "profiles"):
        (ws / subdir).mkdir(parents=True)
    record_workspace(ws)
    deps, calls = make_deps(tmp_path)
    assert run_ui(None, deps=deps) == 0
    assert calls["ensure"] == [(ws.resolve(), True)]


def test_non_interactive_without_workspace_exits_unselected(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    deps, calls = make_deps(tmp_path)
    code = run_ui(None, deps=deps)
    err = capsys.readouterr().err
    assert code == 2
    assert "workspace_unselected" in err
    assert "--workspace" in err
    assert calls["ensure"] == []


def test_first_run_prompt_default_creates_home_workspace(tmp_path: Path) -> None:
    deps, calls = make_deps(
        tmp_path,
        is_interactive=lambda: True,
        prompt=lambda text: "",  # accept the default
    )
    assert run_ui(None, deps=deps) == 0
    created = tmp_path / "home" / "EducationPipeline"
    for subdir in ("runs", "topics", "profiles"):
        assert (created / subdir).is_dir()
    assert calls["ensure"] == [(created.resolve(), True)]
    assert load_registry().last_used == str(created.resolve())


def test_first_run_prompt_accepts_entered_path(tmp_path: Path) -> None:
    chosen = tmp_path / "chosen-ws"
    deps, calls = make_deps(
        tmp_path,
        is_interactive=lambda: True,
        prompt=lambda text: str(chosen),
    )
    assert run_ui(None, deps=deps) == 0
    assert calls["ensure"] == [(chosen.resolve(), True)]


def test_blocking_findings_stop_launch(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ws = tmp_path / "cluttered"
    (ws / "photos").mkdir(parents=True)
    deps, calls = make_deps(tmp_path)
    code = run_ui(str(ws), deps=deps)
    err = capsys.readouterr().err
    assert code == 1
    assert "workspace_invalid" in err
    assert "unrecognized_layout" in err
    assert calls["ensure"] == []
    assert not (ws / "runs").exists()


def test_missing_web_dist_fails_before_daemon_start(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    deps, calls = make_deps(tmp_path, web_dist=lambda: None)
    code = run_ui(str(tmp_path / "ws"), deps=deps)
    err = capsys.readouterr().err
    assert code == 1
    assert "web_assets_missing" in err
    assert "npm run build" in err
    assert calls["ensure"] == []


def test_ui_is_idempotent_for_a_live_daemon(tmp_path: Path) -> None:
    deps, calls = make_deps(tmp_path)
    ws = tmp_path / "ws"
    assert run_ui(str(ws), deps=deps) == 0
    assert run_ui(str(ws), deps=deps) == 0
    # ensure_daemon owns reuse-vs-start; ui just calls it each time.
    assert calls["ensure"] == [(ws.resolve(), True)] * 2
    assert len(calls["opened"]) == 2


def test_stale_build_warns_but_launches(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    deps, calls = make_deps(
        tmp_path,
        build_report=lambda dist: {"status": "stale", "build_id": "1000"},
    )
    assert run_ui(str(tmp_path / "ws"), deps=deps) == 0
    err = capsys.readouterr().err
    assert "warning [cockpit_build_stale]" in err
    assert "npm run build" in err
    assert "--rebuild" in err
    assert calls["opened"]  # launch was not blocked


def test_fresh_build_prints_no_warning(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    deps, calls = make_deps(tmp_path)
    assert run_ui(str(tmp_path / "ws"), deps=deps) == 0
    assert "cockpit_build_stale" not in capsys.readouterr().err


def test_rebuild_runs_npm_then_launches(tmp_path):
    web_dir = tmp_path / "web"
    web_dir.mkdir()
    built = []
    deps, calls = make_deps(
        tmp_path,
        repo_web_dir=lambda: web_dir,
        npm_build=lambda d: built.append(d) or 0,
    )
    assert run_ui(str(tmp_path / "ws"), rebuild=True, deps=deps) == 0
    assert built == [web_dir]
    assert calls["opened"]


def test_rebuild_outside_checkout_errors(tmp_path, capsys):
    deps, calls = make_deps(tmp_path, repo_web_dir=lambda: None)
    assert run_ui(str(tmp_path / "ws"), rebuild=True, deps=deps) == 1
    assert "cockpit_rebuild_unavailable" in capsys.readouterr().err
    assert not calls["ensure"]  # no daemon was started


def test_rebuild_without_npm_errors(tmp_path, capsys):
    deps, calls = make_deps(
        tmp_path,
        repo_web_dir=lambda: tmp_path / "web",
        npm_build=lambda d: None,
    )
    assert run_ui(str(tmp_path / "ws"), rebuild=True, deps=deps) == 1
    assert "npm_missing" in capsys.readouterr().err


def test_rebuild_failure_stops_launch(tmp_path, capsys):
    deps, calls = make_deps(
        tmp_path,
        repo_web_dir=lambda: tmp_path / "web",
        npm_build=lambda d: 2,
    )
    assert run_ui(str(tmp_path / "ws"), rebuild=True, deps=deps) == 1
    assert "cockpit_build_failed" in capsys.readouterr().err
    assert not calls["ensure"]


def test_default_npm_build_returns_none_when_npm_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(ui_module.shutil, "which", lambda name: None)
    assert ui_module._default_npm_build(tmp_path) is None


def test_default_npm_build_returns_nonzero_on_spawn_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(ui_module.shutil, "which", lambda name: "/usr/bin/npm")

    def _raise(*args, **kwargs):
        raise OSError("boom")

    monkeypatch.setattr(ui_module.subprocess, "call", _raise)
    code = ui_module._default_npm_build(tmp_path)
    assert isinstance(code, int)
    assert code != 0
