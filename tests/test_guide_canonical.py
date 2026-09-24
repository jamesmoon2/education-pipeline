from __future__ import annotations

import json
from pathlib import Path

import pytest

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


def _section_json(section: dict) -> str:
    return json.dumps(section, ensure_ascii=False)


def test_splice_section_replaces_only_the_target_section() -> None:
    from education_pipeline.guides.canonical import splice_section

    data = _fixture_data()
    revised = json.loads(json.dumps(data["modules"][0]["sections"][0]))
    revised["title"] = "From events to loops, regenerated"
    revised["blocks"][0]["markdown"] = "A fully regenerated opener."

    merged_bytes = splice_section(
        _base_json(), "loop-basics", "feedback-foundations", _section_json(revised)
    )

    # The canonical base with only that section swapped is exactly the result.
    expected = _fixture_data()
    expected["modules"][0]["sections"][0] = revised
    expected_bytes = canonical_guide_bytes(
        normalize_guide(parse_guide(json.dumps(expected, ensure_ascii=False)))
    )
    assert merged_bytes == expected_bytes

    merged = json.loads(merged_bytes)
    module = next(m for m in merged["modules"] if m["id"] == "loop-basics")
    assert [s["id"] for s in module["sections"]] == [
        s["id"] for s in data["modules"][0]["sections"]
    ]
    assert module["sections"][0]["title"] == "From events to loops, regenerated"


def test_splice_section_rejects_section_id_rename() -> None:
    import pytest

    from education_pipeline.guides.canonical import SpliceError, splice_section

    revised = _fixture_data()["modules"][0]["sections"][0]
    revised["id"] = "feedback-foundations-renamed"

    with pytest.raises(SpliceError, match="rename"):
        splice_section(
            _base_json(), "loop-basics", "feedback-foundations", _section_json(revised)
        )


def test_splice_section_rejects_unknown_module() -> None:
    import pytest

    from education_pipeline.guides.canonical import SpliceError, splice_section

    revised = _fixture_data()["modules"][0]["sections"][0]

    with pytest.raises(SpliceError, match="no-such-module"):
        splice_section(
            _base_json(), "no-such-module", "feedback-foundations", _section_json(revised)
        )


def test_splice_section_rejects_unknown_section() -> None:
    import pytest

    from education_pipeline.guides.canonical import SpliceError, splice_section

    revised = _fixture_data()["modules"][0]["sections"][0]
    revised["id"] = "no-such-section"

    with pytest.raises(SpliceError, match="no-such-section"):
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

    # A fragment carrying a `sections` key is module-shaped, not section-shaped.
    fragment_with_sections = dict(_fixture_data()["modules"][0]["sections"][0])
    fragment_with_sections["sections"] = []
    with pytest.raises(SpliceError, match="single section object"):
        splice_section(
            _base_json(),
            "loop-basics",
            "feedback-foundations",
            json.dumps(fragment_with_sections),
        )

    # A fragment carrying a `modules` key is guide-shaped, not section-shaped.
    fragment_with_modules = dict(_fixture_data()["modules"][0]["sections"][0])
    fragment_with_modules["modules"] = []
    with pytest.raises(SpliceError, match="single section object"):
        splice_section(
            _base_json(),
            "loop-basics",
            "feedback-foundations",
            json.dumps(fragment_with_modules),
        )

    # A whole guide is not a section.
    with pytest.raises(SpliceError, match="rename|section"):
        splice_section(_base_json(), "loop-basics", "feedback-foundations", _base_json())


def test_splice_section_rejects_element_id_collision_with_another_section() -> None:
    import pytest

    from education_pipeline.guides.canonical import SpliceError, splice_section

    data = _fixture_data()
    revised = data["modules"][0]["sections"][0]
    sibling_block_id = data["modules"][0]["sections"][1]["blocks"][0]["id"]
    revised["blocks"][0]["id"] = sibling_block_id

    with pytest.raises(SpliceError, match="duplicate"):
        splice_section(
            _base_json(), "loop-basics", "feedback-foundations", _section_json(revised)
        )


def test_splice_section_rejects_element_id_collision_with_another_module() -> None:
    import pytest

    from education_pipeline.guides.canonical import SpliceError, splice_section

    data = _fixture_data()
    revised = data["modules"][0]["sections"][0]
    other_block_id = data["modules"][1]["sections"][0]["blocks"][0]["id"]
    revised["blocks"][0]["id"] = other_block_id

    with pytest.raises(SpliceError, match="duplicate"):
        splice_section(
            _base_json(), "loop-basics", "feedback-foundations", _section_json(revised)
        )


def test_splice_section_rejects_a_merged_guide_failing_strict_parse() -> None:
    import pytest

    from education_pipeline.guides.canonical import SpliceError, splice_section

    data = _fixture_data()
    # The "recognize-loop-types" section holds the module's only interactive
    # blocks; replacing them with a plain rich_text block leaves the module
    # with none, so the merged guide fails strict parse (module.no_interaction).
    revised = data["modules"][0]["sections"][1]
    revised["blocks"] = [
        {
            "id": "recognize-loop-types-note",
            "type": "rich_text",
            "outcome_ids": ["map-loop"],
            "markdown": "A plain note with no interaction.",
        }
    ]

    with pytest.raises(SpliceError, match="not valid"):
        splice_section(
            _base_json(), "loop-basics", "recognize-loop-types", _section_json(revised)
        )


def test_empty_personalization_annotations_are_omitted_for_both_versions() -> None:
    for version in ("1.0", "1.1"):
        data = json.loads(FIXTURE.read_text(encoding="utf-8"))
        data["schema_version"] = version
        canonical = canonical_guide_bytes(
            normalize_guide(parse_guide(json.dumps(data, ensure_ascii=False)))
        )

        assert b'"serves_goals"' not in canonical
        assert b'"goal_exclusions"' not in canonical


# --- assemble_guide --------------------------------------------------------
#
# `assemble_guide(skeleton_json, modules, *, module_order)` replaces every
# stub in a skeleton with its module fragment, merges optional per-module
# `glossary`/`sources` contributions by id, and re-parses the merged
# document strictly. Reassembling the fixture's own skeleton + module
# fragments must reconstitute the fixture's own canonical bytes exactly.


def _module_order() -> tuple[str, ...]:
    return tuple(module["id"] for module in _fixture_data()["modules"])


def _skeleton_json(data: dict | None = None) -> str:
    data = data if data is not None else _fixture_data()
    skeleton = json.loads(json.dumps(data))
    skeleton["modules"] = [
        {**{key: value for key, value in module.items() if key != "sections"}, "sections": []}
        for module in data["modules"]
    ]
    return json.dumps(skeleton, ensure_ascii=False)


def _modules_map(data: dict | None = None) -> dict[str, str]:
    data = data if data is not None else _fixture_data()
    return {
        module["id"]: json.dumps(module, ensure_ascii=False) for module in data["modules"]
    }


def test_assemble_guide_reconstitutes_the_fixture_deterministically() -> None:
    from education_pipeline.guides.canonical import assemble_guide

    data = _fixture_data()
    skeleton = _skeleton_json(data)
    modules = _modules_map(data)
    order = _module_order()
    expected = canonical_guide_bytes(guide())

    assembled = assemble_guide(skeleton, modules, module_order=order)

    assert assembled == expected
    assert parse_guide(assembled).ok
    # Determinism: same inputs, called again, produce identical bytes.
    assert assemble_guide(skeleton, modules, module_order=order) == assembled
    # Module dict insertion order must not matter; only module_order does.
    reordered_modules = dict(reversed(list(modules.items())))
    assert assemble_guide(skeleton, reordered_modules, module_order=order) == assembled


def test_assemble_guide_accepts_bytes_inputs() -> None:
    from education_pipeline.guides.canonical import assemble_guide

    data = _fixture_data()
    skeleton = _skeleton_json(data).encode("utf-8")
    modules = {
        module_id: text.encode("utf-8") for module_id, text in _modules_map(data).items()
    }

    assembled = assemble_guide(skeleton, modules, module_order=_module_order())

    assert assembled == canonical_guide_bytes(guide())


def test_assemble_guide_merges_module_glossary_contributions_by_id() -> None:
    from education_pipeline.guides.canonical import assemble_guide

    data = _fixture_data()
    skeleton_dict = json.loads(_skeleton_json(data))
    skeleton_dict["glossary"] = []
    skeleton = json.dumps(skeleton_dict, ensure_ascii=False)

    module0 = dict(data["modules"][0])
    module0["glossary"] = data["glossary"][:2]
    module1 = dict(data["modules"][1])
    module1["glossary"] = data["glossary"][2:]
    modules = {
        "loop-basics": json.dumps(module0, ensure_ascii=False),
        "intervention-practice": json.dumps(module1, ensure_ascii=False),
    }

    assembled = assemble_guide(skeleton, modules, module_order=_module_order())
    decoded = json.loads(assembled)

    assert {entry["id"] for entry in decoded["glossary"]} == {
        entry["id"] for entry in data["glossary"]
    }
    assert parse_guide(assembled).ok


def test_assemble_guide_allows_identical_duplicate_contributions() -> None:
    from education_pipeline.guides.canonical import assemble_guide

    data = _fixture_data()
    skeleton_dict = json.loads(_skeleton_json(data))
    skeleton_dict["glossary"] = []
    skeleton = json.dumps(skeleton_dict, ensure_ascii=False)
    shared_entry = data["glossary"][0]

    module0 = dict(data["modules"][0])
    module0["glossary"] = [shared_entry]
    module1 = dict(data["modules"][1])
    module1["glossary"] = [shared_entry]
    modules = {
        "loop-basics": json.dumps(module0, ensure_ascii=False),
        "intervention-practice": json.dumps(module1, ensure_ascii=False),
    }

    assembled = assemble_guide(skeleton, modules, module_order=_module_order())
    decoded = json.loads(assembled)

    assert [entry["id"] for entry in decoded["glossary"]].count(shared_entry["id"]) == 1


def test_assemble_guide_rejects_conflicting_glossary_contribution_content() -> None:
    from education_pipeline.guides.canonical import AssemblyError, assemble_guide

    data = _fixture_data()
    skeleton_dict = json.loads(_skeleton_json(data))
    skeleton_dict["glossary"] = []
    skeleton = json.dumps(skeleton_dict, ensure_ascii=False)

    module0 = dict(data["modules"][0])
    module0["glossary"] = [
        {"id": "shared-term", "term": "Shared", "definition": "From loop-basics."}
    ]
    module1 = dict(data["modules"][1])
    module1["glossary"] = [
        {"id": "shared-term", "term": "Shared", "definition": "From intervention-practice."}
    ]
    modules = {
        "loop-basics": json.dumps(module0, ensure_ascii=False),
        "intervention-practice": json.dumps(module1, ensure_ascii=False),
    }

    with pytest.raises(AssemblyError):
        assemble_guide(skeleton, modules, module_order=_module_order())


def test_assemble_guide_rejects_cross_module_id_collision_naming_both_modules() -> None:
    from education_pipeline.guides.canonical import AssemblyError, assemble_guide

    data = _fixture_data()
    skeleton = _skeleton_json(data)
    module0 = json.loads(json.dumps(data["modules"][0]))
    module1 = data["modules"][1]
    # Steal a section id that already lives in the other module.
    module0["sections"][0]["id"] = module1["sections"][0]["id"]
    modules = {
        "loop-basics": json.dumps(module0, ensure_ascii=False),
        "intervention-practice": json.dumps(module1, ensure_ascii=False),
    }

    with pytest.raises(AssemblyError) as exc_info:
        assemble_guide(skeleton, modules, module_order=_module_order())

    assert set(exc_info.value.module_ids) == {"loop-basics", "intervention-practice"}


def test_assemble_guide_rejects_missing_module() -> None:
    from education_pipeline.guides.canonical import AssemblyError, assemble_guide

    data = _fixture_data()
    skeleton = _skeleton_json(data)
    modules = _modules_map(data)
    del modules["intervention-practice"]

    with pytest.raises(AssemblyError) as exc_info:
        assemble_guide(skeleton, modules, module_order=_module_order())

    assert "intervention-practice" in exc_info.value.module_ids


def test_assemble_guide_rejects_extra_module() -> None:
    from education_pipeline.guides.canonical import AssemblyError, assemble_guide

    data = _fixture_data()
    skeleton = _skeleton_json(data)
    modules = _modules_map(data)
    extra = dict(data["modules"][0])
    extra["id"] = "surprise-module"
    modules["surprise-module"] = json.dumps(extra, ensure_ascii=False)

    with pytest.raises(AssemblyError) as exc_info:
        assemble_guide(skeleton, modules, module_order=_module_order())

    assert "surprise-module" in exc_info.value.module_ids


def test_assemble_guide_rejects_module_fragment_id_rename() -> None:
    from education_pipeline.guides.canonical import AssemblyError, assemble_guide

    data = _fixture_data()
    skeleton = _skeleton_json(data)
    modules = _modules_map(data)
    renamed = dict(data["modules"][0])
    renamed["id"] = "loop-basics-renamed"
    modules["loop-basics"] = json.dumps(renamed, ensure_ascii=False)

    with pytest.raises(AssemblyError) as exc_info:
        assemble_guide(skeleton, modules, module_order=_module_order())

    assert "loop-basics" in exc_info.value.module_ids


def test_assemble_guide_rejects_a_modules_key_in_a_fragment() -> None:
    from education_pipeline.guides.canonical import AssemblyError, assemble_guide

    data = _fixture_data()
    skeleton = _skeleton_json(data)
    modules = _modules_map(data)
    whole_guide_shaped = dict(data["modules"][0])
    whole_guide_shaped["modules"] = []
    modules["loop-basics"] = json.dumps(whole_guide_shaped, ensure_ascii=False)

    with pytest.raises(AssemblyError) as exc_info:
        assemble_guide(skeleton, modules, module_order=_module_order())

    assert "loop-basics" in exc_info.value.module_ids


def test_assemble_guide_rejects_a_skeleton_that_fails_check_skeleton() -> None:
    from education_pipeline.guides.canonical import AssemblyError, assemble_guide

    data = _fixture_data()
    skeleton_dict = json.loads(_skeleton_json(data))
    skeleton_dict["modules"][0]["sections"] = [data["modules"][0]["sections"][0]]
    skeleton = json.dumps(skeleton_dict, ensure_ascii=False)
    modules = _modules_map(data)

    with pytest.raises(AssemblyError) as exc_info:
        assemble_guide(skeleton, modules, module_order=_module_order())

    # A skeleton-level failure implicates no particular module.
    assert exc_info.value.module_ids == ()


def test_assemble_guide_rejects_dangling_source_reference_after_merge() -> None:
    from education_pipeline.guides.canonical import AssemblyError, assemble_guide

    data = _fixture_data()
    skeleton = _skeleton_json(data)
    modules = _modules_map(data)
    module0 = json.loads(modules["loop-basics"])
    module0["sections"][0]["blocks"][0]["source_ids"] = ["not-a-real-source"]
    modules["loop-basics"] = json.dumps(module0, ensure_ascii=False)

    with pytest.raises(AssemblyError):
        assemble_guide(skeleton, modules, module_order=_module_order())


def test_assembly_error_is_a_splice_error_subclass() -> None:
    from education_pipeline.guides.canonical import AssemblyError, SpliceError

    assert issubclass(AssemblyError, SpliceError)


def test_assemble_guide_merges_contributions_skeleton_first_then_module_order() -> None:
    # Pins the merge order itself (skeleton, then modules in `module_order`),
    # which the id-set assertions above cannot see.
    from education_pipeline.guides.canonical import assemble_guide

    data = _fixture_data()
    skeleton_dict = json.loads(_skeleton_json(data))
    skeleton_dict["glossary"] = data["glossary"][:1]
    skeleton = json.dumps(skeleton_dict, ensure_ascii=False)

    module0 = dict(data["modules"][0])
    module0["glossary"] = data["glossary"][1:2]
    module1 = dict(data["modules"][1])
    module1["glossary"] = data["glossary"][2:]
    modules = {
        "loop-basics": json.dumps(module0, ensure_ascii=False),
        "intervention-practice": json.dumps(module1, ensure_ascii=False),
    }

    decoded = json.loads(assemble_guide(skeleton, modules, module_order=_module_order()))

    assert [entry["id"] for entry in decoded["glossary"]] == [
        entry["id"] for entry in data["glossary"]
    ]


# ---------------------------------------------------------------------------
# PR #39 review finding 8: contribution owners are tracked per kind.
# ---------------------------------------------------------------------------


def test_assemble_guide_rejects_a_glossary_id_reused_as_a_source_id() -> None:
    """One id namespace: the same id cannot name a glossary entry and a source.

    ``_merge_contributions`` shared one ``owners`` map between the two kinds
    while looking the previous entry up in the *current* kind's list only, so
    this raised a bare ``StopIteration`` instead of an ``AssemblyError``.
    """

    from education_pipeline.guides.canonical import AssemblyError, assemble_guide

    data = _fixture_data()
    skeleton_dict = json.loads(_skeleton_json(data))
    skeleton_dict["glossary"] = []
    skeleton = json.dumps(skeleton_dict, ensure_ascii=False)

    module0 = dict(data["modules"][0])
    module0["glossary"] = [
        {"id": "shared-id", "term": "Shared", "definition": "From loop-basics."}
    ]
    module1 = dict(data["modules"][1])
    module1["sources"] = [
        {"id": "shared-id", "title": "A source that stole a glossary id"}
    ]
    modules = {
        "loop-basics": json.dumps(module0, ensure_ascii=False),
        "intervention-practice": json.dumps(module1, ensure_ascii=False),
    }

    with pytest.raises(AssemblyError) as excinfo:
        assemble_guide(skeleton, modules, module_order=_module_order())

    message = str(excinfo.value)
    assert "shared-id" in message
    assert "loop-basics" in message and "intervention-practice" in message
    assert set(excinfo.value.module_ids) == {"loop-basics", "intervention-practice"}


def test_assemble_guide_rejects_a_skeleton_glossary_id_reused_as_a_module_source() -> None:
    from education_pipeline.guides.canonical import AssemblyError, assemble_guide

    data = _fixture_data()
    skeleton = _skeleton_json(data)
    shared_id = data["glossary"][0]["id"]

    module1 = dict(data["modules"][1])
    module1["sources"] = [{"id": shared_id, "title": "Not a glossary entry"}]
    modules = dict(_modules_map(data))
    modules["intervention-practice"] = json.dumps(module1, ensure_ascii=False)

    with pytest.raises(AssemblyError) as excinfo:
        assemble_guide(skeleton, modules, module_order=_module_order())

    assert shared_id in str(excinfo.value)
    assert "the skeleton" in str(excinfo.value)


# --- schema 1.2 diagrams ---------------------------------------------------
#
# Spec: docs/superpowers/specs/2026-09-23-diagram-block-design.md §4. The
# canonical walk stays generic: `json` field metadata renames `from_id` /
# `to_id`, `json_keyed` turns comparison values into an object keyed by item
# id, and `omit_empty` drops the kind arrays of other kinds.

DIAGRAMS_FIXTURE = (
    Path(__file__).parent / "fixtures/guides/feedback-loops.diagrams.guide.json"
)
DIAGRAM_IDS = {
    "flow": "growth-loop-flow",
    "concept_map": "loop-kinds-map",
    "comparison": "loop-types-comparison",
    "timeline": "watering-delay-timeline",
}
KIND_KEYS = {
    "flow": {"nodes", "edges"},
    "concept_map": {"hub", "nodes", "edges"},
    "timeline": {"events"},
    "comparison": {"items", "criteria"},
}
PERSONALIZED_EXPECTED_SHA256 = (
    "03ae218e2d12d3d618eec7598a57214e4d65dabaa39cfff6ad2ecc2e629003ff"
)


def _diagrams_data() -> dict:
    return json.loads(DIAGRAMS_FIXTURE.read_text(encoding="utf-8"))


def _blocks(decoded: dict) -> dict[str, dict]:
    return {
        block["id"]: block
        for module in decoded["modules"]
        for section in module["sections"]
        for block in section["blocks"]
    }


def _only_diagram(kind: str) -> dict:
    """The diagrams fixture with every diagram except ``kind``'s removed."""

    data = _diagrams_data()
    keep = DIAGRAM_IDS[kind]
    for module in data["modules"]:
        for section in module["sections"]:
            section["blocks"] = [
                block
                for block in section["blocks"]
                if block["type"] != "diagram" or block["id"] == keep
            ]
    return data


def test_existing_fixture_canonical_bytes_are_unchanged_by_schema_1_2() -> None:
    # Both pre-1.2 fixtures keep their exact canonical bytes (spec §4,
    # Migration: "Canonical bytes of every existing guide are unchanged").
    personalized = normalize_guide(parse_guide(PERSONALIZED_FIXTURE.read_bytes()))

    assert guide_sha256(guide()) == EXPECTED_SHA256
    assert guide_sha256(personalized) == PERSONALIZED_EXPECTED_SHA256


def test_diagrams_fixture_canonical_bytes_round_trip() -> None:
    canonical = canonical_guide_bytes(
        normalize_guide(parse_guide(DIAGRAMS_FIXTURE.read_bytes()))
    )

    assert canonical == canonical_guide_bytes(normalize_guide(parse_guide(canonical)))
    assert json.loads(canonical)["schema_version"] == "1.2"


@pytest.mark.parametrize("kind", sorted(DIAGRAM_IDS))
def test_each_diagram_kind_round_trips_byte_for_byte(kind: str) -> None:
    source = json.dumps(_only_diagram(kind), ensure_ascii=False)
    canonical = canonical_guide_bytes(normalize_guide(parse_guide(source)))

    assert canonical == canonical_guide_bytes(normalize_guide(parse_guide(canonical)))
    decoded_diagrams = [
        block for block in _blocks(json.loads(canonical)).values()
        if block["type"] == "diagram"
    ]
    assert [block["kind"] for block in decoded_diagrams] == [kind]


@pytest.mark.parametrize("kind", sorted(DIAGRAM_IDS))
def test_canonical_diagram_has_no_foreign_kind_fields(kind: str) -> None:
    canonical = canonical_guide_bytes(
        normalize_guide(parse_guide(DIAGRAMS_FIXTURE.read_bytes()))
    )
    block = _blocks(json.loads(canonical))[DIAGRAM_IDS[kind]]

    common = {"id", "type", "kind", "title", "outcome_ids", "source_ids"}
    optional_present = {"caption"} if kind == "flow" else set()
    assert set(block) == common | optional_present | KIND_KEYS[kind]


def test_canonical_flow_uses_from_and_to_and_matches_the_spec_exactly() -> None:
    canonical = canonical_guide_bytes(
        normalize_guide(parse_guide(DIAGRAMS_FIXTURE.read_bytes()))
    )
    flow = _blocks(json.loads(canonical))["growth-loop-flow"]

    assert flow == {
        "caption": "The last connection closes a **reinforcing** loop.",
        "edges": [
            {"from": "biomass", "label": "increases", "to": "leaf-area"},
            {"from": "leaf-area", "label": "increases", "to": "sunlight"},
            {"from": "sunlight", "label": "fuels", "to": "growth"},
            {"from": "growth", "label": "adds to", "to": "biomass"},
        ],
        "id": "growth-loop-flow",
        "kind": "flow",
        "nodes": [
            {"id": "biomass", "label": "Plant biomass"},
            {
                "detail": "More biomass usually means more leaves.",
                "id": "leaf-area",
                "label": "Leaf area",
            },
            {"id": "sunlight", "label": "Sunlight captured"},
            {"id": "growth", "label": "New growth"},
        ],
        "outcome_ids": ["map-loop"],
        "source_ids": [],
        "title": "How plant growth reinforces itself",
        "type": "diagram",
    }
    assert b'"from_id"' not in canonical and b'"to_id"' not in canonical


def test_canonical_comparison_values_are_objects_keyed_by_item_id() -> None:
    canonical = canonical_guide_bytes(
        normalize_guide(parse_guide(DIAGRAMS_FIXTURE.read_bytes()))
    )
    comparison = _blocks(json.loads(canonical))["loop-types-comparison"]

    assert comparison["criteria"][0] == {
        "id": "effect",
        "label": "What it does",
        "values": {
            "balancing": "Pushes toward a goal or limit",
            "reinforcing": "Amplifies change in one direction",
        },
    }
    assert comparison["items"] == [
        {"id": "reinforcing", "label": "Reinforcing loop"},
        {"id": "balancing", "label": "Balancing loop"},
    ]
    assert comparison["source_ids"] == ["meadows-2008"]
    assert b'"item_id"' not in canonical


def test_canonical_diagram_keeps_raw_untrimmed_strings() -> None:
    data = _diagrams_data()
    _blocks(data)["growth-loop-flow"]["nodes"][0]["label"] = " Plant biomass "

    canonical = canonical_guide_bytes(
        normalize_guide(parse_guide(json.dumps(data, ensure_ascii=False)))
    )

    assert _blocks(json.loads(canonical))["growth-loop-flow"]["nodes"][0][
        "label"
    ] == " Plant biomass "


def _diagrams_skeleton_json(data: dict) -> str:
    skeleton = json.loads(json.dumps(data))
    skeleton["modules"] = [
        {**{key: value for key, value in module.items() if key != "sections"}, "sections": []}
        for module in data["modules"]
    ]
    return json.dumps(skeleton, ensure_ascii=False)


def test_assemble_guide_reconstitutes_the_diagrams_fixture() -> None:
    from education_pipeline.guides.canonical import assemble_guide

    data = _diagrams_data()
    order = tuple(module["id"] for module in data["modules"])

    assembled = assemble_guide(
        _diagrams_skeleton_json(data), _modules_map(data), module_order=order
    )

    assert assembled == canonical_guide_bytes(
        normalize_guide(parse_guide(DIAGRAMS_FIXTURE.read_bytes()))
    )


def test_assemble_guide_allows_the_same_local_node_id_in_two_modules() -> None:
    from education_pipeline.guides.canonical import assemble_guide

    data = _diagrams_data()
    for index, module in enumerate(data["modules"]):
        module["sections"][0]["blocks"].append(
            {
                "id": f"{module['id']}-steps",
                "type": "diagram",
                "kind": "flow",
                "title": f"Steps for module {index + 1}",
                "nodes": [
                    {"id": "start", "label": "Start"},
                    {"id": "finish", "label": "Finish"},
                ],
                "edges": [{"from": "start", "to": "finish"}],
            }
        )
    order = tuple(module["id"] for module in data["modules"])

    assembled = assemble_guide(
        _diagrams_skeleton_json(data), _modules_map(data), module_order=order
    )

    assert parse_guide(assembled).ok
    blocks = _blocks(json.loads(assembled))
    assert blocks["loop-basics-steps"]["nodes"][0]["id"] == "start"
    assert blocks["intervention-practice-steps"]["nodes"][0]["id"] == "start"


def test_assemble_guide_still_rejects_a_diagram_block_id_reused_across_modules() -> None:
    from education_pipeline.guides.canonical import AssemblyError, assemble_guide

    data = _diagrams_data()
    stolen = json.loads(json.dumps(_blocks(data)["growth-loop-flow"]))
    data["modules"][1]["sections"][0]["blocks"].append(stolen)
    order = tuple(module["id"] for module in data["modules"])

    with pytest.raises(AssemblyError) as exc_info:
        assemble_guide(
            _diagrams_skeleton_json(data), _modules_map(data), module_order=order
        )

    assert set(exc_info.value.module_ids) == {"loop-basics", "intervention-practice"}
