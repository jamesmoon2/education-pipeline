"""Shared cross-platform helpers for the test suite."""

from __future__ import annotations

from pathlib import Path

import pytest


def symlink_or_skip(link: Path, target: Path, **kwargs) -> None:
    """Create ``link`` pointing at ``target``, or skip the calling test.

    Windows allows symlink creation only with Developer Mode or elevated
    rights; where creation fails the test must degrade to a skip, not an
    error.
    """

    try:
        link.symlink_to(target, **kwargs)
    except (OSError, NotImplementedError):
        pytest.skip("cannot create symlinks on this platform")
