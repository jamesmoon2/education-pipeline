"""Static-asset resolution for the built cockpit SPA.

Pure path logic so it is unit-testable without HTTP: a request path either
maps to a real file under ``dist`` (with content type and cache policy) or to
``None`` (HTTP 404). Anything resolving outside ``dist`` — ``..`` segments,
percent-encoded dots, symlinks pointing out — is rejected.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote

_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json",
    ".map": "application/json",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".txt": "text/plain; charset=utf-8",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
}

#: Vite emits content-hashed filenames under assets/, so they never change.
_IMMUTABLE_CACHE = "public, max-age=31536000, immutable"
_NO_CACHE = "no-store"


@dataclass(frozen=True)
class StaticFile:
    path: Path
    content_type: str
    cache_control: str


#: Built assets copied into the wheel by scripts/build_webdist.py (spec §2.1).
_PACKAGED_WEB_DIST = Path(__file__).resolve().parents[1] / "_webdist"
#: Dev-checkout fallback: the Vite build output in the repo.
_REPO_WEB_DIST = Path(__file__).resolve().parents[2] / "web" / "dist"


def default_web_dist() -> Path | None:
    """Locate the built SPA (spec §2.1 lookup order).

    ``$EP_WEB_DIST`` override → packaged ``education_pipeline/_webdist/`` →
    repo-relative ``web/dist/`` (dev checkout) → ``None``. A directory only
    counts once it holds an ``index.html``, so a half-copied dist is ignored.
    """

    env = os.environ.get("EP_WEB_DIST")
    if env:
        return Path(env)
    for candidate in (_PACKAGED_WEB_DIST, _REPO_WEB_DIST):
        if (candidate / "index.html").is_file():
            return candidate
    return None


def _newest_input_mtime_ns(web_dir: Path) -> int | None:
    """Newest mtime across the cockpit's build inputs (spec §1)."""

    candidates: list[Path] = [
        web_dir / "index.html",
        web_dir / "package.json",
        web_dir / "package-lock.json",
    ]
    candidates.extend(web_dir.glob("tsconfig*.json"))
    candidates.extend(web_dir.glob("vite.config.*"))
    src = web_dir / "src"
    if src.is_dir():
        candidates.extend(p for p in src.rglob("*") if p.is_file())
    newest: int | None = None
    for path in candidates:
        try:
            mtime = path.stat().st_mtime_ns
        except OSError:
            continue
        if newest is None or mtime > newest:
            newest = mtime
    return newest


def cockpit_build_status(web_dir: Path) -> str:
    """``ok``/``stale``/``missing`` for a dev checkout's built cockpit.

    ``stale`` means some build input under ``web_dir`` is newer than
    ``web_dir/dist/index.html``. mtime (not a git SHA) so it needs no git
    and catches uncommitted edits; the outcome is only ever a warning, so
    a rare false positive is harmless.
    """

    try:
        built_ns = (web_dir / "dist" / "index.html").stat().st_mtime_ns
    except OSError:
        return "missing"
    newest = _newest_input_mtime_ns(web_dir)
    if newest is not None and newest > built_ns:
        return "stale"
    return "ok"


def repo_web_dir() -> Path | None:
    """The repo ``web/`` dir when running from a dev checkout, else None.

    A wheel install has no ``web/src`` next to the package, so this is the
    scope guard that keeps every freshness surface silent for wheels.
    """

    web_dir = _REPO_WEB_DIST.parent
    return web_dir if (web_dir / "src").is_dir() else None


def cockpit_build_report(dist: Path | None) -> dict:
    """Freshness payload for ``dist``: ``{"status", "build_id"}``.

    Anything other than the dev-checkout fallback — packaged ``_webdist``,
    an ``$EP_WEB_DIST`` override, or no dist at all — reports ``ok`` so
    wheel users never see a warning. ``build_id`` identifies the current
    build (dist index.html mtime) so the cockpit can key banner dismissal
    to it.
    """

    if os.environ.get("EP_WEB_DIST"):
        return {"status": "ok", "build_id": None}
    web_dir = repo_web_dir()
    if web_dir is None or dist is None or Path(dist) != _REPO_WEB_DIST:
        return {"status": "ok", "build_id": None}
    status = cockpit_build_status(web_dir)
    try:
        build_id = str((web_dir / "dist" / "index.html").stat().st_mtime_ns)
    except OSError:
        build_id = None
    return {"status": status, "build_id": build_id}


def resolve_static(dist: Path, url_path: str) -> StaticFile | None:
    relative = unquote(url_path.split("?", 1)[0].split("#", 1)[0]).lstrip("/")
    if relative == "":
        relative = "index.html"
    dist = dist.resolve()
    candidate = (dist / relative).resolve()
    if candidate != dist and dist not in candidate.parents:
        return None
    if not candidate.is_file():
        final_segment = relative.rsplit("/", 1)[-1]
        if "." in final_segment:
            return None  # looks like a real asset request; don't mask a 404
        candidate = dist / "index.html"
        if not candidate.is_file():
            return None
        relative = "index.html"
    content_type = _CONTENT_TYPES.get(
        candidate.suffix.lower(), "application/octet-stream"
    )
    cache = _IMMUTABLE_CACHE if relative.startswith("assets/") else _NO_CACHE
    return StaticFile(path=candidate, content_type=content_type, cache_control=cache)
