"""Public Interactive Guide v1 contract core."""

from .canonical import canonical_guide_bytes, guide_sha256
from .model import Guide
from .parse import (
    GuideParseError,
    ParseDiagnostic,
    ParseResult,
    normalize_guide,
    parse_guide,
)
from .projection import project_guide_markdown

__all__ = [
    "Guide",
    "GuideParseError",
    "ParseDiagnostic",
    "ParseResult",
    "canonical_guide_bytes",
    "guide_sha256",
    "normalize_guide",
    "parse_guide",
    "project_guide_markdown",
]
