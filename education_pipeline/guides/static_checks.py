"""Deterministic static checks computed from the assembled export document.

Stdlib only. These checks make ``ValidationContext`` real: instead of callers
asserting the runtime invariants, the invariants are derived from the exact
HTML string export will ship.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from html.parser import HTMLParser

from ..guide_runtime import RUNTIME_VERSION, RuntimeAssets, load_runtime_assets
from .document import GuideDocumentError, assemble_guide_document
from .model import Guide
from .projection import public_guide_projection
from .validation import ValidationContext

_STRUCTURAL_MARKERS = ("data-guide-shell", 'id="guide-data"', "skip-link")
_LABELABLE = {"select", "input", "textarea"}
_HEADINGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}


@dataclass(frozen=True)
class StaticCheckResult:
    context: ValidationContext
    document: str | None


@dataclass(frozen=True)
class _DocumentFacts:
    controls_have_labels: bool
    heading_order_valid: bool


class _Analyzer(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.controls_ok = True
        self.heading_ok = True
        self._previous_heading = 0
        # {"has_text": bool, "wraps_unnamed": bool} per open <label>
        self._open_labels: list[dict[str, bool]] = []
        self._open_buttons: list[dict[str, bool]] = []  # {"named": bool}

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "label":
            self._open_labels.append({"has_text": False, "wraps_unnamed": False})
        if tag in _HEADINGS:
            level = _HEADINGS[tag]
            # Skip detection is relative to the *previous* heading, not the
            # deepest seen so far: after h1,h2,h3, a later h2 -> h4 skips h3
            # even though an h3 appeared earlier in the document. A document
            # whose first heading is deeper than h1 has skipped the levels
            # above it. Going shallower is never a skip.
            allowed = self._previous_heading + 1 if self._previous_heading else 1
            if level > allowed:
                self.heading_ok = False
            self._previous_heading = level
        if tag == "button":
            self._open_buttons.append({"named": bool((attributes.get("aria-label") or "").strip())})
        if tag in _LABELABLE:
            named = bool((attributes.get("aria-label") or "").strip()) or bool(
                (attributes.get("aria-labelledby") or "").strip()
            )
            if not named:
                if self._open_labels:
                    # Defer the verdict to </label>: text anywhere inside the
                    # label (before or after the control) names it.
                    self._open_labels[-1]["wraps_unnamed"] = True
                else:
                    self.controls_ok = False

    def handle_data(self, data):
        if data.strip():
            for label in self._open_labels:
                label["has_text"] = True
            if self._open_buttons:
                self._open_buttons[-1]["named"] = True

    def handle_endtag(self, tag):
        if tag == "label" and self._open_labels:
            label = self._open_labels.pop()
            if label["wraps_unnamed"] and not label["has_text"]:
                self.controls_ok = False
        if tag == "button" and self._open_buttons:
            if not self._open_buttons.pop()["named"]:
                self.controls_ok = False


def _analyze_document(document: str) -> _DocumentFacts:
    analyzer = _Analyzer()
    analyzer.feed(document)
    analyzer.close()
    return _DocumentFacts(analyzer.controls_ok, analyzer.heading_ok)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def compute_static_checks(guide: Guide, assets: RuntimeAssets | None = None) -> StaticCheckResult:
    packaged = load_runtime_assets()
    if assets is None:
        assets = packaged
    assets_match = (
        assets.version == RUNTIME_VERSION
        and _sha(assets.css) == _sha(packaged.css)
        and _sha(assets.javascript) == _sha(packaged.javascript)
    )
    projected = public_guide_projection(guide)
    try:
        document = assemble_guide_document(projected, assets=assets, mode="export")
    except GuideDocumentError:
        # assets_match is input-derived, so it stays computed even when
        # assembly fails; the document-derived checks (controls, headings)
        # default to True because they are unknowable without a document —
        # the render failure itself is the finding.
        return StaticCheckResult(
            ValidationContext(render_succeeded=False, assets_match=assets_match), None
        )
    render_succeeded = all(marker in document for marker in _STRUCTURAL_MARKERS)
    facts = _analyze_document(document)
    return StaticCheckResult(
        ValidationContext(
            render_succeeded=render_succeeded,
            assets_match=assets_match,
            controls_have_labels=facts.controls_have_labels,
            heading_order_valid=facts.heading_order_valid,
        ),
        document,
    )
