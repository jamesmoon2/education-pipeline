#!/usr/bin/env python3
"""Build the cockpit and copy it into the package for wheel bundling.

Runs ``npm run build`` in ``web/`` and then deterministically replaces
``education_pipeline/_webdist/`` with a clean copy of ``web/dist/`` (spec
§2.1). ``_webdist/`` is gitignored package data: it exists only in built
wheels and locally after running this script.

Usage:
    python scripts/build_webdist.py [--skip-npm-build]
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = REPO_ROOT / "web"
DIST = WEB_DIR / "dist"
WEBDIST = REPO_ROOT / "education_pipeline" / "_webdist"


def copy_dist(source: Path, destination: Path) -> int:
    """Replace ``destination`` with a clean copy of ``source``.

    Returns the number of files copied. Refuses a missing or index-less
    source so a broken build can never silently produce an empty bundle.
    """

    if not (source / "index.html").is_file():
        raise SystemExit(f"error: {source} has no index.html; build the cockpit first")
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination)
    return sum(1 for path in destination.rglob("*") if path.is_file())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--skip-npm-build",
        action="store_true",
        help="reuse the existing web/dist instead of rebuilding",
    )
    args = parser.parse_args(argv)

    if not args.skip_npm_build:
        subprocess.run(["npm", "run", "build"], cwd=WEB_DIR, check=True)
    copied = copy_dist(DIST, WEBDIST)
    print(f"copied {copied} files: {DIST} -> {WEBDIST}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
