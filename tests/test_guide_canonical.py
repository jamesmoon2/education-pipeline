from __future__ import annotations

import json
from pathlib import Path

from education_pipeline.guides import (
    canonical_guide_bytes,
    guide_sha256,
    normalize_guide,
    parse_guide,
)

FIXTURE = Path(__file__).parent / "fixtures/guides/feedback-loops.guide.json"
EXPECTED_SHA256 = "99fde906c6bb1231c33c4d5d9f1adab011a1f4313c03c574eb7aa27cdbe70b07"


def guide():
    return normalize_guide(parse_guide(FIXTURE.read_text(encoding="utf-8")))


def test_exact_canonical_fixture_bytes_and_hash_are_frozen() -> None:
    canonical = canonical_guide_bytes(guide())

    assert guide_sha256(guide()) == EXPECTED_SHA256
    assert canonical == canonical_guide_bytes(normalize_guide(parse_guide(canonical)))
    assert canonical.endswith(b"\n") and not canonical.endswith(b"\n\n")


def test_non_ascii_is_preserved_and_ascii_escaping_is_not_used() -> None:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    data["course"]["subtitle"] = "Café systems — observe, then act"
    parsed = normalize_guide(parse_guide(json.dumps(data, ensure_ascii=False)))

    canonical = canonical_guide_bytes(parsed)
    assert "Café systems — observe".encode() in canonical
    assert b"\\u00e9" not in canonical


def test_object_keys_sort_recursively_and_arrays_keep_authored_order() -> None:
    canonical = canonical_guide_bytes(guide())
    decoded = json.loads(canonical)

    assert (
        canonical.index(b'"course"')
        < canonical.index(b'"glossary"')
        < canonical.index(b'"modules"')
    )
    assert decoded["outcomes"][0]["id"] == "identify-loop"
    assert decoded["outcomes"][1]["id"] == "map-loop"
    knowledge = next(
        block
        for module in decoded["modules"]
        for section in module["sections"]
        for block in section["blocks"]
        if block["type"] == "knowledge_check"
    )
    assert [choice["id"] for choice in knowledge["choices"]] == [
        "release-reinforcing",
        "release-balancing",
        "release-unrelated",
    ]
