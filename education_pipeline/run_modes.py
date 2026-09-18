"""Per-mode strategies for the two content modes a run can be in.

Every run carries a :class:`~education_pipeline.runs.ContentContract` whose
``kind`` is either ``interactive_guide`` (what new runs always are) or
``legacy_markdown`` (kept so workspaces created before the guide format can
still be resumed). ``RunStore`` used to branch on that kind at every site that
behaved differently; this module replaces those branches with one strategy
object per mode, resolved once by ``RunStore._mode``.

The split is deliberately lopsided:

* :class:`LegacyMarkdownMode` **owns** the legacy Markdown bodies -- the legacy
  next-action walk, the legacy finalize and export, and the legacy prompt
  compilers. They live here, out of ``runs.py``, which is the quarantine.
* :class:`InteractiveGuideMode` is a thin adapter that calls back into the
  guide-v1 methods on ``RunStore``, which stay where they are.

Sites whose only difference is a refusal or a small quirk read a capability
flag (``supports_factcheck``, ``binds_sources``, ...) instead of getting a
method apiece, so every ``ConfigError`` message stays in ``runs.py``, worded
exactly as before.

Only leaf modules are imported at module scope: ``runs`` imports this module,
so the few names this module needs back from it are imported inside the
functions that use them.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from education_pipeline.config import REQUIRED_STAGES
from education_pipeline.run_core import NextAction, _FINAL_SOURCE_STAGE, _write_text
from education_pipeline.export import (
    build_markdown_bundle,
    render_markdown_to_html,
)
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
from education_pipeline.workspace import TopicStore

if TYPE_CHECKING:  # pragma: no cover - typing only
    from education_pipeline.profiles import LearnerProfile
    from education_pipeline.run_core import StageStatus
    from education_pipeline.runs import RunStore
    from education_pipeline.topics import Topic


#: What a prompt compiler hands back: the compiled artifact plus the extra
#: manifest files to record on its ``prompt_written`` event (``None`` when the
#: mode binds no sources).
CompiledPrompt = tuple[PromptArtifact, "dict[str, Path] | None"]


class _RunMode:
    """The per-mode operations ``RunStore`` needs.

    Subclasses are stateless singletons: every method takes the calling store
    and the already-validated topic id, so a mode never holds run state.
    """

    #: The content-contract kind this mode serves, which is also the
    #: ``education_pipeline.stage_graph`` mode string (see ``graph_mode``).
    name: str = ""

    #: Whether a stage's approval binds (and later staleness-checks) the
    #: approved upstream sources declared by the stage graph.
    binds_sources: bool = False

    #: Whether ``advance`` rewrites an existing prompt file in place rather
    #: than refusing to overwrite it.
    prompt_overwrite_on_advance: bool = False

    #: Whether approving a repair response can splice a module-scoped repair
    #: into the approved draft.
    scoped_repair_on_approve: bool = False

    #: Whether validation reports (draft/final) exist for this mode.
    supports_validation: bool = False

    #: Whether the adversarial factcheck stage applies.
    supports_factcheck: bool = False

    #: Whether module-scoped repair prompts apply.
    supports_module_repair: bool = False

    #: Whether the private personalization audit applies.
    supports_audit: bool = False

    #: Whether ``export_run`` accepts formats other than ``html``.
    supports_markdown_export: bool = False

    @property
    def graph_mode(self) -> str:
        """The ``stage_graph`` mode string for this mode.

        Identical to :attr:`name` by construction -- the contract kinds and
        the stage-graph modes are the same two strings -- and named separately
        only where the stage graph is what is being addressed.
        """

        return self.name

    def next_action(
        self,
        store: RunStore,
        topic_id: str,
        stages: tuple[StageStatus, ...],
        finalized: bool,
    ) -> NextAction:
        raise NotImplementedError

    def validate_approval(self, store: RunStore, topic_id: str, stage: str, text: str) -> None:
        """Gate a stage response before it is promoted to ``approved``."""

        return None

    def is_finalized(self, store: RunStore, topic_id: str) -> bool:
        raise NotImplementedError

    def finalize(self, store: RunStore, topic_id: str, *, overwrite: bool) -> Path:
        raise NotImplementedError

    def export(self, store: RunStore, topic_id: str, *, format: str, overwrite: bool) -> Path:
        raise NotImplementedError

    def compile_spec_prompt(
        self, store: RunStore, topic_id: str, spec_input: SpecPromptInput
    ) -> PromptArtifact:
        raise NotImplementedError

    def compile_topic_spec_prompt(
        self,
        store: RunStore,
        topic_id: str,
        topic: Topic,
        profile: LearnerProfile | None,
    ) -> PromptArtifact:
        raise NotImplementedError

    def compile_outline_prompt(
        self,
        store: RunStore,
        topic_id: str,
        topic: Topic,
        approved_spec: str,
        profile: LearnerProfile | None,
    ) -> CompiledPrompt:
        raise NotImplementedError

    def compile_draft_prompt(
        self,
        store: RunStore,
        topic_id: str,
        topic: Topic,
        approved_outline: str,
        profile: LearnerProfile | None,
        *,
        overwrite: bool,
    ) -> CompiledPrompt:
        raise NotImplementedError

    def compile_qa_prompt(
        self,
        store: RunStore,
        topic_id: str,
        topic: Topic,
        *,
        approved_spec: str,
        approved_outline: str,
        approved_draft: str,
        profile: LearnerProfile | None,
    ) -> CompiledPrompt:
        raise NotImplementedError

    def compile_repair_prompt(
        self,
        store: RunStore,
        topic_id: str,
        topic: Topic,
        *,
        approved_draft: str,
        approved_qa: str,
        profile: LearnerProfile | None,
    ) -> CompiledPrompt:
        raise NotImplementedError


class LegacyMarkdownMode(_RunMode):
    """The frozen pre-guide Markdown pipeline, kept only so old runs resume.

    Nothing here is reachable for a run created today: ``create_run`` defaults
    to the interactive-guide contract, and only an explicit
    ``ContentContract.legacy_markdown()`` (or a manifest written before the
    guide format) selects this mode.
    """

    name = "legacy_markdown"

    supports_markdown_export = True

    def next_action(
        self,
        store: RunStore,
        topic_id: str,
        stages: tuple[StageStatus, ...],
        finalized: bool,
    ) -> NextAction:
        by_stage = {status.stage: status for status in stages}
        for stage_name in REQUIRED_STAGES:
            status = by_stage[stage_name]
            pending = store._pending_stage_action(topic_id, status)
            if pending is not None:
                return pending
        if not finalized:
            return NextAction(
                topic_id=topic_id,
                stage=None,
                action="finalize",
                detail=(
                    f"Finalize {topic_id!r}: assemble the approved {_FINAL_SOURCE_STAGE} draft "
                    f"into {store.final_path(topic_id)}."
                ),
            )
        return NextAction(
            topic_id=topic_id,
            stage=None,
            action="done",
            detail=f"Run {topic_id!r} is complete and finalized.",
        )

    def is_finalized(self, store: RunStore, topic_id: str) -> bool:
        return store.final_path(topic_id).exists()

    def finalize(self, store: RunStore, topic_id: str, *, overwrite: bool) -> Path:
        content = store.read_approved(topic_id, _FINAL_SOURCE_STAGE)
        store.create_run(topic_id)
        final = store.final_path(topic_id)
        _write_text(final, content, overwrite=overwrite)
        store._append_event(
            topic_id,
            stage="finalize",
            action="finalized",
            files={
                "final_file": final,
                "source_file": store.stage_paths(topic_id, _FINAL_SOURCE_STAGE).approved_path,
            },
        )
        return final

    def export(self, store: RunStore, topic_id: str, *, format: str, overwrite: bool) -> Path:
        export_path = store.export_path(topic_id, format)
        guide = store._read_final_guide(topic_id)
        topic = TopicStore(store.root).load_topic(topic_id)

        if format == "markdown":
            content = build_markdown_bundle(guide, front_matter=store._export_front_matter(topic_id, topic))
        else:
            content = render_markdown_to_html(guide, title=topic.title)

        _write_text(export_path, content, overwrite=overwrite)
        store._append_event(
            topic_id,
            stage="export",
            action="exported",
            files={"export_file": export_path, "source_file": store.final_path(topic_id)},
        )
        return export_path

    def compile_spec_prompt(
        self, store: RunStore, topic_id: str, spec_input: SpecPromptInput
    ) -> PromptArtifact:
        return compile_spec_prompt(spec_input)

    def compile_topic_spec_prompt(
        self,
        store: RunStore,
        topic_id: str,
        topic: Topic,
        profile: LearnerProfile | None,
    ) -> PromptArtifact:
        return compile_topic_spec_prompt(topic, profile)

    def compile_outline_prompt(
        self,
        store: RunStore,
        topic_id: str,
        topic: Topic,
        approved_spec: str,
        profile: LearnerProfile | None,
    ) -> CompiledPrompt:
        return compile_outline_prompt(topic, approved_spec, profile), None

    def compile_draft_prompt(
        self,
        store: RunStore,
        topic_id: str,
        topic: Topic,
        approved_outline: str,
        profile: LearnerProfile | None,
        *,
        overwrite: bool,
    ) -> CompiledPrompt:
        return compile_draft_prompt(topic, approved_outline, profile), None

    def compile_qa_prompt(
        self,
        store: RunStore,
        topic_id: str,
        topic: Topic,
        *,
        approved_spec: str,
        approved_outline: str,
        approved_draft: str,
        profile: LearnerProfile | None,
    ) -> CompiledPrompt:
        artifact = compile_qa_prompt(
            topic,
            approved_spec=approved_spec,
            approved_outline=approved_outline,
            approved_draft=approved_draft,
            profile=profile,
        )
        return artifact, None

    def compile_repair_prompt(
        self,
        store: RunStore,
        topic_id: str,
        topic: Topic,
        *,
        approved_draft: str,
        approved_qa: str,
        profile: LearnerProfile | None,
    ) -> CompiledPrompt:
        artifact = compile_repair_prompt(
            topic,
            approved_draft=approved_draft,
            approved_qa=approved_qa,
            profile=profile,
        )
        return artifact, None


class InteractiveGuideMode(_RunMode):
    """The interactive-guide pipeline every new run uses.

    Thin by design: the guide-v1 bodies stay on ``RunStore`` and this class
    only names which of them each site calls.
    """

    name = "interactive_guide"

    binds_sources = True
    prompt_overwrite_on_advance = True
    scoped_repair_on_approve = True
    supports_validation = True
    supports_factcheck = True
    supports_module_repair = True
    supports_audit = True

    def next_action(
        self,
        store: RunStore,
        topic_id: str,
        stages: tuple[StageStatus, ...],
        finalized: bool,
    ) -> NextAction:
        return store._next_action_guide_v1(topic_id, stages, finalized)

    def validate_approval(self, store: RunStore, topic_id: str, stage: str, text: str) -> None:
        if stage in {"spec", "outline"}:
            store._validate_guide_approval(topic_id, stage, text)

    def is_finalized(self, store: RunStore, topic_id: str) -> bool:
        return store._is_finalized_guide_v1(topic_id)

    def finalize(self, store: RunStore, topic_id: str, *, overwrite: bool) -> Path:
        return store._finalize_guide_v1(topic_id, overwrite=overwrite)

    def export(self, store: RunStore, topic_id: str, *, format: str, overwrite: bool) -> Path:
        return store._export_guide_v1(topic_id, overwrite=overwrite)

    def compile_spec_prompt(
        self, store: RunStore, topic_id: str, spec_input: SpecPromptInput
    ) -> PromptArtifact:
        return store._guide_v1_spec_artifact(topic_id, spec_input)

    def compile_topic_spec_prompt(
        self,
        store: RunStore,
        topic_id: str,
        topic: Topic,
        profile: LearnerProfile | None,
    ) -> PromptArtifact:
        return store._guide_v1_topic_spec_artifact(topic_id, topic, profile)

    def compile_outline_prompt(
        self,
        store: RunStore,
        topic_id: str,
        topic: Topic,
        approved_spec: str,
        profile: LearnerProfile | None,
    ) -> CompiledPrompt:
        return store._guide_v1_outline_artifact(topic_id, topic, approved_spec, profile)

    def compile_draft_prompt(
        self,
        store: RunStore,
        topic_id: str,
        topic: Topic,
        approved_outline: str,
        profile: LearnerProfile | None,
        *,
        overwrite: bool,
    ) -> CompiledPrompt:
        return store._guide_v1_draft_artifact(
            topic_id, topic, approved_outline, profile, overwrite=overwrite
        )

    def compile_qa_prompt(
        self,
        store: RunStore,
        topic_id: str,
        topic: Topic,
        *,
        approved_spec: str,
        approved_outline: str,
        approved_draft: str,
        profile: LearnerProfile | None,
    ) -> CompiledPrompt:
        return store._guide_v1_qa_artifact(
            topic_id,
            topic,
            approved_spec=approved_spec,
            approved_outline=approved_outline,
            approved_draft=approved_draft,
            profile=profile,
        )

    def compile_repair_prompt(
        self,
        store: RunStore,
        topic_id: str,
        topic: Topic,
        *,
        approved_draft: str,
        approved_qa: str,
        profile: LearnerProfile | None,
    ) -> CompiledPrompt:
        return store._guide_v1_repair_artifact(
            topic_id,
            topic,
            approved_draft=approved_draft,
            approved_qa=approved_qa,
            profile=profile,
        )


LEGACY_MARKDOWN_MODE: _RunMode = LegacyMarkdownMode()
INTERACTIVE_GUIDE_MODE: _RunMode = InteractiveGuideMode()

#: The one table ``RunStore._mode`` dispatches through, keyed on the content
#: contract's ``kind``. Anything that is not the guide kind resumes as legacy
#: Markdown, matching the pre-strategy ``_is_guide_v1`` test.
MODES_BY_KIND: dict[str, _RunMode] = {
    LEGACY_MARKDOWN_MODE.name: LEGACY_MARKDOWN_MODE,
    INTERACTIVE_GUIDE_MODE.name: INTERACTIVE_GUIDE_MODE,
}


def mode_for_kind(kind: str) -> _RunMode:
    """The strategy for a content-contract ``kind``, legacy for anything else."""

    return MODES_BY_KIND.get(kind, LEGACY_MARKDOWN_MODE)
