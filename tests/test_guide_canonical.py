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


# ---------------------------------------------------------------------------
# T21: validate_frame / assemble_guide (per-module drafting, D2/D3)
# ---------------------------------------------------------------------------
#
# These interfaces do not exist yet; the new names are imported inside each
# test function body (as the splice_module tests above already do), so
# collection of this module keeps succeeding for every existing test while
# these new ones fail on import.


def _frame_data() -> dict:
    """A frame built from the fixture: same stubs, every ``sections`` emptied."""

    data = _fixture_data()
    frame = json.loads(json.dumps(data))
    for module in frame["modules"]:
        module["sections"] = []
    return frame


def _frame_json_text() -> str:
    return json.dumps(_frame_data(), ensure_ascii=False)


def _module_ids() -> list:
    return [module["id"] for module in _fixture_data()["modules"]]


def _modules_map() -> dict:
    return {
        module["id"]: _module_json(module) for module in _fixture_data()["modules"]
    }


def _expected_assembled_bytes() -> bytes:
    return canonical_guide_bytes(normalize_guide(parse_guide(FIXTURE.read_bytes())))


# -- validate_frame -----------------------------------------------------


def test_validate_frame_accepts_valid_frame_and_returns_loaded_dict() -> None:
    from education_pipeline.guides.canonical import validate_frame

    frame_text = _frame_json_text()
    result = validate_frame(frame_text, module_ids=_module_ids())

    assert result == json.loads(frame_text)
    assert [module["id"] for module in result["modules"]] == _module_ids()
    assert all(module["sections"] == [] for module in result["modules"])


def test_validate_frame_accepts_bytes_input() -> None:
    from education_pipeline.guides.canonical import validate_frame

    result = validate_frame(
        _frame_json_text().encode("utf-8"), module_ids=_module_ids()
    )

    assert result["schema_version"] == "1.0"


def test_validate_frame_passes_through_other_keys_untouched() -> None:
    from education_pipeline.guides.canonical import validate_frame

    frame = _frame_data()
    result = validate_frame(
        json.dumps(frame, ensure_ascii=False), module_ids=_module_ids()
    )

    for key in ("course", "outcomes", "glossary", "sources"):
        assert result[key] == frame[key]


def test_validate_frame_rejects_invalid_json() -> None:
    import pytest

    from education_pipeline.guides.canonical import SpliceError, validate_frame

    with pytest.raises(SpliceError):
        validate_frame("not json {", module_ids=_module_ids())


def test_validate_frame_rejects_non_object_root() -> None:
    import pytest

    from education_pipeline.guides.canonical import SpliceError, validate_frame

    with pytest.raises(SpliceError):
        validate_frame(json.dumps([1, 2, 3]), module_ids=_module_ids())


def test_validate_frame_rejects_missing_root_key() -> None:
    import pytest

    from education_pipeline.guides.canonical import SpliceError, validate_frame

    frame = _frame_data()
    del frame["glossary"]

    with pytest.raises(SpliceError):
        validate_frame(json.dumps(frame), module_ids=_module_ids())


def test_validate_frame_rejects_extra_root_key() -> None:
    import pytest

    from education_pipeline.guides.canonical import SpliceError, validate_frame

    frame = _frame_data()
    frame["extra_top_level_key"] = "nope"

    with pytest.raises(SpliceError):
        validate_frame(json.dumps(frame), module_ids=_module_ids())


def test_validate_frame_rejects_modules_not_a_list() -> None:
    import pytest

    from education_pipeline.guides.canonical import SpliceError, validate_frame

    frame = _frame_data()
    frame["modules"] = {module["id"]: module for module in frame["modules"]}

    with pytest.raises(SpliceError):
        validate_frame(json.dumps(frame), module_ids=_module_ids())


def test_validate_frame_rejects_module_stub_not_an_object() -> None:
    import pytest

    from education_pipeline.guides.canonical import SpliceError, validate_frame

    frame = _frame_data()
    frame["modules"][0] = "loop-basics"

    with pytest.raises(SpliceError):
        validate_frame(json.dumps(frame), module_ids=_module_ids())


def test_validate_frame_rejects_missing_stub_id() -> None:
    import pytest

    from education_pipeline.guides.canonical import SpliceError, validate_frame

    frame = _frame_data()
    frame["modules"] = frame["modules"][:1]

    with pytest.raises(SpliceError):
        validate_frame(json.dumps(frame), module_ids=_module_ids())


def test_validate_frame_rejects_extra_stub_id() -> None:
    import pytest

    from education_pipeline.guides.canonical import SpliceError, validate_frame

    frame = _frame_data()
    extra = json.loads(json.dumps(frame["modules"][0]))
    extra["id"] = "extra-module"
    frame["modules"].append(extra)

    with pytest.raises(SpliceError):
        validate_frame(json.dumps(frame), module_ids=_module_ids())


def test_validate_frame_rejects_reordered_stub_ids() -> None:
    import pytest

    from education_pipeline.guides.canonical import SpliceError, validate_frame

    frame = _frame_data()
    frame["modules"] = list(reversed(frame["modules"]))

    with pytest.raises(SpliceError):
        validate_frame(json.dumps(frame), module_ids=_module_ids())


def test_validate_frame_rejects_duplicate_stub_id() -> None:
    import pytest

    from education_pipeline.guides.canonical import SpliceError, validate_frame

    frame = _frame_data()
    frame["modules"][1] = json.loads(json.dumps(frame["modules"][0]))

    with pytest.raises(SpliceError):
        validate_frame(json.dumps(frame), module_ids=_module_ids())


def test_validate_frame_rejects_non_string_stub_id() -> None:
    import pytest

    from education_pipeline.guides.canonical import SpliceError, validate_frame

    frame = _frame_data()
    frame["modules"][0]["id"] = 123

    with pytest.raises(SpliceError):
        validate_frame(json.dumps(frame), module_ids=_module_ids())


def test_validate_frame_rejects_stub_sections_not_empty() -> None:
    import pytest

    from education_pipeline.guides.canonical import SpliceError, validate_frame

    frame = _frame_data()
    frame["modules"][0]["sections"] = [{"id": "s", "title": "S", "blocks": []}]

    with pytest.raises(SpliceError):
        validate_frame(json.dumps(frame), module_ids=_module_ids())


# -- assemble_guide -------------------------------------------------------


def test_assemble_guide_returns_expected_canonical_bytes() -> None:
    from education_pipeline.guides.canonical import assemble_guide

    result = assemble_guide(
        _frame_json_text(), _modules_map(), module_ids=_module_ids()
    )

    assert result == _expected_assembled_bytes()


def test_assemble_guide_is_deterministic() -> None:
    from education_pipeline.guides.canonical import assemble_guide

    frame_json = _frame_json_text()
    modules = _modules_map()
    module_ids = _module_ids()

    first = assemble_guide(frame_json, modules, module_ids=module_ids)
    second = assemble_guide(frame_json, modules, module_ids=module_ids)

    assert first == second == _expected_assembled_bytes()


def test_assemble_guide_accepts_bytes_frame_json() -> None:
    from education_pipeline.guides.canonical import assemble_guide

    result = assemble_guide(
        _frame_json_text().encode("utf-8"), _modules_map(), module_ids=_module_ids()
    )

    assert result == _expected_assembled_bytes()


def test_assemble_guide_propagates_frame_validation_errors() -> None:
    import pytest

    from education_pipeline.guides.canonical import SpliceError, assemble_guide

    frame = _frame_data()
    frame["modules"][0]["sections"] = [{"id": "s", "title": "S", "blocks": []}]

    with pytest.raises(SpliceError):
        assemble_guide(
            json.dumps(frame), _modules_map(), module_ids=_module_ids()
        )


def test_assemble_guide_rejects_missing_module() -> None:
    import pytest

    from education_pipeline.guides.canonical import SpliceError, assemble_guide

    modules = _modules_map()
    del modules["intervention-practice"]

    with pytest.raises(SpliceError, match="intervention-practice"):
        assemble_guide(_frame_json_text(), modules, module_ids=_module_ids())


def test_assemble_guide_rejects_extra_module() -> None:
    import pytest

    from education_pipeline.guides.canonical import SpliceError, assemble_guide

    modules = _modules_map()
    modules["unexpected-module"] = _module_json(_fixture_data()["modules"][0])

    with pytest.raises(SpliceError, match="unexpected-module"):
        assemble_guide(_frame_json_text(), modules, module_ids=_module_ids())


def test_assemble_guide_rejects_module_value_not_json() -> None:
    import pytest

    from education_pipeline.guides.canonical import SpliceError, assemble_guide

    modules = _modules_map()
    modules["loop-basics"] = "not json {"

    with pytest.raises(SpliceError):
        assemble_guide(_frame_json_text(), modules, module_ids=_module_ids())


def test_assemble_guide_rejects_module_value_not_a_single_object() -> None:
    import pytest

    from education_pipeline.guides.canonical import SpliceError, assemble_guide

    modules = _modules_map()
    modules["loop-basics"] = json.dumps([1, 2])

    with pytest.raises(SpliceError):
        assemble_guide(_frame_json_text(), modules, module_ids=_module_ids())


def test_assemble_guide_rejects_module_value_with_modules_key() -> None:
    import pytest

    from education_pipeline.guides.canonical import SpliceError, assemble_guide

    modules = _modules_map()
    # A whole guide document is not a single module object.
    modules["loop-basics"] = _base_json()

    with pytest.raises(SpliceError):
        assemble_guide(_frame_json_text(), modules, module_ids=_module_ids())


def test_assemble_guide_rejects_module_id_mismatch_with_key() -> None:
    import pytest

    from education_pipeline.guides.canonical import SpliceError, assemble_guide

    modules = _modules_map()
    renamed = json.loads(modules["loop-basics"])
    renamed["id"] = "loop-basics-renamed"
    modules["loop-basics"] = json.dumps(renamed)

    with pytest.raises(SpliceError, match="rename"):
        assemble_guide(_frame_json_text(), modules, module_ids=_module_ids())


def test_assemble_guide_rejects_element_id_collision_across_modules() -> None:
    import pytest

    from education_pipeline.guides.canonical import SpliceError, assemble_guide

    modules = _modules_map()
    data = _fixture_data()
    other_block_id = data["modules"][1]["sections"][0]["blocks"][0]["id"]
    revised = json.loads(modules["loop-basics"])
    revised["sections"][0]["blocks"][0]["id"] = other_block_id
    modules["loop-basics"] = json.dumps(revised)

    with pytest.raises(SpliceError, match="duplicate"):
        assemble_guide(_frame_json_text(), modules, module_ids=_module_ids())


def test_assemble_guide_rejects_out_of_contract_outcome_reference() -> None:
    import pytest

    from education_pipeline.guides.canonical import SpliceError, assemble_guide

    modules = _modules_map()
    revised = json.loads(modules["loop-basics"])
    revised["outcome_ids"] = ["identify-loop", "not-a-contract-outcome"]
    modules["loop-basics"] = json.dumps(revised)

    with pytest.raises(SpliceError, match="not-a-contract-outcome"):
        assemble_guide(_frame_json_text(), modules, module_ids=_module_ids())



def test_assemble_guide_ignores_mapping_order_and_preserves_module_order() -> None:
    from education_pipeline.guides.canonical import assemble_guide

    modules = _modules_map()
    reversed_mapping = {key: modules[key] for key in reversed(list(modules))}

    assembled = assemble_guide(
        _frame_json_text(), reversed_mapping, module_ids=_module_ids()
    )

    assert assembled == _expected_assembled_bytes()
    assert [module["id"] for module in json.loads(assembled)["modules"]] == _module_ids()


def test_assemble_guide_output_round_trips_and_matches_the_frozen_hash() -> None:
    from education_pipeline.guides.canonical import assemble_guide

    assembled = assemble_guide(
        _frame_json_text(), _modules_map(), module_ids=_module_ids()
    )
    reparsed = normalize_guide(parse_guide(assembled))

    assert guide_sha256(reparsed) == EXPECTED_SHA256
    assert canonical_guide_bytes(reparsed) == assembled


def test_assemble_guide_is_pure_and_leaves_its_inputs_untouched() -> None:
    from education_pipeline.guides.canonical import assemble_guide

    frame_json = _frame_json_text()
    modules = _modules_map()
    modules_snapshot = dict(modules)

    assemble_guide(frame_json, modules, module_ids=_module_ids())

    assert frame_json == _frame_json_text()
    assert modules == modules_snapshot
    assert all(
        module["sections"] == [] for module in json.loads(frame_json)["modules"]
    )


def test_validate_frame_rejects_stub_sections_of_the_wrong_type() -> None:
    import pytest

    from education_pipeline.guides.canonical import SpliceError, validate_frame

    for bad_sections in ({}, "", None, [{"id": "s"}]):
        frame = _frame_data()
        frame["modules"][0]["sections"] = bad_sections
        with pytest.raises(SpliceError, match="sections"):
            validate_frame(json.dumps(frame), module_ids=_module_ids())

    absent = _frame_data()
    del absent["modules"][0]["sections"]
    with pytest.raises(SpliceError, match="sections"):
        validate_frame(json.dumps(absent), module_ids=_module_ids())


# --- T26: section-scoped splice (spec D8) -----------------------------------


def _section_json(section: dict) -> str:
    return json.dumps(section, ensure_ascii=False)


def _fixture_section(module_index: int = 0, section_index: int = 0) -> dict:
    return json.loads(
        json.dumps(_fixture_data()["modules"][module_index]["sections"][section_index])
    )


def test_splice_section_replaces_only_the_target_section() -> None:
    from education_pipeline.guides.canonical import splice_section

    revised = _fixture_section(0, 0)
    revised["title"] = "From events to loops, regenerated"
    revised["blocks"][0]["markdown"] = "A fully regenerated opener."

    merged_bytes = splice_section(
        _base_json(), "loop-basics", "feedback-foundations", _section_json(revised)
    )
    merged = json.loads(merged_bytes)

    # Canonical output that round-trips.
    assert merged_bytes == canonical_guide_bytes(
        normalize_guide(parse_guide(merged_bytes))
    )

    base_canonical = json.loads(canonical_guide_bytes(guide()))
    target_module = merged["modules"][0]
    assert target_module["sections"][0]["title"] == "From events to loops, regenerated"
    # Section order inside the module is preserved.
    assert [section["id"] for section in target_module["sections"]] == [
        section["id"] for section in base_canonical["modules"][0]["sections"]
    ]
    # The sibling section, the other module, and every root key are byte-identical.
    assert json.dumps(target_module["sections"][1], sort_keys=True) == json.dumps(
        base_canonical["modules"][0]["sections"][1], sort_keys=True
    )
    assert json.dumps(merged["modules"][1], sort_keys=True) == json.dumps(
        base_canonical["modules"][1], sort_keys=True
    )
    for key in ("course", "outcomes", "glossary", "sources", "schema_version"):
        assert json.dumps(merged[key], sort_keys=True) == json.dumps(
            base_canonical[key], sort_keys=True
        )
    # The enclosing module's own fields survive untouched.
    for key in ("id", "title", "summary", "outcome_ids", "estimated_minutes"):
        assert json.dumps(target_module[key], sort_keys=True) == json.dumps(
            base_canonical["modules"][0][key], sort_keys=True
        )


def test_splice_section_accepts_bytes_base_and_is_pure() -> None:
    from education_pipeline.guides.canonical import splice_section

    revised = _fixture_section(1, 1)
    revised["title"] = "Practice the gardening decision"
    payload = _section_json(revised)
    base_text = _base_json()

    first = splice_section(
        base_text.encode("utf-8"), "intervention-practice", "garden-decision", payload
    )
    second = splice_section(
        base_text, "intervention-practice", "garden-decision", payload
    )

    assert first == second
    # Inputs are untouched: a pure function, no file I/O, no mutation.
    assert base_text == _base_json()
    assert payload == _section_json(revised)


def test_splice_section_rejects_section_id_rename() -> None:
    import pytest

    from education_pipeline.guides.canonical import SpliceError, splice_section

    revised = _fixture_section(0, 0)
    revised["id"] = "feedback-foundations-renamed"

    with pytest.raises(SpliceError, match="section id must stay"):
        splice_section(
            _base_json(), "loop-basics", "feedback-foundations", _section_json(revised)
        )


def test_splice_section_rejects_unknown_target_module() -> None:
    import pytest

    from education_pipeline.guides.canonical import SpliceError, splice_section

    with pytest.raises(SpliceError, match="loop-basics"):
        splice_section(
            _base_json(),
            "no-such-module",
            "feedback-foundations",
            _section_json(_fixture_section(0, 0)),
        )


def test_splice_section_rejects_unknown_target_section() -> None:
    import pytest

    from education_pipeline.guides.canonical import SpliceError, splice_section

    revised = _fixture_section(0, 0)
    revised["id"] = "no-such-section"

    with pytest.raises(SpliceError, match="recognize-loop-types"):
        splice_section(
            _base_json(), "loop-basics", "no-such-section", _section_json(revised)
        )


def test_splice_section_rejects_non_section_payloads() -> None:
    import pytest

    from education_pipeline.guides.canonical import SpliceError, splice_section

    with pytest.raises(SpliceError, match="not valid JSON"):
        splice_section(_base_json(), "loop-basics", "feedback-foundations", "not json {")

    with pytest.raises(SpliceError, match="single JSON object"):
        splice_section(
            _base_json(), "loop-basics", "feedback-foundations", json.dumps([1, 2])
        )

    # A whole guide is not a section.
    with pytest.raises(SpliceError, match="section"):
        splice_section(
            _base_json(), "loop-basics", "feedback-foundations", _base_json()
        )

    # A module object is not a section either (it carries `sections`).
    with pytest.raises(SpliceError, match="section"):
        splice_section(
            _base_json(),
            "loop-basics",
            "feedback-foundations",
            _module_json(_fixture_data()["modules"][0]),
        )

    # A section without blocks is refused rather than silently emptied.
    blockless = _fixture_section(0, 0)
    del blockless["blocks"]
    with pytest.raises(SpliceError, match="section"):
        splice_section(
            _base_json(),
            "loop-basics",
            "feedback-foundations",
            _section_json(blockless),
        )


def test_splice_section_rejects_element_id_collision_with_other_modules() -> None:
    import pytest

    from education_pipeline.guides.canonical import SpliceError, splice_section

    data = _fixture_data()
    revised = _fixture_section(0, 0)
    # Steal a block id that lives in the other module.
    revised["blocks"][0]["id"] = data["modules"][1]["sections"][0]["blocks"][0]["id"]

    with pytest.raises(SpliceError, match="duplicate"):
        splice_section(
            _base_json(), "loop-basics", "feedback-foundations", _section_json(revised)
        )


def test_splice_section_rejects_out_of_contract_outcome_reference() -> None:
    import pytest

    from education_pipeline.guides.canonical import SpliceError, splice_section

    revised = _fixture_section(0, 0)
    revised["blocks"][0]["outcome_ids"] = ["not-a-contract-outcome"]

    with pytest.raises(SpliceError, match="not-a-contract-outcome"):
        splice_section(
            _base_json(), "loop-basics", "feedback-foundations", _section_json(revised)
        )


def test_splice_section_rejects_an_unparseable_base_guide() -> None:
    import pytest

    from education_pipeline.guides.canonical import SpliceError, splice_section

    with pytest.raises(SpliceError, match="base guide"):
        splice_section(
            '{"schema_version": "1.0"}',
            "loop-basics",
            "feedback-foundations",
            _section_json(_fixture_section(0, 0)),
        )
