"""The troubleshooting doc must stay in sync with the error-code catalog.

``education_pipeline/errors.py`` is append-only, so the user-facing
reference in ``docs/troubleshooting.md`` only ever needs new rows; this
test fails when a code is added without documenting it.
"""

from pathlib import Path

from education_pipeline.errors import ERROR_CATALOG

DOC = Path("docs/troubleshooting.md")


def test_every_catalog_code_is_documented() -> None:
    text = DOC.read_text(encoding="utf-8")
    missing = [code for code in ERROR_CATALOG if f"`{code}`" not in text]
    assert not missing, f"error codes missing from {DOC}: {missing}"


def test_documented_remediations_match_the_catalog() -> None:
    """Each code's recovery action in the doc is the catalog's text, so the
    doc, CLI, and cockpit always give the same advice."""

    text = DOC.read_text(encoding="utf-8")
    stale = [
        entry.code
        for entry in ERROR_CATALOG.values()
        if entry.remediation not in text
    ]
    assert not stale, f"remediation text out of sync for: {stale}"
