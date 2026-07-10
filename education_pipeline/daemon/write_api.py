"""Write-action payload builders for the cockpit /v1 API.

Pure functions mirroring ``read_api``: stores in, JSON-serializable dicts out.
Each function pre-checks state on the same paths the store checks so refusals
carry a precise conflict code; the store call remains the authority and its
``ConfigError`` remains the backstop. Raises:

- :class:`read_api.NotFoundError` -> HTTP 404
- :class:`ConflictError` -> HTTP 409 (codes: ``already_exists``, ``not_ready``,
  ``job_active``)
- ``ConfigError`` propagates -> HTTP 400
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from education_pipeline.config import ConfigError
from education_pipeline.daemon import read_api
from education_pipeline.daemon.jobs import JobStore
from education_pipeline.daemon.read_api import NotFoundError
from education_pipeline.runs import RunStore
from education_pipeline.workspace import ProfileStore, TopicStore


class ConflictError(Exception):
    """The request is well-formed but current run/workspace state refuses it."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


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
    return {
        "topic_id": paths.topic_id,
        "stage": paths.stage,
        "response_path": _run_relative(runs, topic_id, path),
        "status": read_api.run_status_payload(runs, topic_id),
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


def import_profile(profiles: ProfileStore, toml_text: str, *, overwrite: bool = False) -> dict:
    profile_id = _parse_toml_id(toml_text, "profile")
    if profiles.profile_path(profile_id).is_file() and not overwrite:
        raise ConflictError(
            "already_exists",
            f"profile {profile_id!r} already exists; retry with overwrite to replace it",
        )
    profile = profiles.save_profile_toml(profile_id, toml_text, overwrite=overwrite)
    return {"id": profile.id}


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
