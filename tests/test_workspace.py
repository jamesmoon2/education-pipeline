import hashlib
from pathlib import Path
import threading

import pytest

from conftest import symlink_or_skip
from education_pipeline import ConfigError, ProfileStore, TopicStore
from education_pipeline.privacy import canonical_profile_toml_bytes
from education_pipeline.workspace import ProfileRecord, ProfileWriteConflict, _profile_lock


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


PLANTED_SECRET = "PLANTED-WORKSPACE-SECRET-937"


def test_profile_store_saves_lists_and_loads_profiles(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path)

    profile = store.save_profile_toml("visual-profile", PROFILE_TOML)

    assert profile.id == "visual-profile"
    assert store.list_profile_ids() == ("visual-profile",)
    assert store.load_profile("visual-profile").professional_experience == "early-career analysts"
    canonical = canonical_profile_toml_bytes(profile)
    assert store.read_profile_toml("visual-profile").encode("utf-8") == canonical
    assert (tmp_path / "profiles" / "visual-profile.toml").read_bytes() == canonical


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
    assert store.profile_path("visual-profile").read_bytes() == canonical_profile_toml_bytes(profile)


def test_profile_store_creates_canonical_record(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path)

    record = store.create_profile(
        "visual-profile",
        {
            "privacy": {
                "publishable_summary": "Early-career team learning systems thinking.",
                "include_in_published_output": False,
                "private_by_default": True,
            },
            "target_learner": "team cohort",
            "id": "visual-profile",
            "schema_version": 1,
        },
    )

    assert isinstance(record, ProfileRecord)
    assert record.profile.id == "visual-profile"
    assert record.canonical_bytes == canonical_profile_toml_bytes(record.profile)
    assert record.content_sha256 == hashlib.sha256(record.canonical_bytes).hexdigest()
    assert store.profile_path("visual-profile").read_bytes() == record.canonical_bytes


def test_profile_store_compare_and_swap_update_and_stale_hash(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path)
    created = store.create_profile("visual-profile", _profile_mapping(PROFILE_TOML))

    updated = store.update_profile(
        "visual-profile",
        _profile_mapping(UPDATED_PROFILE_TOML),
        base_sha256=created.content_sha256,
    )

    assert updated.profile.professional_experience == "mid-career analysts"
    assert updated.content_sha256 != created.content_sha256
    with pytest.raises(ProfileWriteConflict) as caught:
        store.update_profile(
            "visual-profile",
            _profile_mapping(PROFILE_TOML),
            base_sha256=created.content_sha256,
        )
    assert caught.value.current_sha256 == updated.content_sha256
    assert str(caught.value) == "profile write conflict"
    assert store.read_profile_record("visual-profile") == updated


def test_profile_store_create_and_duplicate_collisions_are_safe(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path)
    source = store.create_profile("visual-profile", _profile_mapping(PROFILE_TOML))

    with pytest.raises(ProfileWriteConflict) as create_conflict:
        store.create_profile("visual-profile", _profile_mapping(PROFILE_TOML))
    assert create_conflict.value.current_sha256 == source.content_sha256

    duplicate = store.duplicate_profile("visual-profile", "copied-profile")

    assert duplicate.profile.id == "copied-profile"
    assert duplicate.canonical_bytes != source.canonical_bytes
    assert store.load_profile("copied-profile").id == "copied-profile"
    with pytest.raises(ProfileWriteConflict) as duplicate_conflict:
        store.duplicate_profile("visual-profile", "copied-profile")
    assert duplicate_conflict.value.current_sha256 == duplicate.content_sha256


def test_profile_store_create_collision_redacts_malformed_existing_bytes(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path)
    store.profiles_dir.mkdir(parents=True)
    store.profile_path("visual-profile").write_text(
        f'id = "{PLANTED_SECRET}"\ntarget_learner = ',
        encoding="utf-8",
    )

    with pytest.raises(ProfileWriteConflict) as caught:
        store.create_profile("visual-profile", _profile_mapping(PROFILE_TOML))

    assert caught.value.current_sha256 is None
    assert str(caught.value) == "profile write conflict"
    assert PLANTED_SECRET not in str(caught.value)
    assert PLANTED_SECRET not in repr(caught.value)


def test_profile_store_duplicate_collision_redacts_mismatched_existing_id(
    tmp_path: Path,
) -> None:
    store = ProfileStore(tmp_path)
    store.create_profile("visual-profile", _profile_mapping(PROFILE_TOML))
    store.profiles_dir.mkdir(parents=True, exist_ok=True)
    target = store.profile_path("copied-profile")
    target.write_text(
        PROFILE_TOML.replace('id = "visual-profile"', f'id = "{PLANTED_SECRET}"'),
        encoding="utf-8",
    )

    with pytest.raises(ProfileWriteConflict) as caught:
        store.duplicate_profile("visual-profile", "copied-profile")

    assert caught.value.current_sha256 is None
    assert str(caught.value) == "profile write conflict"
    assert PLANTED_SECRET not in str(caught.value)
    assert PLANTED_SECRET not in repr(caught.value)


def test_profile_store_failed_atomic_replace_preserves_old_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from education_pipeline import workspace

    store = ProfileStore(tmp_path)
    created = store.create_profile("visual-profile", _profile_mapping(PROFILE_TOML))
    original = store.profile_path("visual-profile").read_bytes()

    def fail_replace(source: Path, target: Path) -> None:
        raise OSError("simulated replacement failure")

    monkeypatch.setattr(workspace.os, "replace", fail_replace)

    with pytest.raises(OSError, match="simulated replacement failure"):
        store.update_profile(
            "visual-profile",
            _profile_mapping(UPDATED_PROFILE_TOML),
            base_sha256=created.content_sha256,
        )

    assert store.profile_path("visual-profile").read_bytes() == original
    assert not tuple(store.profiles_dir.glob(".*.tmp"))


def test_profile_store_reads_legacy_toml_without_rewriting(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path)
    legacy_bytes = PROFILE_TOML.encode("utf-8")
    store.profiles_dir.mkdir(parents=True)
    store.profile_path("visual-profile").write_bytes(legacy_bytes)

    record = store.read_profile_record("visual-profile")

    assert record.canonical_bytes == canonical_profile_toml_bytes(record.profile)
    assert record.content_sha256 == hashlib.sha256(record.canonical_bytes).hexdigest()
    assert store.profile_path("visual-profile").read_bytes() == legacy_bytes


def test_profile_store_counts_matching_attached_snapshots(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path)
    store.save_profile_toml("visual-profile", PROFILE_TOML)
    store.attach_profile_to_topic("visual-profile", "topic-a")
    store.attach_profile_to_topic("visual-profile", "topic-b")
    other = PROFILE_TOML.replace('id = "visual-profile"', 'id = "other-profile"')
    other_path = store.topic_profile_snapshot_path("topic-c")
    other_path.parent.mkdir(parents=True)
    other_path.write_text(other, encoding="utf-8")

    assert store.profile_attachment_count("visual-profile") == 2
    assert store.profile_attachment_count("other-profile") == 1


def test_profile_store_concurrent_stale_writer_allows_one_update(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path)
    created = store.create_profile("visual-profile", _profile_mapping(PROFILE_TOML))
    barrier = threading.Barrier(3)
    results: list[ProfileRecord | ProfileWriteConflict] = []
    results_lock = threading.Lock()

    def update(professional_experience: str) -> None:
        candidate = _profile_mapping(UPDATED_PROFILE_TOML)
        candidate["professional_experience"] = professional_experience
        barrier.wait(timeout=5)
        try:
            result: ProfileRecord | ProfileWriteConflict = store.update_profile(
                "visual-profile",
                candidate,
                base_sha256=created.content_sha256,
            )
        except ProfileWriteConflict as exc:
            result = exc
        with results_lock:
            results.append(result)

    writers = [
        threading.Thread(target=update, args=("writer one",)),
        threading.Thread(target=update, args=("writer two",)),
    ]
    for writer in writers:
        writer.start()
    barrier.wait(timeout=5)
    for writer in writers:
        writer.join(timeout=5)
    assert all(not writer.is_alive() for writer in writers)

    successes = [result for result in results if isinstance(result, ProfileRecord)]
    conflicts = [result for result in results if isinstance(result, ProfileWriteConflict)]
    assert len(successes) == 1
    assert len(conflicts) == 1
    assert conflicts[0].current_sha256 == successes[0].content_sha256
    assert store.read_profile_record("visual-profile") == successes[0]


def test_profile_store_alias_paths_share_lock_and_allow_one_stale_writer(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    direct = ProfileStore(workspace)
    created = direct.create_profile("visual-profile", _profile_mapping(PROFILE_TOML))
    alias_parent = tmp_path / "alias-parent"
    alias_parent.mkdir()
    dotdot = ProfileStore(alias_parent / ".." / "workspace")
    symlink_root = tmp_path / "workspace-link"
    symlink_or_skip(symlink_root, workspace, target_is_directory=True)
    symlinked = ProfileStore(symlink_root)

    locks = [
        _profile_lock(store.profile_path("visual-profile"))
        for store in (direct, dotdot, symlinked)
    ]
    assert locks[0] is locks[1] is locks[2]

    barrier = threading.Barrier(4)
    results: list[ProfileRecord | ProfileWriteConflict | BaseException] = []
    results_lock = threading.Lock()

    def update(store: ProfileStore, professional_experience: str) -> None:
        candidate = _profile_mapping(UPDATED_PROFILE_TOML)
        candidate["professional_experience"] = professional_experience
        try:
            barrier.wait(timeout=5)
            result: ProfileRecord | ProfileWriteConflict | BaseException = store.update_profile(
                "visual-profile",
                candidate,
                base_sha256=created.content_sha256,
            )
        except BaseException as exc:
            result = exc
        with results_lock:
            results.append(result)

    writers = [
        threading.Thread(target=update, args=(store, f"alias writer {index}"))
        for index, store in enumerate((direct, dotdot, symlinked), start=1)
    ]
    for writer in writers:
        writer.start()
    barrier.wait(timeout=5)
    for writer in writers:
        writer.join(timeout=5)
    assert all(not writer.is_alive() for writer in writers)

    successes = [result for result in results if isinstance(result, ProfileRecord)]
    conflicts = [result for result in results if isinstance(result, ProfileWriteConflict)]
    unexpected = [
        result
        for result in results
        if not isinstance(result, (ProfileRecord, ProfileWriteConflict))
    ]
    assert unexpected == []
    assert len(successes) == 1
    assert len(conflicts) == 2
    assert {conflict.current_sha256 for conflict in conflicts} == {
        successes[0].content_sha256
    }


def test_profile_store_rejects_id_mismatch(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path)

    mismatched = PROFILE_TOML.replace('id = "visual-profile"', f'id = "{PLANTED_SECRET}"')
    with pytest.raises(ConfigError, match="profile id mismatch") as caught:
        store.save_profile_toml("different-id", mismatched)
    assert PLANTED_SECRET not in str(caught.value)
    assert "different-id" not in str(caught.value)


def test_profile_store_read_and_update_id_mismatch_are_redacted(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path)
    store.profiles_dir.mkdir(parents=True)
    mismatched = PROFILE_TOML.replace('id = "visual-profile"', f'id = "{PLANTED_SECRET}"')
    store.profile_path("visual-profile").write_text(mismatched, encoding="utf-8")

    with pytest.raises(ConfigError, match="profile id mismatch") as read_error:
        store.read_profile_record("visual-profile")
    with pytest.raises(ConfigError, match="profile id mismatch") as update_error:
        store.update_profile(
            "visual-profile",
            _profile_mapping(UPDATED_PROFILE_TOML),
            base_sha256="0" * 64,
        )

    for error in (read_error.value, update_error.value):
        assert str(error) == "profile id mismatch with artifact path"
        assert PLANTED_SECRET not in str(error)
        assert "visual-profile" not in str(error)


def test_profile_store_rejects_path_traversal_ids(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path)
    invalid_profile_id = f"../{PLANTED_SECRET}"
    invalid_topic_id = f"../{PLANTED_SECRET}-TOPIC"

    with pytest.raises(ConfigError, match="profile id must match") as profile_error:
        store.save_profile_toml(invalid_profile_id, PROFILE_TOML)

    with pytest.raises(ConfigError, match="topic id must match") as topic_error:
        store.attach_profile_to_topic("visual-profile", invalid_topic_id)

    assert invalid_profile_id not in str(profile_error.value)
    assert PLANTED_SECRET not in str(profile_error.value)
    assert invalid_topic_id not in str(topic_error.value)
    assert PLANTED_SECRET not in str(topic_error.value)


def test_topic_store_id_mismatch_is_redacted(tmp_path: Path) -> None:
    store = TopicStore(tmp_path)
    topic_toml = f'id = "{PLANTED_SECRET}"\ntitle = "Private title"\n'

    with pytest.raises(ConfigError, match="topic id mismatch") as caught:
        store.save_topic_toml("public-topic", topic_toml)

    assert str(caught.value) == "topic id mismatch with artifact path"
    assert PLANTED_SECRET not in str(caught.value)
    assert "public-topic" not in str(caught.value)


def test_profile_store_attaches_snapshot_to_topic_run(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path)
    store.save_profile_toml("visual-profile", PROFILE_TOML)

    attachment = store.attach_profile_to_topic("visual-profile", "systems-thinking")

    assert attachment.profile_id == "visual-profile"
    assert attachment.topic_id == "systems-thinking"
    assert attachment.source_path == tmp_path / "profiles" / "visual-profile.toml"
    assert attachment.snapshot_path == tmp_path / "runs" / "systems-thinking" / "inputs" / "profile.toml"
    assert attachment.profile.professional_experience == "early-career analysts"
    assert attachment.snapshot_path.read_bytes() == attachment.source_path.read_bytes()


def test_profile_store_snapshots_exact_legacy_source_bytes(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path)
    source_bytes = PROFILE_TOML.encode("utf-8")
    store.profiles_dir.mkdir(parents=True)
    store.profile_path("visual-profile").write_bytes(source_bytes)

    attachment = store.attach_profile_to_topic("visual-profile", "systems-thinking")

    assert attachment.snapshot_path.read_bytes() == source_bytes


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


def _profile_mapping(toml_text: str) -> dict:
    import tomllib

    return tomllib.loads(toml_text)


# ---------------------------------------------------------------------------
# validate_workspace / fix_workspace (first-run milestone, spec §3.3)


class TestValidateWorkspace:
    def _codes(self, findings):
        return sorted(f.code for f in findings)

    def test_empty_directory_reports_missing_subdirs_only(self, tmp_path: Path) -> None:
        from education_pipeline.workspace import validate_workspace

        findings = validate_workspace(tmp_path)
        assert self._codes(findings) == ["missing_subdir"] * 3
        assert all(f.severity == "blocking" for f in findings)
        assert all(f.auto_fixable for f in findings)
        messages = " ".join(f.message for f in findings)
        for subdir in ("runs", "topics", "profiles"):
            assert subdir in messages

    def test_nonexistent_directory_is_scaffoldable(self, tmp_path: Path) -> None:
        from education_pipeline.workspace import validate_workspace

        findings = validate_workspace(tmp_path / "new-ws")
        assert self._codes(findings) == ["missing_subdir"] * 3
        assert all(f.auto_fixable for f in findings)

    def test_complete_workspace_has_no_findings(self, tmp_path: Path) -> None:
        from education_pipeline.workspace import validate_workspace

        for subdir in ("runs", "topics", "profiles"):
            (tmp_path / subdir).mkdir()
        assert validate_workspace(tmp_path) == []

    def test_partial_workspace_reports_only_missing_subdirs(self, tmp_path: Path) -> None:
        from education_pipeline.workspace import validate_workspace

        (tmp_path / "topics").mkdir()
        findings = validate_workspace(tmp_path)
        assert self._codes(findings) == ["missing_subdir", "missing_subdir"]
        messages = " ".join(f.message for f in findings)
        assert "runs" in messages and "profiles" in messages

    def test_path_is_file_is_blocking(self, tmp_path: Path) -> None:
        from education_pipeline.workspace import validate_workspace

        target = tmp_path / "not-a-dir"
        target.write_text("hello", encoding="utf-8")
        findings = validate_workspace(target)
        assert self._codes(findings) == ["path_is_file"]
        assert findings[0].severity == "blocking"
        assert not findings[0].auto_fixable

    def test_unrecognized_layout_blocks_scaffolding(self, tmp_path: Path) -> None:
        from education_pipeline.workspace import validate_workspace

        (tmp_path / "photos").mkdir()
        (tmp_path / "notes.txt").write_text("hi", encoding="utf-8")
        findings = validate_workspace(tmp_path)
        assert self._codes(findings) == ["unrecognized_layout"]
        assert findings[0].severity == "blocking"
        assert not findings[0].auto_fixable

    def test_workspace_marker_beats_unrecognized_layout(self, tmp_path: Path) -> None:
        from education_pipeline.workspace import validate_workspace

        (tmp_path / "photos").mkdir()
        (tmp_path / "topics").mkdir()
        findings = validate_workspace(tmp_path)
        assert self._codes(findings) == ["missing_subdir", "missing_subdir"]

    def test_discovery_dir_counts_as_workspace_marker(self, tmp_path: Path) -> None:
        from education_pipeline.workspace import validate_workspace

        (tmp_path / ".education-pipeline").mkdir()
        (tmp_path / "unrelated.txt").write_text("x", encoding="utf-8")
        findings = validate_workspace(tmp_path)
        assert self._codes(findings) == ["missing_subdir"] * 3

    def test_not_writable_is_blocking(self, tmp_path: Path) -> None:
        import os

        from education_pipeline.workspace import validate_workspace

        if os.name == "nt":
            # chmod cannot make a directory unwritable on Windows (and
            # os.geteuid does not exist there).
            pytest.skip("POSIX directory modes")
        if os.geteuid() == 0:
            pytest.skip("permission checks are meaningless as root")
        target = tmp_path / "readonly"
        for subdir in ("runs", "topics", "profiles"):
            (target / subdir).mkdir(parents=True)
        target.chmod(0o500)
        try:
            findings = validate_workspace(target)
        finally:
            target.chmod(0o700)
        assert self._codes(findings) == ["not_writable"]
        assert findings[0].severity == "blocking"
        assert not findings[0].auto_fixable

    def test_stale_daemon_record_is_warning(self, tmp_path: Path) -> None:
        from education_pipeline.daemon import lifecycle
        from education_pipeline.workspace import validate_workspace

        for subdir in ("runs", "topics", "profiles"):
            (tmp_path / subdir).mkdir()
        lifecycle.write_discovery(
            tmp_path, pid=999_999_999, port=1, token="t", version="0"
        )
        findings = validate_workspace(tmp_path)
        assert self._codes(findings) == ["stale_daemon_record"]
        assert findings[0].severity == "warning"
        assert findings[0].auto_fixable

    def test_live_daemon_record_is_not_stale(self, tmp_path: Path) -> None:
        import os

        from education_pipeline.daemon import lifecycle
        from education_pipeline.workspace import validate_workspace

        for subdir in ("runs", "topics", "profiles"):
            (tmp_path / subdir).mkdir()
        lifecycle.write_discovery(
            tmp_path, pid=os.getpid(), port=1, token="t", version="0"
        )
        assert validate_workspace(tmp_path) == []

    def test_unparseable_daemon_record_is_stale(self, tmp_path: Path) -> None:
        from education_pipeline.workspace import validate_workspace

        for subdir in ("runs", "topics", "profiles"):
            (tmp_path / subdir).mkdir()
        record = tmp_path / ".education-pipeline" / "daemon.json"
        record.parent.mkdir()
        record.write_text("{corrupt", encoding="utf-8")
        findings = validate_workspace(tmp_path)
        assert self._codes(findings) == ["stale_daemon_record"]

    def test_findings_carry_remediation_text(self, tmp_path: Path) -> None:
        from education_pipeline.workspace import validate_workspace

        findings = validate_workspace(tmp_path)
        assert all(f.remediation for f in findings)


class TestFixWorkspace:
    def test_fix_scaffolds_missing_subdirs(self, tmp_path: Path) -> None:
        from education_pipeline.workspace import fix_workspace

        remaining = fix_workspace(tmp_path / "fresh")
        assert remaining == []
        for subdir in ("runs", "topics", "profiles"):
            assert (tmp_path / "fresh" / subdir).is_dir()

    def test_fix_removes_stale_daemon_record(self, tmp_path: Path) -> None:
        from education_pipeline.daemon import lifecycle
        from education_pipeline.workspace import fix_workspace

        for subdir in ("runs", "topics", "profiles"):
            (tmp_path / subdir).mkdir()
        lifecycle.write_discovery(
            tmp_path, pid=999_999_999, port=1, token="t", version="0"
        )
        assert fix_workspace(tmp_path) == []
        assert not lifecycle.discovery_path(tmp_path).exists()

    def test_fix_never_scaffolds_into_unrecognized_layout(self, tmp_path: Path) -> None:
        from education_pipeline.workspace import fix_workspace

        (tmp_path / "photos").mkdir()
        remaining = fix_workspace(tmp_path)
        assert [f.code for f in remaining] == ["unrecognized_layout"]
        assert not (tmp_path / "runs").exists()

    def test_fix_leaves_non_fixable_findings(self, tmp_path: Path) -> None:
        from education_pipeline.workspace import fix_workspace

        target = tmp_path / "not-a-dir"
        target.write_text("hello", encoding="utf-8")
        remaining = fix_workspace(target)
        assert [f.code for f in remaining] == ["path_is_file"]
        assert target.is_file()
