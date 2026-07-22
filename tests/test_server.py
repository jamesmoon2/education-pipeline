import hashlib
import http.client
import json
import shutil
import sys
import threading
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest

import test_runs
from education_pipeline import (
    STAGE_ORDER,
    ContentContract,
    RunStore,
    load_model_plan,
    parse_model_catalog,
    parse_model_plan,
)
from education_pipeline.daemon import StaticConfigSource, WorkspaceConfigSource
from education_pipeline.daemon import read_api
from education_pipeline.daemon.jobs import JobRunner, JobStore, Worker
from education_pipeline.daemon.server import DaemonContext, build_server
from education_pipeline.providers import Invocation, ProviderResponse, register_runner
from education_pipeline.workspace import ProfileStore, TopicStore

FAKE = Path(__file__).parent / "fake_provider.py"
GUIDE_FIXTURE = Path(__file__).parent / "fixtures" / "guides" / "feedback-loops.guide.json"


class FakeRunner:
    provider_id = "fake"
    executable = True

    def is_available(self):
        return True

    def build_invocation(self, model, plan, prompt_path):
        return Invocation(argv=[sys.executable, str(FAKE)])

    def parse_response(self, stdout):
        return ProviderResponse(text=stdout, metadata={})


def _start_server(tmp_path, monkeypatch, web_dist=None, catalog=None, plan=None):
    monkeypatch.setenv("FAKE_STDOUT", "GENERATED\n")
    register_runner(FakeRunner())
    runs = RunStore(tmp_path)
    # Explicit legacy: server suite exercises Markdown response paths and finalize.
    runs.create_run("t", content_contract=ContentContract.legacy_markdown())
    p = runs.stage_paths("t", "draft").prompt_path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("PROMPT", encoding="utf-8")
    # A guide-contract topic alongside the legacy one, for validation/waiver tests.
    runs.create_run("g", content_contract=ContentContract.interactive_guide_v1())
    gp = runs.stage_paths("g", "draft").prompt_path
    gp.parent.mkdir(parents=True, exist_ok=True)
    gp.write_text("PROMPT", encoding="utf-8")
    topics_dir = tmp_path / "topics"
    topics_dir.mkdir(parents=True, exist_ok=True)
    (topics_dir / "t.toml").write_text(
        'schema_version = 1\nid = "t"\ntitle = "Test Topic"\n', encoding="utf-8"
    )
    (topics_dir / "g.toml").write_text(
        'schema_version = 1\nid = "g"\ntitle = "Guide Topic"\n', encoding="utf-8"
    )
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir(parents=True, exist_ok=True)
    (profiles_dir / "p.toml").write_text(
        'schema_version = 1\nid = "p"\ntarget_learner = "team cohort"\n',
        encoding="utf-8",
    )
    if catalog is None:
        catalog = parse_model_catalog({"providers": [{"id": "fake", "models": [{"id": "m"}]}]})
    if plan is None:
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
        config=StaticConfigSource(catalog, plan),
        topics=TopicStore(tmp_path),
        profiles=ProfileStore(tmp_path),
        on_shutdown=lambda: None,
        web_dist=web_dist,
    )
    srv = build_server(context)
    import threading

    threading.Thread(target=srv.serve_forever, daemon=True).start()
    worker.start()
    return srv, worker, context


@pytest.fixture
def server(tmp_path, monkeypatch):
    srv, worker, _context = _start_server(tmp_path, monkeypatch)
    yield srv.server_port
    worker.stop()
    srv.shutdown()


@pytest.fixture
def server_with_context(tmp_path, monkeypatch):
    """Like ``server``, but also exposes the live DaemonContext so a test can
    mutate its fields (e.g. corrupt ``token`` to force a serialization
    failure in a specific route) without reaching into private handler
    internals."""
    srv, worker, context = _start_server(tmp_path, monkeypatch)
    yield srv.server_port, context
    worker.stop()
    srv.shutdown()


@pytest.fixture
def config_server(tmp_path, monkeypatch):
    catalog = parse_model_catalog(
        {
            "providers": [
                {"id": "manual"},
                {
                    "id": "fake",
                    "models": [
                        {"id": "m", "quality": "fast"},
                        {"id": "strong-m", "quality": "strong"},
                    ],
                },
                {"id": "nope"},
            ],
            "presets": [
                {
                    "id": "test-preset",
                    "label": "Test preset",
                    "description": "Preset used by payload tests.",
                    "stages": {
                        "fake": {
                            "profile": {"model": "m"},
                            "spec": {"model": "strong-m", "effort": "high"},
                            "outline": {"model": "strong-m"},
                            "draft": {"model": "strong-m"},
                            "qa": {"model": "m"},
                            "repair": {"model": "strong-m"},
                            "audit": {"model": "strong-m"},
                        }
                    },
                }
            ],
        }
    )
    plan = parse_model_plan(
        {
            "provider": "fake",
            "stages": {
                "outline": {"model": "m"},
                "draft": {"model": "m"},
            },
        },
        catalog,
    )
    srv, worker, _context = _start_server(tmp_path, monkeypatch, catalog=catalog, plan=plan)
    yield srv.server_port
    worker.stop()
    srv.shutdown()


@pytest.fixture
def ui_server(tmp_path, monkeypatch):
    dist = tmp_path / "webdist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>cockpit</html>", encoding="utf-8")
    (dist / "assets" / "app-abc.js").write_text("js", encoding="utf-8")
    srv, worker, _context = _start_server(tmp_path, monkeypatch, web_dist=dist)
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


def test_build_server_binds_loopback_without_reverse_dns(tmp_path, monkeypatch):
    # HTTPServer.server_bind resolves the bound address with socket.getfqdn(),
    # a reverse-DNS lookup that can stall for many seconds on macOS CI
    # runners and push daemon startup past the client's readiness timeout.
    # The daemon binds loopback only, so binding must never touch DNS.
    import socket

    def _no_reverse_dns(name=""):
        raise AssertionError("server_bind must not call socket.getfqdn")

    monkeypatch.setattr(socket, "getfqdn", _no_reverse_dns)
    srv, worker, _context = _start_server(tmp_path, monkeypatch)
    try:
        assert srv.server_address[0] == "127.0.0.1"
        assert srv.server_name == "127.0.0.1"
        assert srv.server_port == srv.server_address[1]
        status, _ = _req(srv.server_port, "GET", "/v1/health")
        assert status == 200
    finally:
        worker.stop()
        srv.shutdown()


def test_health_requires_token(server):
    status, _ = _req(server, "GET", "/v1/health", token=None)
    assert status == 401


def test_health_ok(server):
    status, body = _req(server, "GET", "/v1/health")
    assert status == 200
    assert body["version"] == "0.1.0"
    # Freshness is always present; the test server's tmp dist is not the
    # repo dev-checkout fallback, so it reports ok/None.
    assert body["cockpit_build"] == {"status": "ok", "build_id": None}


def test_health_reports_stale_dev_checkout(tmp_path, monkeypatch):
    from education_pipeline.daemon import static as static_mod

    web = tmp_path / "web"
    (web / "src").mkdir(parents=True)
    (web / "src" / "App.tsx").write_text("export {}", encoding="utf-8")
    (web / "dist").mkdir()
    (web / "dist" / "index.html").write_text(
        "<!doctype html><html><body><div id='root'></div></body></html>",
        encoding="utf-8",
    )
    import os as _os

    _os.utime(web / "dist" / "index.html", ns=(1_000, 1_000))
    _os.utime(web / "src" / "App.tsx", ns=(2_000, 2_000))
    monkeypatch.setattr(static_mod, "_REPO_WEB_DIST", web / "dist")
    monkeypatch.delenv("EP_WEB_DIST", raising=False)

    srv, worker, _context = _start_server(tmp_path, monkeypatch, web_dist=web / "dist")
    try:
        status, body = _req(srv.server_port, "GET", "/v1/health")
        assert status == 200
        assert body["cockpit_build"]["status"] == "stale"
        assert body["cockpit_build"]["build_id"] == "1000"
        status, html, _headers = _raw_get(srv.server_port, "/")
        assert status == 200
        assert b'id="ep-cockpit-build-banner"' in html
        assert b"education-pipeline ui --rebuild" in html
    finally:
        worker.stop()
        srv.shutdown()


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
    assert payload["error"]["code"] == "invalid_request"
    # server survives: a well-formed request still succeeds afterward
    status, health = _req(server, "GET", "/v1/health")
    assert status == 200


def test_non_numeric_content_length_returns_400(server):
    status, payload = _raw_post(server, "/v1/jobs", b"{}", "notanumber")
    assert status == 400
    assert payload["error"]["code"] == "invalid_request"


def test_oversized_content_length_returns_400(server):
    # Declare a body far exceeding the server's cap; the server must reject
    # based on the header alone (job POST bodies are tiny), not attempt to
    # read gigabytes into memory.
    oversized = 2 * 1024 * 1024  # 2 MiB > the 1 MiB cap
    status, payload = _raw_post(server, "/v1/jobs", b"{}", str(oversized))
    assert status == 400
    assert payload["error"]["code"] == "invalid_request"
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
    # cardinality/shape: exactly the two fixture topics, each listed once —
    # this is the only assertion anywhere on GET /v1/topics's shape.
    assert {i["id"] for i in body["topics"]} == {"g", "t"}
    assert len(body["topics"]) == 2
    entry = next(item for item in body["topics"] if item["id"] == "t")
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
    assert body["profiles"] == [{"id": "p", "attached_topic_count": 0}]
    status, body = _req(server, "GET", "/v1/profiles/p")
    assert status == 200
    assert set(body) == {
        "id",
        "parsed",
        "sensitivity",
        "content_sha256",
        "warnings",
        "attached_topic_count",
    }
    assert body["parsed"]["target_learner"] == "team cohort"
    assert body["sensitivity"]["target_learner"] == "high"
    assert body["attached_topic_count"] == 0
    status, body = _req(server, "GET", "/v1/profiles/nope")
    assert status == 404


def test_runs_list(server):
    status, body = _req(server, "GET", "/v1/runs")
    assert status == 200
    # RunStore.list_run_ids returns tuple(sorted(ids)); assert the exact
    # ordering the API promises, not just the set of ids.
    assert body["runs"] == ["g", "t"]


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


def test_run_status_reports_findings_by_stage(server, tmp_path):
    """The draft validations summary breaks blocking-or-error findings down
    by the stage responsible for fixing them (Task 2.1's Finding.stage),
    so the cockpit can badge/link each stage with actionable work."""
    runs = RunStore(tmp_path)
    guide = json.loads(GUIDE_FIXTURE.read_text(encoding="utf-8"))
    guide["modules"][0]["sections"][0]["blocks"][0]["markdown"] += " TODO"
    draft = runs.stage_paths("g", "draft")
    draft.approved_path.write_text(json.dumps(guide), encoding="utf-8")
    report_path = runs.validate_run("g", "draft")
    report_payload = json.loads(report_path.read_text(encoding="utf-8"))
    finding = next(
        item for item in report_payload["findings"] if item["blocking"] or item["severity"] == "error"
    )

    status, body = _req(server, "GET", "/v1/runs/g")
    assert status == 200
    summary = body["validations"]["draft"]
    assert "findings_by_stage" in summary
    assert all(isinstance(v, int) for v in summary["findings_by_stage"].values())
    assert summary["findings_by_stage"].get(finding["stage"], 0) >= 1


def test_run_status_reports_effective_blocking_after_waivers(server, tmp_path):
    """A run whose every blocker carries an accepted waiver has an open gate
    and no actionable work left, but ``_validation_summary`` used to report
    the raw on-disk blocking count -- waiver-blind -- so the cockpit badge
    and re-run button stayed lit even though there was nothing left to do.
    ``effective_blocking`` must reflect the post-waiver reality while the
    raw ``blocking`` count (and the stage breakdown) still shows the true
    on-disk finding so the panel can keep listing it as waived."""
    runs = RunStore(tmp_path)
    guide = json.loads(GUIDE_FIXTURE.read_text(encoding="utf-8"))
    guide["modules"][0]["sections"][0]["blocks"][0]["markdown"] += " TODO"
    draft = runs.stage_paths("g", "draft")
    draft.approved_path.write_text(json.dumps(guide), encoding="utf-8")
    report_path = runs.validate_run("g", "draft")
    report_payload = json.loads(report_path.read_text(encoding="utf-8"))
    finding = next(item for item in report_payload["findings"] if item["waivable"])

    status, body = _req(
        server,
        "POST",
        "/v1/runs/g/validation/draft/waivers",
        body={
            "finding_id": finding["id"],
            "guide_sha256": report_payload["guide_sha256"],
            "reason": "accepted",
        },
    )
    assert status == 200

    status, body = _req(server, "GET", "/v1/runs/g")
    assert status == 200
    summary = body["validations"]["draft"]
    assert summary["blocking"] > 0
    assert summary["effective_blocking"] == 0
    # The stage responsible for the now-waived blocker must net out of the
    # badge breakdown too -- a fully-waived stage has no actionable work
    # left, so findings_by_stage should agree with effective_blocking == 0
    # instead of still showing the raw pre-waiver count.
    assert summary["findings_by_stage"] == {}


def test_run_status_effective_blocking_falls_back_when_report_is_stale(server, tmp_path):
    """``_validation_summary`` (read_api.py) only trusts a recomputed
    ``gate_result`` when ``report_state`` says the on-disk report is
    "current" -- otherwise it would pair a stale on-disk report body with a
    freshly recomputed gate, and the two could disagree (the exact trap
    Task 3.1's review caught in the CLI's ``_cmd_report``).

    This isolates that guard from the (separate) hash-bound staleness that
    ``apply_waivers`` already provides for free: the approved draft source
    is left untouched here -- only the on-disk report's recorded
    ``guide_sha256`` is corrupted after waiving, so ``report_state`` flips
    to "stale" while a freshly recomputed ``gate_result`` (which reads the
    approved source, not the report file) would still consider the waiver
    valid and *not* stale. Without the ``state == "current"`` guard, the
    recomputed gate would still be trusted and net the badge away even
    though the on-disk report -- the thing the ``blocking``/
    ``findings_by_stage`` counts above are drawn from -- no longer agrees
    with it."""
    runs = RunStore(tmp_path)
    guide = json.loads(GUIDE_FIXTURE.read_text(encoding="utf-8"))
    guide["modules"][0]["sections"][0]["blocks"][0]["markdown"] += " TODO"
    draft = runs.stage_paths("g", "draft")
    draft.approved_path.write_text(json.dumps(guide), encoding="utf-8")
    report_path = runs.validate_run("g", "draft")
    report_payload = json.loads(report_path.read_text(encoding="utf-8"))
    finding = next(item for item in report_payload["findings"] if item["waivable"])
    assert finding["blocking"] or finding["severity"] == "error"

    status, body = _req(
        server,
        "POST",
        "/v1/runs/g/validation/draft/waivers",
        body={
            "finding_id": finding["id"],
            "guide_sha256": report_payload["guide_sha256"],
            "reason": "accepted",
        },
    )
    assert status == 200

    # Corrupt only the on-disk report's recorded hash -- not the approved
    # source. report_state now reads "stale" (recorded hash mismatch), but
    # a fresh gate_result recompute (from the unchanged approved source)
    # would still match the waiver's guide_sha256 and report not-stale.
    corrupted = dict(report_payload)
    corrupted["guide_sha256"] = "0" * 64
    report_path.write_text(json.dumps(corrupted), encoding="utf-8")

    status, body = _req(server, "GET", "/v1/runs/g")
    assert status == 200
    summary = body["validations"]["draft"]
    assert summary["state"] == "stale"
    assert summary["blocking"] > 0
    assert summary["effective_blocking"] == summary["blocking"]
    assert summary["findings_by_stage"].get(finding["stage"], 0) >= 1


def test_run_status_effective_blocking_matches_blocking_without_waivers(server, tmp_path):
    """Perf fix: ``_validation_summary`` skips the ``gate_result`` recompute
    (a full parse + normalize + static-checks pass, doubled again for
    ``final``) when the topic has no waiver set at all -- overwhelmingly the
    common case, since ``apply_waivers`` with ``waiver_set=None`` always
    returns ``effective_blocking = len(blocking findings)``, exactly
    ``counts["blocking"]`` for a "current" report. This pins that the
    short-circuit is semantically a no-op: with no waivers recorded,
    ``effective_blocking`` must still equal the raw ``blocking`` count."""
    runs = RunStore(tmp_path)
    guide = json.loads(GUIDE_FIXTURE.read_text(encoding="utf-8"))
    guide["modules"][0]["sections"][0]["blocks"][0]["markdown"] += " TODO"
    draft = runs.stage_paths("g", "draft")
    draft.approved_path.write_text(json.dumps(guide), encoding="utf-8")
    runs.validate_run("g", "draft")

    assert runs.load_waiver_set("g") is None

    status, body = _req(server, "GET", "/v1/runs/g")
    assert status == 200
    summary = body["validations"]["draft"]
    assert summary["state"] == "current"
    assert summary["blocking"] > 0
    assert summary["effective_blocking"] == summary["blocking"]


def test_run_status_degrades_gracefully_when_waivers_file_is_malformed(server, tmp_path):
    """``RunStore._load_waiver_set`` (runs.py) raises ``ConfigError`` on a
    malformed waivers file -- it only returns ``None`` to mean "no file
    exists". ``_validation_summary`` (read_api.py) calls
    ``runs.load_waiver_set(topic_id)`` to decide whether the ``gate_result``
    recompute is worth paying for, and that call must stay inside the same
    ``try/except ConfigError`` guard as the recompute itself: otherwise a
    single corrupt waivers file turns a graceful degrade-to-raw-counts (the
    behavior before the short-circuit) into a 400 that takes down
    ``GET /v1/runs/{topic}`` -- the endpoint the cockpit polls every 5s."""
    runs = RunStore(tmp_path)
    guide = json.loads(GUIDE_FIXTURE.read_text(encoding="utf-8"))
    guide["modules"][0]["sections"][0]["blocks"][0]["markdown"] += " TODO"
    draft = runs.stage_paths("g", "draft")
    draft.approved_path.write_text(json.dumps(guide), encoding="utf-8")
    runs.validate_run("g", "draft")

    # Hand-corrupt the waivers file directly, bypassing the write API that
    # would normally validate it -- this is what a malformed/partially
    # written file on disk looks like.
    runs.waivers_path("g").write_text(
        json.dumps({"schema_version": 99, "guide_sha256": "x", "waivers": []}),
        encoding="utf-8",
    )

    status, body = _req(server, "GET", "/v1/runs/g")
    assert status == 200
    summary = body["validations"]["draft"]
    assert summary["effective_blocking"] == summary["blocking"]


def test_run_status_degrades_gracefully_when_waivers_file_is_malformed_at_finalize_ready(
    server, tmp_path
):
    """The test above only reaches ``_validation_summary``'s guard -- a
    draft-only fixture can never reach ``run_status`` -> ``_next_action_guide_v1``
    (runs.py), which requires an approved repair *and* a current final
    report before its own, previously-unguarded
    ``self._load_waiver_set(topic_id)`` call at runs.py:565. Commit 18804c0
    claimed to fix "malformed waivers file in run status" but only guarded
    the summary path, leaving this one to raise ``ConfigError`` -> 400
    straight out of ``GET /v1/runs/{topic}``. Drive "g" all the way to
    finalize-ready so this test actually exercises that call."""
    runs = RunStore(tmp_path)
    guide = json.loads(GUIDE_FIXTURE.read_text(encoding="utf-8"))
    guide["modules"][0]["sections"][0]["blocks"][0]["markdown"] += " TODO"
    guide_text = json.dumps(guide)
    # ``_next_action_guide_v1`` derives the next action from manifest-recorded
    # stage status (spec/outline/draft/qa/repair approval events), not just
    # from approved_path's existence on disk -- so this must drive the real
    # prompt/response/approve flow through every stage, not just drop files
    # into approved_path. The server fixture pre-seeds "g" with a stub draft
    # prompt (for the file's other, draft-only tests); remove it first so
    # ``_drive_guide_to_finalize_ready``'s own ``write_draft_prompt`` call
    # doesn't collide with it.
    runs.stage_paths("g", "draft").prompt_path.unlink()
    test_runs._drive_guide_to_finalize_ready(
        runs, "g", draft_body=guide_text, repair_body=guide_text
    )
    report = json.loads(runs.final_report_path("g").read_text(encoding="utf-8"))
    assert report["summary"]["blocking"] > 0

    # Hand-corrupt the waivers file directly, bypassing the write API that
    # would normally validate it -- this is what a malformed/partially
    # written file on disk looks like.
    runs.waivers_path("g").write_text(
        json.dumps({"schema_version": 99, "guide_sha256": "x", "waivers": []}),
        encoding="utf-8",
    )

    status, body = _req(server, "GET", "/v1/runs/g")
    assert status == 200
    # A malformed waivers file must degrade to the raw (un-waived) gate --
    # not 400 -- so next_action still reflects real gate state (a real
    # blocking finding remains, so the run cannot finalize).
    assert body["next_action"]["stage"] == "repair"
    assert body["next_action"]["action"] == "resolve_findings"

    # The one-run corruption must not take down the topics list either --
    # /v1/topics calls run_status_payload for every topic, unguarded.
    status, body = _req(server, "GET", "/v1/topics")
    assert status == 200
    assert {i["id"] for i in body["topics"]} == {"g", "t"}


def test_stage_content_returns_prompt_and_nulls(server):
    status, body = _req(server, "GET", "/v1/runs/t/stages/draft")
    assert status == 200
    assert body == {
        "topic_id": "t",
        "stage": "draft",
        "prompt": "PROMPT",
        "response": None,
        "approved": None,
        "response_sha256": None,
        "content_type": "text/markdown",
    }


def test_stage_content_includes_response_sha256(server):
    import hashlib

    status, body = _req(server, "GET", "/v1/runs/t/stages/draft")
    assert status == 200
    assert body["response_sha256"] is None

    _req(server, "POST", "/v1/runs/t/stages/draft/response", body={"text": "BODY"})
    status, body = _req(server, "GET", "/v1/runs/t/stages/draft")
    assert status == 200
    assert body["response_sha256"] == hashlib.sha256(b"BODY").hexdigest()


def test_stage_content_bad_stage_is_400(server):
    status, body = _req(server, "GET", "/v1/runs/t/stages/banana")
    assert status == 400
    assert body["error"]["code"] == "invalid_request"


def test_manifest_endpoint(server):
    status, body = _req(server, "GET", "/v1/runs/t/manifest")
    assert status == 200
    assert body["topic_id"] == "t"
    assert isinstance(body["events"], list)


def _raw_get(port, path, host=None, token=None):
    conn = http.client.HTTPConnection("127.0.0.1", port)
    if host is None and token is None:
        conn.request("GET", path)
    else:
        conn.putrequest("GET", path, skip_host=True)
        conn.putheader("Host", host if host is not None else "127.0.0.1")
        if token is not None:
            conn.putheader("X-EP-Token", token)
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


def test_cockpit_html_carries_csp_header(ui_server):
    status, _, headers = _raw_get(ui_server, "/")
    assert status == 200
    csp = headers.get("Content-Security-Policy", "")
    assert "default-src 'self'" in csp
    assert "object-src 'none'" in csp


def test_asset_response_has_no_csp_header(ui_server):
    status, _, headers = _raw_get(ui_server, "/assets/app-abc.js")
    assert status == 200
    assert "Content-Security-Policy" not in headers


def test_static_get_race_returns_500_not_dropped_connection(ui_server, tmp_path):
    """Regression test for the defect class the do_GET catch-all was meant to
    close: previously only ``_api_get()`` was wrapped, so a static file that
    vanishes between ``resolve_static`` and ``read_bytes`` (the ordinary
    "npm run build while the page is open" race) raised FileNotFoundError
    straight through do_GET and dropped the connection with no status line
    at all. Simulate the race by having resolve_static point at a file that
    no longer exists.

    Uses a nested ``pytest.MonkeyPatch.context()`` rather than the function-
    scoped ``monkeypatch`` fixture: ``ui_server`` is built by ``_start_server``,
    which patches env vars (e.g. FAKE_STDOUT) through that SAME fixture
    instance, so calling ``monkeypatch.undo()`` here to restore
    ``resolve_static`` mid-test would also unwind the fixture's own setup --
    harmless today, but a landmine the moment a later assertion in this test
    depends on that env patch still being in place.
    """
    from education_pipeline.daemon import server as server_mod
    from education_pipeline.daemon.static import StaticFile

    missing = tmp_path / "gone.js"
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            server_mod,
            "resolve_static",
            lambda dist, path: StaticFile(
                path=missing,
                content_type="text/javascript; charset=utf-8",
                cache_control="no-store",
            ),
        )
        status, body, _ = _raw_get(ui_server, "/assets/app-abc.js")
        body = json.loads(body or b"{}")
        assert status == 500
        assert body["error"]["code"] == "internal"
    # the context manager exit restores resolve_static (and only that); the
    # connection/server survives: a subsequent request still succeeds
    status, body, _ = _raw_get(ui_server, "/assets/app-abc.js")
    assert status == 200


def test_session_endpoint_survives_unexpected_exception(server_with_context):
    """/v1/session is handled entirely outside _api_get(); it must still be
    covered by the last-resort catch-all so an unexpected failure comes back
    as a diagnosable 500 rather than a dropped connection. Force the failure
    locally (an unserializable token breaks json.dumps inside _send for this
    route only) rather than patching the global json module, which would
    affect unrelated background threads (e.g. the job worker) too.

    Uses a nested ``pytest.MonkeyPatch.context()`` rather than the function-
    scoped ``monkeypatch`` fixture: ``server_with_context`` is built by
    ``_start_server``, which patches env vars through that SAME fixture
    instance, so ``monkeypatch.undo()`` here would also unwind the fixture's
    own setup, not just the ``token`` patch -- harmless today, but a landmine
    the moment a later assertion needs that env patch still in place.
    """
    port, context = server_with_context

    class _Unserializable:
        pass

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(context, "token", _Unserializable())
        status, body = _req(port, "GET", "/v1/session", token=None)
        assert status == 500
        assert body["error"]["code"] == "internal"
    # the context manager exit restores context.token (and only that); the
    # connection/server survives: a subsequent request still succeeds
    status, body = _req(port, "GET", "/v1/session", token=None)
    assert status == 200
    assert body["token"] == "secret-token"


def test_do_put_unprocessable_error_returns_422_not_500(server, monkeypatch):
    """do_POST already maps write_api.UnprocessableError -> 422, but do_PUT
    had no matching arm and fell through to the last-resort 500 handler.
    Nothing raises UnprocessableError on PUT today, so force it via
    monkeypatch on a real PUT route (edit_response) to pin the status for
    whenever a future PUT path does raise it."""
    from education_pipeline.daemon import server as server_mod

    def _raise(*args, **kwargs):
        raise server_mod.write_api.UnprocessableError("some_code", "not processable")

    monkeypatch.setattr(server_mod.write_api, "edit_response", _raise)
    status, body = _req(
        server,
        "PUT",
        "/v1/runs/t/stages/draft/response",
        body={"text": "x", "base_sha256": "0" * 64},
    )
    assert status == 422
    assert body["error"]["code"] == "some_code"


def test_do_post_guide_document_error_from_finalize_returns_422_not_500(server, monkeypatch):
    """finalize_run/export_run call normalize_guide/assemble_guide_document,
    which can raise GuideDocumentError or ContractError -- both ValueError
    subclasses, neither a ConfigError. Before this fix that fault escaped the
    do_POST except chain entirely and became a plausible 500 internal; it
    must map to the same 422 guide_not_renderable used at /v1/guide-preview."""
    from education_pipeline.daemon import server as server_mod
    from education_pipeline.guides import GuideDocumentError

    def _raise(*args, **kwargs):
        raise GuideDocumentError("guide cannot be rendered")

    monkeypatch.setattr(server_mod.write_api, "finalize_run", _raise)
    status, body = _req(server, "POST", "/v1/runs/t/finalize", body={})
    assert status == 422
    assert body["error"]["code"] == "guide_not_renderable"


def test_do_post_contract_error_from_export_returns_422_not_500(server, monkeypatch):
    """Same fault class as above via ContractError (also raised from the
    normalize/assemble path), exercised on a different POST route
    (export_run) to confirm the mapping isn't route-specific."""
    from education_pipeline.daemon import server as server_mod
    from education_pipeline.guides import ContractError

    def _raise(*args, **kwargs):
        raise ContractError("guide contract mismatch")

    monkeypatch.setattr(server_mod.write_api, "export_run", _raise)
    status, body = _req(server, "POST", "/v1/runs/t/export", body={})
    assert status == 422
    assert body["error"]["code"] == "guide_not_renderable"


def test_do_post_guide_parse_error_from_finalize_returns_422_not_500(server, monkeypatch):
    """normalize_guide -- the very function named in the comment above the
    do_POST (GuideDocumentError, ContractError) except arm -- actually raises
    GuideParseError, not those two. Before this fix GuideParseError was
    missing from that tuple, so it fell through to a plausible-looking 500
    internal exactly like the faults the tuple was added to catch."""
    from education_pipeline.daemon import server as server_mod
    from education_pipeline.guides import GuideParseError
    from education_pipeline.guides.parse import ParseDiagnostic

    def _raise(*args, **kwargs):
        raise GuideParseError(
            (ParseDiagnostic(code="bad_shape", path="$", message="guide cannot be parsed"),)
        )

    monkeypatch.setattr(server_mod.write_api, "finalize_run", _raise)
    status, body = _req(server, "POST", "/v1/runs/t/finalize", body={})
    assert status == 422
    assert body["error"]["code"] == "guide_not_renderable"


def test_do_put_guide_document_error_returns_422_not_500(server, monkeypatch):
    """Same coherent-taxonomy requirement on the PUT verb: a GuideDocumentError
    escaping a PUT route (e.g. a future update_run_plan-adjacent path) must
    not fall through do_PUT's except chain into the last-resort 500."""
    from education_pipeline.daemon import server as server_mod
    from education_pipeline.guides import GuideDocumentError

    def _raise(*args, **kwargs):
        raise GuideDocumentError("guide cannot be rendered")

    monkeypatch.setattr(server_mod.write_api, "edit_response", _raise)
    status, body = _req(
        server,
        "PUT",
        "/v1/runs/t/stages/draft/response",
        body={"text": "x", "base_sha256": "0" * 64},
    )
    assert status == 422
    assert body["error"]["code"] == "guide_not_renderable"


def test_do_put_guide_parse_error_returns_422_not_500(server, monkeypatch):
    """Same GuideParseError coherent-taxonomy requirement on the PUT verb,
    mirroring test_do_post_guide_parse_error_from_finalize_returns_422_not_500."""
    from education_pipeline.daemon import server as server_mod
    from education_pipeline.guides import GuideParseError
    from education_pipeline.guides.parse import ParseDiagnostic

    def _raise(*args, **kwargs):
        raise GuideParseError(
            (ParseDiagnostic(code="bad_shape", path="$", message="guide cannot be parsed"),)
        )

    monkeypatch.setattr(server_mod.write_api, "edit_response", _raise)
    status, body = _req(
        server,
        "PUT",
        "/v1/runs/t/stages/draft/response",
        body={"text": "x", "base_sha256": "0" * 64},
    )
    assert status == 422
    assert body["error"]["code"] == "guide_not_renderable"


def test_json_api_response_has_no_csp_header(server):
    status, body = _req(server, "GET", "/v1/health")
    assert status == 200
    # confirm via the raw header-capturing helper too
    status, _, headers = _raw_get(server, "/v1/health", token="secret-token")
    assert status == 200
    assert "Content-Security-Policy" not in headers


def test_no_dist_returns_503(server):
    status, body = _req(server, "GET", "/", token=None)
    assert status == 503
    assert body["error"]["code"] == "web_assets_missing"


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


def test_blueprints_endpoint_lists_registry(server):
    status, body = _req(server, "GET", "/v1/blueprints")
    assert status == 200
    ids = [entry["id"] for entry in body["blueprints"]]
    assert ids == [
        "conceptual-foundations",
        "procedural-skill",
        "casebook",
        "quantitative-scientific",
        "exam-preparation",
        "project-based",
    ]
    first = body["blueprints"][0]
    assert set(first) == {
        "id",
        "title",
        "summary",
        "when_to_use",
        "required_interactions",
        "default_difficulty",
    }
    assert body["recommendation"] is None
    assert body["topic_blueprint"] is None


def test_blueprints_endpoint_recommends_for_topic(server):
    status, body = _req(server, "GET", "/v1/blueprints?topic=g")
    assert status == 200
    assert body["recommendation"]["id"] == "conceptual-foundations"
    assert body["recommendation"]["rationale"].strip()
    assert body["topic_blueprint"] is None


def test_blueprints_endpoint_unknown_topic_is_404(server):
    status, _ = _req(server, "GET", "/v1/blueprints?topic=missing-topic")
    assert status == 404


def test_blueprints_recommend_route_works_before_the_topic_exists(server):
    """The wizard recommends from in-progress fields, pre-topic-creation."""

    status, body = _req(
        server,
        "POST",
        "/v1/blueprints/recommend",
        body={"id": "draft-topic", "title": "Certification exam readiness"},
    )
    assert status == 200
    assert body["recommendation"]["id"] == "exam-preparation"
    assert body["recommendation"]["rationale"].strip()
    assert [entry["id"] for entry in body["blueprints"]][0] == "conceptual-foundations"
    assert body["topic_blueprint"] is None

    # TOML mode carries the topic's own blueprint field through.
    status, body = _req(
        server,
        "POST",
        "/v1/blueprints/recommend",
        body={"toml": 'id = "t2"\ntitle = "Anything"\nblueprint = "casebook"\n'},
    )
    assert status == 200
    assert body["topic_blueprint"] == "casebook"

    status, _ = _req(server, "POST", "/v1/blueprints/recommend", body={"toml": "not = toml ="})
    assert status == 400

    status, _ = _req(server, "POST", "/v1/blueprints/recommend", body={"id": "x"})
    assert status == 400


def test_create_topic_accepts_blueprint_and_time_budget(server):
    status, _ = _req(
        server,
        "POST",
        "/v1/topics",
        body={
            "id": "budgeted",
            "title": "Budgeted Topic",
            "blueprint": "casebook",
            "time_budget_minutes": 90,
        },
    )
    assert status == 200
    status, body = _req(server, "GET", "/v1/topics/budgeted")
    assert status == 200
    assert 'blueprint = "casebook"' in body["toml"]
    assert "time_budget_minutes = 90" in body["toml"]

    status, _ = _req(
        server,
        "POST",
        "/v1/topics",
        body={"id": "bad-budget", "title": "X", "time_budget_minutes": 2},
    )
    assert status == 400


def test_run_status_payload_includes_blueprint(server):
    # Run "g" was created before its topic existed, so it has no record.
    status, body = _req(server, "GET", "/v1/runs/g")
    assert status == 200
    assert body["blueprint"] is None

    # An explicit choice via the advance body records the blueprint.
    status, body = _req(
        server, "POST", "/v1/runs/g/advance", body={"blueprint": "casebook"}
    )
    assert status == 200
    assert body["status"]["blueprint"] == {"id": "casebook", "source": "user"}


def test_advance_rejects_unknown_blueprint(server):
    status, body = _req(
        server, "POST", "/v1/runs/g/advance", body={"blueprint": "socratic-method"}
    )
    assert status == 400
    assert "unregistered blueprint" in body["error"]["message"]


def _drive_guide_through_qa_http(context, topic_id="scoped-topic"):
    topic_toml = test_runs.TOPIC_TOML.replace(
        'id = "systems-thinking"', f'id = "{topic_id}"'
    )
    TopicStore(context.root).save_topic_toml(topic_id, topic_toml)
    runs = context.runs
    runs.create_run(topic_id)
    test_runs._drive_guide_through_qa(runs, topic_id)
    return runs


def test_advance_with_repair_module_writes_scoped_prompt(server_with_context):
    port, context = server_with_context
    runs = _drive_guide_through_qa_http(context)

    status, body = _req(
        port,
        "POST",
        "/v1/runs/scoped-topic/advance",
        body={"repair_module": "loop-basics"},
    )

    assert status == 200
    assert body["performed"] == "write_prompt"
    assert runs.repair_scope("scoped-topic") == "loop-basics"


def test_advance_with_unknown_repair_module_is_400(server_with_context):
    port, context = server_with_context
    _drive_guide_through_qa_http(context)

    status, body = _req(
        port,
        "POST",
        "/v1/runs/scoped-topic/advance",
        body={"repair_module": "no-such-module"},
    )

    assert status == 400
    assert "no-such-module" in body["error"]["message"]


def test_repair_modules_payload_lists_candidates_with_finding_counts(
    server_with_context,
):
    port, context = server_with_context
    _drive_guide_through_qa_http(context)

    status, body = _req(port, "GET", "/v1/runs/scoped-topic/repair/modules")

    assert status == 200
    modules = {entry["id"]: entry for entry in body["modules"]}
    assert set(modules) == {"loop-basics", "intervention-practice"}
    assert modules["loop-basics"]["title"]
    assert isinstance(modules["loop-basics"]["open_findings"], int)
    assert body["repair_scope"] is None

    _req(
        port,
        "POST",
        "/v1/runs/scoped-topic/advance",
        body={"repair_module": "loop-basics"},
    )
    status, body = _req(port, "GET", "/v1/runs/scoped-topic/repair/modules")
    assert status == 200
    assert body["repair_scope"] == {"module_id": "loop-basics"}


def test_repair_stage_content_carries_the_scope(server_with_context):
    port, context = server_with_context
    _drive_guide_through_qa_http(context)
    _req(
        port,
        "POST",
        "/v1/runs/scoped-topic/advance",
        body={"repair_module": "loop-basics"},
    )

    status, body = _req(port, "GET", "/v1/runs/scoped-topic/stages/repair")

    assert status == 200
    assert body["repair_scope"] == {"module_id": "loop-basics"}

    status, body = _req(port, "GET", "/v1/runs/scoped-topic/stages/draft")
    assert status == 200
    assert "repair_scope" not in body


def _ready_audit_http_run(context, topic_id="audit-topic"):
    topic_toml = test_runs.TOPIC_TOML.replace(
        'id = "systems-thinking"', f'id = "{topic_id}"'
    )
    TopicStore(context.root).save_topic_toml(topic_id, topic_toml)
    profiles = ProfileStore(context.root)
    profile_id = f"{topic_id}-profile"
    profile_toml = test_runs.PERSONALIZED_PROFILE_TOML.replace(
        'id = "personalized-profile"', f'id = "{profile_id}"'
    )
    profiles.save_profile_toml(profile_id, profile_toml)
    profiles.attach_profile_to_topic(profile_id, topic_id)
    context.runs.create_run(topic_id)
    runs = context.runs
    test_runs._drive_profiled_guide_to_finalize_ready(runs, topic_id)
    return runs, topic_id


def _audit_response_with_warning(runs, topic_id):
    response = json.loads(test_runs._valid_personalization_audit_response(runs, topic_id))
    response["goals"][0]["verdict"] = "weak"
    return json.dumps(response)


def test_personalization_aggregate_projects_all_cockpit_states_without_artifact_paths(
    server_with_context,
):
    port, context = server_with_context

    status, no_profile = _req(port, "GET", "/v1/runs/g/personalization")
    assert status == 200
    assert no_profile == {
        "topic_id": "g",
        "profile": {"state": "not_attached", "id": None},
        "trace": {"state": "missing", "goals": [], "facets": []},
        "audit": {
            "state": "not_run",
            "stage_state": "not_run",
            "available": False,
            "unavailable_reason": "No learner profile is attached.",
            "findings": [],
        },
        "findings": [],
        "export": {"state": "missing"},
    }

    runs, topic_id = _ready_audit_http_run(context, "personalization-state")
    status, trace_only = _req(
        port, "GET", f"/v1/runs/{topic_id}/personalization"
    )
    assert status == 200
    assert trace_only["profile"] == {
        "state": "attached",
        "id": f"{topic_id}-profile",
    }
    assert trace_only["trace"]["state"] == "current"
    assert trace_only["trace"]["facets"] == ["pacing"]
    assert trace_only["trace"]["goals"][0] == {
        "goal_id": "goal-001",
        "goal_text": "Synthetic private goal alpha",
        "status": "served",
        "evidence": [
            {"kind": "module", "id": "loop-basics"},
            {"kind": "outcome", "id": "identify-loop"},
        ],
        "exclusions": [],
    }
    assert trace_only["trace"]["goals"][2] == {
        "goal_id": "goal-003",
        "goal_text": "Synthetic private goal gamma",
        "status": "excluded",
        "evidence": [],
        "exclusions": [{"reason": "Synthetic deferred objective."}],
    }
    assert trace_only["audit"] == {
        "state": "not_run",
        "stage_state": "not_run",
        "available": True,
        "unavailable_reason": None,
        "findings": [],
    }
    assert trace_only["export"] == {"state": "missing"}

    _req(port, "POST", f"/v1/runs/{topic_id}/audit")
    private_narrative = "PLANTED_UNVALIDATED_AUDIT_NARRATIVE"
    response = json.loads(_audit_response_with_warning(runs, topic_id))
    response["overall_summary"] = private_narrative
    _req(
        port,
        "POST",
        f"/v1/runs/{topic_id}/stages/audit/response",
        body={"text": json.dumps(response)},
    )
    _req(port, "POST", f"/v1/runs/{topic_id}/stages/audit/approve")

    status, current_audit = _req(
        port, "GET", f"/v1/runs/{topic_id}/personalization"
    )
    assert status == 200
    assert current_audit["audit"]["state"] == "current"
    assert current_audit["audit"]["stage_state"] == "approved"
    assert current_audit["audit"]["findings"]
    assert all(
        finding["stage"] == "audit"
        and finding["source_stage"] == "repair"
        for finding in current_audit["audit"]["findings"]
    )
    rendered = json.dumps(current_audit)
    assert private_narrative not in rendered
    assert "audit.response.json" not in rendered
    assert "personalization-trace.json" not in rendered

    runs.finalize_run(topic_id)
    runs.export_run(topic_id, format="html")
    assert _req(port, "GET", f"/v1/runs/{topic_id}/personalization")[1][
        "export"
    ] == {"state": "current"}

    served = test_runs._valid_personalization_audit_response(runs, topic_id)
    runs.ingest_response(topic_id, "audit", served, force=True)
    runs.approve_stage(topic_id, "audit", overwrite=True)
    stale_export = _req(
        port, "GET", f"/v1/runs/{topic_id}/personalization"
    )[1]
    assert stale_export["audit"]["state"] == "current"
    assert stale_export["export"] == {"state": "stale"}

    trace_path = runs.personalization_trace_path(topic_id)
    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    trace["active_facets"] = []
    trace_path.write_text(json.dumps(trace), encoding="utf-8")
    stale_audit = _req(
        port, "GET", f"/v1/runs/{topic_id}/personalization"
    )[1]
    assert stale_audit["trace"] == {
        "state": "stale",
        "goals": [],
        "facets": [],
    }
    assert stale_audit["audit"]["state"] == "stale"
    assert stale_audit["audit"]["findings"] == []

    trace_path.write_text("{not json", encoding="utf-8")
    invalid_trace = _req(
        port, "GET", f"/v1/runs/{topic_id}/personalization"
    )[1]
    assert invalid_trace["trace"] == {
        "state": "invalid",
        "goals": [],
        "facets": [],
    }
    assert invalid_trace["audit"]["state"] == "stale"


def test_personalization_aggregate_redacts_malformed_profile_error_path(
    server_with_context,
):
    port, context = server_with_context
    runs, topic_id = _ready_audit_http_run(context, "personalization-invalid-profile")
    snapshot_path = ProfileStore(context.root).topic_profile_snapshot_path(topic_id)
    snapshot_path.write_text("{not toml", encoding="utf-8")

    status, body = _req(port, "GET", f"/v1/runs/{topic_id}/personalization")

    assert status == 400
    assert body == {
        "error": {
            "code": "invalid_request",
            "message": "personalization state is unavailable",
        }
    }
    assert str(snapshot_path) not in json.dumps(body)


def test_personalization_aggregate_combines_deterministic_and_current_audit_findings(
    tmp_path: Path,
):
    context = SimpleNamespace(root=tmp_path, runs=RunStore(tmp_path))
    runs, topic_id = _ready_audit_http_run(context, "personalization-findings")
    repair_path = runs.stage_paths(topic_id, "repair").approved_path
    repair = json.loads(repair_path.read_text(encoding="utf-8"))
    repair["outcomes"][0]["serves_goals"] = []
    repair["modules"][0]["serves_goals"] = ["goal-002"]
    repair_path.write_text(json.dumps(repair), encoding="utf-8")
    runs.validate_run(topic_id, "final")

    not_run = read_api.personalization_payload(runs, topic_id)
    deterministic_ids = {
        finding["id"]
        for finding in not_run["findings"]
        if finding["rule_id"].startswith("personalization.")
    }
    assert deterministic_ids
    assert all(finding["stage"] != "audit" for finding in not_run["findings"])
    assert not_run["audit"]["state"] == "not_run"
    assert not_run["audit"]["findings"] == []

    runs.prepare_personalization_audit(topic_id)
    runs.ingest_response(
        topic_id,
        "audit",
        test_runs._valid_personalization_audit_response(runs, topic_id),
    )
    runs.approve_stage(topic_id, "audit")
    current = read_api.personalization_payload(runs, topic_id)
    audit_ids = {finding["id"] for finding in current["audit"]["findings"]}
    assert audit_ids
    assert {finding["id"] for finding in current["findings"]} == (
        deterministic_ids | audit_ids
    )

    repair["course"]["description"] += " Stale the approved audit generation."
    repair_path.write_text(json.dumps(repair), encoding="utf-8")
    runs.validate_run(topic_id, "final")
    stale = read_api.personalization_payload(runs, topic_id)
    assert stale["audit"]["state"] == "stale"
    assert stale["audit"]["findings"] == []
    assert {finding["id"] for finding in stale["findings"]} == deterministic_ids


def test_personalization_aggregate_does_not_mix_concurrent_trace_and_audit_generations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    context = SimpleNamespace(root=tmp_path, runs=RunStore(tmp_path))
    runs, topic_id = _ready_audit_http_run(context, "personalization-race")
    runs.prepare_personalization_audit(topic_id)
    runs.ingest_response(topic_id, "audit", _audit_response_with_warning(runs, topic_id))
    runs.approve_stage(topic_id, "audit")

    real_audit_state = RunStore.audit_state
    changed = threading.Event()

    def audit_state_with_concurrent_trace_change(store: RunStore, candidate: str) -> str:
        state = real_audit_state(store, candidate)
        if store is runs and candidate == topic_id and not changed.is_set():
            trace_path = store.personalization_trace_path(candidate)

            def change_trace() -> None:
                trace = json.loads(trace_path.read_text(encoding="utf-8"))
                trace["active_facets"] = []
                trace_path.write_text(json.dumps(trace), encoding="utf-8")
                changed.set()

            writer = threading.Thread(target=change_trace)
            writer.start()
            writer.join(5)
            assert not writer.is_alive()
        return state

    monkeypatch.setattr(RunStore, "audit_state", audit_state_with_concurrent_trace_change)

    payload = read_api.personalization_payload(runs, topic_id)

    assert not changed.is_set()
    assert payload["audit"]["state"] == "current"
    assert payload["audit"]["findings"]


def test_personalization_snapshot_serializes_concurrent_audit_approval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    context = SimpleNamespace(root=tmp_path, runs=RunStore(tmp_path))
    runs, topic_id = _ready_audit_http_run(context, "personalization-lock")
    runs.prepare_personalization_audit(topic_id)
    runs.ingest_response(topic_id, "audit", _audit_response_with_warning(runs, topic_id))
    runs.approve_stage(topic_id, "audit")
    runs.finalize_run(topic_id)
    runs.export_run(topic_id, format="html")
    initial = runs.personalization_snapshot(topic_id)
    old_finding_ids = tuple(finding.id for finding in initial.audit_findings)
    assert initial.export_state == "current"

    replacement = test_runs._valid_personalization_audit_response(runs, topic_id)
    runs.ingest_response(topic_id, "audit", replacement, force=True)

    real_export_state = RunStore._export_state_locked
    real_profile_lock = RunStore._profile_generation_lock
    real_manifest_lock = RunStore._manifest_write_lock
    export_state_started = threading.Event()
    release_reader = threading.Event()
    profile_lock_requested = threading.Event()
    manifest_lock_requested = threading.Event()
    mutation_finished = threading.Event()
    reader_result = []
    errors: list[BaseException] = []

    def paused_export_state(store: RunStore, candidate: str, *, audit_snapshot):
        if (
            store is runs
            and candidate == topic_id
            and threading.current_thread().name == "personalization-reader"
            and not export_state_started.is_set()
        ):
            assert tuple(
                finding.id for finding in audit_snapshot.findings
            ) == old_finding_ids
            export_state_started.set()
            assert release_reader.wait(5)
        return real_export_state(
            store,
            candidate,
            audit_snapshot=audit_snapshot,
        )

    def observed_profile_lock(store: RunStore, candidate: str):
        lock = real_profile_lock(store, candidate)
        if (
            store is runs
            and candidate == topic_id
            and threading.current_thread().name == "audit-approver"
        ):
            profile_lock_requested.set()
        return lock

    def observed_manifest_lock(store: RunStore, candidate: str):
        lock = real_manifest_lock(store, candidate)
        if (
            store is runs
            and candidate == topic_id
            and threading.current_thread().name == "audit-approver"
        ):
            manifest_lock_requested.set()
        return lock

    monkeypatch.setattr(RunStore, "_export_state_locked", paused_export_state)
    monkeypatch.setattr(RunStore, "_profile_generation_lock", observed_profile_lock)
    monkeypatch.setattr(RunStore, "_manifest_write_lock", observed_manifest_lock)

    def read_snapshot() -> None:
        try:
            reader_result.append(runs.personalization_snapshot(topic_id))
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    def approve_replacement() -> None:
        try:
            runs.approve_stage(topic_id, "audit", overwrite=True)
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)
        finally:
            mutation_finished.set()

    reader = threading.Thread(target=read_snapshot, name="personalization-reader")
    reader.start()
    approver: threading.Thread | None = None
    try:
        assert export_state_started.wait(5)

        approver = threading.Thread(target=approve_replacement, name="audit-approver")
        approver.start()
        assert profile_lock_requested.wait(5)
        assert not manifest_lock_requested.wait(0.2)
        assert not mutation_finished.wait(0.2)

        release_reader.set()
        assert manifest_lock_requested.wait(5)
    finally:
        release_reader.set()
        reader.join(5)
        if approver is not None:
            approver.join(5)

    assert not errors
    assert not reader.is_alive()
    assert approver is not None and not approver.is_alive()
    assert tuple(finding.id for finding in reader_result[0].audit_findings) == old_finding_ids
    assert reader_result[0].export_state == "current"
    current = runs.personalization_snapshot(topic_id)
    assert tuple(finding.id for finding in current.audit_findings) != old_finding_ids
    assert current.export_state == "stale"


def test_personalization_snapshot_serializes_concurrent_profile_attachment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    context = SimpleNamespace(root=tmp_path, runs=RunStore(tmp_path))
    runs, topic_id = _ready_audit_http_run(context, "personalization-profile-lock")
    profiles = ProfileStore(tmp_path)
    replacement_id = "replacement-profile"
    replacement_toml = test_runs.PERSONALIZED_PROFILE_TOML.replace(
        'id = "personalized-profile"', f'id = "{replacement_id}"'
    ).replace(
        "Synthetic private goal alpha", "Synthetic replacement goal alpha"
    )
    profiles.save_profile_toml(replacement_id, replacement_toml)

    real_read = RunStore._read_attached_profile_snapshot
    profile_captured = threading.Event()
    release_reader = threading.Event()
    attachment_started = threading.Event()
    attachment_finished = threading.Event()
    reader_result = []
    errors: list[BaseException] = []

    def paused_read(store: RunStore, candidate: str):
        snapshot = real_read(store, candidate)
        if (
            store is runs
            and candidate == topic_id
            and threading.current_thread().name == "profile-snapshot-reader"
            and not profile_captured.is_set()
        ):
            profile_captured.set()
            assert release_reader.wait(5)
        return snapshot

    monkeypatch.setattr(RunStore, "_read_attached_profile_snapshot", paused_read)

    def read_snapshot() -> None:
        try:
            reader_result.append(runs.personalization_snapshot(topic_id))
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    def replace_profile() -> None:
        attachment_started.set()
        try:
            profiles.attach_profile_to_topic(replacement_id, topic_id, overwrite=True)
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)
        finally:
            attachment_finished.set()

    reader = threading.Thread(target=read_snapshot, name="profile-snapshot-reader")
    reader.start()
    assert profile_captured.wait(5)

    writer = threading.Thread(target=replace_profile, name="profile-attacher")
    writer.start()
    assert attachment_started.wait(5)
    assert not attachment_finished.wait(0.2)

    release_reader.set()
    reader.join(5)
    writer.join(5)

    assert not errors
    assert not reader.is_alive() and not writer.is_alive()
    assert reader_result[0].profile is not None
    assert reader_result[0].profile.id == f"{topic_id}-profile"
    assert reader_result[0].trace_state == "current"
    current = runs.personalization_snapshot(topic_id)
    assert current.profile is not None
    assert current.profile.id == replacement_id
    assert current.trace_state == "stale"


def test_audit_http_prepare_generic_ingest_approve_status_and_nonwaivable_refusal(
    server_with_context,
):
    port, context = server_with_context
    runs, topic_id = _ready_audit_http_run(context)

    status, prepared = _req(port, "POST", f"/v1/runs/{topic_id}/audit")
    assert status == 200
    assert prepared["next_steps"]["manual"]["action"] == "save_response"
    assert prepared["next_steps"]["provider"] == {"action": "enqueue", "stage": "audit"}

    status, _ = _req(
        port,
        "POST",
        f"/v1/runs/{topic_id}/stages/audit/response",
        body={"text": _audit_response_with_warning(runs, topic_id)},
    )
    assert status == 200
    status, _ = _req(port, "POST", f"/v1/runs/{topic_id}/stages/audit/approve")
    assert status == 200

    status, payload = _req(port, "GET", f"/v1/runs/{topic_id}")
    assert status == 200
    final = payload["validations"]["final"]
    # The personalized fixture already has one missing goal; marking another
    # goal weak yields two projected audit findings. Derive the additive count
    # from the shared accessor so this assertion checks the API projection
    # rather than duplicating the audit engine's finding rules.
    audit_findings = [
        finding for finding in runs.combined_findings(topic_id) if finding.stage == "audit"
    ]
    assert len(audit_findings) == 2
    assert final["audit"] == {
        "state": "current",
        "finding_count": len(audit_findings),
    }
    assert "audit" not in final["findings_by_stage"]

    status, validation = _req(
        port, "GET", f"/v1/runs/{topic_id}/validation/final"
    )
    audit_finding = next(
        finding
        for finding in validation["report"]["findings"]
        if finding["stage"] == "audit"
    )
    assert audit_finding["source_stage"] == "repair"

    status, refused = _req(
        port,
        "POST",
        f"/v1/runs/{topic_id}/validation/final/waivers",
        body={
            "finding_id": audit_finding["id"],
            "guide_sha256": validation["report"]["guide_sha256"],
            "reason": "Attempted audit waiver.",
        },
    )
    assert status == 422
    assert refused["error"]["code"] == "finding_not_waivable"

    status, rebuilt = _req(
        port, "POST", f"/v1/runs/{topic_id}/audit", body={"rebuild": True}
    )
    assert status == 200
    assert rebuilt["audit"]["state"] == "current"
    assert rebuilt["next_steps"]["provider"]["force"] is True


def test_audit_http_errors_are_private_safe(server_with_context):
    port, context = server_with_context
    runs, topic_id = _ready_audit_http_run(context, "audit-private")
    _req(port, "POST", f"/v1/runs/{topic_id}/audit")

    planted = "PLANTED PRIVATE HTTP AUDIT VALUE"
    status, payload = _req(
        port,
        "POST",
        f"/v1/runs/{topic_id}/stages/audit/response",
        body={"text": json.dumps({"secret": planted})},
    )
    assert status == 400
    assert planted not in json.dumps(payload)

    status, unavailable = _req(port, "POST", "/v1/runs/g/audit")
    assert status == 400
    assert unavailable["error"]["message"] == (
        "personalization audit unavailable: no attached profile snapshot"
    )


def test_daemon_fake_provider_audit_flow(server_with_context, monkeypatch):
    port, context = server_with_context
    runs, topic_id = _ready_audit_http_run(context, "audit-provider")
    runs.finalize_run(topic_id)
    assert runs.run_status(topic_id).next_action.action == "done"
    status, _ = _req(port, "POST", f"/v1/runs/{topic_id}/audit")
    assert status == 200

    monkeypatch.setenv("FAKE_STDOUT", _audit_response_with_warning(runs, topic_id))
    status, job = _req(
        port,
        "POST",
        "/v1/jobs",
        body={"topic_id": topic_id, "stage": "audit"},
    )
    assert status == 200

    import time

    for _ in range(200):
        status, job = _req(port, "GET", f"/v1/jobs/{job['id']}")
        if job["status"] in {"succeeded", "failed", "canceled", "interrupted"}:
            break
        time.sleep(0.02)
    assert job["status"] == "succeeded"
    assert runs.audit_state(topic_id) == "not_run"

    status, _ = _req(port, "POST", f"/v1/runs/{topic_id}/stages/audit/approve")
    assert status == 200
    assert runs.audit_state(topic_id) == "current"

    # The optional audit never reopens the primary lifecycle: this finalized
    # run remains done, and advance is still a no-op without changing audit.
    status, body = _req(port, "POST", f"/v1/runs/{topic_id}/advance")
    assert status == 200
    assert body["performed"] is None
    assert body["status"]["next_action"]["action"] == "done"
    assert body["status"]["validations"]["final"]["audit"]["state"] == "current"
    assert runs.audit_state(topic_id) == "current"


def test_audit_provider_private_stderr_is_absent_from_file_http_and_cli_logs(
    server_with_context, monkeypatch, capsys
):
    port, context = server_with_context
    runs, topic_id = _ready_audit_http_run(context, "audit-private-stdout")
    status, _ = _req(port, "POST", f"/v1/runs/{topic_id}/audit")
    assert status == 200

    planted = "Synthetic private goal alpha"
    monkeypatch.setenv("FAKE_STDOUT", _audit_response_with_warning(runs, topic_id))
    monkeypatch.setenv("FAKE_STDERR", planted + "\n")
    status, job = _req(
        port,
        "POST",
        "/v1/jobs",
        body={"topic_id": topic_id, "stage": "audit"},
    )
    assert status == 200

    import time

    for _ in range(200):
        status, job = _req(port, "GET", f"/v1/jobs/{job['id']}")
        if job["status"] in {"succeeded", "failed", "canceled", "interrupted"}:
            break
        time.sleep(0.02)
    assert job["status"] == "succeeded"
    response_path = runs.stage_paths(topic_id, "audit").response_path
    assert response_path.is_file()
    assert json.loads(response_path.read_text(encoding="utf-8"))["schema_version"] == 1

    log_path = context.store.log_path(topic_id, job["id"])
    file_log = log_path.read_text(encoding="utf-8")
    assert planted not in file_log
    assert file_log == ""

    status, log_payload = _req(port, "GET", f"/v1/jobs/{job['id']}/log")
    assert status == 200
    assert planted not in log_payload["data"]
    assert log_payload["data"] == ""

    class StoreBackedClient:
        def get_log(self, job_id, offset):
            stored = context.store.find(job_id)
            assert stored is not None
            data, next_offset = context.store.read_log(stored, offset)
            return data.decode("utf-8", "replace"), next_offset

    monkeypatch.setattr(
        "education_pipeline.cli.ensure_daemon",
        lambda root, autostart=False: StoreBackedClient(),
    )
    from education_pipeline.cli import main as cli_main

    assert cli_main(["--workspace", str(context.root), "logs", job["id"]]) == 0
    cli_log = capsys.readouterr().out
    assert planted not in cli_log
    assert cli_log == ""


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
        assert resp["error"]["code"] == "job_conflict", method_path

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


def test_create_topic_structured_endpoint(server):
    status, body = _req(
        server,
        "POST",
        "/v1/topics",
        body={"id": "n4", "title": "New Four", "brief": "A brief.", "goals": ["explain X"]},
    )
    assert status == 200 and body == {"id": "n4", "title": "New Four"}

    status, body = _req(server, "GET", "/v1/topics/n4")
    assert status == 200 and body["title"] == "New Four"


def test_create_topic_structured_duplicate_is_409(server):
    body = {"id": "n5", "title": "New Five"}
    status, _ = _req(server, "POST", "/v1/topics", body=body)
    assert status == 200

    status, body_resp = _req(server, "POST", "/v1/topics", body=body)
    assert status == 409 and body_resp["error"]["code"] == "already_exists"

    status, _ = _req(
        server, "POST", "/v1/topics", body={"id": "n5", "title": "New Five Updated", "overwrite": True}
    )
    assert status == 200


def test_create_topic_structured_missing_title_is_400(server):
    status, _ = _req(server, "POST", "/v1/topics", body={"id": "n6"})
    assert status == 400


def test_import_profile_endpoint(server):
    toml = 'schema_version = 1\nid = "p2"\ntarget_learner = "new cohort"\n'
    status, body = _req(server, "POST", "/v1/profiles", body={"toml": toml})
    assert status == 200 and body == {"id": "p2"}
    # fixture already created profile "p"
    existing = 'schema_version = 1\nid = "p"\ntarget_learner = "changed"\n'
    status, body = _req(server, "POST", "/v1/profiles", body={"toml": existing})
    assert status == 409 and body["error"]["code"] == "already_exists"


def _api_profile(profile_id, target_learner="Synthetic API cohort alpha"):
    return {
        "schema_version": 1,
        "id": profile_id,
        "target_learner": target_learner,
        "learning_preferences": {"preferred_modalities": ["diagrams"]},
        "privacy": {
            "private_by_default": True,
            "include_in_published_output": True,
            "publishable_summary": f"For {target_learner}",
        },
        "metadata": {"synthetic": {"rank": 3, "enabled": True}},
    }


def test_profile_preview_endpoint_is_structured_and_non_mutating(server_with_context):
    port, context = server_with_context
    profile = _api_profile("preview-only")
    before = {
        path.relative_to(context.root).as_posix(): path.read_bytes()
        for path in context.root.rglob("*")
        if path.is_file()
    }

    status, body = _req(
        port, "POST", "/v1/profiles/preview", body={"profile": profile}
    )

    assert status == 200
    assert set(body) == {
        "parsed",
        "prompt_context",
        "publishable_summary",
        "sensitivity",
        "warnings",
    }
    assert body["parsed"]["id"] == profile["id"]
    assert body["parsed"]["target_learner"] == profile["target_learner"]
    assert profile["target_learner"] in body["prompt_context"]
    assert body["publishable_summary"] == profile["privacy"]["publishable_summary"]
    assert body["sensitivity"]["metadata.*"] == "high"
    assert profile["target_learner"] not in json.dumps(body["warnings"])
    after = {
        path.relative_to(context.root).as_posix(): path.read_bytes()
        for path in context.root.rglob("*")
        if path.is_file()
    }
    assert after == before
    assert not context.profiles.profile_path("preview-only").exists()


def test_profile_preview_rejects_wrong_nested_type_and_unknown_key(server):
    wrong_nested = _api_profile("wrong-nested")
    wrong_nested["privacy"] = []
    status, body = _req(
        server,
        "POST",
        "/v1/profiles/preview",
        body={"profile": wrong_nested},
    )
    assert status == 400
    assert body["error"]["code"] == "invalid_request"

    unknown = _api_profile("unknown-key")
    unknown["learning_preferences"]["secret_copy"] = "forbidden"
    status, body = _req(
        server,
        "POST",
        "/v1/profiles/preview",
        body={"profile": unknown},
    )
    assert status == 400
    assert body["error"]["code"] == "invalid_request"


def test_profile_put_create_update_and_get_status_shapes(server):
    profile = _api_profile("structured-api")
    status, created = _req(
        server,
        "PUT",
        "/v1/profiles/structured-api",
        body={"profile": profile, "base_sha256": None},
    )
    assert status == 201
    assert set(created) == {
        "id",
        "parsed",
        "sensitivity",
        "content_sha256",
        "warnings",
        "attached_topic_count",
    }
    assert created["parsed"]["id"] == profile["id"]
    assert created["parsed"]["target_learner"] == profile["target_learner"]

    updated_profile = {**profile, "target_learner": "Synthetic API cohort beta"}
    status, updated = _req(
        server,
        "PUT",
        "/v1/profiles/structured-api",
        body={
            "profile": updated_profile,
            "base_sha256": created["content_sha256"],
        },
    )
    assert status == 200
    assert updated["parsed"]["id"] == updated_profile["id"]
    assert updated["parsed"]["target_learner"] == updated_profile["target_learner"]
    assert updated["content_sha256"] != created["content_sha256"]

    status, detail = _req(server, "GET", "/v1/profiles/structured-api")
    assert status == 200
    assert detail == updated


def test_profile_put_rejects_path_mismatch_bad_shapes_unknown_keys_and_preconditions(server):
    profile = _api_profile("body-id")
    status, _ = _req(
        server,
        "PUT",
        "/v1/profiles/path-id",
        body={"profile": profile, "base_sha256": None},
    )
    assert status == 400

    bad_nested = _api_profile("bad-nested")
    bad_nested["metadata"] = ["not", "a", "mapping"]
    status, _ = _req(
        server,
        "PUT",
        "/v1/profiles/bad-nested",
        body={"profile": bad_nested, "base_sha256": None},
    )
    assert status == 400

    unknown = _api_profile("unknown-field")
    unknown["secret_copy"] = "forbidden"
    status, _ = _req(
        server,
        "PUT",
        "/v1/profiles/unknown-field",
        body={"profile": unknown, "base_sha256": None},
    )
    assert status == 400

    status, _ = _req(
        server,
        "PUT",
        "/v1/profiles/missing-base",
        body={"profile": _api_profile("missing-base")},
    )
    assert status == 400
    status, _ = _req(
        server,
        "PUT",
        "/v1/profiles/update-missing",
        body={"profile": _api_profile("update-missing"), "base_sha256": "0" * 64},
    )
    assert status == 409


def test_profile_put_conflicts_expose_only_fresh_hash_and_no_values(server):
    private_value = "PLANTED_HTTP_PRIVATE_ALPHA"
    profile = _api_profile("conflict-profile", private_value)
    status, created = _req(
        server,
        "PUT",
        "/v1/profiles/conflict-profile",
        body={"profile": profile, "base_sha256": None},
    )
    assert status == 201

    status, existing = _req(
        server,
        "PUT",
        "/v1/profiles/conflict-profile",
        body={"profile": profile, "base_sha256": None},
    )
    assert status == 409
    assert existing["error"]["code"] == "already_exists"
    assert existing["error"]["detail"] == {
        "current_sha256": created["content_sha256"]
    }

    candidate = {**profile, "target_learner": "PLANTED_HTTP_PRIVATE_BETA"}
    status, stale = _req(
        server,
        "PUT",
        "/v1/profiles/conflict-profile",
        body={"profile": candidate, "base_sha256": "0" * 64},
    )
    assert status == 409
    assert stale["error"]["code"] == "stale_content"
    assert stale["error"]["detail"] == {
        "current_sha256": created["content_sha256"]
    }
    rendered = json.dumps([existing, stale], sort_keys=True)
    assert "PLANTED_HTTP_PRIVATE" not in rendered
    assert set(stale["error"]["detail"]) == {"current_sha256"}


def test_profile_duplicate_endpoint_success_collision_and_missing_source(server):
    source = _api_profile("duplicate-source")
    status, _ = _req(
        server,
        "PUT",
        "/v1/profiles/duplicate-source",
        body={"profile": source, "base_sha256": None},
    )
    assert status == 201

    status, duplicated = _req(
        server,
        "POST",
        "/v1/profiles/duplicate-source/duplicate",
        body={"new_id": "duplicate-target"},
    )
    assert status == 201
    assert duplicated["id"] == "duplicate-target"
    assert duplicated["parsed"]["id"] == "duplicate-target"
    assert duplicated["parsed"]["target_learner"] == source["target_learner"]

    status, collision = _req(
        server,
        "POST",
        "/v1/profiles/duplicate-source/duplicate",
        body={"new_id": "duplicate-target"},
    )
    assert status == 409
    assert collision["error"]["code"] == "already_exists"
    assert collision["error"]["detail"] == {
        "current_sha256": duplicated["content_sha256"]
    }

    status, body = _req(
        server,
        "POST",
        "/v1/profiles/missing-source/duplicate",
        body={"new_id": "unused-target"},
    )
    assert status == 404


def test_profile_attachment_updates_list_and_detail_counts(server):
    status, _ = _req(
        server, "POST", "/v1/topics/t/profile", body={"profile_id": "p"}
    )
    assert status == 200

    status, listing = _req(server, "GET", "/v1/profiles")
    assert status == 200
    assert listing["profiles"] == [{"id": "p", "attached_topic_count": 1}]
    status, detail = _req(server, "GET", "/v1/profiles/p")
    assert status == 200
    assert detail["attached_topic_count"] == 1


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


def test_final_download_uses_immutable_guide_1_1_content_type(server_with_context):
    port, context = server_with_context
    context.runs.create_run(
        "personalized-download",
        content_contract=ContentContract.interactive_guide_v1_1(),
    )
    final = context.runs.final_guide_json_path("personalized-download")
    final.parent.mkdir(parents=True, exist_ok=True)
    final.write_bytes(test_runs.PERSONALIZED_GUIDE_FIXTURE.encode("utf-8"))

    status, headers, data = _raw_download(
        port,
        "/v1/runs/personalized-download/final/download",
    )
    assert status == 200
    assert headers["content-type"] == (
        "application/vnd.education-pipeline.guide+json;version=1.1"
    )
    assert headers["content-disposition"] == (
        'attachment; filename="personalized-download-guide.json"'
    )
    assert data == final.read_bytes()


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


def _sha_hex(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_edit_response_put_happy_path(server):
    _req(server, "POST", "/v1/runs/t/stages/draft/response", body={"text": "V1"})
    status, body = _req(
        server,
        "PUT",
        "/v1/runs/t/stages/draft/response",
        body={"text": "V2", "base_sha256": _sha_hex("V1")},
    )
    assert status == 200
    assert body == {
        "topic_id": "t",
        "stage": "draft",
        "response_path": "responses/draft.response.md",
        "response_sha256": _sha_hex("V2"),
    }
    # follow-up GET shows the new content and the new hash
    status, got = _req(server, "GET", "/v1/runs/t/stages/draft")
    assert got["response"] == "V2"
    assert got["response_sha256"] == _sha_hex("V2")


def test_edit_response_put_requires_token(server):
    status, _ = _req(
        server,
        "PUT",
        "/v1/runs/t/stages/draft/response",
        token=None,
        body={"text": "x", "base_sha256": "0" * 64},
    )
    assert status == 401


def test_edit_response_put_unknown_topic_is_404(server):
    status, body = _req(
        server,
        "PUT",
        "/v1/runs/ghost/stages/draft/response",
        body={"text": "x", "base_sha256": "0" * 64},
    )
    assert status == 404 and body["error"]["code"] == "not_found"


def test_edit_response_put_missing_fields_are_400(server):
    _req(server, "POST", "/v1/runs/t/stages/draft/response", body={"text": "V1"})
    status, _ = _req(server, "PUT", "/v1/runs/t/stages/draft/response", body={"text": "x"})
    assert status == 400
    status, _ = _req(
        server, "PUT", "/v1/runs/t/stages/draft/response", body={"base_sha256": "0" * 64}
    )
    assert status == 400
    status, _ = _req(
        server,
        "PUT",
        "/v1/runs/t/stages/bogus/response",
        body={"text": "x", "base_sha256": "0" * 64},
    )
    assert status == 400


def test_edit_response_put_stale_after_external_write(server, tmp_path):
    _req(server, "POST", "/v1/runs/t/stages/draft/response", body={"text": "V1"})
    loaded_sha = _sha_hex("V1")
    response_file = tmp_path / "runs" / "t" / "responses" / "draft.response.md"
    response_file.write_text("EXTERNAL EDIT", encoding="utf-8")

    status, body = _req(
        server,
        "PUT",
        "/v1/runs/t/stages/draft/response",
        body={"text": "V2", "base_sha256": loaded_sha},
    )
    assert status == 409
    assert body["error"]["code"] == "stale_content"
    assert "draft" in body["error"]["message"]
    # the envelope carries no file content and the external edit is intact
    assert "EXTERNAL EDIT" not in json.dumps(body)
    assert response_file.read_text(encoding="utf-8") == "EXTERNAL EDIT"


def test_edit_response_put_missing_file_is_stale(server):
    status, body = _req(
        server,
        "PUT",
        "/v1/runs/t/stages/qa/response",
        body={"text": "x", "base_sha256": "0" * 64},
    )
    assert status == 409 and body["error"]["code"] == "stale_content"


def test_edit_response_put_blocked_while_job_active(server, monkeypatch):
    import time

    _req(server, "POST", "/v1/runs/t/stages/draft/response", body={"text": "V1"})
    monkeypatch.setenv("FAKE_DELAY", "5")
    status, job = _req(server, "POST", "/v1/jobs", body={"topic_id": "t", "stage": "draft"})
    assert status == 200

    status, body = _req(
        server,
        "PUT",
        "/v1/runs/t/stages/draft/response",
        body={"text": "V2", "base_sha256": _sha_hex("V1")},
    )
    assert status == 409 and body["error"]["code"] == "job_conflict"

    _req(server, "POST", f"/v1/jobs/{job['id']}/cancel")
    for _ in range(200):
        status, current = _req(server, "GET", f"/v1/jobs/{job['id']}")
        if current["status"] in {"succeeded", "failed", "canceled", "interrupted"}:
            break
        time.sleep(0.02)


def test_put_unknown_path_is_404(server):
    status, body = _req(server, "PUT", "/v1/nope", body={"text": "x"})
    assert status == 404


def test_downloads_require_token(server):
    status, _, _ = _raw_download(server, "/v1/runs/t/final/download", token=None)
    assert status == 401


def test_full_pipeline_over_http(server, tmp_path):
    toml = 'schema_version = 1\nid = "full"\ntitle = "Full Pipeline"\n'
    status, body = _req(server, "POST", "/v1/topics", body={"toml": toml})
    assert (status, body) == (200, {"id": "full", "title": "Full Pipeline"})
    # Opt the new topic into the explicit legacy Markdown path before advancing.
    RunStore(tmp_path).create_run("full", content_contract=ContentContract.legacy_markdown())

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


def test_preview_renders_markdown_body(server):
    status, body = _req(
        server, "POST", "/v1/preview", body={"text": "# Hi\n\nSome **bold** text."}
    )
    assert status == 200
    assert "<h1>Hi</h1>" in body["html"]
    assert "<strong>bold</strong>" in body["html"]
    assert "<!DOCTYPE" not in body["html"]


def test_preview_escapes_script_input(server):
    status, body = _req(
        server, "POST", "/v1/preview", body={"text": "<script>alert(1)</script>"}
    )
    assert status == 200
    assert "<script>" not in body["html"]
    assert "&lt;script&gt;" in body["html"]


def test_preview_missing_text_is_400(server):
    status, _ = _req(server, "POST", "/v1/preview", body={})
    assert status == 400
    status, _ = _req(server, "POST", "/v1/preview", body={"text": 42})
    assert status == 400


def test_preview_requires_token(server):
    status, _ = _req(server, "POST", "/v1/preview", token=None, body={"text": "x"})
    assert status == 401


def test_preview_not_blocked_by_active_job(server, monkeypatch):
    import time

    monkeypatch.setenv("FAKE_DELAY", "5")
    status, job = _req(server, "POST", "/v1/jobs", body={"topic_id": "t", "stage": "draft"})
    assert status == 200

    status, body = _req(server, "POST", "/v1/preview", body={"text": "# still works"})
    assert status == 200 and "<h1>still works</h1>" in body["html"]

    _req(server, "POST", f"/v1/jobs/{job['id']}/cancel")
    for _ in range(200):
        status, current = _req(server, "GET", f"/v1/jobs/{job['id']}")
        if current["status"] in {"succeeded", "failed", "canceled", "interrupted"}:
            break
        time.sleep(0.02)


def test_guide_preview_renders_full_sandbox_document(server):
    status, body = _req(
        server,
        "POST",
        "/v1/guide-preview",
        body={"text": GUIDE_FIXTURE.read_text(encoding="utf-8"), "include_validation": True},
    )
    assert status == 200
    assert body["html"].startswith("<!doctype html>")
    assert 'data-guide-mode="preview"' in body["html"]
    assert body["validation"]["blocking"] == 0
    assert len(body["content_sha256"]) == 64


def test_guide_preview_error_semantics(server):
    status, body = _req(server, "POST", "/v1/guide-preview", body={"text": "{"})
    assert status == 400 and body["error"]["code"] == "invalid_guide_json"
    status, body = _req(server, "POST", "/v1/guide-preview", body={"text": "{}"})
    assert status == 422 and body["error"]["code"] == "guide_not_renderable"


def test_create_waiver_over_http_with_corrupt_element_returns_400_not_dropped_connection(
    server, tmp_path
):
    """Regression test for the crash the daemon must never surface as a
    dropped connection: a validation-waivers.json whose root is a valid JSON
    object but whose ``waivers`` list has a corrupt element must come back as
    a genuine HTTP 400 with the standard error envelope."""
    runs = RunStore(tmp_path)
    guide = json.loads(GUIDE_FIXTURE.read_text(encoding="utf-8"))
    guide["modules"][0]["sections"][0]["blocks"][0]["markdown"] += " TODO"
    draft = runs.stage_paths("g", "draft")
    draft.approved_path.write_text(json.dumps(guide), encoding="utf-8")
    report = runs.validate_run("g", "draft")
    report_payload = json.loads(report.read_text(encoding="utf-8"))
    finding = next(item for item in report_payload["findings"] if item["waivable"])

    waivers_path = runs.waivers_path("g")
    waivers_path.parent.mkdir(parents=True, exist_ok=True)
    waivers_path.write_text(
        json.dumps(
            {
                "guide_sha256": report_payload["guide_sha256"],
                "waivers": [1, 2, 3],
            }
        ),
        encoding="utf-8",
    )

    status, body = _req(
        server,
        "POST",
        "/v1/runs/g/validation/draft/waivers",
        body={
            "finding_id": finding["id"],
            "guide_sha256": report_payload["guide_sha256"],
            "reason": "accepted",
        },
    )
    assert status == 400
    assert body["error"]["code"] == "invalid_request"
    # the corrupt file on disk is untouched: no orphaned mkstemp temp file
    # (``.tmp-<random>.json``, per ``_write_bytes_atomic``), no partial write
    assert not list(waivers_path.parent.glob(f".tmp-*{waivers_path.suffix}"))
    assert json.loads(waivers_path.read_text(encoding="utf-8"))["waivers"] == [1, 2, 3]


def test_create_waiver_never_persists_a_file_its_own_loader_rejects(server, tmp_path):
    """create_waiver's guard on a pre-existing waiver element only checked
    that ``finding_id`` was a string. RunStore's loader also requires
    ``reason`` to be a string (and schema_version == 1). An element like
    {"finding_id": "other", "reason": {"nested": True}} passed the write
    guard, got copied verbatim into the newly written file, and the endpoint
    returned 200 — after which every future load of the run's waivers raises
    ConfigError, bricking the run. Whatever the endpoint chooses to do
    (reject, or normalize), a file it accepts and writes must always load
    cleanly via RunStore's own loader."""
    runs = RunStore(tmp_path)
    guide = json.loads(GUIDE_FIXTURE.read_text(encoding="utf-8"))
    guide["modules"][0]["sections"][0]["blocks"][0]["markdown"] += " TODO"
    draft = runs.stage_paths("g", "draft")
    draft.approved_path.write_text(json.dumps(guide), encoding="utf-8")
    report = runs.validate_run("g", "draft")
    report_payload = json.loads(report.read_text(encoding="utf-8"))
    finding = next(item for item in report_payload["findings"] if item["waivable"])

    waivers_path = runs.waivers_path("g")
    waivers_path.parent.mkdir(parents=True, exist_ok=True)
    before = json.dumps(
        {
            "schema_version": 1,
            "guide_sha256": report_payload["guide_sha256"],
            # finding_id is a string (passes the old write-path guard) but
            # reason is not — the loader rejects this, the old guard did not.
            "waivers": [{"finding_id": "some-other-finding", "reason": {"nested": True}}],
        }
    )
    waivers_path.write_text(before, encoding="utf-8")

    status, body = _req(
        server,
        "POST",
        "/v1/runs/g/validation/draft/waivers",
        body={
            "finding_id": finding["id"],
            "guide_sha256": report_payload["guide_sha256"],
            "reason": "accepted",
        },
    )
    if status == 200:
        # The endpoint accepted the request; the file it wrote MUST load
        # cleanly through RunStore's own loader — no divergent schema logic.
        loaded = RunStore(tmp_path).load_waiver_set("g")
        assert loaded is not None
        assert {w.finding_id for w in loaded.waivers} >= {finding["id"]}
    else:
        # The endpoint refused instead: the pre-existing file must be left
        # untouched (no partial write, no orphaned mkstemp temp file, per
        # ``_write_bytes_atomic``'s ``.tmp-<random>.json`` naming).
        assert status == 400
        assert waivers_path.read_text(encoding="utf-8") == before
        assert not list(waivers_path.parent.glob(f".tmp-*{waivers_path.suffix}"))


def test_get_waivers_over_http_with_corrupt_file_returns_400_not_200(server, tmp_path):
    """The GET waivers route used to keep its own, weaker copy of the waivers
    schema check (root-is-a-dict only) and echoed a corrupt file back
    verbatim with ``"state": "current"`` -- telling the cockpit the run is
    healthy while POST .../waivers and RunStore.load_waiver_set both refuse
    the same file with ConfigError. All three surfaces must agree."""
    runs = RunStore(tmp_path)
    guide = json.loads(GUIDE_FIXTURE.read_text(encoding="utf-8"))
    guide["modules"][0]["sections"][0]["blocks"][0]["markdown"] += " TODO"
    draft = runs.stage_paths("g", "draft")
    draft.approved_path.write_text(json.dumps(guide), encoding="utf-8")
    report = runs.validate_run("g", "draft")
    report_payload = json.loads(report.read_text(encoding="utf-8"))

    waivers_path = runs.waivers_path("g")
    waivers_path.parent.mkdir(parents=True, exist_ok=True)
    waivers_path.write_text(
        json.dumps(
            {
                "guide_sha256": report_payload["guide_sha256"],
                "waivers": [1, 2, 3],
            }
        ),
        encoding="utf-8",
    )

    status, body = _req(server, "GET", "/v1/runs/g/validation/draft/waivers")
    assert status == 400
    assert body["error"]["code"] == "invalid_request"


def test_delete_waiver_route_removes_the_waiver(server, tmp_path):
    """DELETE .../waivers/{finding_id} closes a gate the cockpit previously
    opened with POST -- adapting this module's daemon boot helper and its
    existing POST-waiver test to the new verb."""
    from urllib.parse import quote

    topic_id = "systems-thinking"
    runs = test_runs._create_guide_run(tmp_path, topic_id)
    leak_json = test_runs._prompt_leak_guide_json()
    test_runs._drive_guide_to_finalize_ready(
        runs, topic_id, draft_body=leak_json, repair_body=leak_json
    )
    finding_id = test_runs._first_waivable_blocking_finding_id(runs, topic_id, "final")
    report_sha = json.loads(
        runs.final_report_path(topic_id).read_text(encoding="utf-8")
    )["guide_sha256"]

    status, body = _req(
        server,
        "POST",
        f"/v1/runs/{topic_id}/validation/final/waivers",
        body={"finding_id": finding_id, "guide_sha256": report_sha, "reason": "accepted"},
    )
    assert status == 200
    assert runs.waivers_path(topic_id).exists()

    status, body = _req(
        server,
        "DELETE",
        f"/v1/runs/{topic_id}/validation/final/waivers/{quote(finding_id, safe='')}",
    )
    assert status == 200
    assert body["waivers"]["waivers"] == []


def test_delete_waiver_leaves_no_empty_waivers_file(server, tmp_path):
    """The waivers-file existence contract: read_api skips its per-poll gate
    recompute only when the file is ABSENT. Removing the last waiver over HTTP
    must unlink it, not write '{"waivers": []}'."""
    from urllib.parse import quote

    topic_id = "systems-thinking"
    runs = test_runs._create_guide_run(tmp_path, topic_id)
    leak_json = test_runs._prompt_leak_guide_json()
    test_runs._drive_guide_to_finalize_ready(
        runs, topic_id, draft_body=leak_json, repair_body=leak_json
    )
    finding_id = test_runs._first_waivable_blocking_finding_id(runs, topic_id, "final")
    report_sha = json.loads(
        runs.final_report_path(topic_id).read_text(encoding="utf-8")
    )["guide_sha256"]

    status, _ = _req(
        server,
        "POST",
        f"/v1/runs/{topic_id}/validation/final/waivers",
        body={"finding_id": finding_id, "guide_sha256": report_sha, "reason": "accepted"},
    )
    assert status == 200
    assert runs.waivers_path(topic_id).exists()

    status, _ = _req(
        server,
        "DELETE",
        f"/v1/runs/{topic_id}/validation/final/waivers/{quote(finding_id, safe='')}",
    )
    assert status == 200
    assert not runs.waivers_path(topic_id).exists()


def test_delete_unknown_path_is_404(server):
    status, body = _req(server, "DELETE", "/v1/runs/nope/nonsense")
    assert status == 404
    assert body["error"]["code"] == "not_found"


def test_unhandled_exception_returns_500_envelope_not_dropped_connection(server, monkeypatch):
    """The daemon's last-resort handler must convert any unexpected exception
    into a diagnosable 500, never a dropped connection."""
    from education_pipeline.daemon import write_api

    def _boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(write_api, "advance_run", _boom)
    status, body = _req(server, "POST", "/v1/runs/t/advance")
    assert status == 500
    assert body["error"]["code"] == "internal"


@pytest.mark.parametrize(
    ("operation", "method", "path"),
    [
        ("get_profile", "GET", "/v1/profiles/p"),
        ("preview_profile", "POST", "/v1/profiles/preview"),
        ("put_profile", "PUT", "/v1/profiles/private-put"),
        (
            "duplicate_profile",
            "POST",
            "/v1/profiles/p/duplicate",
        ),
    ],
)
def test_profile_unexpected_exceptions_redact_private_values_from_500_and_stderr(
    server,
    monkeypatch,
    capsys,
    operation,
    method,
    path,
):
    from education_pipeline.daemon import read_api, write_api

    planted_value = "PLANTED_LAST_RESORT_PROFILE_PRIVATE_VALUE"

    def fail_with_private_value(*args, **kwargs):
        raise RuntimeError(planted_value)

    module = read_api if operation in {"get_profile", "preview_profile"} else write_api
    monkeypatch.setattr(module, operation, fail_with_private_value)
    if operation == "preview_profile":
        body = {"profile": _api_profile("private-preview", planted_value)}
    elif operation == "put_profile":
        body = {
            "profile": _api_profile("private-put", planted_value),
            "base_sha256": None,
        }
    elif operation == "duplicate_profile":
        body = {"new_id": "private-duplicate"}
    else:
        body = None
    capsys.readouterr()

    status, response = _req(server, method, path, body=body)
    stderr = capsys.readouterr().err

    assert status == 500
    assert response == {
        "error": {"code": "internal", "message": "internal server error"}
    }
    assert planted_value not in json.dumps(response)
    assert planted_value not in stderr


def test_config_providers_reports_availability(config_server):
    status, payload = _req(config_server, "GET", "/v1/config/providers")
    assert status == 200
    by_id = {p["id"]: p for p in payload["providers"]}
    assert by_id["manual"]["available"] is True and by_id["manual"]["executable"] is False
    assert by_id["manual"]["reason"] is None
    assert by_id["fake"]["available"] is True and by_id["fake"]["executable"] is True
    assert by_id["nope"]["available"] is False
    assert "no runner registered" in by_id["nope"]["reason"]


def test_config_catalog_lists_providers_and_models(config_server):
    status, payload = _req(config_server, "GET", "/v1/config/catalog")
    assert status == 200
    by_id = {p["id"]: p for p in payload["providers"]}
    fake_models = {m["id"]: m for m in by_id["fake"]["models"]}
    assert fake_models["m"]["quality"] == "fast"
    assert fake_models["strong-m"]["quality"] == "strong"


def test_config_catalog_includes_presets(config_server):
    status, payload = _req(config_server, "GET", "/v1/config/catalog")
    assert status == 200
    assert isinstance(payload["presets"], list)
    preset = {p["id"]: p for p in payload["presets"]}["test-preset"]
    assert preset["label"] == "Test preset"
    stage_map = preset["stages"]["fake"]
    assert set(stage_map) == {"profile", "spec", "outline", "draft", "qa", "repair", "audit"}
    assert stage_map["spec"] == {"model": "strong-m", "effort": "high"}
    assert stage_map["qa"] == {"model": "m", "effort": None}


def test_config_plan_includes_sha_and_warnings(config_server):
    status, payload = _req(config_server, "GET", "/v1/config/plan")
    assert status == 200
    assert len(payload["plan_sha256"]) == 64
    stages = {s["stage"]: s for s in payload["stages"]}
    assert set(stages) == set(STAGE_ORDER)
    assert isinstance(stages["outline"]["warning"], str) and stages["outline"]["warning"]
    assert stages["finalize"]["recommendation"] == "local_only"
    assert stages["export"]["recommendation"] == "local_only"


def test_put_config_plan_with_correct_sha_updates_and_returns_new_sha(config_server):
    status, payload = _req(config_server, "GET", "/v1/config/plan")
    assert status == 200
    base_sha256 = payload["plan_sha256"]

    status, updated = _req(
        config_server,
        "PUT",
        "/v1/config/plan",
        body={
            "base_sha256": base_sha256,
            "provider": "fake",
            "stages": {"draft": {"model": "strong-m"}},
        },
    )
    assert status == 200
    assert updated["provider"] == "fake"
    assert updated["plan_sha256"] != base_sha256
    stages = {s["stage"]: s for s in updated["stages"]}
    assert stages["draft"]["model"] == "strong-m"

    status, reread = _req(config_server, "GET", "/v1/config/plan")
    assert status == 200
    assert reread["plan_sha256"] == updated["plan_sha256"]


def test_put_config_plan_with_stale_sha_returns_409(config_server):
    status, body = _req(
        config_server,
        "PUT",
        "/v1/config/plan",
        body={
            "base_sha256": "stale" * 16,
            "provider": "fake",
            "stages": {"draft": {"model": "m"}},
        },
    )
    assert status == 409
    assert body["error"]["code"] == "stale_content"


def test_put_config_plan_unknown_stage_key_returns_400_over_http(config_server):
    """A misspelled stage-override key ('modle' instead of 'model') must be
    rejected with 400 over real HTTP, not silently swallowed with a 200 that
    discards the key."""

    status, payload = _req(config_server, "GET", "/v1/config/plan")
    assert status == 200
    base_sha256 = payload["plan_sha256"]

    status, body = _req(
        config_server,
        "PUT",
        "/v1/config/plan",
        body={
            "base_sha256": base_sha256,
            "provider": "fake",
            "stages": {"draft": {"modle": "opus"}},
        },
    )
    assert status == 400
    assert "unknown stage-override key" in body["error"]["message"]

    # nothing was written: the plan sha is unchanged
    status, reread = _req(config_server, "GET", "/v1/config/plan")
    assert reread["plan_sha256"] == base_sha256


def test_put_config_plan_unknown_model_returns_400_and_writes_nothing(tmp_path, monkeypatch):
    # End-to-end over the HTTP layer against a REAL WorkspaceConfigSource: a
    # failed PUT (unknown model) must return 400 and leave the workspace's
    # model-plan.toml untouched (here: still absent, since reads fall back to
    # the packaged example).
    register_runner(FakeRunner())
    runs = RunStore(tmp_path)
    runs.create_run("t", content_contract=ContentContract.legacy_markdown())
    config = WorkspaceConfigSource(tmp_path)
    store = JobStore(tmp_path)
    worker = Worker(store, lambda job: JobRunner(store, runs, *config.load(), timeout=30))
    context = DaemonContext(
        root=tmp_path,
        store=store,
        worker=worker,
        runs=runs,
        token="secret-token",
        version="0.1.0",
        config=config,
        topics=TopicStore(tmp_path),
        profiles=ProfileStore(tmp_path),
        on_shutdown=lambda: None,
    )
    srv = build_server(context)
    import threading

    threading.Thread(target=srv.serve_forever, daemon=True).start()
    worker.start()
    try:
        plan_file = tmp_path / "config" / "model-plan.toml"
        assert not plan_file.exists()  # setup uses the packaged fallback
        base_sha256 = config.plan_sha256()

        status, body = _req(
            srv.server_port,
            "PUT",
            "/v1/config/plan",
            body={
                "base_sha256": base_sha256,
                "provider": "claude-code",
                "stages": {"draft": {"model": "does-not-exist"}},
            },
        )
        assert status == 400
        assert body["error"]["code"] == "invalid_request"
        # The failed PUT wrote nothing: no workspace plan file was created.
        assert not plan_file.exists()
        assert config.plan_sha256() == base_sha256
    finally:
        worker.stop()
        srv.shutdown()


def _start_workspace_config_server(tmp_path):
    # Boots a server over a REAL WorkspaceConfigSource (not StaticConfigSource),
    # matching test_put_config_plan_unknown_model_returns_400_and_writes_nothing
    # above. Model ids are drawn from the packaged config/model-catalog.example.toml
    # fallback that WorkspaceConfigSource reads when the workspace has no catalog.
    register_runner(FakeRunner())
    runs = RunStore(tmp_path)
    runs.create_run("t", content_contract=ContentContract.legacy_markdown())
    config = WorkspaceConfigSource(tmp_path)
    store = JobStore(tmp_path)
    worker = Worker(store, lambda job: JobRunner(store, runs, *config.load(), timeout=30))
    context = DaemonContext(
        root=tmp_path,
        store=store,
        worker=worker,
        runs=runs,
        token="secret-token",
        version="0.1.0",
        config=config,
        topics=TopicStore(tmp_path),
        profiles=ProfileStore(tmp_path),
        on_shutdown=lambda: None,
    )
    srv = build_server(context)
    import threading

    threading.Thread(target=srv.serve_forever, daemon=True).start()
    worker.start()
    return srv, worker, config


def test_hand_edited_plan_toml_is_reflected_by_get_config_plan(tmp_path):
    # Regression for the spec criterion "a hand edit to model-plan.toml takes
    # effect": WorkspaceConfigSource re-reads config/model-plan.toml on every
    # request, so a file written directly to the workspace (as an advanced
    # user editing it in a text editor would) must show up verbatim over the
    # HTTP API without any daemon restart.
    plan_file = tmp_path / "config" / "model-plan.toml"
    plan_file.parent.mkdir(parents=True, exist_ok=True)
    plan_file.write_text(
        '\n'.join(
            [
                'provider = "claude-code"',
                "",
                "[stages.draft]",
                'model = "opus-4-8"',
                'effort = "high"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    expected_sha256 = hashlib.sha256(plan_file.read_bytes()).hexdigest()

    srv, worker, config = _start_workspace_config_server(tmp_path)
    try:
        status, payload = _req(srv.server_port, "GET", "/v1/config/plan")
        assert status == 200
        assert payload["provider"] == "claude-code"
        assert payload["plan_sha256"] == expected_sha256
        stages = {s["stage"]: s for s in payload["stages"]}
        assert stages["draft"]["provider"] == "claude-code"
        assert stages["draft"]["model"] == "opus-4-8"
        assert stages["draft"]["effort"] == "high"
        # Untouched stages keep their built-in defaults (recommendation-only,
        # no explicit model), proving the hand edit was merged, not replacing
        # the whole plan structure.
        assert stages["qa"]["model"] is None
        assert stages["qa"]["recommendation"] == "fast_cheap_check"
    finally:
        worker.stop()
        srv.shutdown()


def test_put_config_plan_round_trips_through_hand_editable_toml(tmp_path):
    # Regression for the spec criterion "...and round-trips through the UI":
    # a UI-issued PUT must produce a model-plan.toml file that (1) contains
    # exactly the edited values when read directly with tomllib, and (2) is
    # still a well-formed plan that load_model_plan can parse against the
    # catalog -- i.e. an advanced user can keep hand-editing the file the UI
    # wrote.
    srv, worker, config = _start_workspace_config_server(tmp_path)
    try:
        status, before = _req(srv.server_port, "GET", "/v1/config/plan")
        assert status == 200
        base_sha256 = before["plan_sha256"]

        status, updated = _req(
            srv.server_port,
            "PUT",
            "/v1/config/plan",
            body={
                "base_sha256": base_sha256,
                "provider": "claude-code",
                "stages": {
                    "draft": {"model": "opus-4-8", "effort": "high"},
                    "qa": {"provider": "codex", "model": "luna"},
                },
            },
        )
        assert status == 200
        assert updated["plan_sha256"] != base_sha256

        plan_file = tmp_path / "config" / "model-plan.toml"
        assert plan_file.exists()
        raw = tomllib.loads(plan_file.read_text(encoding="utf-8"))
        assert raw["provider"] == "claude-code"
        assert raw["stages"]["draft"]["model"] == "opus-4-8"
        assert raw["stages"]["draft"]["effort"] == "high"
        assert raw["stages"]["qa"]["provider"] == "codex"
        assert raw["stages"]["qa"]["model"] == "luna"
        # No stray top-level "provider" leaking into the qa stage table -- the
        # UI-written file is exactly what an advanced user would author by hand.
        assert "provider" not in raw["stages"]["draft"]

        catalog, _ = config.load()
        reparsed = load_model_plan(plan_file, catalog)
        assert reparsed.provider == "claude-code"
        draft = reparsed.stage("draft")
        assert draft.model == "opus-4-8"
        assert draft.effort == "high"
        qa = reparsed.stage("qa")
        assert qa.provider == "codex"
        assert qa.model == "luna"
    finally:
        worker.stop()
        srv.shutdown()


@pytest.fixture
def run_plan_server(tmp_path, monkeypatch):
    # Provider/model ids drawn from config/model-catalog.example.toml.
    catalog = parse_model_catalog(
        {
            "providers": [
                {"id": "manual", "models": [{"id": "prompt-only"}]},
                {
                    "id": "claude-code",
                    "models": [
                        {"id": "balanced", "argv_model": "claude-sonnet-5"},
                    ],
                },
            ]
        }
    )
    plan = parse_model_plan(
        {
            "provider": "claude-code",
            "stages": {
                "draft": {"model": "balanced"},
                "qa": {"provider": "manual", "model": "prompt-only"},
            },
        },
        catalog,
    )
    srv, worker, _context = _start_server(tmp_path, monkeypatch, catalog=catalog, plan=plan)
    yield srv.server_port
    worker.stop()
    srv.shutdown()


def test_run_plan_includes_source_and_command_preview(run_plan_server):
    status, payload = _req(run_plan_server, "GET", "/v1/runs/t/plan")
    assert status == 200
    assert len(payload["plan_sha256"]) == 64
    stages = {s["stage"]: s for s in payload["stages"]}
    assert set(stages) == set(STAGE_ORDER)
    assert all(s["source"] == "default" for s in stages.values())

    draft_command = stages["draft"]["command"]
    assert draft_command is not None
    assert draft_command[0] == "claude"
    assert "--model" in draft_command
    assert "claude-sonnet-5" in draft_command

    # manual provider -> no invocable command
    assert stages["qa"]["command"] is None
    # not a model-driven stage -> no invocable command regardless of provider
    assert stages["finalize"]["command"] is None


def test_run_plan_404_for_unknown_topic(run_plan_server):
    status, body = _req(run_plan_server, "GET", "/v1/runs/nope/plan")
    assert status == 404
    assert body["error"]["code"] == "not_found"


def test_put_run_plan_sets_override_then_clears_it(run_plan_server):
    status, updated = _req(
        run_plan_server,
        "PUT",
        "/v1/runs/t/plan",
        body={"overrides": {"draft": {"provider": "manual", "model": "prompt-only"}}},
    )
    assert status == 200
    stages = {s["stage"]: s for s in updated["stages"]}
    assert stages["draft"]["source"] == "override"
    assert stages["draft"]["provider"] == "manual"
    assert stages["draft"]["command"] is None  # manual provider -> no invocable command

    status, reread = _req(run_plan_server, "GET", "/v1/runs/t/plan")
    assert status == 200
    stages = {s["stage"]: s for s in reread["stages"]}
    assert stages["draft"]["source"] == "override"

    status, cleared = _req(
        run_plan_server, "PUT", "/v1/runs/t/plan", body={"overrides": {"draft": None}}
    )
    assert status == 200
    stages = {s["stage"]: s for s in cleared["stages"]}
    assert stages["draft"]["source"] == "default"
    assert stages["draft"]["command"] is not None


@pytest.mark.parametrize(
    "body",
    [
        {"overrides": "not-a-dict"},
        {"overrides": {"draft": "opus"}},
        {"overrides": {"draft": {"model": 5}}},
    ],
)
def test_put_run_plan_wrong_shape_nested_value_is_400_not_500(run_plan_server, body):
    status, payload = _req(run_plan_server, "PUT", "/v1/runs/t/plan", body=body)
    assert status == 400
    assert payload["error"]["code"] == "invalid_request"


def test_put_run_plan_invalid_model_is_400_and_overrides_unchanged(run_plan_server):
    status, body = _req(
        run_plan_server,
        "PUT",
        "/v1/runs/t/plan",
        body={"overrides": {"draft": {"model": "does-not-exist"}}},
    )
    assert status == 400
    assert body["error"]["code"] == "invalid_request"

    status, reread = _req(run_plan_server, "GET", "/v1/runs/t/plan")
    assert status == 200
    stages = {s["stage"]: s for s in reread["stages"]}
    assert stages["draft"]["source"] == "default"


def test_put_run_plan_unknown_topic_is_404(run_plan_server):
    status, body = _req(
        run_plan_server, "PUT", "/v1/runs/nope/plan", body={"overrides": {}}
    )
    assert status == 404
    assert body["error"]["code"] == "not_found"


def test_put_run_plan_missing_overrides_field_is_400(run_plan_server):
    status, body = _req(run_plan_server, "PUT", "/v1/runs/t/plan", body={})
    assert status == 400
    assert body["error"]["code"] == "invalid_request"


def test_get_run_plan_with_json_array_overrides_file_is_400_not_500(run_plan_server, tmp_path):
    RunStore(tmp_path).plan_overrides_path("t").write_text("[]", encoding="utf-8")

    status, body = _req(run_plan_server, "GET", "/v1/runs/t/plan")

    assert status == 400
    assert body["error"]["code"] == "invalid_request"


def test_get_run_plan_with_non_mapping_stages_overrides_file_is_400(run_plan_server, tmp_path):
    RunStore(tmp_path).plan_overrides_path("t").write_text(
        '{"stages": []}', encoding="utf-8"
    )

    status, body = _req(run_plan_server, "GET", "/v1/runs/t/plan")

    assert status == 400
    assert body["error"]["code"] == "invalid_request"


def test_get_run_plan_degrades_stage_when_stored_override_invalidated_by_catalog_change(
    tmp_path, monkeypatch
):
    catalog_v1 = parse_model_catalog(
        {
            "providers": [
                {"id": "manual", "models": [{"id": "prompt-only"}]},
                {
                    "id": "claude-code",
                    "models": [
                        {"id": "balanced", "argv_model": "claude-sonnet-5"},
                        {"id": "premium", "argv_model": "claude-opus-5"},
                    ],
                },
            ]
        }
    )
    plan = parse_model_plan(
        {
            "provider": "claude-code",
            "stages": {
                "draft": {"model": "balanced"},
                "qa": {"provider": "manual", "model": "prompt-only"},
            },
        },
        catalog_v1,
    )
    register_runner(FakeRunner())
    runs = RunStore(tmp_path)
    runs.create_run("t", content_contract=ContentContract.legacy_markdown())
    config = StaticConfigSource(catalog_v1, plan)
    store = JobStore(tmp_path)
    worker = Worker(store, lambda job: JobRunner(store, runs, catalog_v1, plan, timeout=30))
    context = DaemonContext(
        root=tmp_path,
        store=store,
        worker=worker,
        runs=runs,
        token="secret-token",
        version="0.1.0",
        config=config,
        topics=TopicStore(tmp_path),
        profiles=ProfileStore(tmp_path),
        on_shutdown=lambda: None,
    )
    srv = build_server(context)
    import threading

    threading.Thread(target=srv.serve_forever, daemon=True).start()
    worker.start()
    try:
        # Store a valid override while the "premium" model still exists.
        status, updated = _req(
            srv.server_port,
            "PUT",
            "/v1/runs/t/plan",
            body={"overrides": {"draft": {"model": "premium"}}},
        )
        assert status == 200
        stages = {s["stage"]: s for s in updated["stages"]}
        assert stages["draft"]["source"] == "override"
        assert "override_error" not in stages["draft"]

        # The global catalog is edited -- "premium" no longer exists.
        catalog_v2 = parse_model_catalog(
            {
                "providers": [
                    {"id": "manual", "models": [{"id": "prompt-only"}]},
                    {
                        "id": "claude-code",
                        "models": [{"id": "balanced", "argv_model": "claude-sonnet-5"}],
                    },
                ]
            }
        )
        config.catalog = catalog_v2

        # GET must still return 200, not 400.
        status, payload = _req(srv.server_port, "GET", "/v1/runs/t/plan")
        assert status == 200
        stages = {s["stage"]: s for s in payload["stages"]}
        assert stages["draft"]["source"] == "override"
        assert stages["draft"].get("override_error")
        assert "premium" in stages["draft"]["override_error"]
        # Effective values fall back to what would ACTUALLY run (the
        # override is refused), not to the invalid override itself.
        assert stages["draft"]["model"] == "balanced"
        # A broken stage's command preview must not look runnable -- enqueue
        # of this stage 400s below, so the UI shouldn't show a command as if
        # it would actually execute.
        assert stages["draft"]["command"] is None
        # Other stages are unaffected.
        assert stages["qa"]["source"] == "default"
        assert "override_error" not in stages["qa"]

        # Enqueue of the broken stage 400s with the override message; a
        # different stage enqueues fine.
        status, body = _req(
            srv.server_port,
            "POST",
            "/v1/jobs",
            body={"topic_id": "t", "stage": "draft"},
        )
        assert status == 400
        assert "premium" in body["error"]["message"]

        status, body = _req(
            srv.server_port,
            "POST",
            "/v1/jobs",
            body={"topic_id": "t", "stage": "qa"},
        )
        assert status == 200

        # Clearing the broken stage while it's broken succeeds.
        status, cleared = _req(
            srv.server_port, "PUT", "/v1/runs/t/plan", body={"overrides": {"draft": None}}
        )
        assert status == 200
        stages = {s["stage"]: s for s in cleared["stages"]}
        assert stages["draft"]["source"] == "default"
        assert "override_error" not in stages["draft"]

        # Re-setting the broken stage to a still-invalid value stays 400.
        status, body = _req(
            srv.server_port,
            "PUT",
            "/v1/runs/t/plan",
            body={"overrides": {"draft": {"model": "premium"}}},
        )
        assert status == 400
        assert body["error"]["code"] == "invalid_request"
    finally:
        worker.stop()
        srv.shutdown()


# ---------------------------------------------------------------------------
# Course library: enriched list, archive, duplicate, reveal (spec §5)


def _topic_entry(port, topic_id):
    status, body = _req(port, "GET", "/v1/topics")
    assert status == 200
    return next(t for t in body["topics"] if t["id"] == topic_id)


def test_topics_list_is_enriched(server):
    entry = _topic_entry(server, "t")
    assert entry["archived"] is False
    assert isinstance(entry["last_activity"], str)
    assert entry["profile_id"] is None
    completion = entry["completion"]
    assert completion["stages_total"] == 5
    assert completion["stages_approved"] == 0
    assert completion["exported"] is False


def test_topics_list_enrichment_null_without_run(server_with_context):
    port, context = server_with_context
    (context.root / "topics" / "norun.toml").write_text(
        'schema_version = 1\nid = "norun"\ntitle = "No Run"\n', encoding="utf-8"
    )
    entry = _topic_entry(port, "norun")
    assert entry["run"] is None
    assert entry["archived"] is False
    assert entry["last_activity"] is None
    assert entry["completion"] is None


def test_topics_list_reports_attached_profile_id(server_with_context):
    port, context = server_with_context
    status, _ = _req(
        port, "POST", "/v1/topics/t/profile", body={"profile_id": "p"}
    )
    assert status == 200
    assert _topic_entry(port, "t")["profile_id"] == "p"


def test_archive_route_flips_flag_and_hides_nothing(server_with_context):
    port, context = server_with_context
    status, body = _req(port, "POST", "/v1/runs/t/archive", body={})
    assert status == 200
    assert body["archived"] is True
    assert _topic_entry(port, "t")["archived"] is True
    # Reads still work on an archived course.
    status, _ = _req(port, "GET", "/v1/runs/t")
    assert status == 200
    status, body = _req(port, "POST", "/v1/runs/t/unarchive", body={})
    assert status == 200
    assert body["archived"] is False


def test_archive_route_404_without_run(server_with_context):
    port, context = server_with_context
    (context.root / "topics" / "norun.toml").write_text(
        'schema_version = 1\nid = "norun"\ntitle = "No Run"\n', encoding="utf-8"
    )
    status, body = _req(port, "POST", "/v1/runs/norun/archive", body={})
    assert status == 404
    assert body["error"]["code"] == "not_found"


def test_archived_course_blocks_writes_over_http(server):
    status, _ = _req(server, "POST", "/v1/runs/t/archive", body={})
    assert status == 200
    status, body = _req(server, "POST", "/v1/runs/t/advance", body={})
    assert status == 409
    assert body["error"]["code"] == "archived_course"
    status, body = _req(
        server, "POST", "/v1/jobs", body={"topic_id": "t", "stage": "draft"}
    )
    assert status == 409
    assert body["error"]["code"] == "archived_course"


def test_duplicate_route_creates_copy(server):
    status, body = _req(server, "POST", "/v1/topics/t/duplicate", body={})
    assert status == 201
    assert body == {"id": "t-copy", "title": "Test Topic"}
    entry = _topic_entry(server, "t-copy")
    assert entry["run"] is None


def test_reveal_route_success_returns_path(server_with_context, monkeypatch):
    port, context = server_with_context
    monkeypatch.setenv("EP_REVEAL_OPENER", shutil.which("true"))
    status, body = _req(
        port, "POST", "/v1/reveal", body={"target": "run", "topic_id": "t"}
    )
    assert status == 200
    assert body["path"] == str(context.runs.run_dir("t").resolve())


def test_reveal_route_failure_is_reveal_unsupported_with_path(
    server_with_context, monkeypatch
):
    port, context = server_with_context
    monkeypatch.setenv("EP_REVEAL_OPENER", shutil.which("false"))
    status, body = _req(
        port, "POST", "/v1/reveal", body={"target": "run", "topic_id": "t"}
    )
    assert status == 422
    assert body["error"]["code"] == "reveal_unsupported"
    assert body["error"]["detail"]["path"] == str(context.runs.run_dir("t").resolve())


def test_reveal_route_rejects_unknown_target(server, monkeypatch):
    monkeypatch.setenv("EP_REVEAL_OPENER", shutil.which("true"))
    status, body = _req(
        server, "POST", "/v1/reveal", body={"target": "responses", "topic_id": "t"}
    )
    assert status == 400
    assert body["error"]["code"] == "invalid_request"


# ---------------------------------------------------------------------------
# Workspace read endpoint (spec §4.1)


def test_workspace_payload_counts_and_first_run(server_with_context):
    port, context = server_with_context
    status, body = _req(port, "GET", "/v1/workspace")
    assert status == 200
    assert body["path"] == str(context.root)
    # Fixture workspace: two topics with runs, one profile.
    assert body["counts"] == {"topics": 2, "runs": 2, "profiles": 1}
    assert body["first_run"] is False


def test_workspace_first_run_true_with_zero_runs(tmp_path, monkeypatch):
    import shutil

    ws = tmp_path / "fresh"
    (ws / "topics").mkdir(parents=True)
    srv, worker, context = _start_server(ws, monkeypatch)
    try:
        shutil.rmtree(ws / "runs")
        status, body = _req(srv.server_port, "GET", "/v1/workspace")
        assert status == 200
        assert body["counts"]["runs"] == 0
        assert body["first_run"] is True
    finally:
        worker.stop()
        srv.shutdown()


def test_workspace_requires_token(server):
    status, body = _req(server, "GET", "/v1/workspace", token="wrong")
    assert status == 401
