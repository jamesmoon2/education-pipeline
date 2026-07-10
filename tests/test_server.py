import http.client
import json
import sys
from pathlib import Path

import pytest

from education_pipeline import RunStore, parse_model_catalog, parse_model_plan
from education_pipeline.daemon.jobs import JobRunner, JobStore, Worker
from education_pipeline.daemon.server import DaemonContext, build_server
from education_pipeline.providers import Invocation, ProviderResponse, register_runner

FAKE = Path(__file__).parent / "fake_provider.py"


class FakeRunner:
    provider_id = "fake"
    executable = True

    def is_available(self):
        return True

    def build_invocation(self, model, plan, prompt_path):
        return Invocation(argv=[sys.executable, str(FAKE)])

    def parse_response(self, stdout):
        return ProviderResponse(text=stdout, metadata={})


@pytest.fixture
def server(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_STDOUT", "GENERATED\n")
    register_runner(FakeRunner())
    runs = RunStore(tmp_path)
    runs.create_run("t")
    # drive to the point where draft is the "save_response" next action:
    # write the draft prompt so next_action == save_response for draft
    p = runs.stage_paths("t", "draft").prompt_path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("PROMPT", encoding="utf-8")
    catalog = parse_model_catalog({"providers": [{"id": "fake", "models": [{"id": "m"}]}]})
    plan = parse_model_plan({"provider": "fake", "stages": {"draft": {"model": "m"}}}, catalog)
    store = JobStore(tmp_path)
    worker = Worker(store, lambda job: JobRunner(store, runs, catalog, plan, timeout=30))
    context = DaemonContext(
        root=tmp_path,
        store=store,
        worker=worker,
        runs=runs,
        token="secret-token",
        version="0.1.0",
        catalog=catalog,
        plan=plan,
        on_shutdown=lambda: None,
    )
    srv = build_server(context)
    port = srv.server_port
    import threading

    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    worker.start()
    yield port
    worker.stop()
    srv.shutdown()


def _req(port, method, path, token="secret-token", body=None):
    conn = http.client.HTTPConnection("127.0.0.1", port)
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["X-EP-Token"] = token
    conn.request(method, path, body=json.dumps(body) if body else None, headers=headers)
    resp = conn.getresponse()
    payload = json.loads(resp.read() or b"{}")
    conn.close()
    return resp.status, payload


def test_health_requires_token(server):
    status, _ = _req(server, "GET", "/v1/health", token=None)
    assert status == 401


def test_health_ok(server):
    status, body = _req(server, "GET", "/v1/health")
    assert status == 200
    assert body["version"] == "0.1.0"


def test_enqueue_runs_job_and_lands_response(server):
    status, body = _req(server, "POST", "/v1/jobs", body={"topic_id": "t", "stage": "draft"})
    assert status == 200
    job_id = body["id"]
    # poll until terminal
    import time

    for _ in range(200):
        status, job = _req(server, "GET", f"/v1/jobs/{job_id}")
        if job["status"] in {"succeeded", "failed", "canceled", "interrupted"}:
            break
        time.sleep(0.02)
    assert job["status"] == "succeeded"


def test_enqueue_rejects_unknown_topic(server):
    status, body = _req(server, "POST", "/v1/jobs", body={"topic_id": "../evil", "stage": "draft"})
    assert status == 400
    assert "error" in body


def _raw_post(port, path, raw_body, content_length):
    conn = http.client.HTTPConnection("127.0.0.1", port)
    conn.putrequest("POST", path)
    conn.putheader("X-EP-Token", "secret-token")
    conn.putheader("Content-Type", "application/json")
    conn.putheader("Content-Length", content_length)
    conn.endheaders()
    conn.send(raw_body)
    resp = conn.getresponse()
    payload = json.loads(resp.read() or b"{}")
    conn.close()
    return resp.status, payload


def test_bad_token_rejected(server):
    status, body = _req(server, "GET", "/v1/health", token="wrong")
    assert status == 401
    assert body["error"]["code"] == "unauthorized"


def test_bad_host_rejected(server):
    conn = http.client.HTTPConnection("127.0.0.1", server)
    conn.putrequest("GET", "/v1/health", skip_host=True)
    conn.putheader("Host", "evil.example.com")
    conn.putheader("X-EP-Token", "secret-token")
    conn.endheaders()
    resp = conn.getresponse()
    conn.close()
    assert resp.status == 400


def test_malformed_json_body_returns_400(server):
    body = b"{not valid json"
    status, payload = _raw_post(server, "/v1/jobs", body, str(len(body)))
    assert status == 400
    assert payload["error"]["code"] == "bad_request"
    # server survives: a well-formed request still succeeds afterward
    status, health = _req(server, "GET", "/v1/health")
    assert status == 200


def test_non_numeric_content_length_returns_400(server):
    status, payload = _raw_post(server, "/v1/jobs", b"{}", "notanumber")
    assert status == 400
    assert payload["error"]["code"] == "bad_request"


def test_oversized_content_length_returns_400(server):
    # Declare a body far exceeding the server's cap; the server must reject
    # based on the header alone (job POST bodies are tiny), not attempt to
    # read gigabytes into memory.
    oversized = 2 * 1024 * 1024  # 2 MiB > the 1 MiB cap
    status, payload = _raw_post(server, "/v1/jobs", b"{}", str(oversized))
    assert status == 400
    assert payload["error"]["code"] == "bad_request"
    # server survives: a well-formed request still succeeds afterward
    status, health = _req(server, "GET", "/v1/health")
    assert status == 200
