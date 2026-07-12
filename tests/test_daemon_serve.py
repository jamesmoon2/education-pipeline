import http.client
import json
import os
import threading
import time
from pathlib import Path

import pytest

from education_pipeline import ContentContract, RunStore
from education_pipeline.config import ConfigError
from education_pipeline.daemon import serve
from education_pipeline.daemon import lifecycle


def _health(port, token):
    conn = http.client.HTTPConnection("127.0.0.1", port)
    conn.request("GET", "/v1/health", headers={"X-EP-Token": token})
    resp = conn.getresponse()
    body = json.loads(resp.read())
    conn.close()
    return resp.status, body


def test_serve_writes_discovery_and_serves_health(tmp_path):
    RunStore(tmp_path).create_run("t", content_contract=ContentContract.legacy_markdown())
    ready = threading.Event()
    thread = threading.Thread(target=serve, args=(tmp_path,), kwargs={"ready": ready}, daemon=True)
    thread.start()
    assert ready.wait(timeout=10)
    record = lifecycle.read_discovery(tmp_path)
    assert record is not None
    status, body = _health(record["port"], record["token"])
    assert status == 200
    # graceful shutdown via the API
    conn = http.client.HTTPConnection("127.0.0.1", record["port"])
    conn.request("POST", "/v1/shutdown", headers={"X-EP-Token": record["token"]})
    conn.getresponse().read()
    conn.close()
    thread.join(timeout=10)
    assert lifecycle.read_discovery(tmp_path) is None


def test_serve_refuses_when_workspace_already_claimed(tmp_path):
    RunStore(tmp_path).create_run("t", content_contract=ContentContract.legacy_markdown())
    lifecycle.write_discovery(tmp_path, pid=os.getpid(), port=1, token="x", version="0.1.0")
    with pytest.raises(ConfigError):
        serve(tmp_path)
