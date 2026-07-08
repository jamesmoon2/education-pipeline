"""Workspace-local storage for learner profile artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import tomllib

from education_pipeline.config import ConfigError
from education_pipeline.profiles import LearnerProfile, load_learner_profile, parse_learner_profile
from education_pipeline.topics import Topic, load_topic, parse_topic


_ARTIFACT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


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
        return load_learner_profile(self.profile_path(profile_id))

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

        path = self.profile_path(safe_id)
        _write_text(path, toml_text, overwrite=overwrite)
        return profile

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
        try:
            toml_text = source_path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise ConfigError(f"learner profile file not found: {source_path}") from exc

        profile = _parse_profile_toml(toml_text, f"profile {safe_profile_id!r}")
        _require_matching_profile_id(profile, safe_profile_id)

        snapshot_path = self.topic_profile_snapshot_path(safe_topic_id)
        _write_text(snapshot_path, toml_text, overwrite=overwrite)
        snapshot_profile = load_learner_profile(snapshot_path)
        return ProfileAttachment(
            profile_id=safe_profile_id,
            topic_id=safe_topic_id,
            source_path=source_path,
            snapshot_path=snapshot_path,
            profile=snapshot_profile,
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
            raise ConfigError(
                f"topic id mismatch: artifact is {safe_id!r} but topic defines {topic.id!r}"
            )

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


def _parse_topic_toml(toml_text: str, context: str) -> Topic:
    try:
        data = tomllib.loads(toml_text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"invalid TOML in {context}: {exc}") from exc
    return parse_topic(data)


def _require_matching_profile_id(profile: LearnerProfile, expected_id: str) -> None:
    if profile.id != expected_id:
        raise ConfigError(
            f"profile id mismatch: artifact is {expected_id!r} but profile defines {profile.id!r}"
        )


def _write_text(path: Path, text: str, *, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise ConfigError(f"refusing to overwrite existing file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _artifact_id(value: str, context: str) -> str:
    if not _is_artifact_id(value):
        raise ConfigError(
            f"{context} must match {_ARTIFACT_ID_PATTERN.pattern!r}; got {value!r}"
        )
    return value


def _is_artifact_id(value: str) -> bool:
    return isinstance(value, str) and _ARTIFACT_ID_PATTERN.fullmatch(value) is not None
