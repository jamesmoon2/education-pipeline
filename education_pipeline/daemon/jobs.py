"""Durable job records and their on-disk store.

A Job is the durable record of one stage execution. Job state and logs live
under ``runs/<topic_id>/jobs/<job_id>/`` so history survives daemon restarts and
a fresh client can read past runs without the daemon running.
"""

from __future__ import annotations

import json
import os
import queue
import secrets
import signal
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from education_pipeline.config import ConfigError, ModelCatalog, ModelPlan
from education_pipeline.providers import get_runner
from education_pipeline.runs import RunStore

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


MAX_LOG_BYTES = 10 * 1024 * 1024
DEFAULT_TIMEOUT_SECONDS = 1800


class JobRunner:
    """Executes exactly one job: spawn provider, capture output, ingest response."""

    def __init__(
        self,
        store: JobStore,
        runs: RunStore,
        catalog: ModelCatalog,
        plan: ModelPlan,
        *,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        force: bool = False,
    ) -> None:
        self.store = store
        self.runs = runs
        self.catalog = catalog
        self.plan = plan
        self.timeout = timeout
        self.force = force

    def execute(self, job: Job, cancel: threading.Event) -> Job:
        job.status = "running"
        job.started_at = _utcnow().isoformat()
        self.store.save(job)
        try:
            runner = get_runner(job.provider)
            if not runner.is_available():
                return self._fail(job, f"provider {job.provider!r} is not available on PATH")

            model = self._resolve_model(job)
            plan = self.plan.stage(job.stage)
            prompt_path = self.runs.stage_paths(job.topic_id, job.stage).prompt_path
            if not prompt_path.exists():
                return self._fail(job, f"prompt not written for stage {job.stage!r}")
            invocation = runner.build_invocation(model, plan, prompt_path)
            stdout, stdout_truncated, exit_code, timed_out, canceled = self._spawn(
                job, invocation, prompt_path, cancel
            )
            job.exit_code = exit_code
            if canceled:
                return self._terminal(job, "canceled", error="canceled")
            if timed_out:
                return self._fail(job, "timeout")
            if exit_code != 0:
                return self._fail(job, f"provider exited with code {exit_code}")
            if stdout_truncated:
                # A middle-truncated response is worse than no response: never
                # ingest it silently. Fail closed instead.
                return self._fail(job, "response too large")

            parsed = runner.parse_response(stdout)
            job.metadata.update(parsed.metadata)
            response_path = self.runs.ingest_response(
                job.topic_id, job.stage, parsed.text, force=self.force
            )
            job.response_path = str(response_path)
            self.runs.append_manifest_event(
                job.topic_id,
                {
                    "stage": job.stage,
                    "action": "job",
                    "job_id": job.id,
                    "provider": job.provider,
                    "model": job.model,
                },
            )
            return self._terminal(job, "succeeded")
        except ConfigError as exc:
            return self._fail(job, str(exc))

    def _resolve_model(self, job: Job):
        provider = self.catalog.require_provider(job.provider)
        if job.model is None:
            from education_pipeline.config import ModelOption

            return ModelOption(id="", label="")
        try:
            return provider.models[job.model]
        except KeyError as exc:
            raise ConfigError(
                f"unknown model {job.model!r} for provider {job.provider!r}"
            ) from exc

    def _spawn(self, job, invocation, prompt_path, cancel):
        log = self.store.log_path(job.topic_id, job.id)
        env = dict(os.environ)
        env.update(invocation.env)
        with prompt_path.open("rb") as prompt_handle:
            proc = subprocess.Popen(
                invocation.argv,
                stdin=prompt_handle,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                **popen_kwargs(),
            )
        job.pid = proc.pid
        self.store.save(job)

        # Providers (e.g. Codex) write progress to stderr and the final answer
        # to stdout; others (e.g. Claude) write JSON straight to stdout. Either
        # way the RESPONSE must be parsed from stdout only — mixing stderr in
        # would corrupt it. The LOG stays a combined, human-facing artifact.
        #
        # Both pipes are drained on their own background threads and pushed to
        # a shared queue tagged with their stream name. This is required, not
        # just convenient: if we only read stdout while the child fills the
        # stderr pipe buffer (or vice versa), the child blocks forever once
        # that OS pipe buffer fills — a classic two-pipe deadlock. Routing both
        # reads through a queue also lets the main loop poll the deadline/cancel
        # event on a short interval regardless of what the child is doing.
        chunk_queue: queue.Queue = queue.Queue()

        def _reader(stream_name: str, stream) -> None:
            try:
                for chunk in iter(lambda: stream.read(4096), b""):
                    chunk_queue.put((stream_name, chunk))
            finally:
                chunk_queue.put((stream_name, None))  # EOF sentinel

        assert proc.stdout is not None and proc.stderr is not None
        stdout_reader = threading.Thread(
            target=_reader, args=("stdout", proc.stdout), daemon=True
        )
        stderr_reader = threading.Thread(
            target=_reader, args=("stderr", proc.stderr), daemon=True
        )
        stdout_reader.start()
        stderr_reader.start()

        # Cap the LOG at ~MAX_LOG_BYTES while preserving *both* ends: provider
        # crash messages and JSON-close errors land at the tail, so a head-only
        # cap would discard exactly the diagnostic bytes we most want. Stream
        # live to the log until the head fills (most real runs finish far under
        # this and stream fully live); after that, retain only a rolling tail of
        # the most recent bytes and flush it, behind a truncation marker, at the
        # end. Final on-disk size and in-memory footprint both stay bounded.
        head_limit = MAX_LOG_BYTES // 2
        tail_limit = MAX_LOG_BYTES - head_limit
        head = bytearray()
        tail = bytearray()
        dropped = 0
        truncated = False

        # The RESPONSE capture is stdout only, bounded separately, and fails
        # closed (see `stdout_truncated`) instead of silently truncating.
        stdout_capture = bytearray()
        stdout_truncated = False

        deadline = time.monotonic() + self.timeout
        timed_out = False
        canceled = False
        poll_interval = 0.1
        eof_seen = {"stdout": False, "stderr": False}
        with log.open("wb") as log_handle:
            while not (eof_seen["stdout"] and eof_seen["stderr"]):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    timed_out = True
                    break
                if cancel.is_set():
                    canceled = True
                    break
                try:
                    stream_name, chunk = chunk_queue.get(timeout=min(poll_interval, remaining))
                except queue.Empty:
                    continue
                if chunk is None:
                    eof_seen[stream_name] = True
                    continue
                if len(head) < head_limit:
                    room = head_limit - len(head)
                    log_handle.write(chunk[:room])
                    head.extend(chunk[:room])
                    overflow = chunk[room:]
                else:
                    overflow = chunk
                if overflow:
                    truncated = True
                    dropped += len(overflow)
                    tail.extend(overflow)
                    if len(tail) > tail_limit:
                        del tail[: len(tail) - tail_limit]
                if stream_name == "stdout":
                    if len(stdout_capture) < MAX_LOG_BYTES:
                        room = MAX_LOG_BYTES - len(stdout_capture)
                        stdout_capture.extend(chunk[:room])
                        if len(chunk) > room:
                            stdout_truncated = True
                    else:
                        stdout_truncated = True
            if truncated:
                # `dropped` counts everything past the head; the tail we are
                # about to re-emit is not actually lost, so report only the gap.
                omitted = dropped - len(tail)
                log_handle.write(
                    f"\n...[output truncated, {omitted} bytes omitted]...\n".encode("utf-8")
                )
                log_handle.write(tail)
        if timed_out or canceled or proc.poll() is None:
            terminate_process(proc)
        exit_code = proc.wait()
        stdout_reader.join(timeout=1)
        stderr_reader.join(timeout=1)
        return (
            stdout_capture.decode("utf-8", errors="replace"),
            stdout_truncated,
            exit_code,
            timed_out,
            canceled,
        )

    def _fail(self, job: Job, error: str) -> Job:
        return self._terminal(job, "failed", error=error)

    def _terminal(self, job: Job, status: str, *, error: str | None = None) -> Job:
        job.status = status
        job.error = error
        job.ended_at = _utcnow().isoformat()
        job.pid = None
        self.store.save(job)
        return job


class Worker:
    """A single-worker job queue with FIFO ordering and crash recovery."""

    def __init__(self, store: JobStore, runner_factory: Callable[[Job], JobRunner]) -> None:
        self.store = store
        self.runner_factory = runner_factory
        self._queue: "queue.Queue[str | None]" = queue.Queue()
        self._cancels: dict[str, threading.Event] = {}
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stopping = False

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="ep-worker", daemon=True)
        self._thread.start()

    def stop(self, finish_inflight: bool = True) -> None:
        self._stopping = True
        if not finish_inflight:
            with self._lock:
                for event in self._cancels.values():
                    event.set()
        self._queue.put(None)  # sentinel to wake the loop
        if self._thread is not None:
            self._thread.join(timeout=30)

    def enqueue(self, job: Job) -> None:
        # Check + durable-save + queue insertion must be one atomic operation:
        # otherwise two concurrent callers can both pass the duplicate check
        # (neither job.json exists yet), both persist a "queued" record, and
        # only one wins the queue slot — leaving the loser's job.json on disk
        # with no queue entry, wedging this topic/stage until a restart. The
        # rejected job here is never saved, so `active_for` (which scans
        # job.json files) never sees it and no orphan is left behind.
        with self._lock:
            existing = self.store.active_for(job.topic_id, job.stage)
            if existing is not None and existing.id != job.id:
                raise ConfigError(
                    f"a {existing.status} job already exists for {job.topic_id}/{job.stage}"
                )
            self.store.save(job)
            self._cancels[job.id] = threading.Event()
            self._queue.put(job.id)

    def cancel(self, job_id: str) -> Job | None:
        job = self.store.find(job_id)
        if job is None or job.status in TERMINAL_STATUSES:
            return job
        with self._lock:
            event = self._cancels.get(job_id)
        if job.status == "queued":
            job.status = "canceled"
            job.ended_at = _utcnow().isoformat()
            self.store.save(job)
            if event is not None:
                event.set()
            return job
        if event is not None:
            event.set()
        return self.store.find(job_id)

    def reconcile(self) -> None:
        for job in self.store.all_jobs():
            if job.status == "running":
                if job.pid and _pid_plausibly_alive(job.pid):
                    _best_effort_kill(job.pid)
                job.status = "interrupted"
                job.error = "daemon restarted while job was running"
                job.ended_at = _utcnow().isoformat()
                job.pid = None
                self.store.save(job)
        for job in sorted(
            (j for j in self.store.all_jobs() if j.status == "queued"), key=lambda j: j.id
        ):
            with self._lock:
                self._cancels.setdefault(job.id, threading.Event())
            self._queue.put(job.id)

    def _loop(self) -> None:
        while True:
            job_id = self._queue.get()
            if job_id is None:
                return
            job = self.store.find(job_id)
            if job is None or job.status != "queued":
                continue
            with self._lock:
                cancel = self._cancels.get(job_id, threading.Event())
            if cancel.is_set():
                job.status = "canceled"
                job.ended_at = _utcnow().isoformat()
                self.store.save(job)
                continue
            runner = self.runner_factory(job)
            runner.execute(job, cancel)


def _pid_plausibly_alive(pid: int) -> bool:
    if sys.platform == "win32":  # pragma: no cover - Windows CI
        return True
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False
    except OSError:
        return False


def _best_effort_kill(pid: int) -> None:
    try:
        if sys.platform == "win32":  # pragma: no cover - Windows CI
            os.kill(pid, signal.SIGTERM)
        else:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
    except OSError:
        pass
