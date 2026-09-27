"""T62a red: ``GET /v1/events`` over a real loopback server.

Pins the route as the reviewed design note describes it
(``docs/superpowers/specs/2026-09-27-events-endpoint-design.md`` §1, §2, §4,
§5 and the §7 test plan): the Host check and the token guard run before a
stream slot is taken; a ``200 text/event-stream`` answer is close-delimited
and opens with a ``hello`` frame; notices arrive as byte-exact ``change``
frames; the fifth concurrent stream gets the ``events_capacity`` envelope; a
stream keeps alive, ends at its lifetime, frees its slot on disconnect or on a
failed header/hello write, and ends when the hub closes or the daemon shuts
down.

Every test builds its own small-valued hub and swaps it into the live
``DaemonContext`` (``server_with_context``), so a fake ``clock`` drives the
heartbeat and lifetime deadlines while the real waits stay short
(``liveness_seconds``). The fixture closes whatever hub the context holds in
teardown. Every socket read carries a timeout, so a missing implementation
fails instead of hanging.
"""

from __future__ import annotations

import dataclasses
import http.client
import http.server
import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from education_pipeline import ContentContract, RunStore
from education_pipeline.daemon import lifecycle, serve
from education_pipeline.daemon.jobs import Job
from test_server import _raw_get, _req, server_with_context  # noqa: F401 (fixture)

TOKEN = "secret-token"
REPO_ROOT = Path(__file__).resolve().parent.parent

HELLO_DEFAULT = (
    b'event: hello\ndata: {"heartbeat_seconds":15,"lifetime_seconds":300,"protocol":1}\n\n'
)
KEEPALIVE = b": keepalive\n\n"
FRAME_TOPICS = b'event: change\ndata: {"kind":"topics"}\n\n'
FRAME_JOBS = b'event: change\ndata: {"kind":"jobs"}\n\n'


def frame_run(topic: str) -> bytes:
    return b'event: change\ndata: {"kind":"run","topic":"' + topic.encode("ascii") + b'"}\n\n'


def _events():
    from education_pipeline.daemon import events

    return events


class FakeClock:
    """A monotonic clock the test advances by hand (the hub's ``clock`` hook)."""

    def __init__(self, start: float = 1000.0) -> None:
        self._now = start
        self._lock = threading.Lock()

    def __call__(self) -> float:
        with self._lock:
            return self._now

    def advance(self, seconds: float) -> None:
        with self._lock:
            self._now += seconds


class _Stream:
    """A raw-socket client for one request; reads with deadlines, never blocks."""

    def __init__(
        self,
        port: int,
        *,
        path: str = "/v1/events",
        host: str = "127.0.0.1",
        token: str | None = TOKEN,
        method: str = "GET",
        timeout: float = 5.0,
    ) -> None:
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=timeout)
        lines = [f"{method} {path} HTTP/1.1", f"Host: {host}"]
        if token is not None:
            lines.append(f"X-EP-Token: {token}")
        lines.append("Accept: text/event-stream")
        self.sock.sendall(("\r\n".join(lines) + "\r\n\r\n").encode("ascii"))
        self.buf = b""
        self.eof = False
        head = self._read_until(b"\r\n\r\n", timeout).decode("iso-8859-1")
        status_line, *header_lines = head[:-4].split("\r\n")
        self.status_line = status_line
        self.status = int(status_line.split()[1])
        self.headers: dict[str, str] = {}
        for line in header_lines:
            name, _, value = line.partition(":")
            self.headers[name.strip().lower()] = value.strip()

    def _recv(self, deadline: float) -> bytes:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("no data before the deadline")
        self.sock.settimeout(remaining)
        chunk = self.sock.recv(65536)
        if not chunk:
            self.eof = True
        return chunk

    def _read_until(self, marker: bytes, timeout: float) -> bytes:
        deadline = time.monotonic() + timeout
        while marker not in self.buf:
            if self.eof:
                raise EOFError(f"stream ended before {marker!r}; got {self.buf!r}")
            self.buf += self._recv(deadline)
        end = self.buf.index(marker) + len(marker)
        out, self.buf = self.buf[:end], self.buf[end:]
        return out

    def body(self, timeout: float = 5.0) -> bytes:
        length = int(self.headers.get("content-length", "0"))
        deadline = time.monotonic() + timeout
        while len(self.buf) < length:
            chunk = self._recv(deadline)
            if not chunk:
                break
            self.buf += chunk
        out, self.buf = self.buf[:length], self.buf[length:]
        return out

    def frame(self, timeout: float = 3.0) -> bytes:
        """The next SSE frame (comment or event), through its blank line."""

        return self._read_until(b"\n\n", timeout)

    def change_frame(self, timeout: float = 3.0) -> bytes:
        """The next frame that is not a keepalive comment."""

        deadline = time.monotonic() + timeout
        while True:
            frame = self.frame(max(0.001, deadline - time.monotonic()))
            if frame != KEEPALIVE:
                return frame

    def collect(self, seconds: float) -> bytes:
        """Every byte that arrives within ``seconds`` (stops early at EOF)."""

        deadline = time.monotonic() + seconds
        while not self.eof:
            try:
                self.buf += self._recv(deadline)
            except (TimeoutError, socket.timeout):
                break
        out, self.buf = self.buf, b""
        return out

    def silent_for(self, seconds: float) -> bool:
        return self.collect(seconds) == b"" and not self.eof

    def read_to_eof(self, timeout: float = 3.0) -> bytes:
        deadline = time.monotonic() + timeout
        while not self.eof:
            self.buf += self._recv(deadline)
        out, self.buf = self.buf, b""
        return out

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


def _only_keepalives(data: bytes) -> bool:
    return data.replace(KEEPALIVE, b"") == b""


def _until(predicate, timeout: float = 3.0, interval: float = 0.01) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return bool(predicate())


def _install_hub(context, **overrides):
    """Swap a small-valued hub into the live context, as the note's hooks allow."""

    kwargs = {
        "heartbeat_seconds": 15,
        "lifetime_seconds": 300,
        "liveness_seconds": 0.05,
        "scan_interval_seconds": None,
    }
    kwargs.update(overrides)
    hub = _events().EventHub(context.root, **kwargs)
    context.events = hub
    return hub


def _count_subscribes(monkeypatch) -> list:
    events = _events()
    calls: list = []
    real = events.EventHub.subscribe

    def counting(self):
        calls.append(1)
        return real(self)

    monkeypatch.setattr(events.EventHub, "subscribe", counting)
    return calls


@pytest.fixture
def events_server(server_with_context):  # noqa: F811
    port, context = server_with_context
    opened: list[_Stream] = []

    def open_stream(**kwargs) -> _Stream:
        stream = _Stream(port, **kwargs)
        opened.append(stream)
        return stream

    yield SimpleNamespace(port=port, context=context, open=open_stream)
    for stream in opened:
        stream.close()
    close = getattr(getattr(context, "events", None), "close", None)
    if callable(close):
        close()


def _assert_stream_opens(server, **kwargs) -> _Stream:
    stream = server.open(**kwargs)
    assert stream.status == 200, stream.status_line
    assert stream.headers.get("content-type") == "text/event-stream; charset=utf-8"
    assert stream.frame().startswith(b"event: hello\n")
    return stream


# ---------------------------------------------------------------------------
# Auth and routing: rejected before any stream bytes, and before a slot
# ---------------------------------------------------------------------------


def test_events_rejects_bad_host(events_server, monkeypatch):
    hub = _install_hub(events_server.context)
    calls = _count_subscribes(monkeypatch)

    for host in ("evil.example.com", "evil.example.com:80", "127.0.0.1.evil.example", ""):
        status, body, headers = _raw_get(events_server.port, "/v1/events", host=host, token=TOKEN)
        assert status == 400, host
        assert headers["Content-Type"] == "application/json", host
        assert json.loads(body)["error"]["code"] == "bad_host", host
        assert b"event:" not in body
    assert calls == []
    assert hub.stream_count == 0

    # The Vite dev proxy forwards Host: localhost:5173, and the port is stripped.
    _assert_stream_opens(events_server, host="localhost:5173")
    assert calls == [1]
    assert hub.stream_count == 1


def test_events_rejects_missing_and_wrong_token(events_server, monkeypatch):
    hub = _install_hub(events_server.context)
    calls = _count_subscribes(monkeypatch)

    for token in (None, "wrong", "secret-tokeN", "x" * 1024):
        status, body = _req(events_server.port, "GET", "/v1/events", token=token)
        assert status == 401, token
        assert body["error"]["code"] == "unauthorized", token
    assert calls == []
    assert hub.stream_count == 0

    _assert_stream_opens(events_server)
    assert calls == [1]


def test_events_query_string_token_is_not_accepted(events_server, monkeypatch):
    hub = _install_hub(events_server.context)
    calls = _count_subscribes(monkeypatch)
    port = events_server.port

    # No query-string credential, ever.
    for path in ("/v1/events?token=secret-token", "/v1/events?X-EP-Token=secret-token"):
        status, body = _req(port, "GET", path, token=None)
        assert status == 401, path
        assert body["error"]["code"] == "unauthorized", path

    # The match is exact: other spellings are ordinary 404s after auth.
    for path in ("/v1/events?since=0", "/v1/events/", "/v1/events/x"):
        status, body = _req(port, "GET", path)
        assert status == 404, path
        assert body["error"]["code"] == "not_found", path

    # A doubled leading slash never streams without the token.
    status, body, headers = _raw_get(port, "//v1/events", host="127.0.0.1")
    assert status != 200
    assert "event-stream" not in headers.get("Content-Type", "")

    assert calls == []
    assert hub.stream_count == 0
    _assert_stream_opens(events_server)
    assert calls == [1]


def test_events_other_methods_and_absolute_form_never_stream(events_server, monkeypatch):
    hub = _install_hub(events_server.context)
    calls = _count_subscribes(monkeypatch)
    port = events_server.port

    # No do_HEAD / do_OPTIONS: the stdlib answers 501, so a CORS preflight fails.
    for method in ("HEAD", "OPTIONS"):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            conn.request(method, "/v1/events", headers={"X-EP-Token": TOKEN})
            resp = conn.getresponse()
            resp.read()
            assert resp.status == 501, method
            assert not any(
                name.lower().startswith("access-control") for name, _ in resp.getheaders()
            )
        finally:
            conn.close()

    # An absolute-form target falls through to static serving.
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.putrequest("GET", f"http://127.0.0.1:{port}/v1/events", skip_host=True)
        conn.putheader("Host", "127.0.0.1")
        conn.putheader("X-EP-Token", TOKEN)
        conn.endheaders()
        resp = conn.getresponse()
        resp.read()
        assert "event-stream" not in (resp.getheader("Content-Type") or "")
    finally:
        conn.close()

    assert calls == []
    assert hub.stream_count == 0
    _assert_stream_opens(events_server)
    assert calls == [1]


# ---------------------------------------------------------------------------
# Framing, hello and change frames
# ---------------------------------------------------------------------------


def test_events_headers_and_hello_frame(events_server):
    hub = _install_hub(events_server.context)
    stream = events_server.open()

    assert stream.status_line == "HTTP/1.1 200 OK"
    assert stream.headers["content-type"] == "text/event-stream; charset=utf-8"
    assert stream.headers["cache-control"] == "no-store"
    assert stream.headers["connection"] == "close"
    # Close-delimited: no length, no chunking.
    assert "content-length" not in stream.headers
    assert "transfer-encoding" not in stream.headers
    assert not any(name.startswith("access-control") for name in stream.headers)

    assert stream.frame() == HELLO_DEFAULT
    assert hub.stream_count == 1
    assert stream.silent_for(0.3)


def test_daemon_context_builds_a_default_hub_that_serves_the_route(events_server):
    events = _events()
    context = events_server.context
    hub = context.events
    assert isinstance(hub, events.EventHub)
    # A hub starts no thread until something subscribes.
    assert hub.scanning is False
    assert hub.stream_count == 0

    stream = events_server.open()
    assert stream.status == 200
    assert stream.frame() == HELLO_DEFAULT
    assert hub.stream_count == 1

    explicit = events.EventHub(context.root, scan_interval_seconds=None)
    try:
        assert dataclasses.replace(context, events=explicit).events is explicit
    finally:
        explicit.close()
    fresh = dataclasses.replace(context, events=None).events
    try:
        assert isinstance(fresh, events.EventHub)
        assert fresh is not hub
    finally:
        fresh.close()


def test_events_job_save_notices_jobs_and_run_immediately(events_server):
    context = events_server.context
    hub = _install_hub(context)  # no scanner: only the nudge can speak
    context.store.on_saved = lambda job: hub.job_saved(job.topic_id)  # as serve() wires it
    stream = events_server.open()
    assert stream.status == 200
    assert stream.frame() == HELLO_DEFAULT

    job = context.store.create("t", "draft", "fake", "m", None)
    context.store.save(job)

    assert stream.frame() == FRAME_JOBS
    assert stream.frame() == frame_run("t")
    assert stream.silent_for(0.2)


def test_events_burst_coalesces_to_one_frame_per_notice(events_server):
    context = events_server.context
    root = context.root
    hub = _install_hub(context)
    stream = events_server.open()
    assert stream.frame() == HELLO_DEFAULT

    # A burst between two passes: many run writes, several job records, a profile.
    for index in range(10):
        (root / "runs" / "t" / f"burst-{index}.md").write_text("x" * index, encoding="utf-8")
    for _ in range(3):
        job = context.store.create("t", "draft", "fake", "m", None)
        context.store.save(job)
    (root / "profiles" / "q.toml").write_text(
        'schema_version = 1\nid = "q"\ntarget_learner = "q"\n', encoding="utf-8"
    )
    hub.scan_once()

    assert stream.frame() == FRAME_TOPICS
    assert stream.frame() == FRAME_JOBS
    assert stream.frame() == frame_run("t")
    assert stream.silent_for(0.3)


def test_events_change_after_cli_advance_out_of_process(events_server):
    context = events_server.context
    hub = _install_hub(context, scan_interval_seconds=0.05)
    stream = events_server.open()
    assert stream.frame() == HELLO_DEFAULT
    assert hub.scanning is True

    # The CLI writes the workspace directly, in another process.
    result = subprocess.run(
        [sys.executable, "-m", "education_pipeline", "-C", str(context.root), "advance", "g"],
        cwd=REPO_ROOT,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")

    assert stream.change_frame(timeout=10.0) == frame_run("g")
    # Whatever else the scan saw of that write names the same run.
    trailing = stream.collect(0.3).replace(KEEPALIVE, b"")
    assert trailing.replace(frame_run("g"), b"") == b""


# ---------------------------------------------------------------------------
# The cap
# ---------------------------------------------------------------------------


def test_events_cap_answers_503_envelope(events_server):
    hub = _install_hub(events_server.context)  # the default cap, MAX_STREAMS = 4
    streams = [_assert_stream_opens(events_server) for _ in range(4)]
    assert hub.stream_count == 4

    conn = http.client.HTTPConnection("127.0.0.1", events_server.port, timeout=5)
    try:
        conn.request("GET", "/v1/events", headers={"X-EP-Token": TOKEN})
        resp = conn.getresponse()
        body = json.loads(resp.read())
        assert resp.status == 503
        assert resp.getheader("Content-Type") == "application/json"
        assert body == {
            "error": {
                "code": "events_capacity",
                "message": "event stream limit reached; poll instead",
            }
        }
        # An ordinary keep-alive answer: the same connection serves the next request.
        assert not resp.will_close
        sock = conn.sock
        conn.request("GET", "/v1/health", headers={"X-EP-Token": TOKEN})
        health = conn.getresponse()
        health.read()
        assert health.status == 200
        assert conn.sock is sock
    finally:
        conn.close()
    assert hub.stream_count == 4

    # Closing one stream frees its slot.
    streams[0].close()
    assert _until(lambda: hub.stream_count == 3)
    _assert_stream_opens(events_server)
    assert hub.stream_count == 4


def test_events_capacity_is_a_registered_error_code():
    # Every code the daemon emits is catalogued (tests/test_errors.py), and
    # every catalogued code is documented (tests/test_troubleshooting_doc.py).
    from education_pipeline.errors import ERROR_CATALOG

    assert "events_capacity" in ERROR_CATALOG


def test_events_client_disconnect_frees_the_slot(events_server):
    hub = _install_hub(events_server.context, max_streams=1)
    first = _assert_stream_opens(events_server)
    status, body = _req(events_server.port, "GET", "/v1/events")
    assert status == 503
    assert body["error"]["code"] == "events_capacity"

    # Heartbeats are 15 s away: only the readability check can see this close.
    first.close()
    assert _until(lambda: hub.stream_count == 0, timeout=3.0)
    second = events_server.open()
    assert second.status == 200
    assert second.frame() == HELLO_DEFAULT


@pytest.mark.parametrize("failure", ["headers-oserror", "hello-oserror", "hello-error"])
def test_events_slot_is_freed_when_headers_or_hello_write_fails(
    events_server, monkeypatch, failure
):
    events = _events()
    hub = _install_hub(events_server.context, max_streams=1)
    hello_calls = []

    with monkeypatch.context() as patch:
        if failure == "headers-oserror":
            real_end_headers = http.server.BaseHTTPRequestHandler.end_headers

            def failing_end_headers(self):
                if self.path == "/v1/events":
                    raise BrokenPipeError("peer went away before the headers")
                return real_end_headers(self)

            patch.setattr(http.server.BaseHTTPRequestHandler, "end_headers", failing_end_headers)
        else:
            error = BrokenPipeError if failure == "hello-oserror" else RuntimeError

            def failing_hello(self):
                hello_calls.append(1)
                raise error("the hello write failed")

            patch.setattr(events.EventHub, "hello_payload", failing_hello)

        for _ in range(3):  # more attempts than the cap allows
            sock = socket.create_connection(("127.0.0.1", events_server.port), timeout=5)
            try:
                sock.sendall(
                    f"GET /v1/events HTTP/1.1\r\nHost: 127.0.0.1\r\nX-EP-Token: {TOKEN}\r\n\r\n".encode(
                        "ascii"
                    )
                )
                received = b""
                deadline = time.monotonic() + 1.0
                while time.monotonic() < deadline:
                    sock.settimeout(max(0.01, deadline - time.monotonic()))
                    try:
                        chunk = sock.recv(65536)
                    except (TimeoutError, socket.timeout):
                        break
                    if not chunk:
                        break
                    received += chunk
                assert b"event: hello" not in received
            finally:
                sock.close()
            assert _until(lambda: hub.stream_count == 0, timeout=2.0)

    if failure != "headers-oserror":
        assert hello_calls, "the handler builds its hello frame from hub.hello_payload()"
    # The slot came back every time: a real stream still fits under a cap of one.
    stream = events_server.open()
    assert stream.status == 200
    assert stream.frame() == HELLO_DEFAULT


# ---------------------------------------------------------------------------
# Heartbeat and lifetime, on a fake clock
# ---------------------------------------------------------------------------


def test_events_heartbeat_comment_when_idle(events_server):
    clock = FakeClock()
    hub = _install_hub(events_server.context, clock=clock, liveness_seconds=0.02)
    stream = events_server.open()
    assert stream.frame() == HELLO_DEFAULT

    # Real time passing is not what triggers the heartbeat: the clock is.
    # (Offsets are binary-exact and step past each due time, so neither float
    # rounding nor >= versus > decides the outcome.)
    assert stream.silent_for(0.3)
    clock.advance(14.5)  # t = 14.5
    assert stream.silent_for(0.3)
    clock.advance(1.0)  # t = 15.5: 15 s with no other write
    assert stream.frame(timeout=2.0) == KEEPALIVE
    assert stream.silent_for(0.3)

    # Any other write resets the heartbeat.
    clock.advance(10)  # t = 25.5
    time.sleep(0.1)  # let the handler's loop read the new time first
    hub.job_saved("t")
    assert stream.frame() == FRAME_JOBS
    assert stream.frame() == frame_run("t")
    clock.advance(10)  # t = 35.5: 20 s after the keepalive, 10 s after the notices
    assert stream.silent_for(0.3)
    clock.advance(5.5)  # t = 41: past 15 s after the notices
    assert stream.frame(timeout=2.0) == KEEPALIVE


def test_events_stream_ends_at_max_lifetime(events_server):
    clock = FakeClock()
    hub = _install_hub(events_server.context, clock=clock, liveness_seconds=0.02)
    stream = events_server.open()
    assert stream.frame() == HELLO_DEFAULT

    assert stream.silent_for(0.3)
    clock.advance(299.5)
    before_deadline = stream.collect(0.3)
    assert not stream.eof, "the stream ended before its lifetime"
    assert _only_keepalives(before_deadline)

    clock.advance(1.0)  # past 300 s after hello
    tail = stream.read_to_eof(timeout=2.0)
    assert _only_keepalives(tail)
    assert _until(lambda: hub.stream_count == 0)


# ---------------------------------------------------------------------------
# Shutdown
# ---------------------------------------------------------------------------


def test_events_hub_close_releases_open_streams(events_server):
    # Long liveness waits: only close() can end these streams promptly.
    hub = _install_hub(events_server.context, liveness_seconds=5.0)
    streams = [_assert_stream_opens(events_server) for _ in range(2)]
    assert hub.stream_count == 2

    started = time.monotonic()
    hub.close()
    for stream in streams:
        assert _only_keepalives(stream.read_to_eof(timeout=2.0))
    assert time.monotonic() - started < 2.0
    assert _until(lambda: hub.stream_count == 0)

    # A closed hub takes no new stream.
    status, body = _req(events_server.port, "GET", "/v1/events")
    assert status == 503
    assert body["error"]["code"] == "events_capacity"


def _start_serve(tmp_path):
    RunStore(tmp_path).create_run("t", content_contract=ContentContract.legacy_markdown())
    ready = threading.Event()
    thread = threading.Thread(target=serve, args=(tmp_path,), kwargs={"ready": ready}, daemon=True)
    thread.start()
    assert ready.wait(timeout=10)
    record = lifecycle.read_discovery(tmp_path)
    assert record is not None
    return thread, record


def _shutdown(record) -> None:
    conn = http.client.HTTPConnection("127.0.0.1", record["port"], timeout=5)
    try:
        conn.request("POST", "/v1/shutdown", headers={"X-EP-Token": record["token"]})
        conn.getresponse().read()
    finally:
        conn.close()


def test_serve_shutdown_releases_streams(tmp_path):
    thread, record = _start_serve(tmp_path)
    stream = None
    try:
        stream = _Stream(record["port"], token=record["token"])
        assert stream.status == 200
        assert stream.frame() == HELLO_DEFAULT

        started = time.monotonic()
        _shutdown(record)
        assert _only_keepalives(stream.read_to_eof(timeout=3.0))
        assert time.monotonic() - started < 3.0
        thread.join(timeout=5)
        assert not thread.is_alive()
        assert lifecycle.read_discovery(tmp_path) is None
    finally:
        if stream is not None:
            stream.close()
        if thread.is_alive():
            try:
                _shutdown(record)
            except OSError:
                pass
            thread.join(timeout=5)


def test_serve_wires_job_store_nudge_to_the_hub(tmp_path, monkeypatch):
    from education_pipeline import daemon as daemon_module

    events = _events()
    captured = {}
    real_build_server = daemon_module.build_server

    def spy_build_server(context, *args, **kwargs):
        captured["context"] = context
        return real_build_server(context, *args, **kwargs)

    monkeypatch.setattr(daemon_module, "build_server", spy_build_server)
    thread, record = _start_serve(tmp_path)
    try:
        context = captured["context"]
        hub = context.events
        assert isinstance(hub, events.EventHub)
        assert hub.scanning is False
        assert callable(context.store.on_saved)

        sub = hub.subscribe()
        assert sub is not None
        # No such run on disk, so only the nudge can name it.
        context.store.on_saved(
            Job(
                id="20260927T000000Z-abcd",
                topic_id="zz",
                stage="draft",
                provider="manual",
                model=None,
                effort=None,
            )
        )
        got = hub.wait(sub, 0)
        assert {"kind": "jobs"} in got
        assert {"kind": "run", "topic": "zz"} in got
        hub.unsubscribe(sub)
    finally:
        try:
            _shutdown(record)
        except OSError:
            pass
        thread.join(timeout=5)
    assert not thread.is_alive()
    # serve() closed the hub on the way out.
    assert captured["context"].events.subscribe() is None
