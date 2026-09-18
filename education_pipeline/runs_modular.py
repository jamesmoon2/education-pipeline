"""The per-module draft lifecycle for :class:`~education_pipeline.runs.RunStore`.

A modular draft replaces the single whole-guide draft response with two
waves (spec D1-D5): one **frame** -- the guide object with an empty stub per
contract module -- and then one response per module, assembled afterwards by
an explicit machine step into the same ``responses/draft.response.json`` the
whole strategy writes. Everything downstream of that file (validate,
approve, qa, ...) is untouched.

:class:`ModularDraftMixin` holds no state of its own -- ``RunStore`` supplies
every ``self.`` collaborator used here. Whole-strategy runs never reach any
of this: ``draft_parts`` returns ``None`` and the walk keeps its existing
behaviour byte for byte.

The three invariants worth stating once, because everything here follows
from them:

* **Parts are keyed, events are not rewritten.** A part's progress is read
  off its latest ``prompt_written`` event plus the files on disk, so a fresh
  ``RunStore`` over the same workspace reports exactly the same snapshot.
* **Staleness is per part.** The frame binds the approved outline and the
  whole contract file; a module binds the approved outline, the frame
  *response* and only its own contract entry -- so re-approving an outline
  that leaves ``m2``'s entry alone leaves ``m2`` current, while a replaced
  frame stales every module.
* **One reverse pass.** Part status is computed from a single walk of the
  manifest's events inside an open ``manifest_read_scope``, never one read
  per part, so a poll tick stays O(events) rather than O(parts x events).
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING
import hashlib
import json

from education_pipeline.config import ConfigError
from education_pipeline.draft_parts import (
    FRAME,
    DraftPart,
    DraftPartsStatus,
    PartPaths,
    PartStatus,
)
from education_pipeline.guides.canonical import SpliceError, assemble_guide, validate_frame
from education_pipeline.prompts import (
    PromptArtifact,
    compile_guide_v1_frame_draft_prompt,
    compile_guide_v1_module_draft_prompt,
)
from education_pipeline.run_core import (
    NextAction,
    PromptFile,
    StaleContentError,
    _stub_text,
    _write_bytes_atomic,
    _write_text,
    _write_text_atomic,
)
from education_pipeline.atomic_io import read_bytes_retrying
from education_pipeline.workspace import TopicStore, artifact_id as _artifact_id

if TYPE_CHECKING:  # pragma: no cover - typing only
    from education_pipeline.runs import RunStore

#: The two strategies ``manifest["draft_strategy"]`` can hold.
DRAFT_STRATEGIES = ("whole", "modular")

#: The default for every manifest without the key, so existing workspaces
#: read exactly as they did before this feature existed.
DEFAULT_DRAFT_STRATEGY = "whole"

_PART_PROMPT_SUFFIX = ".prompt.md"


def validate_draft_strategy(value: str) -> str:
    """Return ``value`` if it names a strategy, else raise ``ConfigError``."""

    if value not in DRAFT_STRATEGIES:
        known = ", ".join(DRAFT_STRATEGIES)
        raise ConfigError(
            f"unknown draft strategy {value!r}; supported strategies: {known}"
        )
    return value


def _canonical_module_sha256(entry: object) -> str:
    """SHA-256 of one contract module entry's canonical JSON.

    Canonical means sorted keys and no whitespace, so the hash is a property
    of the entry's *content*: re-approving an outline that re-serializes the
    same entry differently never stales the module drafted from it.
    """

    return hashlib.sha256(
        json.dumps(entry, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _file_sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(read_bytes_retrying(path)).hexdigest()


def _binds_current(event: dict | None, expected: dict[str, str | None]) -> bool:
    """Whether ``event`` recorded the values in ``expected`` for every label.

    A label the event does not carry is "no dependency to check" -- the same
    grandfathering ``_stage_upstream_stale`` applies to pre-feature events --
    so a hand-written prompt with no event at all reads as current rather
    than as permanently stale.
    """

    if event is None:
        return True
    for label, current in expected.items():
        recorded = event.get(label)
        if recorded is None:
            continue
        if recorded != current:
            return False
    return True


class ModularDraftMixin:
    """The per-module draft strategy, mixed into :class:`RunStore`."""

    # ------------------------------------------------------------------
    # Strategy
    # ------------------------------------------------------------------

    def draft_strategy(self: RunStore, topic_id: str) -> str:
        """The run's recorded draft strategy: ``whole`` or ``modular``.

        A missing manifest, an absent key, or an unrecognized value all read
        as ``whole``, so every workspace created before this feature (and
        every legacy Markdown run) behaves exactly as before.
        """

        try:
            manifest = self.read_manifest(topic_id)
        except (ConfigError, NotADirectoryError):
            return DEFAULT_DRAFT_STRATEGY
        value = manifest.get("draft_strategy")
        if value in DRAFT_STRATEGIES:
            return str(value)
        return DEFAULT_DRAFT_STRATEGY

    def _require_modular(self: RunStore, topic_id: str) -> str:
        if self.draft_strategy(topic_id) != "modular":
            raise ConfigError(
                f"run {topic_id!r} drafts the whole guide in one response; "
                "per-part draft operations require a run created with "
                "draft_strategy='modular'"
            )
        return topic_id

    # ------------------------------------------------------------------
    # Paths
    # ------------------------------------------------------------------

    def draft_part_paths(self: RunStore, topic_id: str, part: DraftPart) -> PartPaths:
        """Filesystem locations for one draft part of a modular run."""

        safe_id = _artifact_id(topic_id, "topic id")
        self._require_modular(safe_id)
        run = self.run_dir(safe_id)
        content_type = self.stage_paths(safe_id, "draft").content_type
        if part.kind == "frame":
            prompts = run / "prompts" / "draft"
            responses = run / "responses" / "draft"
            name = "frame"
        else:
            module_id = str(part.module_id)
            known = self._contract_module_ids(safe_id)
            if module_id not in known:
                listed = ", ".join(known) if known else "(none yet)"
                raise ConfigError(
                    f"module {module_id!r} is not in the guide contract for "
                    f"{safe_id!r}; contract modules: {listed}"
                )
            prompts = run / "prompts" / "draft" / "modules"
            responses = run / "responses" / "draft" / "modules"
            name = module_id
        return PartPaths(
            part=part,
            prompt_path=prompts / f"{name}{_PART_PROMPT_SUFFIX}",
            response_path=responses / f"{name}.response.json",
            stub_path=responses / f"{name}.SAVE_RESPONSE_HERE.json",
            content_type=content_type,
        )

    # ------------------------------------------------------------------
    # The guide contract, read as the module registry
    # ------------------------------------------------------------------

    def _read_guide_contract(self: RunStore, topic_id: str) -> dict | None:
        """The run's ``inputs/guide-contract.json``, or ``None`` when absent."""

        path = self._guide_contract_path(topic_id)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ConfigError(f"invalid guide contract file: {path}") from exc
        if not isinstance(data, dict) or not isinstance(data.get("modules"), dict):
            raise ConfigError(
                f"invalid guide contract file: {path} ('modules' must be a JSON object)"
            )
        return data

    def _contract_module_ids(self: RunStore, topic_id: str) -> tuple[str, ...]:
        """Contract module ids in contract order (the file's own key order)."""

        contract = self._read_guide_contract(topic_id)
        if contract is None:
            return ()
        return tuple(contract["modules"])

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def draft_parts(self: RunStore, topic_id: str) -> DraftPartsStatus | None:
        """A snapshot of this run's draft fan-out, or ``None`` on a whole run."""

        safe_id = _artifact_id(topic_id, "topic id")
        if self.draft_strategy(safe_id) != "modular":
            return None
        with self.manifest_read_scope():
            return self._draft_parts_snapshot(safe_id)

    def _latest_part_events(self: RunStore, topic_id: str) -> tuple[dict, dict | None]:
        """One reverse pass over the manifest: per-part prompts, last assembly.

        Returns ``({part key: latest prompt_written event}, latest
        draft_assembled event)``. Deliberately a single walk shared by every
        part (spec D4): one status read must not cost one manifest scan per
        module.
        """

        prompts: dict[str, dict] = {}
        assembled: dict | None = None
        for event in reversed(self._manifest_events(topic_id)):
            if event.get("stage") != "draft":
                continue
            action = event.get("action")
            if action == "draft_assembled":
                if assembled is None:
                    assembled = event
                continue
            if action != "prompt_written":
                continue
            part = DraftPart.from_manifest(event.get("part"))
            if part is None:
                continue
            prompts.setdefault(part.key, event)
        return prompts, assembled

    def _part_status(
        self: RunStore,
        part: DraftPart,
        paths: PartPaths,
        event: dict | None,
        expected: dict[str, str | None],
    ) -> PartStatus:
        prompt_exists = paths.prompt_path.is_file()
        response_exists = paths.response_path.is_file()
        prompt_current = prompt_exists and _binds_current(event, expected)
        if not prompt_exists:
            state = "missing"
        elif not prompt_current:
            state = "stale"
        elif response_exists:
            state = "responded"
        else:
            state = "prompted"
        return PartStatus(
            part=part,
            state=state,
            prompt_path=paths.prompt_path,
            response_path=paths.response_path,
            prompt_current=prompt_current,
            response_current=prompt_current and response_exists,
        )

    def _draft_parts_snapshot(self: RunStore, topic_id: str) -> DraftPartsStatus:
        """Build the fan-out snapshot. Caller holds a ``manifest_read_scope``."""

        contract = self._read_guide_contract(topic_id)
        modules_contract = contract["modules"] if contract is not None else {}
        module_ids = tuple(modules_contract)
        outline_sha = _file_sha256(self.stage_paths(topic_id, "outline").approved_path)
        contract_sha = _file_sha256(self._guide_contract_path(topic_id))

        prompt_events, assembled_event = self._latest_part_events(topic_id)

        frame_paths = self.draft_part_paths(topic_id, FRAME)
        frame = self._part_status(
            FRAME,
            frame_paths,
            prompt_events.get(FRAME.key),
            {
                "source_outline_file_sha256": outline_sha,
                "contract_file_sha256": contract_sha,
            },
        )
        frame_sha = _file_sha256(frame_paths.response_path)

        modules: list[PartStatus] = []
        module_shas: dict[str, str | None] = {}
        for module_id in module_ids:
            part = DraftPart("module", module_id)
            paths = self.draft_part_paths(topic_id, part)
            modules.append(
                self._part_status(
                    part,
                    paths,
                    prompt_events.get(part.key),
                    {
                        "source_outline_file_sha256": outline_sha,
                        "frame_file_sha256": frame_sha,
                        "contract_module_sha256": _canonical_module_sha256(
                            modules_contract[module_id]
                        ),
                    },
                )
            )
            module_shas[module_id] = _file_sha256(paths.response_path)

        assembled_path = self.stage_paths(topic_id, "draft").response_path
        assembled_sha = _file_sha256(assembled_path)
        recorded_sha = (
            assembled_event.get("response_file_sha256")
            if assembled_event is not None
            else None
        )
        if assembled_sha is None:
            assembled = "absent"
        elif recorded_sha == assembled_sha:
            assembled = "matches_record"
        else:
            assembled = "edited"

        current_parts = {"frame": frame_sha, "modules": dict(module_shas)}
        recorded_parts = (
            assembled_event.get("parts") if assembled_event is not None else None
        )
        assembled_stale = recorded_parts != current_parts

        return DraftPartsStatus(
            strategy="modular",
            module_ids=module_ids,
            frame=frame,
            modules=tuple(modules),
            assembled=assembled,
            assembled_stale=assembled_stale,
        )

    def _modular_draft_stage_flags(self: RunStore, topic_id: str) -> tuple[bool, bool]:
        """``(prompt_written, response_ingested)`` for a modular draft stage.

        ``prompt_written`` means every prompt the run currently needs is
        written and current -- the frame while the frame is outstanding, then
        every module prompt as well. ``response_ingested`` is the assembled
        file's presence, exactly the file the whole strategy would have
        written.
        """

        with self.manifest_read_scope():
            status = self._draft_parts_snapshot(topic_id)
        prompt_written = status.frame.state in ("prompted", "responded")
        if status.frame.state == "responded":
            prompt_written = all(
                module.state in ("prompted", "responded") for module in status.modules
            )
        return prompt_written, status.assembled != "absent"

    # ------------------------------------------------------------------
    # Next action
    # ------------------------------------------------------------------

    def _modular_draft_next_action(
        self: RunStore, topic_id: str
    ) -> NextAction | None:
        """The draft arm of the guide-v1 walk on a modular run (spec D5).

        ``None`` once the assembled response is present and current, which is
        the point the walk falls through to the ordinary whole-draft
        behaviour (validate / approve / ...).
        """

        status = self._draft_parts_snapshot(topic_id)
        frame_paths = self.draft_part_paths(topic_id, FRAME)

        if status.frame.state in ("missing", "stale"):
            return NextAction(
                topic_id=topic_id,
                stage="draft",
                action="write_prompt",
                detail=f"Write the draft frame prompt for {topic_id!r}.",
                wave="frame",
            )
        if status.frame.state == "prompted":
            return NextAction(
                topic_id=topic_id,
                stage="draft",
                action="save_response",
                detail=(
                    f"Run the draft frame prompt for {topic_id!r} and save the response "
                    f"to {frame_paths.response_path}."
                ),
                wave="frame",
            )

        unprompted = status.unprompted_module_ids()
        if unprompted:
            return NextAction(
                topic_id=topic_id,
                stage="draft",
                action="write_prompt",
                detail=(
                    f"Write the draft module prompts for {topic_id!r} "
                    f"({', '.join(unprompted)})."
                ),
                wave="modules",
            )

        waiting = status.waiting_module_ids()
        if waiting:
            total = len(status.modules)
            return NextAction(
                topic_id=topic_id,
                stage="draft",
                action="save_response",
                detail=(
                    f"Draft modules for {topic_id!r}: {total - len(waiting)} of {total} "
                    f"module responses saved (waiting: {', '.join(waiting)})."
                ),
                wave="modules",
            )

        if status.assembled == "absent" or status.assembled_stale:
            return NextAction(
                topic_id=topic_id,
                stage="draft",
                action="assemble",
                detail=(
                    f"Assemble the {len(status.modules)} drafted module(s) of "
                    f"{topic_id!r} into the draft response."
                ),
                wave="modules",
            )
        return None

    # ------------------------------------------------------------------
    # Writing part prompts
    # ------------------------------------------------------------------

    def write_draft_part_prompts(
        self: RunStore,
        topic_id: str,
        *,
        parts: Sequence[str] | None = None,
        overwrite: bool = False,
    ) -> tuple[PromptFile, ...]:
        """Write the draft prompts the current wave needs, and log each one.

        On the frame wave (no current frame response) this writes the one
        frame prompt; ``parts`` must be empty there, because the frame is
        never a member of a modules filter. On the modules wave it writes one
        prompt per module that is missing or stale -- every module when
        ``overwrite`` is set, or exactly the ``parts`` subset when one is
        given, naming module ids only.

        Like the whole-draft writer, this establishes the immutable
        ``inputs/guide-contract.json`` first, so every part prompt in a run
        embeds the same contract bytes.
        """

        safe_id = _artifact_id(topic_id, "topic id")
        self._require_modular(safe_id)
        topic = TopicStore(self.root).load_topic(safe_id)
        approved_outline = self.read_approved(safe_id, "outline")
        profile = self._load_attached_profile(safe_id)
        self.create_run(safe_id)
        contract_bytes = self._write_guide_contract(
            safe_id, profile=profile, overwrite=overwrite
        )
        blueprint = self.run_blueprint(safe_id)
        outline_path = self.stage_paths(safe_id, "outline").approved_path
        contract_path = self._guide_contract_path(safe_id)

        with self.manifest_read_scope():
            status = self._draft_parts_snapshot(safe_id)

        if status.frame.state != "responded":
            if parts:
                raise ConfigError(
                    f"run {safe_id!r} is on the draft frame wave; a parts filter names "
                    "module ids and applies only once the frame response is saved"
                )
            if status.frame.state == "prompted" and not overwrite:
                return ()
            artifact = compile_guide_v1_frame_draft_prompt(
                topic,
                approved_outline,
                contract_bytes,
                profile,
                blueprint=blueprint,
            )
            return (
                self._write_part_prompt(
                    safe_id,
                    FRAME,
                    artifact,
                    files={
                        "source_outline_file": outline_path,
                        "contract_file": contract_path,
                    },
                    extra={"part": FRAME.to_manifest()},
                ),
            )

        contract = self._read_guide_contract(safe_id) or {"modules": {}}
        modules_contract = contract["modules"]
        targets = self._modules_wave_targets(safe_id, status, parts, overwrite)
        frame_paths = self.draft_part_paths(safe_id, FRAME)
        frame_json = frame_paths.response_path.read_text(encoding="utf-8")

        written: list[PromptFile] = []
        for module_id in targets:
            artifact = compile_guide_v1_module_draft_prompt(
                topic,
                approved_outline,
                contract_bytes,
                module_id=module_id,
                frame_json=frame_json,
                profile=profile,
                blueprint=blueprint,
            )
            part = DraftPart("module", module_id)
            written.append(
                self._write_part_prompt(
                    safe_id,
                    part,
                    artifact,
                    files={
                        "source_outline_file": outline_path,
                        "contract_file": contract_path,
                        "frame_file": frame_paths.response_path,
                    },
                    extra={
                        "part": part.to_manifest(),
                        "contract_module_sha256": _canonical_module_sha256(
                            modules_contract[module_id]
                        ),
                    },
                )
            )
        return tuple(written)

    def _modules_wave_targets(
        self: RunStore,
        topic_id: str,
        status: DraftPartsStatus,
        parts: Sequence[str] | None,
        overwrite: bool,
    ) -> tuple[str, ...]:
        """Which module ids this modules-wave call writes prompts for."""

        if parts:
            known = set(status.module_ids)
            targets: list[str] = []
            for requested in parts:
                if requested not in known:
                    listed = ", ".join(status.module_ids) or "(none)"
                    raise ConfigError(
                        f"{requested!r} is not a module of run {topic_id!r}; a parts "
                        f"filter names module ids only. Contract modules: {listed}"
                    )
                if requested not in targets:
                    targets.append(requested)
            return tuple(targets)
        if overwrite:
            return status.module_ids
        return status.unprompted_module_ids()

    def _write_part_prompt(
        self: RunStore,
        topic_id: str,
        part: DraftPart,
        artifact: PromptArtifact,
        *,
        files: dict[str, Path],
        extra: dict[str, object],
    ) -> PromptFile:
        """Write one part prompt plus its stub and log its ``prompt_written``.

        The whole-stage twin of this is ``RunStore._write_prompt``; the parts
        differ only in which paths they write, so the stub placeholder text
        and the event shape are the shared ones.
        """

        paths = self.draft_part_paths(topic_id, part)
        # The caller has already decided this part needs a prompt (missing,
        # stale, or explicitly named), so a rewrite in place is the intent --
        # the refusal that protects a whole stage's prompt would only strand
        # the wave.
        _write_text(paths.prompt_path, artifact.text, overwrite=True)
        if not paths.response_path.exists():
            _write_text(paths.stub_path, _stub_text(paths), overwrite=True)
        event_files: dict[str, Path] = {
            "prompt_file": paths.prompt_path,
            "response_file": paths.response_path,
        }
        event_files.update(files)
        self._append_event(
            topic_id,
            stage="draft",
            action="prompt_written",
            files=event_files,
            extra=extra,
        )
        return PromptFile(
            stage="draft",
            topic_id=topic_id,
            prompt_path=paths.prompt_path,
            response_path=paths.response_path,
            stub_path=paths.stub_path,
            artifact=artifact,
        )

    # ------------------------------------------------------------------
    # Ingesting part responses
    # ------------------------------------------------------------------

    def ingest_part_response(
        self: RunStore,
        topic_id: str,
        part: DraftPart,
        text: str,
        *,
        force: bool = False,
    ) -> Path:
        """Atomically land one part's model response, shape-checked first.

        The frame gets the lenient frame check (it can never pass strict
        parsing: stubs have no sections); a module must be exactly one module
        object keeping its contract id. Strict validation of the whole guide
        happens once, at assembly. A hand-saved file at the printed path
        counts as responded without an event, exactly as a whole stage's does.
        """

        safe_id = _artifact_id(topic_id, "topic id")
        paths = self.draft_part_paths(safe_id, part)
        if not text.strip():
            raise ConfigError(
                f"refusing to ingest empty response for draft part {part.key!r}"
            )
        if part.kind == "frame":
            try:
                validate_frame(text, module_ids=self._contract_module_ids(safe_id))
            except SpliceError as exc:
                raise ConfigError(
                    f"cannot ingest the draft frame for {safe_id!r}: {exc}"
                ) from exc
        else:
            self._check_module_response(safe_id, str(part.module_id), text)

        if paths.response_path.exists():
            if not force:
                raise ConfigError(
                    f"response already ingested for draft part {part.key!r}: "
                    f"{paths.response_path}"
                )
            self._append_event(
                safe_id,
                stage="draft",
                action="response_replaced",
                files={"replaced_response_file": paths.response_path},
                extra={"part": part.to_manifest()},
            )
        _write_text_atomic(paths.response_path, text)
        if paths.stub_path.exists():
            paths.stub_path.unlink()
        self._append_event(
            safe_id,
            stage="draft",
            action="response_ingested",
            files={"response_file": paths.response_path},
            extra={"part": part.to_manifest()},
        )
        return paths.response_path

    def _check_module_response(self: RunStore, topic_id: str, module_id: str, text: str) -> None:
        """Refuse anything but exactly one module object keeping its id.

        A whole guide pasted into a module's file is the mistake worth
        catching here rather than at assembly: ``modules`` is the key that
        tells the two apart, and a renamed module is a blocking error, never
        a silent fix.
        """

        try:
            module = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ConfigError(
                f"draft module {module_id!r} response is not valid JSON: {exc}"
            ) from exc
        if not isinstance(module, dict):
            raise ConfigError(
                f"draft module {module_id!r} response must be a single JSON object"
            )
        if "modules" in module:
            raise ConfigError(
                f"draft module {module_id!r} response must be one module object, not a "
                "whole guide (it carries a `modules` key)"
            )
        found = module.get("id")
        if not isinstance(found, str) or found != module_id:
            raise ConfigError(
                f"draft module response must keep its contract id {module_id!r}; "
                f"got {found!r}"
            )

    # ------------------------------------------------------------------
    # Assembly
    # ------------------------------------------------------------------

    def assemble_draft(self: RunStore, topic_id: str, *, force: bool = False) -> Path:
        """Merge the frame and every module response into the draft response.

        The machine step of the modular draft (spec D3): it is the only
        writer of ``responses/draft.response.json`` on this path, so the
        approve-and-continue chain downstream stays exactly what it is for a
        whole draft. A hand edit to the assembled file (``edit_response`` or
        an external write) is detected against the last ``draft_assembled``
        record and refused unless ``force``.
        """

        safe_id = _artifact_id(topic_id, "topic id")
        self._require_modular(safe_id)
        with self.manifest_read_scope():
            status = self._draft_parts_snapshot(safe_id)
            _, assembled_event = self._latest_part_events(safe_id)

        waiting = [
            part.part.key
            for part in (status.frame, *status.modules)
            if part.state != "responded"
        ]
        if waiting or not status.module_ids:
            listed = ", ".join(waiting) or "(no contract modules)"
            raise ConfigError(
                f"cannot assemble the draft for {safe_id!r} while parts are missing or "
                f"stale: {listed}"
            )

        frame_paths = self.draft_part_paths(safe_id, FRAME)
        module_paths = {
            module_id: self.draft_part_paths(safe_id, DraftPart("module", module_id))
            for module_id in status.module_ids
        }
        try:
            assembled = assemble_guide(
                frame_paths.response_path.read_text(encoding="utf-8"),
                {
                    module_id: paths.response_path.read_text(encoding="utf-8")
                    for module_id, paths in module_paths.items()
                },
                module_ids=status.module_ids,
            )
        except SpliceError as exc:
            raise ConfigError(
                f"cannot assemble the draft for {safe_id!r}: {exc}"
            ) from exc

        stage_paths = self.stage_paths(safe_id, "draft")
        if stage_paths.response_path.exists():
            current = _file_sha256(stage_paths.response_path)
            recorded = (
                assembled_event.get("response_file_sha256")
                if assembled_event is not None
                else None
            )
            if recorded != current:
                if not force:
                    raise StaleContentError(
                        f"the assembled draft response for {safe_id!r} changed on disk "
                        "since it was assembled; reassemble with force to discard that "
                        "edit"
                    )
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
            files={"response_file": stage_paths.response_path},
            extra={
                "parts": {
                    "frame": _file_sha256(frame_paths.response_path),
                    "modules": {
                        module_id: _file_sha256(paths.response_path)
                        for module_id, paths in module_paths.items()
                    },
                }
            },
        )
        return stage_paths.response_path
