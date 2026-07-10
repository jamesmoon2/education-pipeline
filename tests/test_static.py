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
    outside = tmp_path / "outside.txt"
    outside.write_text("s", encoding="utf-8")
    (dist / "link.txt").symlink_to(outside)
    assert resolve_static(dist, "/link.txt") is None


def test_query_string_is_ignored(dist):
    sf = resolve_static(dist, "/assets/index-abc123.css?v=1")
    assert sf.path == dist / "assets" / "index-abc123.css"


def test_default_web_dist_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("EP_WEB_DIST", str(tmp_path))
    assert default_web_dist() == tmp_path
