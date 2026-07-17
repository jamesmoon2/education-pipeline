"""Dev-tooling guarantees the suite itself depends on."""


def test_pytest_timeout_is_active_with_a_global_timeout(pytestconfig):
    """A lock-nesting regression must fail a test, not hang the run.

    The manifest-lock contract deadlocks by design (see runs.py). Without a
    timeout that surfaces as a CI hang with no failing test; with one it is a
    crisp per-test failure naming the offending test.
    """

    assert pytestconfig.pluginmanager.hasplugin("timeout")
    assert pytestconfig.getoption("timeout") == 60


# ---------------------------------------------------------------------------
# Cockpit asset bundling (first-run milestone, spec §2.1)


def test_copy_dist_replaces_destination_cleanly(tmp_path):
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    try:
        from build_webdist import copy_dist
    finally:
        sys.path.pop(0)

    source = tmp_path / "dist"
    (source / "assets").mkdir(parents=True)
    (source / "index.html").write_text("<!doctype html>", encoding="utf-8")
    (source / "assets" / "app.js").write_text("js", encoding="utf-8")

    destination = tmp_path / "webdist"
    destination.mkdir()
    (destination / "stale.txt").write_text("old", encoding="utf-8")

    assert copy_dist(source, destination) == 2
    assert (destination / "index.html").is_file()
    assert (destination / "assets" / "app.js").is_file()
    assert not (destination / "stale.txt").exists()


def test_copy_dist_refuses_source_without_index(tmp_path):
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    try:
        from build_webdist import copy_dist
    finally:
        sys.path.pop(0)

    source = tmp_path / "dist"
    source.mkdir()
    with __import__("pytest").raises(SystemExit):
        copy_dist(source, tmp_path / "webdist")


def test_npm_argv_resolves_the_executable_via_which(monkeypatch):
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    try:
        import build_webdist
    finally:
        sys.path.pop(0)

    # Windows resolves npm to npm.cmd only through PATHEXT, which
    # subprocess.run does not apply; the argv must carry the resolved path.
    monkeypatch.setattr(
        build_webdist.shutil,
        "which",
        lambda name: r"C:\nodejs\npm.cmd" if name == "npm" else None,
    )
    assert build_webdist.npm_argv() == [r"C:\nodejs\npm.cmd", "run", "build"]


def test_npm_argv_fails_clearly_when_npm_is_missing(monkeypatch):
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    try:
        import build_webdist
    finally:
        sys.path.pop(0)

    monkeypatch.setattr(build_webdist.shutil, "which", lambda name: None)
    with __import__("pytest").raises(SystemExit) as excinfo:
        build_webdist.npm_argv()
    assert "npm" in str(excinfo.value)


def test_webdist_is_declared_as_package_data():
    import tomllib
    from pathlib import Path

    pyproject = tomllib.loads(
        (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(
            encoding="utf-8"
        )
    )
    patterns = pyproject["tool"]["setuptools"]["package-data"]["education_pipeline"]
    assert any(pattern.startswith("_webdist") for pattern in patterns)


def test_webdist_is_gitignored():
    from pathlib import Path

    gitignore = (Path(__file__).resolve().parents[1] / ".gitignore").read_text(
        encoding="utf-8"
    )
    assert "education_pipeline/_webdist/" in gitignore
