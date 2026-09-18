"""Leaf primitives shared by ``runs`` and its mixins.

``runs`` imports ``run_modes``, ``runs_reports``, ``runs_waivers``,
``runs_personalization`` and ``runs_finalize`` at module scope, so none of
those may import ``runs`` back at module scope. Everything they genuinely
share sits here instead -- the run-directory path helper, the atomic artifact
writers, the final-source constant, and the small frozen value types every
surface passes around -- so each of them can import what it needs at module
scope and no collaborator has to be looked up lazily through the ``runs``
namespace at call time.

``runs`` re-exports these names, because importers (and tests) still read them
from ``education_pipeline.runs``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from education_pipeline.config import OPTIONAL_STAGES, ConfigError
from education_pipeline.atomic_io import atomic_write_bytes, atomic_write_text
from education_pipeline.prompts import PromptArtifact

#: The stage whose approved output is assembled into the final guide.
_FINAL_SOURCE_STAGE = "repair"

MARKDOWN_CONTENT_TYPE = "text/markdown"


class StaleContentError(Exception):
    """The response file changed on disk since the client loaded it."""


def _relative_to(path: Path, run: Path) -> str:
    return path.relative_to(run).as_posix()


def _write_text(path: Path, text: str, *, overwrite: bool) -> None:
    # The refusal is checked before anything is created on disk, so a rejected
    # write leaves the directory exactly as it found it -- no stray temp file.
    if path.exists() and not overwrite:
        raise ConfigError(f"refusing to overwrite existing file: {path}")
    # atomic_write_text encodes UTF-8 and writes in binary mode, which is the
    # byte-for-byte equivalent of write_text(encoding="utf-8", newline=""):
    # artifacts are sha-keyed and byte-compared, so Windows text-mode
    # \n -> \r\n translation must never rewrite them. Going through the temp
    # file means a crash mid-rewrite leaves the previous content in place.
    atomic_write_text(path, text)


def _write_text_atomic(path: Path, text: str) -> None:
    _write_bytes_atomic(path, text.encode("utf-8"))


def _write_bytes_atomic(path: Path, data: bytes) -> None:
    atomic_write_bytes(path, data)


@dataclass(frozen=True)
class StageStatus:
    """Persisted progress for a single stage, derived from workspace files."""

    stage: str
    prompt_written: bool
    response_ingested: bool
    approved: bool
    stale: bool = False

    @property
    def state(self) -> str:
        """The furthest milestone this stage has durably reached."""

        if self.stale:
            return "stale"
        if self.approved:
            return "approved"
        if self.response_ingested:
            return "response_ingested"
        if self.prompt_written:
            return "prompt_written"
        if self.stage in OPTIONAL_STAGES:
            return "not_run"
        return "pending"


@dataclass(frozen=True)
class NextAction:
    """The next step needed to move a run forward, for resuming work.

    ``wave`` is set only on a modular draft's steps (``"frame"`` or
    ``"modules"``); every other action leaves it ``None``. It is last and
    defaulted so the dozens of keyword constructions elsewhere -- and the
    field-wise comparisons in the characterization tests -- keep working
    unchanged.
    """

    topic_id: str
    stage: str | None
    action: str
    detail: str
    wave: str | None = None


@dataclass(frozen=True)
class RunStatus:
    """A resumable snapshot of a run's progress across supported stages."""

    topic_id: str
    stages: tuple[StageStatus, ...]
    finalized: bool
    next_action: NextAction


@dataclass(frozen=True)
class AdvanceResult:
    """The outcome of advancing a run by one machine step."""

    topic_id: str
    performed: str | None
    status: RunStatus


@dataclass(frozen=True)
class StagePaths:
    """Filesystem locations for a single stage within a topic run."""

    stage: str
    topic_id: str
    prompt_path: Path
    response_path: Path
    stub_path: Path
    approved_path: Path
    content_type: str = MARKDOWN_CONTENT_TYPE


@dataclass(frozen=True)
class PromptFile:
    """The result of writing a compiled stage prompt to a topic run."""

    stage: str
    topic_id: str
    prompt_path: Path
    response_path: Path
    stub_path: Path
    artifact: PromptArtifact


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
