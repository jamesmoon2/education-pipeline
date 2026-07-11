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
from .document import (
    DocumentMode,
    GuideDocumentError,
    assemble_guide_document,
    render_guide_markdown,
)
from .reports import Finding, ValidationReport, ValidationSummary, canonical_report_bytes
from .validation import validate_guide
from .waivers import Waiver, WaiverResult, WaiverSet, apply_waivers

__all__ = [
    "Guide",
    "DocumentMode",
    "Finding",
    "GuideDocumentError",
    "GuideParseError",
    "ParseDiagnostic",
    "ParseResult",
    "ValidationReport",
    "ValidationSummary",
    "Waiver",
    "WaiverResult",
    "WaiverSet",
    "apply_waivers",
    "assemble_guide_document",
    "canonical_guide_bytes",
    "canonical_report_bytes",
    "guide_sha256",
    "normalize_guide",
    "parse_guide",
    "project_guide_markdown",
    "render_guide_markdown",
    "validate_guide",
]
