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
    weak_stage_warning,
)
from education_pipeline.providers import get_runner
from education_pipeline.runs import SUPPORTED_STAGES, RunStore
from education_pipeline.workspace import ProfileStore, TopicStore


class NotFoundError(Exception):
    """A referenced workspace resource does not exist."""


def require_run(runs: RunStore, topic_id: str) -> None:
    """Raise :class:`NotFoundError` unless a run manifest exists for the topic."""

    if not runs.manifest_path(topic_id).is_file():
        raise NotFoundError(f"no run started for topic: {topic_id}")


def list_topics(topics: TopicStore, runs: RunStore) -> dict:
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
        entries.append({"id": topic_id, "title": title, "error": error, "run": run})
    return {"topics": entries}


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
    return {"profiles": list(profiles.list_profile_ids())}


def get_profile(profiles: ProfileStore, profile_id: str) -> dict:
    if not profiles.profile_path(profile_id).is_file():
        raise NotFoundError(f"no such profile: {profile_id}")
    return {"id": profile_id, "toml": profiles.read_profile_toml(profile_id)}


def run_status_payload(runs: RunStore, topic_id: str) -> dict:
    require_run(runs, topic_id)
    status = runs.run_status(topic_id)
    contract = runs.content_contract(topic_id)
    validations = {
        phase: _validation_summary(runs, topic_id, phase)
        for phase in ("draft", "final")
    }
    return {
        "topic_id": status.topic_id,
        "finalized": status.finalized,
        "content_contract": contract.to_manifest(),
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
        return {"state": "missing", "blocking": 0, "errors": 0, "warnings": 0}
    state = runs.report_state(topic_id, phase)
    counts = {"blocking": 0, "errors": 0, "warnings": 0}
    path = runs.draft_report_path(topic_id) if phase == "draft" else runs.final_report_path(topic_id)
    if path.is_file():
        try:
            summary = json.loads(path.read_text(encoding="utf-8")).get("summary", {})
            for key in counts:
                if isinstance(summary.get(key), int):
                    counts[key] = summary[key]
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, AttributeError):
            pass
    return {"state": state, **counts}


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
    return {"state": runs.report_state(topic_id, phase), "report": report}


def waivers_payload(runs: RunStore, topic_id: str, phase: str) -> dict:
    validation = validation_payload(runs, topic_id, phase)
    report_hash = validation["report"].get("guide_sha256")
    value = {"schema_version": 1, "guide_sha256": report_hash, "waivers": []}
    path = runs.waivers_path(topic_id)
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ConfigError(f"invalid validation waivers file: {path}") from exc
        if not isinstance(loaded, dict):
            raise ConfigError(f"invalid validation waivers file: {path}")
        value = loaded
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
    payload = plan_payload(catalog, plan, plan_sha256)
    for stage_entry in payload["stages"]:
        stage_plan = plan.stage(stage_entry["stage"])
        stage_entry["source"] = "default"  # Wave 3 adds "override"
        stage_entry["command"] = _stage_command(catalog, stage_plan, runs, topic_id)
    return payload
