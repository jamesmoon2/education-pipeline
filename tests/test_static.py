import os
from pathlib import Path

import pytest

from education_pipeline.daemon import static as static_mod
from education_pipeline.daemon.static import (
    cockpit_build_report,
    cockpit_build_status,
    default_web_dist,
    inject_cockpit_build_warning,
    repo_web_dir,
    resolve_static,
)


@pytest.fixture
def dist(tmp_path):
    d = tmp_path / "dist"
    (d / "assets").mkdir(parents=True)
    (d / "index.html").write_text("<html>app</html>", encoding="utf-8")
    (d / "assets" / "index-abc123.js").write_text("js", encoding="utf-8")
    (d / "assets" / "index-abc123.css").write_text("css", encoding="utf-8")
    return d


def test_root_serves_index(dist):
    sf = resolve_static(dist, "/")
    assert sf.path == dist / "index.html"
    assert sf.content_type == "text/html; charset=utf-8"
    assert sf.cache_control == "no-store"


def test_asset_gets_immutable_cache(dist):
    sf = resolve_static(dist, "/assets/index-abc123.js")
    assert sf.path == dist / "assets" / "index-abc123.js"
    assert sf.content_type == "text/javascript; charset=utf-8"
    assert "immutable" in sf.cache_control


def test_spa_route_falls_back_to_index(dist):
    sf = resolve_static(dist, "/topics/t/stages/draft")
    assert sf.path == dist / "index.html"
    assert sf.cache_control == "no-store"


def test_missing_asset_is_none_not_index(dist):
    assert resolve_static(dist, "/assets/gone.js") is None


def test_traversal_is_rejected(dist, tmp_path):
    (tmp_path / "secret.txt").write_text("s", encoding="utf-8")
    assert resolve_static(dist, "/../secret.txt") is None
    assert resolve_static(dist, "/%2e%2e/secret.txt") is None


def test_symlink_escape_is_rejected(dist, tmp_path):
    from conftest import symlink_or_skip

    outside = tmp_path / "outside.txt"
    outside.write_text("s", encoding="utf-8")
    symlink_or_skip(dist / "link.txt", outside)
    assert resolve_static(dist, "/link.txt") is None


def test_query_string_is_ignored(dist):
    sf = resolve_static(dist, "/assets/index-abc123.css?v=1")
    assert sf.path == dist / "assets" / "index-abc123.css"


def test_default_web_dist_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("EP_WEB_DIST", str(tmp_path))
    assert default_web_dist() == tmp_path


def test_default_web_dist_prefers_packaged_then_repo(tmp_path, monkeypatch):
    """Lookup order (spec §2.1): env override → packaged _webdist → repo web/dist."""

    from education_pipeline.daemon import static

    monkeypatch.delenv("EP_WEB_DIST", raising=False)
    packaged = tmp_path / "packaged"
    repo = tmp_path / "repo-dist"
    for candidate in (packaged, repo):
        candidate.mkdir()
        (candidate / "index.html").write_text("<!doctype html>", encoding="utf-8")
    monkeypatch.setattr(static, "_PACKAGED_WEB_DIST", packaged)
    monkeypatch.setattr(static, "_REPO_WEB_DIST", repo)
    assert static.default_web_dist() == packaged


def test_default_web_dist_prefers_repo_dist_in_source_checkout(tmp_path, monkeypatch):
    """A rebuilt dev cockpit must win over a stale packaged copy."""

    from education_pipeline.daemon import static

    monkeypatch.delenv("EP_WEB_DIST", raising=False)
    packaged = tmp_path / "packaged"
    web = tmp_path / "web"
    repo = web / "dist"
    (web / "src").mkdir(parents=True)
    for candidate in (packaged, repo):
        candidate.mkdir(parents=True, exist_ok=True)
        (candidate / "index.html").write_text("<!doctype html>", encoding="utf-8")
    monkeypatch.setattr(static, "_PACKAGED_WEB_DIST", packaged)
    monkeypatch.setattr(static, "_REPO_WEB_DIST", repo)

    assert static.default_web_dist() == repo


def test_default_web_dist_falls_back_to_repo_dist(tmp_path, monkeypatch):
    from education_pipeline.daemon import static

    monkeypatch.delenv("EP_WEB_DIST", raising=False)
    repo = tmp_path / "repo-dist"
    repo.mkdir()
    (repo / "index.html").write_text("<!doctype html>", encoding="utf-8")
    monkeypatch.setattr(static, "_PACKAGED_WEB_DIST", tmp_path / "absent")
    monkeypatch.setattr(static, "_REPO_WEB_DIST", repo)
    assert static.default_web_dist() == repo


def test_default_web_dist_none_when_no_dist_exists(tmp_path, monkeypatch):
    from education_pipeline.daemon import static

    monkeypatch.delenv("EP_WEB_DIST", raising=False)
    monkeypatch.setattr(static, "_PACKAGED_WEB_DIST", tmp_path / "a")
    monkeypatch.setattr(static, "_REPO_WEB_DIST", tmp_path / "b")
    assert static.default_web_dist() is None


def test_default_web_dist_ignores_dir_without_index(tmp_path, monkeypatch):
    from education_pipeline.daemon import static

    monkeypatch.delenv("EP_WEB_DIST", raising=False)
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setattr(static, "_PACKAGED_WEB_DIST", empty)
    monkeypatch.setattr(static, "_REPO_WEB_DIST", tmp_path / "absent")
    assert static.default_web_dist() is None


def _make_web_dir(tmp_path):
    """A minimal dev checkout web/ dir: src/ input and dist/ output."""
    web = tmp_path / "web"
    (web / "src").mkdir(parents=True)
    (web / "src" / "App.tsx").write_text("export {}", encoding="utf-8")
    (web / "index.html").write_text("<!doctype html>", encoding="utf-8")
    (web / "package.json").write_text("{}", encoding="utf-8")
    (web / "dist").mkdir()
    (web / "dist" / "index.html").write_text("<!doctype html>", encoding="utf-8")
    # Initialize all input files to mtime 0 so tests can set specific mtimes
    _set_mtime(web / "src" / "App.tsx", ns=0)
    _set_mtime(web / "index.html", ns=0)
    _set_mtime(web / "package.json", ns=0)
    _set_mtime(web / "dist" / "index.html", ns=0)
    _set_mtime(web / "src", ns=0)
    return web


def _set_mtime(path, *, ns):
    os.utime(path, ns=(ns, ns))


def test_build_status_ok_when_dist_newer(tmp_path):
    web = _make_web_dir(tmp_path)
    _set_mtime(web / "src" / "App.tsx", ns=1_000)
    _set_mtime(web / "dist" / "index.html", ns=2_000)
    assert cockpit_build_status(web) == "ok"


def test_build_status_stale_when_src_newer(tmp_path):
    web = _make_web_dir(tmp_path)
    _set_mtime(web / "dist" / "index.html", ns=1_000)
    _set_mtime(web / "src" / "App.tsx", ns=2_000)
    assert cockpit_build_status(web) == "stale"


def test_build_status_stale_when_config_input_newer(tmp_path):
    web = _make_web_dir(tmp_path)
    (web / "vite.config.ts").write_text("export default {}", encoding="utf-8")
    _set_mtime(web / "dist" / "index.html", ns=1_000)
    _set_mtime(web / "src" / "App.tsx", ns=500)
    _set_mtime(web / "vite.config.ts", ns=2_000)
    assert cockpit_build_status(web) == "stale"


def test_build_status_stale_when_source_file_was_deleted(tmp_path):
    web = _make_web_dir(tmp_path)
    _set_mtime(web / "dist" / "index.html", ns=1_000)
    (web / "src" / "App.tsx").unlink()
    _set_mtime(web / "src", ns=2_000)

    assert cockpit_build_status(web) == "stale"


def test_build_status_missing_without_dist_index(tmp_path):
    web = _make_web_dir(tmp_path)
    (web / "dist" / "index.html").unlink()
    assert cockpit_build_status(web) == "missing"


def test_repo_web_dir_requires_src(tmp_path, monkeypatch):
    web = _make_web_dir(tmp_path)
    monkeypatch.setattr(static_mod, "_REPO_WEB_DIST", web / "dist")
    assert repo_web_dir() == web
    # Without web/src (a wheel layout) there is no dev checkout.
    monkeypatch.setattr(static_mod, "_REPO_WEB_DIST", tmp_path / "elsewhere" / "dist")
    assert repo_web_dir() is None


def test_build_report_stale_for_dev_checkout(tmp_path, monkeypatch):
    web = _make_web_dir(tmp_path)
    _set_mtime(web / "dist" / "index.html", ns=1_000)
    _set_mtime(web / "src" / "App.tsx", ns=2_000)
    monkeypatch.setattr(static_mod, "_REPO_WEB_DIST", web / "dist")
    monkeypatch.delenv("EP_WEB_DIST", raising=False)
    report = cockpit_build_report(web / "dist")
    assert report["status"] == "stale"
    assert report["build_id"] == "1000"


def test_build_report_silent_for_non_checkout_dist(tmp_path, monkeypatch):
    web = _make_web_dir(tmp_path)
    monkeypatch.setattr(static_mod, "_REPO_WEB_DIST", web / "dist")
    monkeypatch.delenv("EP_WEB_DIST", raising=False)
    # A packaged _webdist (any dist that is not the repo fallback) is silent.
    other = tmp_path / "webdist"
    other.mkdir()
    assert cockpit_build_report(other) == {"status": "ok", "build_id": None}
    assert cockpit_build_report(None) == {"status": "ok", "build_id": None}


def test_build_report_silent_under_env_override(tmp_path, monkeypatch):
    web = _make_web_dir(tmp_path)
    _set_mtime(web / "dist" / "index.html", ns=1_000)
    _set_mtime(web / "src" / "App.tsx", ns=2_000)
    monkeypatch.setattr(static_mod, "_REPO_WEB_DIST", web / "dist")
    monkeypatch.setenv("EP_WEB_DIST", str(web / "dist"))
    assert cockpit_build_report(web / "dist") == {"status": "ok", "build_id": None}


def test_stale_warning_is_injected_without_relying_on_cockpit_javascript():
    html = b"<!doctype html><html><body><div id='root'></div></body></html>"

    rendered = inject_cockpit_build_warning(
        html, {"status": "stale", "build_id": "1234"}
    )

    assert b'id="ep-cockpit-build-banner"' in rendered
    assert b'role="status"' in rendered
    assert b"education-pipeline ui --rebuild" in rendered
    assert b'data-build-id="1234"' in rendered


def test_fresh_or_unidentified_build_does_not_change_cockpit_html():
    html = b"<html><body>cockpit</body></html>"
    assert inject_cockpit_build_warning(
        html, {"status": "ok", "build_id": None}
    ) == html
    assert inject_cockpit_build_warning(
        html, {"status": "stale", "build_id": None}
    ) == html
