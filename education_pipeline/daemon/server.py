"""Loopback JSON API for the run daemon (v1).

Binds strictly to 127.0.0.1 on an ephemeral port. Every request must present the
``X-EP-Token`` header (constant-time compared). The Host header is restricted to
localhost to blunt DNS-rebinding from a future browser client.
"""

from __future__ import annotations

import json
import re
import secrets
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable

from education_pipeline.config import ConfigError, ModelCatalog, ModelPlan
from education_pipeline.daemon.jobs import Job, JobStore, Worker
from education_pipeline.runs import RunStore, SUPPORTED_STAGES

_ALLOWED_HOSTS = {"127.0.0.1", "localhost"}


@dataclass
class DaemonContext:
    root: Path
    store: JobStore
    worker: Worker
    runs: RunStore
    token: str
    version: str
    catalog: ModelCatalog
    plan: ModelPlan
    on_shutdown: Callable[[], None]

    def enqueue_stage(self, topic_id: str, stage: str | None, force: bool) -> Job:
        # Validate topic against the workspace (reuses safe-id logic in RunStore).
        status = self.runs.run_status(topic_id)
        target_stage = stage or status.next_action.stage
        if target_stage is None or target_stage not in SUPPORTED_STAGES:
            raise ConfigError(
                f"stage {target_stage!r} is not an executable stage; "
                f"executable stages: {', '.join(SUPPORTED_STAGES)}"
            )
        # Structural approval gate: only enqueue when the next action is to run a prompt.
        action = status.next_action
        if stage is None and action.action != "save_response":
            raise ConfigError(
                f"nothing to run: next action is {action.action!r} — {action.detail}"
            )
        if self.store.active_for(topic_id, target_stage) is not None:
            raise ConfigError(
                f"a job is already active for {topic_id}/{target_stage}"
            )
        stage_plan = self.plan.stage(target_stage)
        provider = stage_plan.provider or self.plan.provider
        job = self.store.create(topic_id, target_stage, provider, stage_plan.model, stage_plan.effort)
        job.metadata["force"] = force
        self.store.save(job)
        self.worker.enqueue(job)
        return job


def build_server(context: DaemonContext) -> ThreadingHTTPServer:
    handler = _make_handler(context)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    return server


def _make_handler(context: DaemonContext):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):  # silence default stderr logging
            pass

        def _host_ok(self) -> bool:
            host = (self.headers.get("Host") or "").split(":")[0]
            return host in _ALLOWED_HOSTS

        def _authed(self) -> bool:
            presented = self.headers.get("X-EP-Token", "")
            return secrets.compare_digest(presented, context.token)

        def _send(self, status: int, payload: dict) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _error(self, status: int, code: str, message: str) -> None:
            self._send(status, {"error": {"code": code, "message": message}})

        def _guard(self) -> bool:
            if not self._host_ok():
                self._error(400, "bad_host", "host not allowed")
                return False
            if not self._authed():
                self._error(401, "unauthorized", "missing or invalid token")
                return False
            return True

        def _read_body(self) -> dict:
            raw_length = self.headers.get("Content-Length", 0)
            try:
                length = int(raw_length)
            except (TypeError, ValueError):
                raise ConfigError("invalid Content-Length header")
            if length <= 0:
                return {}
            try:
                return json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                raise ConfigError("request body is not valid JSON")

        def do_GET(self):
            if not self._guard():
                return
            if self.path.startswith("/v1/health"):
                self._send(200, {"version": context.version, "started_at": None, "ok": True})
                return
            m = re.match(r"^/v1/jobs/([^/]+)/log(?:\?offset=(\d+))?$", self.path)
            if m:
                job = context.store.find(m.group(1))
                if job is None:
                    return self._error(404, "not_found", "no such job")
                offset = int(m.group(2) or 0)
                data, next_offset = context.store.read_log(job, offset)
                return self._send(200, {"data": data.decode("utf-8", "replace"), "offset": next_offset})
            m = re.match(r"^/v1/jobs/([^/]+)$", self.path)
            if m:
                job = context.store.find(m.group(1))
                if job is None:
                    return self._error(404, "not_found", "no such job")
                return self._send(200, job.to_dict())
            m = re.match(r"^/v1/jobs(?:\?topic=([^&]+))?$", self.path)
            if m:
                jobs = context.store.list(m.group(1))
                return self._send(200, {"jobs": [j.to_dict() for j in jobs]})
            self._error(404, "not_found", "unknown path")

        def do_POST(self):
            if not self._guard():
                return
            try:
                if self.path == "/v1/jobs":
                    body = self._read_body()
                    job = context.enqueue_stage(
                        body.get("topic_id", ""), body.get("stage"), bool(body.get("force"))
                    )
                    return self._send(200, job.to_dict())
                m = re.match(r"^/v1/jobs/([^/]+)/cancel$", self.path)
                if m:
                    job = context.worker.cancel(m.group(1))
                    if job is None:
                        return self._error(404, "not_found", "no such job")
                    return self._send(200, job.to_dict())
                if self.path == "/v1/shutdown":
                    self._send(200, {"ok": True})
                    context.on_shutdown()
                    return
            except ConfigError as exc:
                return self._error(400, "bad_request", str(exc))
            self._error(404, "not_found", "unknown path")

    return Handler
