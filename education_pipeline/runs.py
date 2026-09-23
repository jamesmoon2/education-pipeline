"""Workspace-local run directories, prompt files, and manifest logging."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import ClassVar
import hashlib
import json
import stat
import threading

from education_pipeline.config import (
    OPTIONAL_STAGES,
    # Re-exported: the legacy stage list moved to run_modes with the legacy
    # next-action walk, but importers (and tests) still read it from here.
    REQUIRED_STAGES,
    SUPPORTED_STAGES,
    ConfigError,
)
from education_pipeline.stage_graph import (
    required_stages as graph_required_stages,
    source_labels as graph_source_labels,
    sources_of as graph_sources_of,
    stage as stage_spec,
)
from education_pipeline.guides import (
    ContractError,
    DEFAULT_GUIDE_SCHEMA_VERSION,
    SUPPORTED_GUIDE_SCHEMA_VERSIONS,
    apply_waivers,
    canonical_guide_bytes,
    check_contract_conflict,
    extract_outline_contract,
    extract_spec_contract,
    normalize_guide,
    parse_guide,
)
from education_pipeline.guides.audit import (
    AuditResponseError,
    parse_audit_response,
)
from education_pipeline.privacy import profile_private_values
from education_pipeline.profiles import LearnerProfile
from education_pipeline.topics import Topic
from education_pipeline.prompts import (
    PromptArtifact,
    SpecPromptInput,
    compile_guide_v1_draft_prompt,
    compile_guide_v1_factcheck_prompt,
    compile_guide_v1_module_repair_prompt,
    compile_guide_v1_outline_prompt,
    compile_guide_v1_qa_prompt,
    compile_guide_v1_repair_prompt,
    compile_guide_v1_section_repair_prompt,
    compile_guide_v1_spec_prompt,
)
from education_pipeline.run_modes import CompiledPrompt, _RunMode, mode_for_kind
from education_pipeline.guides.canonical import (
    SpliceError,
    splice_module,
    splice_section,
)
from education_pipeline.guides.blueprints import (
    Blueprint,
    get_blueprint,
    recommend_blueprint,
)
from education_pipeline.atomic_io import read_bytes_retrying
from education_pipeline.workspace_lock import workspace_lock
from education_pipeline.workspace import (
    TopicStore,
    # Run ids are workspace artifact ids: one validator, one message, no
    # matter which surface rejected the id (``workspace`` is upstream of
    # ``runs``, so the shared definition lives there).
    artifact_id as _artifact_id,
    is_artifact_id as _is_artifact_id,
)
from education_pipeline.runs_reports import (
    # Re-exported: the report/quality/validation half of ``RunStore`` moved to
    # ``runs_reports`` with its dataclasses and its guide-source digest memo,
    # but importers (and tests) still read those names from here.
    PersonalizationSnapshot,
    ReportsMixin,
    _GUIDE_SOURCE_SHA_MEMO,
    _GUIDE_SOURCE_SHA_MEMO_LIMIT,
    _GUIDE_SOURCE_SHA_MEMO_LOCK,
    _PublicAuditSnapshot,
    _ValidationArtifacts,
    _guide_source_sha,
)
from education_pipeline.runs_waivers import WaiversMixin
from education_pipeline.runs_personalization import PersonalizationMixin
from education_pipeline.runs_finalize import FinalizeMixin
from education_pipeline.runs_draft_units import DraftUnitsMixin
from education_pipeline.run_core import (
    # Re-exported: the shared leaf primitives and value types moved to
    # ``run_core`` so every mixin can import them at module scope, but
    # importers (and tests) still read them from here.
    AdvanceResult,
    AssembleResult,
    AssembledStatus,
    DraftProgress,
    DraftUnitPaths,
    DraftUnitStatus,
    MARKDOWN_CONTENT_TYPE,
    NextAction,
    PromptFile,
    RepairScope,
    RunStatus,
    StageStatus,
    StagePaths,
    StaleContentError,
    _FINAL_SOURCE_STAGE,
    _relative_to,
    _stub_text,
    _write_bytes_atomic,
    _write_text,
    _write_text_atomic,
)


MANIFEST_SCHEMA_VERSION = 1

RUN_SUBDIRS = ("inputs", "prompts", "responses", "approved", "reports", "final")

_PROMPT_SUFFIX = ".prompt.md"

JSON_CONTENT_TYPE = "application/json"
GUIDE_V1_CONTENT_TYPE = (
    "application/vnd.education-pipeline.guide+json;version=1.0"
)


def _repair_scope_event(scope: RepairScope | None) -> dict[str, object] | None:
    """The manifest keys that record a scoped repair, or None for no scope.

    ``repair_section`` sits beside ``repair_module`` and is written only for a
    section scope, so a module-scoped event stays exactly the shape it has
    always had and an older manifest still reads back as a module scope.
    """

    if scope is None:
        return None
    event: dict[str, object] = {"repair_module": scope.module_id}
    if scope.section_id is not None:
        event["repair_section"] = scope.section_id
    return event

#: Per-thread manifest read scope. While a scope is open on the calling
#: thread, ``entries`` maps a manifest path to the dict parsed from it once,
#: and ``depth`` counts nested opens so an inner ``with`` never ends the outer
#: one. Both are cleared when the outermost scope exits: this is a
#: request-scoped cache, so nothing survives from one status read to the next
#: and a manifest written by another process is picked up on the next request.
#: It is thread-local because the daemon serves requests on a thread pool and
#: one request's snapshot must never be handed to another.
_MANIFEST_READ_SCOPE = threading.local()


def _manifest_scope_entries() -> dict[str, dict] | None:
    """Return the calling thread's open scope map, or ``None`` if none is open."""

    return getattr(_MANIFEST_READ_SCOPE, "entries", None)


def _manifest_scope_discard(path: Path) -> None:
    """Drop ``path`` from the calling thread's scope, if one is open.

    Called from every manifest write so a read-modify-write inside one scope
    can never observe the pre-write copy it just replaced.
    """

    entries = _manifest_scope_entries()
    if entries is not None:
        entries.pop(str(path), None)


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

    @classmethod
    def interactive_guide_v1_1(cls) -> ContentContract:
        return cls(kind="interactive_guide", schema_version="1.1")

    @classmethod
    def interactive_guide_v1_2(cls) -> ContentContract:
        return cls(kind="interactive_guide", schema_version="1.2")

    def to_manifest(self) -> dict[str, str]:
        value = {"kind": self.kind}
        if self.schema_version is not None:
            value["schema_version"] = self.schema_version
        return value




class _TopicWriteLock:
    """A per-topic thread lock paired with the workspace's file lock.

    Exposes exactly the ``threading.Lock`` protocol its callers use --
    ``with``, ``acquire(timeout=...)``, ``release()`` -- and additionally
    holds :func:`~education_pipeline.workspace_lock.workspace_lock` for the
    same critical section, so a second *process* (a CLI invocation running
    beside the daemon) cannot interleave its own manifest read-modify-write
    with this one.

    The thread lock stays plain and non-reentrant and is taken first: an
    attempted nested acquire still blocks loudly rather than silently losing
    an update, and a failed acquisition never touches the workspace lock.
    """

    __slots__ = ("_lock", "_root", "_workspace_locks")

    def __init__(self, lock: threading.Lock, root: Path) -> None:
        self._lock = lock
        self._root = root
        # Held-lock stack: one entry per successful acquire, popped in
        # release. The thread lock makes this at most one deep.
        self._workspace_locks: list = []

    def acquire(self, blocking: bool = True, timeout: float = -1) -> bool:
        if not self._lock.acquire(blocking, timeout):
            return False
        guard = workspace_lock(self._root)
        try:
            guard.__enter__()
        except BaseException:
            self._lock.release()
            raise
        self._workspace_locks.append(guard)
        return True

    def release(self) -> None:
        guard = self._workspace_locks.pop()
        try:
            guard.__exit__(None, None, None)
        finally:
            self._lock.release()

    def locked(self) -> bool:
        return self._lock.locked()

    def __enter__(self) -> "_TopicWriteLock":
        self.acquire()
        return self

    def __exit__(self, *exc_info) -> bool:
        self.release()
        return False


@dataclass(frozen=True)
class RunStore(
    WaiversMixin, ReportsMixin, PersonalizationMixin, FinalizeMixin, DraftUnitsMixin
):
    """Create run directories and write stage prompt/response artifacts."""

    root: Path
    # Per-instance runtime state, not dataclass fields: assigned in __init__ via
    # object.__setattr__ because the dataclass is frozen. Annotated as ClassVar
    # so the dataclass machinery does not treat them as fields (which would
    # pull them into __init__/__repr__/__eq__ and require defaults).
    _manifest_locks: ClassVar[dict[str, _TopicWriteLock]]
    _manifest_locks_guard: ClassVar[threading.Lock]
    _validation_memo: ClassVar[dict[tuple, object]]
    _validation_memo_guard: ClassVar[threading.Lock]

    def __init__(self, root: str | Path) -> None:
        object.__setattr__(self, "root", Path(root))
        object.__setattr__(self, "_manifest_locks", {})
        object.__setattr__(self, "_manifest_locks_guard", threading.Lock())
        object.__setattr__(self, "_validation_memo", {})
        object.__setattr__(self, "_validation_memo_guard", threading.Lock())

    @contextmanager
    def manifest_read_scope(self) -> Iterator[None]:
        """Read each run manifest from disk at most once for the duration.

        ``read_manifest`` re-reads and re-parses the whole manifest file on
        every call, and one ``run_status``/``run_status_payload`` makes dozens
        of them for a single topic -- ``content_contract`` alone re-reads it
        from every ``stage_paths`` call. This scope makes those reads share
        one parse.

        Deliberately request-scoped, not persistent. Entries are discarded
        when the outermost scope exits, so a manifest written by another
        process (a concurrent CLI invocation) is picked up by the very next
        request, exactly as today. Within a request this is strictly *more*
        consistent than the status quo, where those dozens of separate reads
        can each observe a different manifest state.

        Nesting is a no-op tracked by a depth counter, so a caller that
        already holds a scope can call one that opens its own. Scopes are
        per-thread: see :data:`_MANIFEST_READ_SCOPE`.

        The dict handed back by :meth:`read_manifest` is shared for the life
        of the scope, so callers must not mutate it. Read-modify-write paths
        use :meth:`_read_manifest_for_update`, which never consults the scope.
        """

        depth = getattr(_MANIFEST_READ_SCOPE, "depth", 0)
        if depth == 0:
            _MANIFEST_READ_SCOPE.entries = {}
        _MANIFEST_READ_SCOPE.depth = depth + 1
        try:
            yield
        finally:
            _MANIFEST_READ_SCOPE.depth = depth
            if depth == 0:
                _MANIFEST_READ_SCOPE.entries = None

    def _manifest_write_lock(self, topic_id: str) -> _TopicWriteLock:
        """Return the per-topic lock serializing writes to this run's manifest
        and waivers file.

        Thread serialization is scoped to this ``RunStore`` instance: it
        protects concurrent threads (e.g. daemon workers) sharing one
        ``RunStore`` over the same workspace from racing on the same run's
        manifest or waivers file, so callers must share a single
        ``RunStore`` per workspace to get that guarantee. Concurrency
        *between processes* (a CLI invocation beside the daemon) is covered
        by the workspace file lock this lock also holds for the critical
        section -- see :class:`_TopicWriteLock`. Critical sections must
        therefore stay short, and are never held across a provider job.

        This is a plain, non-reentrant ``threading.Lock``, deliberately: the
        invariant is exactly one manifest (or waivers) read-modify-write
        cycle per critical section. Reentrancy would let a method take this
        lock, call another lock-taking method on the same thread, and have
        that inner call perform its own read-modify-write and write the file
        -- only for the outer method to then overwrite the file again from
        its now-stale in-memory snapshot, silently discarding the inner
        call's update. A plain lock instead makes any such nesting deadlock
        immediately and loudly, which is far preferable to a silent lost
        update.

        To compose two writes into a single critical section, do NOT call a
        public lock-taking method (e.g. :meth:`append_manifest_event`,
        :meth:`record_stage_provenance`) from inside another one -- that is
        exactly the nested-acquire hazard above, and will deadlock by
        design. Instead take this lock once and call the unlocked
        ``_locked`` primitive(s) directly (e.g.
        :meth:`_append_manifest_event_locked`,
        :meth:`_record_stage_provenance_locked`), which assume the caller
        already holds the lock and perform a single read-modify-write.
        """

        with self._manifest_locks_guard:
            existing = self._manifest_locks.get(topic_id)
            if existing is None:
                existing = _TopicWriteLock(threading.Lock(), self.root)
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
        content = stage_spec(safe_stage).content
        is_guide_json = contract.kind == "interactive_guide" and content == "guide"
        is_json = is_guide_json or content == "json"
        suffix = ".json" if is_json else ".md"
        response_suffix = f".response{suffix}"
        stub_suffix = f".SAVE_RESPONSE_HERE{suffix}"
        run = self.runs_dir / safe_id
        content_type = MARKDOWN_CONTENT_TYPE
        if is_guide_json:
            content_type = _guide_content_type(contract.schema_version)
        elif content == "json":
            content_type = JSON_CONTENT_TYPE
        return StagePaths(
            stage=safe_stage,
            topic_id=safe_id,
            prompt_path=run / "prompts" / f"{safe_stage}{_PROMPT_SUFFIX}",
            response_path=run / "responses" / f"{safe_stage}{response_suffix}",
            stub_path=run / "responses" / f"{safe_stage}{stub_suffix}",
            approved_path=run / "approved" / f"{safe_stage}{suffix}",
            content_type=content_type,
        )

    def content_contract(self, topic_id: str) -> ContentContract:
        """Return the validated manifest contract without mutating legacy runs.

        A missing manifest means a legacy Markdown run. That is read off
        ``read_manifest``'s own ``FileNotFoundError`` handling rather than a
        separate ``exists()`` probe: the probe was an extra stat plus an extra
        path build on the hottest read in the codebase -- ``stage_paths`` calls
        this, and a single status read calls ``stage_paths`` dozens of times.
        """

        try:
            manifest = self.read_manifest(topic_id)
        except (ConfigError, NotADirectoryError):
            # NotADirectoryError keeps this exactly equivalent to the old
            # Path.exists() probe, which swallowed it into "no manifest".
            return ContentContract.legacy_markdown()
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
        blueprint: str | None = None,
    ) -> Path:
        """Create the run directory tree and initialize a manifest if needed.

        Newly created manifests default to interactive-guide schema ``1.2``
        (with or without an attached profile) when ``content_contract`` is
        omitted; existing manifests keep their recorded version. Pass
        :meth:`ContentContract.legacy_markdown` for an explicit legacy Markdown
        run. When a manifest already exists and ``content_contract`` is omitted,
        the existing run is left unchanged (including pre-existing manifests
        without a ``content_contract`` field, which still read as legacy). When
        a contract is provided against an existing run, it must match the
        immutable recorded contract.

        For interactive-guide runs the effective pedagogical blueprint is
        resolved when the manifest is first created — explicit ``blueprint``
        argument, else the stored topic's ``blueprint`` field, else the
        deterministic recommendation over the stored topic — and recorded
        immutably as ``manifest["blueprint"] = {id, source, rationale?}``.
        Runs with no stored topic and no explicit choice record nothing and
        keep today's blueprint-free behavior. An explicit ``blueprint`` may
        also be recorded, once, on an existing guide manifest that has no
        record yet; a conflicting re-record raises. Legacy Markdown runs never
        record a blueprint.
        """

        run = self.run_dir(topic_id)
        for subdir in RUN_SUBDIRS:
            (run / subdir).mkdir(parents=True, exist_ok=True)

        manifest_path = run / "manifest.json"
        with self._manifest_write_lock(run.name):
            if not manifest_path.exists():
                requested = (
                    content_contract
                    if content_contract is not None
                    else ContentContract.interactive_guide_v1_2()
                )
                _validate_content_contract(requested)
                manifest = {
                    "schema_version": MANIFEST_SCHEMA_VERSION,
                    "topic_id": run.name,
                    "events": [],
                    "content_contract": requested.to_manifest(),
                }
                if requested.kind == "interactive_guide":
                    record = self._resolve_blueprint_record(run.name, blueprint)
                    if record is not None:
                        manifest["blueprint"] = record
                elif blueprint is not None:
                    raise ConfigError(
                        f"run {run.name!r} is a legacy Markdown run; "
                        "legacy runs do not support blueprints"
                    )
                _write_manifest(manifest_path, manifest)
            else:
                if content_contract is not None:
                    _validate_content_contract(content_contract)
                    if self.content_contract(run.name) != content_contract:
                        raise ConfigError(
                            f"run {run.name!r} already has immutable content contract "
                            f"{self.content_contract(run.name)!r}; requested {content_contract!r}"
                        )
                if blueprint is not None:
                    self._record_blueprint_locked(run.name, blueprint)
        return run

    def _resolve_blueprint_record(
        self, topic_id: str, explicit: str | None
    ) -> dict | None:
        """Resolve the effective blueprint record: user > topic > recommended.

        An unregistered explicit or topic-declared blueprint id raises; a
        missing or malformed stored topic degrades to no record (legacy
        behavior) rather than failing run creation.
        """

        if explicit is not None:
            get_blueprint(explicit)
            return {"id": explicit, "source": "user"}
        try:
            topic = TopicStore(self.root).load_topic(topic_id)
        except ConfigError:
            return None
        if topic.blueprint is not None:
            get_blueprint(topic.blueprint)
            return {"id": topic.blueprint, "source": "topic"}
        blueprint_id, rationale = recommend_blueprint(topic)
        return {"id": blueprint_id, "source": "recommended", "rationale": rationale}

    def _record_blueprint_locked(self, topic_id: str, blueprint: str) -> None:
        """Record an explicit blueprint on an existing manifest, immutably.

        Caller must already hold ``_manifest_write_lock(topic_id)``. Recording
        the already-recorded id is a no-op; a different id raises; legacy
        Markdown runs are refused.
        """

        if self.content_contract(topic_id).kind != "interactive_guide":
            raise ConfigError(
                f"run {topic_id!r} is a legacy Markdown run; "
                "legacy runs do not support blueprints"
            )
        get_blueprint(blueprint)
        manifest = self._read_manifest_for_update(topic_id)
        existing = manifest.get("blueprint")
        if isinstance(existing, dict):
            if existing.get("id") != blueprint:
                raise ConfigError(
                    f"run {topic_id!r} already has immutable blueprint "
                    f"{existing.get('id')!r}; requested {blueprint!r}"
                )
            return
        manifest["blueprint"] = {"id": blueprint, "source": "user"}
        _write_manifest(self.manifest_path(topic_id), manifest)

    def blueprint_config(self, topic_id: str) -> dict | None:
        """Return the run's recorded blueprint ``{id, source, rationale?}``.

        ``None`` when the run has no manifest, records no blueprint (legacy
        and pre-blueprint runs), or the record is unreadable.
        """

        safe_id = _artifact_id(topic_id, "topic id")
        if not self.manifest_path(safe_id).exists():
            return None
        record = self.read_manifest(safe_id).get("blueprint")
        if not isinstance(record, dict) or not isinstance(record.get("id"), str):
            return None
        return dict(record)

    def run_blueprint(self, topic_id: str) -> Blueprint | None:
        """Resolve the run's recorded blueprint through the registry."""

        config = self.blueprint_config(topic_id)
        if config is None:
            return None
        return get_blueprint(config["id"])

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

    def required_stages(self, topic_id: str) -> tuple[str, ...]:
        """Required model stages for progress/next-action of this run.

        Interactive-guide (guide-v1) runs require the adversarial ``factcheck``
        stage between ``qa`` and ``repair``; legacy Markdown runs never do.
        """

        return graph_required_stages(self._mode(topic_id).graph_mode)

    def stage_status(self, topic_id: str, stage: str) -> StageStatus:
        """Report the persisted progress for one stage of a run."""

        paths = self.stage_paths(topic_id, stage)
        approved = paths.approved_path.exists()
        stale = False
        if approved and self._mode(paths.topic_id).binds_sources and graph_sources_of(paths.stage):
            stale = self._stage_upstream_stale(paths.topic_id, paths.stage)
        elif paths.stage == "audit":
            stale = (
                (paths.prompt_path.exists() and not self.audit_prompt_is_current(paths.topic_id))
                or self.audit_state(paths.topic_id) == "stale"
                or self._audit_approval_incomplete(paths.topic_id)
            )
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
        with self.manifest_read_scope():
            stages = tuple(
                self.stage_status(safe_id, stage) for stage in SUPPORTED_STAGES
            )
            finalized = self.is_finalized(safe_id)
            return RunStatus(
                topic_id=safe_id,
                stages=stages,
                finalized=finalized,
                next_action=self._next_action(safe_id, stages, finalized),
            )

    def advance(self, topic_id: str) -> AdvanceResult:
        """Perform the run's next machine step, pausing at human steps.

        Machine steps (writing the next stage prompt, assembling a fanned-out
        draft, validation, or finalizing) are done automatically. Human steps (saving a response, approving it,
        resolving findings) and a completed run are left untouched, so this can
        be called repeatedly to drive a run forward and resume it from wherever
        it stopped.
        """

        safe_id = _artifact_id(topic_id, "topic id")
        action = self.run_status(safe_id).next_action
        performed: str | None = None
        if action.action == "write_prompt" and action.stage is not None:
            if action.stage == "draft" and self._mode(safe_id).supports_draft_units:
                # The draft stage has more than one prompt to write; which one
                # is re-derived from the unit state (design decision 8).
                self._advance_draft_prompt(safe_id)
            else:
                overwrite = False
                if self._mode(safe_id).prompt_overwrite_on_advance:
                    paths = self.stage_paths(safe_id, action.stage)
                    if paths.prompt_path.exists():
                        overwrite = True
                self._write_stage_prompt(safe_id, action.stage, overwrite=overwrite)
            performed = "write_prompt"
        elif action.action == "assemble" and action.stage == "draft":
            result = self.assemble_draft(safe_id)
            if not result.ok:
                raise ConfigError(
                    f"cannot assemble the draft for {safe_id!r}: {result.error}"
                )
            performed = "assemble"
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
            "factcheck": self.write_factcheck_prompt,
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
        with self.manifest_read_scope():
            return self._mode(topic_id).next_action(self, topic_id, stages, finalized)

    def _factcheck_grandfathered(self, by_stage: dict[str, StageStatus]) -> bool:
        """True when an approved repair excuses a run's missing factcheck.

        Grandfather pre-feature runs that already approved repair before the
        factcheck stage existed: never demand a factcheck for a run whose
        repair is already done *and still current*. Once that repair goes
        stale it has to be rebuilt, and ``write_repair_prompt`` requires an
        approved factcheck -- so stop skipping the stage rather than advertise
        a rebuild the run cannot perform.
        """

        repair = by_stage["repair"]
        return (
            repair.approved
            and not repair.stale
            and not by_stage["factcheck"].approved
        )

    def _next_action_guide_v1(
        self,
        topic_id: str,
        stages: tuple[StageStatus, ...],
        finalized: bool,
    ) -> NextAction:
        by_stage = {status.stage: status for status in stages}

        for stage_name in _unbound_stages("interactive_guide"):
            status = by_stage[stage_name]
            # The draft stage fans out into skeleton/module units. Their arms
            # sit inside this slot, so they are reached only once spec and
            # outline are approved, draft is not, and the stage response file
            # is still absent -- decision 6's "the response file wins".
            if (
                stage_name == "draft"
                and not status.approved
                and not status.response_ingested
            ):
                unit_action = self._draft_unit_next_action(topic_id)
                if unit_action is not None:
                    return unit_action
            pending = self._pending_stage_action(topic_id, status)
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
        # Memoized on the draft bytes alone: parse_guide is a pure function of
        # its input, and only the ok/not-ok verdict is needed here, so the
        # parse result itself is never retained.
        draft_parses = self._memoized(
            (
                "draft_parses",
                hashlib.sha256(draft_text.encode("utf-8")).hexdigest(),
            ),
            lambda: parse_guide(draft_text).ok,
        )
        if not draft_parses:
            return NextAction(
                topic_id=topic_id,
                stage="draft",
                action="resolve_findings",
                detail=(
                    f"Correct and reapprove the draft response for {topic_id!r}; "
                    "the approved draft is too malformed for QA."
                ),
            )

        draft_report = json.loads(
            self.draft_report_path(topic_id).read_text(encoding="utf-8")
        )
        trace_integrity_blocking = any(
            isinstance(finding, dict)
            and finding.get("rule_id") == "personalization.trace_integrity"
            and finding.get("blocking") is True
            for finding in draft_report.get("findings", [])
        )
        if trace_integrity_blocking:
            return NextAction(
                topic_id=topic_id,
                stage="draft",
                action="resolve_findings",
                detail=(
                    f"The personalization trace for {topic_id!r} could not be rebuilt; "
                    "correct and revalidate the draft before QA."
                ),
            )

        for stage_name in _bound_stages("interactive_guide"):
            status = by_stage[stage_name]
            if stage_name == "factcheck" and self._factcheck_grandfathered(by_stage):
                continue
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

        profile = self._load_attached_profile(topic_id)
        if (
            profile is not None
            and profile.learning_goals
            and self.personalization_trace_state(topic_id, phase="final") != "current"
        ):
            return NextAction(
                topic_id=topic_id,
                stage="repair",
                action="resolve_findings",
                detail=(
                    f"The personalization trace for {topic_id!r} is missing or stale; "
                    "run final validation again."
                ),
            )

        if finalized:
            return NextAction(
                topic_id=topic_id,
                stage=None,
                action="done",
                detail=f"Run {topic_id!r} is complete and finalized.",
            )

        source_text = self.read_approved(topic_id, "repair")
        report = self._status_final_report(topic_id, source_text)
        try:
            waiver_set = self._load_waiver_set(topic_id)
        except ConfigError:
            # Degrade gracefully on a malformed waivers file: fall back to
            # the raw (un-waived) gate rather than 400ing the whole run
            # status -- and, transitively, the /v1/topics list -- the same
            # degradation _validation_summary already applies.
            waiver_set = None
        waiver_result = apply_waivers(report, waiver_set)
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
        """When a guide-v1 qa/factcheck/repair stage is approved but upstream hashes drifted.

        Whether the prompt itself has to be rebuilt is decided by walking the
        stage's stage-graph sources in graph order and comparing each one's
        approved hash against the hash the latest ``prompt_written`` event
        recorded for it: any difference means the prompt no longer embeds the
        current upstream bytes.
        """

        prompt_event = self._latest_stage_event(topic_id, stage, "prompt_written")
        sources = graph_sources_of(stage)
        needs_prompt = True
        if prompt_event is not None and sources:
            recorded = _recorded_source_shas(prompt_event, stage)
            needs_prompt = False
            for position, source in enumerate(sources):
                current = self._approved_source_sha(topic_id, source)
                # The base source (the approved draft) missing from disk leaves
                # nothing to compare against, so the prompt has to be rebuilt
                # without looking at the sources behind it.
                if position == 0 and current is None:
                    needs_prompt = True
                    break
                if recorded[source] != current:
                    needs_prompt = True
                    break

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

    def archive_run(self, topic_id: str) -> None:
        """Flag a run as archived (spec §5.3). Nothing moves on disk."""

        self._set_archived(topic_id, True)

    def unarchive_run(self, topic_id: str) -> None:
        """Clear the archived flag; a pure flag flip."""

        self._set_archived(topic_id, False)

    def _set_archived(self, topic_id: str, archived: bool) -> None:
        safe_id = _artifact_id(topic_id, "topic id")
        with self._manifest_write_lock(safe_id):
            manifest = self._read_manifest_for_update(safe_id)  # ConfigError when no run
            manifest["archived"] = archived
            stamp_key = "archived_at" if archived else "unarchived_at"
            manifest[stamp_key] = datetime.now(timezone.utc).isoformat()
            _write_manifest(self.manifest_path(safe_id), manifest)

    def is_archived(self, topic_id: str) -> bool:
        """True only when a run manifest exists and carries the flag."""

        if not self.manifest_path(topic_id).is_file():
            return False
        try:
            manifest = self.read_manifest(topic_id)
        except ConfigError:
            return False
        return manifest.get("archived") is True

    def last_activity_at(self, topic_id: str) -> str | None:
        """ISO-8601 UTC mtime of the newest run artifact, or None without a run."""

        run = self.run_dir(topic_id)
        if not run.is_dir():
            return None
        newest = None
        for path in run.rglob("*"):
            # One stat() answers both questions this loop asks. ``is_file()``
            # is itself a stat() that swallows OSError into False, so the
            # try/except below covers exactly the entries it used to skip --
            # a racing deletion, a dangling symlink, an unreadable parent --
            # and S_ISREG covers the rest (directories, sockets, devices).
            try:
                status = path.stat()
            except OSError:
                continue  # racing deletion; skip
            if not stat.S_ISREG(status.st_mode):
                continue
            mtime = status.st_mtime
            if newest is None or mtime > newest:
                newest = mtime
        if newest is None:
            return None
        return datetime.fromtimestamp(newest, timezone.utc).isoformat()

    def read_manifest(self, topic_id: str) -> dict:
        """Return the run's parsed manifest.

        Served from the calling thread's :meth:`manifest_read_scope` when one
        is open, so a status read parses each manifest once instead of dozens
        of times. The returned dict is then shared for the life of that scope
        and must not be mutated; read-modify-write paths use
        :meth:`_read_manifest_for_update` instead.
        """

        path = self.manifest_path(topic_id)
        entries = _manifest_scope_entries()
        if entries is not None:
            cached = entries.get(str(path))
            if cached is not None:
                return cached
        manifest = self._read_manifest_file(path)
        if entries is not None:
            entries[str(path)] = manifest
        return manifest

    def _read_manifest_for_update(self, topic_id: str) -> dict:
        """Return a private parsed manifest for a read-modify-write cycle.

        Always reads from disk, never from (and never into) an open read
        scope: the caller is about to mutate the dict it gets back, which a
        scope-shared copy would leak to every other reader in the request.
        """

        return self._read_manifest_file(self.manifest_path(topic_id))

    def _read_manifest_file(self, path: Path) -> dict:
        import time

        # Windows sharing semantics: reading manifest.json at the moment a
        # writer os.replace()s it fails with PermissionError. The replace is
        # transient, so retry briefly instead of crashing a concurrent reader.
        for attempt in range(10):
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except FileNotFoundError as exc:
                raise ConfigError(f"run manifest not found: {path}") from exc
            except PermissionError:
                if attempt == 9:
                    raise
                time.sleep(0.05)
        raise AssertionError("unreachable")

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

        if paths.stage == "audit":
            return self._approve_personalization_audit(paths.topic_id, overwrite=overwrite)

        text = paths.response_path.read_text(encoding="utf-8")
        mode = self._mode(paths.topic_id)
        mode.validate_approval(self, paths.topic_id, paths.stage, text)
        scope: RepairScope | None = None
        if mode.scoped_repair_on_approve and paths.stage == "repair":
            scope = self.repair_scope(paths.topic_id)
            if scope is not None:
                text = self._spliced_scoped_repair(paths.topic_id, scope, text)
        _write_text(paths.approved_path, text, overwrite=overwrite)
        files: dict[str, Path] = {
            "prompt_file": paths.prompt_path,
            "approved_file": paths.approved_path,
        }
        file_hashes: dict[str, str] | None = None
        if mode.binds_sources and graph_sources_of(paths.stage):
            files.update(self._source_files(paths.topic_id, paths.stage))
            # Only bind the fact-check source when it exists: grandfathered
            # pre-feature repairs have none, and recording an absent source
            # would make the stale check false-positive forever. This stays a
            # named exception rather than a general "bind what exists" rule --
            # the draft and qa a stage was compiled from are always on disk by
            # the time its response is approved.
            factcheck_approved = files.get("source_factcheck_file")
            if factcheck_approved is not None and not factcheck_approved.is_file():
                del files["source_factcheck_file"]
            file_hashes = self._prompt_bound_source_hashes(
                paths.topic_id, paths.stage, files
            )
        self._append_event(
            paths.topic_id,
            stage=paths.stage,
            action="response_approved",
            files=files,
            file_hashes=file_hashes,
            extra=_repair_scope_event(scope),
        )
        return paths.approved_path

    def repair_scope(self, topic_id: str) -> RepairScope | None:
        """The target of the pending scoped repair, if any.

        Derived from the latest repair ``prompt_written`` event: a scoped
        prompt records its module and, for a section scope, its section; a
        later whole-guide repair prompt clears the scope. A recorded section
        without a module is not a scope -- the module is what locates it.
        """

        event = self._latest_stage_event(topic_id, "repair", "prompt_written")
        if event is None:
            return None
        module_id = event.get("repair_module")
        if not isinstance(module_id, str):
            return None
        section_id = event.get("repair_section")
        return RepairScope(
            module_id=module_id,
            section_id=section_id if isinstance(section_id, str) else None,
        )

    def _spliced_scoped_repair(
        self, topic_id: str, scope: RepairScope, response_text: str
    ) -> str:
        """Merge a scoped repair response into the approved draft, fail-closed.

        The scoped response is keyed to the exact base draft the prompt was
        built from: a drifted draft raises :class:`StaleContentError`, and any
        splice violation (module or section rename, element-id collision,
        out-of-contract reference) refuses the approval — never a silent fix.
        A scope with a section splices exactly that section; a scope without
        one splices the whole module.
        """

        prompt_event = self._latest_stage_event(topic_id, "repair", "prompt_written")
        draft_path = self.stage_paths(topic_id, "draft").approved_path
        if not draft_path.is_file():
            raise ConfigError(
                f"approved draft not found for {topic_id!r}; a scoped repair needs its base draft"
            )
        draft_bytes = read_bytes_retrying(draft_path)
        recorded = (
            prompt_event.get("source_draft_file_sha256")
            if prompt_event is not None
            else None
        )
        if recorded != hashlib.sha256(draft_bytes).hexdigest():
            raise StaleContentError(
                f"the approved draft for {topic_id!r} changed since the scoped repair "
                "prompt was written; rebuild the scoped repair prompt and re-run it"
            )
        base_text = draft_bytes.decode("utf-8")
        try:
            merged = (
                splice_module(base_text, scope.module_id, response_text)
                if scope.section_id is None
                else splice_section(
                    base_text, scope.module_id, scope.section_id, response_text
                )
            )
        except SpliceError as exc:
            kind = "module" if scope.section_id is None else "section"
            raise ConfigError(
                f"cannot approve {kind}-scoped repair for guide run {topic_id!r}: {exc}"
            ) from exc
        return merged.decode("utf-8")

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
        if paths.stage == "audit":
            self.require_provider_ready_prompt(paths.topic_id, paths.stage)
            inputs = self._current_audit_inputs(paths.topic_id)
            try:
                parse_audit_response(
                    text,
                    guide=inputs.guide,
                    trace=inputs.trace_bytes,
                    private_values=profile_private_values(inputs.profile),
                )
            except AuditResponseError as exc:
                raise ConfigError(str(exc)) from exc
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
        current = hashlib.sha256(read_bytes_retrying(paths.response_path)).hexdigest()
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
        """Append an arbitrary event (with ``recorded_at``) to the run manifest.

        Thin lock-taking wrapper around :meth:`_append_manifest_event_locked`.
        Do not call this from inside another ``_manifest_write_lock``-holding
        method on the same thread -- that will deadlock by design (the lock
        is not reentrant). Compose by calling
        :meth:`_append_manifest_event_locked` directly instead.
        """

        safe_id = _artifact_id(topic_id, "topic id")
        with self._manifest_write_lock(safe_id):
            self._append_manifest_event_locked(safe_id, event)

    def _append_manifest_event_locked(self, topic_id: str, event: dict) -> None:
        """Unlocked read-modify-write of one manifest event.

        Caller must already hold ``_manifest_write_lock(topic_id)``. Exists
        so callers that need to compose this write with another manifest
        mutation in a single critical section can do so without re-entering
        the lock.
        """

        safe_id = _artifact_id(topic_id, "topic id")
        run = self.run_dir(safe_id)
        manifest = self._read_manifest_for_update(safe_id)
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
        re-running a stage appends a new entry rather than replacing the last.

        Thin lock-taking wrapper around
        :meth:`_record_stage_provenance_locked`. Do not call this from
        inside another ``_manifest_write_lock``-holding method on the same
        thread -- that will deadlock by design. Compose by calling
        :meth:`_record_stage_provenance_locked` directly instead.
        """

        safe_id = _artifact_id(topic_id, "topic id")
        with self._manifest_write_lock(safe_id):
            self._record_stage_provenance_locked(
                safe_id,
                stage,
                provider=provider,
                model=model,
                effort=effort,
                source=source,
                job_id=job_id,
            )

    def _record_stage_provenance_locked(
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
        """Unlocked read-modify-write appending one stage-provenance entry.

        Caller must already hold ``_manifest_write_lock(topic_id)``. Exists
        so callers that need to compose this write with another manifest
        mutation in a single critical section can do so without re-entering
        the lock.
        """

        safe_id = _artifact_id(topic_id, "topic id")
        run = self.run_dir(safe_id)
        manifest = self._read_manifest_for_update(safe_id)
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


    def require_provider_ready_prompt(self, topic_id: str, stage: str) -> Path:
        """Return a runnable prompt path, refusing missing/stale audit prompts."""

        paths = self.stage_paths(topic_id, stage)
        if not paths.prompt_path.is_file():
            raise ConfigError(f"{paths.stage} prompt is missing; prepare it before enqueue")
        if paths.stage == "audit" and not self.audit_prompt_is_current(paths.topic_id):
            raise StaleContentError(
                "audit prompt is stale; rebuild it before enqueue or response ingest"
            )
        return paths.prompt_path


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
        artifact = self._mode(safe_id).compile_spec_prompt(self, safe_id, spec_input)
        return self._write_prompt(artifact, overwrite=overwrite)

    def _guide_v1_spec_artifact(
        self, topic_id: str, spec_input: SpecPromptInput
    ) -> PromptArtifact:
        """Compile the guide-v1 spec prompt for an already-materialized run."""

        return compile_guide_v1_spec_prompt(
            spec_input,
            guide_schema_version=self.content_contract(topic_id).schema_version
            or DEFAULT_GUIDE_SCHEMA_VERSION,
            blueprint=self.run_blueprint(topic_id),
        )

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
        artifact = self._mode(safe_id).compile_topic_spec_prompt(
            self, safe_id, topic, profile
        )
        return self._write_prompt(artifact, overwrite=overwrite)

    def _guide_v1_topic_spec_artifact(
        self, topic_id: str, topic: Topic, profile: LearnerProfile | None
    ) -> PromptArtifact:
        """Compile the guide-v1 spec prompt from a stored topic artifact."""

        return compile_guide_v1_spec_prompt(
            SpecPromptInput(
                topic_id=topic.id,
                title=topic.title,
                topic_brief=topic.brief,
                profile=profile,
            ),
            guide_schema_version=self.content_contract(topic_id).schema_version
            or DEFAULT_GUIDE_SCHEMA_VERSION,
            blueprint=self.run_blueprint(topic_id),
        )

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
        artifact, extra_files = self._mode(safe_id).compile_outline_prompt(
            self, safe_id, topic, approved_spec, profile
        )
        return self._write_prompt(artifact, overwrite=overwrite, extra_event_files=extra_files)

    def _guide_v1_outline_artifact(
        self,
        topic_id: str,
        topic: Topic,
        approved_spec: str,
        profile: LearnerProfile | None,
    ) -> CompiledPrompt:
        """Compile the guide-v1 outline prompt and its bound spec source."""

        artifact = compile_guide_v1_outline_prompt(
            topic,
            approved_spec,
            profile,
            guide_schema_version=self.content_contract(topic_id).schema_version
            or DEFAULT_GUIDE_SCHEMA_VERSION,
            blueprint=self.run_blueprint(topic_id),
        )
        extra_files = {
            "source_spec_file": self.stage_paths(topic_id, "spec").approved_path,
        }
        return artifact, extra_files

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
        artifact, extra_files = self._mode(safe_id).compile_draft_prompt(
            self, safe_id, topic, approved_outline, profile, overwrite=overwrite
        )
        written = self._write_prompt(
            artifact, overwrite=overwrite, extra_event_files=extra_files
        )
        if self._mode(safe_id).supports_draft_units:
            # The whole-guide prompt stays the documented single-call
            # alternative (decision 5); the skeleton is where the fan-out
            # actually starts, so both are written together.
            self.write_skeleton_draft_prompt(safe_id)
        return written

    def _guide_v1_draft_artifact(
        self,
        topic_id: str,
        topic: Topic,
        approved_outline: str,
        profile: LearnerProfile | None,
        *,
        overwrite: bool,
    ) -> CompiledPrompt:
        """Write the immutable guide contract and compile the draft prompt."""

        self.create_run(topic_id)
        contract_bytes = self._write_guide_contract(topic_id, profile=profile, overwrite=overwrite)
        artifact = compile_guide_v1_draft_prompt(
            topic,
            approved_outline,
            contract_bytes,
            profile,
            blueprint=self.run_blueprint(topic_id),
        )
        extra_files = {
            "source_outline_file": self.stage_paths(topic_id, "outline").approved_path,
            "contract_file": self._guide_contract_path(topic_id),
        }
        return artifact, extra_files

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
        artifact, extra_files = self._mode(safe_id).compile_qa_prompt(
            self,
            safe_id,
            topic,
            approved_spec=approved_spec,
            approved_outline=approved_outline,
            approved_draft=approved_draft,
            profile=profile,
        )
        return self._write_prompt(
            artifact, overwrite=overwrite, extra_event_files=extra_files
        )

    def _guide_v1_qa_artifact(
        self,
        topic_id: str,
        topic: Topic,
        *,
        approved_spec: str,
        approved_outline: str,
        approved_draft: str,
        profile: LearnerProfile | None,
    ) -> CompiledPrompt:
        """Gate on a current draft report, then compile the guide-v1 QA prompt."""

        state = self.report_state(topic_id, "draft")
        if state != "current":
            if state == "missing":
                raise ConfigError(
                    f"draft validation is required before QA for {topic_id!r}; "
                    "run draft validation first"
                )
            raise ConfigError(
                f"draft validation is stale for {topic_id!r}; "
                "the draft changed and must be revalidated before QA"
            )
        parsed = parse_guide(approved_draft)
        if not parsed.ok:
            raise ConfigError(
                f"approved draft for {topic_id!r} is too malformed for QA; "
                "correct and reapprove the draft response"
            )
        draft_guide_json = canonical_guide_bytes(normalize_guide(parsed)).decode("utf-8")
        draft_findings_json = self.draft_report_path(topic_id).read_text(encoding="utf-8")
        artifact = compile_guide_v1_qa_prompt(
            topic,
            approved_spec=approved_spec,
            approved_outline=approved_outline,
            draft_guide_json=draft_guide_json,
            draft_findings_json=draft_findings_json,
            profile=profile,
            blueprint=self.run_blueprint(topic_id),
        )
        extra_files = {
            **self._source_files(topic_id, "qa"),
            "draft_report_file": self.draft_report_path(topic_id),
        }
        return artifact, extra_files

    def write_factcheck_prompt(
        self,
        topic_id: str,
        *,
        overwrite: bool = False,
    ) -> PromptFile:
        """Compile and write the guide-v1 factcheck prompt.

        The adversarial fact-check stage runs between QA and repair for
        interactive-guide runs only. It requires the spec, outline, draft, and
        QA stages to have been approved, plus a current draft validation report
        and a parseable approved draft (same gates as ``write_qa_prompt``). The
        stage never rewrites the draft; it produces a fixed-section report.
        """

        safe_id = _artifact_id(topic_id, "topic id")
        if not self._mode(safe_id).supports_factcheck:
            raise ConfigError(
                f"the factcheck stage applies only to interactive-guide runs; "
                f"{safe_id!r} is a legacy Markdown run"
            )
        topic = TopicStore(self.root).load_topic(safe_id)
        approved_spec = self.read_approved(safe_id, "spec")
        approved_outline = self.read_approved(safe_id, "outline")
        approved_draft = self.read_approved(safe_id, "draft")
        approved_qa = self.read_approved(safe_id, "qa")
        self._require_current_upstream(safe_id, "factcheck", "qa")
        profile = self._load_attached_profile(safe_id)
        state = self.report_state(safe_id, "draft")
        if state != "current":
            if state == "missing":
                raise ConfigError(
                    f"draft validation is required before factcheck for {safe_id!r}; "
                    "run draft validation first"
                )
            raise ConfigError(
                f"draft validation is stale for {safe_id!r}; "
                "the draft changed and must be revalidated before factcheck"
            )
        parsed = parse_guide(approved_draft)
        if not parsed.ok:
            raise ConfigError(
                f"approved draft for {safe_id!r} is too malformed for factcheck; "
                "correct and reapprove the draft response"
            )
        draft_guide_json = canonical_guide_bytes(normalize_guide(parsed)).decode("utf-8")
        draft_findings_json = self.draft_report_path(safe_id).read_text(encoding="utf-8")
        artifact = compile_guide_v1_factcheck_prompt(
            topic,
            approved_spec=approved_spec,
            approved_outline=approved_outline,
            draft_guide_json=draft_guide_json,
            qa_findings_markdown=approved_qa,
            draft_findings_json=draft_findings_json,
            profile=profile,
            blueprint=self.run_blueprint(safe_id),
        )
        extra_files = {
            **self._source_files(safe_id, "factcheck"),
            "draft_report_file": self.draft_report_path(safe_id),
        }
        return self._write_prompt(
            artifact, overwrite=overwrite, extra_event_files=extra_files
        )

    def _require_repair_ready(
        self, topic_id: str, approved_draft: str
    ) -> tuple[str, str, Path]:
        """Gate a guide-v1 repair prompt and return what both writers compile from.

        The whole-guide and the module-scoped repair prompt have exactly the
        same entry conditions -- both upstreams current, a current draft
        report, an established guide contract, and an approved draft that
        still parses -- so they ask for them here once instead of keeping two
        copies of the same refusals in step. Returns the canonical draft guide
        JSON, the draft report's findings JSON, and the guide contract's path.
        """

        self._require_current_upstream(topic_id, "repair", "qa")
        self._require_current_upstream(topic_id, "repair", "factcheck")
        state = self.report_state(topic_id, "draft")
        if state != "current":
            if state == "missing":
                raise ConfigError(
                    f"draft validation is required before repair for {topic_id!r}; "
                    "run draft validation first"
                )
            raise ConfigError(
                f"draft validation is stale for {topic_id!r}; "
                "the draft changed and must be revalidated before repair"
            )
        contract_path = self._guide_contract_path(topic_id)
        if not contract_path.is_file():
            raise ConfigError(
                f"guide contract not found for {topic_id!r}: {contract_path}"
            )
        parsed = parse_guide(approved_draft)
        if not parsed.ok:
            raise ConfigError(
                f"approved draft for {topic_id!r} is too malformed for repair; "
                "correct and reapprove the draft response"
            )
        draft_guide_json = canonical_guide_bytes(normalize_guide(parsed)).decode("utf-8")
        draft_findings_json = self.draft_report_path(topic_id).read_text(encoding="utf-8")
        return draft_guide_json, draft_findings_json, contract_path

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
        artifact, extra_files = self._mode(safe_id).compile_repair_prompt(
            self,
            safe_id,
            topic,
            approved_draft=approved_draft,
            approved_qa=approved_qa,
            profile=profile,
        )
        return self._write_prompt(
            artifact, overwrite=overwrite, extra_event_files=extra_files
        )

    def _guide_v1_repair_artifact(
        self,
        topic_id: str,
        topic: Topic,
        *,
        approved_draft: str,
        approved_qa: str,
        profile: LearnerProfile | None,
    ) -> CompiledPrompt:
        """Gate the guide-v1 repair inputs, then compile the whole-guide prompt."""

        approved_factcheck = self.read_approved(topic_id, "factcheck")
        draft_guide_json, draft_findings_json, contract_path = self._require_repair_ready(
            topic_id, approved_draft
        )
        artifact = compile_guide_v1_repair_prompt(
            topic,
            draft_guide_json=draft_guide_json,
            qa_findings_markdown=approved_qa,
            factcheck_findings_markdown=approved_factcheck,
            draft_findings_json=draft_findings_json,
            guide_contract=contract_path.read_bytes(),
            profile=profile,
            blueprint=self.run_blueprint(topic_id),
        )
        extra_files = {
            **self._source_files(topic_id, "repair"),
            "draft_report_file": self.draft_report_path(topic_id),
            "contract_file": contract_path,
        }
        return artifact, extra_files

    def write_module_repair_prompt(
        self,
        topic_id: str,
        module_id: str,
        *,
        overwrite: bool = False,
    ) -> PromptFile:
        """Compile and write the module-scoped variant of the repair prompt.

        A thin alias for :meth:`write_scoped_repair_prompt` with no section,
        kept because the module scope is the older and more common call.
        """

        return self.write_scoped_repair_prompt(
            topic_id, RepairScope(module_id=module_id), overwrite=overwrite
        )

    def write_scoped_repair_prompt(
        self,
        topic_id: str,
        scope: RepairScope,
        *,
        overwrite: bool = False,
    ) -> PromptFile:
        """Compile and write the module- or section-scoped repair prompt.

        The one writer for a scoped repair. Available whenever repair is the
        run's active stage (QA approved, or re-entry after final validation
        found problems). The scope and the exact base-draft hash are recorded
        on the ``prompt_written`` event so approval can key the scoped
        response to the draft it patches. An unknown module or section id is a
        usage error.
        """

        module_id = scope.module_id
        section_id = scope.section_id
        safe_id = _artifact_id(topic_id, "topic id")
        if not self._mode(safe_id).supports_module_repair:
            raise ConfigError(
                f"module-scoped repair applies only to interactive-guide runs; "
                f"{safe_id!r} is a legacy Markdown run"
            )
        if not (
            self.stage_paths(safe_id, "qa").approved_path.is_file()
            and self.stage_paths(safe_id, "factcheck").approved_path.is_file()
        ):
            raise ConfigError(
                f"module-scoped repair for {safe_id!r} is available only when repair "
                "is the run's active stage; approve the qa and factcheck stages first"
            )
        topic = TopicStore(self.root).load_topic(safe_id)
        approved_draft = self.read_approved(safe_id, "draft")
        approved_qa = self.read_approved(safe_id, "qa")
        approved_factcheck = self.read_approved(safe_id, "factcheck")
        profile = self._load_attached_profile(safe_id)
        draft_guide_json, draft_findings_json, contract_path = self._require_repair_ready(
            safe_id, approved_draft
        )
        shared = dict(
            draft_guide_json=draft_guide_json,
            qa_findings_markdown=approved_qa,
            factcheck_findings_markdown=approved_factcheck,
            draft_findings_json=draft_findings_json,
            guide_contract=contract_path.read_bytes(),
            profile=profile,
            blueprint=self.run_blueprint(safe_id),
        )
        artifact = (
            compile_guide_v1_module_repair_prompt(topic, module_id=module_id, **shared)
            if section_id is None
            else compile_guide_v1_section_repair_prompt(
                topic, module_id=module_id, section_id=section_id, **shared
            )
        )
        extra_files = {
            **self._source_files(safe_id, "repair"),
            "draft_report_file": self.draft_report_path(safe_id),
            "contract_file": contract_path,
        }
        return self._write_prompt(
            artifact,
            overwrite=overwrite,
            extra_event_files=extra_files,
            extra_event=_repair_scope_event(scope),
        )

    def _write_prompt(
        self,
        artifact: PromptArtifact,
        *,
        overwrite: bool,
        extra_event_files: dict[str, Path] | None = None,
        extra_event: dict[str, object] | None = None,
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
            extra=extra_event,
        )
        return PromptFile(
            stage=paths.stage,
            topic_id=paths.topic_id,
            prompt_path=paths.prompt_path,
            response_path=paths.response_path,
            stub_path=paths.stub_path,
            artifact=artifact,
        )

    def _mode(self, topic_id: str) -> _RunMode:
        """The strategy for this run's content mode: the one dispatch site.

        Every place ``RunStore`` once branched on "is this a guide-v1 run?"
        now asks this for a mode object instead, so the legacy Markdown
        bodies can live in :mod:`education_pipeline.run_modes` and never
        interleave with the guide-v1 ones again.
        """

        return mode_for_kind(self.content_contract(topic_id).kind)


    def _validate_guide_approval(self, topic_id: str, stage: str, response_text: str) -> None:
        """Raise ConfigError if a guide-v1 spec/outline response fails its contract gate."""

        try:
            if stage == "spec":
                spec_contract = extract_spec_contract(
                    response_text,
                    expected_blueprint=self.run_blueprint(topic_id),
                )
                expected_version = self.content_contract(topic_id).schema_version
                if spec_contract["guide_schema_version"] != expected_version:
                    raise ContractError(
                        "spec guide schema version conflicts with the immutable run "
                        f"content contract: expected {expected_version!r}"
                    )
            elif stage == "outline":
                outline_contract = extract_outline_contract(response_text)
                spec_contract = extract_spec_contract(self.read_approved(topic_id, "spec"))
                check_contract_conflict(spec_contract, outline_contract)
        except ContractError as exc:
            raise ConfigError(
                f"cannot approve {stage} for guide run {topic_id!r}: {exc}"
            ) from exc

    def _validate_guide_version(self, topic_id: str, stage: str, response_text: str) -> None:
        """Refuse a draft/repair guide declaring another supported schema version.

        Decision 13: a guide whose ``schema_version`` is a supported version
        other than the run's immutable contract cannot be approved. Anything
        else (undecodable, non-object, missing, non-string, or unsupported
        version) is left to validation, which reports it as a blocker.
        """

        try:
            data = json.loads(response_text)
        except (TypeError, ValueError):
            return
        if not isinstance(data, dict):
            return
        declared = data.get("schema_version")
        if not isinstance(declared, str) or declared not in SUPPORTED_GUIDE_SCHEMA_VERSIONS:
            return
        expected = self.content_contract(topic_id).schema_version
        if declared != expected:
            raise ConfigError(
                f"cannot approve {stage} for guide run {topic_id!r}: guide schema_version "
                f"{declared!r} conflicts with the immutable run content contract: "
                f"expected {expected!r}"
            )


    def _manifest_events(self, topic_id: str) -> list[dict]:
        try:
            events = self.read_manifest(topic_id).get("events", [])
        except ConfigError:
            return []
        return [event for event in events if isinstance(event, dict)]


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

    def _approved_source_sha(self, topic_id: str, source: str) -> str | None:
        """SHA-256 of ``source``'s approved artifact, or ``None`` when it is absent."""

        path = self.stage_paths(topic_id, source).approved_path
        if not path.is_file():
            return None
        return hashlib.sha256(read_bytes_retrying(path)).hexdigest()

    def _source_files(self, topic_id: str, stage: str) -> dict[str, Path]:
        """``stage``'s approved upstream artifacts, keyed by manifest label.

        One entry per stage-graph source, in graph order, so the chain lives in
        ``stage_graph`` rather than in each call site.
        """

        return {
            label: self.stage_paths(topic_id, source).approved_path
            for source, label in zip(
                graph_sources_of(stage), graph_source_labels(stage)
            )
        }

    def _stage_upstream_stale(self, topic_id: str, stage: str) -> bool:
        """True when an approved guide-v1 stage's recorded upstream hashes drifted.

        The upstream stages are the stage's sources in the stage graph, walked
        in graph order -- draft, then qa, then factcheck -- so the chain
        deepening downstream is the graph's business, not this method's. A
        recorded hash that is absent (a pre-feature or grandfathered event) is
        treated as "no dependency to check": the walk stops there and reports
        the stage as current, never as stale.
        """

        event = self._latest_stage_event(topic_id, stage, "response_approved")
        if event is None:
            return False

        for source, recorded in _recorded_source_shas(event, stage).items():
            if recorded is None:
                return False
            current = self._approved_source_sha(topic_id, source)
            if current is None or recorded != current:
                return True
        return False

    def _prompt_bound_source_hashes(
        self, topic_id: str, stage: str, files: dict[str, Path]
    ) -> dict[str, str]:
        """Upstream hashes as recorded on the stage's latest written prompt.

        An approval must key its response to the upstream bytes the *prompt*
        embedded, not to whatever happens to be on disk when the response is
        approved: an upstream stage reapproved in between never reached the
        model, so the response has to read as stale. Only ``source_*`` labels
        the prompt event actually recorded are returned -- anything else falls
        back to hashing the current file, which keeps pre-feature and
        grandfathered runs behaving exactly as before.
        """

        event = self._latest_stage_event(topic_id, stage, "prompt_written")
        if event is None:
            return {}
        bound: dict[str, str] = {}
        for label in files:
            if not label.startswith("source_"):
                continue
            recorded = event.get(f"{label}_sha256")
            if isinstance(recorded, str):
                bound[label] = recorded
        return bound

    def _require_current_upstream(self, topic_id: str, stage: str, upstream: str) -> None:
        """Refuse to compile ``stage`` while an approved upstream stage is stale.

        ``_next_action_*`` already routes callers around this, but the prompt
        writers are public: a direct caller must not be able to splice a fresh
        draft together with superseded upstream findings and then approve the
        result as if the stage sequence had been followed.
        """

        if self._stage_upstream_stale(topic_id, upstream):
            raise ConfigError(
                f"the approved {upstream} for {topic_id!r} is stale; rebuild the "
                f"{upstream} prompt and reapprove it before {stage}"
            )

    def _append_event(
        self,
        topic_id: str,
        *,
        stage: str,
        action: str,
        files: dict[str, Path],
        file_hashes: dict[str, str] | None = None,
        extra: dict[str, object] | None = None,
    ) -> None:
        """Append one structured stage event to the manifest.

        Thin lock-taking wrapper around :meth:`_append_event_locked`. Do not
        call this from inside another ``_manifest_write_lock``-holding method
        on the same thread -- the lock is not reentrant, so that deadlocks by
        design. Compose by calling :meth:`_append_event_locked` directly
        instead.
        """

        safe_id = _artifact_id(topic_id, "topic id")
        with self._manifest_write_lock(safe_id):
            self._append_event_locked(
                safe_id,
                stage=stage,
                action=action,
                files=files,
                file_hashes=file_hashes,
                extra=extra,
            )

    def _append_event_locked(
        self,
        topic_id: str,
        *,
        stage: str,
        action: str,
        files: dict[str, Path],
        file_hashes: dict[str, str] | None = None,
        extra: dict[str, object] | None = None,
    ) -> None:
        """Unlocked read-modify-write of one structured stage event.

        Caller must already hold ``_manifest_write_lock(topic_id)``. Exists so
        callers that need to compose this write with another manifest mutation
        in a single critical section can do so without re-entering the lock.
        """

        safe_id = _artifact_id(topic_id, "topic id")
        run = self.run_dir(safe_id)
        manifest = self._read_manifest_for_update(safe_id)
        event: dict[str, str] = {"stage": stage, "action": action}
        for label, path in files.items():
            event[label] = _relative_to(path, run)
            # An explicit hash pins the bytes this event is *about* (see
            # _prompt_bound_source_hashes); without one, hash the file as it
            # stands now.
            bound = (file_hashes or {}).get(label)
            if bound is not None:
                event[f"{label}_sha256"] = bound
            elif path.is_file():
                event[f"{label}_sha256"] = hashlib.sha256(read_bytes_retrying(path)).hexdigest()
        if extra:
            event.update(extra)
        event["recorded_at"] = datetime.now(timezone.utc).isoformat()
        manifest.setdefault("events", []).append(event)
        _write_manifest(run / "manifest.json", manifest)


def _bound_stages(mode: str) -> tuple[str, ...]:
    """``mode``'s required stages whose prompt embeds an upstream approved stage.

    The tail of the chain -- qa, factcheck, repair for interactive guides --
    read off the stage graph rather than spelled out at the walk.
    """

    return tuple(
        name for name in graph_required_stages(mode) if graph_sources_of(name)
    )


def _unbound_stages(mode: str) -> tuple[str, ...]:
    """``mode``'s required stages with no upstream sources: the head of the chain."""

    return tuple(
        name for name in graph_required_stages(mode) if not graph_sources_of(name)
    )


def _recorded_source_shas(event: dict, stage: str) -> dict[str, str | None]:
    """The upstream hashes ``event`` recorded for ``stage``'s stage-graph sources.

    Keyed by source stage name, in graph order, with ``None`` wherever the
    event carries no hash for that source -- which is how a pre-feature or
    grandfathered event reads.
    """

    return {
        source: event.get(f"{label}_sha256")
        for source, label in zip(graph_sources_of(stage), graph_source_labels(stage))
    }


def _write_manifest(path: Path, manifest: dict) -> None:
    _write_bytes_atomic(path, (json.dumps(manifest, indent=2) + "\n").encode("utf-8"))
    # Every manifest write funnels through here, so this one line is the whole
    # invalidation story for an open read scope.
    _manifest_scope_discard(path)


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
    if contract == ContentContract.interactive_guide_v1_1():
        return
    if contract == ContentContract.interactive_guide_v1_2():
        return
    raise ConfigError(
        "unsupported content contract "
        f"{contract.kind!r} schema {contract.schema_version!r}; supported contracts are "
        "legacy_markdown and interactive_guide schemas '1.0', '1.1' and '1.2'"
    )


def _guide_content_type(schema_version: str | None) -> str:
    if schema_version == "1.0":
        return GUIDE_V1_CONTENT_TYPE
    if schema_version == "1.1":
        return "application/vnd.education-pipeline.guide+json;version=1.1"
    if schema_version == "1.2":
        return "application/vnd.education-pipeline.guide+json;version=1.2"
    raise ConfigError(f"unsupported interactive guide schema {schema_version!r}")


