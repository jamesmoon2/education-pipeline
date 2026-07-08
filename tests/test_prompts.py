from pathlib import Path

import pytest

from education_pipeline import (
    ConfigError,
    ProfileStore,
    SpecPromptInput,
    compile_attached_spec_prompt,
    compile_spec_prompt,
)


PROFILE_TOML = """\
schema_version = 1
id = "visual-profile"
target_learner = "team cohort"
professional_experience = "early-career analysts"
learning_goals = ["understand systems thinking"]

[learning_preferences]
preferred_visual_aids = ["flowcharts", "concept maps"]
diagram_frequency = "frequent"

[privacy]
private_by_default = true
include_in_published_output = false
publishable_summary = "Early-career team learning systems thinking."
"""


UPDATED_PROFILE_TOML = """\
schema_version = 1
id = "visual-profile"
target_learner = "team cohort"
professional_experience = "mid-career analysts"
learning_goals = ["understand systems thinking"]

[learning_preferences]
preferred_visual_aids = ["decision trees"]
diagram_frequency = "occasional"

[privacy]
private_by_default = true
include_in_published_output = false
publishable_summary = "Mid-career team learning systems thinking."
"""


def test_compile_spec_prompt_without_profile_uses_accessible_defaults() -> None:
    artifact = compile_spec_prompt(
        SpecPromptInput(
            topic_id="systems-thinking",
            title="Systems Thinking",
            topic_brief="A public introduction to feedback loops and system boundaries.",
        )
    )

    assert artifact.stage == "spec"
    assert artifact.topic_id == "systems-thinking"
    assert artifact.text.startswith("# Spec Stage Prompt\n")
    assert "- Topic id: systems-thinking" in artifact.text
    assert "- Title: Systems Thinking" in artifact.text
    assert "- Topic brief: A public introduction to feedback loops and system boundaries." in artifact.text
    assert "No learner profile is attached." in artifact.text
    assert "Keep private learner details out of publishable course text" in artifact.text


def test_compile_spec_prompt_includes_profile_context(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path)
    profile = store.save_profile_toml("visual-profile", PROFILE_TOML)

    artifact = compile_spec_prompt(
        SpecPromptInput(
            topic_id="systems-thinking",
            title="Systems Thinking",
            profile=profile,
        )
    )

    assert "# Learner Profile Context" in artifact.text
    assert "- Target learner: team cohort" in artifact.text
    assert "- Professional experience: early-career analysts" in artifact.text
    assert "- Preferred visual aids: flowcharts, concept maps" in artifact.text
    assert "- Diagram frequency: frequent" in artifact.text
    assert "- Include profile in published output: no" in artifact.text


def test_compile_attached_spec_prompt_uses_snapshot_not_current_profile(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path)
    store.save_profile_toml("visual-profile", PROFILE_TOML)
    store.attach_profile_to_topic("visual-profile", "systems-thinking")
    store.save_profile_toml("visual-profile", UPDATED_PROFILE_TOML, overwrite=True)

    artifact = compile_attached_spec_prompt(
        store,
        "systems-thinking",
        title="Systems Thinking",
    )

    assert "- Professional experience: early-career analysts" in artifact.text
    assert "- Preferred visual aids: flowcharts, concept maps" in artifact.text
    assert "mid-career analysts" not in artifact.text
    assert "decision trees" not in artifact.text


def test_compile_attached_spec_prompt_requires_snapshot(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path)

    with pytest.raises(ConfigError, match="learner profile file not found"):
        compile_attached_spec_prompt(store, "systems-thinking", title="Systems Thinking")


def test_compile_spec_prompt_validates_required_topic_fields() -> None:
    with pytest.raises(ConfigError, match="topic_id must be a non-empty string"):
        compile_spec_prompt(SpecPromptInput(topic_id="", title="Systems Thinking"))

    with pytest.raises(ConfigError, match="title must be a non-empty string"):
        compile_spec_prompt(SpecPromptInput(topic_id="systems-thinking", title=" "))

    with pytest.raises(ConfigError, match="topic_brief must be a non-empty string"):
        compile_spec_prompt(
            SpecPromptInput(
                topic_id="systems-thinking",
                title="Systems Thinking",
                topic_brief="",
            )
        )
