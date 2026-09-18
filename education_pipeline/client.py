"""Thin CLI-side HTTP client for the run daemon, with autostart."""

from __future__ import annotations

import http.client
import json
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import quote

from education_pipeline import __version__
from education_pipeline.daemon import lifecycle


class DaemonError(RuntimeError):
    """Raised when the daemon is unreachable or returns an error envelope.

    ``code`` carries the stable catalog slug from the envelope (spec §7.1)
    so callers can print the catalog's remediation; ``daemon_unreachable``
    is synthesized locally when no HTTP response arrived at all.
    """

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code


class DaemonClient:
    def __init__(self, root: str | Path, record: dict) -> None:
        self.root = Path(root)
        self.port = record["port"]
        self.token = record["token"]

    def _call(self, method: str, path: str, body: dict | None = None) -> dict:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        headers = {"X-EP-Token": self.token, "Content-Type": "application/json"}
        payload = json.dumps(body).encode("utf-8") if body is not None else None
        try:
            conn.request(method, path, body=payload, headers=headers)
            resp = conn.getresponse()
            raw = resp.read()
        except OSError as exc:
            raise DaemonError(
                f"daemon unreachable: {exc}", code="daemon_unreachable"
            ) from exc
        finally:
            conn.close()
        data = json.loads(raw or b"{}")
        if resp.status >= 300:
            error = data.get("error", {})
            message = error.get("message", f"HTTP {resp.status}")
            code = error.get("code")
            raise DaemonError(message, code=code if isinstance(code, str) else None)
        return data

    def health(self) -> dict:
        return self._call("GET", "/v1/health")

    def enqueue(
        self,
        topic_id: str,
        stage: str | None = None,
        force: bool = False,
        modules: list[str] | None = None,
    ) -> dict:
        """Enqueue one stage execution; for a draft fan-out, one whole batch.

        The response is the primary job's record. When the draft stage fanned
        out it also carries ``batch_id`` and ``jobs`` (every module job, in
        module order), so a caller can follow the batch without a second call.
        """

        body: dict = {"topic_id": topic_id, "force": force}
        if stage is not None:
            body["stage"] = stage
        if modules is not None:
            body["modules"] = list(modules)
        return self._call("POST", "/v1/jobs", body)

    def list_jobs(self, topic: str | None = None) -> list[dict]:
        path = "/v1/jobs" if topic is None else f"/v1/jobs?topic={quote(topic)}"
        return self._call("GET", path).get("jobs", [])

    def get_job(self, job_id: str) -> dict:
        return self._call("GET", f"/v1/jobs/{quote(job_id)}")

    def get_log(self, job_id: str, offset: int = 0) -> tuple[str, int]:
        data = self._call("GET", f"/v1/jobs/{quote(job_id)}/log?offset={offset}")
        return data.get("data", ""), data.get("offset", offset)

    def cancel(self, job_id: str) -> dict:
        return self._call("POST", f"/v1/jobs/{quote(job_id)}/cancel")

    def get_batch(self, batch_id: str) -> dict:
        return self._call("GET", f"/v1/jobs/batch/{quote(batch_id)}")

    def cancel_batch(self, batch_id: str) -> dict:
        return self._call("POST", f"/v1/jobs/batch/{quote(batch_id)}/cancel")

    def ingest_draft_unit(
        self,
        topic_id: str,
        unit: str,
        text: str,
        *,
        module_id: str | None = None,
        force: bool = False,
    ) -> dict:
        """Save one draft unit's model response (skeleton, or one module)."""

        return self._call(
            "POST", self._draft_unit_path(topic_id, unit, module_id), {
                "text": text,
                "force": force,
            }
        )

    def edit_draft_unit(
        self,
        topic_id: str,
        unit: str,
        text: str,
        *,
        module_id: str | None = None,
        base_sha256: str,
    ) -> dict:
        """Replace one draft unit's response, guarded by its current hash."""

        return self._call(
            "PUT", self._draft_unit_path(topic_id, unit, module_id), {
                "text": text,
                "base_sha256": base_sha256,
            }
        )

    @staticmethod
    def _draft_unit_path(topic_id: str, unit: str, module_id: str | None) -> str:
        base = f"/v1/runs/{quote(topic_id)}/draft"
        if unit == "skeleton":
            return f"{base}/skeleton/response"
        if not module_id:
            raise DaemonError("a module draft unit needs a module id")
        return f"{base}/modules/{quote(module_id)}/response"

    def assemble_draft(self, topic_id: str, *, force: bool = False) -> dict:
        """Assemble the saved draft units into the draft stage response."""

        return self._call(
            "POST", f"/v1/runs/{quote(topic_id)}/draft/assemble", {"force": force}
        )

    def shutdown(self) -> None:
        self._call("POST", "/v1/shutdown")


def _live_record(root: str | Path) -> dict | None:
    record = lifecycle.read_discovery(root)
    if record is None or lifecycle.is_stale(record):
        return None
    if "port" not in record or "token" not in record:
        return None  # in-flight claim placeholder; daemon not ready yet
    return record


def ensure_daemon(root: str | Path, *, autostart: bool = True, timeout: float = 30.0) -> DaemonClient:
    record = _live_record(root)
    if record is not None:
        return DaemonClient(root, record)
    if not autostart:
        raise DaemonError("no daemon running; start one with 'daemon start'")
    # Startup failures must stay diagnosable: the daemon is detached, so its
    # stderr goes to a per-workspace log (truncated on each autostart) rather
    # than /dev/null. The child keeps its own duplicate of the handle.
    log_path = lifecycle.discovery_dir(root) / "daemon.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("wb") as log:
        subprocess.Popen(
            [sys.executable, "-m", "education_pipeline.daemon", str(root)],
            stdout=subprocess.DEVNULL,
            stderr=log,
        )
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        record = _live_record(root)
        if record is not None:
            client = DaemonClient(root, record)
            try:
                client.health()
                return client
            except DaemonError:
                pass
        time.sleep(0.1)
    raise DaemonError(
        f"daemon did not become ready in time; startup log: {log_path}"
    )


def daemon_status(root: str | Path) -> dict:
    record = lifecycle.read_discovery(root)
    if record is None:
        return {"running": False, "pid": None, "port": None, "version": None,
                "version_mismatch": False}
    running = not lifecycle.is_stale(record)
    return {
        "running": running,
        "pid": record.get("pid"),
        "port": record.get("port"),
        "version": record.get("version"),
        "version_mismatch": record.get("version") != __version__,
    }
