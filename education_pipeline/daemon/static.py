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
