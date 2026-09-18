"""Learner-profile personalization and the guide-v1 personalization audit.

Split verbatim out of ``runs.py``: the attached-profile snapshot reads, the
immutable ``inputs/guide-contract.json`` write, and the whole
personalization-audit transaction -- compiling and persisting the audit
prompt, deciding whether that prompt still binds current inputs, and the
hash-bound approval that projects a public-safe audit alongside it.
:class:`PersonalizationMixin` holds no state of its own -- ``RunStore``
supplies every ``self.`` collaborator used here.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import hashlib
import json
import threading
import tomllib

from education_pipeline.config import ConfigError
from education_pipeline.guides import (
    ContractError,
    Guide,
    build_guide_contract,
    canonical_guide_bytes,
    extract_outline_contract,
    extract_spec_contract,
    guide_sha256,
    normalize_guide,
    parse_guide,
)
from education_pipeline.guides.audit import (
    AuditResponseError,
    canonical_safe_audit_projection_bytes,
    parse_audit_response,
)
from education_pipeline.privacy import profile_private_values
from education_pipeline.profiles import LearnerProfile, parse_learner_profile
from education_pipeline.prompts import compile_personalization_audit_prompt
from education_pipeline.atomic_io import read_bytes_retrying
from education_pipeline.run_core import (
    PromptFile,
    StaleContentError,
    _FINAL_SOURCE_STAGE,
    _relative_to,
    _stub_text,
    _write_bytes_atomic,
)
from education_pipeline.workspace import ProfileStore, artifact_id as _artifact_id

_GUIDE_CONTRACT_FILENAME = "guide-contract.json"


@dataclass(frozen=True)
class _AuditInputs:
    guide: Guide
    guide_bytes: bytes
    guide_sha256: str
    profile: LearnerProfile
    profile_snapshot_path: Path
    profile_snapshot_sha256: str
    trace_path: Path
    trace_bytes: bytes
    trace_sha256: str


class PersonalizationMixin:
    """Attached-profile reads and the personalization audit, mixed into :class:`RunStore`."""

    def _profile_generation_lock(self, topic_id: str) -> threading.Lock:
        """Return the outer lock for profile-derived run transactions.

        Persisted artifacts derived from an attached profile hold this lock
        across their complete read/validate/write transaction. If the
        manifest lock is also needed, this profile lock is always acquired
        first. Attachment uses the same lock, so replacement can land only
        before or after one persisted generation, never midway through it.
        """

        return ProfileStore(self.root).topic_profile_snapshot_lock(topic_id)

    def _guide_contract_path(self, topic_id: str) -> Path:
        return self.run_dir(topic_id) / "inputs" / _GUIDE_CONTRACT_FILENAME

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
        snapshot = self._read_attached_profile_snapshot(topic_id)
        return snapshot[0] if snapshot is not None else None

    def _read_attached_profile_snapshot(
        self,
        topic_id: str,
    ) -> tuple[LearnerProfile, Path, str] | None:
        """Parse and hash one exact atomic snapshot read."""

        snapshot_path = ProfileStore(self.root).topic_profile_snapshot_path(topic_id)
        if not snapshot_path.exists():
            return None
        try:
            source_bytes = snapshot_path.read_bytes()
            source_text = source_bytes.decode("utf-8")
            profile = parse_learner_profile(tomllib.loads(source_text))
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
            raise ConfigError(
                f"invalid attached learner profile snapshot: {snapshot_path}"
            ) from exc
        return (
            profile,
            snapshot_path,
            hashlib.sha256(source_bytes).hexdigest(),
        )

    def _current_audit_inputs(self, topic_id: str) -> _AuditInputs:
        """Load one exact, eligible set of private audit inputs."""

        safe_id = _artifact_id(topic_id, "topic id")
        if not self._mode(safe_id).supports_audit:
            raise ConfigError(
                "personalization audit unavailable: run is not an interactive guide"
            )
        snapshot = self._read_attached_profile_snapshot(safe_id)
        if snapshot is None:
            raise ConfigError(
                "personalization audit unavailable: no attached profile snapshot"
            )
        profile, snapshot_path, snapshot_sha = snapshot
        if self.report_state(safe_id, "final") != "current":
            raise ConfigError(
                "personalization audit unavailable: final validation is not current"
            )
        if self.personalization_trace_state(safe_id, phase="final") != "current":
            raise ConfigError(
                "personalization audit unavailable: personalization trace is not current"
            )

        source_path = self.stage_paths(safe_id, _FINAL_SOURCE_STAGE).approved_path
        try:
            source = source_path.read_bytes()
            trace_path = self.personalization_trace_path(safe_id)
            trace_bytes = trace_path.read_bytes()
        except OSError as exc:
            raise ConfigError("personalization audit inputs are unavailable") from exc
        parsed = parse_guide(source)
        if not parsed.ok:
            raise ConfigError(
                "personalization audit unavailable: final candidate is invalid"
            )
        guide = normalize_guide(parsed)
        guide_bytes = canonical_guide_bytes(guide)
        return _AuditInputs(
            guide=guide,
            guide_bytes=guide_bytes,
            guide_sha256=guide_sha256(guide),
            profile=profile,
            profile_snapshot_path=snapshot_path,
            profile_snapshot_sha256=snapshot_sha,
            trace_path=trace_path,
            trace_bytes=trace_bytes,
            trace_sha256=hashlib.sha256(trace_bytes).hexdigest(),
        )

    @staticmethod
    def _audit_input_hashes(inputs: _AuditInputs) -> tuple[str, str, str]:
        return (
            inputs.guide_sha256,
            inputs.profile_snapshot_sha256,
            inputs.trace_sha256,
        )

    def prepare_personalization_audit(
        self, topic_id: str, *, overwrite: bool = False
    ) -> PromptFile:
        """Explicitly compile and persist a current personalization-audit prompt."""

        safe_id = _artifact_id(topic_id, "topic id")
        self.create_run(safe_id)
        inputs = self._current_audit_inputs(safe_id)
        artifact = compile_personalization_audit_prompt(
            topic_id=safe_id,
            final_guide_json=inputs.guide_bytes.decode("utf-8"),
            personalization_trace_json=inputs.trace_bytes.decode("utf-8"),
            profile=inputs.profile,
        )
        paths = self.stage_paths(safe_id, "audit")
        prompt_bytes = artifact.text.encode("utf-8")

        with self._manifest_write_lock(safe_id):
            current = self._current_audit_inputs(safe_id)
            if self._audit_input_hashes(current) != self._audit_input_hashes(inputs):
                raise StaleContentError(
                    "personalization audit inputs changed while the prompt was prepared; retry"
                )
            if paths.prompt_path.exists() and not overwrite:
                raise ConfigError(f"refusing to overwrite existing file: {paths.prompt_path}")
            preserved_approval = None
            if self._public_audit_snapshot_locked(safe_id).state == "current":
                candidate = self._latest_stage_event(
                    safe_id, "audit", "response_approved"
                )
                if (
                    candidate is not None
                    and candidate.get("prompt_file_sha256")
                    == hashlib.sha256(prompt_bytes).hexdigest()
                ):
                    preserved_approval = candidate
            _write_bytes_atomic(paths.prompt_path, prompt_bytes)
            if not paths.response_path.exists():
                _write_bytes_atomic(paths.stub_path, _stub_text(paths).encode("utf-8"))
            self._append_event_locked(
                safe_id,
                stage="audit",
                action="prompt_written",
                files={
                    "prompt_file": paths.prompt_path,
                    "profile_snapshot_file": current.profile_snapshot_path,
                    "personalization_trace_file": current.trace_path,
                },
                extra={
                    "guide_sha256": current.guide_sha256,
                    **(
                        {
                            "preserved_approval_event_sha256": (
                                self._manifest_event_sha256(preserved_approval)
                            )
                        }
                        if preserved_approval is not None
                        else {}
                    ),
                },
            )
        return PromptFile(
            stage="audit",
            topic_id=safe_id,
            prompt_path=paths.prompt_path,
            response_path=paths.response_path,
            stub_path=paths.stub_path,
            artifact=artifact,
        )

    def audit_prompt_is_current(self, topic_id: str) -> bool:
        """Whether the latest audit prompt event and bytes bind current inputs."""

        safe_id = _artifact_id(topic_id, "topic id")
        paths = self.stage_paths(safe_id, "audit")
        if not paths.prompt_path.is_file():
            return False
        event = self._latest_stage_event(safe_id, "audit", "prompt_written")
        if event is None:
            return False
        try:
            inputs = self._current_audit_inputs(safe_id)
            prompt_sha = hashlib.sha256(read_bytes_retrying(paths.prompt_path)).hexdigest()
        except (ConfigError, OSError, UnicodeError):
            return False
        return (
            event.get("prompt_file_sha256") == prompt_sha
            and event.get("prompt_file")
            == _relative_to(paths.prompt_path, self.run_dir(safe_id))
            and event.get("guide_sha256") == inputs.guide_sha256
            and event.get("profile_snapshot_file")
            == _relative_to(inputs.profile_snapshot_path, self.run_dir(safe_id))
            and event.get("profile_snapshot_file_sha256")
            == inputs.profile_snapshot_sha256
            and event.get("personalization_trace_file")
            == _relative_to(inputs.trace_path, self.run_dir(safe_id))
            and event.get("personalization_trace_file_sha256") == inputs.trace_sha256
        )

    def _approve_personalization_audit(
        self, topic_id: str, *, overwrite: bool
    ) -> Path:
        """Validate, project, and hash-bind one audit approval transaction."""

        safe_id = _artifact_id(topic_id, "topic id")
        paths = self.stage_paths(safe_id, "audit")
        with self._profile_generation_lock(safe_id):
            self.require_provider_ready_prompt(safe_id, "audit")
            response_bytes = paths.response_path.read_bytes()
            inputs = self._current_audit_inputs(safe_id)
            try:
                audit = parse_audit_response(
                    response_bytes,
                    guide=inputs.guide,
                    trace=inputs.trace_bytes,
                    private_values=profile_private_values(inputs.profile),
                )
            except AuditResponseError as exc:
                raise ConfigError(str(exc)) from exc
            projection_bytes = canonical_safe_audit_projection_bytes(
                audit, guide=inputs.guide
            )
            projection_path = self.audit_projection_path(safe_id)

            with self._manifest_write_lock(safe_id):
                current = self._current_audit_inputs(safe_id)
                if self._audit_input_hashes(current) != self._audit_input_hashes(inputs):
                    raise StaleContentError(
                        "personalization audit inputs changed during approval; retry"
                    )
                if paths.response_path.read_bytes() != response_bytes:
                    raise StaleContentError(
                        "the audit response changed on disk during approval; reload and retry"
                    )
                if not self.audit_prompt_is_current(safe_id):
                    raise StaleContentError(
                        "audit prompt is stale; rebuild it before approval"
                    )
                if paths.approved_path.exists() and not overwrite:
                    raise ConfigError(
                        f"refusing to overwrite existing file: {paths.approved_path}"
                    )

                bindings = {"guide_sha256": current.guide_sha256}
                self._append_event_locked(
                    safe_id,
                    stage="audit",
                    action="audit_approval_started",
                    files={
                        "prompt_file": paths.prompt_path,
                        "response_file": paths.response_path,
                        "profile_snapshot_file": current.profile_snapshot_path,
                        "personalization_trace_file": current.trace_path,
                    },
                    extra=bindings,
                )
                _write_bytes_atomic(paths.approved_path, response_bytes)
                _write_bytes_atomic(projection_path, projection_bytes)
                self._append_event_locked(
                    safe_id,
                    stage="audit",
                    action="response_approved",
                    files={
                        "prompt_file": paths.prompt_path,
                        "approved_file": paths.approved_path,
                        "profile_snapshot_file": current.profile_snapshot_path,
                        "personalization_trace_file": current.trace_path,
                        "audit_projection_file": projection_path,
                    },
                    extra=bindings,
                )
        return paths.approved_path

    @staticmethod
    def _manifest_event_sha256(event: dict) -> str:
        return hashlib.sha256(
            json.dumps(
                event,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

    def _prompt_preserves_approval(self, prompt_event: dict, approval: dict) -> bool:
        if prompt_event.get("preserved_approval_event_sha256") != (
            self._manifest_event_sha256(approval)
        ):
            return False
        binding_fields = (
            "prompt_file",
            "prompt_file_sha256",
            "guide_sha256",
            "profile_snapshot_file",
            "profile_snapshot_file_sha256",
            "personalization_trace_file",
            "personalization_trace_file_sha256",
        )
        return all(
            prompt_event.get(field) == approval.get(field)
            for field in binding_fields
        )

    def _audit_approval_incomplete(self, topic_id: str) -> bool:
        latest_start = -1
        latest_approval = -1
        for index, event in enumerate(self._manifest_events(topic_id)):
            if event.get("stage") != "audit":
                continue
            if event.get("action") == "audit_approval_started":
                latest_start = index
            elif event.get("action") == "response_approved":
                latest_approval = index
        return latest_start > latest_approval
