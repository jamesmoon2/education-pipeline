"""Per-module draft units for :class:`~education_pipeline.runs.RunStore`.

The draft stage of a guide-v1 run asks the model for one *skeleton* (the whole
guide with every module reduced to a sectionless stub) and then for one object
per module, instead of one whole-guide response. Those units live under
``<run>/draft/`` and are assembled deterministically into the ordinary
``responses/draft.response.json`` -- so the stage keeps exactly one prompt
state, one response file, one approval and one validation, and everything
downstream of the response file is untouched.

Design:
``docs/superpowers/specs/2026-09-18-per-module-drafting-design.md`` (decisions
1, 3, 4, 6-9; sections 1 and 4).

:class:`DraftUnitsMixin` holds no state of its own -- ``RunStore`` supplies
every ``self.`` collaborator used here, exactly as the other Phase 1 mixins do.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json

from education_pipeline.atomic_io import read_bytes_retrying
from education_pipeline.config import ConfigError
from education_pipeline.guides.canonical import AssemblyError, assemble_guide
from education_pipeline.guides.contract import extract_outline_contract
from education_pipeline.guides.parse import ID_RE, check_skeleton
from education_pipeline.prompts import (
    compile_guide_v1_module_draft_prompt,
    compile_guide_v1_skeleton_prompt,
)
from education_pipeline.run_core import (
    AssembleResult,
    AssembledStatus,
    DraftProgress,
    DraftUnitPaths,
    DraftUnitStatus,
    NextAction,
    StaleContentError,
    _relative_to,
    _write_bytes_atomic,
    _write_text,
    _write_text_atomic,
)
from education_pipeline.workspace import TopicStore, artifact_id as _artifact_id

#: The two unit kinds. ``skeleton`` is a singleton; ``module`` is per module id.
DRAFT_UNITS = ("skeleton", "module")

_DRAFT_DIRNAME = "draft"
_SKELETON_DIRNAME = "skeleton"
_MODULES_DIRNAME = "modules"
_ORPHANED_DIRNAME = "orphaned"


def _canonical_json(value: object) -> bytes:
    """The bytes a hash of a JSON value is taken over: one canonical spelling."""

    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _sha256_of(value: object) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _diagnostics_text(result) -> str:
    return "; ".join(
        f"{item.code} at {item.path}: {item.message}" for item in result.diagnostics
    )


def _unit_stub_text(paths: DraftUnitPaths) -> str:
    label = (
        "course skeleton"
        if paths.unit == "skeleton"
        else f"module {paths.module_id!r}"
    )
    return (
        f"# Response placeholder for the draft {label}\n"
        "\n"
        "No model response has been saved for this draft unit yet.\n"
        "Run the sibling prompt.md and save the response as:\n"
        "\n"
        f"    {paths.response_path.name}\n"
        "\n"
        "This placeholder is ignored by the pipeline and does not count as an\n"
        "ingested response. Delete it once the real response is in place.\n"
    )


class DraftUnitsMixin:
    """The draft unit lifecycle, mixed into :class:`RunStore`."""

    # -- guards and layout ------------------------------------------------

    def _require_draft_units(self, topic_id: str) -> str:
        """Validate the topic id and refuse legacy Markdown runs."""

        safe_id = _artifact_id(topic_id, "topic id")
        if not self._mode(safe_id).supports_draft_units:
            raise ConfigError(
                f"per-module drafting applies only to interactive-guide runs; "
                f"{safe_id!r} is a legacy Markdown run"
            )
        return safe_id

    def draft_unit_paths(
        self, topic_id: str, unit: str, *, module_id: str | None = None
    ) -> DraftUnitPaths:
        """Filesystem locations for one draft unit. The only speller of the layout."""

        safe_id = self._require_draft_units(topic_id)
        if unit not in DRAFT_UNITS:
            known = ", ".join(DRAFT_UNITS)
            raise ConfigError(f"unknown draft unit {unit!r}; known units: {known}")
        base = self.run_dir(safe_id) / _DRAFT_DIRNAME
        if unit == "skeleton":
            if module_id is not None:
                raise ConfigError("the draft skeleton unit takes no module id")
            base = base / _SKELETON_DIRNAME
        else:
            if module_id is None:
                raise ConfigError("a module draft unit needs a module id")
            # Module ids are validated slugs in the outline contract, so this
            # is also what keeps them safe as directory names.
            if not isinstance(module_id, str) or not ID_RE.match(module_id):
                raise ConfigError(
                    f"module id {module_id!r} must be a stable machine identifier "
                    "matching the guide ID pattern '^[a-z][a-z0-9-]{0,63}$'"
                )
            base = base / _MODULES_DIRNAME / module_id
        return DraftUnitPaths(
            unit=unit,
            module_id=module_id,
            prompt_path=base / "prompt.md",
            response_path=base / "response.json",
            stub_path=base / "SAVE_RESPONSE_HERE.json",
            previous_path=base / "response.previous.json",
        )

    # -- inputs the unit layer hashes and embeds --------------------------

    def _draft_module_order(self, topic_id: str) -> tuple[str, ...]:
        """The authored module order, read from the approved outline's contract.

        Never from ``inputs/guide-contract.json``, whose module map is
        re-emitted with ``sort_keys=True`` (design decision 3).
        """

        try:
            contract = extract_outline_contract(self.read_approved(topic_id, "outline"))
        except Exception as exc:  # ContractError and friends
            raise ConfigError(
                f"cannot read the module order for run {topic_id!r}: {exc}"
            ) from exc
        return tuple(contract["modules"])

    def _draft_contract_entries(self, topic_id: str) -> dict[str, object]:
        path = self._guide_contract_path(topic_id)
        if not path.is_file():
            return {}
        try:
            payload = json.loads(read_bytes_retrying(path).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}
        modules = payload.get("modules") if isinstance(payload, dict) else None
        return dict(modules) if isinstance(modules, dict) else {}

    def _draft_skeleton_text(
        self, topic_id: str, paths: DraftUnitPaths | None = None
    ) -> str | None:
        path = (paths or self.draft_unit_paths(topic_id, "skeleton")).response_path
        if not path.is_file():
            return None
        return read_bytes_retrying(path).decode("utf-8")

    @staticmethod
    def _draft_skeleton_stubs(skeleton_text: str | None) -> dict[str, object]:
        if not skeleton_text:
            return {}
        try:
            payload = json.loads(skeleton_text)
        except json.JSONDecodeError:
            return {}
        modules = payload.get("modules") if isinstance(payload, dict) else None
        if not isinstance(modules, list):
            return {}
        return {
            module["id"]: module
            for module in modules
            if isinstance(module, dict) and isinstance(module.get("id"), str)
        }

    # -- writers ----------------------------------------------------------

    def write_skeleton_draft_prompt(self, topic_id: str) -> DraftUnitPaths:
        """Write ``draft/skeleton/prompt.md`` from the approved outline.

        Called by :meth:`~education_pipeline.runs.RunStore.write_draft_prompt`
        on guide runs, which has already (re)written the immutable guide
        contract and the whole-guide alternative prompt and has already
        applied that call's overwrite rule to the stage prompt; this adds the
        unit the fan-out actually starts from, idempotently.
        """

        safe_id = self._require_draft_units(topic_id)
        order = self._draft_module_order(safe_id)
        contract_path = self._guide_contract_path(safe_id)
        approved_outline = self.read_approved(safe_id, "outline")
        artifact = compile_guide_v1_skeleton_prompt(
            TopicStore(self.root).load_topic(safe_id),
            approved_outline,
            read_bytes_retrying(contract_path),
            self._load_attached_profile(safe_id),
            blueprint=self.run_blueprint(safe_id),
            module_order=order,
        )
        paths = self.draft_unit_paths(safe_id, "skeleton")
        paths.prompt_path.parent.mkdir(parents=True, exist_ok=True)
        _write_text(paths.prompt_path, artifact.text, overwrite=True)
        if not paths.response_path.exists():
            _write_text(paths.stub_path, _unit_stub_text(paths), overwrite=True)
        self._point_stage_stub_at_units(safe_id)
        self._append_unit_prompt_event(safe_id, paths, contract_path=contract_path)
        return paths

    def _orphan_draft_units(self, topic_id: str) -> Path | None:
        """Move every draft unit artifact aside, before the inputs are rebuilt.

        Decision 7b: an outline change rebuilds the guide contract, the
        whole-guide prompt and the skeleton prompt, and "moves existing unit
        responses aside as orphaned". Left in place, the old
        ``draft/skeleton/response.json`` keeps ``draft_progress`` reporting
        ``response_ingested`` and lets a skeleton written against the *old*
        contract be assembled against the new one. Model output is never
        deleted -- everything lands under ``draft/orphaned/<ts>/``, so the
        rebuilt skeleton reads ``prompt_written`` and nothing stale can be
        assembled. Returns the directory it moved things into, or ``None``
        when there was nothing to move.
        """

        safe_id = self._require_draft_units(topic_id)
        draft_dir = self.run_dir(safe_id) / _DRAFT_DIRNAME
        skeleton_dir = draft_dir / _SKELETON_DIRNAME
        modules_dir = draft_dir / _MODULES_DIRNAME
        skeleton_response = skeleton_dir / "response.json"
        module_dirs = (
            sorted(child for child in modules_dir.iterdir() if child.is_dir())
            if modules_dir.is_dir()
            else []
        )
        if not skeleton_response.is_file() and not module_dirs:
            return None

        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        target = draft_dir / _ORPHANED_DIRNAME / stamp
        suffix = 1
        while target.exists():  # two rebuilds within one second
            target = draft_dir / _ORPHANED_DIRNAME / f"{stamp}-{suffix}"
            suffix += 1
        target.mkdir(parents=True)

        moved: list[str] = []
        if skeleton_response.is_file():
            (target / _SKELETON_DIRNAME).mkdir()
            for name in ("response.json", "response.previous.json"):
                source = skeleton_dir / name
                if source.is_file():
                    source.replace(target / _SKELETON_DIRNAME / name)
            moved.append("skeleton")
        if module_dirs:
            modules_dir.replace(target / _MODULES_DIRNAME)
            moved.extend(child.name for child in module_dirs)

        self._append_event(
            safe_id,
            stage="draft",
            action="draft_units_orphaned",
            files={},
            extra={
                "orphaned_dir": _relative_to(target, self.run_dir(safe_id)),
                "units": moved,
            },
        )
        return target

    def _point_stage_stub_at_units(self, topic_id: str) -> None:
        """Rewrite the stage-level draft stub so it names the unit drop targets.

        ``responses/draft.SAVE_RESPONSE_HERE.json`` stays -- it is the
        whole-guide alternative's drop target (decision 5) -- but a manual
        user should not be told to paste a whole course by default.
        """

        from education_pipeline.run_core import _stub_text

        stage_paths = self.stage_paths(topic_id, "draft")
        if not stage_paths.stub_path.exists():
            return
        text = _stub_text(stage_paths) + (
            "\n"
            "This run drafts one module at a time. The primary drop targets are\n"
            "the per-unit files instead:\n"
            "\n"
            "    draft/skeleton/response.json\n"
            "    draft/modules/<module-id>/response.json\n"
            "\n"
            "Saving a whole guide here is still accepted and wins over the units.\n"
        )
        _write_text(stage_paths.stub_path, text, overwrite=True)

    def write_module_draft_prompts(
        self,
        topic_id: str,
        *,
        module_ids: object = None,
        overwrite: bool = False,
    ) -> tuple[DraftUnitPaths, ...]:
        """Write one draft prompt per module, in the authored outline order.

        Requires a skeleton response that passes
        :func:`~education_pipeline.guides.parse.check_skeleton`: the module
        prompts embed the skeleton, so a skeleton that is not a valid stub
        document has nothing to hand them. The unit writers are idempotent
        and deliberately ignore the stage-level
        ``prompt_overwrite_on_advance`` flag -- only an explicit
        ``overwrite`` rewrites a prompt that is already on disk.
        """

        safe_id = self._require_draft_units(topic_id)
        order = self._draft_module_order(safe_id)
        skeleton_text = self._draft_skeleton_text(safe_id)
        if skeleton_text is None:
            raise ConfigError(
                f"no draft skeleton response for {safe_id!r}: save "
                f"{self.draft_unit_paths(safe_id, 'skeleton').response_path} first"
            )
        checked = check_skeleton(skeleton_text, module_order=order)
        if not checked.ok:
            raise ConfigError(
                f"the draft skeleton for {safe_id!r} is not valid: "
                f"{_diagnostics_text(checked)}"
            )

        if module_ids is None:
            targets = order
        else:
            requested = list(module_ids)
            unknown = [name for name in requested if name not in order]
            if unknown:
                raise ConfigError(
                    f"module(s) {', '.join(sorted(unknown))} are not in the outline "
                    f"contract for {safe_id!r}; known modules: {', '.join(order)}"
                )
            targets = tuple(name for name in order if name in set(requested))

        written: list[DraftUnitPaths] = []
        for module_id in targets:
            paths = self.draft_unit_paths(safe_id, "module", module_id=module_id)
            if paths.prompt_path.exists() and not overwrite:
                raise ConfigError(
                    f"draft prompt already written for module {module_id!r}: "
                    f"{paths.prompt_path}"
                )
            written.append(paths)

        topic = TopicStore(self.root).load_topic(safe_id)
        approved_outline = self.read_approved(safe_id, "outline")
        profile = self._load_attached_profile(safe_id)
        blueprint = self.run_blueprint(safe_id)
        contract_path = self._guide_contract_path(safe_id)
        contract_bytes = read_bytes_retrying(contract_path)
        entries = self._draft_contract_entries(safe_id)
        stubs = self._draft_skeleton_stubs(skeleton_text)
        skeleton_sha = hashlib.sha256(skeleton_text.encode("utf-8")).hexdigest()

        for paths in written:
            module_id = paths.module_id
            artifact = compile_guide_v1_module_draft_prompt(
                topic,
                module_id=module_id,
                module_index=order.index(module_id),
                module_order=order,
                skeleton_json=skeleton_text,
                guide_contract=contract_bytes,
                approved_outline=approved_outline,
                profile=profile,
                blueprint=blueprint,
            )
            paths.prompt_path.parent.mkdir(parents=True, exist_ok=True)
            _write_text(paths.prompt_path, artifact.text, overwrite=True)
            if not paths.response_path.exists():
                _write_text(paths.stub_path, _unit_stub_text(paths), overwrite=True)

        # One critical section for the whole batch: N appends, one lock.
        with self._manifest_write_lock(safe_id):
            for paths in written:
                self._append_unit_prompt_event_locked(
                    safe_id,
                    paths,
                    contract_path=contract_path,
                    extra={
                        "contract_entry_sha256": _sha256_of(
                            entries.get(paths.module_id)
                        ),
                        "skeleton_stub_sha256": _sha256_of(stubs.get(paths.module_id)),
                        "skeleton_response_sha256": skeleton_sha,
                    },
                )
        return tuple(written)

    def _append_unit_prompt_event(
        self,
        topic_id: str,
        paths: DraftUnitPaths,
        *,
        contract_path: Path,
        extra: dict[str, object] | None = None,
    ) -> None:
        with self._manifest_write_lock(topic_id):
            self._append_unit_prompt_event_locked(
                topic_id, paths, contract_path=contract_path, extra=extra
            )

    def _append_unit_prompt_event_locked(
        self,
        topic_id: str,
        paths: DraftUnitPaths,
        *,
        contract_path: Path,
        extra: dict[str, object] | None = None,
    ) -> None:
        payload: dict[str, object] = {"unit": paths.unit}
        if paths.module_id is not None:
            payload["module_id"] = paths.module_id
        payload.update(extra or {})
        self._append_event_locked(
            topic_id,
            stage="draft",
            action="unit_prompt_written",
            files={
                "prompt_file": paths.prompt_path,
                "response_file": paths.response_path,
                "source_outline_file": self.stage_paths(
                    topic_id, "outline"
                ).approved_path,
                "contract_file": contract_path,
            },
            extra=payload,
        )

    # -- ingest and edit --------------------------------------------------

    def ingest_draft_unit(
        self,
        topic_id: str,
        unit: str,
        text: str,
        *,
        module_id: str | None = None,
        force: bool = False,
    ) -> DraftUnitPaths:
        """The unit-level twin of ``ingest_response``.

        Same empty-text and never-clobber-without-``force`` rules. A forced
        replacement keeps the prior bytes as ``response.previous.json`` for
        the viewer's diff and records ``unit_response_replaced``. After a
        skeleton ingest the missing module prompts are written (decision 9);
        after a module ingest an assembly is attempted. Nothing approves.
        """

        safe_id = self._require_draft_units(topic_id)
        paths = self.draft_unit_paths(safe_id, unit, module_id=module_id)
        if not text.strip():
            raise ConfigError(
                f"refusing to ingest empty response for draft unit {paths.unit!r}"
            )
        existed = paths.response_path.exists()
        if existed and not force:
            raise ConfigError(
                f"response already ingested for draft unit {paths.unit!r}: "
                f"{paths.response_path}"
            )
        previous = read_bytes_retrying(paths.response_path) if existed else None
        paths.response_path.parent.mkdir(parents=True, exist_ok=True)
        _write_text_atomic(paths.response_path, text)
        if previous is not None:
            _write_bytes_atomic(paths.previous_path, previous)
        if paths.stub_path.exists():
            paths.stub_path.unlink()
        if previous is not None:
            self._append_unit_response_event(
                safe_id,
                paths,
                action="unit_response_replaced",
                extra={"previous_sha256": hashlib.sha256(previous).hexdigest()},
            )
        if paths.unit == "skeleton":
            self._write_missing_module_draft_prompts(safe_id)
        else:
            # A forced rerun forces the assembly it triggers, or the ingest
            # would land while the stage response it supersedes stayed put.
            self._assemble_draft_if_ready(safe_id, force=force)
        return paths

    def edit_draft_unit(
        self,
        topic_id: str,
        unit: str,
        text: str,
        *,
        module_id: str | None = None,
        base_sha256: str,
    ) -> DraftUnitPaths:
        """Guarded read-modify-write of an existing draft unit response."""

        safe_id = self._require_draft_units(topic_id)
        paths = self.draft_unit_paths(safe_id, unit, module_id=module_id)
        if not text.strip():
            raise ConfigError(
                f"refusing to save empty response for draft unit {paths.unit!r}"
            )
        if not paths.response_path.exists():
            raise ConfigError(
                f"no response to edit for draft unit {paths.unit!r}: "
                f"{paths.response_path}"
            )
        current = hashlib.sha256(read_bytes_retrying(paths.response_path)).hexdigest()
        if current != base_sha256:
            raise StaleContentError(
                f"the draft {paths.unit} response changed on disk since it was "
                "loaded; reload the current content before saving"
            )
        _write_text_atomic(paths.response_path, text)
        self._append_unit_response_event(
            safe_id,
            paths,
            action="unit_response_edited",
            extra={"base_sha256": base_sha256},
        )
        if paths.unit == "skeleton":
            self._write_missing_module_draft_prompts(safe_id)
        else:
            self._assemble_draft_if_ready(safe_id)
        return paths

    def _append_unit_response_event(
        self,
        topic_id: str,
        paths: DraftUnitPaths,
        *,
        action: str,
        extra: dict[str, object],
    ) -> None:
        # The unit events name their response hash ``response_sha256`` (design
        # section 1's table), not ``<label>_sha256`` as ``files`` would, so the
        # path and the hash are both spelled out here.
        payload: dict[str, object] = {
            "unit": paths.unit,
            "response_file": _relative_to(paths.response_path, self.run_dir(topic_id)),
            "response_sha256": hashlib.sha256(
                read_bytes_retrying(paths.response_path)
            ).hexdigest(),
        }
        if paths.module_id is not None:
            payload["module_id"] = paths.module_id
        payload.update(extra)
        self._append_event(
            topic_id, stage="draft", action=action, files={}, extra=payload
        )

    def _write_missing_module_draft_prompts(self, topic_id: str) -> None:
        """Decision 9: writing prompts is a machine step, so ingest does it.

        Only the *missing* prompts are written -- a module whose prompt is
        already on disk keeps the inputs it was compiled from, which is what
        makes it read as ``stale`` rather than silently changing under a
        response that is already saved.
        """

        try:
            order = self._draft_module_order(topic_id)
        except ConfigError:
            return
        skeleton_text = self._draft_skeleton_text(topic_id)
        if skeleton_text is None:
            return
        if not check_skeleton(skeleton_text, module_order=order).ok:
            return
        missing = [
            module_id
            for module_id in order
            if not self.draft_unit_paths(
                topic_id, "module", module_id=module_id
            ).prompt_path.exists()
        ]
        if missing:
            self.write_module_draft_prompts(topic_id, module_ids=missing)

    def _assemble_draft_if_ready(self, topic_id: str, *, force: bool = False) -> None:
        """Attempt assembly after a module ingest, never fighting a hand edit."""

        try:
            self.assemble_draft(topic_id, force=force)
        except StaleContentError as exc:
            # Decision 6: the response file wins. Re-running a module against a
            # superseded draft response needs an explicit force -- and the
            # refusal is recorded, so ``draft_progress.assembled.error`` says
            # why the stage response did not move rather than nothing at all.
            self._append_event(
                topic_id,
                stage="draft",
                action="draft_assembly_failed",
                files={},
                extra={"error": str(exc), "module_ids": []},
            )

    # -- assembly ---------------------------------------------------------

    def _last_assembled_sha256(self, topic_id: str) -> str | None:
        event = self._latest_stage_event(topic_id, "draft", "draft_assembled")
        if event is None:
            return None
        recorded = event.get("response_sha256")
        return recorded if isinstance(recorded, str) else None

    def assemble_draft(self, topic_id: str, *, force: bool = False) -> AssembleResult:
        """Assemble the skeleton and every module into the draft response.

        Deterministic: no model call, no approval. A no-op while any module
        is outstanding or stale (and silent -- nothing is recorded for a
        fan-out that is simply unfinished). A stage response file whose bytes
        are not the last assembled bytes was written by hand and is never
        overwritten without ``force``.
        """

        safe_id = self._require_draft_units(topic_id)
        order = self._draft_module_order(safe_id)
        skeleton_text = self._draft_skeleton_text(safe_id)
        if skeleton_text is None:
            return AssembleResult(
                ok=False,
                error=f"no draft skeleton response saved for {safe_id!r}",
            )

        progress_states = self._module_unit_states(safe_id, order, skeleton_text)
        outstanding = tuple(
            module_id
            for module_id in order
            if progress_states.get(module_id) != "response_ingested"
        )
        if outstanding:
            return AssembleResult(
                ok=False,
                error=(
                    f"{len(order) - len(outstanding)} of {len(order)} module responses "
                    f"are saved for {safe_id!r}; outstanding: {', '.join(outstanding)}"
                ),
                module_ids=outstanding,
            )

        module_texts = {
            module_id: read_bytes_retrying(
                self.draft_unit_paths(
                    safe_id, "module", module_id=module_id
                ).response_path
            ).decode("utf-8")
            for module_id in order
        }

        stage_paths = self.stage_paths(safe_id, "draft")
        existing = (
            read_bytes_retrying(stage_paths.response_path)
            if stage_paths.response_path.exists()
            else None
        )
        existing_sha = (
            hashlib.sha256(existing).hexdigest() if existing is not None else None
        )
        superseded = (
            existing is not None and existing_sha != self._last_assembled_sha256(safe_id)
        )
        if superseded and not force:
            raise StaleContentError(
                f"the draft response for {safe_id!r} was written outside the unit "
                "layer; re-assemble with force to replace it"
            )

        try:
            assembled = assemble_guide(
                skeleton_text, module_texts, module_order=order
            )
        except AssemblyError as exc:
            self._append_event(
                safe_id,
                stage="draft",
                action="draft_assembly_failed",
                files={},
                extra={"error": str(exc), "module_ids": list(exc.module_ids)},
            )
            return AssembleResult(
                ok=False, error=str(exc), module_ids=tuple(exc.module_ids)
            )

        digest = hashlib.sha256(assembled).hexdigest()
        if existing == assembled:
            return AssembleResult(
                ok=True, response_sha256=digest, module_ids=tuple(order)
            )
        if superseded:
            self._append_event(
                safe_id,
                stage="draft",
                action="response_replaced",
                files={"replaced_response_file": stage_paths.response_path},
            )
        _write_bytes_atomic(stage_paths.response_path, assembled)
        if stage_paths.stub_path.exists():
            stage_paths.stub_path.unlink()
        self._append_event(
            safe_id,
            stage="draft",
            action="draft_assembled",
            files={},
            extra={
                "response_file": _relative_to(
                    stage_paths.response_path, self.run_dir(safe_id)
                ),
                "response_sha256": digest,
                "skeleton_sha256": hashlib.sha256(
                    skeleton_text.encode("utf-8")
                ).hexdigest(),
                "module_ids": list(order),
                "module_sha256": {
                    module_id: hashlib.sha256(text.encode("utf-8")).hexdigest()
                    for module_id, text in module_texts.items()
                },
            },
        )
        return AssembleResult(ok=True, response_sha256=digest, module_ids=tuple(order))

    # -- progress ---------------------------------------------------------

    def _module_unit_states(
        self, topic_id: str, order: tuple[str, ...], skeleton_text: str | None
    ) -> dict[str, str]:
        """Per-contract-module state, ignoring the superseded/orphaned overlays."""

        entries = self._draft_contract_entries(topic_id)
        stubs = self._draft_skeleton_stubs(skeleton_text)
        recorded = self._recorded_unit_prompt_events(topic_id)
        states: dict[str, str] = {}
        for module_id in order:
            paths = self.draft_unit_paths(topic_id, "module", module_id=module_id)
            has_prompt = paths.prompt_path.exists()
            has_response = paths.response_path.exists()
            if not has_prompt and not has_response:
                states[module_id] = "not_run"
                continue
            event = recorded.get(module_id)
            if event is not None and self._module_inputs_drifted(
                event, entries.get(module_id), stubs.get(module_id)
            ):
                states[module_id] = "stale"
                continue
            states[module_id] = "response_ingested" if has_response else "prompt_written"
        return states

    @staticmethod
    def _module_inputs_drifted(
        event: dict, contract_entry: object, stub: object
    ) -> bool:
        """Decision 7: a module is stale when the inputs its prompt embedded changed.

        Hashed against ``inputs/guide-contract.json`` and the skeleton
        response -- never against the live approved outline, which no arm
        rewrites once the draft prompt exists and which would therefore mark
        every module stale with no action that clears it.
        """

        for key, current in (
            ("contract_entry_sha256", _sha256_of(contract_entry)),
            ("skeleton_stub_sha256", _sha256_of(stub)),
        ):
            recorded = event.get(key)
            if isinstance(recorded, str) and recorded != current:
                return True
        return False

    def _recorded_unit_prompt_events(self, topic_id: str) -> dict[str, dict]:
        """The latest ``unit_prompt_written`` event per module id."""

        path = self.manifest_path(topic_id)
        if not path.is_file():
            return {}
        try:
            events = self.read_manifest(topic_id).get("events", [])
        except ConfigError:
            return {}
        latest: dict[str, dict] = {}
        for event in events:
            if (
                event.get("stage") == "draft"
                and event.get("action") == "unit_prompt_written"
                and event.get("unit") == "module"
                and isinstance(event.get("module_id"), str)
            ):
                latest[event["module_id"]] = event
        return latest

    def _orphaned_module_ids(
        self, topic_id: str, order: tuple[str, ...]
    ) -> tuple[str, ...]:
        """Module unit directories whose id is no longer in the contract.

        Ignored by assembly, never deleted: the design only says an orphan is
        left alone, so a re-added module finds its old response waiting.
        """

        modules_dir = self.run_dir(topic_id) / _DRAFT_DIRNAME / _MODULES_DIRNAME
        if not modules_dir.is_dir():
            return ()
        found = [
            child.name
            for child in sorted(modules_dir.iterdir())
            if child.is_dir()
            and child.name not in order
            and ID_RE.match(child.name)
            and ((child / "prompt.md").is_file() or (child / "response.json").is_file())
        ]
        return tuple(found)

    def draft_progress(self, topic_id: str) -> DraftProgress:
        """A pure read of the run's per-module drafting state.

        Every value is a function of files under ``<run>/draft/``, the
        manifest and the approved outline, so a fresh ``RunStore`` over the
        same workspace reports exactly the same thing.
        """

        safe_id = self._require_draft_units(topic_id)
        skeleton_paths = self.draft_unit_paths(safe_id, "skeleton")
        skeleton_text = self._draft_skeleton_text(safe_id, skeleton_paths)

        assembled = self._recorded_assembly(safe_id)
        response_path = self.stage_paths(safe_id, "draft").response_path
        last_assembled = self._last_assembled_sha256(safe_id)
        superseded = False
        if response_path.exists():
            # With nothing ever assembled, any response on disk came from
            # outside the unit layer by definition -- no need to read and hash
            # a whole guide to learn that on every status poll.
            superseded = last_assembled is None or (
                hashlib.sha256(read_bytes_retrying(response_path)).hexdigest()
                != last_assembled
            )

        if skeleton_text is None:
            # The module units *are* the skeleton's stubs, so nothing below
            # this point needs the contract's module order -- and reading it
            # means parsing the approved outline, which every status poll of
            # every run would otherwise pay for.
            skeleton = DraftUnitStatus(
                unit="skeleton",
                state="prompt_written"
                if skeleton_paths.prompt_path.exists()
                else "not_run",
            )
            return DraftProgress(
                skeleton=skeleton, assembled=assembled, superseded=superseded
            )
        try:
            order = self._draft_module_order(safe_id)
        except ConfigError:
            order = ()
        checked = check_skeleton(skeleton_text, module_order=order)
        skeleton = DraftUnitStatus(
            unit="skeleton",
            state="response_ingested",
            response_sha256=hashlib.sha256(skeleton_text.encode("utf-8")).hexdigest(),
            error=None if checked.ok else _diagnostics_text(checked),
        )

        stubs = self._draft_skeleton_stubs(skeleton_text)
        states = self._module_unit_states(safe_id, order, skeleton_text)
        modules: list[DraftUnitStatus] = []
        for module_id in order + self._orphaned_module_ids(safe_id, order):
            paths = self.draft_unit_paths(safe_id, "module", module_id=module_id)
            if module_id in order:
                state = states[module_id]
            else:
                state = "orphaned"
            if superseded:
                state = "superseded"
            stub = stubs.get(module_id)
            title = stub.get("title") if isinstance(stub, dict) else None
            response_sha = None
            if paths.response_path.is_file():
                response_sha = hashlib.sha256(
                    read_bytes_retrying(paths.response_path)
                ).hexdigest()
            modules.append(
                DraftUnitStatus(
                    unit="module",
                    state=state,
                    module_id=module_id,
                    title=title if isinstance(title, str) else None,
                    response_sha256=response_sha,
                )
            )
        return DraftProgress(
            skeleton=skeleton,
            modules=tuple(modules),
            assembled=assembled,
            superseded=superseded,
        )

    def _recorded_assembly(self, topic_id: str) -> AssembledStatus | None:
        path = self.manifest_path(topic_id)
        if not path.is_file():
            return None
        try:
            events = self.read_manifest(topic_id).get("events", [])
        except ConfigError:
            return None
        for event in reversed(events):
            if event.get("stage") != "draft":
                continue
            action = event.get("action")
            if action == "draft_assembled":
                module_ids = event.get("module_ids")
                return AssembledStatus(
                    ok=True,
                    response_sha256=event.get("response_sha256"),
                    module_ids=tuple(module_ids)
                    if isinstance(module_ids, list)
                    else (),
                )
            if action == "draft_assembly_failed":
                module_ids = event.get("module_ids")
                return AssembledStatus(
                    ok=False,
                    error=event.get("error"),
                    module_ids=tuple(module_ids)
                    if isinstance(module_ids, list)
                    else (),
                )
        return None

    # -- next_action and advance ------------------------------------------

    def _draft_outline_changed(self, topic_id: str) -> bool:
        """Decision 7b: the approved outline moved on since the draft prompt.

        Deliberately keyed to the draft ``prompt_written`` event rather than
        to the stage graph: draft has no graph sources, so ``stage_status``
        never marks it stale, and this arm is scoped to an *unapproved*
        draft by its caller.
        """

        event = self._latest_stage_event(topic_id, "draft", "prompt_written")
        if event is None:
            return False
        recorded = event.get("source_outline_file_sha256")
        if not isinstance(recorded, str):
            return False
        current = self._approved_source_sha(topic_id, "outline")
        return current is not None and current != recorded

    def _draft_assembly_error(self, topic_id: str) -> str | None:
        """A read-only assembly attempt, for the "every module saved" arm.

        Memoized on the exact bytes it reads, so a status poll on an
        unchanged run never re-parses the guide.
        """

        order = self._draft_module_order(topic_id)
        skeleton_text = self._draft_skeleton_text(topic_id)
        if skeleton_text is None:
            return None
        module_texts = {}
        for module_id in order:
            paths = self.draft_unit_paths(topic_id, "module", module_id=module_id)
            if not paths.response_path.is_file():
                return None
            module_texts[module_id] = read_bytes_retrying(
                paths.response_path
            ).decode("utf-8")

        def _attempt() -> str | None:
            try:
                assemble_guide(skeleton_text, module_texts, module_order=order)
            except AssemblyError as exc:
                return str(exc)
            return None

        key = (
            "draft_assembly",
            hashlib.sha256(skeleton_text.encode("utf-8")).hexdigest(),
            tuple(
                (module_id, hashlib.sha256(text.encode("utf-8")).hexdigest())
                for module_id, text in module_texts.items()
            ),
        )
        return self._memoized(key, _attempt)

    def _draft_unit_next_action(self, topic_id: str) -> NextAction | None:
        """The draft slot's unit arms, or ``None`` to fall through to today's.

        Reached from ``_next_action_guide_v1`` only once spec and outline are
        approved, draft is not, and ``responses/draft.response.json`` is
        absent -- decision 6's "the response file wins".
        """

        if not self._mode(topic_id).supports_draft_units:
            return None
        if self._draft_outline_changed(topic_id):
            return NextAction(
                topic_id=topic_id,
                stage="draft",
                action="write_prompt",
                detail=(
                    f"The approved outline for {topic_id!r} changed since the draft "
                    "prompt was written; rebuild the draft inputs (guide contract, "
                    "draft prompt and skeleton prompt)."
                ),
            )
        if not self.stage_paths(topic_id, "draft").prompt_path.is_file():
            # Nothing drafted at all: today's stage arm already says it best.
            return None

        progress = self.draft_progress(topic_id)
        skeleton_paths = self.draft_unit_paths(topic_id, "skeleton")
        if progress.skeleton.state == "not_run":
            return NextAction(
                topic_id=topic_id,
                stage="draft",
                action="write_prompt",
                detail=(
                    f"Write the draft skeleton prompt for {topic_id!r} "
                    f"({skeleton_paths.prompt_path})."
                ),
            )
        if progress.skeleton.state == "prompt_written":
            return NextAction(
                topic_id=topic_id,
                stage="draft",
                action="save_response",
                detail=(
                    f"Run the draft skeleton prompt for {topic_id!r} and save the "
                    f"response to {skeleton_paths.response_path}."
                ),
            )
        if progress.skeleton.error is not None:
            return NextAction(
                topic_id=topic_id,
                stage="draft",
                action="save_response",
                detail=(
                    f"The draft skeleton response for {topic_id!r} is not a valid "
                    f"course skeleton: {progress.skeleton.error}"
                ),
            )

        contract_units = tuple(
            unit for unit in progress.modules if unit.state != "orphaned"
        )
        if any(unit.state == "not_run" for unit in contract_units):
            return NextAction(
                topic_id=topic_id,
                stage="draft",
                action="write_prompt",
                detail=(
                    f"Write the per-module draft prompts for {topic_id!r} "
                    f"(draft/modules/<module-id>/prompt.md)."
                ),
            )
        saved = sum(1 for unit in contract_units if unit.state == "response_ingested")
        if saved < len(contract_units):
            return NextAction(
                topic_id=topic_id,
                stage="draft",
                action="save_response",
                detail=(
                    f"draft: {saved} of {len(contract_units)} module responses saved "
                    f"for {topic_id!r}; run the outstanding module prompts."
                ),
            )
        error = self._draft_assembly_error(topic_id)
        if error is not None:
            return NextAction(
                topic_id=topic_id,
                stage="draft",
                action="save_response",
                detail=(
                    f"Every module response is saved for {topic_id!r} but assembly "
                    f"failed: {error}"
                ),
            )
        # Assembly is deterministic -- no model call -- so it is a machine step
        # ``advance`` performs, exactly like validation and finalization.
        return NextAction(
            topic_id=topic_id,
            stage="draft",
            action="assemble",
            detail=(
                f"All {len(contract_units)} module responses are saved for "
                f"{topic_id!r}; assemble them into the draft response."
            ),
        )

    def _advance_draft_prompt(self, topic_id: str) -> None:
        """Which draft writer ``advance`` runs, re-derived from the unit state."""

        stage_prompt = self.stage_paths(topic_id, "draft").prompt_path
        if self._draft_outline_changed(topic_id):
            # Decision 7b: the unit responses were written against the old
            # contract, so they move aside before the new inputs land.
            self._orphan_draft_units(topic_id)
            self.write_draft_prompt(topic_id, overwrite=True)
            return
        if not stage_prompt.is_file():
            self.write_draft_prompt(topic_id)
            return
        if not self.draft_unit_paths(topic_id, "skeleton").prompt_path.is_file():
            self.write_draft_prompt(topic_id, overwrite=True)
            return
        try:
            order = self._draft_module_order(topic_id)
        except ConfigError:
            order = ()
        if self._draft_skeleton_text(topic_id) is not None:
            missing = [
                module_id
                for module_id in order
                if not self.draft_unit_paths(
                    topic_id, "module", module_id=module_id
                ).prompt_path.exists()
            ]
            if missing:
                self.write_module_draft_prompts(topic_id, module_ids=missing)
                return
        self.write_draft_prompt(topic_id, overwrite=True)
