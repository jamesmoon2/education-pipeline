"""Deterministic finalize and export: the two steps that never call a model.

Split verbatim out of ``runs.py``: the ``final/`` artifact paths, the
hash-derived "is this run still finalized?" check, the finalize transaction
that assembles the approved repair into ``final/guide.json`` plus its
projected Markdown, and the export transaction that renders the packaged
runtime into a self-contained document with its quality-report sidecar.
:class:`FinalizeMixin` holds no state of its own -- ``RunStore`` supplies
every ``self.`` collaborator used here, and
:mod:`education_pipeline.run_modes` calls several of these on the store.
"""

from __future__ import annotations

from pathlib import Path
import hashlib

from education_pipeline.config import SUPPORTED_STAGES, ConfigError
from education_pipeline.export import EXPORT_FORMATS
from education_pipeline.guides import (
    apply_waivers,
    canonical_guide_bytes,
    guide_sha256,
    normalize_guide,
    parse_guide,
    project_guide_markdown,
)
from education_pipeline.guides.personalization import authoritative_goals
from education_pipeline.guides.validation import PersonalizationValidationContext
from education_pipeline.guide_runtime import load_runtime_assets
from education_pipeline.privacy import profile_private_values
from education_pipeline.run_core import (
    _FINAL_SOURCE_STAGE,
    _write_bytes_atomic,
    _write_text_atomic,
)
from education_pipeline.workspace import artifact_id as _artifact_id

_FINAL_FILENAME = "guide.md"


class FinalizeMixin:
    """Deterministic finalize and export, mixed into :class:`RunStore`."""

    def final_path(self, topic_id: str) -> Path:
        """Path of the assembled final guide for a run (legacy ``final/guide.md``)."""

        return self.run_dir(topic_id) / "final" / _FINAL_FILENAME

    def final_guide_json_path(self, topic_id: str) -> Path:
        """Path of the guide-v1 final JSON artifact (``final/guide.json``)."""

        return self.final_path(topic_id).with_name("guide.json")

    def final_guide_md_path(self, topic_id: str) -> Path:
        """Path of the guide-v1 projected Markdown artifact (``final/guide.md``)."""

        return self.final_path(topic_id).with_name("guide.md")

    def is_finalized(self, topic_id: str) -> bool:
        """Whether the run's final guide has been assembled.

        Legacy runs: file existence of ``final/guide.md``. Guide-v1 runs: hash-
        derived — a finalized event must exist, both final artifacts must exist,
        and the event's ``source_file_sha256`` must still match the current
        approved repair bytes.
        """

        safe_id = _artifact_id(topic_id, "topic id")
        return self._mode(safe_id).is_finalized(self, safe_id)

    def _is_finalized_guide_v1(self, topic_id: str) -> bool:
        """Hash-derived finalized check for an interactive-guide run.

        A finalized event must exist, both final artifacts must exist, and the
        event's ``source_file_sha256`` must still match the current approved
        repair bytes.
        """

        final_json = self.final_guide_json_path(topic_id)
        final_md = self.final_guide_md_path(topic_id)
        if not final_json.is_file() or not final_md.is_file():
            return False

        try:
            events = self.read_manifest(topic_id).get("events", [])
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
        source = self.stage_paths(topic_id, _FINAL_SOURCE_STAGE).approved_path
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
        return self._mode(safe_id).finalize(self, safe_id, overwrite=overwrite)

    def _finalize_guide_v1(self, topic_id: str, *, overwrite: bool) -> Path:
        source_text = self.read_approved(topic_id, _FINAL_SOURCE_STAGE)
        if self.report_state(topic_id, "final") != "current":
            raise ConfigError(
                f"final validation is missing or stale for {topic_id!r}; "
                "run final validation before finalizing"
            )
        self._require_current_personalization_trace(topic_id)

        report, _, _ = self._validated_final(topic_id, source_text)
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
        mode = self._mode(safe_id)
        if format != "html" and not mode.supports_markdown_export:
            raise ConfigError("guide-v1 runs support only HTML export")
        return mode.export(self, safe_id, format=format, overwrite=overwrite)

    def _export_guide_v1(self, topic_id: str, *, overwrite: bool) -> Path:
        """Export only the finalized canonical guide through the packaged runtime."""

        safe_id = _artifact_id(topic_id, "topic id")
        with self._profile_generation_lock(safe_id):
            with self._manifest_write_lock(safe_id):
                return self._export_guide_v1_locked(safe_id, overwrite=overwrite)

    def _export_guide_v1_locked(self, topic_id: str, *, overwrite: bool) -> Path:
        """Build and persist one immutable export snapshot under the topic lock."""

        final_json = self.final_guide_json_path(topic_id)
        if not final_json.is_file() or not self.is_finalized(topic_id):
            raise ConfigError(f"run {topic_id!r} is not currently finalized")
        if self.report_state(topic_id, "final") != "current":
            raise ConfigError("final validation is missing or stale; revalidate before export")
        assets = load_runtime_assets()
        source_text = final_json.read_text(encoding="utf-8")
        profile_snapshot = self._read_attached_profile_snapshot(topic_id)
        profile = profile_snapshot[0] if profile_snapshot else None
        validation_inputs = (
            profile_private_values(profile) if profile else (),
            PersonalizationValidationContext(
                profile_present=profile is not None,
                authoritative_goal_ids=tuple(
                    goal.goal_id for goal in authoritative_goals(profile)
                ) if profile else (),
            ),
            self._calibration_context(topic_id, profile),
        )
        waiver_set = self._load_waiver_set(topic_id)
        report, document, guide = self._validated_final(
            topic_id,
            source_text,
            validation_inputs=validation_inputs,
            assets=assets,
        )
        waiver_result = apply_waivers(report, waiver_set)
        if not waiver_result.gate_open:
            raise ConfigError(
                f"cannot export {topic_id!r}: "
                f"{waiver_result.effective_blocking} blocking finding(s) remain"
            )
        if document is None or guide is None:
            # An open waiver gate guarantees no render_failed blocker, so the
            # checked document and its guide are present. Guard defensively
            # against a None write, keeping the failure on the 400-mapped
            # ConfigError path (any mapped status is fine; the last-resort 500
            # handler is not).
            raise ConfigError(
                f"cannot export {topic_id!r}: the checked guide document is unavailable"
            )
        trace_projection, trace_file_sha256 = self._safe_trace_projection_bytes(
            topic_id, report, guide, profile_snapshot
        )
        audit_snapshot = self._public_audit_snapshot_locked(
            topic_id,
            current_bindings=(
                guide_sha256(guide),
                profile_snapshot[2],
                trace_file_sha256,
            )
            if profile_snapshot is not None and trace_file_sha256 is not None
            else None,
        )
        content = document
        export_path = self.export_path(topic_id, "html")
        if export_path.exists() and not overwrite:
            raise ConfigError(f"refusing to overwrite existing file: {export_path}")
        _write_text_atomic(export_path, content)

        export_sha256 = hashlib.sha256(content.encode("utf-8")).hexdigest()
        runtime_css_sha256 = hashlib.sha256(assets.css.encode("utf-8")).hexdigest()
        runtime_js_sha256 = hashlib.sha256(assets.javascript.encode("utf-8")).hexdigest()
        sidecar_bytes = self._quality_report_bytes(
            topic_id,
            report=report,
            waiver_result=waiver_result,
            waiver_set=waiver_set,
            guide=guide,
            export_sha256=export_sha256,
            runtime_css_sha256=runtime_css_sha256,
            runtime_js_sha256=runtime_js_sha256,
            runtime_version=assets.version,
            audit_snapshot=audit_snapshot,
            trace_projection=trace_projection,
        )
        report_path = self.export_report_path(topic_id)
        _write_bytes_atomic(report_path, sidecar_bytes)

        # Build the event payload before entering the (non-reentrant) manifest
        # lock; ``_model_stage_provenance`` reads the manifest.
        model_stage_provenance = self._model_stage_provenance(topic_id)
        self._append_event_locked(
            topic_id,
            stage="export",
            action="exported",
            files={
                "export_file": export_path,
                "source_file": final_json,
                "report_file": self.final_report_path(topic_id),
                "quality_report_file": report_path,
            },
            extra={
                "guide_schema_version": guide.schema_version,
                "runtime_version": assets.version,
                "runtime_css_sha256": runtime_css_sha256,
                "runtime_js_sha256": runtime_js_sha256,
                "quality_report_sha256": hashlib.sha256(sidecar_bytes).hexdigest(),
                "model_stage_provenance": model_stage_provenance,
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
