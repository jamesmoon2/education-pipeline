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
from typing import Callable, Protocol

from education_pipeline.config import ConfigError, ModelCatalog, ModelPlan, apply_overrides
from education_pipeline.daemon import read_api, write_api
from education_pipeline.daemon.jobs import Job, JobStore, Worker
from education_pipeline.daemon.static import resolve_static
from education_pipeline.export import render_html_body
from education_pipeline.guides import (
    GuideDocumentError,
    assemble_guide_document,
    normalize_guide,
    parse_guide,
    validate_guide,
)
from education_pipeline.runs import RunStore, SUPPORTED_STAGES
from education_pipeline.workspace import ProfileStore, TopicStore

_ALLOWED_HOSTS = {"127.0.0.1", "localhost"}


class ConfigSource(Protocol):
    """Reads the model catalog + plan, fresh, on every ``load()`` call."""

    def load(self) -> tuple[ModelCatalog, ModelPlan]: ...

    def plan_sha256(self) -> str: ...

    def write_plan(self, toml_text: str) -> None: ...
MAX_REQUEST_BODY_BYTES = 1024 * 1024  # 1 MiB; job POST bodies are tiny


def _require_str(body: dict, key: str) -> str:
    value = body.get(key)
    if not isinstance(value, str):
        raise ConfigError(f"body field {key!r} must be a string")
    return value


@dataclass
class DaemonContext:
    root: Path
    store: JobStore
    worker: Worker
    runs: RunStore
    token: str
    version: str
    config: ConfigSource
    topics: TopicStore
    profiles: ProfileStore
    on_shutdown: Callable[[], None]
    web_dist: Path | None = None

    def enqueue_stage(self, topic_id: str, stage: str | None, force: bool) -> Job:
        catalog, plan = self.config.load()
        overrides = self.runs.read_plan_overrides(topic_id)
        plan = apply_overrides(plan, overrides, catalog)
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
        stage_plan = plan.stage(target_stage)
        provider = stage_plan.provider or plan.provider
        job = self.store.create(topic_id, target_stage, provider, stage_plan.model, stage_plan.effort)
        job.metadata["force"] = force
        job.metadata["plan_source"] = (
            "override" if target_stage in overrides.get("stages", {}) else "default"
        )
        # Do not pre-save here: Worker.enqueue performs the duplicate-active
        # check, durable save, and queue insertion as one atomic operation
        # under its lock, so a rejected job never gets a job.json written.
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

        def _send_file(self, path, content_type: str, filename: str) -> None:
            body = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.end_headers()
            self.wfile.write(body)

        def _error(self, status: int, code: str, message: str, details=None) -> None:
            error = {"code": code, "message": message}
            if details is not None:
                error["details"] = details
            self._send(status, {"error": error})

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
            if length > MAX_REQUEST_BODY_BYTES:
                raise ConfigError(
                    f"request body of {length} bytes exceeds the "
                    f"{MAX_REQUEST_BODY_BYTES}-byte cap"
                )
            try:
                value = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                raise ConfigError("request body is not valid JSON")
            if not isinstance(value, dict):
                raise ConfigError("request JSON root must be an object")
            return value

        def do_GET(self):
            if not self._host_ok():
                return self._error(400, "bad_host", "host not allowed")
            path = self.path.split("?", 1)[0]
            if path == "/v1/session":
                # Token bootstrap for the browser SPA. Safe without auth on
                # loopback: no CORS headers are ever sent, so a cross-origin
                # page can issue this request but never read the response.
                return self._send(
                    200, {"token": context.token, "version": context.version}
                )
            if path.startswith("/v1/"):
                if not self._authed():
                    return self._error(401, "unauthorized", "missing or invalid token")
                return self._api_get()
            return self._static_get()

        def _static_get(self):
            dist = context.web_dist
            if dist is None:
                return self._error(
                    503,
                    "ui_unavailable",
                    "web UI not built; run `npm run build` in web/ or set EP_WEB_DIST",
                )
            static = resolve_static(dist, self.path)
            if static is None:
                return self._error(404, "not_found", "unknown path")
            body = static.path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", static.content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", static.cache_control)
            if static.content_type.startswith("text/html"):
                self.send_header(
                    "Content-Security-Policy",
                    "default-src 'self'; script-src 'self' 'unsafe-inline'; "
                    "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
                    "connect-src 'self'; frame-src 'self'; object-src 'none'; "
                    "base-uri 'none'; form-action 'none'",
                )
            self.end_headers()
            self.wfile.write(body)

        def _api_get(self):
            try:
                return self._api_get_routes()
            except read_api.NotFoundError as exc:
                return self._error(404, "not_found", str(exc))
            except ConfigError as exc:
                return self._error(400, "bad_request", str(exc))

        def _api_get_routes(self):
            if self.path.startswith("/v1/health"):
                return self._send(
                    200, {"version": context.version, "started_at": None, "ok": True}
                )
            if self.path == "/v1/topics":
                return self._send(
                    200, read_api.list_topics(context.topics, context.runs)
                )
            m = re.match(r"^/v1/topics/([^/?]+)$", self.path)
            if m:
                return self._send(200, read_api.get_topic(context.topics, m.group(1)))
            if self.path == "/v1/profiles":
                return self._send(200, read_api.list_profiles(context.profiles))
            m = re.match(r"^/v1/profiles/([^/?]+)$", self.path)
            if m:
                return self._send(
                    200, read_api.get_profile(context.profiles, m.group(1))
                )
            if self.path == "/v1/config/providers":
                catalog, _ = context.config.load()
                return self._send(200, read_api.providers_payload(catalog))
            if self.path == "/v1/config/catalog":
                catalog, _ = context.config.load()
                return self._send(200, read_api.catalog_payload(catalog))
            if self.path == "/v1/config/plan":
                catalog, plan = context.config.load()
                return self._send(
                    200,
                    read_api.plan_payload(catalog, plan, context.config.plan_sha256()),
                )
            if self.path == "/v1/runs":
                return self._send(200, read_api.list_runs(context.runs))
            m = re.match(r"^/v1/runs/([^/?]+)/manifest$", self.path)
            if m:
                return self._send(
                    200, read_api.manifest_payload(context.runs, m.group(1))
                )
            m = re.match(r"^/v1/runs/([^/?]+)/stages/([^/?]+)$", self.path)
            if m:
                return self._send(
                    200, read_api.stage_content(context.runs, m.group(1), m.group(2))
                )
            m = re.match(r"^/v1/runs/([^/?]+)/validation/(draft|final)$", self.path)
            if m:
                return self._send(
                    200, read_api.validation_payload(context.runs, m.group(1), m.group(2))
                )
            m = re.match(r"^/v1/runs/([^/?]+)/validation/(draft|final)/waivers$", self.path)
            if m:
                return self._send(
                    200, read_api.waivers_payload(context.runs, m.group(1), m.group(2))
                )
            m = re.match(r"^/v1/runs/([^/?]+)/final/download$", self.path)
            if m:
                topic_id = m.group(1)
                path = read_api.final_download_path(context.runs, topic_id)
                guide_v1 = context.runs.content_contract(topic_id).kind == "interactive_guide"
                return self._send_file(
                    path,
                    "application/vnd.education-pipeline.guide+json;version=1.0"
                    if guide_v1 else "text/markdown; charset=utf-8",
                    f"{topic_id}-guide.json" if guide_v1 else f"{topic_id}-guide.md",
                )
            m = re.match(r"^/v1/runs/([^/?]+)/exports/([^/?]+)/download$", self.path)
            if m:
                topic_id, fmt = m.group(1), m.group(2)
                path = read_api.export_download_path(context.runs, topic_id, fmt)
                if fmt == "html":
                    return self._send_file(
                        path, "text/html; charset=utf-8", f"{topic_id}-guide.html"
                    )
                return self._send_file(
                    path, "text/markdown; charset=utf-8", f"{topic_id}-guide.bundle.md"
                )
            m = re.match(r"^/v1/runs/([^/?]+)/plan$", self.path)
            if m:
                catalog, plan = context.config.load()
                return self._send(
                    200,
                    read_api.run_plan_payload(
                        catalog, plan, context.config.plan_sha256(), context.runs, m.group(1)
                    ),
                )
            m = re.match(r"^/v1/runs/([^/?]+)$", self.path)
            if m:
                return self._send(
                    200, read_api.run_status_payload(context.runs, m.group(1))
                )
            m = re.match(r"^/v1/jobs/([^/]+)/log(?:\?offset=(\d+))?$", self.path)
            if m:
                job = context.store.find(m.group(1))
                if job is None:
                    return self._error(404, "not_found", "no such job")
                offset = int(m.group(2) or 0)
                data, next_offset = context.store.read_log(job, offset)
                return self._send(
                    200,
                    {"data": data.decode("utf-8", "replace"), "offset": next_offset},
                )
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
                return self._api_post_routes()
            except read_api.NotFoundError as exc:
                return self._error(404, "not_found", str(exc))
            except write_api.ConflictError as exc:
                return self._error(409, exc.code, str(exc))
            except write_api.UnprocessableError as exc:
                return self._error(422, exc.code, str(exc), exc.details)
            except ConfigError as exc:
                return self._error(400, "bad_request", str(exc))

        def _api_post_routes(self):
            if self.path == "/v1/preview":
                body = self._read_body()
                return self._send(
                    200, {"html": render_html_body(_require_str(body, "text"))}
                )
            if self.path == "/v1/guide-preview":
                body = self._read_body()
                text = _require_str(body, "text")
                try:
                    json.loads(text)
                except json.JSONDecodeError:
                    return self._error(400, "invalid_guide_json", "guide text is not valid JSON")
                parsed = parse_guide(text)
                report = validate_guide(text, phase="draft")
                if not parsed.ok:
                    return self._error(
                        422,
                        "guide_not_renderable",
                        "guide JSON is not safe to render",
                        report.to_dict(),
                    )
                try:
                    guide = normalize_guide(parsed)
                    html = assemble_guide_document(guide, mode="preview")
                except GuideDocumentError as exc:
                    return self._error(422, "guide_not_renderable", str(exc), report.to_dict())
                return self._send(
                    200,
                    {
                        "html": html,
                        "content_sha256": report.guide_sha256,
                        "validation": {
                            key: report.summary.to_dict()[key]
                            for key in ("blocking", "errors", "warnings")
                        },
                    },
                )
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
            m = re.match(r"^/v1/runs/([^/?]+)/advance$", self.path)
            if m:
                self._read_body()  # enforce the JSON/size rules even for an empty body
                return self._send(
                    200, write_api.advance_run(context.runs, context.store, m.group(1))
                )
            m = re.match(r"^/v1/runs/([^/?]+)/validate$", self.path)
            if m:
                body = self._read_body()
                return self._send(
                    200,
                    write_api.validate_run(
                        context.runs, context.store, m.group(1), _require_str(body, "phase")
                    ),
                )
            m = re.match(r"^/v1/runs/([^/?]+)/validation/(draft|final)/waivers$", self.path)
            if m:
                body = self._read_body()
                return self._send(
                    200,
                    write_api.create_waiver(
                        context.runs,
                        m.group(1),
                        m.group(2),
                        _require_str(body, "finding_id"),
                        _require_str(body, "guide_sha256"),
                        _require_str(body, "reason"),
                    ),
                )
            m = re.match(r"^/v1/runs/([^/?]+)/stages/([^/?]+)/response$", self.path)
            if m:
                body = self._read_body()
                return self._send(
                    200,
                    write_api.ingest_response(
                        context.runs,
                        context.store,
                        m.group(1),
                        m.group(2),
                        _require_str(body, "text"),
                        force=bool(body.get("force")),
                    ),
                )
            m = re.match(r"^/v1/runs/([^/?]+)/stages/([^/?]+)/approve$", self.path)
            if m:
                body = self._read_body()
                return self._send(
                    200,
                    write_api.approve_stage(
                        context.runs,
                        context.store,
                        m.group(1),
                        m.group(2),
                        overwrite=bool(body.get("overwrite")),
                    ),
                )
            m = re.match(r"^/v1/runs/([^/?]+)/finalize$", self.path)
            if m:
                body = self._read_body()
                return self._send(
                    200,
                    write_api.finalize_run(
                        context.runs,
                        context.store,
                        m.group(1),
                        overwrite=bool(body.get("overwrite")),
                    ),
                )
            m = re.match(r"^/v1/runs/([^/?]+)/export$", self.path)
            if m:
                body = self._read_body()
                return self._send(
                    200,
                    write_api.export_run(
                        context.runs,
                        m.group(1),
                        format=body.get("format", "html")
                        if isinstance(body.get("format", "html"), str)
                        else "",
                        overwrite=bool(body.get("overwrite")),
                    ),
                )
            if self.path == "/v1/topics":
                body = self._read_body()
                return self._send(
                    200,
                    write_api.import_topic(
                        context.topics,
                        _require_str(body, "toml"),
                        overwrite=bool(body.get("overwrite")),
                    ),
                )
            if self.path == "/v1/profiles":
                body = self._read_body()
                return self._send(
                    200,
                    write_api.import_profile(
                        context.profiles,
                        _require_str(body, "toml"),
                        overwrite=bool(body.get("overwrite")),
                    ),
                )
            m = re.match(r"^/v1/topics/([^/?]+)/profile$", self.path)
            if m:
                body = self._read_body()
                return self._send(
                    200,
                    write_api.attach_profile(
                        context.profiles,
                        m.group(1),
                        _require_str(body, "profile_id"),
                        overwrite=bool(body.get("overwrite", True)),
                    ),
                )
            self._error(404, "not_found", "unknown path")

        def do_PUT(self):
            if not self._guard():
                return
            try:
                return self._api_put_routes()
            except read_api.NotFoundError as exc:
                return self._error(404, "not_found", str(exc))
            except write_api.ConflictError as exc:
                return self._error(409, exc.code, str(exc))
            except ConfigError as exc:
                return self._error(400, "bad_request", str(exc))

        def _api_put_routes(self):
            if self.path == "/v1/config/plan":
                return self._send(
                    200,
                    write_api.update_global_plan(context.config, self._read_body()),
                )
            m = re.match(r"^/v1/runs/([^/?]+)/plan$", self.path)
            if m:
                return self._send(
                    200,
                    write_api.update_run_plan(
                        context.runs, context.config, m.group(1), self._read_body()
                    ),
                )
            m = re.match(r"^/v1/runs/([^/?]+)/stages/([^/?]+)/response$", self.path)
            if m:
                body = self._read_body()
                return self._send(
                    200,
                    write_api.edit_response(
                        context.runs,
                        context.store,
                        m.group(1),
                        m.group(2),
                        _require_str(body, "text"),
                        base_sha256=_require_str(body, "base_sha256"),
                    ),
                )
            self._error(404, "not_found", "unknown path")

    return Handler
