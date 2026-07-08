from pathlib import Path

import pytest

from education_pipeline import ConfigError, ProfileStore


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


UPDATED_PROFILE_TOML = """\
schema_version = 1
id = "visual-profile"
target_learner = "team cohort"
professional_experience = "mid-career analysts"
learning_goals = ["understand systems thinking"]

[learning_preferences]
preferred_visual_aids = ["decision trees"]

[privacy]
private_by_default = true
include_in_published_output = false
publishable_summary = "Mid-career team learning systems thinking."
"""


def test_profile_store_saves_lists_and_loads_profiles(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path)

    profile = store.save_profile_toml("visual-profile", PROFILE_TOML)

    assert profile.id == "visual-profile"
    assert store.list_profile_ids() == ("visual-profile",)
    assert store.load_profile("visual-profile").professional_experience == "early-career analysts"
    assert store.read_profile_toml("visual-profile") == PROFILE_TOML
    assert (tmp_path / "profiles" / "visual-profile.toml").read_text(encoding="utf-8") == PROFILE_TOML


def test_profile_store_rejects_overwrite_without_opt_in(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path)
    store.save_profile_toml("visual-profile", PROFILE_TOML)

    with pytest.raises(ConfigError, match="refusing to overwrite"):
        store.save_profile_toml("visual-profile", UPDATED_PROFILE_TOML)

    profile = store.save_profile_toml("visual-profile", UPDATED_PROFILE_TOML, overwrite=True)

    assert profile.professional_experience == "mid-career analysts"


def test_profile_store_imports_validated_profile_file(tmp_path: Path) -> None:
    source = tmp_path / "incoming-profile.toml"
    source.write_text(PROFILE_TOML, encoding="utf-8")
    store = ProfileStore(tmp_path / "workspace")

    profile = store.import_profile("visual-profile", source)

    assert profile.id == "visual-profile"
    assert store.load_profile("visual-profile").learning_preferences.preferred_visual_aids == (
        "flowcharts",
        "concept maps",
    )


def test_profile_store_rejects_id_mismatch(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path)

    with pytest.raises(ConfigError, match="profile id mismatch"):
        store.save_profile_toml("different-id", PROFILE_TOML)


def test_profile_store_rejects_path_traversal_ids(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path)

    with pytest.raises(ConfigError, match="profile id must match"):
        store.save_profile_toml("../escape", PROFILE_TOML)

    with pytest.raises(ConfigError, match="topic id must match"):
        store.attach_profile_to_topic("visual-profile", "../escape")


def test_profile_store_attaches_snapshot_to_topic_run(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path)
    store.save_profile_toml("visual-profile", PROFILE_TOML)

    attachment = store.attach_profile_to_topic("visual-profile", "systems-thinking")

    assert attachment.profile_id == "visual-profile"
    assert attachment.topic_id == "systems-thinking"
    assert attachment.source_path == tmp_path / "profiles" / "visual-profile.toml"
    assert attachment.snapshot_path == tmp_path / "runs" / "systems-thinking" / "inputs" / "profile.toml"
    assert attachment.profile.professional_experience == "early-career analysts"
    assert attachment.snapshot_path.read_text(encoding="utf-8") == PROFILE_TOML


def test_profile_store_attached_snapshot_is_reproducible_after_profile_changes(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path)
    store.save_profile_toml("visual-profile", PROFILE_TOML)
    store.attach_profile_to_topic("visual-profile", "systems-thinking")

    store.save_profile_toml("visual-profile", UPDATED_PROFILE_TOML, overwrite=True)

    snapshot = store.load_topic_profile_snapshot("systems-thinking")
    current = store.load_profile("visual-profile")

    assert snapshot.professional_experience == "early-career analysts"
    assert current.professional_experience == "mid-career analysts"


def test_profile_store_rejects_snapshot_overwrite_without_opt_in(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path)
    store.save_profile_toml("visual-profile", PROFILE_TOML)
    store.attach_profile_to_topic("visual-profile", "systems-thinking")

    with pytest.raises(ConfigError, match="refusing to overwrite"):
        store.attach_profile_to_topic("visual-profile", "systems-thinking")

    attachment = store.attach_profile_to_topic(
        "visual-profile",
        "systems-thinking",
        overwrite=True,
    )

    assert attachment.profile.id == "visual-profile"
