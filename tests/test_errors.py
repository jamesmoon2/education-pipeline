"""Tests for the stable error-code catalog (spec §7.1).

Codes are append-only and live in one module. Every code the daemon can emit
must be registered, so the cockpit and CLI can always map a code to a
plain-language explanation and a recovery action.
"""

import re
from pathlib import Path

from education_pipeline.errors import ERROR_CATALOG, remediation_for

REPO = Path(__file__).resolve().parents[1]

SPEC_CODES = {
    "stale_content",
    "not_found",
    "invalid_request",
    "workspace_invalid",
    "workspace_unselected",
    "provider_unavailable",
    "job_conflict",
    "archived_course",
    "validation_blocked",
    "web_assets_missing",
    "reveal_unsupported",
    "internal",
}


def test_catalog_contains_all_spec_codes() -> None:
    assert SPEC_CODES <= set(ERROR_CATALOG)


def test_catalog_contains_daemon_unreachable_for_clients() -> None:
    # Synthesized client-side on fetch failure, but defined centrally so the
    # CLI and cockpit agree on its remediation text.
    assert "daemon_unreachable" in ERROR_CATALOG


def test_catalog_entries_have_summary_and_remediation() -> None:
    for code, entry in ERROR_CATALOG.items():
        assert entry.code == code
        assert entry.summary.strip(), code
        assert entry.remediation.strip(), code


def _emitted_codes(source: Path) -> set[str]:
    text = source.read_text(encoding="utf-8")
    codes = set(re.findall(r"_error\(\s*\d+,\s*\"([a-z0-9_]+)\"", text))
    codes |= set(re.findall(r"(?:ConflictError|UnprocessableError)\(\s*\n?\s*\"([a-z0-9_]+)\"", text))
    return codes


def test_every_code_the_daemon_emits_is_registered() -> None:
    emitted: set[str] = set()
    for module in ("server.py", "write_api.py", "read_api.py"):
        emitted |= _emitted_codes(REPO / "education_pipeline" / "daemon" / module)
    assert emitted, "expected to find emitted error codes in daemon sources"
    unregistered = emitted - set(ERROR_CATALOG)
    assert unregistered == set(), f"unregistered daemon error codes: {sorted(unregistered)}"


def test_retired_codes_are_not_reintroduced() -> None:
    # Renamed during the envelope migration: bad_request -> invalid_request,
    # job_active -> job_conflict, ui_unavailable -> web_assets_missing.
    retired = {"bad_request", "job_active", "ui_unavailable"}
    emitted: set[str] = set()
    for module in ("server.py", "write_api.py", "read_api.py"):
        emitted |= _emitted_codes(REPO / "education_pipeline" / "daemon" / module)
    assert emitted & retired == set()
    assert retired & set(ERROR_CATALOG) == set()


def test_remediation_for_unknown_code_is_none() -> None:
    assert remediation_for("no_such_code") is None
    assert remediation_for("internal") is not None
