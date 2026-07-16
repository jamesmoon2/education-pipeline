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
PERSONALIZED_FIXTURE = (
    Path(__file__).parent
    / "fixtures/guides/feedback-loops.personalized.guide.json"
)
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


def test_schema_1_1_canonical_round_trip_preserves_authored_version_and_annotations() -> None:
    source = PERSONALIZED_FIXTURE.read_bytes()
    guide = normalize_guide(parse_guide(source))

    canonical = canonical_guide_bytes(guide)
    decoded = json.loads(canonical)

    assert decoded["schema_version"] == "1.1"
    assert decoded["outcomes"][0]["serves_goals"] == ["goal-001"]
    assert decoded["modules"][0]["serves_goals"] == ["goal-001", "goal-002"]
    assert decoded["course"]["goal_exclusions"] == [
        {"goal_id": "goal-003", "reason": "Synthetic deferred objective."}
    ]
    assert canonical == canonical_guide_bytes(normalize_guide(parse_guide(canonical)))


def _fixture_data() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _base_json() -> str:
    return FIXTURE.read_text(encoding="utf-8")


def _module_json(module: dict) -> str:
    return json.dumps(module, ensure_ascii=False)


def test_splice_module_replaces_only_the_target_module() -> None:
    from education_pipeline.guides.canonical import splice_module

    data = _fixture_data()
    revised = json.loads(json.dumps(data["modules"][0]))
    revised["title"] = "Loop Basics, Regenerated"
    revised["sections"][0]["blocks"][0]["markdown"] = "A fully regenerated opener."

    merged_bytes = splice_module(_base_json(), "loop-basics", _module_json(revised))
    merged = json.loads(merged_bytes)

    # Canonical output that round-trips.
    merged_guide = normalize_guide(parse_guide(merged_bytes))
    assert merged_bytes == canonical_guide_bytes(merged_guide)

    # The target changed; module order is preserved.
    assert [module["id"] for module in merged["modules"]] == [
        module["id"] for module in data["modules"]
    ]
    assert merged["modules"][0]["title"] == "Loop Basics, Regenerated"

    # Modules outside the target are byte-identical (canonical serialization).
    base_canonical = json.loads(canonical_guide_bytes(guide()))
    assert json.dumps(merged["modules"][1], sort_keys=True) == json.dumps(
        base_canonical["modules"][1], sort_keys=True
    )
    # Course metadata, outcomes, glossary, and sources are untouched.
    for key in ("course", "outcomes", "glossary", "sources", "schema_version"):
        assert json.dumps(merged[key], sort_keys=True) == json.dumps(
            base_canonical[key], sort_keys=True
        )


def test_splice_module_rejects_module_id_rename() -> None:
    import pytest

    from education_pipeline.guides.canonical import SpliceError, splice_module

    revised = _fixture_data()["modules"][0]
    revised["id"] = "loop-basics-renamed"

    with pytest.raises(SpliceError, match="rename"):
        splice_module(_base_json(), "loop-basics", _module_json(revised))


def test_splice_module_rejects_unknown_target_module() -> None:
    import pytest

    from education_pipeline.guides.canonical import SpliceError, splice_module

    revised = _fixture_data()["modules"][0]
    revised["id"] = "no-such-module"

    with pytest.raises(SpliceError, match="no-such-module"):
        splice_module(_base_json(), "no-such-module", _module_json(revised))


def test_splice_module_rejects_element_id_collision_with_other_modules() -> None:
    import pytest

    from education_pipeline.guides.canonical import SpliceError, splice_module

    data = _fixture_data()
    revised = data["modules"][0]
    # Steal a block id that lives in the other module.
    other_block_id = data["modules"][1]["sections"][0]["blocks"][0]["id"]
    revised["sections"][0]["blocks"][0]["id"] = other_block_id

    with pytest.raises(SpliceError, match="duplicate"):
        splice_module(_base_json(), "loop-basics", _module_json(revised))


def test_splice_module_rejects_out_of_contract_outcome_reference() -> None:
    import pytest

    from education_pipeline.guides.canonical import SpliceError, splice_module

    revised = _fixture_data()["modules"][0]
    revised["outcome_ids"] = ["identify-loop", "not-a-contract-outcome"]

    with pytest.raises(SpliceError, match="not-a-contract-outcome"):
        splice_module(_base_json(), "loop-basics", _module_json(revised))


def test_splice_module_rejects_non_module_payloads() -> None:
    import pytest

    from education_pipeline.guides.canonical import SpliceError, splice_module

    with pytest.raises(SpliceError, match="not valid JSON"):
        splice_module(_base_json(), "loop-basics", "not json {")

    with pytest.raises(SpliceError, match="single JSON object"):
        splice_module(_base_json(), "loop-basics", json.dumps([1, 2]))

    # A whole guide is not a module.
    with pytest.raises(SpliceError, match="rename|module"):
        splice_module(_base_json(), "loop-basics", _base_json())


def test_empty_personalization_annotations_are_omitted_for_both_versions() -> None:
    for version in ("1.0", "1.1"):
        data = json.loads(FIXTURE.read_text(encoding="utf-8"))
        data["schema_version"] = version
        canonical = canonical_guide_bytes(
            normalize_guide(parse_guide(json.dumps(data, ensure_ascii=False)))
        )

        assert b'"serves_goals"' not in canonical
        assert b'"goal_exclusions"' not in canonical
