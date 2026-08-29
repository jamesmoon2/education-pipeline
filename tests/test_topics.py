from pathlib import Path

import pytest

from education_pipeline import (
    ConfigError,
    Topic,
    TopicStore,
    load_topic,
    parse_topic,
)
from education_pipeline.topics import emit_topic_toml

import tomllib


TOPIC_TOML = """\
schema_version = 1
id = "systems-thinking"
title = "Systems Thinking"
brief = "A public introduction to feedback loops and system boundaries."
audience = "early-career analysts"
goals = ["explain feedback loops", "identify system boundaries"]
scope_includes = ["reinforcing and balancing loops"]
scope_excludes = ["formal control theory"]
key_questions = ["What makes a loop reinforcing?"]
prerequisites = ["basic graphs"]
constraints = ["no calculus"]
tags = ["public", "intro"]
notes = "Keep examples domain-neutral."

[metadata]
source = "handbook"
"""


MINIMAL_TOPIC_TOML = """\
id = "minimal-topic"
title = "Minimal Topic"
"""


def test_parse_topic_reads_all_fields() -> None:
    topic = parse_topic(_toml(TOPIC_TOML))

    assert topic.id == "systems-thinking"
    assert topic.title == "Systems Thinking"
    assert topic.brief == "A public introduction to feedback loops and system boundaries."
    assert topic.audience == "early-career analysts"
    assert topic.goals == ("explain feedback loops", "identify system boundaries")
    assert topic.scope_includes == ("reinforcing and balancing loops",)
    assert topic.scope_excludes == ("formal control theory",)
    assert topic.key_questions == ("What makes a loop reinforcing?",)
    assert topic.prerequisites == ("basic graphs",)
    assert topic.constraints == ("no calculus",)
    assert topic.tags == ("public", "intro")
    assert topic.notes == "Keep examples domain-neutral."
    assert topic.metadata == {"source": "handbook"}


def test_parse_topic_applies_defaults_for_minimal_input() -> None:
    topic = parse_topic(_toml(MINIMAL_TOPIC_TOML))

    assert topic.schema_version == 1
    assert topic.brief is None
    assert topic.audience is None
    assert topic.goals == ()
    assert topic.scope_includes == ()
    assert topic.tags == ()
    assert topic.metadata == {}


def test_parse_topic_rejects_unknown_field() -> None:
    with pytest.raises(ConfigError, match="unknown topic field"):
        parse_topic({"id": "x", "title": "X", "difficulty": "hard"})


def test_parse_topic_rejects_missing_required_fields() -> None:
    with pytest.raises(ConfigError, match="must define non-empty string 'id'"):
        parse_topic({"title": "X"})

    with pytest.raises(ConfigError, match="must define non-empty string 'title'"):
        parse_topic({"id": "x"})


def test_parse_topic_rejects_unsupported_schema_version() -> None:
    with pytest.raises(ConfigError, match="unsupported topic schema_version"):
        parse_topic({"schema_version": 2, "id": "x", "title": "X"})


def test_parse_topic_rejects_non_string_list_items() -> None:
    with pytest.raises(ConfigError, match="field 'goals' item #1"):
        parse_topic({"id": "x", "title": "X", "goals": [""]})


def test_load_topic_reads_a_toml_file(tmp_path: Path) -> None:
    path = tmp_path / "systems-thinking.toml"
    path.write_text(TOPIC_TOML, encoding="utf-8")

    topic = load_topic(path)

    assert isinstance(topic, Topic)
    assert topic.title == "Systems Thinking"


def test_load_topic_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="topic file not found"):
        load_topic(tmp_path / "missing.toml")


def _toml(text: str) -> dict:
    import tomllib

    return tomllib.loads(text)


def test_parse_topic_reads_optional_blueprint_and_time_budget() -> None:
    topic = parse_topic(
        {
            "id": "x",
            "title": "X",
            "blueprint": "procedural-skill",
            "time_budget_minutes": 90,
        }
    )

    assert topic.blueprint == "procedural-skill"
    assert topic.time_budget_minutes == 90


def test_parse_topic_defaults_blueprint_and_time_budget_to_none() -> None:
    topic = parse_topic(_toml(MINIMAL_TOPIC_TOML))

    assert topic.blueprint is None
    assert topic.time_budget_minutes is None


def test_parse_topic_rejects_invalid_blueprint_shape() -> None:
    with pytest.raises(ConfigError, match="'blueprint' must be a non-empty string"):
        parse_topic({"id": "x", "title": "X", "blueprint": "  "})


@pytest.mark.parametrize("value", [4, 10_001, "90", True])
def test_parse_topic_rejects_out_of_range_time_budget(value: object) -> None:
    with pytest.raises(ConfigError, match="time_budget_minutes"):
        parse_topic({"id": "x", "title": "X", "time_budget_minutes": value})


def test_emit_topic_toml_round_trips_blueprint_and_time_budget() -> None:
    topic = Topic(
        id="budgeted-topic",
        title="Budgeted Topic",
        blueprint="exam-preparation",
        time_budget_minutes=120,
    )

    toml_text = emit_topic_toml(topic)
    round_tripped = parse_topic(tomllib.loads(toml_text))

    assert round_tripped == topic
    assert 'blueprint = "exam-preparation"' in toml_text
    assert "time_budget_minutes = 120" in toml_text


def test_emit_topic_toml_omits_absent_blueprint_and_time_budget() -> None:
    toml_text = emit_topic_toml(Topic(id="minimal-topic", title="Minimal Topic"))

    assert "blueprint" not in toml_text
    assert "time_budget_minutes" not in toml_text


def test_topic_store_saves_lists_and_loads_topics(tmp_path: Path) -> None:
    store = TopicStore(tmp_path)

    topic = store.save_topic_toml("systems-thinking", TOPIC_TOML)

    assert topic.id == "systems-thinking"
    assert store.list_topic_ids() == ("systems-thinking",)
    assert store.load_topic("systems-thinking").title == "Systems Thinking"
    assert store.read_topic_toml("systems-thinking") == TOPIC_TOML
    assert (tmp_path / "topics" / "systems-thinking.toml").read_text(encoding="utf-8") == TOPIC_TOML


def test_topic_store_rejects_id_mismatch(tmp_path: Path) -> None:
    store = TopicStore(tmp_path)

    with pytest.raises(ConfigError, match="topic id mismatch"):
        store.save_topic_toml("different-id", TOPIC_TOML)


def test_topic_store_rejects_overwrite_without_opt_in(tmp_path: Path) -> None:
    store = TopicStore(tmp_path)
    store.save_topic_toml("systems-thinking", TOPIC_TOML)

    with pytest.raises(ConfigError, match="refusing to overwrite"):
        store.save_topic_toml("systems-thinking", TOPIC_TOML)

    topic = store.save_topic_toml("systems-thinking", TOPIC_TOML, overwrite=True)
    assert topic.id == "systems-thinking"


def test_topic_store_imports_validated_topic_file(tmp_path: Path) -> None:
    source = tmp_path / "incoming-topic.toml"
    source.write_text(TOPIC_TOML, encoding="utf-8")
    store = TopicStore(tmp_path / "workspace")

    topic = store.import_topic("systems-thinking", source)

    assert topic.id == "systems-thinking"
    assert store.load_topic("systems-thinking").goals == (
        "explain feedback loops",
        "identify system boundaries",
    )


def test_topic_store_rejects_path_traversal_ids(tmp_path: Path) -> None:
    store = TopicStore(tmp_path)

    with pytest.raises(ConfigError, match="topic id must match"):
        store.save_topic_toml("../escape", TOPIC_TOML)


def test_emit_topic_toml_round_trips_goals_and_special_characters() -> None:
    topic = Topic(
        id="quotes-and-slashes",
        title='Systems "Thinking" 101',
        brief='A guide with a backslash \\ and a "quoted" phrase.',
        audience="early-career analysts",
        goals=('explain "feedback" loops', "handle backslashes \\ safely"),
        notes="Line with a tab\tand a newline\nembedded.",
    )

    toml_text = emit_topic_toml(topic)
    round_tripped = parse_topic(tomllib.loads(toml_text))

    assert round_tripped == topic


def test_emit_topic_toml_omits_empty_optional_fields() -> None:
    topic = Topic(id="minimal-topic", title="Minimal Topic")

    toml_text = emit_topic_toml(topic)

    assert 'id = "minimal-topic"' in toml_text
    assert 'title = "Minimal Topic"' in toml_text
    assert "schema_version = 1" in toml_text
    assert "brief" not in toml_text
    assert "goals" not in toml_text
    assert "metadata" not in toml_text

    round_tripped = parse_topic(tomllib.loads(toml_text))
    assert round_tripped == topic


# ---------------------------------------------------------------------------
# ``Mapping`` is both an annotation and an ``isinstance`` target here, so the
# import source must not change which values parse.


def test_parse_topic_accepts_every_registered_mapping_type() -> None:
    from collections import ChainMap, OrderedDict, UserDict
    from types import MappingProxyType

    source = {"id": "mapping-kinds", "title": "Mapping Kinds"}
    variants = [
        source,
        MappingProxyType(source),
        OrderedDict(source),
        ChainMap(source),
        UserDict(source),
    ]

    parsed = [parse_topic(variant) for variant in variants]

    assert all(item == parsed[0] for item in parsed)


@pytest.mark.parametrize("value", [None, [], "id = 1", 7, ("id", "x")])
def test_parse_topic_rejects_non_mappings(value: object) -> None:
    with pytest.raises(ConfigError, match="topic must be a table"):
        parse_topic(value)  # type: ignore[arg-type]


def test_topic_metadata_accepts_a_mapping_proxy() -> None:
    from types import MappingProxyType

    topic = parse_topic(
        {
            "id": "proxy-metadata",
            "title": "Proxy Metadata",
            "metadata": MappingProxyType({"cohort": "spring"}),
        }
    )

    assert topic.metadata["cohort"] == "spring"
