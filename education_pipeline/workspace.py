"""Workspace-local storage for learner profile artifacts."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import tempfile
import threading
from typing import Any, Mapping
import tomllib

from education_pipeline.config import ConfigError
from education_pipeline.privacy import canonical_profile_toml_bytes, profile_to_dict
from education_pipeline.profiles import LearnerProfile, load_learner_profile, parse_learner_profile
from education_pipeline.topics import Topic, load_topic, parse_topic


_ARTIFACT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_PROFILE_LOCKS: dict[Path, threading.Lock] = {}
_PROFILE_LOCKS_GUARD = threading.Lock()

#: Subdirectories every workspace must contain.
WORKSPACE_SUBDIRS = ("runs", "topics", "profiles")

#: Any of these marks a directory as an (possibly incomplete) workspace.
_WORKSPACE_MARKERS = WORKSPACE_SUBDIRS + (".education-pipeline",)


@dataclass(frozen=True)
class WorkspaceFinding:
    """One structured setup-validation finding (spec §3.3).

    Mirrors the release-gates finding shape: severity, code, message, and
    remediation, plus whether ``fix_workspace`` can resolve it automatically.
    """

    code: str
    severity: str  # "blocking" | "warning"
    message: str
    remediation: str
    auto_fixable: bool = False


def validate_workspace(root: str | Path) -> list[WorkspaceFinding]:
    """Validate a directory as an education-pipeline workspace.

    Returns structured findings; an empty list means the workspace is ready.
    A nonexistent or empty directory is scaffoldable (``missing_subdir``
    findings only); a non-empty directory with no workspace marker is
    ``unrecognized_layout`` and is never scaffolded automatically.
    """

    from education_pipeline.daemon import lifecycle

    root = Path(root)
    if root.exists() and not root.is_dir():
        return [
            WorkspaceFinding(
                code="path_is_file",
                severity="blocking",
                message=f"{root} exists but is not a directory",
                remediation="choose a directory path for the workspace",
            )
        ]

    findings: list[WorkspaceFinding] = []
    if root.is_dir():
        if not os.access(root, os.W_OK):
            return [
                WorkspaceFinding(
                    code="not_writable",
                    severity="blocking",
                    message=f"workspace directory is not writable: {root}",
                    remediation="fix the directory permissions or choose another directory",
                )
            ]
        has_marker = any((root / marker).exists() for marker in _WORKSPACE_MARKERS)
        has_entries = any(root.iterdir())
        if has_entries and not has_marker:
            return [
                WorkspaceFinding(
                    code="unrecognized_layout",
                    severity="blocking",
                    message=(
                        f"{root} is not empty and does not look like a workspace"
                    ),
                    remediation=(
                        "confirm this directory explicitly before scaffolding "
                        "into it, or choose an empty directory"
                    ),
                )
            ]
    else:
        ancestor = root.parent
        while not ancestor.exists() and ancestor != ancestor.parent:
            ancestor = ancestor.parent
        if ancestor.is_dir() and not os.access(ancestor, os.W_OK):
            return [
                WorkspaceFinding(
                    code="not_writable",
                    severity="blocking",
                    message=f"cannot create workspace under read-only {ancestor}",
                    remediation="fix the directory permissions or choose another directory",
                )
            ]

    for subdir in WORKSPACE_SUBDIRS:
        if not (root / subdir).is_dir():
            findings.append(
                WorkspaceFinding(
                    code="missing_subdir",
                    severity="blocking",
                    message=f"missing workspace subdirectory: {subdir}/",
                    remediation=f"create {root / subdir} (auto-fixable)",
                    auto_fixable=True,
                )
            )

    if lifecycle.discovery_path(root).is_file():
        record = lifecycle.read_discovery(root)
        if record is None or lifecycle.is_stale(record):
            findings.append(
                WorkspaceFinding(
                    code="stale_daemon_record",
                    severity="warning",
                    message=(
                        "a stale daemon discovery record was left behind at "
                        f"{lifecycle.discovery_path(root)}"
                    ),
                    remediation="remove the stale daemon.json (auto-fixable)",
                    auto_fixable=True,
                )
            )
    return findings


def fix_workspace(root: str | Path) -> list[WorkspaceFinding]:
    """Apply the auto-fixable findings and return whatever remains.

    Scaffolds missing subdirectories and removes a stale daemon discovery
    record. Never scaffolds into an unrecognized non-empty directory --
    that requires explicit user confirmation (spec §3.3).
    """

    from education_pipeline.daemon import lifecycle

    root = Path(root)
    for finding in validate_workspace(root):
        if not finding.auto_fixable:
            continue
        if finding.code == "missing_subdir":
            for subdir in WORKSPACE_SUBDIRS:
                (root / subdir).mkdir(parents=True, exist_ok=True)
        elif finding.code == "stale_daemon_record":
            lifecycle.remove_discovery(root)
    return validate_workspace(root)


@dataclass(frozen=True)
class ProfileRecord:
    """A validated profile and its canonical persistence identity."""

    profile: LearnerProfile
    canonical_bytes: bytes
    content_sha256: str


class ProfileWriteConflict(ConfigError):
    """A safe compare-and-swap conflict that exposes no profile content."""

    def __init__(self, current_sha256: str | None) -> None:
        super().__init__("profile write conflict")
        self.current_sha256 = current_sha256


@dataclass(frozen=True)
class ProfileAttachment:
    """A profile snapshot attached to a topic run."""

    profile_id: str
    topic_id: str
    source_path: Path
    snapshot_path: Path
    profile: LearnerProfile


@dataclass(frozen=True)
class ProfileStore:
    """Read and write workspace-local learner profile artifacts."""

    root: Path

    def __init__(self, root: str | Path) -> None:
        object.__setattr__(self, "root", Path(root))

    @property
    def profiles_dir(self) -> Path:
        return self.root / "profiles"

    @property
    def runs_dir(self) -> Path:
        return self.root / "runs"

    def profile_path(self, profile_id: str) -> Path:
        safe_id = _artifact_id(profile_id, "profile id")
        return self.profiles_dir / f"{safe_id}.toml"

    def topic_profile_snapshot_path(self, topic_id: str) -> Path:
        safe_id = _artifact_id(topic_id, "topic id")
        return self.runs_dir / safe_id / "inputs" / "profile.toml"

    def topic_profile_snapshot_lock(self, topic_id: str) -> threading.Lock:
        """Return the lock coordinating one topic's attached profile snapshot.

        Readers that must derive several values from one attachment generation
        may hold this lock across those reads.  The lock is plain and
        non-reentrant; callers must not invoke ``attach_profile_to_topic``
        while holding it.
        """

        return _profile_lock(self.topic_profile_snapshot_path(topic_id))

    def list_profile_ids(self) -> tuple[str, ...]:
        if not self.profiles_dir.exists():
            return ()
        ids = [
            path.stem
            for path in self.profiles_dir.glob("*.toml")
            if path.is_file() and _is_artifact_id(path.stem)
        ]
        return tuple(sorted(ids))

    def load_profile(self, profile_id: str) -> LearnerProfile:
        return self.read_profile_record(profile_id).profile

    def read_profile_record(self, profile_id: str) -> ProfileRecord:
        safe_id = _artifact_id(profile_id, "profile id")
        path = self.profile_path(safe_id)
        source_bytes = _read_bytes(path, "learner profile file")
        profile = _parse_profile_bytes(source_bytes, f"profile {safe_id!r}")
        _require_matching_profile_id(profile, safe_id)
        return _profile_record(profile)

    def read_profile_toml(self, profile_id: str) -> str:
        path = self.profile_path(profile_id)
        try:
            return path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise ConfigError(f"learner profile file not found: {path}") from exc

    def save_profile_toml(
        self,
        profile_id: str,
        toml_text: str,
        *,
        overwrite: bool = False,
    ) -> LearnerProfile:
        safe_id = _artifact_id(profile_id, "profile id")
        profile = _parse_profile_toml(toml_text, f"profile {safe_id!r}")
        _require_matching_profile_id(profile, safe_id)
        if not overwrite:
            try:
                return self.create_profile(safe_id, profile).profile
            except ProfileWriteConflict as exc:
                raise ConfigError(
                    f"refusing to overwrite existing file: {self.profile_path(safe_id)}"
                ) from exc

        try:
            current = self.read_profile_record(safe_id)
        except ConfigError:
            if self.profile_path(safe_id).exists():
                raise
            return self.create_profile(safe_id, profile).profile
        return self.update_profile(
            safe_id,
            profile,
            base_sha256=current.content_sha256,
        ).profile

    def import_profile_toml(
        self,
        profile_id: str,
        toml_text: str,
        *,
        overwrite: bool = False,
    ) -> ProfileRecord:
        """Atomically import canonical TOML under one target lock."""

        safe_id = _artifact_id(profile_id, "profile id")
        profile = _parse_profile_toml(toml_text, f"profile {safe_id!r}")
        _require_matching_profile_id(profile, safe_id)
        candidate = _profile_record(profile)
        path = self.profile_path(safe_id)

        with _profile_lock(path):
            if path.exists() and not overwrite:
                try:
                    current_sha256 = self.read_profile_record(safe_id).content_sha256
                except ConfigError:
                    current_sha256 = None
                raise ProfileWriteConflict(current_sha256)
            _atomic_replace_bytes(path, candidate.canonical_bytes)
        return candidate

    def create_profile(
        self,
        profile_id: str,
        value: LearnerProfile | Mapping[str, Any],
    ) -> ProfileRecord:
        """Atomically create a canonical profile when the target is absent."""

        return self._write_profile(profile_id, value, base_sha256=None)

    def update_profile(
        self,
        profile_id: str,
        value: LearnerProfile | Mapping[str, Any],
        *,
        base_sha256: str,
    ) -> ProfileRecord:
        """Atomically replace a profile only when its canonical SHA matches."""

        if not isinstance(base_sha256, str) or not base_sha256:
            raise ConfigError("profile update requires a non-empty base_sha256")
        return self._write_profile(profile_id, value, base_sha256=base_sha256)

    def duplicate_profile(self, profile_id: str, new_id: str) -> ProfileRecord:
        """Create a canonical copy with a replaced embedded profile id."""

        source = self.read_profile_record(profile_id)
        duplicate = profile_to_dict(source.profile)
        duplicate["id"] = _artifact_id(new_id, "profile id")
        return self.create_profile(new_id, duplicate)

    def profile_attachment_count(self, profile_id: str) -> int:
        """Count valid run snapshots whose embedded id matches the profile."""

        safe_id = _artifact_id(profile_id, "profile id")
        if not self.runs_dir.exists():
            return 0
        count = 0
        for snapshot_path in self.runs_dir.glob("*/inputs/profile.toml"):
            if not snapshot_path.is_file():
                continue
            try:
                snapshot = load_learner_profile(snapshot_path)
            except ConfigError:
                continue
            if snapshot.id == safe_id:
                count += 1
        return count

    def _write_profile(
        self,
        profile_id: str,
        value: LearnerProfile | Mapping[str, Any],
        *,
        base_sha256: str | None,
    ) -> ProfileRecord:
        safe_id = _artifact_id(profile_id, "profile id")
        profile = value if isinstance(value, LearnerProfile) else parse_learner_profile(value)
        _require_matching_profile_id(profile, safe_id)
        candidate = _profile_record(profile)
        path = self.profile_path(safe_id)

        with _profile_lock(path):
            if path.exists():
                if base_sha256 is None:
                    try:
                        current_sha256 = self.read_profile_record(safe_id).content_sha256
                    except ConfigError:
                        current_sha256 = None
                    raise ProfileWriteConflict(current_sha256)
                current = self.read_profile_record(safe_id)
                if base_sha256 != current.content_sha256:
                    raise ProfileWriteConflict(current.content_sha256)
            elif base_sha256 is not None:
                raise ProfileWriteConflict(None)
            _atomic_replace_bytes(path, candidate.canonical_bytes)
        return candidate

    def import_profile(
        self,
        profile_id: str,
        source_path: str | Path,
        *,
        overwrite: bool = False,
    ) -> LearnerProfile:
        source = Path(source_path)
        try:
            toml_text = source.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise ConfigError(f"learner profile import file not found: {source}") from exc

        return self.save_profile_toml(profile_id, toml_text, overwrite=overwrite)

    def attach_profile_to_topic(
        self,
        profile_id: str,
        topic_id: str,
        *,
        overwrite: bool = False,
    ) -> ProfileAttachment:
        safe_profile_id = _artifact_id(profile_id, "profile id")
        safe_topic_id = _artifact_id(topic_id, "topic id")
        source_path = self.profile_path(safe_profile_id)
        source_bytes = _read_bytes(source_path, "learner profile file")
        profile = _parse_profile_bytes(source_bytes, f"profile {safe_profile_id!r}")
        _require_matching_profile_id(profile, safe_profile_id)

        snapshot_path = self.topic_profile_snapshot_path(safe_topic_id)
        with self.topic_profile_snapshot_lock(safe_topic_id):
            if snapshot_path.exists() and not overwrite:
                raise ConfigError(f"refusing to overwrite existing file: {snapshot_path}")
            _atomic_replace_bytes(snapshot_path, source_bytes)
        return ProfileAttachment(
            profile_id=safe_profile_id,
            topic_id=safe_topic_id,
            source_path=source_path,
            snapshot_path=snapshot_path,
            profile=profile,
        )

    def load_topic_profile_snapshot(self, topic_id: str) -> LearnerProfile:
        return load_learner_profile(self.topic_profile_snapshot_path(topic_id))


@dataclass(frozen=True)
class TopicStore:
    """Read and write workspace-local topic artifacts."""

    root: Path

    def __init__(self, root: str | Path) -> None:
        object.__setattr__(self, "root", Path(root))

    @property
    def topics_dir(self) -> Path:
        return self.root / "topics"

    def topic_path(self, topic_id: str) -> Path:
        safe_id = _artifact_id(topic_id, "topic id")
        return self.topics_dir / f"{safe_id}.toml"

    def list_topic_ids(self) -> tuple[str, ...]:
        if not self.topics_dir.exists():
            return ()
        ids = [
            path.stem
            for path in self.topics_dir.glob("*.toml")
            if path.is_file() and _is_artifact_id(path.stem)
        ]
        return tuple(sorted(ids))

    def load_topic(self, topic_id: str) -> Topic:
        return load_topic(self.topic_path(topic_id))

    def read_topic_toml(self, topic_id: str) -> str:
        path = self.topic_path(topic_id)
        try:
            return path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise ConfigError(f"topic file not found: {path}") from exc

    def save_topic_toml(
        self,
        topic_id: str,
        toml_text: str,
        *,
        overwrite: bool = False,
    ) -> Topic:
        safe_id = _artifact_id(topic_id, "topic id")
        topic = _parse_topic_toml(toml_text, f"topic {safe_id!r}")
        if topic.id != safe_id:
            raise ConfigError("topic id mismatch with artifact path")

        path = self.topic_path(safe_id)
        _write_text(path, toml_text, overwrite=overwrite)
        return topic

    def import_topic(
        self,
        topic_id: str,
        source_path: str | Path,
        *,
        overwrite: bool = False,
    ) -> Topic:
        source = Path(source_path)
        try:
            toml_text = source.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise ConfigError(f"topic import file not found: {source}") from exc

        return self.save_topic_toml(topic_id, toml_text, overwrite=overwrite)


def _parse_profile_toml(toml_text: str, context: str) -> LearnerProfile:
    try:
        data = tomllib.loads(toml_text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"invalid TOML in {context}: {exc}") from exc
    return parse_learner_profile(data)


def _parse_profile_bytes(source_bytes: bytes, context: str) -> LearnerProfile:
    try:
        toml_text = source_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ConfigError(f"invalid UTF-8 in {context}") from exc
    return _parse_profile_toml(toml_text, context)


def _parse_topic_toml(toml_text: str, context: str) -> Topic:
    try:
        data = tomllib.loads(toml_text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"invalid TOML in {context}: {exc}") from exc
    return parse_topic(data)


def _require_matching_profile_id(profile: LearnerProfile, expected_id: str) -> None:
    if profile.id != expected_id:
        raise ConfigError("profile id mismatch with artifact path")


def _write_text(path: Path, text: str, *, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise ConfigError(f"refusing to overwrite existing file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _read_bytes(path: Path, context: str) -> bytes:
    try:
        return path.read_bytes()
    except FileNotFoundError as exc:
        raise ConfigError(f"{context} not found: {path}") from exc


def _profile_record(profile: LearnerProfile) -> ProfileRecord:
    canonical_bytes = canonical_profile_toml_bytes(profile)
    return ProfileRecord(
        profile=profile,
        canonical_bytes=canonical_bytes,
        content_sha256=hashlib.sha256(canonical_bytes).hexdigest(),
    )


def _profile_lock(path: Path) -> threading.Lock:
    key = path.resolve(strict=False)
    with _PROFILE_LOCKS_GUARD:
        return _PROFILE_LOCKS.setdefault(key, threading.Lock())


def _atomic_replace_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def _artifact_id(value: str, context: str) -> str:
    if not _is_artifact_id(value):
        raise ConfigError(f"{context} must match required artifact-id format")
    return value


def _is_artifact_id(value: str) -> bool:
    return isinstance(value, str) and _ARTIFACT_ID_PATTERN.fullmatch(value) is not None
