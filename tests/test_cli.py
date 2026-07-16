import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

import test_runs
from education_pipeline import ContentContract, RunStore
from education_pipeline.cli import main
from education_pipeline.privacy import canonical_profile_toml_bytes, profile_to_dict
from education_pipeline.profiles import load_learner_profile
from education_pipeline.workspace import ProfileStore


TOPIC_TOML = """\
schema_version = 1
id = "systems-thinking"
title = "Systems Thinking"
brief = "A public introduction to feedback loops."
goals = ["explain feedback loops"]
"""


PROFILE_TOML = """\
schema_version = 1
id = "visual-profile"
target_learner = "team cohort"
professional_experience = "early-career analysts"
learning_goals = ["understand systems thinking"]

[privacy]
private_by_default = true
include_in_published_output = false
publishable_summary = "Early-career team learning systems thinking."
"""


EDITED_PROFILE_TOML = """\
id = "visual-profile"
schema_version = 1
professional_experience = "principal planted actuary"
target_learner = "private planted seminar"
learning_goals = ["trace canonical edits"]

[privacy]
publishable_summary = "Synthetic public summary."
include_in_published_output = false
private_by_default = true
"""


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def _run(ws: Path, *args: str) -> int:
    return main(["--workspace", str(ws), *args])


def test_topic_import_and_list(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ws = tmp_path / "ws"
    topic_file = _write(tmp_path / "topic.toml", TOPIC_TOML)

    assert _run(ws, "topic", "import", str(topic_file)) == 0
    assert "systems-thinking" in capsys.readouterr().out

    assert _run(ws, "topic", "list") == 0
    assert "systems-thinking" in capsys.readouterr().out


def test_status_reports_next_action(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ws = tmp_path / "ws"
    _run(ws, "topic", "import", str(_write(tmp_path / "topic.toml", TOPIC_TOML)))
    _run(ws, "create", "systems-thinking", "--legacy-markdown")
    capsys.readouterr()

    assert _run(ws, "status", "systems-thinking") == 0
    out = capsys.readouterr().out
    assert "spec" in out
    assert "write_prompt" in out


def test_advance_writes_prompt(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ws = tmp_path / "ws"
    _run(ws, "topic", "import", str(_write(tmp_path / "topic.toml", TOPIC_TOML)))
    _run(ws, "create", "systems-thinking", "--legacy-markdown")
    capsys.readouterr()

    assert _run(ws, "advance", "systems-thinking") == 0
    assert "write_prompt" in capsys.readouterr().out
    assert (ws / "runs" / "systems-thinking" / "prompts" / "spec.prompt.md").exists()


def test_audit_command_prepares_prompt_and_prints_manual_and_provider_steps(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ws = tmp_path / "ws"
    topic_id = "systems-thinking"
    runs = test_runs._create_profiled_guide_run(ws, topic_id=topic_id)
    test_runs._drive_profiled_guide_to_finalize_ready(runs, topic_id)

    assert _run(ws, "audit", topic_id) == 0
    out = capsys.readouterr().out
    assert "prepared audit:" in out
    assert "responses/audit.response.json" in out
    assert f"run {topic_id} --stage audit" in out
    assert "--force" not in out

    runs.ingest_response(
        topic_id,
        "audit",
        test_runs._valid_personalization_audit_response(runs, topic_id),
    )
    runs.approve_stage(topic_id, "audit")
    assert _run(ws, "audit", topic_id) == 0
    rebuilt = capsys.readouterr().out
    assert f"run {topic_id} --stage audit --force" in rebuilt


def test_full_flow_drives_run_to_export(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    _run(ws, "topic", "import", str(_write(tmp_path / "topic.toml", TOPIC_TOML)))
    _run(ws, "create", "systems-thinking", "--legacy-markdown")
    runs = RunStore(ws)

    for _ in range(50):
        assert _run(ws, "advance", "systems-thinking") == 0
        action = runs.run_status("systems-thinking").next_action
        if action.action == "done":
            break
        if action.action == "save_response":
            runs.stage_paths("systems-thinking", action.stage).response_path.write_text(
                f"# {action.stage}\n", encoding="utf-8"
            )
        elif action.action == "approve":
            assert _run(ws, "approve", "systems-thinking", action.stage) == 0
    else:  # pragma: no cover
        raise AssertionError("CLI advance did not reach done")

    assert runs.is_finalized("systems-thinking")
    assert _run(ws, "export", "systems-thinking", "--format", "html") == 0
    assert _run(ws, "export", "systems-thinking", "--format", "markdown") == 0
    assert (ws / "runs" / "systems-thinking" / "final" / "guide.html").exists()
    assert (ws / "runs" / "systems-thinking" / "final" / "guide.bundle.md").exists()


def test_export_before_finalize_errors(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ws = tmp_path / "ws"
    _run(ws, "topic", "import", str(_write(tmp_path / "topic.toml", TOPIC_TOML)))
    capsys.readouterr()

    assert _run(ws, "export", "systems-thinking") == 1
    assert "not finalized" in capsys.readouterr().err


def test_unknown_topic_errors(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert _run(tmp_path / "ws", "advance", "missing-topic") == 1
    assert "error:" in capsys.readouterr().err


def test_profile_attach_threads_into_spec_prompt(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    _run(ws, "profile", "import", str(_write(tmp_path / "profile.toml", PROFILE_TOML)))
    _run(ws, "topic", "import", str(_write(tmp_path / "topic.toml", TOPIC_TOML)))
    _run(ws, "create", "systems-thinking", "--legacy-markdown")
    assert _run(ws, "profile", "attach", "visual-profile", "systems-thinking") == 0

    assert _run(ws, "advance", "systems-thinking") == 0
    prompt = (ws / "runs" / "systems-thinking" / "prompts" / "spec.prompt.md").read_text()
    assert "# Learner Profile Context" in prompt
    assert "- Professional experience: early-career analysts" in prompt


def _seed_profile(ws: Path, source: Path) -> None:
    profile = load_learner_profile(source)
    ProfileStore(ws).create_profile(profile.id, profile)


def test_profile_show_prints_only_canonical_toml(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ws = tmp_path / "ws"
    source = _write(tmp_path / "profile.toml", PROFILE_TOML)
    _seed_profile(ws, source)
    expected = ProfileStore(ws).read_profile_record("visual-profile").canonical_bytes.decode()

    assert _run(ws, "profile", "show", "visual-profile") == 0
    captured = capsys.readouterr()
    assert captured.out == expected
    assert captured.err == ""


def test_profile_show_preserves_canonical_stdout_bytes_under_non_utf8_encoding(
    tmp_path: Path,
) -> None:
    ws = tmp_path / "ws"
    source = _write(tmp_path / "profile.toml", PROFILE_TOML)
    _seed_profile(ws, source)
    expected = ProfileStore(ws).read_profile_record("visual-profile").canonical_bytes
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-16"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "education_pipeline",
            "--workspace",
            str(ws),
            "profile",
            "show",
            "visual-profile",
        ],
        cwd=Path(__file__).parent.parent,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout == expected
    assert result.stderr == b""


def test_profile_show_config_error_redacts_planted_values(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    ws = tmp_path / "ws"
    _seed_profile(ws, _write(tmp_path / "profile.toml", PROFILE_TOML))
    planted_values = ("771234567",)
    ProfileStore(ws).profile_path("visual-profile").write_text(
        PROFILE_TOML.replace("schema_version = 1", f"schema_version = {planted_values[0]}"),
        encoding="utf-8",
    )

    assert _run(ws, "profile", "show", "visual-profile") == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "error: profile command failed\n"
    assert all(value not in captured.err for value in planted_values)


def test_profile_edit_from_file_writes_canonical_bytes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ws = tmp_path / "ws"
    _seed_profile(ws, _write(tmp_path / "profile.toml", PROFILE_TOML))
    edited_path = _write(tmp_path / "edited.toml", EDITED_PROFILE_TOML)
    expected = canonical_profile_toml_bytes(load_learner_profile(edited_path))

    assert _run(
        ws, "profile", "edit", "visual-profile", "--from-file", str(edited_path)
    ) == 0
    assert capsys.readouterr().out == "updated profile visual-profile\n"
    assert (ws / "profiles" / "visual-profile.toml").read_bytes() == expected


def test_profile_edit_config_error_redacts_planted_values(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    planted_values = ("882345678",)
    edited_path = _write(
        tmp_path / "edited.toml",
        EDITED_PROFILE_TOML.replace(
            "schema_version = 1", f"schema_version = {planted_values[0]}"
        ),
    )

    assert _run(
        tmp_path / "ws",
        "profile",
        "edit",
        "visual-profile",
        "--from-file",
        str(edited_path),
    ) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "error: profile command failed\n"
    assert all(value not in captured.err for value in planted_values)


def test_profile_duplicate_replaces_embedded_id_and_writes_canonically(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ws = tmp_path / "ws"
    _seed_profile(ws, _write(tmp_path / "profile.toml", PROFILE_TOML))

    assert _run(ws, "profile", "duplicate", "visual-profile", "visual-copy") == 0
    assert capsys.readouterr().out == "duplicated profile visual-profile as visual-copy\n"

    store = ProfileStore(ws)
    source = profile_to_dict(store.read_profile_record("visual-profile").profile)
    duplicate = store.read_profile_record("visual-copy")
    assert duplicate.profile.id == "visual-copy"
    source["id"] = "visual-copy"
    assert profile_to_dict(duplicate.profile) == source
    assert (ws / "profiles" / "visual-copy.toml").read_bytes() == duplicate.canonical_bytes


def test_profile_duplicate_config_error_redacts_planted_values(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    ws = tmp_path / "ws"
    _seed_profile(ws, _write(tmp_path / "profile.toml", PROFILE_TOML))
    planted_values = ("993456789",)
    ProfileStore(ws).profile_path("visual-profile").write_text(
        PROFILE_TOML.replace("schema_version = 1", f"schema_version = {planted_values[0]}"),
        encoding="utf-8",
    )

    assert _run(
        ws, "profile", "duplicate", "visual-profile", "visual-copy"
    ) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "error: profile command failed\n"
    assert all(value not in captured.err for value in planted_values)


def test_profile_edit_stale_conflict_exits_2_with_only_fresh_hash(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ws = tmp_path / "ws"
    _seed_profile(ws, _write(tmp_path / "profile.toml", PROFILE_TOML))
    edited_path = _write(tmp_path / "edited.toml", EDITED_PROFILE_TOML)
    concurrent_path = _write(
        tmp_path / "concurrent.toml",
        EDITED_PROFILE_TOML.replace(
            "private planted seminar", "confidential planted cohort"
        ).replace("principal planted actuary", "secret planted engineer"),
    )
    concurrent = load_learner_profile(concurrent_path)
    real_update = ProfileStore.update_profile

    def update_after_concurrent_write(
        self: ProfileStore, profile_id: str, value, *, base_sha256: str
    ):
        real_update(self, profile_id, concurrent, base_sha256=base_sha256)
        return real_update(self, profile_id, value, base_sha256=base_sha256)

    monkeypatch.setattr(ProfileStore, "update_profile", update_after_concurrent_write)

    assert _run(
        ws, "profile", "edit", "visual-profile", "--from-file", str(edited_path)
    ) == 2
    captured = capsys.readouterr()
    fresh_hash = ProfileStore(ws).read_profile_record("visual-profile").content_sha256
    assert captured.out == ""
    assert fresh_hash in captured.err
    for private_value in (
        "private planted seminar",
        "principal planted actuary",
        "confidential planted cohort",
        "secret planted engineer",
    ):
        assert private_value not in captured.err


def test_profile_duplicate_existing_target_exits_2_without_private_values(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ws = tmp_path / "ws"
    _seed_profile(ws, _write(tmp_path / "profile.toml", PROFILE_TOML))
    store = ProfileStore(ws)
    existing = store.duplicate_profile("visual-profile", "visual-copy")
    capsys.readouterr()

    assert _run(ws, "profile", "duplicate", "visual-profile", "visual-copy") == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert existing.content_sha256 in captured.err
    assert "team cohort" not in captured.err
    assert "early-career analysts" not in captured.err


def test_profile_duplicate_missing_source_errors(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _run(tmp_path / "ws", "profile", "duplicate", "missing", "copy") == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "error:" in captured.err


def test_profile_edit_missing_from_file_errors(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ws = tmp_path / "ws"
    _seed_profile(ws, _write(tmp_path / "profile.toml", PROFILE_TOML))

    assert _run(
        ws,
        "profile",
        "edit",
        "visual-profile",
        "--from-file",
        str(tmp_path / "missing.toml"),
    ) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "error:" in captured.err


def _seed_topic_to_draft(ws: Path):
    """Advance a run so the next action is 'save_response' for the draft stage."""
    from education_pipeline import RunStore
    from education_pipeline.topics import load_topic
    from education_pipeline.workspace import TopicStore

    ws.mkdir(parents=True, exist_ok=True)
    topic_toml = ws / "_seed-topic.toml"
    _write(topic_toml, TOPIC_TOML)
    topic = load_topic(topic_toml)
    TopicStore(ws).import_topic(topic.id, topic_toml, overwrite=True)

    runs = RunStore(ws)
    runs.create_run("systems-thinking", content_contract=ContentContract.legacy_markdown())
    # spec -> approved
    runs.write_spec_prompt("systems-thinking", title="Systems Thinking")
    runs.response_path("systems-thinking", "spec").write_text("# Spec\n", encoding="utf-8")
    runs.approve_stage("systems-thinking", "spec")
    # outline -> approved
    runs.write_outline_prompt("systems-thinking")
    runs.response_path("systems-thinking", "outline").write_text("# Outline\n", encoding="utf-8")
    runs.approve_stage("systems-thinking", "outline")
    # draft prompt written, no response yet -> next action is save_response(draft)
    runs.write_draft_prompt("systems-thinking")


def test_daemon_status_reports_stopped(tmp_path, capsys):
    assert _run(tmp_path, "daemon", "status") == 0
    assert "stopped" in capsys.readouterr().out.lower()


def test_run_wait_executes_and_lands_response(tmp_path, monkeypatch):
    import sys

    from education_pipeline.providers import Invocation, ProviderResponse, register_runner

    class FakeRunner:
        provider_id = "fake"
        executable = True

        def is_available(self):
            return True

        def build_invocation(self, model, plan, prompt_path):
            fake = Path(__file__).parent / "fake_provider.py"
            return Invocation(argv=[sys.executable, str(fake)])

        def parse_response(self, stdout):
            return ProviderResponse(text=stdout, metadata={})

    register_runner(FakeRunner())
    monkeypatch.setenv("FAKE_STDOUT", "# Generated draft\n")

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
    import threading

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

    # workspace config points the plan's draft stage at the fake provider
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "model-catalog.toml").write_text(
        '[[providers]]\nid = "fake"\n[[providers.models]]\nid = "m"\n', encoding="utf-8"
    )
    (cfg / "model-plan.toml").write_text(
        'provider = "fake"\n[stages.draft]\nmodel = "m"\n', encoding="utf-8"
    )
    _seed_topic_to_draft(tmp_path)
    code = _run(tmp_path, "run", "systems-thinking", "--wait")
    assert code == 0
    from education_pipeline import RunStore

    assert RunStore(tmp_path).response_path("systems-thinking", "draft").read_text(
        encoding="utf-8"
    ) == "# Generated draft\n"
    _run(tmp_path, "daemon", "stop")


def test_run_refuses_when_next_action_is_approval(tmp_path, capsys):
    from education_pipeline import RunStore
    from education_pipeline.topics import load_topic
    from education_pipeline.workspace import TopicStore

    topic_toml = tmp_path / "_seed-topic.toml"
    _write(topic_toml, TOPIC_TOML)
    topic = load_topic(topic_toml)
    TopicStore(tmp_path).import_topic(topic.id, topic_toml, overwrite=True)

    runs = RunStore(tmp_path)
    runs.create_run("systems-thinking", content_contract=ContentContract.legacy_markdown())
    runs.write_spec_prompt("systems-thinking", title="Systems Thinking")
    runs.response_path("systems-thinking", "spec").write_text("# Spec\n", encoding="utf-8")
    runs.approve_stage("systems-thinking", "spec")
    runs.write_outline_prompt("systems-thinking")
    runs.response_path("systems-thinking", "outline").write_text("# Outline\n", encoding="utf-8")
    # next action is 'approve' outline, not 'save_response'
    code = _run(tmp_path, "run", "systems-thinking")
    assert code == 1
    _run(tmp_path, "daemon", "stop")


def test_create_command_defaults_to_interactive_guide(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ws = tmp_path / "ws"
    assert _run(ws, "create", "systems-thinking") == 0
    out = capsys.readouterr().out
    assert "created run systems-thinking (interactive_guide 1.0)" in out
    runs = RunStore(ws)
    assert runs.content_contract("systems-thinking") == ContentContract.interactive_guide_v1()
    assert runs.read_manifest("systems-thinking")["content_contract"] == {
        "kind": "interactive_guide",
        "schema_version": "1.0",
    }


def test_create_command_legacy_markdown(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ws = tmp_path / "ws"
    assert _run(ws, "create", "systems-thinking", "--legacy-markdown") == 0
    out = capsys.readouterr().out
    assert "created run systems-thinking (legacy_markdown)" in out
    runs = RunStore(ws)
    assert runs.content_contract("systems-thinking") == ContentContract.legacy_markdown()
    assert runs.read_manifest("systems-thinking")["content_contract"] == {
        "kind": "legacy_markdown"
    }


def test_create_command_conflicting_contract_exits_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ws = tmp_path / "ws"
    assert _run(ws, "create", "systems-thinking") == 0
    capsys.readouterr()
    assert _run(ws, "create", "systems-thinking", "--legacy-markdown") == 1
    err = capsys.readouterr().err
    assert "immutable content contract" in err


@pytest.fixture
def guide_v1_workspace(tmp_path: Path):
    """A guide-v1 run driven to an approved repair with a current, open final report."""

    root = tmp_path / "ws"
    topic_id = "systems-thinking"
    runs = test_runs._create_guide_run(root, topic_id)
    test_runs._drive_guide_to_finalize_ready(runs, topic_id)
    return root, topic_id


@pytest.fixture
def workspace_with_blockers(tmp_path: Path):
    """A guide-v1 run with an approved, validated draft carrying blocking findings."""

    root = tmp_path / "ws"
    topic_id = "systems-thinking"
    runs = test_runs._create_guide_run(root, topic_id)
    leak_json = test_runs._prompt_leak_guide_json()
    test_runs._drive_guide_to_draft_approved(runs, topic_id, draft_body=leak_json)
    runs.validate_run(topic_id, "draft")
    return root, topic_id


@pytest.fixture
def exported_guide_workspace(tmp_path: Path):
    """A guide-v1 run finalized and exported to HTML, with its sidecar report."""

    root = tmp_path / "ws"
    topic_id = "systems-thinking"
    runs = test_runs._create_guide_run(root, topic_id)
    test_runs._drive_guide_to_finalize_ready(runs, topic_id)
    runs.finalize_run(topic_id)
    runs.export_run(topic_id, format="html")
    return root, topic_id


def _mismatched_minutes_guide_json(base: str) -> str:
    """Mutate a guide-fixture JSON body so course/module minutes disagree.

    Produces a ``time.module_total_mismatch`` finding, whose rule maps to the
    "outline" stage -- distinct from both the draft-phase default stage
    ("draft") and the finding-stage default ("draft"), so tests built on it
    can only pass if real rule-to-stage attribution is flowing end to end.
    """

    data = json.loads(base)
    data["course"]["estimated_minutes"] += 5
    return json.dumps(data)


@pytest.fixture
def workspace_with_mixed_findings(tmp_path: Path):
    """A validated draft carrying both a blocking (draft-stage) finding and a
    non-blocking (outline-stage) finding -- lets tests assert real stage
    attribution and real --blocking filtering, not fixture coincidence."""

    root = tmp_path / "ws"
    topic_id = "systems-thinking"
    runs = test_runs._create_guide_run(root, topic_id)
    body = _mismatched_minutes_guide_json(test_runs._prompt_leak_guide_json())
    test_runs._drive_guide_to_draft_approved(runs, topic_id, draft_body=body)
    runs.validate_run(topic_id, "draft")
    return root, topic_id


@pytest.fixture
def workspace_with_stale_draft_report(tmp_path: Path):
    """A draft validated once, then edited without revalidating -- the
    on-disk draft report is now stale relative to the approved draft."""

    root = tmp_path / "ws"
    topic_id = "systems-thinking"
    runs = test_runs._create_guide_run(root, topic_id)
    test_runs._drive_guide_to_draft_approved(runs, topic_id)
    runs.validate_run(topic_id, "draft")

    draft_paths = runs.stage_paths(topic_id, "draft")
    base_sha = hashlib.sha256(draft_paths.response_path.read_bytes()).hexdigest()
    edited = test_runs._edit_course_description(
        draft_paths.response_path.read_text(encoding="utf-8"),
        "Edited after validation so the draft report goes stale.",
    )
    runs.edit_response(topic_id, "draft", edited, base_sha256=base_sha)
    runs.approve_stage(topic_id, "draft", overwrite=True)
    assert runs.report_state(topic_id, "draft") == "stale"
    return root, topic_id


@pytest.fixture
def workspace_with_stale_final_report(tmp_path: Path):
    """A repair validated once, then edited without revalidating -- the
    on-disk final report is now stale relative to the approved repair."""

    root = tmp_path / "ws"
    topic_id = "systems-thinking"
    runs = test_runs._create_guide_run(root, topic_id)
    test_runs._drive_guide_to_finalize_ready(runs, topic_id)

    repair_paths = runs.stage_paths(topic_id, "repair")
    base_sha = hashlib.sha256(repair_paths.response_path.read_bytes()).hexdigest()
    edited = test_runs._edit_course_description(
        repair_paths.response_path.read_text(encoding="utf-8"),
        "Edited after final validation so the final report goes stale.",
    )
    runs.edit_response(topic_id, "repair", edited, base_sha256=base_sha)
    runs.approve_stage(topic_id, "repair", overwrite=True)
    assert runs.report_state(topic_id, "final") == "stale"
    return root, topic_id


def test_validate_command_exit_codes_track_the_gate(guide_v1_workspace, capsys):
    root, topic_id = guide_v1_workspace
    assert main(["--workspace", str(root), "validate", topic_id, "--phase", "final"]) == 0


def test_validate_command_exit_code_is_1_when_gate_is_blocked(workspace_with_blockers, capsys):
    root, topic_id = workspace_with_blockers
    assert main(["--workspace", str(root), "validate", topic_id, "--phase", "draft"]) == 1
    out = capsys.readouterr().out
    assert "gate blocked" in out


def test_validate_command_nonexistent_topic_exits_2(tmp_path: Path, capsys) -> None:
    """A typo'd/nonexistent topic id is a usage/config error (exit 2), not a
    blocked gate (exit 1) -- scripts must be able to tell "no such run" apart
    from "gate blocked" by exit code alone."""

    root = tmp_path / "ws"
    exit_code = main(["--workspace", str(root), "validate", "no-such-topic", "--phase", "draft"])
    assert exit_code == 2
    err = capsys.readouterr().err
    assert "error:" in err


def test_findings_command_lists_stage_attributed_findings(workspace_with_mixed_findings, capsys):
    root, topic_id = workspace_with_mixed_findings
    assert main(["--workspace", str(root), "findings", topic_id, "--phase", "draft"]) == 0
    out = capsys.readouterr().out
    # The rule->stage map attributes time.module_total_mismatch to "outline",
    # not the draft-phase default ("draft"); this line can only appear if the
    # CLI is threading the finding's real stage through, not the fallback.
    assert "\toutline\t" in out
    assert "time.module_total_mismatch" in out


def test_findings_command_blocking_filter(workspace_with_mixed_findings, capsys):
    root, topic_id = workspace_with_mixed_findings
    assert main(["--workspace", str(root), "findings", topic_id, "--phase", "draft"]) == 0
    unfiltered = capsys.readouterr().out.strip().splitlines()

    assert (
        main(["--workspace", str(root), "findings", topic_id, "--phase", "draft", "--blocking"])
        == 0
    )
    filtered = capsys.readouterr().out.strip().splitlines()

    assert len(filtered) < len(unfiltered)
    assert all("content.prompt_leak" in line for line in filtered)
    assert not any("time.module_total_mismatch" in line for line in filtered)


def test_findings_command_warns_on_stale_report(workspace_with_stale_draft_report, capsys):
    root, topic_id = workspace_with_stale_draft_report
    assert main(["--workspace", str(root), "findings", topic_id, "--phase", "draft"]) == 0
    err = capsys.readouterr().err
    assert "stale" in err.lower()


def test_findings_command_falls_back_to_repair_stage_for_pre_v2_finding(
    guide_v1_workspace, capsys
):
    """A pre-v2 report on disk has no ``stage`` key on its findings (that field
    was added later). The CLI must fall back to the phase-derived stage
    ("final" phase -> "repair", matching the web's findingHref convention in
    d0a291f) rather than a hardcoded "draft" -- reverting to a hardcoded
    fallback would make this test fail while every other findings test (whose
    fixtures always carry ``stage`` on disk) stays green."""

    root, topic_id = guide_v1_workspace
    runs = RunStore(root)
    report_path = runs.final_report_path(topic_id)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    stage_less_finding = {
        "id": "pre-v2-finding",
        "rule_id": "content.pre_v2_example",
        "severity": "warning",
        "blocking": False,
        "waivable": True,
        "path": "modules[0]",
        "message": "pre-v2 report with no stage on this finding",
        "remediation": "n/a",
        # no "stage" key -- this is what a pre-v2 report looks like on disk.
    }
    report["findings"] = [stage_less_finding]
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    assert main(["--workspace", str(root), "findings", topic_id, "--phase", "final"]) == 0
    out = capsys.readouterr().out
    assert "\trepair\t" in out
    assert "\tdraft\t" not in out


def test_findings_command_no_report_exits_2(tmp_path: Path, capsys) -> None:
    """No validation report has been written yet: this is a usage/config
    error (exit 2), not a blocked gate (exit 1)."""

    root = tmp_path / "ws"
    topic_id = "systems-thinking"
    test_runs._create_guide_run(root, topic_id)

    exit_code = main(["--workspace", str(root), "findings", topic_id, "--phase", "draft"])
    assert exit_code == 2
    err = capsys.readouterr().err
    assert "error:" in err


def _approve_warning_audit(root: Path, topic_id: str) -> tuple[RunStore, dict]:
    runs = RunStore(root)
    runs.prepare_personalization_audit(topic_id)
    response = json.loads(test_runs._valid_personalization_audit_response(runs, topic_id))
    response["goals"][0]["verdict"] = "weak"
    runs.ingest_response(topic_id, "audit", json.dumps(response))
    runs.approve_stage(topic_id, "audit")
    finding = next(f for f in runs.combined_findings(topic_id) if f.stage == "audit")
    return runs, finding.to_dict()


def test_cli_findings_report_and_waive_use_safe_combined_audit_findings(
    tmp_path: Path, capsys
):
    root = tmp_path / "ws"
    topic_id = "systems-thinking"
    runs = test_runs._create_profiled_guide_run(root, topic_id=topic_id)
    test_runs._drive_profiled_guide_to_finalize_ready(runs, topic_id)
    runs, audit_finding = _approve_warning_audit(root, topic_id)

    assert main(["--workspace", str(root), "findings", topic_id]) == 0
    findings_out = capsys.readouterr().out
    assert "\taudit\t" in findings_out
    assert audit_finding["rule_id"] in findings_out

    assert main(["--workspace", str(root), "report", topic_id]) == 0
    report = json.loads(capsys.readouterr().out)
    projected = next(
        finding for finding in report["findings"] if finding["stage"] == "audit"
    )
    assert projected["source_stage"] == "repair"

    assert main(
        [
            "--workspace",
            str(root),
            "waive",
            topic_id,
            audit_finding["id"],
            "--reason",
            "Attempted audit waiver.",
        ]
    ) == 2
    assert "not waivable" in capsys.readouterr().err
    assert runs.load_waiver_set(topic_id) is None


def test_report_command_prints_sidecar_after_export(exported_guide_workspace, capsys):
    root, topic_id = exported_guide_workspace
    assert main(["--workspace", str(root), "report", topic_id]) == 0
    assert '"quality_report_schema_version"' in capsys.readouterr().out


def test_report_prints_persisted_not_run_sidecar_unchanged_when_live_audit_is_current(
    tmp_path: Path, capsys
):
    root = tmp_path / "ws"
    topic_id = "systems-thinking"
    runs = test_runs._create_profiled_guide_run(root, topic_id=topic_id)
    test_runs._drive_profiled_guide_to_finalize_ready(runs, topic_id)
    runs.finalize_run(topic_id)
    runs.export_run(topic_id, format="html")
    persisted = runs.export_report_path(topic_id).read_text(encoding="utf-8")
    assert json.loads(persisted)["audit"]["state"] == "not_run"

    _approve_warning_audit(root, topic_id)
    assert runs.export_state(topic_id) == "stale"

    assert main(["--workspace", str(root), "report", topic_id]) == 0
    captured = capsys.readouterr()
    assert captured.out == persisted
    assert "export" in captured.err.lower()
    assert "stale" in captured.err.lower()


def test_report_prints_persisted_current_sidecar_unchanged_when_live_audit_is_stale(
    tmp_path: Path, capsys
):
    root = tmp_path / "ws"
    topic_id = "systems-thinking"
    runs = test_runs._create_profiled_guide_run(root, topic_id=topic_id)
    test_runs._drive_profiled_guide_to_finalize_ready(runs, topic_id)
    _approve_warning_audit(root, topic_id)
    runs.finalize_run(topic_id)
    runs.export_run(topic_id, format="html")
    persisted = runs.export_report_path(topic_id).read_text(encoding="utf-8")
    assert json.loads(persisted)["audit"]["state"] == "current"

    projection = runs.audit_projection_path(topic_id)
    projection.write_bytes(projection.read_bytes() + b"\n")
    assert runs.audit_state(topic_id) == "stale"
    assert runs.export_state(topic_id) == "stale"

    assert main(["--workspace", str(root), "report", topic_id]) == 0
    captured = capsys.readouterr()
    assert captured.out == persisted
    assert "export" in captured.err.lower()
    assert "stale" in captured.err.lower()


def test_report_command_prints_final_report_when_not_exported(guide_v1_workspace, capsys):
    """No export sidecar exists yet -- falls back to the raw final validation report."""

    root, topic_id = guide_v1_workspace
    assert main(["--workspace", str(root), "report", topic_id]) == 0
    out = capsys.readouterr().out
    assert '"phase": "final"' in out
    assert '"quality_report_schema_version"' not in out


def test_report_command_warns_on_stale_report(workspace_with_stale_final_report, capsys):
    root, topic_id = workspace_with_stale_final_report
    main(["--workspace", str(root), "report", topic_id])
    err = capsys.readouterr().err
    assert "stale" in err.lower()


def test_report_command_nonexistent_topic_exits_2(tmp_path: Path, capsys) -> None:
    """A typo'd/nonexistent topic id is a usage/config error (exit 2), not a
    blocked gate (exit 1)."""

    root = tmp_path / "ws"
    exit_code = main(["--workspace", str(root), "report", "no-such-topic"])
    assert exit_code == 2
    err = capsys.readouterr().err
    assert "error:" in err


def _blocking_finding_id(root, topic_id, phase="draft"):
    report = json.loads(
        RunStore(root).draft_report_path(topic_id).read_text(encoding="utf-8")
        if phase == "draft"
        else RunStore(root).final_report_path(topic_id).read_text(encoding="utf-8")
    )
    return next(f["id"] for f in report["findings"] if f["blocking"] and f["waivable"])


def test_waive_command_opens_the_gate(workspace_with_blockers, capsys):
    """The waive command's whole point is flipping a blocked gate open --
    not just writing a waivers file. Assert the gate transition via a
    follow-up `validate` run, not just the waive command's own exit code,
    so this test fails if the gate math regresses even though `waive`
    itself still exits 0."""

    root, topic_id = workspace_with_blockers
    finding_id = _blocking_finding_id(root, topic_id)

    assert main(["--workspace", str(root), "validate", topic_id, "--phase", "draft"]) == 1
    capsys.readouterr()

    assert (
        main(
            [
                "--workspace",
                str(root),
                "waive",
                topic_id,
                finding_id,
                "--reason",
                "Intentional example text.",
                "--phase",
                "draft",
            ]
        )
        == 0
    )

    assert main(["--workspace", str(root), "validate", topic_id, "--phase", "draft"]) == 0


def test_waive_command_empty_reason_exits_2(workspace_with_blockers, capsys):
    root, topic_id = workspace_with_blockers
    finding_id = _blocking_finding_id(root, topic_id)

    exit_code = main(
        [
            "--workspace",
            str(root),
            "waive",
            topic_id,
            finding_id,
            "--reason",
            "   ",
            "--phase",
            "draft",
        ]
    )
    assert exit_code == 2
    err = capsys.readouterr().err
    assert "error:" in err

    # The gate must remain blocked: no waiver should have been recorded.
    assert main(["--workspace", str(root), "validate", topic_id, "--phase", "draft"]) == 1


def test_waive_command_non_waivable_finding_exits_2(tmp_path, capsys):
    root = tmp_path / "ws"
    topic_id = "systems-thinking"
    runs = test_runs._create_guide_run(root, topic_id)
    bad = json.loads(test_runs.GUIDE_FIXTURE)
    bad["schema_version"] = "2.0"
    test_runs._drive_guide_to_draft_approved(runs, topic_id, draft_body=json.dumps(bad))
    runs.validate_run(topic_id, "draft")
    report = json.loads(runs.draft_report_path(topic_id).read_text(encoding="utf-8"))
    finding = next(f for f in report["findings"] if f["blocking"] and not f["waivable"])

    exit_code = main(
        [
            "--workspace",
            str(root),
            "waive",
            topic_id,
            finding["id"],
            "--reason",
            "Please let this through.",
            "--phase",
            "draft",
        ]
    )
    assert exit_code == 2


def test_unwaive_command_closes_the_gate_again(workspace_with_blockers, capsys):
    """The inverse contract: unwaive must flip a previously-opened gate back
    closed. Only checking unwaive's own exit code (which is 0 either way in
    a no-waiver-existed case) would not prove the removal actually mutated
    the waiver set, so this asserts the gate via a follow-up `validate`."""

    root, topic_id = workspace_with_blockers
    finding_id = _blocking_finding_id(root, topic_id)

    assert (
        main(
            [
                "--workspace",
                str(root),
                "waive",
                topic_id,
                finding_id,
                "--reason",
                "Intentional example text.",
                "--phase",
                "draft",
            ]
        )
        == 0
    )
    assert main(["--workspace", str(root), "validate", topic_id, "--phase", "draft"]) == 0
    capsys.readouterr()

    assert (
        main(
            ["--workspace", str(root), "unwaive", topic_id, finding_id, "--phase", "draft"]
        )
        == 0
    )

    assert main(["--workspace", str(root), "validate", topic_id, "--phase", "draft"]) == 1


def test_daemon_status_prints_cockpit_url(tmp_path, capsys, monkeypatch):
    from education_pipeline import cli

    monkeypatch.setattr(
        cli,
        "daemon_status",
        lambda root: {
            "running": True,
            "pid": 123,
            "port": 4242,
            "version": "0.1.0",
            "version_mismatch": False,
        },
    )
    assert _run(tmp_path, "daemon", "status") == 0
    out = capsys.readouterr().out
    assert "http://127.0.0.1:4242/" in out


# ---------------------------------------------------------------------------
# workspace check (first-run milestone, spec §3.3)


def test_workspace_check_reports_findings_and_exits_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = _run(tmp_path, "workspace", "check")
    out = capsys.readouterr().out
    assert code == 1
    assert out.count("missing_subdir") == 3
    assert "blocking" in out


def test_workspace_check_ok_exits_0(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    for subdir in ("runs", "topics", "profiles"):
        (tmp_path / subdir).mkdir()
    code = _run(tmp_path, "workspace", "check")
    out = capsys.readouterr().out
    assert code == 0
    assert "ok" in out.lower()


def test_workspace_check_fix_scaffolds_and_exits_0(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = _run(tmp_path, "workspace", "check", "--fix")
    capsys.readouterr()
    assert code == 0
    for subdir in ("runs", "topics", "profiles"):
        assert (tmp_path / subdir).is_dir()


def test_workspace_check_fix_refuses_unrecognized_layout(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "photos").mkdir()
    code = _run(tmp_path, "workspace", "check", "--fix")
    out = capsys.readouterr().out
    assert code == 1
    assert "unrecognized_layout" in out
    assert not (tmp_path / "runs").exists()


def test_workspace_check_warning_only_exits_0(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from education_pipeline.daemon import lifecycle

    for subdir in ("runs", "topics", "profiles"):
        (tmp_path / subdir).mkdir()
    lifecycle.write_discovery(tmp_path, pid=999_999_999, port=1, token="t", version="0")
    code = _run(tmp_path, "workspace", "check")
    out = capsys.readouterr().out
    assert code == 0
    assert "stale_daemon_record" in out


def test_daemon_error_prints_catalog_remediation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from education_pipeline import cli
    from education_pipeline.client import DaemonError

    def _raise(*args, **kwargs):
        raise DaemonError("job j1 is running for topic 't'", code="job_conflict")

    monkeypatch.setattr(cli, "ensure_daemon", _raise)
    code = _run(tmp_path, "run", "some-topic")
    err = capsys.readouterr().err
    assert code == 1
    assert "job j1 is running" in err
    assert "Wait for the running job" in err  # catalog remediation line


def test_daemon_error_without_code_prints_no_remediation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from education_pipeline import cli
    from education_pipeline.client import DaemonError

    def _raise(*args, **kwargs):
        raise DaemonError("plain failure")

    monkeypatch.setattr(cli, "ensure_daemon", _raise)
    code = _run(tmp_path, "run", "some-topic")
    err = capsys.readouterr().err
    assert code == 1
    assert "plain failure" in err
    assert "fix:" not in err
