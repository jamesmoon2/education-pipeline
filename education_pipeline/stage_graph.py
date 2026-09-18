"""The declarative stage graph: one table that describes the pipeline.

``STAGES`` below is the single source of truth for

* **stage order** -- the order stages run in, and the order every derived
  sequence (required/supported/optional lists, status walks) is reported in;
* **mode membership** -- which content modes (``legacy_markdown`` /
  ``interactive_guide``) require a stage, and which stages are optional
  add-ons that belong to no mode;
* **upstream sources** -- which approved stages feed a stage's prompt, which
  is what drives prompt-time source binding (``source_<stage>_file`` manifest
  labels) and downstream staleness when an upstream stage is re-approved;
* **the reasoning flag** -- whether a stage is reasoning-heavy, and therefore
  warns when a below-``strong`` model is planned for it.

``education_pipeline.config`` derives its stage-topology constants from this
table, and later threads (T12 stale walks, T13 next-action walks) derive their
dependency traversals from it rather than hand-unrolling the chain again.

This module intentionally imports nothing from the rest of the package so that
``config`` -- and anything else -- can import it without a cycle.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType


MODES: tuple[str, ...] = ("legacy_markdown", "interactive_guide")


@dataclass(frozen=True)
class StageSpec:
    """One row of the stage table."""

    name: str
    sources: tuple[str, ...]
    content: str
    modes: frozenset[str]
    optional: bool
    reasoning: bool
    prompt_writer: str | None


_BOTH_MODES = frozenset(MODES)
_GUIDE_ONLY = frozenset({"interactive_guide"})

STAGES: tuple[StageSpec, ...] = (
    StageSpec(
        name="spec",
        sources=(),
        content="markdown",
        modes=_BOTH_MODES,
        optional=False,
        reasoning=True,
        prompt_writer="write_spec_prompt",
    ),
    StageSpec(
        name="outline",
        sources=(),
        content="markdown",
        modes=_BOTH_MODES,
        optional=False,
        reasoning=True,
        prompt_writer="write_outline_prompt",
    ),
    StageSpec(
        name="draft",
        sources=(),
        content="guide",
        modes=_BOTH_MODES,
        optional=False,
        reasoning=False,
        prompt_writer="write_draft_prompt",
    ),
    StageSpec(
        name="qa",
        sources=("draft",),
        content="markdown",
        modes=_BOTH_MODES,
        optional=False,
        reasoning=False,
        prompt_writer="write_qa_prompt",
    ),
    StageSpec(
        name="factcheck",
        sources=("draft", "qa"),
        content="markdown",
        modes=_GUIDE_ONLY,
        optional=False,
        reasoning=True,
        prompt_writer="write_factcheck_prompt",
    ),
    StageSpec(
        name="repair",
        sources=("draft", "qa", "factcheck"),
        content="guide",
        modes=_BOTH_MODES,
        optional=False,
        reasoning=True,
        prompt_writer="write_repair_prompt",
    ),
    StageSpec(
        name="audit",
        sources=(),
        content="json",
        modes=frozenset(),
        optional=True,
        reasoning=False,
        prompt_writer=None,
    ),
)

STAGE_BY_NAME = MappingProxyType({spec.name: spec for spec in STAGES})


def _check() -> None:
    """Fail at import time if the table above is internally inconsistent."""

    names: list[str] = []
    modes = frozenset(MODES)
    for spec in STAGES:
        if spec.name in names:
            raise ValueError(f"duplicate stage name in STAGES: {spec.name!r}")
        for source in spec.sources:
            if source not in names:
                raise ValueError(
                    f"stage {spec.name!r} source {source!r} must be an earlier stage"
                )
        if not spec.modes <= modes:
            raise ValueError(
                f"stage {spec.name!r} has modes outside MODES: "
                f"{sorted(spec.modes - modes)}"
            )
        names.append(spec.name)


_check()


def stage(name: str) -> StageSpec:
    """The spec for ``name``; ``KeyError`` when no such stage exists."""

    return STAGE_BY_NAME[name]


def required_stages(mode: str) -> tuple[str, ...]:
    """Non-optional stages belonging to ``mode``, in ``STAGES`` order."""

    if mode not in MODES:
        raise ValueError(f"unknown content mode: {mode!r}")
    return tuple(
        spec.name for spec in STAGES if not spec.optional and mode in spec.modes
    )


def supported_stages() -> tuple[str, ...]:
    """Every model-driven stage (required in some mode, or optional)."""

    return tuple(spec.name for spec in STAGES if spec.modes or spec.optional)


def optional_stages() -> tuple[str, ...]:
    """Stages that no mode requires, in ``STAGES`` order."""

    return tuple(spec.name for spec in STAGES if spec.optional)


def reasoning_stages() -> frozenset[str]:
    """Stages that warn when planned with a below-``strong`` model."""

    return frozenset(spec.name for spec in STAGES if spec.reasoning)


def sources_of(name: str) -> tuple[str, ...]:
    """Approved upstream stages bound into ``name``'s prompt."""

    return stage(name).sources


def dependents_of(name: str) -> tuple[str, ...]:
    """Stages made stale by re-approving ``name``, transitively, in ``STAGES`` order."""

    stage(name)  # validate the name even when nothing depends on it
    stale = {name}
    dependents: list[str] = []
    for spec in STAGES:
        if spec.name in stale:
            continue
        if stale.intersection(spec.sources):
            stale.add(spec.name)
            dependents.append(spec.name)
    return tuple(dependents)


def source_labels(name: str) -> tuple[str, ...]:
    """Manifest file labels for ``name``'s sources, e.g. ``source_draft_file``."""

    return tuple(f"source_{source}_file" for source in sources_of(name))
