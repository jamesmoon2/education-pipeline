"""Workspace-local run directories, prompt files, and manifest logging."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import json
import re

from education_pipeline.config import ConfigError
from education_pipeline.prompts import (
    PromptArtifact,
    SpecPromptInput,
    compile_draft_prompt,
    compile_outline_prompt,
    compile_qa_prompt,
    compile_repair_prompt,
    compile_spec_prompt,
    compile_topic_spec_prompt,
)
from education_pipeline.workspace import ProfileStore, TopicStore


MANIFEST_SCHEMA_VERSION = 1

RUN_SUBDIRS = ("inputs", "prompts", "responses", "approved", "reports", "final")

#: Stages this writer can currently compile prompts for. Finalize and export are
#: intentionally omitted until their prompt compilers exist.
SUPPORTED_STAGES = ("spec", "outline", "draft", "qa", "repair")

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
    approved_path: Path


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
class StageStatus:
    """Persisted progress for a single stage, derived from workspace files."""

    stage: str
    prompt_written: bool
    response_ingested: bool
    approved: bool

    @property
    def state(self) -> str:
        """The furthest milestone this stage has durably reached."""

        if self.approved:
            return "approved"
        if self.response_ingested:
            return "response_ingested"
        if self.prompt_written:
            return "prompt_written"
        return "pending"


@dataclass(frozen=True)
class NextAction:
    """The next step needed to move a run forward, for resuming work."""

    topic_id: str
    stage: str | None
    action: str
    detail: str


@dataclass(frozen=True)
class RunStatus:
    """A resumable snapshot of a run's progress across supported stages."""

    topic_id: str
    stages: tuple[StageStatus, ...]
    next_action: NextAction


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
            approved_path=run / "approved" / f"{safe_stage}.md",
        )

    def response_path(self, topic_id: str, stage: str) -> Path:
        return self.stage_paths(topic_id, stage).response_path

    def approved_path(self, topic_id: str, stage: str) -> Path:
        return self.stage_paths(topic_id, stage).approved_path

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

    def list_run_ids(self) -> tuple[str, ...]:
        """List topic ids that have a started run (an initialized manifest)."""

        if not self.runs_dir.exists():
            return ()
        ids = [
            path.name
            for path in self.runs_dir.iterdir()
            if path.is_dir()
            and _is_artifact_id(path.name)
            and (path / "manifest.json").is_file()
        ]
        return tuple(sorted(ids))

    def stage_status(self, topic_id: str, stage: str) -> StageStatus:
        """Report the persisted progress for one stage of a run."""

        paths = self.stage_paths(topic_id, stage)
        return StageStatus(
            stage=paths.stage,
            prompt_written=paths.prompt_path.exists(),
            response_ingested=paths.response_path.exists(),
            approved=paths.approved_path.exists(),
        )

    def run_status(self, topic_id: str) -> RunStatus:
        """Report a resumable snapshot of a run across all supported stages.

        Reads only the workspace filesystem, so a fresh session can recover
        exactly where earlier work left off without losing anything.
        """

        safe_id = _artifact_id(topic_id, "topic id")
        stages = tuple(self.stage_status(safe_id, stage) for stage in SUPPORTED_STAGES)
        return RunStatus(
            topic_id=safe_id,
            stages=stages,
            next_action=self._next_action(safe_id, stages),
        )

    def _next_action(self, topic_id: str, stages: tuple[StageStatus, ...]) -> NextAction:
        for status in stages:
            if status.approved:
                continue
            if not status.prompt_written:
                return NextAction(
                    topic_id=topic_id,
                    stage=status.stage,
                    action="write_prompt",
                    detail=f"Write the {status.stage} prompt for {topic_id!r}.",
                )
            if not status.response_ingested:
                response_path = self.stage_paths(topic_id, status.stage).response_path
                return NextAction(
                    topic_id=topic_id,
                    stage=status.stage,
                    action="save_response",
                    detail=(
                        f"Run the {status.stage} prompt and save the response to {response_path}."
                    ),
                )
            return NextAction(
                topic_id=topic_id,
                stage=status.stage,
                action="approve",
                detail=f"Review and approve the {status.stage} response for {topic_id!r}.",
            )
        return NextAction(
            topic_id=topic_id,
            stage=None,
            action="done",
            detail=f"All supported stages are approved for {topic_id!r}.",
        )

    def read_manifest(self, topic_id: str) -> dict:
        path = self.manifest_path(topic_id)
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ConfigError(f"run manifest not found: {path}") from exc

    def has_ingested_response(self, topic_id: str, stage: str) -> bool:
        """Return True only when a real (non-stub) response file is present."""

        return self.stage_paths(topic_id, stage).response_path.exists()

    def read_approved(self, topic_id: str, stage: str) -> str:
        """Read the approved output for a stage, raising if it is absent."""

        path = self.stage_paths(topic_id, stage).approved_path
        try:
            return path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise ConfigError(f"approved {stage} response not found: {path}") from exc

    def approve_stage(self, topic_id: str, stage: str, *, overwrite: bool = False) -> Path:
        """Promote a stage's ingested response into the ``approved`` directory.

        The approved copy is the canonical input for downstream stages. A stub
        placeholder never counts as an ingested response, so approving before a
        real response is saved raises.
        """

        paths = self.stage_paths(topic_id, stage)
        if not paths.response_path.exists():
            raise ConfigError(
                f"no ingested response to approve for stage {paths.stage!r}: {paths.response_path}"
            )

        text = paths.response_path.read_text(encoding="utf-8")
        _write_text(paths.approved_path, text, overwrite=overwrite)
        self._append_event(
            paths.topic_id,
            stage=paths.stage,
            action="response_approved",
            files={"prompt_file": paths.prompt_path, "approved_file": paths.approved_path},
        )
        return paths.approved_path

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

    def write_topic_spec_prompt(
        self,
        topic_id: str,
        *,
        overwrite: bool = False,
    ) -> PromptFile:
        """Compile and write the spec prompt from a stored topic artifact.

        Loads the topic from the workspace ``topics`` directory and reuses the
        topic's attached learner profile snapshot when one exists.
        """

        safe_id = _artifact_id(topic_id, "topic id")
        topic = TopicStore(self.root).load_topic(safe_id)
        profile = self._load_attached_profile(safe_id)
        artifact = compile_topic_spec_prompt(topic, profile)
        return self._write_prompt(artifact, overwrite=overwrite)

    def write_outline_prompt(
        self,
        topic_id: str,
        *,
        overwrite: bool = False,
    ) -> PromptFile:
        """Compile and write the outline prompt from the approved spec.

        Requires the spec stage to have been approved, and reuses the topic's
        attached learner profile snapshot when one exists.
        """

        safe_id = _artifact_id(topic_id, "topic id")
        topic = TopicStore(self.root).load_topic(safe_id)
        approved_spec = self.read_approved(safe_id, "spec")
        profile = self._load_attached_profile(safe_id)
        artifact = compile_outline_prompt(topic, approved_spec, profile)
        return self._write_prompt(artifact, overwrite=overwrite)

    def write_draft_prompt(
        self,
        topic_id: str,
        *,
        overwrite: bool = False,
    ) -> PromptFile:
        """Compile and write the draft prompt from the approved outline.

        Requires the outline stage to have been approved, and reuses the topic's
        attached learner profile snapshot when one exists.
        """

        safe_id = _artifact_id(topic_id, "topic id")
        topic = TopicStore(self.root).load_topic(safe_id)
        approved_outline = self.read_approved(safe_id, "outline")
        profile = self._load_attached_profile(safe_id)
        artifact = compile_draft_prompt(topic, approved_outline, profile)
        return self._write_prompt(artifact, overwrite=overwrite)

    def write_qa_prompt(
        self,
        topic_id: str,
        *,
        overwrite: bool = False,
    ) -> PromptFile:
        """Compile and write the QA prompt from the approved draft, spec, and outline.

        Requires the spec, outline, and draft stages to have been approved, and
        reuses the topic's attached learner profile snapshot when one exists.
        """

        safe_id = _artifact_id(topic_id, "topic id")
        topic = TopicStore(self.root).load_topic(safe_id)
        approved_spec = self.read_approved(safe_id, "spec")
        approved_outline = self.read_approved(safe_id, "outline")
        approved_draft = self.read_approved(safe_id, "draft")
        profile = self._load_attached_profile(safe_id)
        artifact = compile_qa_prompt(
            topic,
            approved_spec=approved_spec,
            approved_outline=approved_outline,
            approved_draft=approved_draft,
            profile=profile,
        )
        return self._write_prompt(artifact, overwrite=overwrite)

    def write_repair_prompt(
        self,
        topic_id: str,
        *,
        overwrite: bool = False,
    ) -> PromptFile:
        """Compile and write the repair prompt from the approved draft and QA findings.

        Requires the draft and QA stages to have been approved, and reuses the
        topic's attached learner profile snapshot when one exists.
        """

        safe_id = _artifact_id(topic_id, "topic id")
        topic = TopicStore(self.root).load_topic(safe_id)
        approved_draft = self.read_approved(safe_id, "draft")
        approved_qa = self.read_approved(safe_id, "qa")
        profile = self._load_attached_profile(safe_id)
        artifact = compile_repair_prompt(
            topic,
            approved_draft=approved_draft,
            approved_qa=approved_qa,
            profile=profile,
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
            files={"prompt_file": paths.prompt_path, "response_file": paths.response_path},
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
        files: dict[str, Path],
    ) -> None:
        run = self.run_dir(topic_id)
        manifest = self.read_manifest(topic_id)
        event: dict[str, str] = {"stage": stage, "action": action}
        for label, path in files.items():
            event[label] = _relative_to(path, run)
        event["recorded_at"] = datetime.now(timezone.utc).isoformat()
        manifest.setdefault("events", []).append(event)
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
    if not _is_artifact_id(value):
        raise ConfigError(
            f"{context} must match {_ARTIFACT_ID_PATTERN.pattern!r}; got {value!r}"
        )
    return value


def _is_artifact_id(value: str) -> bool:
    return isinstance(value, str) and _ARTIFACT_ID_PATTERN.fullmatch(value) is not None
