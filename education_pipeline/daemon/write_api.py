"""Write-action payload builders for the cockpit /v1 API.

Pure functions mirroring ``read_api``: stores in, JSON-serializable dicts out.
Each function pre-checks state on the same paths the store checks so refusals
carry a precise conflict code; the store call remains the authority and its
``ConfigError`` remains the backstop. Raises:

- :class:`read_api.NotFoundError` -> HTTP 404
- :class:`ConflictError` -> HTTP 409 (codes: ``already_exists``, ``not_ready``,
  ``job_active``, ``stale_content``)
- ``ConfigError`` propagates -> HTTP 400
"""

from __future__ import annotations

import hashlib
import tomllib
from pathlib import Path

from education_pipeline.config import (
    ConfigError,
    apply_overrides_lenient,
    emit_model_plan_toml,
    parse_model_plan,
)
from education_pipeline.daemon import read_api
from education_pipeline.daemon.jobs import JobStore
from education_pipeline.daemon.read_api import NotFoundError
from education_pipeline.runs import RunStore, StaleContentError
from education_pipeline.topics import Topic, emit_topic_toml
from education_pipeline.workspace import ProfileStore, TopicStore


class ConflictError(Exception):
    """The request is well-formed but current run/workspace state refuses it."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class UnprocessableError(Exception):
    """Safe input that cannot be accepted under the guide contract."""

    def __init__(self, code: str, message: str, details: dict | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.details = details


def _run_relative(runs: RunStore, topic_id: str, path: Path) -> str:
    return path.relative_to(runs.run_dir(topic_id)).as_posix()


def _require_no_active_job(jobs: JobStore, topic_id: str) -> None:
    job = jobs.any_active_for(topic_id)
    if job is not None:
        raise ConflictError(
            "job_active",
            f"job {job.id} is {job.status} for topic {topic_id!r}; "
            "wait for it to finish or cancel it first",
        )


def advance_run(runs: RunStore, jobs: JobStore, topic_id: str) -> dict:
    _require_no_active_job(jobs, topic_id)
    result = runs.advance(topic_id)
    return {
        "performed": result.performed,
        "status": read_api.run_status_payload(runs, result.topic_id),
    }


def validate_run(runs: RunStore, jobs: JobStore, topic_id: str, phase: str) -> dict:
    read_api.require_run(runs, topic_id)
    if phase not in {"draft", "final"}:
        raise ConfigError("phase must be 'draft' or 'final'")
    stage = "draft" if phase == "draft" else "repair"
    job = jobs.active_for(topic_id, stage)
    if job is not None:
        raise ConflictError(
            "job_active", f"job {job.id} is {job.status} for {topic_id}/{stage}"
        )
    runs.validate_run(topic_id, phase)
    return {
        **read_api.validation_payload(runs, topic_id, phase),
        "status": read_api.run_status_payload(runs, topic_id),
    }


def create_waiver(
    runs: RunStore,
    topic_id: str,
    phase: str,
    finding_id: str,
    guide_sha256: str,
    reason: str,
) -> dict:
    payload = read_api.validation_payload(runs, topic_id, phase)
    if payload["state"] != "current":
        raise ConflictError("stale_validation", "validation report or guide input is stale")
    report = payload["report"]
    if report.get("guide_sha256") != guide_sha256:
        raise ConflictError("stale_validation", "guide hash does not match the current report")
    if not isinstance(reason, str) or not reason.strip():
        raise ConfigError("waiver reason must not be empty")
    finding = next(
        (item for item in report.get("findings", []) if item.get("id") == finding_id),
        None,
    )
    if finding is None:
        raise NotFoundError(f"no finding {finding_id!r} in the current {phase} report")
    if not finding.get("waivable"):
        raise UnprocessableError("finding_not_waivable", f"finding {finding_id!r} is not waivable")

    # Delegate the read-modify-write to RunStore.record_waiver rather than
    # hand-rolling a second locking/temp-file scheme here: on a
    # ThreadingHTTPServer, two concurrent POSTs to this endpoint for the same
    # run raced on an unserialized load-mutate-write with a shared hardcoded
    # temp filename, producing both lost updates and FileNotFoundError from a
    # colliding ``.tmp`` rename. ``record_waiver`` uses RunStore's per-topic
    # ``_manifest_lock`` (serialization) and ``_write_bytes_atomic``
    # (collision-free ``mkstemp`` temp names) -- the same tools that already
    # protect manifest read-modify-write cycles -- so this is a single,
    # reused critical section rather than a divergent one. It also reuses
    # ``load_waiver_set`` internally, so the schema-validation guarantee
    # described below still holds: a malformed persisted waivers file is
    # never silently propagated into the new file.
    waiver_set = runs.record_waiver(topic_id, guide_sha256, finding_id, reason.strip())
    value = {
        "schema_version": waiver_set.schema_version,
        "guide_sha256": waiver_set.guide_sha256,
        "waivers": [
            {"finding_id": w.finding_id, "reason": w.reason} for w in waiver_set.waivers
        ],
    }
    return {"waivers": value, **read_api.validation_payload(runs, topic_id, phase)}


def ingest_response(
    runs: RunStore,
    jobs: JobStore,
    topic_id: str,
    stage: str,
    text: str,
    *,
    force: bool = False,
) -> dict:
    read_api.require_run(runs, topic_id)
    _require_no_active_job(jobs, topic_id)
    paths = runs.stage_paths(topic_id, stage)
    if paths.response_path.exists() and not force:
        raise ConflictError(
            "already_exists",
            f"response already ingested for stage {paths.stage!r}; "
            "retry with force to replace it",
        )
    path = runs.ingest_response(topic_id, stage, text, force=force)
    runs.record_stage_provenance(
        topic_id, stage, provider="manual", model=None, effort=None, source="manual"
    )
    return {
        "topic_id": paths.topic_id,
        "stage": paths.stage,
        "response_path": _run_relative(runs, topic_id, path),
        "status": read_api.run_status_payload(runs, topic_id),
    }


def edit_response(
    runs: RunStore,
    jobs: JobStore,
    topic_id: str,
    stage: str,
    text: str,
    *,
    base_sha256: str,
) -> dict:
    read_api.require_run(runs, topic_id)
    _require_no_active_job(jobs, topic_id)
    paths = runs.stage_paths(topic_id, stage)
    if not paths.response_path.exists():
        raise ConflictError(
            "stale_content",
            f"the {paths.stage} response no longer exists on disk; "
            "reload the current stage content",
        )
    try:
        path = runs.edit_response(topic_id, stage, text, base_sha256=base_sha256)
    except StaleContentError as exc:
        raise ConflictError("stale_content", str(exc)) from exc
    return {
        "topic_id": paths.topic_id,
        "stage": paths.stage,
        "response_path": _run_relative(runs, topic_id, path),
        "response_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def approve_stage(
    runs: RunStore,
    jobs: JobStore,
    topic_id: str,
    stage: str,
    *,
    overwrite: bool = False,
) -> dict:
    read_api.require_run(runs, topic_id)
    _require_no_active_job(jobs, topic_id)
    paths = runs.stage_paths(topic_id, stage)
    if not paths.response_path.exists():
        raise ConflictError(
            "not_ready",
            f"no ingested response to approve for stage {paths.stage!r}; save a response first",
        )
    if paths.approved_path.exists() and not overwrite:
        raise ConflictError(
            "already_exists",
            f"stage {paths.stage!r} is already approved; retry with overwrite to replace it",
        )
    path = runs.approve_stage(topic_id, stage, overwrite=overwrite)
    return {
        "topic_id": paths.topic_id,
        "stage": paths.stage,
        "approved_path": _run_relative(runs, topic_id, path),
        "status": read_api.run_status_payload(runs, topic_id),
    }


def finalize_run(
    runs: RunStore, jobs: JobStore, topic_id: str, *, overwrite: bool = False
) -> dict:
    read_api.require_run(runs, topic_id)
    _require_no_active_job(jobs, topic_id)
    if not runs.stage_paths(topic_id, "repair").approved_path.exists():
        raise ConflictError(
            "not_ready", "the repair stage is not approved; approve it before finalizing"
        )
    if runs.final_path(topic_id).exists() and not overwrite:
        raise ConflictError(
            "already_exists",
            "run is already finalized; retry with overwrite to rebuild the final guide",
        )
    path = runs.finalize_run(topic_id, overwrite=overwrite)
    return {
        "topic_id": topic_id,
        "final_path": _run_relative(runs, topic_id, path),
        "status": read_api.run_status_payload(runs, topic_id),
    }


def export_run(
    runs: RunStore, topic_id: str, *, format: str = "html", overwrite: bool = False
) -> dict:
    # Deliberately no job guard: export only reads final/ and writes a new
    # file the worker never touches.
    read_api.require_run(runs, topic_id)
    export_path = runs.export_path(topic_id, format)  # ConfigError on bad format -> 400
    if not runs.is_finalized(topic_id):
        raise ConflictError("not_ready", "run is not finalized; finalize before exporting")
    if export_path.exists() and not overwrite:
        raise ConflictError(
            "already_exists",
            f"{format} export already exists; retry with overwrite to replace it",
        )
    path = runs.export_run(topic_id, format=format, overwrite=overwrite)
    return {
        "topic_id": topic_id,
        "format": format,
        "export_path": _run_relative(runs, topic_id, path),
    }


def _parse_toml_id(toml_text: str, kind: str) -> str:
    try:
        data = tomllib.loads(toml_text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"invalid TOML in {kind} import: {exc}") from exc
    artifact_id = data.get("id")
    if not isinstance(artifact_id, str) or not artifact_id:
        raise ConfigError(f"{kind} TOML must define a string 'id'")
    return artifact_id


def import_topic(topics: TopicStore, toml_text: str, *, overwrite: bool = False) -> dict:
    topic_id = _parse_toml_id(toml_text, "topic")
    if topics.topic_path(topic_id).is_file() and not overwrite:
        raise ConflictError(
            "already_exists",
            f"topic {topic_id!r} already exists; retry with overwrite to replace it",
        )
    topic = topics.save_topic_toml(topic_id, toml_text, overwrite=overwrite)
    return {"id": topic.id, "title": topic.title}


def _require_body_string(body: dict, key: str) -> str:
    value = body.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"body must define non-empty string {key!r}")
    return value


def _optional_body_string(body: dict, key: str) -> str | None:
    if key not in body:
        return None
    value = body[key]
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"body field {key!r} must be a non-empty string when set")
    return value


def _optional_body_string_tuple(body: dict, key: str) -> tuple[str, ...]:
    if key not in body:
        return ()
    value = body[key]
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ConfigError(f"body field {key!r} must be a list of strings")
    strings: list[str] = []
    for index, item in enumerate(value, start=1):
        if not isinstance(item, str) or not item.strip():
            raise ConfigError(f"body field {key!r} item #{index} must be a non-empty string")
        strings.append(item)
    return tuple(strings)


def create_topic(topics: TopicStore, body: dict, *, overwrite: bool = False) -> dict:
    topic_id = _require_body_string(body, "id")
    title = _require_body_string(body, "title")
    topic = Topic(
        id=topic_id,
        title=title,
        brief=_optional_body_string(body, "brief"),
        audience=_optional_body_string(body, "audience"),
        goals=_optional_body_string_tuple(body, "goals"),
        scope_includes=_optional_body_string_tuple(body, "scope_includes"),
        scope_excludes=_optional_body_string_tuple(body, "scope_excludes"),
        key_questions=_optional_body_string_tuple(body, "key_questions"),
        prerequisites=_optional_body_string_tuple(body, "prerequisites"),
        constraints=_optional_body_string_tuple(body, "constraints"),
        tags=_optional_body_string_tuple(body, "tags"),
        notes=_optional_body_string(body, "notes"),
    )
    if topics.topic_path(topic_id).is_file() and not overwrite:
        raise ConflictError(
            "already_exists",
            f"topic {topic_id!r} already exists; retry with overwrite to replace it",
        )
    saved = topics.save_topic_toml(topic_id, emit_topic_toml(topic), overwrite=overwrite)
    return {"id": saved.id, "title": saved.title}


def import_profile(profiles: ProfileStore, toml_text: str, *, overwrite: bool = False) -> dict:
    profile_id = _parse_toml_id(toml_text, "profile")
    if profiles.profile_path(profile_id).is_file() and not overwrite:
        raise ConflictError(
            "already_exists",
            f"profile {profile_id!r} already exists; retry with overwrite to replace it",
        )
    profile = profiles.save_profile_toml(profile_id, toml_text, overwrite=overwrite)
    return {"id": profile.id}


def update_global_plan(config, body: dict) -> dict:
    base_sha256 = body.get("base_sha256")
    if not isinstance(base_sha256, str):
        raise ConfigError("body field 'base_sha256' must be a string")
    if base_sha256 != config.plan_sha256():
        raise ConflictError(
            "stale_content", "the model plan changed on disk; reload settings"
        )
    catalog, _ = config.load()
    plan = parse_model_plan(
        {"provider": body.get("provider"), "stages": body.get("stages", {})},
        catalog=catalog,
        # Strict at write, lenient on disk (owner's decision): reject an
        # unknown/misspelled stage key here rather than silently discarding
        # it, without tightening load_model_plan's disk loader.
        strict_keys=True,
    )
    config.write_plan(emit_model_plan_toml(plan))
    return read_api.plan_payload(catalog, plan, config.plan_sha256())


def update_run_plan(runs: RunStore, config, topic_id: str, body: dict) -> dict:
    read_api.require_run(runs, topic_id)
    overrides_body = body.get("overrides")
    if not isinstance(overrides_body, dict):
        raise ConfigError("body field 'overrides' must be a table")

    catalog, plan = config.load()
    stored = runs.read_plan_overrides(topic_id)
    stored_stages = stored.get("stages", {})
    if not isinstance(stored_stages, dict):
        stored_stages = {}
    merged_stages = dict(stored_stages)
    for stage_name, stage_override in overrides_body.items():
        if stage_override is None:
            merged_stages.pop(stage_name, None)
        elif isinstance(stage_override, dict):
            merged_stages[stage_name] = stage_override
        else:
            raise ConfigError(
                f"override for stage {stage_name!r} must be a table or null"
            )
    merged = {"stages": merged_stages}

    # Validate leniently: reject only when a stage THIS REQUEST touches ends
    # up invalid after merge. A different stage's stored override may already
    # be broken (the global plan/catalog changed underneath it) -- that must
    # not block clearing or editing an unrelated stage, or the only way to
    # recover would be hand-editing the overrides file.
    _, errors = apply_overrides_lenient(plan, merged, catalog)
    touched_errors = {
        stage_name: message
        for stage_name, message in errors.items()
        if stage_name in overrides_body
    }
    if touched_errors:
        stage_name, message = next(iter(touched_errors.items()))
        raise ConfigError(f"override for stage {stage_name!r} is invalid: {message}")

    runs.write_plan_overrides(topic_id, merged)
    return read_api.run_plan_payload(catalog, plan, config.plan_sha256(), runs, topic_id)


def attach_profile(
    profiles: ProfileStore, topic_id: str, profile_id: str, *, overwrite: bool = True
) -> dict:
    if not profiles.profile_path(profile_id).is_file():
        raise NotFoundError(f"no such profile: {profile_id}")
    attachment = profiles.attach_profile_to_topic(profile_id, topic_id, overwrite=overwrite)
    run_dir = profiles.runs_dir / attachment.topic_id
    return {
        "profile_id": attachment.profile_id,
        "topic_id": attachment.topic_id,
        "snapshot_path": attachment.snapshot_path.relative_to(run_dir).as_posix(),
    }
