from pathlib import Path

import pytest

from education_pipeline.daemon.static import default_web_dist, resolve_static


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
