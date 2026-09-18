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
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from education_pipeline import cost as cost_module
from education_pipeline.atomic_io import atomic_write_bytes, atomic_write_text
from education_pipeline.config import (
    DEFAULT_PARALLELISM,
    MAX_PARALLELISM,
    MIN_PARALLELISM,
    ConfigError,
    ModelCatalog,
    ModelPlan,
)
from education_pipeline.providers import get_runner
from education_pipeline.runs import RunStore, StaleContentError
from education_pipeline.workspace_lock import workspace_lock

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
    # Identity of the spawned process (see ``_process_identity``), recorded so
    # crash recovery can tell "still our child" from "this pid was recycled".
    pid_identity: str | None = None
    created_at: str = ""
    started_at: str | None = None
    ended_at: str | None = None
    exit_code: int | None = None
    response_path: str | None = None
    error: str | None = None
    # What this execution cost, and whether the provider reported that itself
    # ("provider") or we estimated it from byte counts ("estimate"). Both stay
    # None when the cost could not be determined; records written before these
    # fields existed load with both None (see ``from_dict``).
    cost_usd: float | None = None
    cost_source: str | None = None
    # Draft fan-out (per-module-drafting design, decision 10). ``unit`` is
    # "skeleton" or "module" for a job that executes one draft unit rather
    # than a whole stage; ``module_id`` names the module for a module unit;
    # ``batch_id`` groups the module jobs written by one fan-out, and is what
    # the worker pool's admission rule is keyed on. All three stay None for an
    # ordinary stage job, and records written before they existed load as None
    # (see ``from_dict``).
    unit: str | None = None
    module_id: str | None = None
    batch_id: str | None = None
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Job":
        fields = {f: data.get(f) for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        fields["metadata"] = data.get("metadata") or {}
        return cls(**fields)


def _is_path_segment(name: str) -> bool:
    """True when ``name`` is a single, non-traversing path component.

    Topic and job ids reach the scoped lookups below straight off the HTTP
    routes (``/v1/jobs/<id>``, ``/v1/jobs?topic=<id>``). Those lookups join an
    id into a filesystem path, so the id must first be proven to name one
    child directory and nothing else. Refusing anything else is behaviour
    preserving: job records are only ever created through
    ``DaemonContext.enqueue_stage``, which validates the topic against
    ``RunStore``'s artifact-id pattern first, so no stored record can carry an
    id that fails this check -- the old workspace-wide scan matched nothing
    for such ids either.
    """

    if not name or name in (os.curdir, os.pardir):
        return False
    probe = Path(name)
    return len(probe.parts) == 1 and not probe.is_absolute() and probe.name == name


def _read_job_record(path: Path) -> dict:
    # Windows sharing semantics: reading job.json at the moment the worker
    # os.replace()s it fails with PermissionError. The replace is transient,
    # so retry briefly instead of surfacing a daemon 500.
    for attempt in range(10):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except PermissionError:
            if attempt == 9:
                raise
            time.sleep(0.05)
    raise AssertionError("unreachable")


class JobStore:
    """Read and write job records under a workspace's ``runs`` tree."""

    def __init__(self, root: str | Path, *, lock_timeout_seconds: float = 5.0) -> None:
        self.root = Path(root)
        self.lock_timeout_seconds = lock_timeout_seconds

    def lock(self):
        """The workspace advisory lock, for admitting or starting a job.

        Admission is a workspace mutation like any other: a CLI process that
        holds the lock around its own check-and-mutate (``cli._guarded_
        mutation``) must not have a job admitted underneath it. The lock is
        reentrant per process, so nesting inside ``RunStore``'s manifest
        critical sections is safe.

        Never held across the provider subprocess -- only around the record
        write that publishes a state change.
        """

        return workspace_lock(self.root, timeout_seconds=self.lock_timeout_seconds)

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
        *,
        unit: str | None = None,
        module_id: str | None = None,
        batch_id: str | None = None,
    ) -> Job:
        with self.lock():
            job = Job(
                id=new_job_id(),
                topic_id=topic_id,
                stage=stage,
                provider=provider,
                model=model,
                effort=effort,
                created_at=_utcnow().isoformat(),
                unit=unit,
                module_id=module_id,
                batch_id=batch_id,
            )
            self.job_dir(topic_id, job.id).mkdir(parents=True, exist_ok=True)
        return job

    def save(self, job: Job) -> None:
        atomic_write_text(
            self._job_json(job.topic_id, job.id),
            json.dumps(job.to_dict(), indent=2),
        )

    def load(self, topic_id: str, job_id: str) -> Job:
        return Job.from_dict(_read_job_record(self._job_json(topic_id, job_id)))

    def all_jobs(self) -> list[Job]:
        """Every job record in the workspace.

        The genuinely workspace-wide listing (``list()`` with no topic, and
        ``Worker.reconcile``). Topic- and id-scoped callers must not pay for
        it: see :meth:`list` and :meth:`find`.
        """

        jobs: list[Job] = []
        if not self.runs_dir.exists():
            return jobs
        for jobs_dir in self.runs_dir.glob("*/jobs"):
            for job_dir in jobs_dir.iterdir():
                record = job_dir / "job.json"
                if record.is_file():
                    jobs.append(Job.from_dict(_read_job_record(record)))
        return jobs

    def _topic_jobs(self, topic_id: str) -> list[Job]:
        """Records under one topic's ``jobs`` directory, unordered."""

        if not _is_path_segment(topic_id):
            return []
        jobs_dir = self.runs_dir / topic_id / "jobs"
        if not jobs_dir.is_dir():
            return []
        jobs: list[Job] = []
        for job_dir in jobs_dir.iterdir():
            record = job_dir / "job.json"
            if not record.is_file():
                continue
            job = Job.from_dict(_read_job_record(record))
            # ``save`` always writes a record under its own topic, so this
            # only ever drops a hand-edited record whose stored topic_id
            # disagrees with its directory -- which the old filter over
            # ``all_jobs()`` dropped too. Keeps the postcondition every
            # caller relies on: everything listed belongs to ``topic_id``.
            if job.topic_id == topic_id:
                jobs.append(job)
        return jobs

    def list(self, topic_id: str | None = None) -> list[Job]:
        """Jobs newest-first, for one topic or (``topic_id=None``) all of them.

        The per-topic case reads only ``runs/<topic_id>/jobs`` instead of
        parsing every record in the workspace: ``active_for`` and
        ``any_active_for`` are built on it, and those sit on the enqueue path
        under ``Worker``'s lock.
        """

        jobs = self.all_jobs() if topic_id is None else self._topic_jobs(topic_id)
        return sorted(jobs, key=lambda j: j.id, reverse=True)

    def find(self, job_id: str) -> Job | None:
        """The job with this id, read by its deterministic path.

        ``save`` writes every record to ``runs/<topic_id>/jobs/<job_id>/
        job.json``, so the only unknown is which topic owns the id: probe that
        exact path under each topic rather than parsing (and then linearly
        scanning) every record in the workspace. This is on the daemon's 1s
        log poll and the CLI's 0.25s job poll, and ``Worker.cancel``/
        ``Worker._loop`` call it per job.
        """

        if not _is_path_segment(job_id):
            return None
        for jobs_dir in self.runs_dir.glob("*/jobs"):
            record = jobs_dir / job_id / "job.json"
            if not record.is_file():
                continue
            job = Job.from_dict(_read_job_record(record))
            if job.id == job_id:
                return job
        return None

    def active_for(self, topic_id: str, stage: str) -> Job | None:
        for job in self.list(topic_id):
            if job.stage == stage and job.status not in TERMINAL_STATUSES:
                return job
        return None

    def active_unit_for(self, topic_id: str, stage: str, module_id: str | None) -> Job | None:
        """The live job for exactly this module of this stage, if any.

        ``active_for`` deliberately keeps matching *any* job of the stage, so
        the enqueue-a-whole-stage guards still refuse mid-batch. This narrower
        lookup serves only ``Worker.enqueue``'s duplicate check: during a draft
        fan-out several module jobs of the same stage are live at once by
        design, and only a second job for the *same* module is a duplicate.
        """

        for job in self.list(topic_id):
            if (
                job.stage == stage
                and job.module_id == module_id
                and job.status not in TERMINAL_STATUSES
            ):
                return job
        return None

    def batch(self, batch_id: str) -> list[Job]:
        """Every job of one fan-out, in creation order, whatever its status.

        Creation order is job-id order (``new_job_id`` is a sortable stamp),
        not save order: callers (``Worker.cancel_batch``, the batch view) want
        the order the fan-out wrote the jobs in.
        """

        if not batch_id:
            return []
        jobs = [job for job in self.all_jobs() if job.batch_id == batch_id]
        return sorted(jobs, key=lambda j: j.id)

    def any_active_for(self, topic_id: str) -> Job | None:
        """The first queued/running job for the topic across all stages, if any."""

        for job in self.list(topic_id):
            if job.status not in TERMINAL_STATUSES:
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


def _taskkill_tree(pid: int) -> None:  # pragma: no cover - exercised on Windows CI
    """Force-kill a Windows process and all of its descendants.

    ``Popen.terminate()``/``os.kill`` on Windows only signal the root
    process, so a provider that spawns helper children would leak them.
    ``taskkill /T`` walks and kills the whole tree; it ships with every
    supported Windows.
    """

    subprocess.run(
        ["taskkill", "/T", "/F", "/PID", str(pid)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def terminate_process(proc: subprocess.Popen, *, grace: float = 5.0) -> None:
    """Terminate a spawned provider and its process tree portably.

    On POSIX the whole session/process-group is signalled TERM then KILL (the
    child was spawned with ``start_new_session=True``); on Windows the tree is
    force-killed via ``taskkill /T`` (there are no SIGTERM semantics), with
    ``Popen.kill()`` kept as a fallback for the root.
    """

    if proc.poll() is not None:
        return
    try:
        if sys.platform == "win32":  # pragma: no cover - exercised on Windows CI
            _taskkill_tree(proc.pid)
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
        # queued -> running is the second half of admission: publish it under
        # the same workspace lock, so another process cannot see "no active
        # job" and mutate the run while this one is starting. Only the record
        # write is inside; the provider subprocess below never is.
        with self.store.lock():
            job.status = "running"
            job.started_at = _utcnow().isoformat()
            self.store.save(job)
        # Bound outside the try so the failure arm can still see raw provider
        # output captured before a parse/ingest error threw it away.
        stdout: str | None = None
        try:
            # Re-stamp the job with the *effective* stage plan carried by this
            # runner (the daemon re-resolves global plan + run overrides when
            # the worker picks the job up). The enqueue-time fields are only a
            # snapshot for display; overrides edited while the job sat queued
            # must govern what actually executes — and the record/manifest
            # must reflect what really ran.
            stage_plan = self.plan.stage(job.stage)
            job.provider = stage_plan.provider or self.plan.provider
            job.model = stage_plan.model
            job.effort = stage_plan.effort
            self.store.save(job)

            runner = get_runner(job.provider)
            if not runner.is_available():
                return self._fail(job, f"provider {job.provider!r} is not available on PATH")

            model = self._resolve_model(job)
            if job.unit is not None:
                # A draft-unit job (skeleton, or one module of a fan-out) has
                # its own prompt and its own response beside the stage's; it
                # must never read or write the stage-level pair.
                unit_paths = self.runs.draft_unit_paths(
                    job.topic_id, job.unit, module_id=job.module_id
                )
                prompt_path = unit_paths.prompt_path
                if not prompt_path.exists():
                    return self._fail(job, f"prompt not written for {self._unit_label(job)}")
            else:
                prompt_path = self.runs.stage_paths(job.topic_id, job.stage).prompt_path
                if job.stage == "audit":
                    prompt_path = self.runs.require_provider_ready_prompt(
                        job.topic_id, job.stage
                    )
                elif not prompt_path.exists():
                    return self._fail(job, f"prompt not written for stage {job.stage!r}")
            invocation = runner.build_invocation(model, stage_plan, prompt_path)
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
            self._record_cost(job, parsed, prompt_path, model)
            if job.unit is not None:
                response_path = self.runs.ingest_draft_unit(
                    job.topic_id,
                    job.unit,
                    parsed.text,
                    module_id=job.module_id,
                    force=self.force,
                ).response_path
            else:
                response_path = self.runs.ingest_response(
                    job.topic_id, job.stage, parsed.text, force=self.force
                )
            job.response_path = str(response_path)
            try:
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
                self.runs.record_stage_provenance(
                    job.topic_id,
                    job.stage,
                    provider=job.provider,
                    model=job.model,
                    effort=job.effort,
                    source=job.metadata.get("plan_source", "default"),
                    job_id=job.id,
                )
            except Exception as exc:
                # The response already landed durably; a manifest-event append
                # failure must not downgrade an already-committed success.
                job.metadata["manifest_event_error"] = str(exc)
            return self._terminal(job, "succeeded")
        except (ConfigError, StaleContentError) as exc:
            # parse_response or ingest_response refused the output: the model
            # already did the work, so the raw bytes are written beside the
            # stage's response before the job goes terminal.
            salvaged = self._salvage_stdout(job, stdout)
            error = str(exc)
            if salvaged is not None:
                job.metadata["salvaged_output"] = salvaged.name
                error = f"{error} (raw output salvaged to {salvaged.name})"
            return self._fail(job, error)
        except Exception as exc:
            # A non-ConfigError exception (Popen raising FileNotFoundError/
            # OSError, os.replace failing, a parser raising ValueError, ...)
            # must not propagate out of execute(): Worker._loop calls this
            # directly on its single worker thread, so an uncaught exception
            # here would kill that thread and permanently wedge the daemon.
            if job.pid:
                _best_effort_kill(job.pid)
            return self._fail(job, f"unexpected error: {exc}")

    def _record_cost(self, job: Job, parsed, prompt_path: Path, model) -> None:
        """Stamp the job with what this execution cost, if that is knowable.

        The provider's own figure wins; otherwise fall back to a byte-based
        estimate over the prompt we fed in and the response we got back (the
        prompt's size is taken from its stat, so the file is not read twice).
        An unpriced model leaves both fields None rather than claiming zero.

        ``model`` is the :class:`~education_pipeline.config.ModelOption` this
        execution already resolved, and the estimate is keyed off the id the
        provider was actually invoked with (``argv_model``, or the option id
        when the catalog declares none) -- never ``job.model``, which is only
        a catalog's project-local alias for it.
        """

        reported = parsed.metadata.get("total_cost_usd")
        if isinstance(reported, (int, float)) and not isinstance(reported, bool):
            job.cost_usd = float(reported)
            job.cost_source = "provider"
            return
        try:
            prompt_bytes = prompt_path.stat().st_size
        except OSError:  # pragma: no cover - prompt was read moments ago
            prompt_bytes = 0
        estimate = cost_module.estimate_cost_usd(
            prompt_bytes,
            len(parsed.text.encode("utf-8")),
            model.argv_model or model.id,
        )
        job.cost_usd = estimate["usd"]
        job.cost_source = estimate["source"]

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
        job.pid_identity = _process_identity(proc.pid)
        self.store.save(job)

        # Providers (e.g. Codex) write progress to stderr and the final answer
        # to stdout; others (e.g. Claude) write JSON straight to stdout. Either
        # way the RESPONSE must be parsed from stdout only — mixing stderr in
        # would corrupt it. For ordinary stages the LOG stays a combined,
        # human-facing artifact. Audit output is different: neither stdout nor
        # stderr can be proven free of narratives or profile values before it
        # is emitted. Suppress both raw streams from the job log / log API;
        # stdout is still captured separately and bounded for ingestion.
        #
        # This suppression is load-bearing, not an oversight: private values
        # "never appear in API errors, warnings, findings, logs, ..." (see
        # docs/superpowers/specs/2026-07-12-personalization-design.md, "Private
        # values may exist in local profile, prompt, trace, and raw
        # audit-response artifacts by design"). A failed audit parse still
        # keeps its output — `_salvage_stdout` writes it to
        # `<stage>.failed.<ts>.txt`, which IS a raw audit-response artifact
        # and stays in the workspace — so nothing is lost by keeping the log
        # itself empty here. Do not "fix" this by logging audit streams.
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
                if job.stage != "audit":
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
            # Provider CLIs on Windows emit \r\n; responses are sha-keyed
            # byte-exact artifacts, so normalize the platform newline noise
            # before the response is parsed and ingested.
            stdout_capture.decode("utf-8", errors="replace").replace("\r\n", "\n"),
            stdout_truncated,
            exit_code,
            timed_out,
            canceled,
        )

    def _salvage_stdout(self, job: Job, stdout: str | None) -> Path | None:
        """Write raw provider output beside the stage response, or None.

        ``stdout`` is None when the job failed before the provider ran (an
        unknown model, say), and there is then nothing to salvage. Otherwise
        the bytes land verbatim -- including empty output, which is itself the
        evidence of what went wrong -- under a timestamped name a human and
        ``write_api.salvage_stage_output`` can both find.
        """

        if stdout is None:
            return None
        try:
            responses = self.runs.stage_paths(job.topic_id, job.stage).response_path.parent
            stamp = _utcnow().strftime("%Y%m%dT%H%M%SZ")
            # A unit job names the unit it failed for, so concurrent module
            # jobs of one batch cannot collide on (or be mistaken for) the
            # bare stage-level salvage file.
            stem = self._unit_stem(job)
            path = responses / f"{stem}.failed.{stamp}.txt"
            suffix = 1
            while path.exists():  # two failures within one second
                path = responses / f"{stem}.failed.{stamp}-{suffix}.txt"
                suffix += 1
            atomic_write_bytes(path, stdout.encode("utf-8"))
            return path
        except Exception as exc:  # salvage is best effort; never mask the real error
            job.metadata["salvage_error"] = str(exc)
            return None

    @staticmethod
    def _unit_stem(job: Job) -> str:
        """``draft.<module_id>`` / ``draft.skeleton`` for a unit job, else ``<stage>``."""

        if job.unit is None:
            return job.stage
        return f"{job.stage}.{job.module_id or job.unit}"

    @staticmethod
    def _unit_label(job: Job) -> str:
        if job.module_id is not None:
            return f"draft module {job.module_id!r}"
        return f"draft unit {job.unit!r}"

    def _fail(self, job: Job, error: str) -> Job:
        return self._terminal(job, "failed", error=error)

    def _terminal(self, job: Job, status: str, *, error: str | None = None) -> Job:
        job.status = status
        job.error = error
        job.ended_at = _utcnow().isoformat()
        job.pid = None
        self.store.save(job)
        return job


def _validate_parallelism(value: object) -> int:
    """The same 1..4 whole-number rule the plan key carries, at the pool boundary.

    ``Worker`` is constructed from a plan today, but also directly by tests
    and by anything embedding the daemon, so the bound is enforced here too
    rather than trusted.
    """

    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"worker parallelism must be an integer; got {value!r}")
    if not MIN_PARALLELISM <= value <= MAX_PARALLELISM:
        raise ConfigError(
            f"worker parallelism must be between {MIN_PARALLELISM} and "
            f"{MAX_PARALLELISM}; got {value}"
        )
    return value


class Worker:
    """A bounded worker pool over one FIFO queue, with crash recovery.

    ``parallelism`` threads share a single queue, so ordering is still FIFO.
    What keeps concurrency honest is one admission rule, evaluated in
    :meth:`_loop` *after* a job is dequeued: a job may start only when nothing
    is running, or when every running job shares its ``batch_id``. So the
    module jobs of one draft fan-out overlap up to ``parallelism``, and every
    other job is exactly as serialized as it was when this was a single
    thread -- an ordinary job never runs beside anything, and a batch never
    starts while an ordinary job is in flight.

    Admission is deliberately *not* checked in :meth:`enqueue`: enqueue runs
    under the workspace lock (``server.py`` holds it around admission) and
    must stay non-blocking. A thread holding an inadmissible job waits on
    ``_admit``, a condition variable signalled at every job completion (and
    at every cancel); it never re-queues the job to the tail, which would
    spin whenever a non-batch job sat between two batch jobs. Waiting cannot
    deadlock: a running job always reaches a terminal state (exit, timeout or
    cancel), and its completion signals the condition.
    """

    def __init__(
        self,
        store: JobStore,
        runner_factory: Callable[[Job], JobRunner],
        *,
        parallelism: int = DEFAULT_PARALLELISM,
    ) -> None:
        self.store = store
        self.runner_factory = runner_factory
        self.parallelism = _validate_parallelism(parallelism)
        self._queue: "queue.Queue[str | None]" = queue.Queue()
        self._cancels: dict[str, threading.Event] = {}
        self._lock = threading.Lock()
        # Shares ``_lock``: admission reads the same running-job map that
        # completion mutates, and a waiter must release that lock while it
        # sleeps or no completion could ever publish itself.
        self._admit = threading.Condition(self._lock)
        # job_id -> batch_id (None for an ordinary job) for jobs admitted and
        # not yet finished. Its emptiness *is* "nothing is running".
        self._running: dict[str, str | None] = {}
        self._threads: list[threading.Thread] = []
        self._stopping = False

    def start(self) -> None:
        self._threads = [
            threading.Thread(target=self._loop, name=f"ep-worker-{index}", daemon=True)
            for index in range(self.parallelism)
        ]
        for thread in self._threads:
            thread.start()

    def stop(self, finish_inflight: bool = True) -> None:
        self._stopping = True
        if not finish_inflight:
            with self._lock:
                for event in self._cancels.values():
                    event.set()
        # One sentinel per thread: each returns on the first one it takes, and
        # a thread parked on ``_admit`` is woken by the notify below (its job
        # becomes admissible as the others drain).
        for _ in range(max(len(self._threads), 1)):
            self._queue.put(None)
        with self._admit:
            self._admit.notify_all()
        for thread in self._threads:
            thread.join(timeout=30)

    def enqueue(self, job: Job) -> None:
        # Check + durable-save + queue insertion must be one atomic operation:
        # otherwise two concurrent callers can both pass the duplicate check
        # (neither job.json exists yet), both persist a "queued" record, and
        # only one wins the queue slot — leaving the loser's job.json on disk
        # with no queue entry, wedging this topic/stage until a restart. The
        # rejected job here is never saved, so `active_for` (which scans
        # job.json files) never sees it and no orphan is left behind.
        with self._lock:
            # A module job collides only with a live job for the *same* module:
            # a fan-out puts several jobs of one stage in flight on purpose.
            # Ordinary jobs keep the stage-wide check unchanged.
            if job.module_id is not None:
                existing = self.store.active_unit_for(job.topic_id, job.stage, job.module_id)
                scope = f"{job.topic_id}/{job.stage}/{job.module_id}"
            else:
                existing = self.store.active_for(job.topic_id, job.stage)
                scope = f"{job.topic_id}/{job.stage}"
            if existing is not None and existing.id != job.id:
                raise ConfigError(f"a {existing.status} job already exists for {scope}")
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
            self._wake_waiters()
            return job
        if event is not None:
            event.set()
        self._wake_waiters()
        return self.store.find(job_id)

    def _wake_waiters(self) -> None:
        with self._admit:
            self._admit.notify_all()

    def cancel_batch(self, batch_id: str) -> list[Job]:
        """Cancel every job of one fan-out: queued ones flip, running ones signal.

        Per job this is exactly :meth:`cancel`, so a queued job goes terminal
        immediately and a running one is asked to stop through its cancel
        event (the runner terminates the provider and writes the terminal
        record). A job that has been dequeued but is still waiting for
        admission sees its event too and never starts.
        """

        results = [self.cancel(job.id) for job in self.store.batch(batch_id)]
        with self._admit:
            self._admit.notify_all()
        return [job for job in results if job is not None]

    def reconcile(self) -> None:
        for job in self.store.all_jobs():
            if job.status == "running":
                if (
                    job.pid
                    and _pid_plausibly_alive(job.pid)
                    and _identity_still_matches(job.pid, job.pid_identity)
                ):
                    _best_effort_kill(job.pid)
                job.status = "interrupted"
                job.error = "daemon restarted while job was running"
                job.ended_at = _utcnow().isoformat()
                job.pid = None
                job.pid_identity = None
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
            if not self._acquire_slot(job, cancel):
                # Canceled while it waited for a slot; it never started.
                job.status = "canceled"
                job.ended_at = _utcnow().isoformat()
                self.store.save(job)
                continue
            try:
                # runner_factory is inside the try so a factory that raises
                # (e.g. bad config building the JobRunner) can't kill the loop.
                runner = self.runner_factory(job)
                runner.execute(job, cancel)
            except Exception as exc:
                # Defense in depth: JobRunner.execute already catches broad
                # exceptions internally, but if anything still escapes (e.g. a
                # broken runner_factory, or a bug in execute itself), the
                # single worker thread must survive it rather than dying and
                # wedging every subsequent job permanently.
                fresh = self.store.find(job_id) or job
                if fresh.status not in TERMINAL_STATUSES:
                    fresh.status = "failed"
                    fresh.error = f"worker loop error: {exc}"
                    fresh.ended_at = _utcnow().isoformat()
                    fresh.pid = None
                    self.store.save(fresh)
            finally:
                self._release_slot(job)

    def _admissible(self, job: Job) -> bool:
        """The whole pool rule; caller holds ``_lock``.

        Nothing running: anything may start. Otherwise only a job of the very
        batch already running may join it -- which keeps an ordinary
        (``batch_id is None``) job alone, as it has always been.
        """

        if not self._running:
            return True
        if job.batch_id is None:
            return False
        return all(batch_id == job.batch_id for batch_id in self._running.values())

    def _acquire_slot(self, job: Job, cancel: threading.Event) -> bool:
        """Block until this job may start. False when it was canceled instead.

        The job is never put back on the queue: re-queueing an inadmissible
        job to the tail spins hot whenever an ordinary job sits between two
        batch jobs, and loses FIFO order. The wait timeout is only a
        belt-and-braces poll -- every completion and cancel notifies.
        """

        with self._admit:
            while not self._admissible(job):
                if cancel.is_set():
                    return False
                self._admit.wait(timeout=0.5)
            if cancel.is_set():
                return False
            self._running[job.id] = job.batch_id
        return True

    def _release_slot(self, job: Job) -> None:
        with self._admit:
            self._running.pop(job.id, None)
            self._admit.notify_all()


def _process_identity(pid: int) -> str | None:
    """A stable identity for a live pid, or ``None`` when it can't be had.

    Pids are recycled, so a pid alone cannot prove that the process running
    now is the one a job record was spawned for -- after a reboot the same
    number may belong to something unrelated. On Linux the process start time
    (field 22 of ``/proc/<pid>/stat``, in clock ticks since boot) pins the
    identity: it is fixed for the life of the process and a recycled pid gets
    a different one. The field is parsed after the last ``)`` because the
    process name (field 2) may itself contain spaces and parentheses.

    Other platforms have no equally cheap, dependency-free equivalent, so this
    returns ``None`` there and callers fall back to today's pid-only
    behaviour.
    """

    if sys.platform != "linux":
        return None
    try:
        stat = Path(f"/proc/{int(pid)}/stat").read_text(encoding="utf-8", errors="replace")
        fields = stat[stat.rindex(")") + 1 :].split()
        # fields[0] is field 3 (state), so field 22 (starttime) is index 19.
        starttime = int(fields[19])
    except (OSError, ValueError, IndexError):
        return None
    return f"linux-start:{starttime}"


def _identity_still_matches(pid: int, recorded: str | None) -> bool:
    """True when signalling ``pid`` is safe for a job that recorded ``recorded``.

    A record written before process identities existed (``recorded is None``)
    keeps the old pid-only behaviour; a recorded identity must match the live
    process, otherwise the pid has been recycled and belongs to someone else.
    """

    if recorded is None:
        return True
    return _process_identity(pid) == recorded


def effective_timeout_seconds(
    plan: ModelPlan,
    stage: str,
    model: str | None = None,
    *,
    default: float = DEFAULT_TIMEOUT_SECONDS,
) -> float:
    """How long one job for ``stage`` may run before it is timed out.

    The stage's ``timeout_seconds`` wins when the effective plan sets one,
    otherwise ``default`` (the daemon-wide value). ``model`` is accepted for a
    future per-model layer; the plan carries no per-model settings today.
    """

    stage_plan = plan.stages.get(stage)
    if stage_plan is not None and stage_plan.timeout_seconds is not None:
        return float(stage_plan.timeout_seconds)
    return default


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
            _taskkill_tree(pid)
        else:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
    except OSError:
        pass
