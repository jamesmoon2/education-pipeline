"""Workspace-local run directories, prompt files, and manifest logging."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import json
import re

from education_pipeline.config import ConfigError
from education_pipeline.prompts import PromptArtifact, SpecPromptInput, compile_spec_prompt
from education_pipeline.workspace import ProfileStore


MANIFEST_SCHEMA_VERSION = 1

RUN_SUBDIRS = ("inputs", "prompts", "responses", "approved", "reports", "final")

#: Stages this writer can currently compile prompts for. Outline, draft, QA,
#: repair, finalize, and export are intentionally omitted until their prompt
#: compilers exist.
SUPPORTED_STAGES = ("spec",)

_PROMPT_SUFFIX = ".prompt.md"
_RESPONSE_SUFFIX = ".response.md"
_STUB_SUFFIX = ".SAVE_RESPONSE_HERE.md"

_ARTIFACT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


@dataclass(frozen=True)
class StagePaths:
    """Filesystem locations for a single stage within a topic run."""

    stage: str
    topic_id: str
    prompt_path: Path
    response_path: Path
    stub_path: Path


@dataclass(frozen=True)
class PromptFile:
    """The result of writing a compiled stage prompt to a topic run."""

    stage: str
    topic_id: str
    prompt_path: Path
    response_path: Path
    stub_path: Path
    artifact: PromptArtifact


@dataclass(frozen=True)
class RunStore:
    """Create run directories and write stage prompt/response artifacts."""

    root: Path

    def __init__(self, root: str | Path) -> None:
        object.__setattr__(self, "root", Path(root))

    @property
    def runs_dir(self) -> Path:
        return self.root / "runs"

    def run_dir(self, topic_id: str) -> Path:
        safe_id = _artifact_id(topic_id, "topic id")
        return self.runs_dir / safe_id

    def manifest_path(self, topic_id: str) -> Path:
        return self.run_dir(topic_id) / "manifest.json"

    def stage_paths(self, topic_id: str, stage: str) -> StagePaths:
        safe_id = _artifact_id(topic_id, "topic id")
        safe_stage = _supported_stage(stage)
        run = self.runs_dir / safe_id
        return StagePaths(
            stage=safe_stage,
            topic_id=safe_id,
            prompt_path=run / "prompts" / f"{safe_stage}{_PROMPT_SUFFIX}",
            response_path=run / "responses" / f"{safe_stage}{_RESPONSE_SUFFIX}",
            stub_path=run / "responses" / f"{safe_stage}{_STUB_SUFFIX}",
        )

    def response_path(self, topic_id: str, stage: str) -> Path:
        return self.stage_paths(topic_id, stage).response_path

    def create_run(self, topic_id: str) -> Path:
        """Create the run directory tree and initialize an empty manifest."""

        run = self.run_dir(topic_id)
        for subdir in RUN_SUBDIRS:
            (run / subdir).mkdir(parents=True, exist_ok=True)

        manifest_path = run / "manifest.json"
        if not manifest_path.exists():
            _write_manifest(
                manifest_path,
                {
                    "schema_version": MANIFEST_SCHEMA_VERSION,
                    "topic_id": run.name,
                    "events": [],
                },
            )
        return run

    def read_manifest(self, topic_id: str) -> dict:
        path = self.manifest_path(topic_id)
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ConfigError(f"run manifest not found: {path}") from exc

    def has_ingested_response(self, topic_id: str, stage: str) -> bool:
        """Return True only when a real (non-stub) response file is present."""

        return self.stage_paths(topic_id, stage).response_path.exists()

    def write_spec_prompt(
        self,
        topic_id: str,
        *,
        title: str,
        topic_brief: str | None = None,
        overwrite: bool = False,
    ) -> PromptFile:
        """Compile and write the spec-stage prompt for a topic run.

        Uses the topic's attached learner profile snapshot when one exists,
        otherwise compiles with broadly accessible defaults.
        """

        safe_id = _artifact_id(topic_id, "topic id")
        profile = self._load_attached_profile(safe_id)
        artifact = compile_spec_prompt(
            SpecPromptInput(
                topic_id=safe_id,
                title=title,
                topic_brief=topic_brief,
                profile=profile,
            )
        )
        return self._write_prompt(artifact, overwrite=overwrite)

    def _write_prompt(self, artifact: PromptArtifact, *, overwrite: bool) -> PromptFile:
        paths = self.stage_paths(artifact.topic_id, artifact.stage)
        self.create_run(artifact.topic_id)

        _write_text(paths.prompt_path, artifact.text, overwrite=overwrite)
        if not paths.response_path.exists():
            _write_text(paths.stub_path, _stub_text(paths), overwrite=True)

        self._append_event(
            artifact.topic_id,
            stage=paths.stage,
            action="prompt_written",
            prompt_path=paths.prompt_path,
            response_path=paths.response_path,
        )
        return PromptFile(
            stage=paths.stage,
            topic_id=paths.topic_id,
            prompt_path=paths.prompt_path,
            response_path=paths.response_path,
            stub_path=paths.stub_path,
            artifact=artifact,
        )

    def _load_attached_profile(self, topic_id: str):
        snapshot_path = ProfileStore(self.root).topic_profile_snapshot_path(topic_id)
        if not snapshot_path.exists():
            return None
        return ProfileStore(self.root).load_topic_profile_snapshot(topic_id)

    def _append_event(
        self,
        topic_id: str,
        *,
        stage: str,
        action: str,
        prompt_path: Path,
        response_path: Path,
    ) -> None:
        run = self.run_dir(topic_id)
        manifest = self.read_manifest(topic_id)
        manifest.setdefault("events", []).append(
            {
                "stage": stage,
                "action": action,
                "prompt_file": _relative_to(prompt_path, run),
                "response_file": _relative_to(response_path, run),
                "recorded_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        _write_manifest(run / "manifest.json", manifest)


def _stub_text(paths: StagePaths) -> str:
    return (
        f"# Response placeholder for the {paths.stage} stage\n"
        "\n"
        "No model response has been saved for this stage yet.\n"
        "Save the response as a sibling file named:\n"
        "\n"
        f"    {paths.response_path.name}\n"
        "\n"
        "This placeholder is ignored by the pipeline and does not count as an\n"
        "ingested response. Delete it once the real response is in place.\n"
    )


def _relative_to(path: Path, run: Path) -> str:
    return path.relative_to(run).as_posix()


def _write_manifest(path: Path, manifest: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str, *, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise ConfigError(f"refusing to overwrite existing file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _supported_stage(stage: str) -> str:
    if stage not in SUPPORTED_STAGES:
        known = ", ".join(SUPPORTED_STAGES)
        raise ConfigError(f"unsupported run stage {stage!r}; supported stages: {known}")
    return stage


def _artifact_id(value: str, context: str) -> str:
    if not isinstance(value, str) or _ARTIFACT_ID_PATTERN.fullmatch(value) is None:
        raise ConfigError(
            f"{context} must match {_ARTIFACT_ID_PATTERN.pattern!r}; got {value!r}"
        )
    return value
