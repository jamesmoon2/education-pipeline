from __future__ import annotations

import sys
import threading
from pathlib import Path

from education_pipeline import RunStore
from education_pipeline.cli import main
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
        return ProviderResponse(text=stdout, metadata={"echo": True})


def _write_config(ws: Path):
    cfg = ws / "config"
    cfg.mkdir()
    (cfg / "model-catalog.toml").write_text(
        '[[providers]]\nid = "fake"\n[[providers.models]]\nid = "m"\n', encoding="utf-8"
    )
    (cfg / "model-plan.toml").write_text(
        'provider = "fake"\n[stages.spec]\nmodel = "m"\n', encoding="utf-8"
    )


def test_full_run_via_cli_lands_response_and_manifest_event(tmp_path, monkeypatch):
    register_runner(FakeRunner())
    monkeypatch.setenv("FAKE_STDOUT", "# Executed spec\n")
    _write_config(tmp_path)
    runs = RunStore(tmp_path)
    runs.write_spec_prompt("systems-thinking", title="Systems Thinking")  # next action: save_response(spec)

    # `ensure_daemon` normally autostarts the daemon as a separate OS process
    # (a fresh interpreter that only knows the built-in providers), which
    # can't see the FakeRunner registered above in this test process. Run the
    # real daemon code path (`serve()`) in a background thread of this
    # process instead, so the shared provider registry includes "fake". Only
    # redirect the specific daemon-spawn argv -- the worker's own
    # subprocess.Popen calls (to run fake_provider.py per job) must go
    # through unmodified, since client.py's `subprocess` is the same module
    # object used by the daemon's job runner.
    import subprocess

    from education_pipeline.daemon import serve

    real_popen = subprocess.Popen

    def _thread_popen(argv, **kwargs):
        if len(argv) >= 3 and argv[1:3] == ["-m", "education_pipeline.daemon"]:
            root = argv[-1]
            ready = threading.Event()
            threading.Thread(
                target=serve, args=(root,), kwargs={"ready": ready}, daemon=True
            ).start()
            # `serve()` sets this only after writing the full discovery record
            # (with port), avoiding a race against the placeholder pid-only
            # record `claim_discovery` writes first.
            ready.wait(timeout=5)
            return None
        return real_popen(argv, **kwargs)

    monkeypatch.setattr("education_pipeline.client.subprocess.Popen", _thread_popen)

    code = main(["-C", str(tmp_path), "run", "systems-thinking", "--wait"])
    assert code == 0
    assert runs.response_path("systems-thinking", "spec").read_text(encoding="utf-8") == "# Executed spec\n"
    actions = [e["action"] for e in runs.read_manifest("systems-thinking")["events"]]
    assert "job" in actions
    main(["-C", str(tmp_path), "daemon", "stop"])
