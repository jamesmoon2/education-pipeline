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
        self._deepest_heading = 0
        self._label_depth = 0
        self._open_buttons: list[dict[str, bool]] = []  # {"named": bool}

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "label":
            self._label_depth += 1
        if tag in _HEADINGS:
            level = _HEADINGS[tag]
            if self._deepest_heading and level > self._deepest_heading + 1:
                self.heading_ok = False
            self._deepest_heading = max(self._deepest_heading, level)
        if tag == "button":
            self._open_buttons.append({"named": bool((attributes.get("aria-label") or "").strip())})
        if tag in _LABELABLE:
            named = bool((attributes.get("aria-label") or "").strip()) or bool(
                (attributes.get("aria-labelledby") or "").strip()
            )
            if not named and self._label_depth == 0:
                self.controls_ok = False

    def handle_data(self, data):
        if data.strip() and self._open_buttons:
            self._open_buttons[-1]["named"] = True

    def handle_endtag(self, tag):
        if tag == "label" and self._label_depth:
            self._label_depth -= 1
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
    assets = assets or load_runtime_assets()
    packaged = load_runtime_assets()
    assets_match = (
        assets.version == RUNTIME_VERSION
        and _sha(assets.css) == _sha(packaged.css)
        and _sha(assets.javascript) == _sha(packaged.javascript)
    )
    try:
        document = assemble_guide_document(guide, assets=assets, mode="export")
    except GuideDocumentError:
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
