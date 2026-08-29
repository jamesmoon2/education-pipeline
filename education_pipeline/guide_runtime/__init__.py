"""Packaged browser runtime assets for Interactive Guide v1."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import resources

RUNTIME_VERSION = "1.0"
SUPPORTED_SCHEMA_VERSIONS = frozenset({"1.0", "1.1"})


@dataclass(frozen=True)
class RuntimeAssets:
    css: str
    javascript: str
    version: str = RUNTIME_VERSION


def load_runtime_assets() -> RuntimeAssets:
    """Load the exact maintained assets included in the installed package."""
    root = resources.files(__package__).joinpath("assets")
    return RuntimeAssets(
        css=root.joinpath("runtime.css").read_text(encoding="utf-8"),
        javascript=root.joinpath("runtime.js").read_text(encoding="utf-8"),
    )


__all__ = [
    "RUNTIME_VERSION",
    "SUPPORTED_SCHEMA_VERSIONS",
    "RuntimeAssets",
    "load_runtime_assets",
]
