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


@dataclass(frozen=True)
class RepairScope:
    """The target of a pending scoped repair.

    A module-scoped repair regenerates one whole module (``section_id`` is
    ``None``); a section-scoped repair regenerates exactly one section of
    that module. Frozen and comparable, so callers can pass it around and
    compare it without caring how the manifest spells it.
    """

    module_id: str
    section_id: str | None = None


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


@dataclass(frozen=True)
class DraftUnitPaths:
    """Filesystem locations for one draft *unit* of a guide-v1 run.

    A unit is either the single ``skeleton`` (the whole guide with every
    module reduced to a sectionless stub) or one ``module``. Nothing else
    spells the ``<run>/draft/`` layout: every caller goes through
    :meth:`~education_pipeline.runs.RunStore.draft_unit_paths`.
    """

    unit: str
    module_id: str | None
    prompt_path: Path
    response_path: Path
    stub_path: Path
    previous_path: Path


@dataclass(frozen=True)
class DraftUnitStatus:
    """The persisted state of one draft unit, derived from workspace files.

    ``state`` is one of ``not_run``, ``prompt_written``, ``response_ingested``,
    ``stale`` (the contract entry or skeleton stub the prompt embedded has
    changed), ``orphaned`` (a unit whose module id left the contract; ignored
    by assembly, never deleted) or ``superseded`` (the stage response file no
    longer holds the last assembled bytes).
    """

    unit: str
    state: str
    module_id: str | None = None
    title: str | None = None
    response_sha256: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class AssembledStatus:
    """The last recorded assembly attempt for a run's draft units."""

    ok: bool
    response_sha256: str | None = None
    error: str | None = None
    module_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class DraftProgress:
    """A resumable snapshot of a guide-v1 run's per-module drafting.

    ``modules`` stays empty until a skeleton response exists: the module
    units are the skeleton's stubs, and before it lands there is nothing to
    report per module. The counts are derived, never stored, so they cannot
    drift from the unit list they summarize.
    """

    skeleton: DraftUnitStatus
    modules: tuple[DraftUnitStatus, ...] = ()
    assembled: AssembledStatus | None = None
    superseded: bool = False

    @property
    def total(self) -> int:
        return len(self.modules)

    @property
    def saved(self) -> int:
        return sum(1 for unit in self.modules if unit.state == "response_ingested")

    @property
    def stale(self) -> int:
        return sum(1 for unit in self.modules if unit.state == "stale")


@dataclass(frozen=True)
class AssembleResult:
    """The outcome of one deterministic draft assembly.

    ``module_ids`` names the modules the caller would have to act on: the
    outstanding ones when assembly was skipped, the implicated ones when it
    failed, and every assembled module on success.
    """

    ok: bool
    response_sha256: str | None = None
    error: str | None = None
    module_ids: tuple[str, ...] = ()
