import json
from pathlib import Path

import pytest

from education_pipeline import (
    ConfigError,
    NextAction,
    PromptFile,
    ProfileStore,
    RunStatus,
    RunStore,
    StageStatus,
    TopicStore,
)


def _drive_spec_to_approved(runs: RunStore, topic_id: str) -> None:
    result = runs.write_spec_prompt(topic_id, title="Systems Thinking")
    result.response_path.write_text("# Course Specification\n", encoding="utf-8")
    runs.approve_stage(topic_id, "spec")


def _drive_outline_to_approved(runs: RunStore, topic_id: str) -> None:
    result = runs.write_outline_prompt(topic_id)
    result.response_path.write_text("# Course Outline\n", encoding="utf-8")
    runs.approve_stage(topic_id, "outline")


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


def test_approve_stage_promotes_ingested_response(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    result = store.write_spec_prompt("systems-thinking", title="Systems Thinking")
    result.response_path.write_text("# Course Specification\n", encoding="utf-8")

    approved_path = store.approve_stage("systems-thinking", "spec")

    assert approved_path == tmp_path / "runs" / "systems-thinking" / "approved" / "spec.md"
    assert approved_path.read_text(encoding="utf-8") == "# Course Specification\n"
    assert store.read_approved("systems-thinking", "spec") == "# Course Specification\n"

    events = store.read_manifest("systems-thinking")["events"]
    assert events[-1]["stage"] == "spec"
    assert events[-1]["action"] == "response_approved"
    assert events[-1]["approved_file"] == "approved/spec.md"


def test_approve_stage_requires_ingested_response(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    store.write_spec_prompt("systems-thinking", title="Systems Thinking")

    with pytest.raises(ConfigError, match="no ingested response to approve"):
        store.approve_stage("systems-thinking", "spec")


def test_write_outline_prompt_uses_approved_spec_and_topic(tmp_path: Path) -> None:
    TopicStore(tmp_path).save_topic_toml("systems-thinking", TOPIC_TOML)
    runs = RunStore(tmp_path)
    spec = runs.write_topic_spec_prompt("systems-thinking")
    spec.response_path.write_text(
        "# Course Specification: Systems Thinking\n\n## Learning Outcomes\n- Explain loops.\n",
        encoding="utf-8",
    )
    runs.approve_stage("systems-thinking", "spec")

    result = runs.write_outline_prompt("systems-thinking")

    assert result.stage == "outline"
    assert result.prompt_path == tmp_path / "runs" / "systems-thinking" / "prompts" / "outline.prompt.md"
    prompt_text = result.prompt_path.read_text(encoding="utf-8")
    assert "## Approved Specification" in prompt_text
    assert "- Explain loops." in prompt_text
    assert "- Title: Systems Thinking" in prompt_text


def test_write_outline_prompt_requires_approved_spec(tmp_path: Path) -> None:
    TopicStore(tmp_path).save_topic_toml("systems-thinking", TOPIC_TOML)

    with pytest.raises(ConfigError, match="approved spec response not found"):
        RunStore(tmp_path).write_outline_prompt("systems-thinking")


def test_write_draft_prompt_uses_approved_outline(tmp_path: Path) -> None:
    TopicStore(tmp_path).save_topic_toml("systems-thinking", TOPIC_TOML)
    runs = RunStore(tmp_path)
    _drive_spec_to_approved(runs, "systems-thinking")

    outline = runs.write_outline_prompt("systems-thinking")
    outline.response_path.write_text(
        "# Course Outline: Systems Thinking\n\n## Modules\n1. Feedback loops\n",
        encoding="utf-8",
    )
    runs.approve_stage("systems-thinking", "outline")

    result = runs.write_draft_prompt("systems-thinking")

    assert result.stage == "draft"
    assert result.prompt_path == tmp_path / "runs" / "systems-thinking" / "prompts" / "draft.prompt.md"
    prompt_text = result.prompt_path.read_text(encoding="utf-8")
    assert "## Approved Outline" in prompt_text
    assert "1. Feedback loops" in prompt_text
    assert "- Title: Systems Thinking" in prompt_text


def test_write_draft_prompt_requires_approved_outline(tmp_path: Path) -> None:
    TopicStore(tmp_path).save_topic_toml("systems-thinking", TOPIC_TOML)
    runs = RunStore(tmp_path)
    _drive_spec_to_approved(runs, "systems-thinking")

    with pytest.raises(ConfigError, match="approved outline response not found"):
        runs.write_draft_prompt("systems-thinking")


def test_run_status_reports_pending_before_any_work(tmp_path: Path) -> None:
    status = RunStore(tmp_path).run_status("systems-thinking")

    assert isinstance(status, RunStatus)
    assert status.topic_id == "systems-thinking"
    assert [s.stage for s in status.stages] == ["spec", "outline", "draft"]
    assert all(
        not s.prompt_written and not s.response_ingested and not s.approved
        for s in status.stages
    )
    assert status.stages[0].state == "pending"
    assert status.next_action == NextAction(
        topic_id="systems-thinking",
        stage="spec",
        action="write_prompt",
        detail=status.next_action.detail,
    )


def test_run_status_advances_through_spec_substates(tmp_path: Path) -> None:
    runs = RunStore(tmp_path)

    result = runs.write_spec_prompt("systems-thinking", title="Systems Thinking")
    action = runs.run_status("systems-thinking").next_action
    assert (action.stage, action.action) == ("spec", "save_response")

    result.response_path.write_text("# Course Specification\n", encoding="utf-8")
    action = runs.run_status("systems-thinking").next_action
    assert (action.stage, action.action) == ("spec", "approve")

    runs.approve_stage("systems-thinking", "spec")
    status = runs.run_status("systems-thinking")
    assert status.stages[0].state == "approved"
    assert (status.next_action.stage, status.next_action.action) == ("outline", "write_prompt")


def test_run_status_reports_done_when_all_stages_approved(tmp_path: Path) -> None:
    TopicStore(tmp_path).save_topic_toml("systems-thinking", TOPIC_TOML)
    runs = RunStore(tmp_path)
    _drive_spec_to_approved(runs, "systems-thinking")
    _drive_outline_to_approved(runs, "systems-thinking")

    draft = runs.write_draft_prompt("systems-thinking")
    draft.response_path.write_text("# Systems Thinking\n", encoding="utf-8")
    runs.approve_stage("systems-thinking", "draft")

    status = runs.run_status("systems-thinking")
    assert all(s.approved for s in status.stages)
    assert status.next_action.stage is None
    assert status.next_action.action == "done"


def test_stage_status_rejects_unsupported_stage(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="unsupported run stage"):
        RunStore(tmp_path).stage_status("systems-thinking", "qa")


def test_stage_status_returns_flags(tmp_path: Path) -> None:
    runs = RunStore(tmp_path)
    runs.write_spec_prompt("systems-thinking", title="Systems Thinking")

    status = runs.stage_status("systems-thinking", "spec")

    assert isinstance(status, StageStatus)
    assert status.prompt_written is True
    assert status.response_ingested is False
    assert status.approved is False


def test_list_run_ids_returns_started_runs(tmp_path: Path) -> None:
    runs = RunStore(tmp_path)
    assert runs.list_run_ids() == ()

    runs.write_spec_prompt("beta-topic", title="Beta")
    runs.write_spec_prompt("alpha-topic", title="Alpha")

    assert runs.list_run_ids() == ("alpha-topic", "beta-topic")


def test_run_store_rejects_path_traversal_topic_ids(tmp_path: Path) -> None:
    store = RunStore(tmp_path)

    with pytest.raises(ConfigError, match="topic id must match"):
        store.create_run("../escape")

    with pytest.raises(ConfigError, match="topic id must match"):
        store.write_spec_prompt("../escape", title="Systems Thinking")


def test_write_spec_prompt_rejects_unknown_stage_helper(tmp_path: Path) -> None:
    store = RunStore(tmp_path)

    with pytest.raises(ConfigError, match="unsupported run stage"):
        store.stage_paths("systems-thinking", "qa")
