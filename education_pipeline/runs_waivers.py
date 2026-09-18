"""Validation waivers for :class:`~education_pipeline.runs.RunStore`.

Split verbatim out of ``runs.py``: the hash-bound read-modify-write cycle for
a run's ``reports/validation-waivers.json``, plus the public record/remove
entry points the CLI and daemon call. :class:`WaiversMixin` holds no state of
its own -- ``RunStore`` supplies every ``self.`` collaborator used here.
"""

from __future__ import annotations

from pathlib import Path
import json

from education_pipeline.config import ConfigError
from education_pipeline.guides import (
    Waiver,
    WaiverResult,
    WaiverSet,
    apply_waivers,
)


class WaiversMixin:
    """Waiver storage and gating, mixed into :class:`RunStore`."""

    def waivers_path(self, topic_id: str) -> Path:
        return self.run_dir(topic_id) / "reports" / "validation-waivers.json"

    def load_waiver_set(self, topic_id: str) -> WaiverSet | None:
        """Load and validate this topic's on-disk waivers file, if any.

        Public so callers that need to read or rebuild the waivers file
        (e.g. the daemon's create_waiver endpoint) validate against exactly
        the same shape rules this loader enforces elsewhere — a single
        source of truth for what counts as a loadable waivers file, instead
        of a second, divergent copy of the schema checks.
        """
        return self._load_waiver_set(topic_id)

    def record_waiver(
        self, topic_id: str, phase: str, finding_id: str, reason: str
    ) -> WaiverResult:
        """Waive one finding for ``phase`` and return the resulting gate.

        Thin public wrapper around :meth:`_record_waiver`, which also
        surfaces the freshly-written :class:`WaiverSet` for callers (e.g.
        the daemon's ``create_waiver`` endpoint) that need to echo it back
        without a second, unlocked re-read.
        """

        result, _ = self._record_waiver(topic_id, phase, finding_id, reason)
        return result

    def record_waiver_with_set(
        self, topic_id: str, phase: str, finding_id: str, reason: str
    ) -> tuple[WaiverResult, WaiverSet]:
        """Waive one finding and return both the gate and the written set.

        Public form of :meth:`_record_waiver`, for callers (the daemon) that
        must render the persisted waiver set in their response. The set is the
        one built *inside* the locked critical section: a second, unlocked
        ``load_waiver_set`` afterward would be racy (a concurrent writer bound
        to a different ``guide_sha256`` could land between the two calls and
        silently drop the waiver just recorded) and would dereference an
        unchecked Optional.
        """

        return self._record_waiver(topic_id, phase, finding_id, reason)

    def _record_waiver(
        self, topic_id: str, phase: str, finding_id: str, reason: str
    ) -> tuple[WaiverResult, WaiverSet]:
        """Waive one finding for ``phase``, returning both the resulting gate
        and the ``WaiverSet`` that was just written to disk.

        Hash-bound to the current report's ``guide_sha256``: rather than
        trusting a caller-supplied hash, this recomputes the phase report
        fresh from the approved source (the same computation
        :meth:`gate_result` performs) and binds the waiver to that hash, so
        a waiver can never be recorded against stale content by accident.

        Validates the reason is non-empty and the finding both exists in
        the current report and is waivable, raising ``ConfigError``
        otherwise -- so CLI callers get a clean, typed error instead of
        silently persisting a waiver :func:`apply_waivers` would just
        reject later.

        Read-modify-write of the waivers file is a critical section: the
        daemon's ``create_waiver`` endpoint runs on a ``ThreadingHTTPServer``,
        so two concurrent requests waiving different findings on the same run
        must not race on load-mutate-write, and the write itself must not
        collide with a second writer's temp file. This uses
        :meth:`_manifest_write_lock` (per-topic serialization, shared with the
        manifest read-modify-write helpers) and :func:`_write_bytes_atomic`
        (collision-free ``mkstemp`` temp names) rather than a second,
        hand-rolled locking/temp-file scheme.

        Pre-existing waivers survive only when they were recorded against the
        same ``guide_sha256``; a stale waiver set (recorded against a
        different guide hash) is discarded rather than carried forward.

        Returning the written ``WaiverSet`` lets ``write_api.create_waiver``
        build its HTTP response from exactly what was persisted *inside*
        this critical section, instead of taking a second, unlocked
        ``load_waiver_set`` snapshot afterward -- which could race a
        concurrent writer and echo back a set that no longer contains the
        waiver this call just recorded.
        """

        artifacts = self._compute_phase_report(topic_id, phase)
        safe_id = artifacts.safe_id
        report = artifacts.report
        if not isinstance(reason, str) or not reason.strip():
            raise ConfigError("waiver reason must not be empty")
        reason = reason.strip()
        finding = next((item for item in report.findings if item.id == finding_id), None)
        if finding is None:
            raise ConfigError(f"no finding {finding_id!r} in the current {phase} report")
        if not finding.waivable:
            raise ConfigError(f"finding {finding_id!r} is not waivable")

        guide_sha256 = report.guide_sha256
        with self._manifest_write_lock(safe_id):
            items = self._current_waiver_items_locked(safe_id, guide_sha256)
            items = [item for item in items if item["finding_id"] != finding_id]
            items.append({"finding_id": finding_id, "reason": reason})
            new_set = self._write_waiver_set_locked(safe_id, guide_sha256, items)
        return apply_waivers(report, new_set), new_set

    def remove_waiver(self, topic_id: str, phase: str, finding_id: str) -> WaiverResult:
        """Remove one finding's waiver for ``phase`` and return the resulting gate.

        Symmetric with :meth:`record_waiver`: hash-bound to a fresh
        recompute of the current report, same locking discipline, same
        atomic write. Removing a waiver that was never recorded (or
        belonged to a stale hash, which is discarded rather than carried
        forward) is a no-op -- the desired end state (no waiver for this
        finding) already holds.

        Unlike :meth:`record_waiver`, this skips the write entirely when the
        resulting items are unchanged from what was read: removing an id
        that was never waived (including the common case of no waivers file
        existing at all) must not create or rewrite the waivers file. This
        matters for two reasons -- the daemon's validation poll
        (``read_api.py``) skips its expensive ``gate_result`` recompute only
        when ``load_waiver_set(...) is None``, so writing an empty file here
        would silently and permanently defeat that optimization; and an
        existing waivers file bound to a *stale* hash would otherwise be
        clobbered by an unrelated no-op removal instead of surviving on disk.
        """

        result, _ = self._remove_waiver(topic_id, phase, finding_id)
        return result

    def remove_waiver_with_set(
        self, topic_id: str, phase: str, finding_id: str
    ) -> tuple[WaiverResult, WaiverSet]:
        """Removal's counterpart to :meth:`record_waiver_with_set`.

        The returned set is the state after the write. When the last waiver is
        removed the file is unlinked and the set is empty for the current
        ``guide_sha256`` -- an absent file and an empty set are the same state
        to every reader, so the caller can build its response without a second
        (racy) read.
        """

        return self._remove_waiver(topic_id, phase, finding_id)

    def _remove_waiver(
        self, topic_id: str, phase: str, finding_id: str
    ) -> tuple[WaiverResult, WaiverSet]:
        artifacts = self._compute_phase_report(topic_id, phase)
        safe_id = artifacts.safe_id
        report = artifacts.report
        guide_sha256 = report.guide_sha256
        with self._manifest_write_lock(safe_id):
            items = self._current_waiver_items_locked(safe_id, guide_sha256)
            filtered = [item for item in items if item["finding_id"] != finding_id]
            if filtered == items:
                new_set = self._build_waiver_set(guide_sha256, items)
            elif filtered:
                new_set = self._write_waiver_set_locked(safe_id, guide_sha256, filtered)
            else:
                self.waivers_path(safe_id).unlink(missing_ok=True)
                new_set = self._build_waiver_set(guide_sha256, [])
        return apply_waivers(report, new_set), new_set

    def _current_waiver_items_locked(self, topic_id: str, guide_sha256: str) -> list[dict]:
        """Read the persisted waiver set as plain dicts, dropping it if stale.

        Caller must already hold ``_manifest_write_lock(topic_id)``. Exists
        so :meth:`record_waiver` and :meth:`remove_waiver` share one
        read-side of the read-modify-write cycle instead of two divergent
        copies.
        """

        existing_set = self._load_waiver_set(topic_id)
        if existing_set is None or existing_set.guide_sha256 != guide_sha256:
            return []
        return [{"finding_id": w.finding_id, "reason": w.reason} for w in existing_set.waivers]

    def _build_waiver_set(self, guide_sha256: str, items: list[dict]) -> WaiverSet:
        """Build the in-memory :class:`WaiverSet` for ``items`` without any I/O.

        Pure factoring shared by :meth:`_write_waiver_set_locked` (which
        also persists the result) and :meth:`remove_waiver`'s no-op path
        (which must return an equivalent ``WaiverSet`` without touching
        disk) -- one canonical shape instead of two divergent copies.
        """

        items = sorted(items, key=lambda item: item["finding_id"])
        return WaiverSet(
            guide_sha256=guide_sha256,
            waivers=tuple(
                Waiver(finding_id=item["finding_id"], reason=item["reason"]) for item in items
            ),
            schema_version=1,
        )

    def _write_waiver_set_locked(
        self, topic_id: str, guide_sha256: str, items: list[dict]
    ) -> WaiverSet:
        """Atomically write ``items`` as this topic's waivers file.

        Caller must already hold ``_manifest_write_lock(topic_id)``. Exists
        so :meth:`record_waiver` and :meth:`remove_waiver` share one
        write-side of the read-modify-write cycle instead of two divergent
        copies.
        """

        from education_pipeline.runs import _write_bytes_atomic

        new_set = self._build_waiver_set(guide_sha256, items)
        path = self.waivers_path(topic_id)
        value = {
            "schema_version": new_set.schema_version,
            "guide_sha256": new_set.guide_sha256,
            "waivers": [
                {"finding_id": w.finding_id, "reason": w.reason} for w in new_set.waivers
            ],
        }
        _write_bytes_atomic(
            path, (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")
        )
        return new_set

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
