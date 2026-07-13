"""Public Interactive Guide v1 contract core."""

from .canonical import canonical_guide_bytes, guide_sha256
from .contract import (
    ContractError,
    build_guide_contract,
    check_contract_conflict,
    extract_outline_contract,
    extract_spec_contract,
    validate_outline_contract,
    validate_spec_contract,
)
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
from .static_checks import StaticCheckResult, compute_static_checks
from .validation import MAX_GUIDE_SOURCE_BYTES, ValidationContext, validate_guide
from .waivers import Waiver, WaiverResult, WaiverSet, apply_waivers

__all__ = [
    "Guide",
    "ContractError",
    "MAX_GUIDE_SOURCE_BYTES",
    "DocumentMode",
    "Finding",
    "GuideDocumentError",
    "GuideParseError",
    "ParseDiagnostic",
    "ParseResult",
    "StaticCheckResult",
    "ValidationReport",
    "ValidationSummary",
    "ValidationContext",
    "Waiver",
    "WaiverResult",
    "WaiverSet",
    "apply_waivers",
    "assemble_guide_document",
    "build_guide_contract",
    "canonical_guide_bytes",
    "canonical_report_bytes",
    "check_contract_conflict",
    "compute_static_checks",
    "extract_outline_contract",
    "extract_spec_contract",
    "guide_sha256",
    "normalize_guide",
    "parse_guide",
    "project_guide_markdown",
    "render_guide_markdown",
    "validate_guide",
    "validate_outline_contract",
    "validate_spec_contract",
]
