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
    """Raised when the daemon is unreachable or returns an error envelope."""


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
            raise DaemonError(f"daemon unreachable: {exc}") from exc
        finally:
            conn.close()
        data = json.loads(raw or b"{}")
        if resp.status >= 300:
            message = data.get("error", {}).get("message", f"HTTP {resp.status}")
            raise DaemonError(message)
        return data

    def health(self) -> dict:
        return self._call("GET", "/v1/health")

    def enqueue(self, topic_id: str, stage: str | None = None, force: bool = False) -> dict:
        body = {"topic_id": topic_id, "force": force}
        if stage is not None:
            body["stage"] = stage
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

    def shutdown(self) -> None:
        self._call("POST", "/v1/shutdown")


def _live_record(root: str | Path) -> dict | None:
    record = lifecycle.read_discovery(root)
    if record is None or lifecycle.is_stale(record):
        return None
    if "port" not in record or "token" not in record:
        return None  # in-flight claim placeholder; daemon not ready yet
    return record


def ensure_daemon(root: str | Path, *, autostart: bool = True, timeout: float = 15.0) -> DaemonClient:
    record = _live_record(root)
    if record is not None:
        return DaemonClient(root, record)
    if not autostart:
        raise DaemonError("no daemon running; start one with 'daemon start'")
    subprocess.Popen(
        [sys.executable, "-m", "education_pipeline.daemon", str(root)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
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
    raise DaemonError("daemon did not become ready in time")


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
