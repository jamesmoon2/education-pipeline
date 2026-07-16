"""Read-only JSON payload builders for the cockpit /v1 API.

Pure functions: stores in, JSON-serializable dicts out. Raise
:class:`NotFoundError` for missing resources (HTTP 404) and let
``ConfigError`` propagate for invalid input (HTTP 400).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from education_pipeline.config import (
    STAGE_ORDER,
    ConfigError,
    ModelCatalog,
    ModelOption,
    ModelPlan,
    apply_overrides_lenient,
    weak_stage_warning,
)
from education_pipeline.providers import get_runner
from education_pipeline.privacy import (
    profile_field_sensitivity,
    profile_summary_warnings,
    profile_to_dict,
)
from education_pipeline.profiles import (
    parse_learner_profile,
    render_profile_prompt_context,
    render_profile_public_summary,
)
from education_pipeline.export import EXPORT_FORMATS
from education_pipeline.runs import REQUIRED_STAGES, SUPPORTED_STAGES, RunStore
from education_pipeline.workspace import ProfileRecord, ProfileStore, TopicStore


class NotFoundError(Exception):
    """A referenced workspace resource does not exist."""


def require_run(runs: RunStore, topic_id: str) -> None:
    """Raise :class:`NotFoundError` unless a run manifest exists for the topic."""

    if not runs.manifest_path(topic_id).is_file():
        raise NotFoundError(f"no run started for topic: {topic_id}")


def list_topics(topics: TopicStore, runs: RunStore, profiles: ProfileStore) -> dict:
    """The course-library payload, enriched server-side (spec §5.1).

    Adds ``last_activity`` (ISO-8601 mtime of the newest run artifact),
    ``archived`` (manifest flag; no run means ``false``), ``profile_id``
    (attached snapshot's embedded id), and ``completion`` so the cockpit
    stays presentation-only.
    """

    entries = []
    for topic_id in topics.list_topic_ids():
        title: str | None = None
        error: str | None = None
        try:
            title = topics.load_topic(topic_id).title
        except ConfigError as exc:
            error = str(exc)
        run = (
            run_status_payload(runs, topic_id)
            if runs.manifest_path(topic_id).is_file()
            else None
        )
        entries.append(
            {
                "id": topic_id,
                "title": title,
                "error": error,
                "run": run,
                "archived": runs.is_archived(topic_id) if run else False,
                "last_activity": runs.last_activity_at(topic_id) if run else None,
                "profile_id": _attached_profile_id(profiles, topic_id),
                "completion": _completion_summary(runs, topic_id, run),
            }
        )
    return {"topics": entries}


def _attached_profile_id(profiles: ProfileStore, topic_id: str) -> str | None:
    if not profiles.topic_profile_snapshot_path(topic_id).is_file():
        return None
    try:
        return profiles.load_topic_profile_snapshot(topic_id).id
    except ConfigError:
        return None  # unreadable snapshot; the run board surfaces the detail


def _completion_summary(runs: RunStore, topic_id: str, run: dict | None) -> dict | None:
    if run is None:
        return None
    approved = sum(
        1
        for stage in run["stages"]
        if stage["stage"] in REQUIRED_STAGES and stage["approved"]
    )
    exported = any(
        runs.export_path(topic_id, format).is_file() for format in EXPORT_FORMATS
    )
    return {
        "stages_approved": approved,
        "stages_total": len(REQUIRED_STAGES),
        "exported": exported,
    }


def workspace_payload(
    root: Path, topics: TopicStore, runs: RunStore, profiles: ProfileStore
) -> dict:
    """Read-only workspace summary powering the welcome panel (spec §4.1)."""

    run_count = len(runs.list_run_ids())
    return {
        "path": str(root),
        "counts": {
            "topics": len(topics.list_topic_ids()),
            "runs": run_count,
            "profiles": len(profiles.list_profile_ids()),
        },
        "first_run": run_count == 0,
    }


def get_topic(topics: TopicStore, topic_id: str) -> dict:
    if not topics.topic_path(topic_id).is_file():
        raise NotFoundError(f"no such topic: {topic_id}")
    title: str | None = None
    try:
        title = topics.load_topic(topic_id).title
    except ConfigError:
        pass  # surface the raw TOML even if it no longer parses
    return {"id": topic_id, "title": title, "toml": topics.read_topic_toml(topic_id)}


def list_profiles(profiles: ProfileStore) -> dict:
    return {
        "profiles": [
            {
                "id": profile_id,
                "attached_topic_count": profiles.profile_attachment_count(profile_id),
            }
            for profile_id in profiles.list_profile_ids()
        ]
    }


def get_profile(profiles: ProfileStore, profile_id: str) -> dict:
    if not profiles.profile_path(profile_id).is_file():
        raise NotFoundError("no such profile")
    return profile_payload(
        profiles,
        profile_id,
        record=profiles.read_profile_record(profile_id),
    )


def profile_payload(
    profiles: ProfileStore,
    profile_id: str,
    *,
    record: ProfileRecord,
) -> dict:
    """Project one canonical store record to the frozen structured API shape."""

    return {
        "id": profile_id,
        "parsed": profile_to_dict(record.profile),
        "sensitivity": _profile_sensitivity_payload(),
        "content_sha256": record.content_sha256,
        "warnings": _profile_warnings_payload(record.profile),
        "attached_topic_count": profiles.profile_attachment_count(profile_id),
    }


def preview_profile(value: object) -> dict:
    """Render a structured profile without consulting or mutating the store."""

    profile = parse_learner_profile(value)
    return {
        "parsed": profile_to_dict(profile),
        "prompt_context": render_profile_prompt_context(profile),
        "publishable_summary": render_profile_public_summary(profile),
        "sensitivity": _profile_sensitivity_payload(),
        "warnings": _profile_warnings_payload(profile),
    }


def _profile_sensitivity_payload() -> dict:
    return {
        field_path: tier.value
        for field_path, tier in profile_field_sensitivity().items()
    }


def _profile_warnings_payload(profile) -> list[dict]:
    return [
        {
            "code": warning.code,
            "field_path": warning.field_path,
            "fingerprint": warning.fingerprint,
        }
        for warning in profile_summary_warnings(profile)
    ]


def blueprints_payload(
    topics: TopicStore, topic_id: str | None = None
) -> dict:
    """List the registered blueprints, plus a per-topic recommendation.

    With ``topic_id`` naming a stored topic, ``recommendation`` carries the
    deterministic recommendation and rationale and ``topic_blueprint`` the
    topic's own declared blueprint (when set). Without it both are ``None``.
    """

    from education_pipeline.guides.blueprints import (
        list_blueprints,
        recommend_blueprint,
    )

    recommendation = None
    topic_blueprint = None
    if topic_id is not None:
        if not topics.topic_path(topic_id).is_file():
            raise NotFoundError("no such topic")
        topic = topics.load_topic(topic_id)
        blueprint_id, rationale = recommend_blueprint(topic)
        recommendation = {"id": blueprint_id, "rationale": rationale}
        topic_blueprint = topic.blueprint
    return {
        "blueprints": [
            {
                "id": blueprint.id,
                "title": blueprint.title,
                "summary": blueprint.summary,
                "when_to_use": blueprint.when_to_use,
                "required_interactions": sorted(blueprint.required_interactions),
                "default_difficulty": blueprint.default_difficulty,
            }
            for blueprint in list_blueprints()
        ],
        "recommendation": recommendation,
        "topic_blueprint": topic_blueprint,
    }


def run_status_payload(runs: RunStore, topic_id: str) -> dict:
    require_run(runs, topic_id)
    status = runs.run_status(topic_id)
    contract = runs.content_contract(topic_id)
    manifest = runs.read_manifest(topic_id)
    validations = {
        phase: _validation_summary(runs, topic_id, phase)
        for phase in ("draft", "final")
    }
    return {
        "topic_id": status.topic_id,
        "finalized": status.finalized,
        "content_contract": contract.to_manifest(),
        "blueprint": runs.blueprint_config(topic_id),
        "stage_provenance": manifest.get("stage_provenance", []),
        "validations": validations,
        "stages": [
            {
                "stage": s.stage,
                "state": s.state,
                "prompt_written": s.prompt_written,
                "response_ingested": s.response_ingested,
                "approved": s.approved,
            }
            for s in status.stages
        ],
        "next_action": {
            "topic_id": status.next_action.topic_id,
            "stage": status.next_action.stage,
            "action": status.next_action.action,
            "detail": status.next_action.detail,
        },
    }


def list_runs(runs: RunStore) -> dict:
    return {"runs": list(runs.list_run_ids())}


def personalization_payload(runs: RunStore, topic_id: str) -> dict:
    """Return the one authenticated local cockpit personalization aggregate.

    Private profile goals and exclusions are intentionally available to the
    local cockpit. Model-authored audit narratives and artifact locations are
    not: audit presentation is sourced only from the strict safe projection
    captured by :meth:`RunStore.personalization_snapshot`.
    """

    require_run(runs, topic_id)
    try:
        snapshot = runs.personalization_snapshot(topic_id)
    except ConfigError:
        raise ConfigError("personalization state is unavailable") from None
    profile = snapshot.profile
    trace = snapshot.trace
    trace_state = snapshot.trace_state
    goals: list[dict] = []
    facets: list[str] = []
    if trace is not None and trace_state == "current":
        facets = list(trace.active_facets)
        for goal in trace.goals:
            evidence = [
                {"kind": "module", "id": element_id}
                for element_id in goal.serving_module_ids
            ] + [
                {"kind": "outcome", "id": element_id}
                for element_id in goal.serving_outcome_ids
            ]
            goals.append(
                {
                    "goal_id": goal.goal_id,
                    "goal_text": goal.goal_text,
                    "status": (
                        "served"
                        if evidence
                        else "excluded"
                        if goal.exclusions
                        else "missing"
                    ),
                    "evidence": evidence,
                    "exclusions": [
                        {"reason": exclusion.reason}
                        for exclusion in goal.exclusions
                    ],
                }
            )

    audit_findings = [
        finding.to_dict()
        for finding in snapshot.audit_findings
        if finding.stage == "audit"
    ]
    findings = [
        finding.to_dict()
        for finding in snapshot.findings
        if finding.rule_id.startswith("personalization.")
        or finding.stage == "audit"
    ]

    available = False
    unavailable_reason: str | None
    if profile is None:
        unavailable_reason = "No learner profile is attached."
    elif snapshot.final_report_state != "current":
        unavailable_reason = "Final validation is not current."
    elif trace_state != "current":
        unavailable_reason = "The personalization trace is not current."
    else:
        available = True
        unavailable_reason = None

    return {
        "topic_id": topic_id,
        "profile": {
            "state": "attached" if profile is not None else "not_attached",
            "id": profile.id if profile is not None else None,
        },
        "trace": {"state": trace_state, "goals": goals, "facets": facets},
        "audit": {
            "state": snapshot.audit_state,
            "stage_state": snapshot.audit_stage_state,
            "available": available,
            "unavailable_reason": unavailable_reason,
            "findings": audit_findings,
        },
        "findings": findings,
        "export": {"state": snapshot.export_state},
    }


def stage_content(runs: RunStore, topic_id: str, stage: str) -> dict:
    require_run(runs, topic_id)
    paths = runs.stage_paths(topic_id, stage)  # ConfigError on bad stage -> 400

    def _read(path):
        return path.read_text(encoding="utf-8") if path.is_file() else None

    response_sha256 = (
        hashlib.sha256(paths.response_path.read_bytes()).hexdigest()
        if paths.response_path.is_file()
        else None
    )
    return {
        "topic_id": paths.topic_id,
        "stage": paths.stage,
        "prompt": _read(paths.prompt_path),
        "response": _read(paths.response_path),
        "approved": _read(paths.approved_path),
        "response_sha256": response_sha256,
        "content_type": paths.content_type,
    }


def _validation_summary(runs: RunStore, topic_id: str, phase: str) -> dict:
    if runs.content_contract(topic_id).kind != "interactive_guide":
        result = {
            "state": "missing",
            "blocking": 0,
            "errors": 0,
            "warnings": 0,
            "findings_by_stage": {},
            "effective_blocking": 0,
        }
        if phase == "final":
            result["audit"] = {"state": "not_run", "finding_count": 0}
        return result
    state = runs.report_state(topic_id, phase)
    counts = {"blocking": 0, "errors": 0, "warnings": 0}
    by_stage: dict[str, int] = {}
    waived_ids: set[str] = set()
    path = runs.draft_report_path(topic_id) if phase == "draft" else runs.final_report_path(topic_id)
    report: dict | None = None
    if path.is_file():
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
            summary = report.get("summary", {})
            for key in counts:
                if isinstance(summary.get(key), int):
                    counts[key] = summary[key]
            for finding in report.get("findings", []):
                if finding.get("blocking") or finding.get("severity") == "error":
                    stage = finding.get("stage", "draft")
                    by_stage[stage] = by_stage.get(stage, 0) + 1
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, AttributeError):
            report = None

    # Waivers are hash-bound (apply_waivers, guides/waivers.py): a waiver set
    # recorded against different content is dropped, so a recomputed gate on
    # changed content closes automatically. effective_blocking inherits that
    # fail-safe for free -- no extra staleness logic needed here.
    #
    # gate_result recomputes the report from the approved source, while
    # counts/by_stage above come from the report *file on disk*. Pairing a
    # stale on-disk body with a fresh recomputed gate would make this summary
    # disagree with itself -- the exact trap Task 3.1's review caught in the
    # CLI's _cmd_report. Only trust a recomputed effective_blocking when the
    # on-disk report is confirmed "current"; otherwise leave it equal to the
    # raw blocking count and let the stale banner + re-run button do their
    # job.
    #
    # gate_result's recompute is a full parse + normalize + static-checks
    # pass (plus, for final, a runtime render and a11y pass) -- expensive
    # enough that paying for it on every 5s cockpit poll matters for large
    # guides. Skip it entirely when the topic has no waiver set: with
    # waiver_set=None, apply_waivers always returns
    # effective_blocking == len(blocking findings), which for a "current"
    # report is exactly counts["blocking"] already computed above -- so the
    # short-circuit is semantically a no-op for the overwhelmingly common
    # no-waivers case.
    effective_blocking = counts["blocking"]
    if state == "current":
        try:
            gate = (
                runs.gate_result(topic_id, phase)
                if runs.load_waiver_set(topic_id) is not None
                else None
            )
        except ConfigError:
            gate = None
        if gate is not None and not gate.stale:
            effective_blocking = gate.effective_blocking
            waived_ids = set(gate.waived_finding_ids)

    if waived_ids and by_stage and report is not None:
        for finding in report.get("findings", []):
            if finding.get("id") not in waived_ids:
                continue
            if not (finding.get("blocking") or finding.get("severity") == "error"):
                continue
            stage = finding.get("stage", "draft")
            if by_stage.get(stage):
                by_stage[stage] -= 1
                if by_stage[stage] <= 0:
                    del by_stage[stage]

    result = {
        "state": state,
        **counts,
        "findings_by_stage": by_stage,
        "effective_blocking": effective_blocking,
    }
    if phase == "final":
        result["audit"] = audit_summary(runs, topic_id)
    return result


def audit_summary(runs: RunStore, topic_id: str) -> dict:
    """Return only public-safe audit state and its additive finding count."""

    state = runs.audit_state(topic_id)
    finding_count = 0
    if state == "current":
        finding_count = sum(
            finding.stage == "audit" for finding in runs.combined_findings(topic_id)
        )
    return {"state": state, "finding_count": finding_count}


def validation_payload(runs: RunStore, topic_id: str, phase: str) -> dict:
    require_run(runs, topic_id)
    if phase not in {"draft", "final"}:
        raise ConfigError("phase must be 'draft' or 'final'")
    if runs.content_contract(topic_id).kind != "interactive_guide":
        raise NotFoundError(f"run {topic_id!r} has no guide validation reports")
    path = runs.draft_report_path(topic_id) if phase == "draft" else runs.final_report_path(topic_id)
    if not path.is_file():
        raise NotFoundError(f"no {phase} validation report for topic {topic_id!r}")
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConfigError(f"invalid validation report: {path}") from exc
    if not isinstance(report, dict):
        raise ConfigError(f"invalid validation report: {path}")
    if phase == "final":
        # Presentation surfaces consume the shared combined accessor. The
        # deterministic report on disk remains audit-free and continues to
        # own all blocker, waiver, and gate semantics.
        report = dict(report)
        report["findings"] = [
            finding.to_dict() for finding in runs.combined_findings(topic_id)
        ]
    return {"state": runs.report_state(topic_id, phase), "report": report}


def waivers_payload(runs: RunStore, topic_id: str, phase: str) -> dict:
    # Route through RunStore.load_waiver_set -- the single source of truth
    # for the waivers-file schema -- instead of re-parsing the raw JSON here.
    # A second, weaker shape check (root-is-a-dict only) previously let this
    # route echo a corrupt file back verbatim with "state": "current" while
    # the write route and the loader itself both raised ConfigError for the
    # very same file. All three surfaces must now agree.
    validation = validation_payload(runs, topic_id, phase)
    report_hash = validation["report"].get("guide_sha256")
    waiver_set = runs.load_waiver_set(topic_id)
    if waiver_set is None:
        value = {"schema_version": 1, "guide_sha256": report_hash, "waivers": []}
    else:
        value = {
            "schema_version": waiver_set.schema_version,
            "guide_sha256": waiver_set.guide_sha256,
            "waivers": [
                {"finding_id": w.finding_id, "reason": w.reason} for w in waiver_set.waivers
            ],
        }
    state = validation["state"]
    if value.get("guide_sha256") != report_hash:
        state = "stale"
    return {"state": state, "waivers": value}


def manifest_payload(runs: RunStore, topic_id: str) -> dict:
    if not runs.manifest_path(topic_id).is_file():
        raise NotFoundError(f"no run manifest for topic: {topic_id}")
    return runs.read_manifest(topic_id)


def final_download_path(runs: RunStore, topic_id: str) -> Path:
    path = (
        runs.final_guide_json_path(topic_id)
        if runs.content_contract(topic_id).kind == "interactive_guide"
        else runs.final_path(topic_id)
    )
    if not path.is_file():
        raise NotFoundError(f"run {topic_id!r} is not finalized")
    return path


def export_download_path(runs: RunStore, topic_id: str, format: str) -> Path:
    path = runs.export_path(topic_id, format)  # ConfigError on bad format -> 400
    if not path.is_file():
        raise NotFoundError(f"no {format} export produced for topic {topic_id!r}")
    return path


def providers_payload(catalog: ModelCatalog) -> dict:
    providers = []
    for provider in catalog.providers.values():
        available = False
        reason: str | None = None
        executable = False
        try:
            runner = get_runner(provider.id)
        except ConfigError:
            reason = f"no runner registered for {provider.id!r}"
        else:
            executable = runner.executable
            if runner.is_available():
                available = True
            else:
                reason = f"{provider.id} CLI not found on PATH"
        providers.append(
            {
                "id": provider.id,
                "label": provider.label,
                "description": provider.description,
                "executable": executable,
                "available": available,
                "reason": reason,
            }
        )
    return {"providers": providers}


def catalog_payload(catalog: ModelCatalog) -> dict:
    providers = []
    for provider in catalog.providers.values():
        providers.append(
            {
                "id": provider.id,
                "label": provider.label,
                "description": provider.description,
                "models": [
                    {
                        "id": model.id,
                        "label": model.label,
                        "description": model.description,
                        "quality": model.quality,
                        "default_effort": model.default_effort,
                    }
                    for model in provider.models.values()
                ],
            }
        )
    return {"providers": providers}


def plan_payload(catalog: ModelCatalog, plan: ModelPlan, plan_sha256: str) -> dict:
    stages = []
    for stage_name in STAGE_ORDER:
        stage_plan = plan.stage(stage_name)
        stages.append(
            {
                "stage": stage_plan.stage,
                "provider": stage_plan.provider,
                "model": stage_plan.model,
                "effort": stage_plan.effort,
                "recommendation": stage_plan.recommendation,
                "warning": weak_stage_warning(catalog, stage_plan),
            }
        )
    return {
        "provider": plan.provider,
        "plan_sha256": plan_sha256,
        "stages": stages,
    }


def _stage_command(
    catalog: ModelCatalog, stage_plan, runs: RunStore, topic_id: str
) -> list[str] | None:
    """The argv the daemon would spawn for this stage, or None if unresolvable.

    Unresolvable covers: manual/unset provider, a stage the run engine doesn't
    drive through a model, an unregistered provider, a non-executable runner,
    and an unknown model id — none of these are errors, they just mean there's
    nothing to preview yet.
    """

    provider_id = stage_plan.provider
    if provider_id in (None, "manual") or stage_plan.stage not in SUPPORTED_STAGES:
        return None
    try:
        runner = get_runner(provider_id)
        if not runner.executable:
            return None
        provider = catalog.require_provider(provider_id)
        if stage_plan.model is not None:
            model = provider.models.get(stage_plan.model)
            if model is None:
                return None
        else:
            model = ModelOption(id="", label="")
        prompt_path = runs.stage_paths(topic_id, stage_plan.stage).prompt_path
        return list(runner.build_invocation(model, stage_plan, prompt_path).argv)
    except ConfigError:
        return None


def run_plan_payload(
    catalog: ModelCatalog, plan: ModelPlan, plan_sha256: str, runs: RunStore, topic_id: str
) -> dict:
    """The effective plan for one run, plus per-stage source + command preview."""

    require_run(runs, topic_id)
    overrides = runs.read_plan_overrides(topic_id)
    override_stage_names = set(overrides.get("stages", {}) or {})
    effective, errors = apply_overrides_lenient(plan, overrides, catalog)
    payload = plan_payload(catalog, effective, plan_sha256)
    for stage_entry in payload["stages"]:
        stage_name = stage_entry["stage"]
        stage_plan = effective.stage(stage_name)
        is_override = stage_name in override_stage_names
        stage_entry["source"] = "override" if is_override else "default"
        if is_override and stage_name in errors:
            stage_entry["override_error"] = (
                f"stored override is invalid: {errors[stage_name]} "
                "-- reset this stage to clear it."
            )
        if stage_entry.get("override_error"):
            # The command preview would be computed from the fallback plan,
            # which looks runnable but isn't -- enqueue of this stage 400s.
            stage_entry["command"] = None
        else:
            stage_entry["command"] = _stage_command(catalog, stage_plan, runs, topic_id)
    return payload
