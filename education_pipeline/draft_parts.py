"""Value types for the per-module draft strategy (spec D1/D3/D4).

A modular draft is drafted in two waves: one **frame** (the whole guide
object with an empty stub per contract module) and then one response per
module. This module holds the pure value types those waves are described
with -- which part is being addressed, where its files live, how far it has
got, and the snapshot of the whole fan-out -- so the lifecycle logic in
:mod:`education_pipeline.runs_modular` can stay about the run and the
surfaces (CLI, daemon, cockpit) can name a part without importing
``runs``.

Leaf module by construction: no I/O, no imports from ``runs`` or any of its
mixins. ``education_pipeline`` re-exports these names alongside
``NextAction`` and friends.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

#: The two kinds of draft part.
FRAME_KIND = "frame"
MODULE_KIND = "module"

#: A part's lifecycle states, in the order a part passes through them.
PART_STATES = ("missing", "prompted", "responded", "stale")

#: The assembled response's three states (spec D3).
ASSEMBLED_STATES = ("absent", "matches_record", "edited")


@dataclass(frozen=True)
class DraftPart:
    """One addressable unit of a modular draft: the frame, or one module."""

    kind: str
    module_id: str | None = None

    def __post_init__(self) -> None:
        if self.kind == FRAME_KIND:
            if self.module_id is not None:
                raise ValueError("the frame part carries no module id")
            return
        if self.kind == MODULE_KIND:
            if not isinstance(self.module_id, str) or not self.module_id:
                raise ValueError("a module part requires a non-empty module id")
            return
        raise ValueError(
            f"unknown draft part kind {self.kind!r}; expected "
            f"{FRAME_KIND!r} or {MODULE_KIND!r}"
        )

    @property
    def key(self) -> str:
        """A stable, flat identifier: ``frame`` or ``module:<id>``."""

        if self.kind == FRAME_KIND:
            return FRAME_KIND
        return f"{MODULE_KIND}:{self.module_id}"

    @classmethod
    def from_key(cls, key: str) -> DraftPart:
        """Inverse of :attr:`key`."""

        if key == FRAME_KIND:
            return FRAME
        prefix = f"{MODULE_KIND}:"
        if key.startswith(prefix):
            return cls(MODULE_KIND, key[len(prefix) :])
        raise ValueError(f"unknown draft part key {key!r}")

    def to_manifest(self) -> dict[str, str]:
        """The ``part`` object recorded on this part's manifest events."""

        if self.kind == FRAME_KIND:
            return {"kind": FRAME_KIND}
        return {"kind": MODULE_KIND, "module_id": str(self.module_id)}

    @classmethod
    def from_manifest(cls, value: object) -> DraftPart | None:
        """Read a manifest ``part`` object back, or ``None`` when it is absent.

        Tolerant on purpose: a manifest is read-only input from disk, so an
        unrecognized shape reads as "this event is about no part" rather
        than raising in the middle of a status walk.
        """

        if not isinstance(value, dict):
            return None
        kind = value.get("kind")
        if kind == FRAME_KIND:
            return FRAME
        if kind == MODULE_KIND:
            module_id = value.get("module_id")
            if isinstance(module_id, str) and module_id:
                return cls(MODULE_KIND, module_id)
        return None


#: The one frame part; every run has exactly one, so it is a singleton.
FRAME = DraftPart(FRAME_KIND)


@dataclass(frozen=True)
class PartPaths:
    """Filesystem locations for one draft part within a topic run."""

    part: DraftPart
    prompt_path: Path
    response_path: Path
    stub_path: Path
    content_type: str

    @property
    def stage(self) -> str:
        """Always ``draft``: parts only exist inside the draft stage.

        Named to match :class:`~education_pipeline.run_core.StagePaths` so the
        shared stub-placeholder renderer (``run_core._stub_text``) can render a
        part's stub without a second, divergent copy of its wording.
        """

        return "draft"


@dataclass(frozen=True)
class PartStatus:
    """How far one draft part has got, derived from files plus the manifest.

    ``state`` is one of :data:`PART_STATES`: ``missing`` (no prompt file),
    ``prompted`` (prompt current, no response yet), ``responded`` (prompt
    current and a response saved), ``stale`` (the prompt file exists but the
    inputs its ``prompt_written`` event bound have since changed, so any
    response saved against it was drafted from superseded bytes).
    """

    part: DraftPart
    state: str
    prompt_path: Path
    response_path: Path
    prompt_current: bool
    response_current: bool


@dataclass(frozen=True)
class DraftPartsStatus:
    """A resumable snapshot of a modular draft's whole fan-out."""

    strategy: str
    module_ids: tuple[str, ...]
    frame: PartStatus
    modules: tuple[PartStatus, ...]
    assembled: str
    assembled_stale: bool

    @property
    def wave(self) -> str | None:
        """Which wave the run is in: ``frame``, ``modules``, or ``None``.

        ``None`` only once every part is responded and current *and* the
        assembled response matches the parts it was assembled from -- the
        point at which a modular draft is exactly where a whole draft is
        after ``ingest_response``.
        """

        if self.frame.state != "responded":
            return FRAME_KIND
        if any(module.state != "responded" for module in self.modules):
            return "modules"
        if self.assembled == "absent" or self.assembled_stale:
            return "modules"
        return None

    def module(self, module_id: str) -> PartStatus | None:
        """This snapshot's status for one module, or ``None`` when unknown."""

        for status in self.modules:
            if status.part.module_id == module_id:
                return status
        return None

    def waiting_module_ids(self) -> tuple[str, ...]:
        """Module ids whose prompt is current but whose response is missing."""

        return tuple(
            str(status.part.module_id)
            for status in self.modules
            if status.state == "prompted"
        )

    def unprompted_module_ids(self) -> tuple[str, ...]:
        """Module ids needing a prompt: never written, or written and stale."""

        return tuple(
            str(status.part.module_id)
            for status in self.modules
            if status.state in ("missing", "stale")
        )
