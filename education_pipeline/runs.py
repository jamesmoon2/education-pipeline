"""Workspace-local run directories, prompt files, and manifest logging."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import ClassVar
import hashlib
import json
import re
import threading

from education_pipeline.config import ConfigError
from education_pipeline.export import (
    EXPORT_FORMATS,
    build_markdown_bundle,
    render_markdown_to_html,
)
from education_pipeline.guides import (
    ContractError,
    Waiver,
    WaiverSet,
    apply_waivers,
    build_guide_contract,
    canonical_guide_bytes,
    canonical_report_bytes,
    check_contract_conflict,
    extract_outline_contract,
    extract_spec_contract,
    guide_sha256,
    normalize_guide,
    parse_guide,
    project_guide_markdown,
    validate_guide,
    assemble_guide_document,
)
from education_pipeline.guide_runtime import load_runtime_assets
from education_pipeline.prompts import (
    PromptArtifact,
    SpecPromptInput,
    compile_draft_prompt,
    compile_guide_v1_draft_prompt,
    compile_guide_v1_outline_prompt,
    compile_guide_v1_qa_prompt,
    compile_guide_v1_repair_prompt,
    compile_guide_v1_spec_prompt,
    compile_outline_prompt,
    compile_qa_prompt,
    compile_repair_prompt,
    compile_spec_prompt,
    compile_topic_spec_prompt,
)
from education_pipeline.workspace import ProfileStore, TopicStore

_GUIDE_CONTRACT_FILENAME = "guide-contract.json"


class StaleContentError(Exception):
    """The response file changed on disk since the client loaded it."""


MANIFEST_SCHEMA_VERSION = 1

RUN_SUBDIRS = ("inputs", "prompts", "responses", "approved", "reports", "final")

#: Stages this writer can currently compile prompts for. Finalize and export are
#: intentionally omitted until their prompt compilers exist.
SUPPORTED_STAGES = ("spec", "outline", "draft", "qa", "repair")

_PROMPT_SUFFIX = ".prompt.md"
_RESPONSE_SUFFIX = ".response.md"
_STUB_SUFFIX = ".SAVE_RESPONSE_HERE.md"

MARKDOWN_CONTENT_TYPE = "text/markdown"
GUIDE_V1_CONTENT_TYPE = (
    "application/vnd.education-pipeline.guide+json;version=1.0"
)

#: The stage whose approved output is assembled into the final guide.
_FINAL_SOURCE_STAGE = "repair"
_FINAL_FILENAME = "guide.md"

_ARTIFACT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


@dataclass(frozen=True)
class ContentContract:
    """Immutable content format recorded by a run manifest."""

    kind: str
    schema_version: str | None = None

    @classmethod
    def legacy_markdown(cls) -> ContentContract:
        return cls(kind="legacy_markdown")

    @classmethod
    def interactive_guide_v1(cls) -> ContentContract:
        return cls(kind="interactive_guide", schema_version="1.0")

    def to_manifest(self) -> dict[str, str]:
        value = {"kind": self.kind}
        if self.schema_version is not None:
            value["schema_version"] = self.schema_version
        return value


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
    finalized: bool
    next_action: NextAction


@dataclass(frozen=True)
class AdvanceResult:
    """The outcome of advancing a run by one machine step."""

    topic_id: str
    performed: str | None
    status: RunStatus


@dataclass(frozen=True)
class RunStore:
    """Create run directories and write stage prompt/response artifacts."""

    root: Path
    # Per-instance runtime state, not dataclass fields: assigned in __init__ via
    # object.__setattr__ because the dataclass is frozen. Annotated as ClassVar
    # so the dataclass machinery does not treat them as fields (which would
    # pull them into __init__/__repr__/__eq__ and require defaults).
    _manifest_locks: ClassVar[dict[str, threading.Lock]]
    _manifest_locks_guard: ClassVar[threading.Lock]

    def __init__(self, root: str | Path) -> None:
        object.__setattr__(self, "root", Path(root))
        object.__setattr__(self, "_manifest_locks", {})
        object.__setattr__(self, "_manifest_locks_guard", threading.Lock())

    def _manifest_lock(self, topic_id: str) -> threading.Lock:
        """Return the per-topic lock guarding manifest read-modify-write cycles.

        Serialization is scoped to this ``RunStore`` instance only: it
        protects concurrent threads (e.g. daemon workers) sharing one
        ``RunStore`` over the same workspace from racing on the same run's
        manifest. Two ``RunStore`` instances over the same workspace share no
        locks, and cross-process concurrency (e.g. concurrent CLI invocations)
        is out of scope here. Callers must share a single ``RunStore`` per
        workspace to get this guarantee.
        """

        with self._manifest_locks_guard:
            existing = self._manifest_locks.get(topic_id)
            if existing is None:
                existing = threading.Lock()
                self._manifest_locks[topic_id] = existing
            return existing

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
        contract = self.content_contract(safe_id)
        is_guide_json = contract.kind == "interactive_guide" and safe_stage in {
            "draft",
            "repair",
        }
        suffix = ".json" if is_guide_json else ".md"
        response_suffix = f".response{suffix}"
        stub_suffix = f".SAVE_RESPONSE_HERE{suffix}"
        run = self.runs_dir / safe_id
        return StagePaths(
            stage=safe_stage,
            topic_id=safe_id,
            prompt_path=run / "prompts" / f"{safe_stage}{_PROMPT_SUFFIX}",
            response_path=run / "responses" / f"{safe_stage}{response_suffix}",
            stub_path=run / "responses" / f"{safe_stage}{stub_suffix}",
            approved_path=run / "approved" / f"{safe_stage}{suffix}",
            content_type=GUIDE_V1_CONTENT_TYPE if is_guide_json else MARKDOWN_CONTENT_TYPE,
        )

    def content_contract(self, topic_id: str) -> ContentContract:
        """Return the validated manifest contract without mutating legacy runs."""

        path = self.manifest_path(topic_id)
        if not path.exists():
            return ContentContract.legacy_markdown()
        manifest = self.read_manifest(topic_id)
        return _parse_content_contract(manifest.get("content_contract"))

    def plan_overrides_path(self, topic_id: str) -> Path:
        return self.run_dir(topic_id) / "model-plan-overrides.json"

    def read_plan_overrides(self, topic_id: str) -> dict:
        """Return the run's sparse model-plan overrides, or {} when absent."""

        path = self.plan_overrides_path(topic_id)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ConfigError(f"invalid model-plan overrides file: {path}") from exc
        if not isinstance(data, dict):
            raise ConfigError(f"invalid model-plan overrides file: {path} (must be a JSON object)")
        stages = data.get("stages", {})
        if stages is not None and not isinstance(stages, dict):
            raise ConfigError(
                f"invalid model-plan overrides file: {path} ('stages' must be a JSON object)"
            )
        return data

    def write_plan_overrides(self, topic_id: str, overrides: dict) -> None:
        """Atomically persist sparse per-run model-plan overrides."""

        path = self.plan_overrides_path(topic_id)
        _write_bytes_atomic(path, (json.dumps(overrides, indent=2) + "\n").encode("utf-8"))

    def response_path(self, topic_id: str, stage: str) -> Path:
        return self.stage_paths(topic_id, stage).response_path

    def approved_path(self, topic_id: str, stage: str) -> Path:
        return self.stage_paths(topic_id, stage).approved_path

    def create_run(
        self,
        topic_id: str,
        *,
        content_contract: ContentContract | None = None,
    ) -> Path:
        """Create the run directory tree and initialize a manifest if needed.

        Newly created manifests default to interactive_guide schema ``1.0`` when
        ``content_contract`` is omitted. Pass
        :meth:`ContentContract.legacy_markdown` for an explicit legacy Markdown
        run. When a manifest already exists and ``content_contract`` is omitted,
        the existing run is left unchanged (including pre-existing manifests
        without a ``content_contract`` field, which still read as legacy). When
        a contract is provided against an existing run, it must match the
        immutable recorded contract.
        """

        run = self.run_dir(topic_id)
        for subdir in RUN_SUBDIRS:
            (run / subdir).mkdir(parents=True, exist_ok=True)

        manifest_path = run / "manifest.json"
        with self._manifest_lock(run.name):
            if not manifest_path.exists():
                requested = (
                    content_contract
                    if content_contract is not None
                    else ContentContract.interactive_guide_v1()
                )
                _validate_content_contract(requested)
                manifest = {
                    "schema_version": MANIFEST_SCHEMA_VERSION,
                    "topic_id": run.name,
                    "events": [],
                    "content_contract": requested.to_manifest(),
                }
                _write_manifest(manifest_path, manifest)
            elif content_contract is not None:
                _validate_content_contract(content_contract)
                if self.content_contract(run.name) != content_contract:
                    raise ConfigError(
                        f"run {run.name!r} already has immutable content contract "
                        f"{self.content_contract(run.name)!r}; requested {content_contract!r}"
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
        approved = paths.approved_path.exists()
        stale = False
        if approved and self._is_guide_v1(paths.topic_id) and paths.stage in {"qa", "repair"}:
            stale = self._stage_upstream_stale(paths.topic_id, paths.stage)
        return StageStatus(
            stage=paths.stage,
            prompt_written=paths.prompt_path.exists(),
            response_ingested=paths.response_path.exists(),
            approved=approved,
            stale=stale,
        )

    def run_status(self, topic_id: str) -> RunStatus:
        """Report a resumable snapshot of a run across all supported stages.

        Reads only the workspace filesystem, so a fresh session can recover
        exactly where earlier work left off without losing anything.
        """

        safe_id = _artifact_id(topic_id, "topic id")
        stages = tuple(self.stage_status(safe_id, stage) for stage in SUPPORTED_STAGES)
        finalized = self.is_finalized(safe_id)
        return RunStatus(
            topic_id=safe_id,
            stages=stages,
            finalized=finalized,
            next_action=self._next_action(safe_id, stages, finalized),
        )

    def advance(self, topic_id: str) -> AdvanceResult:
        """Perform the run's next machine step, pausing at human steps.

        Machine steps (writing the next stage prompt, validation, or finalizing)
        are done automatically. Human steps (saving a response, approving it,
        resolving findings) and a completed run are left untouched, so this can
        be called repeatedly to drive a run forward and resume it from wherever
        it stopped.
        """

        safe_id = _artifact_id(topic_id, "topic id")
        action = self.run_status(safe_id).next_action
        performed: str | None = None
        if action.action == "write_prompt" and action.stage is not None:
            overwrite = False
            if self._is_guide_v1(safe_id):
                paths = self.stage_paths(safe_id, action.stage)
                if paths.prompt_path.exists():
                    overwrite = True
            self._write_stage_prompt(safe_id, action.stage, overwrite=overwrite)
            performed = "write_prompt"
        elif action.action == "validate":
            phase = "draft" if action.stage == "draft" else "final"
            self.validate_run(safe_id, phase)
            performed = "validate"
        elif action.action == "finalize":
            self.finalize_run(safe_id)
            performed = "finalize"
        return AdvanceResult(
            topic_id=safe_id,
            performed=performed,
            status=self.run_status(safe_id),
        )

    def _write_stage_prompt(
        self, topic_id: str, stage: str, *, overwrite: bool = False
    ) -> PromptFile:
        writers = {
            "spec": self.write_topic_spec_prompt,
            "outline": self.write_outline_prompt,
            "draft": self.write_draft_prompt,
            "qa": self.write_qa_prompt,
            "repair": self.write_repair_prompt,
        }
        try:
            writer = writers[stage]
        except KeyError as exc:
            raise ConfigError(f"no prompt writer for stage {stage!r}") from exc
        return writer(topic_id, overwrite=overwrite)

    def _next_action(
        self,
        topic_id: str,
        stages: tuple[StageStatus, ...],
        finalized: bool,
    ) -> NextAction:
        if self._is_guide_v1(topic_id):
            return self._next_action_guide_v1(topic_id, stages, finalized)
        return self._next_action_legacy(topic_id, stages, finalized)

    def _next_action_legacy(
        self,
        topic_id: str,
        stages: tuple[StageStatus, ...],
        finalized: bool,
    ) -> NextAction:
        for status in stages:
            pending = self._pending_stage_action(topic_id, status)
            if pending is not None:
                return pending
        if not finalized:
            return NextAction(
                topic_id=topic_id,
                stage=None,
                action="finalize",
                detail=(
                    f"Finalize {topic_id!r}: assemble the approved {_FINAL_SOURCE_STAGE} draft "
                    f"into {self.final_path(topic_id)}."
                ),
            )
        return NextAction(
            topic_id=topic_id,
            stage=None,
            action="done",
            detail=f"Run {topic_id!r} is complete and finalized.",
        )

    def _next_action_guide_v1(
        self,
        topic_id: str,
        stages: tuple[StageStatus, ...],
        finalized: bool,
    ) -> NextAction:
        by_stage = {status.stage: status for status in stages}

        for stage_name in ("spec", "outline", "draft"):
            pending = self._pending_stage_action(topic_id, by_stage[stage_name])
            if pending is not None:
                return pending

        if self.report_state(topic_id, "draft") != "current":
            return NextAction(
                topic_id=topic_id,
                stage="draft",
                action="validate",
                detail=f"Run draft validation for {topic_id!r}.",
            )

        draft_text = self.read_approved(topic_id, "draft")
        if not parse_guide(draft_text).ok:
            return NextAction(
                topic_id=topic_id,
                stage="draft",
                action="resolve_findings",
                detail=(
                    f"Correct and reapprove the draft response for {topic_id!r}; "
                    "the approved draft is too malformed for QA."
                ),
            )

        for stage_name in ("qa", "repair"):
            status = by_stage[stage_name]
            if status.approved and status.stale:
                return self._stale_stage_rebuild_action(topic_id, stage_name)
            pending = self._pending_stage_action(topic_id, status)
            if pending is not None:
                return pending

        if self.report_state(topic_id, "final") != "current":
            return NextAction(
                topic_id=topic_id,
                stage="repair",
                action="validate",
                detail=f"Run final validation for {topic_id!r}.",
            )

        if finalized:
            return NextAction(
                topic_id=topic_id,
                stage=None,
                action="done",
                detail=f"Run {topic_id!r} is complete and finalized.",
            )

        source_text = self.read_approved(topic_id, "repair")
        report = validate_guide(source_text, phase="final")
        waiver_result = apply_waivers(report, self._load_waiver_set(topic_id))
        if not waiver_result.gate_open:
            return NextAction(
                topic_id=topic_id,
                stage="repair",
                action="resolve_findings",
                detail=(
                    f"{waiver_result.effective_blocking} blocking finding(s) remain for "
                    f"{topic_id!r}; non-waivable findings cannot be waived."
                ),
            )

        return NextAction(
            topic_id=topic_id,
            stage=None,
            action="finalize",
            detail=(
                f"Finalize {topic_id!r}: write final/guide.json and final/guide.md "
                f"from the approved repair."
            ),
        )

    def _pending_stage_action(
        self, topic_id: str, status: StageStatus
    ) -> NextAction | None:
        if status.approved:
            return None
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

    def _stale_stage_rebuild_action(self, topic_id: str, stage: str) -> NextAction:
        """When a guide-v1 qa/repair stage is approved but upstream hashes drifted."""

        prompt_event = self._latest_stage_event(topic_id, stage, "prompt_written")
        draft_path = self.stage_paths(topic_id, "draft").approved_path
        draft_sha = (
            hashlib.sha256(draft_path.read_bytes()).hexdigest()
            if draft_path.is_file()
            else None
        )
        needs_prompt = True
        if prompt_event is not None and draft_sha is not None:
            recorded_draft = prompt_event.get("source_draft_file_sha256")
            needs_prompt = recorded_draft != draft_sha
            if stage == "repair" and not needs_prompt:
                qa_path = self.stage_paths(topic_id, "qa").approved_path
                qa_sha = (
                    hashlib.sha256(qa_path.read_bytes()).hexdigest()
                    if qa_path.is_file()
                    else None
                )
                recorded_qa = prompt_event.get("source_qa_file_sha256")
                needs_prompt = recorded_qa != qa_sha

        if needs_prompt:
            return NextAction(
                topic_id=topic_id,
                stage=stage,
                action="write_prompt",
                detail=(
                    f"Upstream content changed for {topic_id!r}; rebuild the {stage} prompt "
                    "(force), re-run it, and reapprove (overwrite)."
                ),
            )
        return NextAction(
            topic_id=topic_id,
            stage=stage,
            action="save_response",
            detail=(
                f"Upstream content changed for {topic_id!r}; re-run the {stage} prompt "
                "and reapprove (overwrite)."
            ),
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

        For guide-v1 runs, spec and outline responses must contain valid fenced
        contract blocks (and outline must not conflict with the approved spec)
        before promotion.
        """

        paths = self.stage_paths(topic_id, stage)
        if not paths.response_path.exists():
            raise ConfigError(
                f"no ingested response to approve for stage {paths.stage!r}: {paths.response_path}"
            )

        text = paths.response_path.read_text(encoding="utf-8")
        if self._is_guide_v1(paths.topic_id) and paths.stage in {"spec", "outline"}:
            self._validate_guide_approval(paths.topic_id, paths.stage, text)
        _write_text(paths.approved_path, text, overwrite=overwrite)
        files: dict[str, Path] = {
            "prompt_file": paths.prompt_path,
            "approved_file": paths.approved_path,
        }
        if self._is_guide_v1(paths.topic_id) and paths.stage in {"qa", "repair"}:
            files["source_draft_file"] = self.stage_paths(paths.topic_id, "draft").approved_path
            if paths.stage == "repair":
                files["source_qa_file"] = self.stage_paths(paths.topic_id, "qa").approved_path
        self._append_event(
            paths.topic_id,
            stage=paths.stage,
            action="response_approved",
            files=files,
        )
        return paths.approved_path

    def ingest_response(
        self, topic_id: str, stage: str, text: str, *, force: bool = False
    ) -> Path:
        """Atomically land an executed provider response as the stage response.

        The written file is byte-for-byte a hand-saved response. Empty or
        whitespace-only output is rejected, and an existing response is never
        clobbered unless ``force`` is set. A forced overwrite records the prior
        response's hash in a ``response_replaced`` manifest event first.
        """

        paths = self.stage_paths(topic_id, stage)
        if not text.strip():
            raise ConfigError(f"refusing to ingest empty response for stage {paths.stage!r}")
        if paths.response_path.exists() and not force:
            raise ConfigError(
                f"response already ingested for stage {paths.stage!r}: {paths.response_path}"
            )
        if paths.response_path.exists() and force:
            self._append_event(
                paths.topic_id,
                stage=paths.stage,
                action="response_replaced",
                files={"replaced_response_file": paths.response_path},
            )
        _write_text_atomic(paths.response_path, text)
        if paths.stub_path.exists():
            paths.stub_path.unlink()
        return paths.response_path

    def edit_response(
        self, topic_id: str, stage: str, text: str, *, base_sha256: str
    ) -> Path:
        """Guarded read-modify-write of an existing stage response.

        Unlike ``ingest_response`` (wholesale create/replace), editing
        presupposes content: the response file must exist and its current
        bytes must hash to ``base_sha256``, otherwise the file changed since
        the caller loaded it and :class:`StaleContentError` is raised. On a
        match the new text is written atomically and a ``response_edited``
        manifest event is recorded — an in-browser edit is an authored change
        worth auditing.
        """

        paths = self.stage_paths(topic_id, stage)
        if not text.strip():
            raise ConfigError(f"refusing to save empty response for stage {paths.stage!r}")
        if not paths.response_path.exists():
            raise ConfigError(
                f"no response to edit for stage {paths.stage!r}: {paths.response_path}"
            )
        current = hashlib.sha256(paths.response_path.read_bytes()).hexdigest()
        if current != base_sha256:
            raise StaleContentError(
                f"the {paths.stage} response changed on disk since it was loaded; "
                "reload the current content before saving"
            )
        _write_text_atomic(paths.response_path, text)
        self._append_event(
            paths.topic_id,
            stage=paths.stage,
            action="response_edited",
            files={"response_file": paths.response_path},
        )
        return paths.response_path

    def append_manifest_event(self, topic_id: str, event: dict) -> None:
        """Append an arbitrary event (with ``recorded_at``) to the run manifest."""

        safe_id = _artifact_id(topic_id, "topic id")
        run = self.run_dir(safe_id)
        with self._manifest_lock(safe_id):
            manifest = self.read_manifest(safe_id)
            entry = dict(event)
            entry.setdefault("recorded_at", datetime.now(timezone.utc).isoformat())
            manifest.setdefault("events", []).append(entry)
            _write_manifest(run / "manifest.json", manifest)

    def record_stage_provenance(
        self,
        topic_id: str,
        stage: str,
        *,
        provider: str,
        model: str | None,
        effort: str | None,
        source: str,
        job_id: str | None = None,
    ) -> None:
        """Append the effective provider/model/effort that ran a stage to
        manifest["stage_provenance"] (created as [] when missing). Append-only;
        re-running a stage appends a new entry rather than replacing the last."""

        safe_id = _artifact_id(topic_id, "topic id")
        run = self.run_dir(safe_id)
        with self._manifest_lock(safe_id):
            manifest = self.read_manifest(safe_id)
            entry = {
                "stage": stage,
                "provider": provider,
                "model": model,
                "effort": effort,
                "source": source,
                "job_id": job_id,
                "recorded_at": datetime.now(timezone.utc).isoformat(),
            }
            manifest.setdefault("stage_provenance", []).append(entry)
            _write_manifest(run / "manifest.json", manifest)

    def final_path(self, topic_id: str) -> Path:
        """Path of the assembled final guide for a run (legacy ``final/guide.md``)."""

        return self.run_dir(topic_id) / "final" / _FINAL_FILENAME

    def final_guide_json_path(self, topic_id: str) -> Path:
        """Path of the guide-v1 final JSON artifact (``final/guide.json``)."""

        return self.final_path(topic_id).with_name("guide.json")

    def final_guide_md_path(self, topic_id: str) -> Path:
        """Path of the guide-v1 projected Markdown artifact (``final/guide.md``)."""

        return self.final_path(topic_id).with_name("guide.md")

    def draft_report_path(self, topic_id: str) -> Path:
        return self.run_dir(topic_id) / "reports" / "draft-validation.json"

    def final_report_path(self, topic_id: str) -> Path:
        return self.run_dir(topic_id) / "reports" / "final-validation.json"

    def waivers_path(self, topic_id: str) -> Path:
        return self.run_dir(topic_id) / "reports" / "validation-waivers.json"

    def export_path(self, topic_id: str, format: str) -> Path:
        """Path an export of ``format`` is (or would be) written to."""

        if format not in EXPORT_FORMATS:
            supported = ", ".join(EXPORT_FORMATS)
            raise ConfigError(f"unsupported export format {format!r}; supported: {supported}")
        name = "guide.bundle.md" if format == "markdown" else "guide.html"
        return self.final_path(topic_id).with_name(name)

    def export_run(
        self,
        topic_id: str,
        *,
        format: str = "html",
        overwrite: bool = False,
    ) -> Path:
        """Export the finalized guide to a distributable format.

        This is an optional deterministic step after ``finalize_run``. ``format``
        is ``"html"`` (a self-contained document) or ``"markdown"`` (the guide
        with a front-matter provenance block). Both are written into ``final/``.
        """

        safe_id = _artifact_id(topic_id, "topic id")
        if self._is_guide_v1(safe_id):
            if format != "html":
                raise ConfigError("guide-v1 runs support only HTML export")
            return self._export_guide_v1(safe_id, overwrite=overwrite)
        export_path = self.export_path(safe_id, format)
        guide = self._read_final_guide(safe_id)
        topic = TopicStore(self.root).load_topic(safe_id)

        if format == "markdown":
            content = build_markdown_bundle(guide, front_matter=self._export_front_matter(safe_id, topic))
        else:
            content = render_markdown_to_html(guide, title=topic.title)

        _write_text(export_path, content, overwrite=overwrite)
        self._append_event(
            safe_id,
            stage="export",
            action="exported",
            files={"export_file": export_path, "source_file": self.final_path(safe_id)},
        )
        return export_path

    def _export_guide_v1(self, topic_id: str, *, overwrite: bool) -> Path:
        """Export only the finalized canonical guide through the packaged runtime."""

        final_json = self.final_guide_json_path(topic_id)
        if not final_json.is_file() or not self.is_finalized(topic_id):
            raise ConfigError(f"run {topic_id!r} is not currently finalized")
        if self.report_state(topic_id, "final") != "current":
            raise ConfigError("final validation is missing or stale; revalidate before export")

        source_text = final_json.read_text(encoding="utf-8")
        report = validate_guide(source_text, phase="final")
        waiver_result = apply_waivers(report, self._load_waiver_set(topic_id))
        if not waiver_result.gate_open:
            raise ConfigError(
                f"cannot export {topic_id!r}: "
                f"{waiver_result.effective_blocking} blocking finding(s) remain"
            )
        parsed = parse_guide(source_text)
        if not parsed.ok:
            raise ConfigError("final/guide.json is not a renderable guide")
        guide = normalize_guide(parsed)
        assets = load_runtime_assets()
        content = assemble_guide_document(guide, assets=assets, mode="export")
        export_path = self.export_path(topic_id, "html")
        if export_path.exists() and not overwrite:
            raise ConfigError(f"refusing to overwrite existing file: {export_path}")
        _write_text_atomic(export_path, content)
        self._append_event(
            topic_id,
            stage="export",
            action="exported",
            files={
                "export_file": export_path,
                "source_file": final_json,
                "report_file": self.final_report_path(topic_id),
            },
            extra={
                "guide_schema_version": guide.schema_version,
                "runtime_version": assets.version,
                "runtime_css_sha256": hashlib.sha256(assets.css.encode("utf-8")).hexdigest(),
                "runtime_js_sha256": hashlib.sha256(assets.javascript.encode("utf-8")).hexdigest(),
                "model_stage_provenance": self._model_stage_provenance(topic_id),
            },
        )
        return export_path

    def _model_stage_provenance(self, topic_id: str) -> dict[str, dict[str, str | None]]:
        """Return the latest non-sensitive provider/model aliases by stage."""

        latest: dict[str, dict[str, str | None]] = {}
        for event in self.read_manifest(topic_id).get("events", []):
            stage = event.get("stage")
            provider = event.get("provider")
            if (
                event.get("action") == "job"
                and stage in SUPPORTED_STAGES
                and isinstance(provider, str)
            ):
                model = event.get("model")
                latest[stage] = {
                    "provider": provider,
                    "model": model if isinstance(model, str) else None,
                }
        return {stage: latest[stage] for stage in SUPPORTED_STAGES if stage in latest}

    def _read_final_guide(self, topic_id: str) -> str:
        path = self.final_path(topic_id)
        try:
            return path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise ConfigError(
                f"run {topic_id!r} is not finalized; run finalize_run first: {path}"
            ) from exc

    def _export_front_matter(self, topic_id: str, topic) -> dict[str, str]:
        front_matter = {
            "title": topic.title,
            "topic_id": topic_id,
            "source": "final/guide.md",
            "generator": "education-pipeline",
        }
        events = self.read_manifest(topic_id).get("events", [])
        finalized = next(
            (event for event in reversed(events) if event.get("action") == "finalized"),
            None,
        )
        if finalized is not None and finalized.get("recorded_at"):
            front_matter["generated"] = finalized["recorded_at"]
        return front_matter

    def is_finalized(self, topic_id: str) -> bool:
        """Whether the run's final guide has been assembled.

        Legacy runs: file existence of ``final/guide.md``. Guide-v1 runs: hash-
        derived — a finalized event must exist, both final artifacts must exist,
        and the event's ``source_file_sha256`` must still match the current
        approved repair bytes.
        """

        safe_id = _artifact_id(topic_id, "topic id")
        if not self._is_guide_v1(safe_id):
            return self.final_path(safe_id).exists()

        final_json = self.final_guide_json_path(safe_id)
        final_md = self.final_guide_md_path(safe_id)
        if not final_json.is_file() or not final_md.is_file():
            return False

        try:
            events = self.read_manifest(safe_id).get("events", [])
        except ConfigError:
            return False

        finalized = next(
            (event for event in reversed(events) if event.get("action") == "finalized"),
            None,
        )
        if finalized is None:
            return False

        recorded = finalized.get("source_file_sha256")
        if not isinstance(recorded, str):
            return False
        source = self.stage_paths(safe_id, _FINAL_SOURCE_STAGE).approved_path
        if not source.is_file():
            return False
        return recorded == hashlib.sha256(source.read_bytes()).hexdigest()

    def finalize_run(self, topic_id: str, *, overwrite: bool = False) -> Path:
        """Assemble the approved final-stage draft into the run's ``final`` guide.

        Legacy: copies the approved repair into ``final/guide.md``. Guide-v1:
        requires a current final validation report with an open waiver gate, then
        writes ``final/guide.json`` and ``final/guide.md`` atomically.
        """

        safe_id = _artifact_id(topic_id, "topic id")
        if self._is_guide_v1(safe_id):
            return self._finalize_guide_v1(safe_id, overwrite=overwrite)

        content = self.read_approved(safe_id, _FINAL_SOURCE_STAGE)
        self.create_run(safe_id)
        final = self.final_path(safe_id)
        _write_text(final, content, overwrite=overwrite)
        self._append_event(
            safe_id,
            stage="finalize",
            action="finalized",
            files={
                "final_file": final,
                "source_file": self.stage_paths(safe_id, _FINAL_SOURCE_STAGE).approved_path,
            },
        )
        return final

    def _finalize_guide_v1(self, topic_id: str, *, overwrite: bool) -> Path:
        source_text = self.read_approved(topic_id, _FINAL_SOURCE_STAGE)
        if self.report_state(topic_id, "final") != "current":
            raise ConfigError(
                f"final validation is missing or stale for {topic_id!r}; "
                "run final validation before finalizing"
            )

        report = validate_guide(source_text, phase="final")
        waiver_result = apply_waivers(report, self._load_waiver_set(topic_id))
        if not waiver_result.gate_open:
            parts = [
                f"cannot finalize {topic_id!r}: "
                f"{waiver_result.effective_blocking} blocking finding(s) remain"
            ]
            if waiver_result.stale:
                parts.append("stale waivers were ignored")
            if waiver_result.rejected_finding_ids:
                parts.append(
                    "non-waivable or empty-reason waivers were rejected: "
                    + ", ".join(waiver_result.rejected_finding_ids)
                )
            raise ConfigError("; ".join(parts))

        parsed = parse_guide(source_text)
        if not parsed.ok:
            raise ConfigError(
                f"cannot finalize {topic_id!r}: approved repair is not valid guide JSON"
            )
        guide = normalize_guide(parsed)
        guide_json = canonical_guide_bytes(guide)
        guide_md = project_guide_markdown(guide)

        final_json = self.final_guide_json_path(topic_id)
        final_md = self.final_guide_md_path(topic_id)
        if not overwrite:
            if final_json.exists() or final_md.exists():
                raise ConfigError(
                    f"refusing to overwrite existing final guide artifacts for {topic_id!r}: "
                    f"{final_json} / {final_md}"
                )

        self.create_run(topic_id)
        _write_bytes_atomic(final_json, guide_json)
        _write_bytes_atomic(final_md, guide_md.encode("utf-8"))
        self._append_event(
            topic_id,
            stage="finalize",
            action="finalized",
            files={
                "final_json_file": final_json,
                "final_md_file": final_md,
                "source_file": self.stage_paths(topic_id, _FINAL_SOURCE_STAGE).approved_path,
                "report_file": self.final_report_path(topic_id),
            },
            extra={
                "guide_sha256": guide_sha256(guide),
                "schema_version": guide.schema_version,
            },
        )
        return final_json

    def report_state(self, topic_id: str, phase: str) -> str:
        """Return ``missing`` | ``current`` | ``stale`` for a validation report.

        Freshness is content-derived from the source approved artifact hash,
        never from file-existence alone.
        """

        safe_id = _artifact_id(topic_id, "topic id")
        if not self._is_guide_v1(safe_id):
            raise ConfigError("validation applies only to guide runs")
        if phase not in {"draft", "final"}:
            raise ConfigError(f"phase must be 'draft' or 'final'; got {phase!r}")

        source_stage = "draft" if phase == "draft" else "repair"
        source_path = self.stage_paths(safe_id, source_stage).approved_path
        report_path = (
            self.draft_report_path(safe_id) if phase == "draft" else self.final_report_path(safe_id)
        )
        if not source_path.is_file() or not report_path.is_file():
            return "missing"

        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return "stale"
        if not isinstance(report, dict) or report.get("phase") != phase:
            return "stale"
        recorded = report.get("guide_sha256")
        if not isinstance(recorded, str):
            return "stale"
        source_text = source_path.read_text(encoding="utf-8")
        if recorded == _guide_source_sha(source_text):
            return "current"
        return "stale"

    def validate_run(self, topic_id: str, phase: str) -> Path:
        """Run deterministic validation and write the phase report atomically."""

        safe_id = _artifact_id(topic_id, "topic id")
        if not self._is_guide_v1(safe_id):
            raise ConfigError("validation applies only to guide runs")
        if phase not in {"draft", "final"}:
            raise ConfigError(f"phase must be 'draft' or 'final'; got {phase!r}")

        source_stage = "draft" if phase == "draft" else "repair"
        source_path = self.stage_paths(safe_id, source_stage).approved_path
        if not source_path.is_file():
            raise ConfigError(
                f"approved {source_stage} response not found: {source_path}"
            )
        source_text = source_path.read_text(encoding="utf-8")
        report = validate_guide(source_text, phase=phase)
        report_path = (
            self.draft_report_path(safe_id) if phase == "draft" else self.final_report_path(safe_id)
        )
        self.create_run(safe_id)
        _write_bytes_atomic(report_path, canonical_report_bytes(report))
        self._append_event(
            safe_id,
            stage=source_stage,
            action="validated",
            files={"report_file": report_path, "source_file": source_path},
            extra={"phase": phase},
        )
        return report_path

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
        otherwise compiles with broadly accessible defaults. Guide-v1 runs
        use the contract-aware guide-v1 compiler.
        """

        safe_id = _artifact_id(topic_id, "topic id")
        # Materialize the run first so a missing manifest takes the new default
        # (interactive_guide 1.0) before compiler selection.
        self.create_run(safe_id)
        profile = self._load_attached_profile(safe_id)
        spec_input = SpecPromptInput(
            topic_id=safe_id,
            title=title,
            topic_brief=topic_brief,
            profile=profile,
        )
        if self._is_guide_v1(safe_id):
            artifact = compile_guide_v1_spec_prompt(spec_input)
        else:
            artifact = compile_spec_prompt(spec_input)
        return self._write_prompt(artifact, overwrite=overwrite)

    def write_topic_spec_prompt(
        self,
        topic_id: str,
        *,
        overwrite: bool = False,
    ) -> PromptFile:
        """Compile and write the spec prompt from a stored topic artifact.

        Loads the topic from the workspace ``topics`` directory and reuses the
        topic's attached learner profile snapshot when one exists. Guide-v1
        runs compile from the topic's id, title, and brief only.
        """

        safe_id = _artifact_id(topic_id, "topic id")
        # Materialize the run first so a missing manifest takes the new default
        # (interactive_guide 1.0) before compiler selection.
        self.create_run(safe_id)
        topic = TopicStore(self.root).load_topic(safe_id)
        profile = self._load_attached_profile(safe_id)
        if self._is_guide_v1(safe_id):
            artifact = compile_guide_v1_spec_prompt(
                SpecPromptInput(
                    topic_id=topic.id,
                    title=topic.title,
                    topic_brief=topic.brief,
                    profile=profile,
                )
            )
        else:
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
        attached learner profile snapshot when one exists. Guide-v1 runs use
        the contract-aware outline compiler and record the approved-spec source
        hash on the prompt_written event.
        """

        safe_id = _artifact_id(topic_id, "topic id")
        topic = TopicStore(self.root).load_topic(safe_id)
        approved_spec = self.read_approved(safe_id, "spec")
        profile = self._load_attached_profile(safe_id)
        if self._is_guide_v1(safe_id):
            artifact = compile_guide_v1_outline_prompt(topic, approved_spec, profile)
            extra_files = {
                "source_spec_file": self.stage_paths(safe_id, "spec").approved_path,
            }
        else:
            artifact = compile_outline_prompt(topic, approved_spec, profile)
            extra_files = None
        return self._write_prompt(artifact, overwrite=overwrite, extra_event_files=extra_files)

    def write_draft_prompt(
        self,
        topic_id: str,
        *,
        overwrite: bool = False,
    ) -> PromptFile:
        """Compile and write the draft prompt from the approved outline.

        Requires the outline stage to have been approved, and reuses the topic's
        attached learner profile snapshot when one exists. Guide-v1 runs also
        write immutable ``inputs/guide-contract.json`` and embed those bytes in
        the draft prompt.
        """

        safe_id = _artifact_id(topic_id, "topic id")
        topic = TopicStore(self.root).load_topic(safe_id)
        approved_outline = self.read_approved(safe_id, "outline")
        profile = self._load_attached_profile(safe_id)
        if self._is_guide_v1(safe_id):
            self.create_run(safe_id)
            contract_bytes = self._write_guide_contract(safe_id, profile=profile, overwrite=overwrite)
            artifact = compile_guide_v1_draft_prompt(
                topic, approved_outline, contract_bytes, profile
            )
            extra_files = {
                "source_outline_file": self.stage_paths(safe_id, "outline").approved_path,
                "contract_file": self._guide_contract_path(safe_id),
            }
        else:
            artifact = compile_draft_prompt(topic, approved_outline, profile)
            extra_files = None
        return self._write_prompt(artifact, overwrite=overwrite, extra_event_files=extra_files)

    def write_qa_prompt(
        self,
        topic_id: str,
        *,
        overwrite: bool = False,
    ) -> PromptFile:
        """Compile and write the QA prompt from the approved draft, spec, and outline.

        Requires the spec, outline, and draft stages to have been approved, and
        reuses the topic's attached learner profile snapshot when one exists.
        Guide-v1 runs also require a current draft validation report and a
        parseable approved draft.
        """

        safe_id = _artifact_id(topic_id, "topic id")
        topic = TopicStore(self.root).load_topic(safe_id)
        approved_spec = self.read_approved(safe_id, "spec")
        approved_outline = self.read_approved(safe_id, "outline")
        approved_draft = self.read_approved(safe_id, "draft")
        profile = self._load_attached_profile(safe_id)
        if self._is_guide_v1(safe_id):
            state = self.report_state(safe_id, "draft")
            if state != "current":
                if state == "missing":
                    raise ConfigError(
                        f"draft validation is required before QA for {safe_id!r}; "
                        "run draft validation first"
                    )
                raise ConfigError(
                    f"draft validation is stale for {safe_id!r}; "
                    "the draft changed and must be revalidated before QA"
                )
            parsed = parse_guide(approved_draft)
            if not parsed.ok:
                raise ConfigError(
                    f"approved draft for {safe_id!r} is too malformed for QA; "
                    "correct and reapprove the draft response"
                )
            draft_guide_json = canonical_guide_bytes(normalize_guide(parsed)).decode("utf-8")
            draft_findings_json = self.draft_report_path(safe_id).read_text(encoding="utf-8")
            artifact = compile_guide_v1_qa_prompt(
                topic,
                approved_spec=approved_spec,
                approved_outline=approved_outline,
                draft_guide_json=draft_guide_json,
                draft_findings_json=draft_findings_json,
                profile=profile,
            )
            extra_files = {
                "source_draft_file": self.stage_paths(safe_id, "draft").approved_path,
                "draft_report_file": self.draft_report_path(safe_id),
            }
            return self._write_prompt(
                artifact, overwrite=overwrite, extra_event_files=extra_files
            )
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
        topic's attached learner profile snapshot when one exists. Guide-v1 runs
        also require a current draft report and the guide contract file.
        """

        safe_id = _artifact_id(topic_id, "topic id")
        topic = TopicStore(self.root).load_topic(safe_id)
        approved_draft = self.read_approved(safe_id, "draft")
        approved_qa = self.read_approved(safe_id, "qa")
        profile = self._load_attached_profile(safe_id)
        if self._is_guide_v1(safe_id):
            state = self.report_state(safe_id, "draft")
            if state != "current":
                if state == "missing":
                    raise ConfigError(
                        f"draft validation is required before repair for {safe_id!r}; "
                        "run draft validation first"
                    )
                raise ConfigError(
                    f"draft validation is stale for {safe_id!r}; "
                    "the draft changed and must be revalidated before repair"
                )
            contract_path = self._guide_contract_path(safe_id)
            if not contract_path.is_file():
                raise ConfigError(
                    f"guide contract not found for {safe_id!r}: {contract_path}"
                )
            parsed = parse_guide(approved_draft)
            if not parsed.ok:
                raise ConfigError(
                    f"approved draft for {safe_id!r} is too malformed for repair; "
                    "correct and reapprove the draft response"
                )
            draft_guide_json = canonical_guide_bytes(normalize_guide(parsed)).decode("utf-8")
            draft_findings_json = self.draft_report_path(safe_id).read_text(encoding="utf-8")
            artifact = compile_guide_v1_repair_prompt(
                topic,
                draft_guide_json=draft_guide_json,
                qa_findings_markdown=approved_qa,
                draft_findings_json=draft_findings_json,
                guide_contract=contract_path.read_bytes(),
                profile=profile,
            )
            extra_files = {
                "source_draft_file": self.stage_paths(safe_id, "draft").approved_path,
                "source_qa_file": self.stage_paths(safe_id, "qa").approved_path,
                "draft_report_file": self.draft_report_path(safe_id),
                "contract_file": contract_path,
            }
            return self._write_prompt(
                artifact, overwrite=overwrite, extra_event_files=extra_files
            )
        artifact = compile_repair_prompt(
            topic,
            approved_draft=approved_draft,
            approved_qa=approved_qa,
            profile=profile,
        )
        return self._write_prompt(artifact, overwrite=overwrite)

    def _write_prompt(
        self,
        artifact: PromptArtifact,
        *,
        overwrite: bool,
        extra_event_files: dict[str, Path] | None = None,
    ) -> PromptFile:
        paths = self.stage_paths(artifact.topic_id, artifact.stage)
        self.create_run(artifact.topic_id)

        _write_text(paths.prompt_path, artifact.text, overwrite=overwrite)
        if not paths.response_path.exists():
            _write_text(paths.stub_path, _stub_text(paths), overwrite=True)

        files: dict[str, Path] = {
            "prompt_file": paths.prompt_path,
            "response_file": paths.response_path,
        }
        if extra_event_files:
            files.update(extra_event_files)
        self._append_event(
            artifact.topic_id,
            stage=paths.stage,
            action="prompt_written",
            files=files,
        )
        return PromptFile(
            stage=paths.stage,
            topic_id=paths.topic_id,
            prompt_path=paths.prompt_path,
            response_path=paths.response_path,
            stub_path=paths.stub_path,
            artifact=artifact,
        )

    def _is_guide_v1(self, topic_id: str) -> bool:
        return self.content_contract(topic_id).kind == "interactive_guide"

    def _guide_contract_path(self, topic_id: str) -> Path:
        return self.run_dir(topic_id) / "inputs" / _GUIDE_CONTRACT_FILENAME

    def _validate_guide_approval(self, topic_id: str, stage: str, response_text: str) -> None:
        """Raise ConfigError if a guide-v1 spec/outline response fails its contract gate."""

        try:
            if stage == "spec":
                extract_spec_contract(response_text)
            elif stage == "outline":
                outline_contract = extract_outline_contract(response_text)
                spec_contract = extract_spec_contract(self.read_approved(topic_id, "spec"))
                check_contract_conflict(spec_contract, outline_contract)
        except ContractError as exc:
            raise ConfigError(
                f"cannot approve {stage} for guide run {topic_id!r}: {exc}"
            ) from exc

    def _publishable_profile_summary(self, profile) -> str | None:
        if profile is None:
            return None
        if not profile.privacy.include_in_published_output:
            return None
        summary = profile.privacy.publishable_summary
        if not summary:
            return None
        return summary

    def _write_guide_contract(self, topic_id: str, *, profile, overwrite: bool) -> bytes:
        """Build and atomically write ``inputs/guide-contract.json`` for a guide-v1 draft.

        Returns the bytes actually on disk after the write (or no-op when the
        existing file already matches). Divergent bytes without ``overwrite``
        raise: the guide contract is immutable once established.
        """

        try:
            spec_contract = extract_spec_contract(self.read_approved(topic_id, "spec"))
            outline_contract = extract_outline_contract(self.read_approved(topic_id, "outline"))
        except ContractError as exc:
            raise ConfigError(
                f"cannot build guide contract for run {topic_id!r}: {exc}"
            ) from exc

        contract_bytes = build_guide_contract(
            spec_contract,
            outline_contract,
            publishable_profile_summary=self._publishable_profile_summary(profile),
        )
        path = self._guide_contract_path(topic_id)
        if path.exists():
            existing = path.read_bytes()
            if existing == contract_bytes:
                return existing
            if not overwrite:
                raise ConfigError(
                    f"guide contract is immutable and requires an explicit overwrite/rebuild: {path}"
                )
        _write_bytes_atomic(path, contract_bytes)
        return contract_bytes

    def _load_attached_profile(self, topic_id: str):
        snapshot_path = ProfileStore(self.root).topic_profile_snapshot_path(topic_id)
        if not snapshot_path.exists():
            return None
        return ProfileStore(self.root).load_topic_profile_snapshot(topic_id)

    def _load_waiver_set(self, topic_id: str) -> WaiverSet | None:
        path = self.waivers_path(topic_id)
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ConfigError(f"invalid validation waivers file: {path}") from exc
        if not isinstance(payload, dict):
            raise ConfigError(f"invalid validation waivers file: {path}")
        schema_version = payload.get("schema_version")
        guide_hash = payload.get("guide_sha256")
        waivers_raw = payload.get("waivers")
        if schema_version != 1:
            raise ConfigError(f"invalid validation waivers file: {path}")
        if not isinstance(guide_hash, str) or not isinstance(waivers_raw, list):
            raise ConfigError(f"invalid validation waivers file: {path}")
        waivers: list[Waiver] = []
        for item in waivers_raw:
            if not isinstance(item, dict):
                raise ConfigError(f"invalid validation waivers file: {path}")
            finding_id = item.get("finding_id")
            reason = item.get("reason")
            if not isinstance(finding_id, str) or not isinstance(reason, str):
                raise ConfigError(f"invalid validation waivers file: {path}")
            waivers.append(Waiver(finding_id=finding_id, reason=reason))
        return WaiverSet(guide_sha256=guide_hash, waivers=tuple(waivers), schema_version=1)

    def _latest_stage_event(
        self, topic_id: str, stage: str, action: str
    ) -> dict | None:
        path = self.manifest_path(topic_id)
        if not path.is_file():
            return None
        try:
            events = self.read_manifest(topic_id).get("events", [])
        except ConfigError:
            return None
        for event in reversed(events):
            if event.get("stage") == stage and event.get("action") == action:
                return event
        return None

    def _stage_upstream_stale(self, topic_id: str, stage: str) -> bool:
        """True when an approved guide-v1 qa/repair stage's recorded upstream hashes drifted."""

        event = self._latest_stage_event(topic_id, stage, "response_approved")
        if event is None:
            return False

        draft_path = self.stage_paths(topic_id, "draft").approved_path
        recorded_draft = event.get("source_draft_file_sha256")
        if recorded_draft is None:
            return False
        if not draft_path.is_file():
            return True
        if recorded_draft != hashlib.sha256(draft_path.read_bytes()).hexdigest():
            return True

        if stage == "repair":
            recorded_qa = event.get("source_qa_file_sha256")
            if recorded_qa is None:
                return False
            qa_path = self.stage_paths(topic_id, "qa").approved_path
            if not qa_path.is_file():
                return True
            if recorded_qa != hashlib.sha256(qa_path.read_bytes()).hexdigest():
                return True
        return False

    def _append_event(
        self,
        topic_id: str,
        *,
        stage: str,
        action: str,
        files: dict[str, Path],
        extra: dict[str, object] | None = None,
    ) -> None:
        safe_id = _artifact_id(topic_id, "topic id")
        run = self.run_dir(safe_id)
        with self._manifest_lock(safe_id):
            manifest = self.read_manifest(safe_id)
            event: dict[str, str] = {"stage": stage, "action": action}
            for label, path in files.items():
                event[label] = _relative_to(path, run)
                if path.is_file():
                    event[f"{label}_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
            if extra:
                event.update(extra)
            event["recorded_at"] = datetime.now(timezone.utc).isoformat()
            manifest.setdefault("events", []).append(event)
            _write_manifest(run / "manifest.json", manifest)


def _guide_source_sha(text: str) -> str:
    """Hash the guide source the same way ``validate_guide`` records ``guide_sha256``."""

    raw = text.encode("utf-8")
    if len(raw) > 2_000_000:
        return hashlib.sha256(raw).hexdigest()
    parsed = parse_guide(text)
    if not parsed.ok:
        return hashlib.sha256(raw).hexdigest()
    return guide_sha256(normalize_guide(parsed))


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
    _write_bytes_atomic(path, (json.dumps(manifest, indent=2) + "\n").encode("utf-8"))


def _write_text(path: Path, text: str, *, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise ConfigError(f"refusing to overwrite existing file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_text_atomic(path: Path, text: str) -> None:
    _write_bytes_atomic(path, text.encode("utf-8"))


def _write_bytes_atomic(path: Path, data: bytes) -> None:
    import os
    import tempfile

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=path.suffix)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _supported_stage(stage: str) -> str:
    if stage not in SUPPORTED_STAGES:
        known = ", ".join(SUPPORTED_STAGES)
        raise ConfigError(f"unsupported run stage {stage!r}; supported stages: {known}")
    return stage


def _parse_content_contract(value: object) -> ContentContract:
    if value is None:
        return ContentContract.legacy_markdown()
    if not isinstance(value, dict):
        raise ConfigError("run manifest content_contract must be an object")
    unknown = set(value) - {"kind", "schema_version"}
    if unknown:
        raise ConfigError(
            "run manifest content_contract has unsupported fields: "
            + ", ".join(sorted(unknown))
        )
    kind = value.get("kind")
    schema_version = value.get("schema_version")
    if not isinstance(kind, str) or (
        schema_version is not None and not isinstance(schema_version, str)
    ):
        raise ConfigError("run manifest content_contract fields must be strings")
    contract = ContentContract(kind=kind, schema_version=schema_version)
    _validate_content_contract(contract)
    return contract


def _validate_content_contract(contract: ContentContract) -> None:
    if contract == ContentContract.legacy_markdown():
        return
    if contract == ContentContract.interactive_guide_v1():
        return
    raise ConfigError(
        "unsupported content contract "
        f"{contract.kind!r} schema {contract.schema_version!r}; supported contracts are "
        "legacy_markdown and interactive_guide schema '1.0'"
    )


def _artifact_id(value: str, context: str) -> str:
    if not _is_artifact_id(value):
        raise ConfigError(
            f"{context} must match {_ARTIFACT_ID_PATTERN.pattern!r}; got {value!r}"
        )
    return value


def _is_artifact_id(value: str) -> bool:
    return isinstance(value, str) and _ARTIFACT_ID_PATTERN.fullmatch(value) is not None
