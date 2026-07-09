"""Durable job records and their on-disk store.

A Job is the durable record of one stage execution. Job state and logs live
under ``runs/<topic_id>/jobs/<job_id>/`` so history survives daemon restarts and
a fresh client can read past runs without the daemon running.
"""

from __future__ import annotations

import json
import os
import secrets
import signal
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

JOB_STATUSES = (
    "queued",
    "running",
    "succeeded",
    "failed",
    "canceled",
    "interrupted",
)
TERMINAL_STATUSES = frozenset({"succeeded", "failed", "canceled", "interrupted"})


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_job_id(now: datetime | None = None) -> str:
    """A sortable, collision-safe, filesystem-safe job id."""

    stamp = (now or _utcnow()).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{secrets.token_hex(2)}"


@dataclass
class Job:
    id: str
    topic_id: str
    stage: str
    provider: str
    model: str | None
    effort: str | None
    status: str = "queued"
    pid: int | None = None
    created_at: str = ""
    started_at: str | None = None
    ended_at: str | None = None
    exit_code: int | None = None
    response_path: str | None = None
    error: str | None = None
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Job":
        fields = {f: data.get(f) for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        fields["metadata"] = data.get("metadata") or {}
        return cls(**fields)


class JobStore:
    """Read and write job records under a workspace's ``runs`` tree."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    @property
    def runs_dir(self) -> Path:
        return self.root / "runs"

    def job_dir(self, topic_id: str, job_id: str) -> Path:
        return self.runs_dir / topic_id / "jobs" / job_id

    def _job_json(self, topic_id: str, job_id: str) -> Path:
        return self.job_dir(topic_id, job_id) / "job.json"

    def log_path(self, topic_id: str, job_id: str) -> Path:
        path = self.job_dir(topic_id, job_id) / "output.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def create(
        self,
        topic_id: str,
        stage: str,
        provider: str,
        model: str | None,
        effort: str | None,
    ) -> Job:
        job = Job(
            id=new_job_id(),
            topic_id=topic_id,
            stage=stage,
            provider=provider,
            model=model,
            effort=effort,
            created_at=_utcnow().isoformat(),
        )
        self.job_dir(topic_id, job.id).mkdir(parents=True, exist_ok=True)
        return job

    def save(self, job: Job) -> None:
        target = self._job_json(job.topic_id, job.id)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=".tmp-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(job.to_dict(), handle, indent=2)
            os.replace(tmp, target)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    def load(self, topic_id: str, job_id: str) -> Job:
        data = json.loads(self._job_json(topic_id, job_id).read_text(encoding="utf-8"))
        return Job.from_dict(data)

    def all_jobs(self) -> list[Job]:
        jobs: list[Job] = []
        if not self.runs_dir.exists():
            return jobs
        for jobs_dir in self.runs_dir.glob("*/jobs"):
            for job_dir in jobs_dir.iterdir():
                record = job_dir / "job.json"
                if record.is_file():
                    jobs.append(Job.from_dict(json.loads(record.read_text(encoding="utf-8"))))
        return jobs

    def list(self, topic_id: str | None = None) -> list[Job]:
        jobs = [j for j in self.all_jobs() if topic_id is None or j.topic_id == topic_id]
        return sorted(jobs, key=lambda j: j.id, reverse=True)

    def find(self, job_id: str) -> Job | None:
        for job in self.all_jobs():
            if job.id == job_id:
                return job
        return None

    def active_for(self, topic_id: str, stage: str) -> Job | None:
        for job in self.list(topic_id):
            if job.stage == stage and job.status not in TERMINAL_STATUSES:
                return job
        return None

    def read_log(self, job: Job, offset: int = 0) -> tuple[bytes, int]:
        path = self.job_dir(job.topic_id, job.id) / "output.log"
        if not path.exists():
            return b"", offset
        with path.open("rb") as handle:
            handle.seek(offset)
            data = handle.read()
        return data, offset + len(data)


def popen_kwargs() -> dict:
    """Spawn flags that put the child in its own killable group, per platform."""

    if sys.platform == "win32":  # pragma: no cover - exercised on Windows CI
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def terminate_process(proc: subprocess.Popen, *, grace: float = 5.0) -> None:
    """Terminate a spawned provider process portably: TERM then KILL.

    On POSIX the whole session/process-group is signalled (the child was spawned
    with ``start_new_session=True``); on Windows ``Popen.terminate()`` /
    ``kill()`` are used (no SIGTERM semantics).
    """

    if proc.poll() is not None:
        return
    try:
        if sys.platform == "win32":  # pragma: no cover - exercised on Windows CI
            proc.terminate()
        else:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        pass
    try:
        proc.wait(timeout=grace)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        if sys.platform == "win32":  # pragma: no cover - exercised on Windows CI
            proc.kill()
        else:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        pass
    try:
        proc.wait(timeout=grace)
    except subprocess.TimeoutExpired:  # pragma: no cover - defensive
        pass
