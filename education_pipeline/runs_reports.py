"""Validation reports, quality reports, and derived report state.

Split verbatim out of ``runs.py``: everything that produces, reads, caches or
judges a run's validation/quality artifacts -- the phase reports under
``reports/``, the personalization trace and public-safe audit projection that
feed them, the export sidecar's quality report, and the ``missing`` /
``current`` / ``stale`` state each of those answers with.
:class:`ReportsMixin` holds no state of its own -- ``RunStore`` supplies every
``self.`` collaborator used here.

Every collaborator is imported at module scope from the leaf module that
owns it, so a test that needs to stub one patches it here, on
``education_pipeline.runs_reports``, rather than on the ``runs`` namespace.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
import hashlib
import json
import threading

from education_pipeline.config import ConfigError
from education_pipeline.guides import (
    DEFAULT_GUIDE_SCHEMA_VERSION,
    Finding,
    Guide,
    MAX_GUIDE_SOURCE_BYTES,
    QUALITY_REPORT_SCHEMA_VERSION,
    REPORT_SCHEMA_VERSION,
    ValidationReport,
    WaiverResult,
    WaiverSet,
    apply_waivers,
    canonical_report_bytes,
    compute_static_checks,
    guide_sha256,
    normalize_guide,
    parse_guide,
    quality_report_bytes,
    validate_guide,
)
from education_pipeline.guide_runtime import RuntimeAssets, load_runtime_assets
from education_pipeline.guides.validation import (
    CalibrationContext,
    PersonalizationValidationContext,
    validation_guide_sha256,
)
from education_pipeline.guides.personalization import (
    SAFE_PERSONALIZATION_FINDING_IDS,
    PersonalizationTraceError,
    PersonalizationTrace,
    authoritative_goals,
    build_personalization_trace,
    canonical_personalization_trace_bytes,
    canonical_safe_personalization_trace_bytes,
    parse_personalization_trace,
    personalization_trace_is_fresh,
)
from education_pipeline.guides.audit import AUDIT_PROJECTION_SCHEMA_VERSION
from education_pipeline.guides.projection import public_guide_projection
from education_pipeline.privacy import profile_private_values
from education_pipeline.profiles import LearnerProfile
from education_pipeline.atomic_io import read_bytes_retrying
from education_pipeline.run_core import StageStatus, _relative_to, _write_bytes_atomic
from education_pipeline.workspace import (
    ProfileStore,
    TopicStore,
    artifact_id as _artifact_id,
)


@dataclass(frozen=True)
class _PublicAuditSnapshot:
    state: str
    projection_bytes: bytes | None = None
    projection_sha256: str | None = None
    findings: tuple[Finding, ...] = ()


@dataclass(frozen=True)
class _ValidationArtifacts:
    safe_id: str
    source_stage: str
    source_path: Path
    report_path: Path
    report: ValidationReport
    trace: PersonalizationTrace | None
    trace_bytes: bytes | None
    profile_snapshot_path: Path | None
    profile_snapshot_sha256: str | None
    source_sha256: str


@dataclass(frozen=True)
class PersonalizationSnapshot:
    """One lock-protected generation for the cockpit personalization view."""

    profile: LearnerProfile | None
    trace: PersonalizationTrace | None
    trace_state: str
    final_report_state: str
    audit_state: str
    audit_stage_state: str
    audit_findings: tuple[Finding, ...]
    findings: tuple[Finding, ...]
    export_state: str


#: Bound for :attr:`RunStore._validation_memo`. A cockpit poll tick touches at
#: most two entries per open run (the draft parse verdict and the final
#: validation report), so this covers a workspace of ~32 open courses while
#: keeping a long-lived daemon's memo from growing without limit.
_VALIDATION_MEMO_LIMIT = 64

#: Bound for the guide-source digest memo. The live working set is a couple of
#: sources per open run (draft and final), so a few hundred entries covers a
#: whole workspace's poll traffic; each entry is two short hex strings.
_GUIDE_SOURCE_SHA_MEMO_LIMIT = 256
_GUIDE_SOURCE_SHA_MEMO: dict[str, str] = {}
_GUIDE_SOURCE_SHA_MEMO_LOCK = threading.Lock()


def _guide_source_sha(text: str) -> str:
    """Hash the guide source the same way ``validate_guide`` records ``guide_sha256``.

    Memoized on the exact input bytes. ``report_state`` answers "is this
    report still current?" on every cockpit poll -- once per phase, per
    course, per tick -- and each answer costs a codepoint sanitize, a full
    parse + normalize, and a canonical re-encode of the entire guide, for
    content that has almost never changed since the previous tick.

    The key is the SHA-256 of the raw input, which makes this a pure-function
    cache rather than run state: equal bytes have equal digests by
    construction, so an edited guide simply misses (no invalidation window,
    no path or topic to go stale) and no content can leak between workspaces
    (identical bytes must hash identically anyway). It is module level
    because ``RunStore`` is constructed freely -- fresh per CLI command, per
    test -- so an instance-scoped memo would rarely be the one that is asked
    twice.

    Bounded by clear-on-full rather than an LRU: overflow costs one
    recomputation per live source and never a wrong answer, which does not
    justify carrying eviction bookkeeping on this path.
    """

    key = hashlib.sha256(text.encode("utf-8")).hexdigest()
    with _GUIDE_SOURCE_SHA_MEMO_LOCK:
        memoized = _GUIDE_SOURCE_SHA_MEMO.get(key)
    if memoized is not None:
        return memoized
    digest = validation_guide_sha256(text)
    with _GUIDE_SOURCE_SHA_MEMO_LOCK:
        if len(_GUIDE_SOURCE_SHA_MEMO) >= _GUIDE_SOURCE_SHA_MEMO_LIMIT:
            _GUIDE_SOURCE_SHA_MEMO.clear()
        _GUIDE_SOURCE_SHA_MEMO[key] = digest
    return digest


class ReportsMixin:
    """Report production, report reading, and report state, mixed into
    :class:`RunStore`."""

    def _memoized(self, key: tuple, compute: Callable[[], object]):
        """Return ``compute()`` for ``key``, reusing this store's cached value.

        The memo is per-``RunStore`` instance (never a module global, never
        keyed on ``topic_id`` alone) so two stores over different workspaces
        can never serve each other's verdicts, and every key below carries a
        content digest of everything the memoized computation reads -- so a
        changed input simply misses. There is deliberately no ``invalidate``
        hook: correctness comes from the key, not from remembering to call
        one.

        Bounded by first-in-first-out eviction. Overflow costs one
        recomputation, never a wrong answer.
        """

        with self._validation_memo_guard:
            if key in self._validation_memo:
                return self._validation_memo[key]
        value = compute()
        with self._validation_memo_guard:
            self._validation_memo[key] = value
            while len(self._validation_memo) > _VALIDATION_MEMO_LIMIT:
                del self._validation_memo[next(iter(self._validation_memo))]
        return value

    def draft_report_path(self, topic_id: str) -> Path:
        return self.run_dir(topic_id) / "reports" / "draft-validation.json"

    def final_report_path(self, topic_id: str) -> Path:
        return self.run_dir(topic_id) / "reports" / "final-validation.json"

    def personalization_trace_path(self, topic_id: str) -> Path:
        return self.run_dir(topic_id) / "reports" / "personalization-trace.json"

    def audit_projection_path(self, topic_id: str) -> Path:
        """Fixed public-safe projection path for the optional local audit."""

        return self.run_dir(topic_id) / "reports" / "personalization-audit-projection.json"

    def audit_state(self, topic_id: str) -> str:
        """Return public audit state: ``not_run`` | ``current`` | ``stale``."""

        safe_id = _artifact_id(topic_id, "topic id")
        with self._manifest_write_lock(safe_id):
            return self._public_audit_snapshot_locked(safe_id).state

    def _public_audit_snapshot_locked(
        self,
        topic_id: str,
        *,
        current_bindings: tuple[str, str, str] | None = None,
    ) -> _PublicAuditSnapshot:
        """Capture one approval-bound audit generation under the topic lock."""

        safe_id = _artifact_id(topic_id, "topic id")
        events = self._manifest_events(safe_id)
        approval_index = next(
            (
                index
                for index in range(len(events) - 1, -1, -1)
                if events[index].get("stage") == "audit"
                and events[index].get("action") == "response_approved"
            ),
            None,
        )
        if approval_index is None:
            return _PublicAuditSnapshot("not_run")
        approval = events[approval_index]
        for event in events[approval_index + 1 :]:
            if event.get("stage") != "audit":
                continue
            if event.get("action") == "audit_approval_started":
                return _PublicAuditSnapshot("stale")
            if event.get("action") == "prompt_written" and not self._prompt_preserves_approval(
                event, approval
            ):
                return _PublicAuditSnapshot("stale")
        try:
            paths = self.stage_paths(safe_id, "audit")
            projection_path = self.audit_projection_path(safe_id)
            projection_bytes = read_bytes_retrying(projection_path)
            file_hashes = {
                "prompt_file_sha256": hashlib.sha256(read_bytes_retrying(paths.prompt_path)).hexdigest(),
                "approved_file_sha256": hashlib.sha256(read_bytes_retrying(paths.approved_path)).hexdigest(),
                "audit_projection_file_sha256": hashlib.sha256(projection_bytes).hexdigest(),
            }
        except (ConfigError, OSError, UnicodeError):
            return _PublicAuditSnapshot("stale")
        if current_bindings is None:
            try:
                inputs = self._current_audit_inputs(safe_id)
                current_bindings = self._audit_input_hashes(inputs)
            except (ConfigError, OSError, UnicodeError):
                return _PublicAuditSnapshot("stale")
        guide_hash, profile_hash, trace_hash = current_bindings
        profile_path = ProfileStore(self.root).topic_profile_snapshot_path(safe_id)
        trace_path = self.personalization_trace_path(safe_id)
        expected = {
            **file_hashes,
            "guide_sha256": guide_hash,
            "profile_snapshot_file_sha256": profile_hash,
            "personalization_trace_file_sha256": trace_hash,
            "prompt_file": _relative_to(paths.prompt_path, self.run_dir(safe_id)),
            "approved_file": _relative_to(paths.approved_path, self.run_dir(safe_id)),
            "profile_snapshot_file": _relative_to(
                profile_path, self.run_dir(safe_id)
            ),
            "personalization_trace_file": _relative_to(
                trace_path, self.run_dir(safe_id)
            ),
            "audit_projection_file": _relative_to(
                projection_path, self.run_dir(safe_id)
            ),
        }
        if not all(approval.get(key) == value for key, value in expected.items()):
            return _PublicAuditSnapshot("stale")
        findings = self._parse_safe_audit_projection(projection_bytes)
        return _PublicAuditSnapshot(
            "current",
            projection_bytes=projection_bytes,
            projection_sha256=file_hashes["audit_projection_file_sha256"],
            findings=findings,
        )

    def personalization_snapshot(self, topic_id: str) -> PersonalizationSnapshot:
        """Capture every personalization-cockpit state from one generation.

        The profile-snapshot lock is acquired before the topic lock and both
        are held across all reads. Every transaction that needs both locks
        follows that profile-then-manifest order; attachment takes only the
        profile lock, and manifest-only writers never acquire the profile lock
        from inside their critical section.
        """

        safe_id = _artifact_id(topic_id, "topic id")
        profiles = ProfileStore(self.root)
        with profiles.topic_profile_snapshot_lock(safe_id):
            with self._manifest_write_lock(safe_id):
                profile_snapshot = self._read_attached_profile_snapshot(safe_id)
                profile = profile_snapshot[0] if profile_snapshot is not None else None

                trace_path = self.personalization_trace_path(safe_id)
                trace: PersonalizationTrace | None = None
                if not trace_path.is_file():
                    trace_state = "missing"
                else:
                    try:
                        trace_bytes = read_bytes_retrying(trace_path)
                        trace = parse_personalization_trace(trace_bytes)
                    except (OSError, PersonalizationTraceError):
                        trace_state = "invalid"
                    else:
                        trace_state = self._personalization_trace_state_for_bytes(
                            safe_id, "final", trace_bytes
                        )

                final_report_state = self.report_state(safe_id, "final")
                audit = self._public_audit_snapshot_locked(safe_id)
                findings = (
                    ()
                    if final_report_state == "missing"
                    else self._combined_findings_locked(
                        safe_id,
                        audit_snapshot=audit,
                    )
                )
                audit_paths = self.stage_paths(safe_id, "audit")
                audit_stale = (
                    (
                        audit_paths.prompt_path.exists()
                        and not self.audit_prompt_is_current(safe_id)
                    )
                    or audit.state == "stale"
                    or self._audit_approval_incomplete(safe_id)
                )
                audit_stage_state = StageStatus(
                    stage="audit",
                    prompt_written=audit_paths.prompt_path.exists(),
                    response_ingested=audit_paths.response_path.exists(),
                    approved=audit_paths.approved_path.exists(),
                    stale=audit_stale,
                ).state
                export_state = self._export_state_locked(
                    safe_id,
                    audit_snapshot=audit,
                )

                return PersonalizationSnapshot(
                    profile=profile,
                    trace=trace,
                    trace_state=trace_state,
                    final_report_state=final_report_state,
                    audit_state=audit.state,
                    audit_stage_state=audit_stage_state,
                    audit_findings=audit.findings,
                    findings=findings,
                    export_state=export_state,
                )

    def combined_findings(
        self, topic_id: str, *, phase: str = "final"
    ) -> tuple[Finding, ...]:
        """Return deterministic findings plus current public-safe audit findings.

        This is the single presentation/export accessor.  It never rewrites the
        persisted validation report and never feeds audit findings into waiver
        or effective-blocking calculations.
        """

        safe_id = _artifact_id(topic_id, "topic id")
        with self._manifest_write_lock(safe_id):
            return self._combined_findings_locked(safe_id, phase=phase)

    def _combined_findings_locked(
        self,
        topic_id: str,
        *,
        phase: str = "final",
        audit_snapshot: _PublicAuditSnapshot | None = None,
    ) -> tuple[Finding, ...]:
        """Unlocked combined-findings projection for an existing topic lock."""

        report = self._read_validation_report(topic_id, phase)
        if phase != "final":
            return report.findings
        if audit_snapshot is None:
            audit_snapshot = self._public_audit_snapshot_locked(topic_id)
        return ValidationReport(
            guide_schema_version=report.guide_schema_version,
            phase=report.phase,
            guide_sha256=report.guide_sha256,
            findings=report.findings + audit_snapshot.findings,
            report_schema_version=report.report_schema_version,
            validator_version=report.validator_version,
        ).findings

    def export_state(self, topic_id: str) -> str:
        """Return ``missing`` | ``current`` | ``stale`` for a guide export.

        Freshness is derived from the complete current export input, not the
        existence of an old HTML/report pair.  Schema-v1 sidecars are readable
        historical artifacts but always require re-export.
        """

        safe_id = _artifact_id(topic_id, "topic id")
        with self._manifest_write_lock(safe_id):
            return self._export_state_locked(safe_id)

    def _export_state_locked(
        self,
        topic_id: str,
        *,
        audit_snapshot: _PublicAuditSnapshot | None = None,
    ) -> str:
        """Unlocked export-state derivation for an existing topic lock."""

        safe_id = _artifact_id(topic_id, "topic id")
        export_path = self.export_path(safe_id, "html")
        report_path = self.export_report_path(safe_id)
        if not export_path.is_file() or not report_path.is_file():
            return "missing"
        # One read serves both the schema check here and the byte comparison
        # against the recomputed report below -- and pins both to the same
        # generation of the file. Report sidecars are written only by
        # _write_bytes_atomic from canonical_report_bytes (JSON, LF-only), so
        # read_text's universal-newline translation was a no-op on them.
        try:
            report_bytes = report_path.read_bytes()
            existing = json.loads(report_bytes.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return "stale"
        if (
            not isinstance(existing, dict)
            or existing.get("quality_report_schema_version")
            != QUALITY_REPORT_SCHEMA_VERSION
        ):
            return "stale"
        if not self._mode(safe_id).supports_validation or not self.is_finalized(safe_id):
            return "stale"
        try:
            assets = load_runtime_assets()
            source_text = self.final_guide_json_path(safe_id).read_text(
                encoding="utf-8"
            )
            profile_snapshot = self._read_attached_profile_snapshot(safe_id)
            profile = profile_snapshot[0] if profile_snapshot else None
            validation_inputs = (
                profile_private_values(profile) if profile else (),
                PersonalizationValidationContext(
                    profile_present=profile is not None,
                    authoritative_goal_ids=tuple(
                        goal.goal_id for goal in authoritative_goals(profile)
                    ) if profile else (),
                ),
                self._calibration_context(safe_id, profile),
            )
            waiver_set = self._load_waiver_set(safe_id)
            report, _, guide = self._validated_final(
                safe_id,
                source_text,
                validation_inputs=validation_inputs,
                assets=assets,
            )
            if guide is None:
                return "stale"
            waiver_result = apply_waivers(report, waiver_set)
            trace_projection, trace_file_sha256 = self._safe_trace_projection_bytes(
                safe_id, report, guide, profile_snapshot
            )
            if audit_snapshot is None:
                audit_snapshot = self._public_audit_snapshot_locked(
                    safe_id,
                    current_bindings=(
                        guide_sha256(guide),
                        profile_snapshot[2],
                        trace_file_sha256,
                    )
                    if profile_snapshot is not None and trace_file_sha256 is not None
                    else None,
                )
            export_bytes = export_path.read_bytes()
            expected = self._quality_report_bytes(
                safe_id,
                report=report,
                waiver_result=waiver_result,
                waiver_set=waiver_set,
                guide=guide,
                export_sha256=hashlib.sha256(export_bytes).hexdigest(),
                runtime_css_sha256=hashlib.sha256(
                    assets.css.encode("utf-8")
                ).hexdigest(),
                runtime_js_sha256=hashlib.sha256(
                    assets.javascript.encode("utf-8")
                ).hexdigest(),
                runtime_version=assets.version,
                audit_snapshot=audit_snapshot,
                trace_projection=trace_projection,
            )
            return "current" if report_bytes == expected else "stale"
        except (ConfigError, OSError, UnicodeError, ValueError):
            return "stale"

    def _read_validation_report(
        self, topic_id: str, phase: str = "final"
    ) -> ValidationReport:
        if phase not in {"draft", "final"}:
            raise ConfigError(f"phase must be 'draft' or 'final'; got {phase!r}")
        path = (
            self.draft_report_path(topic_id)
            if phase == "draft"
            else self.final_report_path(topic_id)
        )
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return ValidationReport.from_dict(payload)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            raise ConfigError(f"invalid validation report: {path}") from exc

    def _parse_safe_audit_projection(
        self, projection_bytes: bytes
    ) -> tuple[Finding, ...]:
        try:
            payload = json.loads(projection_bytes)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ConfigError("current audit projection is invalid") from exc
        if not isinstance(payload, dict) or set(payload) != {
            "schema_version",
            "findings",
        }:
            raise ConfigError("current audit projection is invalid")
        if payload.get("schema_version") != AUDIT_PROJECTION_SCHEMA_VERSION or (
            not isinstance(payload.get("findings"), list)
        ):
            raise ConfigError("current audit projection is invalid")
        try:
            findings = tuple(
                Finding.from_dict(item) for item in payload["findings"]
            )
        except ValueError as exc:
            raise ConfigError("current audit projection is invalid") from exc
        if any(finding.stage != "audit" for finding in findings):
            raise ConfigError("current audit projection is invalid")
        ordered = ValidationReport(
            guide_schema_version=DEFAULT_GUIDE_SCHEMA_VERSION,
            phase="final",
            guide_sha256="",
            findings=findings,
        ).findings
        return ordered

    def _safe_trace_projection_bytes(
        self,
        topic_id: str,
        report: ValidationReport,
        guide: Guide,
        profile_snapshot: tuple[LearnerProfile, Path, str] | None,
    ) -> tuple[bytes | None, str | None]:
        path = self.personalization_trace_path(topic_id)
        if profile_snapshot is None:
            return None, None
        try:
            profile, _, profile_sha256 = profile_snapshot
            if not profile.learning_goals and not path.is_file():
                return None, None
            expected = build_personalization_trace(
                guide,
                profile,
                guide_sha256=validation_guide_sha256(guide),
                profile_snapshot_sha256=profile_sha256,
            )
            captured = path.read_bytes()
            if not personalization_trace_is_fresh(captured, expected_trace=expected):
                raise ConfigError("current personalization trace is stale")
            trace = parse_personalization_trace(captured)
            safe_ids = tuple(
                sorted(
                    {
                        finding.rule_id
                        for finding in report.findings
                        if finding.rule_id in SAFE_PERSONALIZATION_FINDING_IDS
                    }
                )
            )
            projected = canonical_safe_personalization_trace_bytes(
                trace, safe_finding_ids=safe_ids
            )
            if path.read_bytes() != captured:
                raise ConfigError("personalization trace changed during export")
            return projected, hashlib.sha256(captured).hexdigest()
        except (OSError, PersonalizationTraceError) as exc:
            raise ConfigError("current personalization trace is invalid") from exc

    def _quality_report_bytes(
        self,
        topic_id: str,
        *,
        report: ValidationReport,
        waiver_result: WaiverResult,
        waiver_set: WaiverSet | None,
        guide: Guide,
        export_sha256: str,
        runtime_css_sha256: str,
        runtime_js_sha256: str,
        runtime_version: str,
        audit_snapshot: _PublicAuditSnapshot,
        trace_projection: bytes | None,
    ) -> bytes:
        audit_state = audit_snapshot.state
        audit_findings = audit_snapshot.findings
        audit_projection_sha256 = audit_snapshot.projection_sha256
        safe_trace_projection_sha256 = (
            hashlib.sha256(trace_projection).hexdigest()
            if trace_projection is not None
            else None
        )
        public_guide_sha256 = guide_sha256(public_guide_projection(guide))
        persisted_report = self._read_validation_report(topic_id)
        digest_payload = {
            "public_guide_sha256": public_guide_sha256,
            "public_report_sha256": hashlib.sha256(
                canonical_report_bytes(
                    replace(persisted_report, guide_sha256=public_guide_sha256)
                )
            ).hexdigest(),
            "validator_version": report.validator_version,
            "report_schema_version": report.report_schema_version,
            "waiver_result": {
                "gate_open": waiver_result.gate_open,
                "effective_blocking": waiver_result.effective_blocking,
                "waived_finding_ids": list(waiver_result.waived_finding_ids),
                "rejected_finding_ids": list(waiver_result.rejected_finding_ids),
                "orphaned_finding_ids": list(waiver_result.orphaned_finding_ids),
                "stale": waiver_result.stale,
            },
            "audit_state": audit_state,
            "safe_audit_projection_sha256": audit_projection_sha256,
            "safe_trace_projection_sha256": safe_trace_projection_sha256,
            "quality_report_schema_version": QUALITY_REPORT_SCHEMA_VERSION,
            "runtime_version": runtime_version,
            "runtime_css_sha256": runtime_css_sha256,
            "runtime_js_sha256": runtime_js_sha256,
        }
        export_input_sha256 = hashlib.sha256(
            json.dumps(
                digest_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return quality_report_bytes(
            report,
            waiver_result,
            waiver_set,
            export_sha256=export_sha256,
            runtime_css_sha256=runtime_css_sha256,
            runtime_js_sha256=runtime_js_sha256,
            runtime_version=runtime_version,
            public_guide_sha256=public_guide_sha256,
            audit_state=audit_state,
            safe_audit_projection_sha256=audit_projection_sha256,
            safe_trace_projection_sha256=safe_trace_projection_sha256,
            safe_audit_findings=audit_findings,
            export_input_sha256=export_input_sha256,
        )


    def export_report_path(self, topic_id: str) -> Path:
        """Path of the sidecar quality report for the HTML export.

        The HTML export path with a ``.report.json`` suffix appended to its
        stem, in the same directory (``guide.html`` -> ``guide.report.json``).
        """

        export_path = self.export_path(topic_id, "html")
        return export_path.with_name(export_path.stem + ".report.json")

    def report_state(self, topic_id: str, phase: str) -> str:
        """Return ``missing`` | ``current`` | ``stale`` for a validation report.

        Freshness is content-derived from the source approved artifact hash,
        never from file-existence alone.
        """

        safe_id = _artifact_id(topic_id, "topic id")
        if not self._mode(safe_id).supports_validation:
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

        # One read serves both the parse and the digest below. Report files
        # are written only by _write_bytes_atomic from canonical_report_bytes
        # (JSON, LF-terminated, every \r escaped), so read_text's
        # universal-newline translation was a no-op on them -- and decoding
        # here raises the same UnicodeDecodeError read_text did.
        try:
            report_bytes = report_path.read_bytes()
            report = json.loads(report_bytes.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return "stale"
        if not isinstance(report, dict) or report.get("phase") != phase:
            return "stale"
        schema_version = report.get("report_schema_version")
        if not isinstance(schema_version, int) or schema_version < REPORT_SCHEMA_VERSION:
            # A pre-v2 report predates stage attribution. Its findings are
            # still displayed (under the stale banner), but it must not sit
            # "current" forever against unchanged content: reading it stale
            # routes the run through the re-run affordance that already
            # exists, which re-derives the report at the current schema.
            return "stale"
        recorded = report.get("guide_sha256")
        if not isinstance(recorded, str):
            return "stale"
        # Decode from bytes, exactly as _compute_phase_report reads the same
        # file: read_text's universal newlines would strip \r and make a CRLF
        # source hash differently here than at validation time.
        source_text = source_path.read_bytes().decode("utf-8")
        if recorded != _guide_source_sha(source_text):
            return "stale"

        report_sha256 = hashlib.sha256(report_bytes).hexdigest()
        validation_event = next(
            (
                event
                for event in reversed(self.read_manifest(safe_id).get("events", []))
                if event.get("action") == "validated"
                and event.get("phase") == phase
                and event.get("report_file_sha256") == report_sha256
            ),
            None,
        )
        if validation_event is None:
            return "stale"
        snapshot_path = ProfileStore(self.root).topic_profile_snapshot_path(safe_id)
        current_profile_sha256 = (
            hashlib.sha256(snapshot_path.read_bytes()).hexdigest()
            if snapshot_path.is_file()
            else None
        )
        if validation_event.get("profile_snapshot_file_sha256") != current_profile_sha256:
            return "stale"
        return "current"

    def personalization_trace_state(self, topic_id: str, *, phase: str = "final") -> str:
        """Return ``missing`` | ``current`` | ``stale`` for the shared local trace."""

        safe_id = _artifact_id(topic_id, "topic id")
        if phase not in {"draft", "final"}:
            raise ConfigError(f"phase must be 'draft' or 'final'; got {phase!r}")
        trace_path = self.personalization_trace_path(safe_id)
        if not trace_path.is_file():
            return "missing"
        try:
            current = trace_path.read_bytes()
        except OSError:
            return "stale"
        return self._personalization_trace_state_for_bytes(safe_id, phase, current)

    def _personalization_trace_state_for_bytes(
        self, topic_id: str, phase: str, current: bytes
    ) -> str:
        """Derive trace freshness from bytes captured by the current reader."""

        try:
            artifacts = self._compute_phase_report(topic_id, phase)
        except (ConfigError, OSError, UnicodeError):
            return "stale"
        if artifacts.trace is None:
            return "stale"
        return (
            "current"
            if personalization_trace_is_fresh(
                current,
                expected_trace=artifacts.trace,
            )
            else "stale"
        )

    def _require_current_personalization_trace(self, topic_id: str) -> None:
        profile = self._load_attached_profile(topic_id)
        if profile is None or not profile.learning_goals:
            return
        state = self.personalization_trace_state(topic_id, phase="final")
        if state != "current":
            raise ConfigError(
                f"personalization trace is {state} for {topic_id!r}; "
                "run final validation before release"
            )

    def _status_final_report(self, topic_id: str, source_text: str) -> ValidationReport:
        """Final-phase validation report for the status/next-action path,
        memoized per ``RunStore`` instance.

        ``_next_action`` needs this full parse + normalize + static-checks +
        validate pass to decide whether the finalize gate is open, and
        ``run_status_payload`` calls it for every course on every cockpit
        poll tick -- for content that has almost never changed since the
        previous tick. This is the one caller of :meth:`_validated_final`
        that re-asks the same question on a timer, so it is the one that
        memoizes; the explicit recompute paths (``validate_run``,
        ``gate_result``, export/finalize) keep computing fresh, as their
        docstrings promise.

        The key covers *every* input the computation reads, so invalidation
        is by construction and there is no ``invalidate()`` to forget to
        call:

        * the SHA-256 of ``source_text``. A digest of the bytes in hand is
          used in preference to the manifest's recorded ``source_file_sha256``
          or a ``stat`` fingerprint (size + mtime_ns) of the approved file:
          the caller has already read the approved source, so hashing it is
          both cheaper (no second read, no manifest scan) and strictly
          stronger -- an on-disk edit that happened to preserve size and
          mtime still misses.
        * the resolved profile validation inputs (protected values,
          personalization context, calibration context) -- all frozen,
          hashable dataclasses, so they go into the key by value.

        Waivers deliberately do not appear: :meth:`_validated_final` never
        reads them. They are applied downstream by :func:`apply_waivers`, on
        every call, outside this memo.

        Only the report is retained (not the assembled document or the
        normalized guide), and ``ValidationReport`` is a frozen dataclass
        over a tuple of frozen findings, so a cached value cannot be mutated
        by a caller.
        """

        validation_inputs = self._profile_validation_inputs(topic_id)
        return self._memoized(
            (
                "status_final_report",
                hashlib.sha256(source_text.encode("utf-8")).hexdigest(),
                *validation_inputs,
            ),
            lambda: self._validated_final(
                topic_id, source_text, validation_inputs=validation_inputs
            )[0],
        )

    def _validated_final(
        self,
        topic_id: str,
        source_text: str,
        *,
        validation_inputs: tuple[
            tuple[str, ...], PersonalizationValidationContext, CalibrationContext
        ]
        | None = None,
        assets: RuntimeAssets | None = None,
    ) -> tuple[ValidationReport, str | None, Guide | None]:
        """Validate final-phase content with computed static checks.

        Returns ``(report, assembled_document, guide)``. Both ``document`` and
        ``guide`` are ``None`` when the source does not parse (schema blockers
        already in the report) or exceeds ``MAX_GUIDE_SOURCE_BYTES``. When the
        source parses but assembly failed, ``document`` is ``None`` while
        ``guide`` is the normalized guide. Surfacing ``guide`` lets callers
        reuse the single parse instead of re-parsing the source.
        """

        private_values, personalization_context, calibration_context = (
            validation_inputs
            if validation_inputs is not None
            else self._profile_validation_inputs(topic_id)
        )
        if len(source_text.encode("utf-8")) > MAX_GUIDE_SOURCE_BYTES:
            # The raw str path applies the size cap before parsing and records
            # the raw-source sha as the report digest, matching
            # ``_guide_source_sha`` so report_state stays "current".
            return validate_guide(
                source_text,
                phase="final",
                private_values=private_values,
                personalization_context=personalization_context,
                calibration_context=calibration_context,
            ), None, None
        parsed = parse_guide(source_text)
        if not parsed.ok:
            return validate_guide(
                source_text,
                phase="final",
                private_values=private_values,
                personalization_context=personalization_context,
                calibration_context=calibration_context,
            ), None, None
        guide = normalize_guide(parsed)
        result = (
            compute_static_checks(
                guide,
                assets=assets,
                packaged_assets=assets,
            )
            if assets is not None
            else compute_static_checks(guide)
        )
        report = validate_guide(
            guide,
            phase="final",
            context=result.context,
            private_values=private_values,
            personalization_context=personalization_context,
            calibration_context=calibration_context,
        )
        return report, result.document, guide

    def _private_profile_values(self, topic_id: str) -> tuple[str, ...]:
        """Return the shared protected-value policy for an attached profile.

        Kept as a compatibility wrapper for callers that inspect the run's
        active validation denylist. Returns ``()`` when no profile is attached.
        """

        profile = self._load_attached_profile(topic_id)
        if profile is None:
            return ()
        return profile_private_values(profile)

    def _profile_validation_inputs(
        self, topic_id: str
    ) -> tuple[tuple[str, ...], PersonalizationValidationContext, CalibrationContext]:
        """Load one snapshot for profile presence, protected values, and calibration."""

        snapshot = self._read_attached_profile_snapshot(topic_id)
        profile = snapshot[0] if snapshot is not None else None
        return (
            profile_private_values(profile) if profile is not None else (),
            PersonalizationValidationContext(
                profile_present=profile is not None,
                authoritative_goal_ids=tuple(
                    goal.goal_id for goal in authoritative_goals(profile)
                ) if profile is not None else (),
            ),
            self._calibration_context(topic_id, profile),
        )

    def _calibration_context(self, topic_id: str, profile) -> CalibrationContext:
        """Build the run's calibration inputs from topic, manifest, and profile.

        A missing or malformed stored topic degrades to no topic-derived
        checks. Only field presence and declared configuration cross into the
        context; finding messages never carry profile values.
        """

        config = self.blueprint_config(topic_id)
        time_budget = None
        try:
            time_budget = TopicStore(self.root).load_topic(topic_id).time_budget_minutes
        except ConfigError:
            pass
        return CalibrationContext(
            configured_blueprint=config["id"] if config is not None else None,
            time_budget_minutes=time_budget,
            attention_constraints_present=bool(
                profile is not None
                and profile.learning_preferences.attention_constraints
            ),
            learner_skill_level=(
                profile.current_skill_level if profile is not None else None
            ),
        )

    def _compute_phase_report(
        self, topic_id: str, phase: str
    ) -> _ValidationArtifacts:
        """Shared validation core for ``validate_run``, ``gate_result``, and
        ``validate_and_gate``: read the approved phase source and compute its
        report, without writing anything.

        Returns the report and, when construction succeeds, the exact private
        trace derived from the same guide/profile snapshot. Raises
        ``ConfigError`` when there is no approved source for the phase yet
        (nothing to validate).
        """

        safe_id = _artifact_id(topic_id, "topic id")
        if not self._mode(safe_id).supports_validation:
            raise ConfigError("validation applies only to guide runs")
        if phase not in {"draft", "final"}:
            raise ConfigError(f"phase must be 'draft' or 'final'; got {phase!r}")

        source_stage = "draft" if phase == "draft" else "repair"
        source_path = self.stage_paths(safe_id, source_stage).approved_path
        if not source_path.is_file():
            raise ConfigError(
                f"approved {source_stage} response not found: {source_path}"
            )
        source_bytes = source_path.read_bytes()
        source_text = source_bytes.decode("utf-8")
        snapshot = self._read_attached_profile_snapshot(safe_id)
        profile = snapshot[0] if snapshot is not None else None
        profile_snapshot_path = snapshot[1] if snapshot is not None else None
        profile_snapshot_sha256 = snapshot[2] if snapshot is not None else None
        private_values = profile_private_values(profile) if profile is not None else ()
        personalization_context = PersonalizationValidationContext(
            profile_present=profile is not None,
            authoritative_goal_ids=tuple(
                goal.goal_id for goal in authoritative_goals(profile)
            ) if profile is not None else (),
        )
        calibration_context = self._calibration_context(safe_id, profile)
        guide: Guide | None = None
        if phase == "final":
            report, _, guide = self._validated_final(
                safe_id,
                source_text,
                validation_inputs=(
                    private_values,
                    personalization_context,
                    calibration_context,
                ),
            )
        else:
            report = validate_guide(
                source_text,
                phase=phase,
                private_values=private_values,
                personalization_context=personalization_context,
                calibration_context=calibration_context,
            )
            if len(source_text.encode("utf-8")) <= MAX_GUIDE_SOURCE_BYTES:
                parsed = parse_guide(source_text)
                if parsed.ok:
                    guide = normalize_guide(parsed)
        report_path = (
            self.draft_report_path(safe_id) if phase == "draft" else self.final_report_path(safe_id)
        )
        trace = None
        trace_bytes = None
        if profile is not None and guide is not None and profile_snapshot_sha256 is not None:
            try:
                trace = build_personalization_trace(
                    guide,
                    profile,
                    guide_sha256=validation_guide_sha256(guide),
                    profile_snapshot_sha256=profile_snapshot_sha256,
                )
                trace_bytes = canonical_personalization_trace_bytes(trace)
            except (PersonalizationTraceError, UnicodeError, ValueError):
                trace = None
                trace_bytes = None
                trace_finding = Finding(
                    id="personalization.trace_integrity:trace",
                    rule_id="personalization.trace_integrity",
                    severity="error",
                    blocking=True,
                    waivable=False,
                    path="",
                    message="The personalization trace could not be constructed safely.",
                    remediation="Correct the source annotations and rebuild the personalization trace.",
                    stage="draft",
                )
                report = replace(
                    report,
                    findings=report.findings + (trace_finding,),
                )
        return _ValidationArtifacts(
            safe_id=safe_id,
            source_stage=source_stage,
            source_path=source_path,
            report_path=report_path,
            report=report,
            trace=trace,
            trace_bytes=trace_bytes,
            profile_snapshot_path=profile_snapshot_path,
            profile_snapshot_sha256=profile_snapshot_sha256,
            source_sha256=hashlib.sha256(source_bytes).hexdigest(),
        )

    def validate_run(self, topic_id: str, phase: str) -> Path:
        """Run deterministic validation and write the phase report atomically.

        Delegates to :meth:`validate_and_gate` for the persist step (compute,
        write, provenance) and discards the gate result -- keeping the
        "validated" event's provenance identical regardless of which method a
        caller uses.
        """

        self.validate_and_gate(topic_id, phase)
        safe_id = _artifact_id(topic_id, "topic id")
        report_path = (
            self.draft_report_path(safe_id) if phase == "draft" else self.final_report_path(safe_id)
        )
        return report_path

    def gate_result(self, topic_id: str, phase: str) -> WaiverResult:
        """Compute the effective waiver gate for a phase, without writing anything.

        Recomputes the validation report fresh from the approved source (the
        same computation ``validate_run`` performs) rather than trusting a
        possibly-stale persisted report file, then applies the topic's waiver
        set via :func:`apply_waivers`. This mirrors the recompute-then-gate
        pattern already used internally (e.g. ``run_status``'s next-action
        check and ``_export_guide_v1``), so callers never touch
        ``_load_waiver_set`` directly.

        Raises ``ConfigError`` when there is no approved source for the phase
        yet (nothing to validate) -- the same precondition ``validate_run``
        enforces -- so CLI/daemon callers can print a clean error instead of
        a traceback.
        """

        artifacts = self._compute_phase_report(topic_id, phase)
        return apply_waivers(
            artifacts.report,
            self._load_waiver_set(artifacts.safe_id),
        )

    def validate_and_gate(self, topic_id: str, phase: str) -> WaiverResult:
        """Validate a phase, persist the report, and return the resulting gate.

        Equivalent to calling ``validate_run`` followed by ``gate_result``,
        but computes the (expensive, parse+normalize+static-checks) report
        exactly once instead of twice. Intended for callers -- like the CLI's
        ``validate`` command -- that need both the persisted-report side
        effect and the gate outcome from a single invocation.
        """

        safe_id = _artifact_id(topic_id, "topic id")
        with self._profile_generation_lock(safe_id):
            artifacts = self._compute_phase_report(safe_id, phase)
            self.create_run(artifacts.safe_id)
            with self._manifest_write_lock(artifacts.safe_id):
                _write_bytes_atomic(
                    artifacts.report_path,
                    canonical_report_bytes(artifacts.report),
                )
                if artifacts.trace_bytes is not None:
                    _write_bytes_atomic(
                        self.personalization_trace_path(artifacts.safe_id),
                        artifacts.trace_bytes,
                    )
                event_files = {
                    "report_file": artifacts.report_path,
                    "source_file": artifacts.source_path,
                }
                if artifacts.profile_snapshot_path is not None:
                    event_files["profile_snapshot_file"] = artifacts.profile_snapshot_path
                if artifacts.trace_bytes is not None:
                    event_files["personalization_trace_file"] = (
                        self.personalization_trace_path(artifacts.safe_id)
                    )
                event_extra: dict[str, object] = {
                    "phase": phase,
                    "source_file_sha256": artifacts.source_sha256,
                }
                if artifacts.profile_snapshot_sha256 is not None:
                    event_extra["profile_snapshot_file_sha256"] = (
                        artifacts.profile_snapshot_sha256
                    )
                self._append_event_locked(
                    artifacts.safe_id,
                    stage=artifacts.source_stage,
                    action="validated",
                    files=event_files,
                    extra=event_extra,
                )
            return apply_waivers(
                artifacts.report,
                self._load_waiver_set(artifacts.safe_id),
            )
