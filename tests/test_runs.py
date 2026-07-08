import json
from pathlib import Path

import pytest

from education_pipeline import (
    ConfigError,
    PromptFile,
    ProfileStore,
    RunStore,
    TopicStore,
)


TOPIC_TOML = """\
schema_version = 1
id = "systems-thinking"
title = "Systems Thinking"
brief = "A public introduction to feedback loops."
audience = "early-career analysts"
goals = ["explain feedback loops"]
"""


PROFILE_TOML = """\
schema_version = 1
id = "visual-profile"
target_learner = "team cohort"
professional_experience = "early-career analysts"
learning_goals = ["understand systems thinking"]

[learning_preferences]
preferred_visual_aids = ["flowcharts", "concept maps"]

[privacy]
private_by_default = true
include_in_published_output = false
publishable_summary = "Early-career team learning systems thinking."
"""


def test_run_store_creates_run_directories(tmp_path: Path) -> None:
    store = RunStore(tmp_path)

    run_dir = store.create_run("systems-thinking")

    assert run_dir == tmp_path / "runs" / "systems-thinking"
    for subdir in ("inputs", "prompts", "responses", "approved", "reports", "final"):
        assert (run_dir / subdir).is_dir()

    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["topic_id"] == "systems-thinking"
    assert manifest["events"] == []


def test_write_spec_prompt_writes_prompt_and_response_stub(tmp_path: Path) -> None:
    store = RunStore(tmp_path)

    result = store.write_spec_prompt("systems-thinking", title="Systems Thinking")

    assert isinstance(result, PromptFile)
    assert result.stage == "spec"
    assert result.topic_id == "systems-thinking"
    assert result.artifact.stage == "spec"

    run_dir = tmp_path / "runs" / "systems-thinking"
    assert result.prompt_path == run_dir / "prompts" / "spec.prompt.md"
    assert result.response_path == run_dir / "responses" / "spec.response.md"
    assert result.stub_path == run_dir / "responses" / "spec.SAVE_RESPONSE_HERE.md"

    assert result.prompt_path.read_text(encoding="utf-8").startswith("# Spec Stage Prompt\n")
    assert "No learner profile is attached." in result.prompt_path.read_text(encoding="utf-8")

    assert not result.response_path.exists()
    assert result.stub_path.exists()
    stub_text = result.stub_path.read_text(encoding="utf-8")
    assert "spec.response.md" in stub_text
    assert "ignored" in stub_text.lower()


def test_write_spec_prompt_uses_attached_profile_snapshot(tmp_path: Path) -> None:
    profiles = ProfileStore(tmp_path)
    profiles.save_profile_toml("visual-profile", PROFILE_TOML)
    profiles.attach_profile_to_topic("visual-profile", "systems-thinking")

    runs = RunStore(tmp_path)
    result = runs.write_spec_prompt("systems-thinking", title="Systems Thinking")

    prompt_text = result.prompt_path.read_text(encoding="utf-8")
    assert "# Learner Profile Context" in prompt_text
    assert "- Professional experience: early-career analysts" in prompt_text
    assert "No learner profile is attached." not in prompt_text


def test_write_spec_prompt_records_manifest_event(tmp_path: Path) -> None:
    store = RunStore(tmp_path)

    store.write_spec_prompt("systems-thinking", title="Systems Thinking")

    manifest = store.read_manifest("systems-thinking")
    assert len(manifest["events"]) == 1
    event = manifest["events"][0]
    assert event["stage"] == "spec"
    assert event["action"] == "prompt_written"
    assert event["prompt_file"] == "prompts/spec.prompt.md"
    assert event["response_file"] == "responses/spec.response.md"
    assert isinstance(event["recorded_at"], str) and event["recorded_at"]


def test_write_spec_prompt_refuses_overwrite_without_opt_in(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    store.write_spec_prompt("systems-thinking", title="Systems Thinking")

    with pytest.raises(ConfigError, match="refusing to overwrite"):
        store.write_spec_prompt("systems-thinking", title="Systems Thinking")

    store.write_spec_prompt("systems-thinking", title="Systems Thinking", overwrite=True)

    manifest = store.read_manifest("systems-thinking")
    assert len(manifest["events"]) == 2


def test_has_ingested_response_ignores_stub(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    result = store.write_spec_prompt("systems-thinking", title="Systems Thinking")

    assert store.has_ingested_response("systems-thinking", "spec") is False

    result.response_path.write_text("# Course Specification\n", encoding="utf-8")

    assert store.has_ingested_response("systems-thinking", "spec") is True


def test_write_topic_spec_prompt_uses_stored_topic(tmp_path: Path) -> None:
    topics = TopicStore(tmp_path)
    topics.save_topic_toml("systems-thinking", TOPIC_TOML)

    runs = RunStore(tmp_path)
    result = runs.write_topic_spec_prompt("systems-thinking")

    assert isinstance(result, PromptFile)
    assert result.stage == "spec"
    assert result.topic_id == "systems-thinking"

    prompt_text = result.prompt_path.read_text(encoding="utf-8")
    assert "- Title: Systems Thinking" in prompt_text
    assert "- Audience: early-career analysts" in prompt_text
    assert "- Goals: explain feedback loops" in prompt_text

    manifest = runs.read_manifest("systems-thinking")
    assert manifest["events"][0]["stage"] == "spec"


def test_write_topic_spec_prompt_uses_attached_profile_snapshot(tmp_path: Path) -> None:
    profiles = ProfileStore(tmp_path)
    profiles.save_profile_toml("visual-profile", PROFILE_TOML)
    profiles.attach_profile_to_topic("visual-profile", "systems-thinking")
    TopicStore(tmp_path).save_topic_toml("systems-thinking", TOPIC_TOML)

    result = RunStore(tmp_path).write_topic_spec_prompt("systems-thinking")

    prompt_text = result.prompt_path.read_text(encoding="utf-8")
    assert "# Learner Profile Context" in prompt_text
    assert "- Professional experience: early-career analysts" in prompt_text


def test_write_topic_spec_prompt_missing_topic_raises(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="topic file not found"):
        RunStore(tmp_path).write_topic_spec_prompt("systems-thinking")


def test_run_store_rejects_path_traversal_topic_ids(tmp_path: Path) -> None:
    store = RunStore(tmp_path)

    with pytest.raises(ConfigError, match="topic id must match"):
        store.create_run("../escape")

    with pytest.raises(ConfigError, match="topic id must match"):
        store.write_spec_prompt("../escape", title="Systems Thinking")


def test_write_spec_prompt_rejects_unknown_stage_helper(tmp_path: Path) -> None:
    store = RunStore(tmp_path)

    with pytest.raises(ConfigError, match="unsupported run stage"):
        store.stage_paths("systems-thinking", "outline")
