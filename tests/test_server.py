import http.client
import json
import sys
from pathlib import Path

import pytest

from education_pipeline import RunStore, parse_model_catalog, parse_model_plan
from education_pipeline.daemon.jobs import JobRunner, JobStore, Worker
from education_pipeline.daemon.server import DaemonContext, build_server
from education_pipeline.providers import Invocation, ProviderResponse, register_runner
from education_pipeline.workspace import ProfileStore, TopicStore

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


def _start_server(tmp_path, monkeypatch, web_dist=None):
    monkeypatch.setenv("FAKE_STDOUT", "GENERATED\n")
    register_runner(FakeRunner())
    runs = RunStore(tmp_path)
    runs.create_run("t")
    p = runs.stage_paths("t", "draft").prompt_path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("PROMPT", encoding="utf-8")
    topics_dir = tmp_path / "topics"
    topics_dir.mkdir(parents=True, exist_ok=True)
    (topics_dir / "t.toml").write_text(
        'schema_version = 1\nid = "t"\ntitle = "Test Topic"\n', encoding="utf-8"
    )
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir(parents=True, exist_ok=True)
    (profiles_dir / "p.toml").write_text(
        'schema_version = 1\nid = "p"\ntarget_learner = "team cohort"\n',
        encoding="utf-8",
    )
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
        topics=TopicStore(tmp_path),
        profiles=ProfileStore(tmp_path),
        on_shutdown=lambda: None,
        web_dist=web_dist,
    )
    srv = build_server(context)
    import threading

    threading.Thread(target=srv.serve_forever, daemon=True).start()
    worker.start()
    return srv, worker


@pytest.fixture
def server(tmp_path, monkeypatch):
    srv, worker = _start_server(tmp_path, monkeypatch)
    yield srv.server_port
    worker.stop()
    srv.shutdown()


@pytest.fixture
def ui_server(tmp_path, monkeypatch):
    dist = tmp_path / "webdist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>cockpit</html>", encoding="utf-8")
    (dist / "assets" / "app-abc.js").write_text("js", encoding="utf-8")
    srv, worker = _start_server(tmp_path, monkeypatch, web_dist=dist)
    yield srv.server_port
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


def test_session_returns_token_without_auth(server):
    status, body = _req(server, "GET", "/v1/session", token=None)
    assert status == 200
    assert body["token"] == "secret-token"
    assert body["version"] == "0.1.0"


def test_session_rejects_bad_host(server):
    conn = http.client.HTTPConnection("127.0.0.1", server)
    conn.putrequest("GET", "/v1/session", skip_host=True)
    conn.putheader("Host", "evil.example.com")
    conn.endheaders()
    resp = conn.getresponse()
    conn.close()
    assert resp.status == 400


def test_non_api_path_is_not_unauthorized(server):
    # Static serving lands in a later task; until then unknown non-/v1 paths
    # must 404 (or 503), never 401 — the browser has no token yet.
    status, _ = _req(server, "GET", "/favicon.ico", token=None)
    assert status in (404, 503)


def test_api_get_still_requires_token(server):
    status, body = _req(server, "GET", "/v1/jobs", token=None)
    assert status == 401
    assert body["error"]["code"] == "unauthorized"


def test_topics_list_includes_title_and_run(server):
    status, body = _req(server, "GET", "/v1/topics")
    assert status == 200
    (entry,) = body["topics"]
    assert entry["id"] == "t"
    assert entry["title"] == "Test Topic"
    assert entry["error"] is None
    # the fixture created a run for "t"; spec prompt not written yet
    assert entry["run"]["next_action"]["action"] == "write_prompt"
    assert entry["run"]["next_action"]["stage"] == "spec"


def test_topics_list_requires_token(server):
    status, _ = _req(server, "GET", "/v1/topics", token=None)
    assert status == 401


def test_topic_get_returns_toml(server):
    status, body = _req(server, "GET", "/v1/topics/t")
    assert status == 200
    assert body["id"] == "t"
    assert body["title"] == "Test Topic"
    assert 'title = "Test Topic"' in body["toml"]


def test_topic_get_unknown_is_404(server):
    status, body = _req(server, "GET", "/v1/topics/nope")
    assert status == 404
    assert body["error"]["code"] == "not_found"


def test_profiles_list_and_get(server):
    status, body = _req(server, "GET", "/v1/profiles")
    assert status == 200
    assert body["profiles"] == ["p"]
    status, body = _req(server, "GET", "/v1/profiles/p")
    assert status == 200
    assert 'target_learner = "team cohort"' in body["toml"]
    status, body = _req(server, "GET", "/v1/profiles/nope")
    assert status == 404


def test_runs_list(server):
    status, body = _req(server, "GET", "/v1/runs")
    assert status == 200
    assert body["runs"] == ["t"]


def test_run_status_endpoint(server):
    status, body = _req(server, "GET", "/v1/runs/t")
    assert status == 200
    assert body["topic_id"] == "t"
    assert body["finalized"] is False
    draft = next(s for s in body["stages"] if s["stage"] == "draft")
    assert draft["state"] == "prompt_written"  # fixture wrote the draft prompt
    assert body["next_action"]["action"] == "write_prompt"


def test_run_status_unknown_topic_is_404(server):
    status, body = _req(server, "GET", "/v1/runs/nope")
    assert status == 404


def test_stage_content_returns_prompt_and_nulls(server):
    status, body = _req(server, "GET", "/v1/runs/t/stages/draft")
    assert status == 200
    assert body == {
        "topic_id": "t",
        "stage": "draft",
        "prompt": "PROMPT",
        "response": None,
        "approved": None,
    }


def test_stage_content_bad_stage_is_400(server):
    status, body = _req(server, "GET", "/v1/runs/t/stages/banana")
    assert status == 400
    assert body["error"]["code"] == "bad_request"


def test_manifest_endpoint(server):
    status, body = _req(server, "GET", "/v1/runs/t/manifest")
    assert status == 200
    assert body["topic_id"] == "t"
    assert isinstance(body["events"], list)


def _raw_get(port, path, host=None):
    conn = http.client.HTTPConnection("127.0.0.1", port)
    if host is None:
        conn.request("GET", path)
    else:
        conn.putrequest("GET", path, skip_host=True)
        conn.putheader("Host", host)
        conn.endheaders()
    resp = conn.getresponse()
    body = resp.read()
    headers = dict(resp.getheaders())
    conn.close()
    return resp.status, body, headers


def test_index_served_without_token(ui_server):
    status, body, headers = _raw_get(ui_server, "/")
    assert status == 200
    assert b"cockpit" in body
    assert headers["Content-Type"] == "text/html; charset=utf-8"
    assert headers["Cache-Control"] == "no-store"
    assert not any(h.lower().startswith("access-control") for h in headers)


def test_asset_served_with_immutable_cache(ui_server):
    status, _, headers = _raw_get(ui_server, "/assets/app-abc.js")
    assert status == 200
    assert "immutable" in headers["Cache-Control"]


def test_spa_route_serves_index(ui_server):
    status, body, _ = _raw_get(ui_server, "/topics/t/stages/draft")
    assert status == 200
    assert b"cockpit" in body


def test_static_traversal_rejected(ui_server):
    status, _, _ = _raw_get(ui_server, "/../topics/t.toml")
    assert status == 404


def test_static_still_checks_host(ui_server):
    status, _, _ = _raw_get(ui_server, "/", host="evil.example.com")
    assert status == 400


def test_no_dist_returns_503(server):
    status, body = _req(server, "GET", "/", token=None)
    assert status == 503
    assert body["error"]["code"] == "ui_unavailable"


def test_write_endpoints_require_token(server):
    status, body = _req(server, "POST", "/v1/runs/t/advance", token=None)
    assert status == 401
    status, body = _req(server, "POST", "/v1/runs/t/stages/spec/response", token=None, body={"text": "x"})
    assert status == 401


def test_advance_writes_spec_prompt_and_returns_status(server):
    status, body = _req(server, "POST", "/v1/runs/t/advance")
    assert status == 200
    assert body["performed"] == "write_prompt"
    assert body["status"]["next_action"]["action"] == "save_response"
    assert body["status"]["next_action"]["stage"] == "spec"
    # single-step: calling again at a human step is a no-op
    status, body = _req(server, "POST", "/v1/runs/t/advance")
    assert status == 200 and body["performed"] is None


def test_response_ingest_conflict_and_force(server):
    status, body = _req(server, "POST", "/v1/runs/t/stages/draft/response", body={"text": "R1"})
    assert status == 200
    assert body["topic_id"] == "t" and body["stage"] == "draft"
    assert body["response_path"] == "responses/draft.response.md"
    assert body["status"]["stages"][2]["response_ingested"] is True
    status, body = _req(server, "POST", "/v1/runs/t/stages/draft/response", body={"text": "R2"})
    assert status == 409 and body["error"]["code"] == "already_exists"
    status, _ = _req(
        server, "POST", "/v1/runs/t/stages/draft/response", body={"text": "R2", "force": True}
    )
    assert status == 200


def test_response_validation_errors(server):
    status, body = _req(server, "POST", "/v1/runs/t/stages/draft/response", body={"text": "  "})
    assert status == 400
    status, body = _req(server, "POST", "/v1/runs/t/stages/draft/response", body={"text": 42})
    assert status == 400
    status, body = _req(server, "POST", "/v1/runs/t/stages/bogus/response", body={"text": "x"})
    assert status == 400
    status, body = _req(server, "POST", "/v1/runs/ghost/stages/draft/response", body={"text": "x"})
    assert status == 404 and body["error"]["code"] == "not_found"


def test_approve_endpoint_conflict_codes(server):
    status, body = _req(server, "POST", "/v1/runs/t/stages/qa/approve")
    assert status == 409 and body["error"]["code"] == "not_ready"
    _req(server, "POST", "/v1/runs/t/stages/qa/response", body={"text": "QA"})
    status, body = _req(server, "POST", "/v1/runs/t/stages/qa/approve")
    assert status == 200 and body["approved_path"] == "approved/qa.md"
    status, body = _req(server, "POST", "/v1/runs/t/stages/qa/approve")
    assert status == 409 and body["error"]["code"] == "already_exists"
    status, _ = _req(server, "POST", "/v1/runs/t/stages/qa/approve", body={"overwrite": True})
    assert status == 200


def test_finalize_and_export_endpoints(server):
    status, body = _req(server, "POST", "/v1/runs/t/finalize")
    assert status == 409 and body["error"]["code"] == "not_ready"
    status, body = _req(server, "POST", "/v1/runs/t/export", body={"format": "html"})
    assert status == 409 and body["error"]["code"] == "not_ready"

    _req(server, "POST", "/v1/runs/t/stages/repair/response", body={"text": "FINAL BODY"})
    _req(server, "POST", "/v1/runs/t/stages/repair/approve")
    status, body = _req(server, "POST", "/v1/runs/t/finalize")
    assert status == 200 and body["final_path"] == "final/guide.md"
    status, body = _req(server, "POST", "/v1/runs/t/finalize")
    assert status == 409 and body["error"]["code"] == "already_exists"

    status, body = _req(server, "POST", "/v1/runs/t/export", body={"format": "docx"})
    assert status == 400
    status, body = _req(server, "POST", "/v1/runs/t/export", body={"format": "html"})
    assert status == 200
    assert body == {"topic_id": "t", "format": "html", "export_path": "final/guide.html"}
    status, body = _req(server, "POST", "/v1/runs/t/export", body={"format": "html"})
    assert status == 409 and body["error"]["code"] == "already_exists"
    status, _ = _req(server, "POST", "/v1/runs/t/export", body={"format": "html", "overwrite": True})
    assert status == 200


def test_run_writes_blocked_while_job_active(server, monkeypatch):
    import time

    monkeypatch.setenv("FAKE_DELAY", "5")
    status, job = _req(server, "POST", "/v1/jobs", body={"topic_id": "t", "stage": "draft"})
    assert status == 200

    for method_path, body in (
        ("/v1/runs/t/advance", None),
        ("/v1/runs/t/stages/draft/response", {"text": "R"}),
        ("/v1/runs/t/stages/draft/approve", None),
        ("/v1/runs/t/finalize", None),
    ):
        status, resp = _req(server, "POST", method_path, body=body)
        assert status == 409, method_path
        assert resp["error"]["code"] == "job_active", method_path

    status, _ = _req(server, "POST", f"/v1/jobs/{job['id']}/cancel")
    assert status == 200
    for _ in range(200):
        status, current = _req(server, "GET", f"/v1/jobs/{job['id']}")
        if current["status"] in {"succeeded", "failed", "canceled", "interrupted"}:
            break
        time.sleep(0.02)
    assert current["status"] == "canceled"

    status, body = _req(server, "POST", "/v1/runs/t/advance")
    assert status == 200


def test_import_topic_endpoint(server):
    toml = 'schema_version = 1\nid = "n1"\ntitle = "New One"\n'
    status, body = _req(server, "POST", "/v1/topics", body={"toml": toml})
    assert status == 200 and body == {"id": "n1", "title": "New One"}
    status, body = _req(server, "POST", "/v1/topics", body={"toml": toml})
    assert status == 409 and body["error"]["code"] == "already_exists"
    status, _ = _req(server, "POST", "/v1/topics", body={"toml": toml, "overwrite": True})
    assert status == 200
    # imported topic is visible to the read API
    status, body = _req(server, "GET", "/v1/topics/n1")
    assert status == 200 and body["title"] == "New One"


def test_import_topic_rejects_invalid_input(server):
    status, _ = _req(server, "POST", "/v1/topics", body={"toml": "not = [valid"})
    assert status == 400
    status, _ = _req(server, "POST", "/v1/topics", body={"toml": 'schema_version = 1\ntitle = "No Id"\n'})
    assert status == 400
    status, _ = _req(server, "POST", "/v1/topics", body={"toml": 42})
    assert status == 400


def test_import_profile_endpoint(server):
    toml = 'schema_version = 1\nid = "p2"\ntarget_learner = "new cohort"\n'
    status, body = _req(server, "POST", "/v1/profiles", body={"toml": toml})
    assert status == 200 and body == {"id": "p2"}
    # fixture already created profile "p"
    existing = 'schema_version = 1\nid = "p"\ntarget_learner = "changed"\n'
    status, body = _req(server, "POST", "/v1/profiles", body={"toml": existing})
    assert status == 409 and body["error"]["code"] == "already_exists"


def test_attach_profile_endpoint(server):
    status, body = _req(server, "POST", "/v1/topics/t/profile", body={"profile_id": "p"})
    assert status == 200
    assert body == {"profile_id": "p", "topic_id": "t", "snapshot_path": "inputs/profile.toml"}
    # default overwrite=true: re-attaching refreshes the snapshot
    status, _ = _req(server, "POST", "/v1/topics/t/profile", body={"profile_id": "p"})
    assert status == 200
    status, body = _req(server, "POST", "/v1/topics/t/profile", body={"profile_id": "ghost"})
    assert status == 404
    status, body = _req(server, "POST", "/v1/topics/t/profile", body={"profile_id": 7})
    assert status == 400


def _raw_download(port, path, token="secret-token"):
    conn = http.client.HTTPConnection("127.0.0.1", port)
    headers = {}
    if token is not None:
        headers["X-EP-Token"] = token
    conn.request("GET", path, headers=headers)
    resp = conn.getresponse()
    data = resp.read()
    headers_out = {k.lower(): v for k, v in resp.getheaders()}
    conn.close()
    return resp.status, headers_out, data


def _finalize_t_over_http(port):
    _req(port, "POST", "/v1/runs/t/stages/repair/response", body={"text": "FINAL BODY"})
    _req(port, "POST", "/v1/runs/t/stages/repair/approve")
    _req(port, "POST", "/v1/runs/t/finalize")


def test_final_download(server):
    status, _, _ = _raw_download(server, "/v1/runs/t/final/download")
    assert status == 404
    _finalize_t_over_http(server)
    status, headers, data = _raw_download(server, "/v1/runs/t/final/download")
    assert status == 200
    assert headers["content-type"] == "text/markdown; charset=utf-8"
    assert headers["content-disposition"] == 'attachment; filename="t-guide.md"'
    assert data.decode("utf-8") == "FINAL BODY"


def test_export_download(server):
    _finalize_t_over_http(server)
    _req(server, "POST", "/v1/runs/t/export", body={"format": "html"})
    status, headers, data = _raw_download(server, "/v1/runs/t/exports/html/download")
    assert status == 200
    assert headers["content-type"] == "text/html; charset=utf-8"
    assert headers["content-disposition"] == 'attachment; filename="t-guide.html"'
    assert b"FINAL BODY" in data
    status, _, _ = _raw_download(server, "/v1/runs/t/exports/markdown/download")
    assert status == 404
    status, _, _ = _raw_download(server, "/v1/runs/t/exports/docx/download")
    assert status == 400


def test_downloads_require_token(server):
    status, _, _ = _raw_download(server, "/v1/runs/t/final/download", token=None)
    assert status == 401


def test_full_pipeline_over_http(server):
    toml = 'schema_version = 1\nid = "full"\ntitle = "Full Pipeline"\n'
    status, body = _req(server, "POST", "/v1/topics", body={"toml": toml})
    assert (status, body) == (200, {"id": "full", "title": "Full Pipeline"})

    for stage in ("spec", "outline", "draft", "qa", "repair"):
        status, body = _req(server, "POST", "/v1/runs/full/advance")
        assert status == 200 and body["performed"] == "write_prompt", stage
        assert body["status"]["next_action"]["stage"] == stage
        status, _ = _req(
            server,
            "POST",
            f"/v1/runs/full/stages/{stage}/response",
            body={"text": f"{stage} response"},
        )
        assert status == 200, stage
        status, _ = _req(server, "POST", f"/v1/runs/full/stages/{stage}/approve")
        assert status == 200, stage

    status, body = _req(server, "POST", "/v1/runs/full/advance")
    assert status == 200 and body["performed"] == "finalize"
    assert body["status"]["finalized"] is True
    assert body["status"]["next_action"]["action"] == "done"

    for fmt in ("html", "markdown"):
        status, _ = _req(server, "POST", "/v1/runs/full/export", body={"format": fmt})
        assert status == 200, fmt

    status, manifest = _req(server, "GET", "/v1/runs/full/manifest")
    assert status == 200
    actions = [event["action"] for event in manifest["events"]]
    assert actions.count("prompt_written") == 5
    assert actions.count("response_approved") == 5
    assert actions.count("finalized") == 1
    assert actions.count("exported") == 2

    for path, ctype in (
        ("/v1/runs/full/final/download", "text/markdown; charset=utf-8"),
        ("/v1/runs/full/exports/html/download", "text/html; charset=utf-8"),
        ("/v1/runs/full/exports/markdown/download", "text/markdown; charset=utf-8"),
    ):
        status, headers, _ = _raw_download(server, path)
        assert status == 200, path
        assert headers["content-type"] == ctype, path
